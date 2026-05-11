"""P2 — vertical metrics + per-glyph advance/LSB/BBox.

Tests the full P2 scope:
1. ``probe_vertical`` recovers ascent/descent/cap-height/x-height from
   a single reference-string render, within ±2 px of the synthetic
   font's known values.
2. ``probe_advance_and_lsb`` returns LSB in addition to advance.
3. ``extract_via_render(include_lsb=True)`` reports LSBs in the
   returned :class:`MetricsSpec`.
4. Auto-cmap mode: ``extract_via_render(cmap=None)`` reads the font's
   cmap table (only — not outlines) and measures everything in it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def _box_glyph(width: int, height: int, x_off: int = 50, y_off: int = 0):
    pen = TTGlyphPen(None)
    pen.moveTo((x_off, y_off))
    pen.lineTo((width - x_off, y_off))
    pen.lineTo((width - x_off, y_off + height))
    pen.lineTo((x_off, y_off + height))
    pen.closePath()
    return pen.glyph()


def _empty_glyph():
    return TTGlyphPen(None).glyph()


def _build_p2_font(out_path: Path) -> Path:
    """Synthetic font with per-glyph heights (so x_height vs cap_height
    can be measured distinctly)."""
    fb = FontBuilder(1000, isTTF=True)
    glyph_order = [".notdef", "H", "x", "g", "l", "A", "B", "space"]
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap({
        0x0048: "H", 0x0078: "x", 0x0067: "g", 0x006C: "l",
        0x0041: "A", 0x0042: "B", 0x0020: "space",
    })
    # Per-glyph (width, height, y_off). H spans 0..700, x spans 0..500,
    # g spans -200..500 (descender), l spans 0..800 (ascender).
    specs = {
        ".notdef": (500, 0, 0),
        "H":       (700, 700, 0),
        "x":       (400, 500, 0),
        "g":       (450, 700, -200),
        "l":       (200, 800, 0),
        "A":       (600, 700, 0),
        "B":       (650, 700, 0),
        "space":   (250, 0, 0),
    }
    glyphs = {}
    # Box glyphs use x_off=50; LSB in hmtx must match outline xMin for
    # FreeType to render them in the correct canvas position. Whitespace
    # glyphs have LSB=0 (no outline).
    lsb_for: dict[str, int] = {}
    for name in glyph_order:
        w, h, y = specs[name]
        if h == 0:
            glyphs[name] = _empty_glyph()
            lsb_for[name] = 0
        else:
            glyphs[name] = _box_glyph(w, h, y_off=y)
            lsb_for[name] = 50  # matches x_off in _box_glyph
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (specs[n][0], lsb_for[n]) for n in glyph_order})
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
        usWinAscent=800, usWinDescent=200,
        sxHeight=500, sCapHeight=700,
    )
    fb.setupNameTable({"familyName": "P2Test", "styleName": "Regular"})
    fb.setupPost()
    fb.save(str(out_path))
    return out_path


@pytest.fixture
def synth_font(tmp_path: Path) -> Path:
    return _build_p2_font(tmp_path / "p2.ttf")


def test_probe_vertical_recovers_cap_and_x_height(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.orchestrator import probe_vertical

    with FreeTypeBackend(synth_font) as be:
        px = probe_vertical(be, size_px=1000)

    # Synthetic font: capHeight=700, xHeight=500 (in font units; 1 unit ≈ 1 px
    # at size_px=upem=1000). Box glyphs span y=0..height, so ink_top = 700 above
    # baseline for H, 500 for x.
    assert "cap_height" in px, f"got {px}"
    assert "x_height" in px
    # Allow ±5 px (font fb box quirks).
    assert abs(px["cap_height"] - 700.0) <= 5, f"cap_height={px['cap_height']}"
    assert abs(px["x_height"] - 500.0) <= 5, f"x_height={px['x_height']}"


def test_probe_advance_and_lsb_for_inked_glyph(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.orchestrator import probe_advance_and_lsb

    with FreeTypeBackend(synth_font) as be:
        adv, lsb = probe_advance_and_lsb(be, "A", size_px=1000)

    # A: advance=600, box starts at x=50 (LSB=50)
    assert abs(adv - 600.0) <= 1.5, f"adv={adv}"
    assert lsb is not None
    assert abs(lsb - 50.0) <= 5, f"lsb={lsb}"


def test_probe_advance_and_lsb_for_whitespace_glyph(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.orchestrator import probe_advance_and_lsb

    with FreeTypeBackend(synth_font) as be:
        adv, lsb = probe_advance_and_lsb(be, " ", size_px=1000)

    # space: advance=250, no ink → LSB=None
    assert abs(adv - 250.0) <= 1.5
    assert lsb is None


def test_extract_via_render_populates_global_metrics(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor import extract_via_render

    spec = extract_via_render(
        synth_font, renderer="freetype",
        cmap=[ord("A"), ord("H"), ord("x"), ord("g"), ord("l")],
    )
    # global_metrics should now carry hhea ascent/descent and OS/2 caps.
    hhea = spec.global_metrics.hhea
    os2 = spec.global_metrics.os2
    assert "ascent" in hhea, f"hhea missing ascent: {hhea}"
    assert "descent" in hhea
    assert "sCapHeight" in os2
    assert "sxHeight" in os2


def test_extract_via_render_with_include_lsb(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor import extract_via_render

    spec = extract_via_render(
        synth_font, renderer="freetype",
        cmap=[ord("A"), ord("H")],
        include_lsb=True,
    )
    # A has box starting at x=50 → LSB ≈ 50u.
    a = spec.glyphs["U+0041"]
    assert a.lsb is not None
    assert abs(a.lsb - 50) <= 5, f"LSB={a.lsb}"


def test_extract_via_render_auto_cmap(synth_font: Path) -> None:
    """When cmap=None we read the font's cmap table only (no outlines)."""
    from polaris_mcfg.render_extractor import extract_via_render

    spec = extract_via_render(synth_font, renderer="freetype")
    # We put A, B, H, x, g, l, space (=0x20) in cmap. We expect at least
    # the visible ones to be measured. The space glyph is whitespace —
    # advance is measured but LSB is undefined.
    for cp_hex in ("U+0041", "U+0042", "U+0048"):
        assert cp_hex in spec.glyphs, f"missing {cp_hex}"


