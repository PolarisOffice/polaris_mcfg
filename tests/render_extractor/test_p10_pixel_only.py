"""P10 — `--pixel-only` strictest-EULA mode.

When ``pixel_only=True``, the extractor must not touch the font file
outside the rendering pipeline:

  - No HarfBuzz shape() calls (kerning + shaped advance lost)
  - No file-backend numeric copy (metadata / pair list / unnamed)

The only file access is the cmap-table read for codepoint enumeration
(when ``cmap=None``). Result is ~80% metric coverage (advance, LSB,
vertical, italic angle, underline) using only rendered pixels.

This is the mode for fonts whose EULA explicitly forbids metric
extraction or reverse engineering.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def _box(width: int):
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((width - 50, 0))
    pen.lineTo((width - 50, 700))
    pen.lineTo((50, 700))
    pen.closePath()
    return pen.glyph()


def _empty():
    return TTGlyphPen(None).glyph()


def _build_font(out: Path) -> Path:
    fb = FontBuilder(1000, isTTF=True)
    # Include H, x, g, l so the vertical-metric probe finds them
    names = [".notdef", "A", "V", "T", "o", "H", "x", "g", "l"]
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({
        0x0041: "A", 0x0056: "V", 0x0054: "T", 0x006F: "o",
        0x0048: "H", 0x0078: "x", 0x0067: "g", 0x006C: "l",
    })
    glyphs = {".notdef": _empty()}
    for n in names[1:]:
        glyphs[n] = _box(600)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (600 if n != ".notdef" else 500, 50)
                               for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
                usWinAscent=800, usWinDescent=200,
                sxHeight=500, sCapHeight=700)
    fb.setupNameTable({"familyName": "T", "styleName": "R"})
    fb.setupPost()
    # Add classic kern so a non-pixel-only run would pick it up
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0
    kern = newTable("kern")
    kern.version = 0
    sub = KernTable_format_0()
    sub.apple = False
    sub.coverage = 1
    sub.version = 0
    sub.format = 0
    sub.kernTable = {("A", "V"): -100, ("T", "o"): -80}
    kern.kernTables = [sub]
    fb.font["kern"] = kern
    fb.save(str(out))
    return out


def test_pixel_only_disables_kerning(tmp_path: Path) -> None:
    """pixel_only=True suppresses kerning even when include_kerning=True."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V"), ord("T"), ord("o")],
        include_lsb=True,
        include_kerning=True,  # would normally pick up classic kern
        pixel_only=True,
    )
    # No kerning at all
    assert spec.kerning is None or spec.kerning == []
    # source marker
    assert spec.source.get("pixelOnly") is True
    assert "include_kerning" in spec.source.get("pixelOnlyDisabled", [])


def test_pixel_only_disables_shaped(tmp_path: Path) -> None:
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A")],
        include_shaped=True,
        pixel_only=True,
    )
    assert spec.shaped_advances is None or spec.shaped_advances == []
    assert "include_shaped" in spec.source.get("pixelOnlyDisabled", [])


def test_pixel_only_disables_reference_options(tmp_path: Path) -> None:
    """pixel_only suppresses every reference-from option even when set."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V")],
        include_lsb=True,
        metadata_from=font,
        pair_list_from=font,
        unnamed_from=font,
        full_reference=font,
        pixel_only=True,
    )
    # No reference markers in source
    assert "metadataReference" not in spec.source
    assert "pairListReference" not in spec.source
    assert "unnamedReference" not in spec.source
    disabled = spec.source.get("pixelOnlyDisabled", [])
    assert "metadata_from" in disabled
    assert "pair_list_from" in disabled
    assert "unnamed_from" in disabled
    assert "full_reference" in disabled


def test_pixel_only_still_measures_advance_and_lsb(tmp_path: Path) -> None:
    """advance + LSB + vertical are still captured under pixel-only."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V")],
        include_lsb=True,
        pixel_only=True,
    )
    # A and V both measured
    assert "U+0041" in spec.glyphs
    assert "U+0056" in spec.glyphs
    a = spec.glyphs["U+0041"]
    assert abs(a.advanceWidth - 600) <= 2
    assert a.lsb is not None
    assert abs(a.lsb - 50) <= 5
    # Vertical metrics populated (hhea, OS/2)
    assert spec.global_metrics.hhea.get("ascent") is not None
    assert spec.global_metrics.os2.get("sCapHeight") is not None


def test_pixel_only_marker_clean_when_no_conflicting_options(
    tmp_path: Path,
) -> None:
    """When pixel-only is the only option (no kerning etc. originally
    requested), pixelOnlyDisabled is absent / empty."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A")],
        include_lsb=True,
        pixel_only=True,
    )
    assert spec.source.get("pixelOnly") is True
    # No conflicts → no disabled list
    assert spec.source.get("pixelOnlyDisabled") in (None, [])
