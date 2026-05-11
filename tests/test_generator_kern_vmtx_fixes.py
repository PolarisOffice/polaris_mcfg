"""Regression tests for the two generator bugs surfaced by the end-to-end
M8 render-extractor demo:

1. classic ``kern`` table 16-bit subtable-length overflow when pair
   count exceeds ~10,920 (subtable header has a 16-bit length field, max
   65535 bytes; 14-byte header + 6 bytes/pair).

2. ``vmtx`` underfill when ``--apply gsub`` inserts stub glyphs that
   increase ``numGlyphs`` but the design font's ``vmtx`` is left at its
   original size. fontTools refuses to load such a font at next read.
"""
from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.schema import (
    GlobalMetrics,
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    ShapedAdvanceOverride,
)


# ---------------------------------------------------------------------------
# Bug 1: classic kern subtable length overflow
# ---------------------------------------------------------------------------


def _box(width: int):
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((width - 50, 0))
    pen.lineTo((width - 50, 700))
    pen.lineTo((50, 700))
    pen.closePath()
    return pen.glyph()


def _build_design_font(out: Path, n_glyphs: int = 200,
                       with_vmtx: bool = False) -> Path:
    """Build a small design font with N glyphs in the BMP."""
    fb = FontBuilder(1000, isTTF=True)
    names = [".notdef"] + [f"g{i:04d}" for i in range(n_glyphs)]
    fb.setupGlyphOrder(names)
    cmap = {0x1000 + i: f"g{i:04d}" for i in range(n_glyphs)}
    fb.setupCharacterMap(cmap)
    glyphs = {".notdef": _box(500)}
    for n in names[1:]:
        glyphs[n] = _box(600)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (600 if n != ".notdef" else 500, 50)
                               for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
        usWinAscent=800, usWinDescent=200,
        sxHeight=500, sCapHeight=700,
    )
    fb.setupNameTable({"familyName": "T", "styleName": "R"})
    fb.setupPost()
    if with_vmtx:
        fb.setupVerticalHeader(
            ascent=500, descent=-500, lineGap=0,
            advanceHeightMax=1000,
            minTopSideBearing=0, minBottomSideBearing=0,
            yMaxExtent=1000,
            caretSlopeRise=0, caretSlopeRun=1, caretOffset=0,
            reserved0=0, reserved1=0, reserved2=0, reserved3=0, reserved4=0,
            metricDataFormat=0,
        )
        fb.setupVerticalMetrics({n: (1000, 0) for n in names})
    fb.save(str(out))
    return out


def test_classic_kern_skipped_when_pair_count_overflows(tmp_path: Path) -> None:
    """When >MAX_CLASSIC_KERN_PAIRS pairs, classic kern is skipped but
    GPOS still carries them and the font remains loadable."""
    design = _build_design_font(tmp_path / "design.ttf", n_glyphs=200)

    # Spec with >10,920 pairs (force overflow)
    glyphs = {
        f"U+{0x1000 + i:04X}": GlyphMetric(advanceWidth=600)
        for i in range(200)
    }
    # 200 × 200 = 40000 candidate pairs; sample 11000 of them
    pairs = []
    seen = 0
    for l in range(200):
        for r in range(200):
            pairs.append(KerningPair(
                left=f"U+{0x1000 + l:04X}",
                right=f"U+{0x1000 + r:04X}",
                value=-10,
            ))
            seen += 1
            if seen >= 11000:
                break
        if seen >= 11000:
            break
    spec = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs=glyphs,
        kerning=pairs,
    )

    out = tmp_path / "result.ttf"
    report = generate_font(
        spec, design, out,
        apply=("global", "advance", "kerning"),
        family_name="T2", style_name="R",
        license_text="OFL", license_url="x",
    )
    # Result must load without error — that's the whole point
    f = TTFont(str(out))
    # The font may or may not have a `kern` table — when omitted, GPOS
    # is still present and carries the pairs.
    assert f.get("GPOS") is not None
    f.close()

    # Report reflects the skip
    kern_report = report.get("kerning", {})
    assert kern_report["pairs"] == 11000
    assert kern_report["classicKernWritten"] == 0
    assert kern_report["classicKernSkippedReason"] == "size>16bit-limit"


