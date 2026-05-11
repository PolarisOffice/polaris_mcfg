"""P8 — `--metadata-from` + `--pair-list-from` + `--full-reference` options.

These close the small gap between what the render backend can recover
purely from pixels and what's needed for byte-for-byte file-backend
equivalence. The reference helpers read only:

  - classification flags from head/hhea/OS-2/post (not metric values)
  - kerning pair tuples from kern + GPOS (left/right pairs, not values)

Tests verify:
1. ``load_metadata_flags`` returns the right keys
2. ``load_pair_list`` returns codepoint tuples
3. ``--metadata-from`` populates spec globals
4. ``--pair-list-from`` extends the candidate set and reaches pairs the
   default heuristic misses
5. ``--full-reference`` is the union of the two
6. CJK monospace fast-path (generalized from Hangul) detects monospace
   blocks beyond Hangul Syllables
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable

from polaris_mcfg.render_extractor.reference import (
    load_metadata_flags,
    load_pair_list,
    merge_metadata_into_globals,
)


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


def _build_kerned_font(out: Path,
                      pairs: list[tuple[str, str, int]],
                      italic_angle: float = 0.0,
                      weight: int = 400) -> Path:
    fb = FontBuilder(1000, isTTF=True)
    names = [".notdef", "A", "V", "T", "o", "comma"]
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({
        0x0041: "A", 0x0056: "V", 0x0054: "T", 0x006F: "o", 0x002C: "comma",
    })
    glyphs = {".notdef": _empty()}
    for n in names[1:]:
        glyphs[n] = _box(600)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (600 if n != ".notdef" else 500, 50)
                               for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200, lineGap=100)
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=100,
        usWinAscent=800, usWinDescent=200,
        sxHeight=500, sCapHeight=700,
        usWeightClass=weight,
        fsSelection=0x40,
    )
    fb.setupNameTable({"familyName": "T", "styleName": "R"})
    fb.setupPost(italicAngle=italic_angle, underlinePosition=-75,
                 underlineThickness=50, isFixedPitch=0)
    if pairs:
        from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0
        kern = newTable("kern")
        kern.version = 0
        sub = KernTable_format_0()
        sub.apple = False
        sub.coverage = 1
        sub.version = 0
        sub.format = 0
        sub.kernTable = {(l, r): v for (l, r, v) in pairs}
        kern.kernTables = [sub]
        fb.font["kern"] = kern
    fb.save(str(out))
    return out


# ---------------------------------------------------------------------------
# reference.py units
# ---------------------------------------------------------------------------


def test_load_metadata_flags_returns_expected_keys(tmp_path: Path) -> None:
    font = _build_kerned_font(tmp_path / "f.ttf", pairs=[],
                              italic_angle=-12.0, weight=700)
    meta = load_metadata_flags(font)
    assert meta["head"]["unitsPerEm"] == 1000
    assert meta["hhea"]["ascent"] == 800
    assert meta["hhea"]["descent"] == -200
    assert meta["hhea"]["lineGap"] == 100
    assert meta["os2"]["sCapHeight"] == 700
    assert meta["os2"]["sxHeight"] == 500
    assert meta["os2"]["fsSelection"] == 0x40
    assert meta["post"]["italicAngle"] == -12.0
    assert meta["post"]["underlinePosition"] == -75


def test_load_pair_list_returns_codepoint_tuples(tmp_path: Path) -> None:
    font = _build_kerned_font(tmp_path / "f.ttf", pairs=[
        ("A", "V", -100),
        ("T", "o", -80),
    ])
    pairs = load_pair_list(font)
    pairs_set = {(l, r) for (l, r) in pairs}
    assert (ord("A"), ord("V")) in pairs_set
    assert (ord("T"), ord("o")) in pairs_set


def test_merge_metadata_metadata_wins() -> None:
    measured = {
        "head": {}, "hhea": {"ascent": 798, "descent": -243, "lineGap": 0},
        "os2": {"sCapHeight": 741}, "post": {},
    }
    metadata = {
        "head": {"unitsPerEm": 1000}, "hhea": {"ascent": 880},
        "os2": {"sCapHeight": 733, "fsSelection": 0x40},
        "post": {"italicAngle": 0.0},
    }
    merged = merge_metadata_into_globals(measured, metadata)
    # Metadata wins on overlapping fields
    assert merged["hhea"]["ascent"] == 880
    assert merged["os2"]["sCapHeight"] == 733
    # Measured-only fields are preserved
    assert merged["hhea"]["descent"] == -243
    # Metadata-only fields appear
    assert merged["os2"]["fsSelection"] == 0x40
    assert merged["post"]["italicAngle"] == 0.0


# ---------------------------------------------------------------------------
# orchestrator integration
# ---------------------------------------------------------------------------


def test_metadata_from_populates_spec_globals(tmp_path: Path) -> None:
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_kerned_font(tmp_path / "f.ttf", pairs=[],
                              italic_angle=-15.0, weight=900)
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V")],
        metadata_from=font,
    )
    # File metadata is now in the spec
    assert spec.global_metrics.post.get("italicAngle") == -15.0
    assert spec.global_metrics.os2.get("usWeightClass") == 900
    assert spec.global_metrics.hhea.get("lineGap") == 100
    # source dict records the reference
    assert "metadataReference" in spec.source


def test_pair_list_from_extends_candidate_set(tmp_path: Path) -> None:
    """A pair the default heuristic would skip (T,o without ASCII × Korean
    punct) gets captured when --pair-list-from is set."""
    from polaris_mcfg.render_extractor import extract_via_render
    from polaris_mcfg.render_extractor.kerning import PairCandidate

    font = _build_kerned_font(tmp_path / "f.ttf", pairs=[
        ("A", "V", -100),
        ("T", "o", -80),
    ])
    # Empty candidate list to prove pair-list-from adds them in
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V"), ord("T"), ord("o")],
        include_kerning=True,
        pair_candidates=[],  # nothing by default
        pair_list_from=font,  # but file contributes (A,V) and (T,o)
    )
    pairs = {(p.left, p.right): p.value for p in (spec.kerning or [])}
    assert pairs.get(("U+0041", "U+0056")) == -100
    assert pairs.get(("U+0054", "U+006F")) == -80
    assert "pairListReference" in spec.source


def test_full_reference_is_alias_for_both(tmp_path: Path) -> None:
    """--full-reference FILE must behave as both --metadata-from FILE and
    --pair-list-from FILE."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_kerned_font(tmp_path / "f.ttf", pairs=[
        ("A", "V", -100),
    ], italic_angle=-10.0)
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("V")],
        include_kerning=True,
        pair_candidates=[],
        full_reference=font,
    )
    # Metadata side
    assert spec.global_metrics.post.get("italicAngle") == -10.0
    # Pair-list side
    pairs = {(p.left, p.right): p.value for p in (spec.kerning or [])}
    assert pairs.get(("U+0041", "U+0056")) == -100


