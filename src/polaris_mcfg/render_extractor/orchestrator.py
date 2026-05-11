"""Orchestrator — turns a font path into a MetricsSpec via rendering.

The Orchestrator decides:
- which backend to instantiate (FreeType / browser / auto),
- what to render (single-glyph advance probes, vertical-metric probe,
  kerning pair probes, ...),
- how to assemble the per-glyph + global + kerning results into a
  :class:`MetricsSpec`.

This is the only module a user-facing CLI talks to.

Phases (see ``docs/design/12-render-extractor.md`` §8):
    P1: backend wiring + single-glyph advance probe (this file's first cut)
    P2: vertical metrics, full-cmap advance + LSB + BBox
    P3: Hangul monospace auto-detect + replication
    P4: kerning pair enumeration + threshold
    P5: browser backend selection
    P6: shaped-advance via lang attribute (browser only)
    P7: docs + release
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..schema import (
    GlobalMetrics,
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    ShapedAdvanceOverride,
    codepoint_to_id,
)
from .analyzer import (
    measure_advance_repeated,
    measure_baseline_metrics,
    measure_glyph_bbox,
)
from .backends import RenderBackend, RenderRequest
from .units import pixel_to_unit

# Default characters used for vertical-metric probing.
DEFAULT_VERT_REFS = {"cap": "H", "x": "x", "desc": "g", "asc": "l"}

# Hangul monospace probe set. If all four advances are within ±1 px the
# Hangul block is treated as monospace and only "가" is measured for the
# full 11,172 syllables.
HANGUL_MONOSPACE_PROBES = ("가", "뷁", "이", "왈")

#: Hangul Syllables block: U+AC00 .. U+D7A3 (11,172 chars).
HANGUL_SYLLABLES_RANGE = range(0xAC00, 0xD7A4)


def _open_backend(font_path: Path, renderer: str) -> RenderBackend:
    """Pick and instantiate a backend.

    ``renderer`` values:
        - ``"freetype"``: always pick FreeType (raises if unavailable).
        - ``"browser"``: always pick Playwright browser (raises if unavailable).
        - ``"auto"``: try FreeType first, then browser.
    """
    if renderer == "freetype":
        from .backends.freetype_backend import FreeTypeBackend
        return FreeTypeBackend(font_path)
    if renderer == "browser":
        from .backends.browser_backend import BrowserBackend  # noqa: F401
        return BrowserBackend(font_path)  # type: ignore[name-defined]
    if renderer == "auto":
        try:
            from .backends.freetype_backend import FreeTypeBackend
            return FreeTypeBackend(font_path)
        except Exception:
            pass
        try:
            from .backends.browser_backend import BrowserBackend
            return BrowserBackend(font_path)
        except Exception as e:
            raise RuntimeError(
                "No render backend available. Install with "
                "`pip install -e '.[render-extract]'` "
                "(FreeType) or `'.[render-extract-browser]'` (Playwright)."
            ) from e
    raise ValueError(f"unknown renderer: {renderer!r}")


def probe_advance(backend: RenderBackend, ch: str, size_px: int = 1000,
                  repeats: int = 4) -> float:
    """Measure the advance of one character in pixels via N-repeat fit."""
    text = ch * repeats
    result = backend.render(RenderRequest(text=text, size_px=size_px))
    return measure_advance_repeated(result)


def probe_vertical(backend: RenderBackend, size_px: int = 1000,
                   refs: dict[str, str] = DEFAULT_VERT_REFS) -> dict[str, float]:
    """Render the vertical reference string and return pixel-space metrics.

    Returns
    -------
    dict
        Keys ``cap_height``, ``x_height``, ``descent``, ``ascent`` in pixels.
    """
    text = "".join(refs.values())
    result = backend.render(RenderRequest(text=text, size_px=size_px))
    return measure_baseline_metrics(result, refs)


def _hangul_is_monospace(backend: RenderBackend, size_px: int = 1000,
                        tolerance_px: float = 1.0) -> tuple[bool, float | None]:
    """Decide whether the Hangul syllables block is uniform-advance.

    Returns ``(is_monospace, common_advance_px_or_None)``.
    """
    advances = []
    for probe in HANGUL_MONOSPACE_PROBES:
        try:
            adv = probe_advance(backend, probe, size_px=size_px)
        except Exception:
            return False, None
        advances.append(adv)
    if not advances:
        return False, None
    mn, mx = min(advances), max(advances)
    if mx - mn <= tolerance_px:
        return True, sum(advances) / len(advances)
    return False, None


def extract_via_render(
    font_path: str | Path,
    *,
    renderer: str = "auto",
    size_px: int = 1000,
    upem: int = 1000,
    include_lsb: bool = False,
    include_kerning: bool = False,
    include_vertical: bool = False,
    detect_monospace: bool = True,
    cmap: Iterable[int] | None = None,
    skip_kerning: bool = False,
) -> MetricsSpec:
    """Render-based extraction (P1: minimal stub).

    Returns a :class:`MetricsSpec` populated from rendered measurements.
    In P1 we populate only ``unitsPerEm`` and a small handful of cmap
    glyphs as a proof of life. Phases P2+ fill in the rest.

    Parameters
    ----------
    font_path
        Path to the font file (TTF/OTF/WOFF).
    renderer
        ``"freetype"`` | ``"browser"`` | ``"auto"``.
    size_px
        Render EM size in pixels. Default 1000.
    upem
        UPM frame to report metrics in. The backend's reported UPM (if
        any) takes priority; otherwise this value is used.
    cmap
        Iterable of unicode codepoints to measure. If ``None``, P1 uses
        a tiny default set ``"HxglMABCabc012가"`` to keep tests fast.
    """
    font_path = Path(font_path)
    if cmap is None:
        cmap = [ord(c) for c in "HxglMABCabc012가"]
    cmap = list(cmap)

    with _open_backend(font_path, renderer) as backend:
        reported_upem = backend.reported_upem()
        upem_used = reported_upem if reported_upem is not None else upem

        # Per-glyph advance (P1: minimal; P2 expands)
        glyphs: dict[str, GlyphMetric] = {}
        for cp in cmap:
            ch = chr(cp)
            try:
                adv_px = probe_advance(backend, ch, size_px=size_px)
            except Exception:
                continue
            adv_units = pixel_to_unit(adv_px, size_px=size_px, upem=upem_used)
            glyphs[codepoint_to_id(cp)] = GlyphMetric(advanceWidth=adv_units)

    spec = MetricsSpec(
        source={
            "filename": font_path.name,
            "extractedVia": "render",
            "renderer": renderer,
            "renderSizePx": size_px,
            "reportedUpem": reported_upem,
        },
        global_metrics=GlobalMetrics(unitsPerEm=upem_used),
        glyphs=glyphs,
    )
    return spec
