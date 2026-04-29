"""Regression tests for the codex code-review issues addressed in v0.2.4.

Each test pins a behavior surfaced in the review:

- P1: GSUB override with a *visible* source glyph must NOT make the
  glyph invisible. The stub now copies the design font's outline.
- P2: kerning values are in source-font units and must be UPM-scaled
  when the design has a different UPM (otherwise visibly over-/under-kerned).
- P2: PairPos lookups referenced from non-``kern`` features (or from
  contextual lookups via SubstLookupRecord) must not be silently dropped
  when we inject our own kern lookup.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.schema import (
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    ShapedAdvanceOverride,
)

from .conftest import make_test_font


# ---------- P1: GSUB stub preserves design outline ----------

def test_gsub_stub_clones_design_outline_for_visible_glyphs(tmp_font_dir: Path):
    """A visible glyph (non-empty contour) under a script-level advance
    override must keep its visible outline after `--apply gsub`.
    """
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})

    spec = extract_metrics(src, deterministic=True)
    # Manually inject a visible-glyph override: U+0041 ('A') with override
    # advance under (hang, KOR). The conftest fixture's 'A' glyph has 4
    # contour points (a box).
    spec.shaped_advances = [ShapedAdvanceOverride(
        codepoint="U+0041", script="hang", language="KOR", advance=900,
    )]

    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "gsub"))

    f = TTFont(str(out))
    # Find the stub glyph
    stub_name = "polaris.0041.hang_KOR"
    assert stub_name in f.getGlyphOrder()

    stub_glyph = f["glyf"][stub_name]
    # Critical check: the stub must NOT be an empty-outline placeholder.
    # The design's 'A' glyph has 1 contour with 4 points (a box rectangle).
    assert stub_glyph.numberOfContours > 0, \
        "stub must clone the design's visible outline, not be empty"
    assert hasattr(stub_glyph, "coordinates")
    assert len(stub_glyph.coordinates) > 0

    # Advance is the override; LSB matches the design's original (so the
    # visible outline stays in the same horizontal position).
    stub_advance, stub_lsb = f["hmtx"].metrics[stub_name]
    a_advance, a_lsb = f["hmtx"].metrics["A"]
    assert stub_advance == 900
    assert stub_lsb == a_lsb
    f.close()


# ---------- P2: kerning value UPM scaling ----------

def test_kerning_values_are_upm_scaled(tmp_font_dir: Path):
    """When source UPM != design UPM, kerning pair values must be
    proportionally scaled to design UPM (otherwise visibly over/under
    kerned)."""
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=2000,
                         glyph_widths={".notdef": 1000, "A": 1200, "B": 1300, "space": 500})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=1000,
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})

    addOpenTypeFeaturesFromString(
        TTFont_open := TTFont(str(src)),
        "feature kern { pos A B -200; } kern;"
    )
    TTFont_open.save(str(src))

    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    # Source kern is -200 at upm 2000.
    pair = next(p for p in spec.kerning if p.left == "U+0041" and p.right == "U+0042")
    assert pair.value == -200

    out = tmp_font_dir / "out.ttf"
    # Without --match-upm: design stays at upm=1000, kern should be scaled
    # 2000 -> 1000 (halved) -> -100.
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"),
                  match_upm=False)
    f = TTFont(str(out))
    assert "kern" in f
    sub = f["kern"].kernTables[0]
    assert sub.kernTable[("A", "B")] == -100, \
        f"expected -100 (scaled from -200 across upm 2000->1000), got {sub.kernTable[('A','B')]}"
    f.close()


def test_kerning_values_no_op_when_upms_match(tmp_font_dir: Path):
    """When source and design UPMs match, kerning values pass through."""
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=1000)
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=1000)
    addOpenTypeFeaturesFromString(
        f := TTFont(str(src)),
        "feature kern { pos A B -77; } kern;"
    )
    f.save(str(src))

    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))
    f = TTFont(str(out))
    assert f["kern"].kernTables[0].kernTable[("A", "B")] == -77
    f.close()


# ---------- P2: PairPos lookups in non-kern features survive ----------

def test_pairpos_in_non_kern_feature_is_preserved(tmp_font_dir: Path):
    """Design font's PairPos lookups referenced from a non-kern feature
    (e.g., ``cpsp``) must NOT be dropped when we inject our kern lookup.
    Otherwise the design's contextual spacing breaks."""
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    # Design has a PairPos lookup wired into the `cpsp` (capital spacing)
    # feature. Our generator should leave that alone.
    addOpenTypeFeaturesFromString(
        f := TTFont(str(dsn)),
        "feature cpsp { pos A B 50; } cpsp;"
    )
    f.save(str(dsn))

    src = make_test_font(tmp_font_dir / "src.ttf")
    addOpenTypeFeaturesFromString(
        f := TTFont(str(src)),
        "feature kern { pos A B -30; } kern;"
    )
    f.save(str(src))
    spec = extract_metrics(src, include_kerning=True, deterministic=True)

    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))

    f = TTFont(str(out))
    gpos = f["GPOS"].table
    # The cpsp feature record must still exist...
    cpsp = next((fr for fr in gpos.FeatureList.FeatureRecord
                 if fr.FeatureTag == "cpsp"), None)
    assert cpsp is not None, "cpsp feature was dropped"
    # ...and its referenced lookup must still exist in LookupList and
    # actually be a PairPos type 2 lookup.
    cpsp_lookup_indices = list(cpsp.Feature.LookupListIndex)
    assert cpsp_lookup_indices, "cpsp feature lost its lookup references"
    for idx in cpsp_lookup_indices:
        lk = gpos.LookupList.Lookup[idx]
        assert lk.LookupType in (2, 9), \
            f"cpsp now references non-PairPos lookup type {lk.LookupType}"
    f.close()
