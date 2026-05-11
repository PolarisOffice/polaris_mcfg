"""P6 — shaped advance + cross-backend integration regression.

These tests use real-font fixtures when available and synthetic fonts
otherwise. They verify:

1. ``include_shaped=True`` populates ``spec.shaped_advances`` from
   HarfBuzz shape() output.
2. Render-extracted shaped advances agree with the file-extractor's
   shaped advances (HarfBuzz under the hood for both).
3. The full extract → compare → render pipeline is consistent: any
   metric extracted via file backend can be re-extracted via render
   backend within the documented tolerance.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.skipif(
    not Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf").exists(),
    reason="NotoSansKR-Bold not present (gitignored)",
)
def test_render_shaped_advances_match_file_on_notosanskr() -> None:
    """File backend and render backend should agree on shaped advances
    (both use HarfBuzz, so this should be byte-identical for any cmap
    codepoint where shape differs from default)."""
    from polaris_mcfg.extractor import extract_metrics
    from polaris_mcfg.render_extractor import extract_via_render

    font = Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf")
    # Restrict to a tiny cmap so the test finishes in seconds. Pick
    # codepoints where shape difference is known to exist for KOR (e.g.,
    # ASCII space U+0020 has hang/KOR shaping = wider space).
    cmap = [0x0020, 0x0028, 0x0029, 0x002E, 0x002C, 0x003F, 0x0021]

    file_spec = extract_metrics(font, include_gsub=True, deterministic=True)
    render_spec = extract_via_render(
        font, renderer="freetype",
        cmap=cmap,
        include_shaped=True,
    )

    # Build (codepoint, script, language) → advance lookup for each.
    def _idx(spec):
        out: dict[tuple[str, str, str], int] = {}
        for sa in (spec.shaped_advances or []):
            out[(sa.codepoint, sa.script, sa.language)] = sa.advance
        return out

    file_idx = _idx(file_spec)
    render_idx = _idx(render_spec)

    # For every (cp, script, lang) the render backend recorded, the file
    # backend should also have it with the same advance (both use HB).
    for key, rv in render_idx.items():
        if key in file_idx:
            assert rv == file_idx[key], (
                f"shaped advance mismatch {key}: render={rv} file={file_idx[key]}"
            )


@pytest.mark.skipif(
    not Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf").exists(),
    reason="NotoSansKR-Bold not present (gitignored)",
)
def test_full_pipeline_render_extract_agrees_with_file_extract() -> None:
    """End-to-end pipeline regression on NotoSansKR-Bold.

    Picks 8 Latin + 5 Hangul codepoints and 5 kerning pair candidates.
    Render extraction must agree with file extraction on:
      - per-glyph advance (≤ 2u diff)
      - per-glyph LSB (≤ 5u diff)
      - kerning pair values (exact, since both go through HB)
    """
    from polaris_mcfg.extractor import extract_metrics
    from polaris_mcfg.render_extractor import extract_via_render
    from polaris_mcfg.render_extractor.kerning import PairCandidate

    font = Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf")
    latin = [ord(c) for c in "AVWTaov,"]
    hangul = [ord(c) for c in "가나다라마"]
    cps = latin + hangul

    file_spec = extract_metrics(
        font, include_lsb=True, include_kerning=True, deterministic=True)

    # Custom kerning candidates restricted to our cmap subset
    pair_cands = [
        PairCandidate(ord("A"), ord("V")),
        PairCandidate(ord("T"), ord("o")),
        PairCandidate(ord("V"), ord("A")),
        PairCandidate(ord("W"), ord("a")),
        PairCandidate(ord("A"), ord("v")),
    ]
    render_spec = extract_via_render(
        font, renderer="freetype",
        cmap=cps,
        include_lsb=True,
        include_kerning=True,
        pair_candidates=pair_cands,
    )

    # Advance + LSB agreement
    for cp in cps:
        gid = f"U+{cp:04X}"
        assert gid in render_spec.glyphs, gid
        fa = file_spec.glyphs[gid].advanceWidth
        ra = render_spec.glyphs[gid].advanceWidth
        assert abs(ra - fa) <= 2, f"{gid} adv: file={fa} render={ra}"
        fl = file_spec.glyphs[gid].lsb
        rl = render_spec.glyphs[gid].lsb
        if fl is not None and rl is not None:
            assert abs(rl - fl) <= 5, f"{gid} lsb: file={fl} render={rl}"

    # Kerning agreement (exact since both use HB)
    file_pairs = {(p.left, p.right): p.value for p in (file_spec.kerning or [])}
    render_pairs = {
        (p.left, p.right): p.value for p in (render_spec.kerning or [])
    }
    for lr, rv in render_pairs.items():
        if lr in file_pairs:
            assert rv == file_pairs[lr], (
                f"kern {lr}: render={rv} file={file_pairs[lr]}")


def test_shaped_advances_omitted_when_not_requested(tmp_path: Path) -> None:
    """Without include_shaped, spec.shaped_advances stays None."""
    from polaris_mcfg.render_extractor import extract_via_render
    from tests.render_extractor.test_p2_basic_metrics import _build_p2_font

    font = _build_p2_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("H")],
        include_shaped=False,
    )
    assert spec.shaped_advances is None


def test_shaped_advances_empty_list_for_simple_font(tmp_path: Path) -> None:
    """For a synth font with no GSUB/GPOS contextual rules,
    include_shaped=True returns an empty list (no overrides found)."""
    from polaris_mcfg.render_extractor import extract_via_render
    from tests.render_extractor.test_p2_basic_metrics import _build_p2_font

    font = _build_p2_font(tmp_path / "f.ttf")
    spec = extract_via_render(
        font, renderer="freetype",
        cmap=[ord("A"), ord("H"), ord("x")],
        include_shaped=True,
    )
    assert spec.shaped_advances == []
