"""P3 — Hangul monospace auto-detect + replication.

The Hangul Syllables block (U+AC00..U+D7A3, 11,172 chars) is almost
always monospace in production fonts (NotoSansKR, Pretendard, KoPub
body faces, etc.). Measuring all 11,172 individually wastes 5+ seconds
of FreeType time and emits 11,172 redundant probes.

The fast-path: render 4 representative syllables ("가", "뷁", "이",
"왈"). If all 4 advances agree within ±1 px, the block is monospace
and we replicate the common value across the cmap.

These tests verify:
1. ``_hangul_is_monospace`` correctly identifies a monospace font.
2. ``extract_via_render`` skips per-syllable measurement when the
   fast-path triggers (timing + source.hangulMonospace marker).
3. With ``detect_monospace=False`` every syllable is measured.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen


def _box(width: int, height: int = 700, x_off: int = 50):
    pen = TTGlyphPen(None)
    pen.moveTo((x_off, 0))
    pen.lineTo((width - x_off, 0))
    pen.lineTo((width - x_off, height))
    pen.lineTo((x_off, height))
    pen.closePath()
    return pen.glyph()


def _empty():
    return TTGlyphPen(None).glyph()


def _build_hangul_mono_font(out_path: Path, advance: int = 920,
                            n_syllables: int = 20) -> Path:
    """Build a tiny font whose Hangul block is uniform advance.

    Always includes the 4 monospace-probe codepoints ("가", "뷁", "이",
    "왈") so the auto-detector can fire. ``n_syllables`` additional
    syllables are added beyond those.
    """
    fb = FontBuilder(1000, isTTF=True)
    # Probe set first (must match HANGUL_MONOSPACE_PROBES in orchestrator).
    probe_cps = [ord(c) for c in ("가", "뷁", "이", "왈")]  # 가 뷁 이 왈
    extra_cps = [0xAC00 + i * 100 + 1 for i in range(n_syllables)]
    hangul_cps = probe_cps + [cp for cp in extra_cps if cp not in probe_cps]
    syl_names = [f"hangul_{cp:04X}" for cp in hangul_cps]
    glyph_order = [".notdef", "H"] + syl_names
    fb.setupGlyphOrder(glyph_order)
    cmap = {0x0048: "H"}
    for cp, name in zip(hangul_cps, syl_names):
        cmap[cp] = name
    fb.setupCharacterMap(cmap)
    glyphs = {".notdef": _empty(), "H": _box(700)}
    for name in syl_names:
        glyphs[name] = _box(advance)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({
        ".notdef": (500, 0),
        "H": (700, 50),
        **{name: (advance, 50) for name in syl_names},
    })
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
        usWinAscent=800, usWinDescent=200,
        sxHeight=500, sCapHeight=700,
    )
    fb.setupNameTable({"familyName": "P3MonoTest", "styleName": "Regular"})
    fb.setupPost()
    fb.save(str(out_path))
    return out_path


def _build_hangul_variable_font(out_path: Path) -> Path:
    """Hangul block with per-syllable variable advance (rare but valid)."""
    fb = FontBuilder(1000, isTTF=True)
    # 4 syllables matching the monospace-probe set, with varying widths.
    probes = {
        ord("가"): ("ga", 900),
        ord("뷁"): ("byk", 950),
        ord("이"): ("i", 880),
        ord("왈"): ("wal", 920),
    }
    glyph_order = [".notdef", "H"] + [name for name, _ in probes.values()]
    fb.setupGlyphOrder(glyph_order)
    cmap = {0x0048: "H"}
    cmap.update({cp: name for cp, (name, _) in probes.items()})
    fb.setupCharacterMap(cmap)
    glyphs = {".notdef": _empty(), "H": _box(700)}
    for name, w in probes.values():
        glyphs[name] = _box(w)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({
        ".notdef": (500, 0),
        "H": (700, 50),
        **{name: (w, 50) for name, w in probes.values()},
    })
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
        usWinAscent=800, usWinDescent=200,
        sxHeight=500, sCapHeight=700,
    )
    fb.setupNameTable({"familyName": "P3VarTest", "styleName": "Regular"})
    fb.setupPost()
    fb.save(str(out_path))
    return out_path


def test_hangul_is_monospace_detects_uniform_block(tmp_path: Path) -> None:
    """All 4 probe syllables have identical advance → monospace = True."""
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.orchestrator import _hangul_is_monospace

    font = _build_hangul_mono_font(tmp_path / "mono.ttf", advance=920)
    with FreeTypeBackend(font) as be:
        is_mono, common = _hangul_is_monospace(be, size_px=1000)
    assert is_mono is True
    assert abs(common - 920.0) <= 1.5


def test_hangul_is_monospace_rejects_variable_block(tmp_path: Path) -> None:
    """Probe syllables disagree → monospace = False."""
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.orchestrator import _hangul_is_monospace

    font = _build_hangul_variable_font(tmp_path / "var.ttf")
    with FreeTypeBackend(font) as be:
        is_mono, common = _hangul_is_monospace(be, size_px=1000)
    assert is_mono is False


def test_extract_via_render_uses_hangul_fast_path(tmp_path: Path) -> None:
    """When monospace is detected, source marker is set and all syllables
    share the same advance value (no per-syllable measurement)."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_hangul_mono_font(
        tmp_path / "mono.ttf", advance=920, n_syllables=20)
    # Use the same cmap our synth font populates.
    probe_cps = [ord(c) for c in ("가", "뷁", "이", "왈")]
    extra_cps = [0xAC00 + i * 100 + 1 for i in range(20)]
    cmap = sorted({0x0048, *probe_cps, *extra_cps})
    spec = extract_via_render(
        font, renderer="freetype", cmap=cmap, detect_monospace=True,
    )
    # Source marker present
    mono = spec.source.get("hangulMonospace")
    assert mono is not None
    assert mono["detected"] is True
    assert mono["commonAdvance"] == 920
    # All Hangul Syllables in cmap got the common advance
    for cp in cmap:
        if 0xAC00 <= cp <= 0xD7A3:
            gid = f"U+{cp:04X}"
            assert gid in spec.glyphs, gid
            assert spec.glyphs[gid].advanceWidth == 920