def test_classic_kern_written_under_limit(tmp_path: Path) -> None:
    """At pair counts under MAX_CLASSIC_KERN_PAIRS, classic kern is
    still written (legacy compatibility)."""
    design = _build_design_font(tmp_path / "design.ttf", n_glyphs=50)
    glyphs = {
        f"U+{0x1000 + i:04X}": GlyphMetric(advanceWidth=600)
        for i in range(50)
    }
    pairs = [
        KerningPair(
            left=f"U+{0x1000 + l:04X}",
            right=f"U+{0x1000 + r:04X}",
            value=-5,
        )
        for l in range(50) for r in range(50)
    ]  # 2500 pairs, well under limit
    spec = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs=glyphs,
        kerning=pairs,
    )
    out = tmp_path / "result.ttf"
    report = generate_font(
        spec, design, out,
        apply=("global", "advance", "kerning"),
        family_name="T3", style_name="R",
        license_text="OFL", license_url="x",
    )
    f = TTFont(str(out))
    assert f.get("kern") is not None
    assert f["kern"].kernTables[0].kernTable  # populated
    f.close()
    assert report["kerning"]["classicKernWritten"] == 2500


# ---------------------------------------------------------------------------
# Bug 2: vmtx underfill when stub glyphs are inserted
# ---------------------------------------------------------------------------


def test_apply_gsub_does_not_corrupt_vmtx(tmp_path: Path) -> None:
    """When the design font has vmtx and --apply gsub inserts stub
    glyphs, the result font must still be loadable (i.e., vmtx grew
    to match the new numGlyphs)."""
    design = _build_design_font(
        tmp_path / "design.ttf", n_glyphs=50, with_vmtx=True)

    # A spec with shaped-advance overrides that will produce stub glyphs
    glyphs = {
        f"U+{0x1000 + i:04X}": GlyphMetric(advanceWidth=600)
        for i in range(50)
    }
    overrides = [
        ShapedAdvanceOverride(
            codepoint=f"U+{0x1000 + i:04X}",
            script="hang", language="KOR",
            advance=900,
        )
        for i in range(5)  # 5 stubs inserted
    ]
    spec = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs=glyphs,
        shaped_advances=overrides,
    )

    out = tmp_path / "result.ttf"
    generate_font(
        spec, design, out,
        apply=("global", "advance", "gsub"),
        family_name="T4", style_name="R",
        license_text="OFL", license_url="x",
    )

    # The whole point: reload must succeed without
    # "not enough 'vmtx' table data" error.
    f = TTFont(str(out))
    vmtx = f["vmtx"]
    glyph_order = f.getGlyphOrder()
    # vmtx must cover every glyph in the order
    for gn in glyph_order:
        assert gn in vmtx.metrics, f"vmtx missing {gn}"
    # And the stub glyphs are present
    stubs = [n for n in glyph_order if n.startswith("polaris.")]
    assert len(stubs) >= 1
    f.close()


def test_missing_notdef_stub_does_not_corrupt_vmtx(tmp_path: Path) -> None:
    """When --missing-glyph notdef inserts the notdef-fallback stub, the
    vmtx must grow with it."""
    design = _build_design_font(
        tmp_path / "design.ttf", n_glyphs=20, with_vmtx=True)

    # Spec with a codepoint the design font doesn't have (forces routing
    # to notdef stub).
    glyphs = {
        "U+0041": GlyphMetric(advanceWidth=600),  # design has no 0x0041
    }
    spec = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs=glyphs,
    )

    out = tmp_path / "result.ttf"
    generate_font(
        spec, design, out,
        apply=("global", "advance"),
        family_name="T5", style_name="R",
        license_text="OFL", license_url="x",
        missing_glyph="notdef",
    )

    f = TTFont(str(out))
    glyph_order = f.getGlyphOrder()
    vmtx = f["vmtx"]
    for gn in glyph_order:
        assert gn in vmtx.metrics, f"vmtx missing {gn}"
    f.close()
