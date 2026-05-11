"""P4 — kerning pair enumeration + threshold.

Two layers:

1. ``default_pair_candidates(cmap=...)`` enumerates ASCII × ASCII +
   ASCII × Korean-punct + Korean-punct × ASCII pairs, filtered by
   whatever the font actually has in its cmap.
2. ``extract_kerning_pairs(font_path, candidates)`` shapes each pair
   through HarfBuzz and reports the post-GPOS advance delta. Pairs
   below the noise threshold are dropped.

Both are exposed to ``extract_via_render`` via ``include_kerning=True``.
"""
from __future__ import annotations

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


def _build_kern_font(out_path: Path,
                     kern_pairs: list[tuple[str, str, int]]) -> Path:
    """Build a font with a classic kern table containing the given pairs."""
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0

    fb = FontBuilder(1000, isTTF=True)
    glyph_order = [".notdef", "A", "V", "T", "o", "comma", "period"]
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap({
        0x0041: "A", 0x0056: "V", 0x0054: "T", 0x006F: "o",
        0x002C: "comma", 0x002E: "period",
    })
    glyphs = {
        ".notdef": _empty(),
        "A": _box(700), "V": _box(700), "T": _box(600), "o": _box(500),
        "comma": _box(200, height=200), "period": _box(200, height=150),
    }
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({
        ".notdef": (500, 0),
        "A": (700, 50), "V": (700, 50), "T": (600, 50),
        "o": (500, 50), "comma": (200, 50), "period": (200, 50),
    })
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=0)
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
        usWinAscent=800, usWinDescent=200,
        sxHeight=500, sCapHeight=700,
    )
    fb.setupNameTable({"familyName": "P4KernTest", "styleName": "Regular"})
    fb.setupPost()
    # Classic kern table
    kern = newTable("kern")
    kern.version = 0
    sub = KernTable_format_0()
    sub.apple = False
    sub.coverage = 1
    sub.version = 0
    sub.format = 0
    sub.kernTable = {(l, r): v for (l, r, v) in kern_pairs}
    kern.kernTables = [sub]
    fb.font["kern"] = kern
    fb.save(str(out_path))
    return out_path


def test_default_pair_candidates_respects_cmap() -> None:
    from polaris_mcfg.render_extractor.kerning import default_pair_candidates

    # Tiny cmap → only pairs in it are emitted.
    cmap = [ord(c) for c in "ABab"]
    cand = default_pair_candidates(cmap=cmap)
    pairs = {(p.left, p.right) for p in cand}
    assert pairs == {
        (ord("A"), ord("A")), (ord("A"), ord("B")),
        (ord("A"), ord("a")), (ord("A"), ord("b")),
        (ord("B"), ord("A")), (ord("B"), ord("B")),
        (ord("B"), ord("a")), (ord("B"), ord("b")),
        (ord("a"), ord("A")), (ord("a"), ord("B")),
        (ord("a"), ord("a")), (ord("a"), ord("b")),
        (ord("b"), ord("A")), (ord("b"), ord("B")),
        (ord("b"), ord("a")), (ord("b"), ord("b")),
    }


def test_default_pair_candidates_full_size() -> None:
    """Without a cmap filter, we get the full ASCII×ASCII + ASCII×Korean
    cross-product."""
    from polaris_mcfg.render_extractor.kerning import (
        ASCII_PRINTABLE, KOREAN_PUNCT, default_pair_candidates,
    )
    cand = default_pair_candidates(cmap=None)
    expected = (
        len(ASCII_PRINTABLE) ** 2
        + len(ASCII_PRINTABLE) * len(KOREAN_PUNCT)
        + len(KOREAN_PUNCT) * len(ASCII_PRINTABLE)
    )
    assert len(cand) == expected


