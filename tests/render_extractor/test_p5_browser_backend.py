"""P5 — Playwright browser backend.

Runs only when Playwright + Chromium are available. Marked with the
``browser`` pytest mark so they can be deselected on CI with
``-m "not browser"`` if Playwright isn't installed.

The browser backend is the slowest in M8 (launches Chromium per
backend instance), so these tests are deliberately small: one PoC
advance measurement on the synthetic font, plus one cross-backend
agreement check against the FreeType backend (both should agree
within ±1 unit at size_px=100 → ±10 unit in font-unit frame, allowing
for browser sub-pixel quirks).
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Skip the whole module if Playwright isn't importable. We don't require
# Chromium binaries here — the BrowserBackend.open() raises at runtime
# if the browser isn't installed, which is fine for CI without
# `playwright install`.
playwright = pytest.importorskip("playwright")

pytestmark = pytest.mark.browser


def _build_p2_like_font(out_path: Path) -> Path:
    """Re-use the P2 synthetic font helper."""
    # Import the helper from the P2 test module to avoid duplication.
    from tests.render_extractor.test_p2_basic_metrics import _build_p2_font
    return _build_p2_font(out_path)


def test_browser_backend_opens(tmp_path: Path) -> None:
    from polaris_mcfg.render_extractor.backends.browser_backend import (
        BrowserBackend,
    )
    font = _build_p2_like_font(tmp_path / "b.ttf")
    try:
        with BrowserBackend(font) as be:
            assert be.reported_upem() is None  # browser can't report UPM
    except Exception as e:
        if "Executable doesn" in str(e) or "playwright install" in str(e):
            pytest.skip("Chromium not installed; run `playwright install chromium`")
        raise


def test_browser_backend_measures_advance(tmp_path: Path) -> None:
    """AAAA pattern on browser backend recovers 600u advance from the
    synthetic font at size_px=100 (60px per glyph)."""
    from polaris_mcfg.render_extractor.analyzer import measure_advance_repeated
    from polaris_mcfg.render_extractor.backends import RenderRequest
    from polaris_mcfg.render_extractor.backends.browser_backend import (
        BrowserBackend,
    )
    font = _build_p2_like_font(tmp_path / "b.ttf")
    try:
        with BrowserBackend(font) as be:
            result = be.render(RenderRequest(text="AAAA", size_px=100))
    except Exception as e:
        if "Executable doesn" in str(e) or "playwright install" in str(e):
            pytest.skip("Chromium not installed")
        raise
    adv_px = measure_advance_repeated(result)
    # 600u glyph at size_px=100 (100 CSS px per em) → expected ~60 CSS px.
    assert abs(adv_px - 60.0) < 1.5, f"adv_px={adv_px}"


def test_browser_and_freetype_agree_on_advance(tmp_path: Path) -> None:
    """Cross-backend regression: browser and FreeType report the same
    advance for the same synthetic font within ±1 unit (in font units)."""
    from polaris_mcfg.render_extractor.analyzer import measure_advance_repeated
    from polaris_mcfg.render_extractor.backends import RenderRequest
    from polaris_mcfg.render_extractor.backends.browser_backend import (
        BrowserBackend,
    )
    from polaris_mcfg.render_extractor.backends.freetype_backend import (
        FreeTypeBackend,
    )
    from polaris_mcfg.render_extractor.units import pixel_to_unit

    font = _build_p2_like_font(tmp_path / "b.ttf")

    # FreeType: size_px=1000 → 1 unit = 1 px.
    with FreeTypeBackend(font) as be:
        ft_px = measure_advance_repeated(
            be.render(RenderRequest(text="AAAA", size_px=1000)))
    ft_units = pixel_to_unit(ft_px, size_px=1000, upem=1000)

    # Browser: size_px=100 → 1 unit = 0.1 px. Use upem=1000 since the
    # browser backend doesn't report it.
    try:
        with BrowserBackend(font) as be:
            br_px = measure_advance_repeated(
                be.render(RenderRequest(text="AAAA", size_px=100)))
    except Exception as e:
        if "Executable doesn" in str(e) or "playwright install" in str(e):
            pytest.skip("Chromium not installed")
        raise
    br_units = pixel_to_unit(br_px, size_px=100, upem=1000)

    assert abs(br_units - ft_units) <= 1, (
        f"freetype={ft_units}u  browser={br_units}u")


def test_extract_via_render_with_browser_renderer(tmp_path: Path) -> None:
    """End-to-end: extract_via_render(renderer='browser') returns a
    valid MetricsSpec from the browser pipeline."""
    from polaris_mcfg.render_extractor import extract_via_render

    font = _build_p2_like_font(tmp_path / "b.ttf")
    try:
        spec = extract_via_render(
            font, renderer="browser",
            cmap=[ord("A"), ord("H"), ord("x")],
            size_px=100,  # smaller, faster for tests
        )
    except Exception as e:
        if "Executable doesn" in str(e) or "playwright install" in str(e):
            pytest.skip("Chromium not installed")
        raise
    assert spec.source["renderer"] == "browser"
    # A=600u, H=700u, x=400u (in font units)
    assert "U+0041" in spec.glyphs
    assert abs(spec.glyphs["U+0041"].advanceWidth - 600) <= 5
    assert abs(spec.glyphs["U+0048"].advanceWidth - 700) <= 5
    assert abs(spec.glyphs["U+0078"].advanceWidth - 400) <= 5
