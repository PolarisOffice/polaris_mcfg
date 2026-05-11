"""P1 — RenderBackend wiring + FreeType backend smoke + single-glyph advance.

These tests verify the smallest possible promise of the render extractor:
given a synthetic TTF whose advances we control via the test font helper,
the FreeType backend reports per-glyph pen advances that match (up to
±1 unit at size_px = upem).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.conftest import make_test_font


@pytest.fixture
def synth_font(tmp_path: Path) -> Path:
    """Synthetic TTF: A=600u, B=650u, space=250u at 1000 UPM."""
    return make_test_font(
        tmp_path / "synth.ttf",
        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250},
    )


def test_freetype_backend_opens(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )

    with FreeTypeBackend(synth_font) as be:
        assert be.reported_upem() == 1000


def test_freetype_renders_single_char_to_pixel_buffer(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor.backends import RenderRequest
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )

    with FreeTypeBackend(synth_font) as be:
        result = be.render(RenderRequest(text="A", size_px=1000))

    assert isinstance(result.image, np.ndarray)
    assert result.image.dtype == np.uint8
    assert result.image.ndim == 2
    # At 1000px EM size on a 1000 UPM font, glyph "A" (advance 600u, box
    # 50..550 × 0..700) should produce ink.
    assert (result.image > 0).any(), "glyph 'A' produced no ink"
    assert len(result.glyphs) == 1
    g = result.glyphs[0]
    # backend-reported advance ≈ 600 px (within 1 px subpixel rounding)
    assert abs(g.advance_x - 600.0) < 1.5, f"advance_x={g.advance_x}"


def test_probe_advance_AAAA_matches_known_width(synth_font: Path) -> None:
    """The whole point of P1: pixel-measured advance ≈ true advance."""
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.orchestrator import probe_advance

    with FreeTypeBackend(synth_font) as be:
        adv_A = probe_advance(be, "A", size_px=1000, repeats=4)
        adv_B = probe_advance(be, "B", size_px=1000, repeats=4)

    # Synthetic font advances: A=600, B=650 at 1000 UPM. With size_px=1000
    # we expect 1 px ≈ 1 unit, so measured ≈ true ± 1.
    assert abs(adv_A - 600.0) < 1.5, f"adv_A={adv_A}"
    assert abs(adv_B - 650.0) < 1.5, f"adv_B={adv_B}"


def test_extract_via_render_returns_metricsspec(synth_font: Path) -> None:
    from polaris_mcfg.render_extractor import extract_via_render
    from polaris_mcfg.schema import MetricsSpec

    spec = extract_via_render(
        synth_font,
        renderer="freetype",
        cmap=[ord("A"), ord("B")],
    )
    assert isinstance(spec, MetricsSpec)
    assert spec.global_metrics.unitsPerEm == 1000
    # P1: we put backend identity into the source dict
    assert spec.source.get("extractedVia") == "render"
    assert spec.source.get("renderer") == "freetype"
    # Advances within ±1 unit of the synthetic font's true values.
    a_id = "U+0041"
    b_id = "U+0042"
    assert a_id in spec.glyphs and b_id in spec.glyphs
    assert abs(spec.glyphs[a_id].advanceWidth - 600) <= 1
    assert abs(spec.glyphs[b_id].advanceWidth - 650) <= 1
