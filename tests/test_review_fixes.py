"""Regression tests for the v0.2.2 review-fix bundle.

Each test pins a behavior surfaced by the code review (B2/B4/B5/B6 from
the review priority list). The fixes themselves live in extractor.py,
generator.py, comparator.py, validator.py, render.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from polaris_mcfg.comparator import diff_specs
from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.schema import (
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    codepoint_to_id,
)
from polaris_mcfg.validator import validate_font

from .conftest import make_test_font


# ---------- B2: --missing-glyph notdef actually remaps cmap ----------

def test_missing_glyph_notdef_routes_codepoints_to_notdef(tmp_font_dir: Path):
    """Codepoints in source spec that don't exist in design font should be
    cmap-remapped to a notdef-equivalent stub glyph when --missing-glyph
    notdef is set. (cmap-to-.notdef directly is dropped by OpenType
    convention, so a same-advance stub stands in.)
    """
    from polaris_mcfg.generator import _NOTDEF_STUB_NAME
    # Source has C; design only has A.
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 700, "A": 600, "C": 999},
                         cmap={0x0041: "A", 0x0043: "C"})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 200, "A": 600},
                         cmap={0x0041: "A"})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, missing_glyph="notdef")

    f = TTFont(str(out))
    # .notdef advance copied from source.
    assert f["hmtx"].metrics[".notdef"][0] == 700
    # Stub exists with the same advance.
    assert _NOTDEF_STUB_NAME in f.getGlyphOrder()
    assert f["hmtx"].metrics[_NOTDEF_STUB_NAME][0] == 700
    # C codepoint now routed to the stub in every Unicode subtable.
    routed = any(
        sub.cmap.get(0x0043) == _NOTDEF_STUB_NAME
        for sub in f["cmap"].tables if sub.isUnicode()
    )
    assert routed, "missing codepoint should be remapped to the notdef stub"
    f.close()
    assert stats["advance"]["missing"] >= 1
    assert stats["advance"]["notdefRemapped"] >= 1


def test_missing_glyph_skip_does_not_touch_cmap(tmp_font_dir: Path):
    """skip mode is the conservative default — design cmap stays intact and
    no synthetic stub glyphs are inserted. (.notdef's advance still gets
    overridden because the source spec carries it explicitly via
    ``glyph#.notdef`` in the per-glyph loop; that's orthogonal to the
    cmap-routing behavior gated by missing_mode.)
    """
    from polaris_mcfg.generator import _NOTDEF_STUB_NAME
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 700, "A": 600, "C": 999},
                         cmap={0x0041: "A", 0x0043: "C"})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 200, "A": 600},
                         cmap={0x0041: "A"})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, missing_glyph="skip")
    f = TTFont(str(out))
    has_C = any(0x0043 in sub.cmap for sub in f["cmap"].tables if sub.isUnicode())
    assert not has_C, "skip mode must not add cmap entries for missing glyphs"
    # No synthetic notdef stub in skip mode.
    assert _NOTDEF_STUB_NAME not in f.getGlyphOrder()
    f.close()


# ---------- B4: kerning diff honors --threshold ----------

def test_kerning_diff_below_threshold_treated_as_match():
    a = MetricsSpec(
        glyphs={"U+0041": GlyphMetric(advanceWidth=600)},
        kerning=[KerningPair(left="U+0041", right="U+0042", value=-50)],
    )
    b = MetricsSpec(
        glyphs={"U+0041": GlyphMetric(advanceWidth=600)},
        kerning=[KerningPair(left="U+0041", right="U+0042", value=-49)],
    )
    strict = diff_specs(a, b, threshold=0)
    loose = diff_specs(a, b, threshold=1)
    assert strict.kerning_diff is not None and strict.kerning_diff.common
    assert loose.kerning_diff is not None and not loose.kerning_diff.common


# ---------- B5: validator's LSB check tolerates partial None ----------

def test_validator_lsb_check_skips_when_lsb_absent_on_one_side(tmp_font_dir: Path):
    """If only one spec carries LSBs, validator must skip the LSB check
    rather than raise on None comparisons.
    """
    f = make_test_font(tmp_font_dir / "t.ttf")
    actual_with_lsb = extract_metrics(f, include_lsb=True, deterministic=True)
    ref_no_lsb = extract_metrics(f, include_lsb=False, deterministic=True)

    # Manually persist ref to JSON and validate against it. validator should
    # NOT crash and lsb_match should be omitted (not failed).
    ref_path = tmp_font_dir / "ref.json"
    ref_path.write_text(ref_no_lsb.to_json(), encoding="utf-8")
    report = validate_font(f, ref_path)
    names = {c.name for c in report.checks}
    # No LSB on ref → check is omitted (returns None internally).
    assert "lsb_match" not in names
    # And the report still renders without errors.
    from polaris_mcfg.validator import format_text
    assert "PASS" in format_text(report)


# ---------- B6: validator accepts WOFF2 reference fonts ----------

def test_validator_rendering_check_works_with_woff2_reference(tmp_font_dir: Path):
    """`--against` may now point to a .woff2 file; HarfBuzz handles all three
    of TTF/OTF/WOFF2 transparently."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 800, "B": 850, "space": 250})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    spec = extract_metrics(src, deterministic=True)

    # Build a WOFF2 of the reference font.
    src_wf = tmp_font_dir / "src.woff2"
    f = TTFont(str(src))
    f.flavor = "woff2"
    f.save(str(src_wf))
    f.close()

    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance"))
    report = validate_font(out, src_wf, render_texts=["A B", "BA"],
                           render_tolerance_pct=0.1)
    names = {c.name for c in report.checks}
    assert "rendering_match" in names, \
        "WOFF2 reference must trigger rendering check (was previously skipped)"
    rc = next(c for c in report.checks if c.name == "rendering_match")
    assert rc.passed