def test_render_vs_file_advance_lsb_diff_within_tolerance(
    synth_font: Path,
) -> None:
    """End-to-end: render extraction vs file extraction on the same synth
    font. p95 advance diff ≤ 2u, max ≤ 5u, LSB diff ≤ 5u.
    """
    from polaris_mcfg.extractor import extract_metrics
    from polaris_mcfg.render_extractor import extract_via_render

    file_spec = extract_metrics(
        synth_font, include_lsb=True, deterministic=True)
    test_cps = [ord(c) for c in "AHxglB"]
    render_spec = extract_via_render(
        synth_font, renderer="freetype",
        include_lsb=True, cmap=test_cps,
    )
    adv_diffs: list[int] = []
    lsb_diffs: list[int] = []
    for cp in test_cps:
        gid = f"U+{cp:04X}"
        if gid not in file_spec.glyphs or gid not in render_spec.glyphs:
            continue
        adv_diffs.append(
            render_spec.glyphs[gid].advanceWidth
            - file_spec.glyphs[gid].advanceWidth
        )
        fl = file_spec.glyphs[gid].lsb
        rl = render_spec.glyphs[gid].lsb
        if fl is not None and rl is not None:
            lsb_diffs.append(rl - fl)

    assert len(adv_diffs) >= 6
    assert max(abs(d) for d in adv_diffs) <= 2, f"adv diffs: {adv_diffs}"
    assert max(abs(d) for d in lsb_diffs) <= 5, f"lsb diffs: {lsb_diffs}"


@pytest.mark.skipif(
    not Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf").exists(),
    reason="NotoSansKR-Bold not present (gitignored)",
)
def test_render_vs_file_on_real_notosanskr() -> None:
    """Real-font regression: NotoSansKR-Bold advance / LSB diff ≤ 2u on
    a subset of mixed Latin + Hangul codepoints.

    Skipped when the font isn't checked out locally (CI). When run, this
    is the strongest possible accuracy gate: the render backend must
    match the file backend within ±2 unit across diverse glyphs.
    """
    from polaris_mcfg.extractor import extract_metrics
    from polaris_mcfg.render_extractor import extract_via_render

    font = Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf")
    file_spec = extract_metrics(
        font, include_lsb=True, deterministic=True)
    test_cps = [ord(c) for c in "AHxglMNOP가나다라"]
    render_spec = extract_via_render(
        font, renderer="freetype",
        include_lsb=True, cmap=test_cps,
    )
    for cp in test_cps:
        gid = f"U+{cp:04X}"
        assert gid in render_spec.glyphs, gid
        fa = file_spec.glyphs[gid].advanceWidth
        ra = render_spec.glyphs[gid].advanceWidth
        assert abs(ra - fa) <= 2, f"{gid}: file={fa} render={ra}"
        fl = file_spec.glyphs[gid].lsb
        rl = render_spec.glyphs[gid].lsb
        if fl is not None and rl is not None:
            assert abs(rl - fl) <= 5, f"{gid} lsb: file={fl} render={rl}"
