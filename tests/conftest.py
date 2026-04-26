"""Shared test helpers — generate tiny in-memory test fonts via fontTools."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def _empty_glyph() -> object:
    pen = TTGlyphPen(None)
    return pen.glyph()


def _box_glyph(width: int, height: int = 700, x: int = 50, y: int = 0) -> object:
    """Simple filled box glyph for rendering / metric tests."""
    pen = TTGlyphPen(None)
    pen.moveTo((x, y))
    pen.lineTo((x + width - 2 * x, y))
    pen.lineTo((x + width - 2 * x, y + height))
    pen.lineTo((x, y + height))
    pen.closePath()
    return pen.glyph()


def make_test_font(
    out_path: Path,
    *,
    family: str = "TestSans",
    style: str = "Regular",
    units_per_em: int = 1000,
    ascent: int = 800,
    descent: int = -200,
    line_gap: int = 0,
    cap_height: int = 700,
    x_height: int = 500,
    glyph_widths: dict[str, int] | None = None,
    cmap: dict[int, str] | None = None,
    kerning: Iterable[tuple[str, str, int]] | None = None,
) -> Path:
    """Build a minimal valid TTF for tests.

    Parameters
    ----------
    glyph_widths : mapping of glyph-name -> advance width.
        Must include ``.notdef`` and any glyph referenced in ``cmap``.
    cmap : mapping of unicode codepoint -> glyph name.
    kerning : iterable of (left_glyph_name, right_glyph_name, value).
        Emitted as a classic ``kern`` table.
    """
    if glyph_widths is None:
        glyph_widths = {".notdef": 500, "A": 600, "B": 650, "space": 250}
    if cmap is None:
        cmap = {0x0041: "A", 0x0042: "B", 0x0020: "space"}

    glyph_order = list(glyph_widths.keys())
    if ".notdef" not in glyph_order:
        glyph_order.insert(0, ".notdef")

    fb = FontBuilder(units_per_em, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)

    glyphs = {}
    for name in glyph_order:
        if name == ".notdef" or name == "space":
            glyphs[name] = _empty_glyph()
        else:
            glyphs[name] = _box_glyph(glyph_widths[name])
    fb.setupGlyf(glyphs)

    metrics = {name: (glyph_widths[name], 0) for name in glyph_order}
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(
        ascent=ascent, descent=descent, lineGap=line_gap
    )
    fb.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=descent,
        sTypoLineGap=line_gap,
        usWinAscent=ascent,
        usWinDescent=-descent,
        sxHeight=x_height,
        sCapHeight=cap_height,
    )
    fb.setupNameTable({"familyName": family, "styleName": style})
    fb.setupPost()

    if kerning:
        from fontTools.ttLib import newTable
        kern = newTable("kern")
        kern.version = 0
        from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0
        sub = KernTable_format_0()
        sub.apple = False
        sub.coverage = 1
        sub.version = 0
        sub.format = 0
        sub.kernTable = {(l, r): v for (l, r, v) in kerning}
        kern.kernTables = [sub]
        fb.font["kern"] = kern

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(out_path))
    return out_path


@pytest.fixture
def tmp_font_dir(tmp_path: Path) -> Path:
    return tmp_path