def test_extract_kerning_pairs_recovers_known_kern(tmp_path: Path) -> None:
    """Classic kern table with (A,V) = -100 should be recovered exactly
    via HarfBuzz shaping."""
    from polaris_mcfg.render_extractor.kerning import (
        PairCandidate, extract_kerning_pairs,
    )

    font = _build_kern_font(tmp_path / "k.ttf", [
        ("A", "V", -100),
        ("T", "o", -80),
        ("A", "T", -50),
    ])
    candidates = [
        PairCandidate(ord("A"), ord("V")),
        PairCandidate(ord("T"), ord("o")),
        PairCandidate(ord("A"), ord("T")),
        PairCandidate(ord("A"), ord("A")),  # not kerned, should drop
    ]
    pairs = extract_kerning_pairs(font, candidates, threshold_units=2)
    by_lr = {(p.left, p.right): p.value for p in pairs}
    assert by_lr.get(("U+0041", "U+0056")) == -100
    assert by_lr.get(("U+0054", "U+006F")) == -80
    assert by_lr.get(("U+0041", "U+0054")) == -50
    # AA was not kerned → below threshold → dropped
    assert ("U+0041", "U+0041") not in by_lr


def test_extract_kerning_pairs_respects_threshold(tmp_path: Path) -> None:
    """Pairs with |kern| < threshold are dropped."""
    from polaris_mcfg.render_extractor.kerning import (
        PairCandidate, extract_kerning_pairs,
    )

    font = _build_kern_font(tmp_path / "k.ttf", [
        ("A", "V", -100),
        ("T", "o", -1),  # below threshold
    ])
    candidates = [
        PairCandidate(ord("A"), ord("V")),
        PairCandidate(ord("T"), ord("o")),
    ]
    pairs = extract_kerning_pairs(font, candidates, threshold_units=2)
    by_lr = {(p.left, p.right): p.value for p in pairs}
    assert by_lr.get(("U+0041", "U+0056")) == -100
    assert ("U+0054", "U+006F") not in by_lr


def test_extract_via_render_with_include_kerning(tmp_path: Path) -> None:
    """End-to-end: include_kerning=True populates spec.kerning."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_kern_font(tmp_path / "k.ttf", [
        ("A", "V", -100),
        ("T", "o", -80),
    ])
    spec = extract_via_render(
        font, renderer="freetype",
        include_kerning=True,
        kern_threshold_units=2,
    )
    assert spec.kerning is not None
    pairs = {(p.left, p.right): p.value for p in spec.kerning}
    assert pairs.get(("U+0041", "U+0056")) == -100
    assert pairs.get(("U+0054", "U+006F")) == -80


def test_extract_via_render_skip_kerning_disables(tmp_path: Path) -> None:
    """skip_kerning=True wins over include_kerning=True."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_kern_font(tmp_path / "k.ttf", [("A", "V", -100)])
    spec = extract_via_render(
        font, renderer="freetype",
        include_kerning=True,
        skip_kerning=True,
    )
    assert spec.kerning is None


@pytest.mark.skipif(
    not Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf").exists(),
    reason="NotoSansKR-Bold not present (gitignored)",
)
def test_kerning_recovery_on_real_notosanskr() -> None:
    """Real font regression: render kerning pairs match file kerning pairs
    (where both extract them).

    NotoSansKR has ~20K GPOS PairPos pairs but they're class-based and
    massive. We compare only against the pairs the file backend
    extracted, and check that overlapping pairs agree exactly.
    """
    from polaris_mcfg.extractor import extract_metrics
    from polaris_mcfg.render_extractor import extract_via_render
    from polaris_mcfg.render_extractor.kerning import PairCandidate

    font = Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf")
    file_spec = extract_metrics(
        font, include_kerning=True, deterministic=True)
    file_pairs = {(p.left, p.right): p.value for p in (file_spec.kerning or [])}

    # Probe a small set to keep this test fast (the full default set is
    # ~14K and takes seconds).
    cands = [
        PairCandidate(ord(l), ord(r))
        for l, r in [("A", "V"), ("T", "o"), ("V", "A"),
                     ("A", "Y"), ("W", "a")]
    ]
    render_spec = extract_via_render(
        font, renderer="freetype",
        include_kerning=True,
        pair_candidates=cands,
        cmap=[ord(c) for c in "AVTYWoa"],
    )
    render_pairs = {(p.left, p.right): p.value
                    for p in (render_spec.kerning or [])}

    # For every render-extracted pair, value must match file backend (if
    # file also extracted it).
    for lr, rv in render_pairs.items():
        if lr in file_pairs:
            assert rv == file_pairs[lr], (
                f"render kern {lr}={rv} != file {file_pairs[lr]}")
