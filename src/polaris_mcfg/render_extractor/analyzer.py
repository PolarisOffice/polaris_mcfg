"""ImageAnalyzer — extract metrics from rendered pixel buffers.

Given a :class:`RenderResult` from a backend, this module measures:

- Per-glyph pixel bounding boxes (for LSB and bbox).
- Sub-pixel advance via "N-repeat linear fit": render the same glyph N
  times in a row and linear-fit the N first-pixel positions; the slope
  is the true advance.
- Baseline / cap-height / x-height / descender depth from key reference
  glyphs.

All measurements are in *pixels* of the rendered buffer. Conversion to
font units is done by :mod:`units` using the size and inferred UPM.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .backends import GlyphRender, RenderResult

# Pixels with alpha >= this threshold count as ink. 16/255 ≈ 6% — well
# below font hint AA but above stray subpixel-AA bleed.
INK_THRESHOLD = 16


@dataclass
class GlyphBBox:
    """Pixel-space bbox of a single rendered glyph.

    Coordinates use the same origin as the parent :attr:`RenderResult.image`
    (top-left = (0, 0)). Empty glyphs (whitespace) have width 0 and height 0
    but still carry a defined ``pen_x`` so advance measurement works.
    """
    char: str
    pen_x: float        # cursor x at the moment this glyph was drawn
    ink_left: float | None    # leftmost ink pixel x, None if empty
    ink_right: float | None
    ink_top: float | None
    ink_bottom: float | None

    @property
    def is_empty(self) -> bool:
        return self.ink_left is None

    @property
    def width(self) -> float:
        if self.is_empty:
            return 0.0
        return self.ink_right - self.ink_left


def measure_glyph_bbox(image: np.ndarray, gr: GlyphRender,
                       canvas_left: float = 0.0) -> GlyphBBox:
    """Find the inked sub-rectangle of one glyph using its individual bitmap.

    We rely on the per-glyph bitmap captured by the backend — that
    sidesteps the problem of identifying which pixels belong to which
    glyph in a multi-character image (adjacent glyphs can overlap).
    """
    bitmap = gr.bitmap
    if bitmap.size == 0 or not (bitmap >= INK_THRESHOLD).any():
        return GlyphBBox(
            char=gr.char,
            pen_x=gr.pen_x,
            ink_left=None,
            ink_right=None,
            ink_top=None,
            ink_bottom=None,
        )
    rows = np.any(bitmap >= INK_THRESHOLD, axis=1)
    cols = np.any(bitmap >= INK_THRESHOLD, axis=0)
    row_idx = np.where(rows)[0]
    col_idx = np.where(cols)[0]
    top_local = float(row_idx.min())
    bottom_local = float(row_idx.max() + 1)
    left_local = float(col_idx.min())
    right_local = float(col_idx.max() + 1)
    # Translate to canvas coords.
    canvas_pen_x = gr.pen_x + canvas_left
    return GlyphBBox(
        char=gr.char,
        pen_x=canvas_pen_x,
        ink_left=canvas_pen_x + gr.bitmap_left + left_local,
        ink_right=canvas_pen_x + gr.bitmap_left + right_local,
        ink_top=gr.pen_y - gr.bitmap_top + top_local,
        ink_bottom=gr.pen_y - gr.bitmap_top + bottom_local,
    )


def measure_advance_repeated(result: RenderResult) -> float:
    """Measure the advance of a single-character N-repeat render via linear fit.

    The render is expected to be ``"X" * N`` for some glyph X and some
    N >= 2. The function returns the average advance in pixels via
    least-squares fit on the N pen positions (which the backend reports
    cumulatively). Sub-pixel precision: ~ ±0.25 px for N=4.
    """
    if len(result.glyphs) < 2:
        raise ValueError("measure_advance_repeated requires N >= 2 glyphs.")
    xs = np.array([g.pen_x for g in result.glyphs], dtype=float)
    ys = np.arange(len(xs), dtype=float)
    # Fit ys = slope_inv * xs + intercept_inv → xs = (1/slope_inv) * ys + ...
    # Easier: fit xs = m * ys + b directly. m is the per-step advance.
    A = np.vstack([ys, np.ones_like(ys)]).T
    m, _b = np.linalg.lstsq(A, xs, rcond=None)[0]
    return float(m)


def measure_baseline_metrics(result: RenderResult,
                             ref_chars: dict[str, str]) -> dict[str, float]:
    """Measure vertical metrics from a single render containing reference
    characters.

    Parameters
    ----------
    result : RenderResult
        Render of e.g. ``"HxgjQ"`` at a known size.
    ref_chars : dict
        Maps semantic role to character. Recognized keys:

        - ``cap``: a flat-topped capital, used for cap height. Default ``"H"``.
        - ``x``: a small x-height letter (``"x"``).
        - ``desc``: a descender (``"g"`` or ``"j"``).
        - ``asc``: an ascender (``"l"`` or ``"H"``).

    Returns
    -------
    dict
        Pixel-space measurements: ``cap_height``, ``x_height``,
        ``descent``, ``ascent``. All relative to ``result.baseline_y``.
    """
    bboxes = {g.char: measure_glyph_bbox(result.image, g) for g in result.glyphs}
    out: dict[str, float] = {}
    baseline = result.baseline_y
    if "cap" in ref_chars and ref_chars["cap"] in bboxes:
        b = bboxes[ref_chars["cap"]]
        if not b.is_empty:
            out["cap_height"] = baseline - b.ink_top
    if "x" in ref_chars and ref_chars["x"] in bboxes:
        b = bboxes[ref_chars["x"]]
        if not b.is_empty:
            out["x_height"] = baseline - b.ink_top
    if "desc" in ref_chars and ref_chars["desc"] in bboxes:
        b = bboxes[ref_chars["desc"]]
        if not b.is_empty:
            out["descent"] = b.ink_bottom - baseline
    if "asc" in ref_chars and ref_chars["asc"] in bboxes:
        b = bboxes[ref_chars["asc"]]
        if not b.is_empty:
            out["ascent"] = baseline - b.ink_top
    return out


def measure_line_gap(result_two_line: RenderResult,
                     baseline_a_y: float, baseline_b_y: float,
                     ascent_px: float, descent_px: float) -> float:
    """Given a two-line render, baseline gap = ascent + descent + lineGap.

    Returns the inferred lineGap in pixels.
    """
    gap = abs(baseline_b_y - baseline_a_y) - ascent_px - descent_px
    return float(gap)
