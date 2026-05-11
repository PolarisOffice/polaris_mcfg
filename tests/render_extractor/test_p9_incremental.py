"""P9 — incremental spec update.

When the user iterates on a probe set or fixes a bug, they need to
re-measure only the affected unicode block, not the whole 24K-glyph
font (which takes 40 min). This is the merge-with-base mechanism:

    spec_v2 = extract_via_render(
        font,
        update_spec=spec_v1_json,
        refresh_blocks=["Halfwidth/Fullwidth Forms"],
    )

Tests cover the merge precedence, refresh-set expansion, and the
end-to-end flow through ``extract_via_render``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from polaris_mcfg.render_extractor.incremental import (
    expand_refresh_set,
    load_spec,
    merge_specs,
)
from polaris_mcfg.schema import (
    GlobalMetrics,
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    ShapedAdvanceOverride,
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


def _build_font(out: Path, n_glyphs: int = 20) -> Path:
    fb = FontBuilder(1000, isTTF=True)
    names = [".notdef"] + [f"g{i:04d}" for i in range(n_glyphs)]
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({0x1000 + i: f"g{i:04d}" for i in range(n_glyphs)})
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
    fb.save(str(out))
    return out


# ---------------------------------------------------------------------------
# merge_specs
# ---------------------------------------------------------------------------


def test_merge_overlay_wins_on_overlapping_glyphs() -> None:
    base = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs={
            "U+0041": GlyphMetric(advanceWidth=600, lsb=50),
            "U+0042": GlyphMetric(advanceWidth=650, lsb=55),
        },
    )
    overlay = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs={
            "U+0041": GlyphMetric(advanceWidth=999, lsb=99),  # overlay wins
        },
    )
    merged = merge_specs(base, overlay)
    assert merged.glyphs["U+0041"].advanceWidth == 999
    assert merged.glyphs["U+0041"].lsb == 99
    # base survives where overlay didn't touch
    assert merged.glyphs["U+0042"].advanceWidth == 650
    assert merged.glyphs["U+0042"].lsb == 55
    # mergedFromBase marker is set
    assert merged.source.get("mergedFromBase") is True


def test_merge_kerning_overlap_wins() -> None:
    base = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        kerning=[
            KerningPair(left="U+0041", right="U+0056", value=-100),
            KerningPair(left="U+0054", right="U+006F", value=-80),
        ],
    )
    overlay = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        kerning=[
            KerningPair(left="U+0041", right="U+0056", value=-50),  # overlay wins
            KerningPair(left="U+0057", right="U+0061", value=-30),  # new pair
        ],
    )
    merged = merge_specs(base, overlay)
    by_lr = {(p.left, p.right): p.value for p in (merged.kerning or [])}
    assert by_lr[("U+0041", "U+0056")] == -50    # overlay
    assert by_lr[("U+0054", "U+006F")] == -80    # base
    assert by_lr[("U+0057", "U+0061")] == -30    # new from overlay
    assert len(by_lr) == 3


def test_merge_shaped_advances_triple_key() -> None:
    base = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        shaped_advances=[
            ShapedAdvanceOverride(codepoint="U+0020", script="hang",
                                  language="KOR", advance=500),
        ],
    )
    overlay = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        shaped_advances=[
            ShapedAdvanceOverride(codepoint="U+0020", script="hang",
                                  language="KOR", advance=999),  # overlay
            ShapedAdvanceOverride(codepoint="U+0020", script="kana",
                                  language="JAN", advance=600),  # new
        ],
    )
    merged = merge_specs(base, overlay)
    by_key = {(s.codepoint, s.script, s.language): s.advance
              for s in (merged.shaped_advances or [])}
    assert by_key[("U+0020", "hang", "KOR")] == 999
    assert by_key[("U+0020", "kana", "JAN")] == 600


def test_merge_none_kerning_passes_through() -> None:
    base = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        kerning=None,
    )
    overlay = MetricsSpec(
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        kerning=[KerningPair(left="U+0041", right="U+0056", value=-50)],
    )
    merged = merge_specs(base, overlay)
    assert merged.kerning is not None
    assert len(merged.kerning) == 1


# ---------------------------------------------------------------------------
# expand_refresh_set
# ---------------------------------------------------------------------------


def test_expand_refresh_set_codepoints() -> None:
    s = expand_refresh_set(refresh_cmap=[0x41, 0x42, 0x43])
    assert s == {0x41, 0x42, 0x43}


def test_expand_refresh_set_block() -> None:
    s = expand_refresh_set(refresh_blocks=["Hangul Syllables"])
    assert 0xAC00 in s
    assert 0xD7A3 in s
    assert len(s) == 11172  # full Hangul Syllables block


def test_expand_refresh_set_combination() -> None:
    s = expand_refresh_set(refresh_cmap=[0x41],
                          refresh_blocks=["Halfwidth/Fullwidth Forms"])
    assert 0x41 in s
    assert 0xFF01 in s


def test_expand_refresh_set_unknown_block_raises() -> None:
    with pytest.raises(ValueError, match="unknown block"):
        expand_refresh_set(refresh_blocks=["NonExistent Block"])


# ---------------------------------------------------------------------------
# end-to-end through extract_via_render
# ---------------------------------------------------------------------------


def test_update_spec_without_refresh_remeasures_all(tmp_path: Path) -> None:
    """Without refresh_*, the full cmap is re-measured and overlay wins
    on overlap. Base entries the overlay didn't touch (e.g., kerning
    pairs outside the candidate set) carry through."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf", n_glyphs=10)

    # First-time extract
    spec_v1 = extract_via_render(
        font, renderer="freetype",
        cmap=[0x1000, 0x1001],
        include_lsb=True,
    )
    spec_v1_json = tmp_path / "v1.json"
    spec_v1_json.write_text(spec_v1.to_json())

    # Inject an extra glyph into base to confirm it carries through.
    spec_v1.glyphs["U+9999"] = GlyphMetric(advanceWidth=12345, lsb=99)
    spec_v1_json.write_text(spec_v1.to_json())

    spec_v2 = extract_via_render(
        font, renderer="freetype",
        cmap=[0x1000, 0x1001],  # re-measure same set
        include_lsb=True,
        update_spec=spec_v1_json,
    )
    # The synthetic U+9999 from base survives
    assert "U+9999" in spec_v2.glyphs
    assert spec_v2.glyphs["U+9999"].advanceWidth == 12345
    # Re-measured glyphs are present
    assert "U+1000" in spec_v2.glyphs
    # source has the merge marker
    assert spec_v2.source.get("updateBase") == "v1.json"


