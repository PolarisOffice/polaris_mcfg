"""v2 — `--apply gsub` shaped-advance override tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.schema import (
    MetricsSpec,
    ShapedAdvanceOverride,
    codepoint_to_id,
)

from .conftest import make_test_font


def _shape_adv(font_path: Path, text: str, *,
               script: str | None = None, lang: str | None = None) -> int:
    import uharfbuzz as hb
    blob = hb.Blob.from_file_path(str(font_path))
    face = hb.Face(blob); fnt = hb.Font(face)
    buf = hb.Buffer(); buf.add_str(text)
    if script:
        buf.script = script
        buf.language = lang or "dflt"
        buf.direction = "ltr"
    else:
        buf.guess_segment_properties()
    hb.shape(fnt, buf)
    return sum(p.x_advance for p in buf.glyph_positions)


def test_extract_gsub_detects_shape_induced_advance_change(tmp_font_dir: Path):
    """Build a tiny font with a Korean wider-space-like substitution; extractor
    should detect that ``space`` shapes wider under (hang, KOR)."""
    src = make_test_font(
        tmp_font_dir / "src.ttf",
        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250, "space.kor": 320},
        cmap={0x0041: "A", 0x0042: "B", 0x0020: "space"},
    )
    fea = """
    languagesystem DFLT dflt;
    languagesystem hang KOR;
    feature locl {
      script hang; language KOR exclude_dflt;
      sub space by space.kor;
    } locl;
    """
    f = TTFont(str(src)); addOpenTypeFeaturesFromString(f, fea); f.save(str(src))

    spec = extract_metrics(src, include_gsub=True, deterministic=True,
                           gsub_contexts=(("hang", "KOR"),))
    assert spec.shaped_advances is not None
    space_overrides = [ov for ov in spec.shaped_advances
                       if ov.codepoint == codepoint_to_id(0x20)]
    assert space_overrides
    ov = space_overrides[0]
    assert ov.script == "hang"
    assert ov.language == "KOR"
    assert ov.advance == 320


def test_apply_gsub_inserts_locl_substitution(tmp_font_dir: Path):
    """Generator with `--apply gsub` should make the result font shape the
    same as the source under the override's (script, lang)."""
    src = make_test_font(
        tmp_font_dir / "src.ttf",
        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250, "space.kor": 320},
        cmap={0x0041: "A", 0x0042: "B", 0x0020: "space"},
    )
    fea = """
    languagesystem DFLT dflt;
    languagesystem hang KOR;
    feature locl {
      script hang; language KOR exclude_dflt;
      sub space by space.kor;
    } locl;
    """
    f = TTFont(str(src)); addOpenTypeFeaturesFromString(f, fea); f.save(str(src))

    dsn = make_test_font(
        tmp_font_dir / "dsn.ttf",
        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250},
        cmap={0x0041: "A", 0x0042: "B", 0x0020: "space"},
    )
    spec = extract_metrics(src, include_gsub=True, deterministic=True,
                           gsub_contexts=(("hang", "KOR"),))
    assert spec.shaped_advances
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, apply=("global", "advance", "gsub"))
    assert stats["gsub"]["applied"] >= 1

    # Default shaping: original space width (250)
    assert _shape_adv(out, " ") == 250
    # Korean shaping: substituted to space.kor (320)
    assert _shape_adv(out, " ", script="hang", lang="KOR") == 320


def test_gsub_skipped_for_codepoints_not_in_design(tmp_font_dir: Path):
    """Override entries for codepoints absent from design font are skipped."""
    src = make_test_font(tmp_font_dir / "src.ttf")
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, deterministic=True)
    spec.shaped_advances = [ShapedAdvanceOverride(
        codepoint="U+2764",  # ❤ — not in design's cmap
        script="latn", language="ENG", advance=500,
    )]
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, apply=("global", "advance", "gsub"))
    assert stats["gsub"]["applied"] == 0
    assert stats["gsub"]["skipped"] == 1


def test_schema_round_trip_includes_shaped_advances():
    spec = MetricsSpec()
    spec.shaped_advances = [
        ShapedAdvanceOverride(codepoint="U+0020", script="hang", language="KOR", advance=280),
        ShapedAdvanceOverride(codepoint="U+0020", script="hani", language="ZHS", advance=300),
    ]
    s = spec.to_json()
    restored = MetricsSpec.from_json(s)
    assert restored.shaped_advances is not None
    assert len(restored.shaped_advances) == 2
    assert restored.shaped_advances[0].advance == 280
