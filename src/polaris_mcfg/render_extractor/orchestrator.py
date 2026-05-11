"""Orchestrator — turns a font path into a MetricsSpec via rendering.

The Orchestrator decides:
- which backend to instantiate (FreeType / browser / auto),
- what to render (single-glyph advance probes, vertical-metric probe,
  kerning pair probes, ...),
- how to assemble the per-glyph + global + kerning results into a
  :class:`MetricsSpec`.

This is the only module a user-facing CLI talks to.

Phases (see ``docs/design/12-render-extractor.md`` §8):
    P1: backend wiring + single-glyph advance probe
    P2: vertical metrics, full-cmap advance + LSB + BBox (this file)
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
from .kerning import (
    DEFAULT_KERN_THRESHOLD_UNITS,
    PairCandidate,
    default_pair_candidates,
    extract_kerning_pairs,
)
from .units import pixel_to_unit, pixel_to_unit_float

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


def probe_advance_and_lsb(backend: RenderBackend, ch: str, size_px: int = 1000,
                          repeats: int = 4) -> tuple[float, float | None]:
    """Measure advance + LSB (left side bearing) for a single character.

    LSB is the gap between the pen position and the leftmost ink pixel.
    For empty glyphs (whitespace) LSB is undefined and returned as ``None``.
    """
    text = ch * repeats
    result = backend.render(RenderRequest(text=text, size_px=size_px))
    advance = measure_advance_repeated(result)
    if not result.glyphs:
        return advance, None
    bbox = measure_glyph_bbox(result.image, result.glyphs[0])
    if bbox.is_empty:
        return advance, None
    # LSB = ink_left - pen_x
    lsb = bbox.ink_left - bbox.pen_x
    return advance, lsb


def probe_lsb_only(backend: RenderBackend, ch: str,
                   size_px: int = 1000) -> float | None:
    """LSB-only single-render probe. ~4× cheaper than probe_advance_and_lsb
    when advance is already known (e.g. inside the Hangul fast-path)."""
    result = backend.render(RenderRequest(text=ch, size_px=size_px))
    if not result.glyphs:
        return None
    bbox = measure_glyph_bbox(result.image, result.glyphs[0])
    if bbox.is_empty:
        return None
    return bbox.ink_left - bbox.pen_x


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


def _measure_global(backend: RenderBackend, size_px: int,
                    upem: int) -> dict[str, dict]:
    """Build the ``GlobalMetrics`` sub-dicts (head/hhea/OS/2/post) from render.

    Only fields we can plausibly recover from rendered output are filled.
    Field choices roughly mirror file-extractor's ``HHEA_FIELDS`` /
    ``OS2_FIELDS`` / ``POST_FIELDS`` but skip outline-derived items.
    """
    px = probe_vertical(backend, size_px=size_px)

    def u(name: str) -> int:
        return pixel_to_unit(px[name], size_px=size_px, upem=upem)

    ascent = u("ascent") if "ascent" in px else None
    descent = u("descent") if "descent" in px else None
    cap = u("cap_height") if "cap_height" in px else None
    xh = u("x_height") if "x_height" in px else None

    hhea: dict = {}
    if ascent is not None:
        hhea["ascent"] = ascent
    if descent is not None:
        # OpenType hhea descent is *negative* below baseline (per spec).
        hhea["descent"] = -descent
    # lineGap is hard to measure from one render; punt to 0 unless caller
    # uses a multi-line probe.
    hhea["lineGap"] = 0

    os2: dict = {}
    if ascent is not None:
        os2["sTypoAscender"] = ascent
        os2["usWinAscent"] = ascent
    if descent is not None:
        os2["sTypoDescender"] = -descent
        os2["usWinDescent"] = descent  # usWin* fields are positive
    os2["sTypoLineGap"] = 0
    if cap is not None:
        os2["sCapHeight"] = cap
    if xh is not None:
        os2["sxHeight"] = xh

    return {"head": {}, "hhea": hhea, "os2": os2, "post": {}}


def _enumerate_cmap_from_font(font_path: Path) -> list[int]:
    """For tests: list the cmap codepoints of a font without exposing them.

    The render extractor is meant to be used when the caller can't (or
    won't) read the file. But in practice the caller still needs to know
    *which* codepoints to probe. Two strategies:

    1. Caller supplies the list explicitly (production use).
    2. Caller asks us to read just the ``cmap`` table from the font file.
       The ``cmap`` table is a numeric whitelist of supported codepoints
       — no outline data — and reading it is uncontroversial under any
       reasonable EULA.

    This helper is the strategy-2 fallback. It reads ONLY the ``cmap``
    table via fontTools.
    """
    from fontTools.ttLib import TTFont
    font = TTFont(str(font_path), lazy=True)
    try:
        cmap = font.getBestCmap() or {}
        return sorted(cmap.keys())
    finally:
        font.close()


def _partition_hangul_syllables(cmap: list[int]) -> tuple[list[int], list[int]]:
    """Split a cmap into ``(hangul_syllables, other)``.

    Hangul Syllables block = U+AC00 .. U+D7A3 (11,172 chars).
    """
    hangul: list[int] = []
    other: list[int] = []
    for cp in cmap:
        if 0xAC00 <= cp <= 0xD7A3:
            hangul.append(cp)
        else:
            other.append(cp)
    return hangul, other


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
    max_glyphs: int | None = None,
    progress: bool = False,
    pair_candidates: list[PairCandidate] | None = None,
    kern_threshold_units: int = DEFAULT_KERN_THRESHOLD_UNITS,
) -> MetricsSpec:
    """Render-based extraction.

    Returns a :class:`MetricsSpec` populated from rendered measurements.

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
    include_lsb
        Measure per-glyph left side bearing in addition to advance.
    cmap
        Iterable of unicode codepoints to measure. If ``None``, the cmap
        is read from the font's ``cmap`` table (a uncontroversial-to-read
        numeric whitelist — no outline data).
    max_glyphs
        If given, only the first N codepoints are measured. Useful for
        smoke tests on huge CJK fonts.
    progress
        If True, print a one-line progress update every 500 glyphs.
    """
    font_path = Path(font_path)

    if cmap is None:
        cmap = _enumerate_cmap_from_font(font_path)
    cmap = list(cmap)
    if max_glyphs is not None:
        cmap = cmap[:max_glyphs]

    with _open_backend(font_path, renderer) as backend:
        reported_upem = backend.reported_upem()
        upem_used = reported_upem if reported_upem is not None else upem

        # Global / vertical metrics (single render)
        global_dicts = _measure_global(backend, size_px=size_px, upem=upem_used)

        glyphs: dict[str, GlyphMetric] = {}
        # Pixel-space advances retained for downstream kerning measurement
        # (the kerning measurer needs left-glyph advance in *pixels*, not
        # in font units, to compute the cursor delta).
        advances_px: dict[int, float] = {}
        hangul_monospace_used = False
        hangul_common_advance: int | None = None
        hangul_common_advance_px: float | None = None

        # Hangul fast-path: if the Syllables block is monospace, measure
        # one syllable and replicate to the other 11,171.
        if detect_monospace:
            hangul_cps, other_cps = _partition_hangul_syllables(cmap)
            if len(hangul_cps) >= len(HANGUL_MONOSPACE_PROBES):
                is_mono, common_px = _hangul_is_monospace(
                    backend, size_px=size_px)
                if is_mono and common_px is not None:
                    hangul_monospace_used = True
                    hangul_common_advance_px = common_px
                    hangul_common_advance = pixel_to_unit(
                        common_px, size_px=size_px, upem=upem_used)
                    # Replicate ADVANCE across the block. LSB is per-syllable
                    # even when advance is uniform (Korean syllables share
                    # the same advance box but the ink position inside it
                    # varies), so we still single-render each syllable for
                    # LSB if include_lsb=True. Even so, the per-syllable LSB
                    # probe is ~4× cheaper than the 4-repeat advance probe,
                    # so the fast-path still pays off.
                    for cp in hangul_cps:
                        lsb_units: int | None = None
                        if include_lsb:
                            lsb_px = probe_lsb_only(
                                backend, chr(cp), size_px=size_px)
                            if lsb_px is not None:
                                lsb_units = pixel_to_unit(
                                    lsb_px, size_px=size_px, upem=upem_used)
                        glyphs[codepoint_to_id(cp)] = GlyphMetric(
                            advanceWidth=hangul_common_advance,
                            lsb=lsb_units,
                        )
                        advances_px[cp] = common_px
                    cmap_to_measure = other_cps
                else:
                    cmap_to_measure = cmap
            else:
                cmap_to_measure = cmap
        else:
            cmap_to_measure = cmap

        for i, cp in enumerate(cmap_to_measure):
            ch = chr(cp)
            try:
                if include_lsb:
                    adv_px, lsb_px = probe_advance_and_lsb(
                        backend, ch, size_px=size_px)
                else:
                    adv_px = probe_advance(backend, ch, size_px=size_px)
                    lsb_px = None
            except Exception:
                continue
            adv_units = pixel_to_unit(adv_px, size_px=size_px, upem=upem_used)
            lsb_units = (pixel_to_unit(lsb_px, size_px=size_px, upem=upem_used)
                         if lsb_px is not None else None)
            glyphs[codepoint_to_id(cp)] = GlyphMetric(
                advanceWidth=adv_units, lsb=lsb_units)
            advances_px[cp] = adv_px
            if progress and (i + 1) % 500 == 0:
                print(f"  ... {i + 1}/{len(cmap_to_measure)} glyphs measured")

    # P4: kerning pair extraction (opt-in, runs after the backend
    # `with` block since the kerning module opens its own HarfBuzz
    # font handle independent of the render backend)
    kerning: list[KerningPair] | None = None
    if include_kerning and not skip_kerning:
        if pair_candidates is None:
            pair_candidates = default_pair_candidates(cmap=cmap)
        if progress:
            print(f"  measuring {len(pair_candidates)} kerning pairs...")
        kerning = extract_kerning_pairs(
            font_path, pair_candidates,
            threshold_units=kern_threshold_units,
            progress=progress,
        )

    global_metrics = GlobalMetrics(
        unitsPerEm=upem_used,
        head=global_dicts["head"],
        hhea=global_dicts["hhea"],
        os2=global_dicts["os2"],
        post=global_dicts["post"],
    )
    source: dict = {
        "filename": font_path.name,
        "extractedVia": "render",
        "renderer": renderer,
        "renderSizePx": size_px,
        "reportedUpem": reported_upem,
    }
    if hangul_monospace_used:
        source["hangulMonospace"] = {
            "detected": True,
            "commonAdvance": hangul_common_advance,
            "syllablesReplicated": sum(
                1 for cp in cmap if 0xAC00 <= cp <= 0xD7A3),
        }
    spec = MetricsSpec(
        source=source,
        global_metrics=global_metrics,
        glyphs=glyphs,
        kerning=kerning,
    )
    return spec
