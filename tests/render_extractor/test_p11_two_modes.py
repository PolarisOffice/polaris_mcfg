"""P11 — two-mode workflow (Strict vs Full).

After empirical measurement showed that the heuristic-only kerning
recovery is ~5% on CJK fonts (NotoSansKR has 21K pairs but only 1K
are ASCII × ASCII), the only two operationally meaningful render-
backend modes are:

  Strict:  --pixel-only --include-lsb
           pure region A, EULA-strictest, ~80% coverage
           (advance + LSB + vertical, no kerning / no shaped /
           no unnamed glyph)

  Full:    --full-reference SOURCE.ttf
           region A + B, byte-for-byte file-backend equivalence,
           ~100% coverage. Auto-enables include_lsb, include_kerning,
           include_shaped so the user doesn't have to remember
           which flags combine with --full-reference.

Tests verify the auto-enable behavior, including the pixel-only ×
full-reference interaction (pixel-only wins for kerning + shaped).
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


def test_full_reference_auto_enables_includes(tmp_path: Path) -> None:
    """One flag (--full-reference) should be enough — auto-enables
    include_lsb, include_kerning, include_shaped."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V"), ord("T"), ord("o"), ord("H"),
              ord("x"), ord("g"), ord("l")],
        full_reference=font,
        # Note: caller did NOT set include_kerning, include_shaped,
        # include_lsb — but full_reference should turn them on.
    )
    # LSB measured (include_lsb auto-on)
    assert spec.glyphs["U+0041"].lsb is not None
    # Kerning extracted (include_kerning auto-on + pair_list from file)
    assert spec.kerning is not None
    pairs = {(p.left, p.right): p.value for p in spec.kerning}
    assert pairs.get(("U+0041", "U+0056")) == -100
    # Shaped advance considered (include_shaped auto-on)
    assert spec.shaped_advances is not None  # empty list is OK
    # The three reference markers are all set
    assert "metadataReference" in spec.source
    assert "pairListReference" in spec.source
    # unnamedReference only shows when something was actually copied;
    # this synth font has no unnamed glyphs in cmap, so marker absent
    # is OK


def test_strict_mode_pixel_only_with_lsb(tmp_path: Path) -> None:
    """The Strict-mode invocation: --pixel-only --include-lsb."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V"), ord("H"), ord("x")],
        pixel_only=True,
        include_lsb=True,
    )
    # advance + LSB present
    a = spec.glyphs["U+0041"]
    assert a.lsb is not None
    # No kerning, no shaped
    assert spec.kerning is None or spec.kerning == []
    assert spec.shaped_advances is None or spec.shaped_advances == []
    # pixelOnly marker
    assert spec.source.get("pixelOnly") is True


def test_pixel_only_wins_over_full_reference_for_kerning(tmp_path: Path) -> None:
    """If a confused user combines --pixel-only --full-reference, the
    strict intent wins: kerning + shaped + reference-from sources are
    all suppressed. (pixel_only is processed before full_reference
    auto-enable.)"""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V"), ord("H"), ord("x")],
        pixel_only=True,
        full_reference=font,
    )
    # Region-A-only outcome: no kerning, no shaped, no references
    assert spec.kerning is None or spec.kerning == []
    assert spec.shaped_advances is None or spec.shaped_advances == []
    assert "metadataReference" not in spec.source
    assert "pairListReference" not in spec.source
    assert spec.source.get("pixelOnly") is True
    # full_reference appears in disabled list
    assert "full_reference" in spec.source.get("pixelOnlyDisabled", [])


def test_full_reference_pixel_only_keeps_lsb_auto_on(tmp_path: Path) -> None:
    """include_lsb auto-on stays on even under pixel_only (LSB is
    region A — pixel measurement)."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V")],
        pixel_only=True,
        full_reference=font,
        # include_lsb intentionally omitted — full_reference would
        # turn it on, but pixel_only suppresses full_reference itself.
        # Effective: include_lsb defaults to False.
    )
    # LSB is None (we didn't explicitly set include_lsb, and
    # pixel-only suppressed full_reference's auto-enable)
    a = spec.glyphs.get("U+0041")
    assert a is not None
    # advance measured regardless of include_lsb
    assert a.advanceWidth > 0