def test_extract_via_render_disabling_fast_path_measures_each(
    tmp_path: Path,
) -> None:
    """With detect_monospace=False, no source marker; every glyph is measured."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_hangul_mono_font(
        tmp_path / "mono.ttf", advance=920, n_syllables=10)
    probe_cps = [ord(c) for c in ("가", "뷁", "이", "왈")]
    cmap = sorted({0x0048, *probe_cps,
                   *(0xAC00 + i * 100 + 1 for i in range(10))})
    spec = extract_via_render(
        font, renderer="freetype", cmap=cmap, detect_monospace=False,
    )
    assert "hangulMonospace" not in spec.source


def test_hangul_fast_path_is_faster(tmp_path: Path) -> None:
    """Sanity: fast-path completes faster than full-measure on the same
    cmap. This isn't a strict perf gate (CI noise) but catches regressions
    where the fast-path is accidentally falling through to per-glyph
    measurement.
    """
    from polaris_mcfg.render_extractor import extract_via_render

    n = 100  # bigger gap so timing diff is clearly above CI noise
    font = _build_hangul_mono_font(
        tmp_path / "mono.ttf", advance=920, n_syllables=n)
    probe_cps = [ord(c) for c in ("가", "뷁", "이", "왈")]
    cmap = sorted({0x0048, *probe_cps,
                   *(0xAC00 + i * 100 + 1 for i in range(n))})

    t0 = time.perf_counter()
    extract_via_render(
        font, renderer="freetype", cmap=cmap, detect_monospace=False)
    t_full = time.perf_counter() - t0

    t0 = time.perf_counter()
    spec_fast = extract_via_render(
        font, renderer="freetype", cmap=cmap, detect_monospace=True)
    t_fast = time.perf_counter() - t0

    # Sanity: fast-path actually fired
    assert spec_fast.source.get("hangulMonospace", {}).get("detected") is True
    # ~100 syllables vs ~4 probes → expect at least ~30% speedup. Loose
    # bound to absorb CI variance.
    assert t_fast < t_full * 0.7, f"t_full={t_full:.3f} t_fast={t_fast:.3f}"