def test_refresh_cmap_only_measures_subset(tmp_path: Path) -> None:
    """With refresh_cmap, only those codepoints are rendered; the rest
    come from the base spec unchanged."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf", n_glyphs=10)

    spec_v1 = extract_via_render(
        font, renderer="freetype",
        cmap=[0x1000, 0x1001, 0x1002, 0x1003],
        include_lsb=True,
    )
    # Corrupt one glyph in base to detect refresh
    spec_v1.glyphs["U+1000"] = GlyphMetric(advanceWidth=9999, lsb=88)
    spec_v1_json = tmp_path / "v1.json"
    spec_v1_json.write_text(spec_v1.to_json())

    # Refresh only U+1000 — should clobber the 9999 with real measurement,
    # but U+1001..1003 stay at base values.
    spec_v2 = extract_via_render(
        font, renderer="freetype",
        cmap=[0x1000, 0x1001, 0x1002, 0x1003],
        include_lsb=True,
        update_spec=spec_v1_json,
        refresh_cmap=[0x1000],
    )
    assert spec_v2.glyphs["U+1000"].advanceWidth == 600  # actual measured
    assert "U+1001" in spec_v2.glyphs
    assert spec_v2.source.get("refreshedCodepoints") == 1


def test_refresh_without_update_spec_raises(tmp_path: Path) -> None:
    """refresh_cmap / refresh_blocks need a base spec to merge into."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_font(tmp_path / "f.ttf", n_glyphs=5)
    with pytest.raises(ValueError, match="require --update-spec"):
        extract_via_render(
            font, renderer="freetype",
            refresh_cmap=[0x1000],
        )