# ---------------------------------------------------------------------------
# CJK monospace fast-path generalization
# ---------------------------------------------------------------------------


def test_monospace_blocks_list_has_all_categories() -> None:
    from polaris_mcfg.render_extractor.orchestrator import MONOSPACE_BLOCKS

    names = {name for name, _r, _p in MONOSPACE_BLOCKS}
    assert "Hangul Syllables" in names
    assert "CJK Unified Ideographs" in names
    assert "CJK Compatibility Ideographs" in names
    assert "Halfwidth/Fullwidth Forms" in names


def test_partition_by_blocks_routes_codepoints() -> None:
    from polaris_mcfg.render_extractor.orchestrator import _partition_by_blocks

    cmap = [
        0x0041,  # 'A' — not in any monospace block
        0xAC00,  # '가' — Hangul Syllables
        0x4E00,  # '一' — CJK Unified
        0xF900,  # '豈' — CJK Compatibility
        0xFF01,  # '！' — Halfwidth/Fullwidth
    ]
    by_block, leftover = _partition_by_blocks(cmap)
    assert by_block["Hangul Syllables"] == [0xAC00]
    assert by_block["CJK Unified Ideographs"] == [0x4E00]
    assert by_block["CJK Compatibility Ideographs"] == [0xF900]
    assert by_block["Halfwidth/Fullwidth Forms"] == [0xFF01]
    assert leftover == [0x0041]
