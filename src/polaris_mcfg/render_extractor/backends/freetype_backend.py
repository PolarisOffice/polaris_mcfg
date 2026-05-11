"""FreeType-based render backend.

Notes on the EULA boundary
--------------------------
FreeType *does* parse the font file under the hood — but it does so in C,
through a stable public-API rendering pipeline. Our Python code never
sees a font table; we only see pixels and pen positions. This is a
weaker EULA defense than the browser backend (which uses an even more
distant indirection: OS rendering via Chromium), but it's strong enough
for most "no reverse engineering" clauses since FreeType is universally
accepted as a renderer.

Hinting
-------
Hinting is off by default (FT_LOAD_NO_HINTING + FT_LOAD_NO_AUTOHINT).
Hinting snaps stems to integer pixel grids, which adds ±1 px noise to
sub-pixel measurements. Off = smoother outlines, more accurate sub-pixel
edge detection.

Subpixel AA is also off (we render to a single-channel gray buffer).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import GlyphRender, RenderBackend, RenderRequest, RenderResult


class FreeTypeBackend(RenderBackend):
    """FreeType-driven renderer.

    ``size_px`` in the :class:`RenderRequest` is used as the EM pixel size
    (``set_pixel_sizes(0, size_px)``). At ``size_px = 1000`` for a 1000-UPM
    font, 1 font unit ≈ 1 pixel — which is the sweet spot for
    sub-pixel-precision measurement without massive PNG sizes.
    """

    name = "freetype"

    def __init__(self, font_path: str | Path,
                 workdir: str | Path | None = None) -> None:
        super().__init__(font_path, workdir=workdir)
        self._face = None
        self._face_index = 0  # First face in a .ttc (M8 doesn't iterate)

    def open(self) -> None:
        # Import lazily so users without the optional extra don't crash on
        # `import polaris_mcfg`.
        try:
            import freetype
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "FreeType backend requires `freetype-py`. Install with "
                "`pip install -e '.[render-extract]'` (from a checkout) or "
                "`pip install freetype-py`."
            ) from e
        self._face = freetype.Face(str(self.font_path), index=self._face_index)

    def close(self) -> None:
        # freetype-py Face doesn't expose .done(); rely on GC.
        self._face = None

    def reported_upem(self) -> int | None:
        if self._face is None:
            return None
        return int(self._face.units_per_EM)

    def _load_flags(self, hinting: bool) -> int:
        import freetype
        if hinting:
            flags = freetype.FT_LOAD_DEFAULT | freetype.FT_LOAD_RENDER
        else:
            flags = (
                freetype.FT_LOAD_NO_HINTING
                | freetype.FT_LOAD_NO_AUTOHINT
                | freetype.FT_LOAD_RENDER
            )
        return flags

    def _do_render(self, request: RenderRequest) -> RenderResult:
        if self._face is None:
            raise RuntimeError("FreeTypeBackend not opened. Use as a context "
                               "manager: `with FreeTypeBackend(...) as be:`.")

        face = self._face
        # Use pixel sizing so 1pt math is trivial.
        face.set_pixel_sizes(0, request.size_px)
        flags = self._load_flags(request.hinting)

        # First pass: measure total width + max ascent/descent in pixels.
        # FreeType reports metrics in 26.6 fixed-point; we convert to float
        # pixels by dividing by 64.
        pen_x_subpx = 0  # in 26.6
        ascent_px = face.size.ascender / 64.0
        descent_px = -face.size.descender / 64.0  # FT descender is negative

        # We need a 2-pass approach because the bitmap is uint8 and we need
        # to know its dimensions upfront. First pass measures the bbox.
        max_top = 0
        max_bottom = 0
        glyph_records: list[tuple[str, int, int, int, int]] = []  # char, pen_x_26_6, left, top, advance_26_6 — bitmap captured in pass 2
        for ch in request.text:
            face.load_char(ch, flags)
            g = face.glyph
            bm = g.bitmap
            # Top edge of bitmap = g.bitmap_top above baseline
            top = g.bitmap_top
            bottom = bm.rows - g.bitmap_top
            if top > max_top:
                max_top = top
            if bottom > max_bottom:
                max_bottom = bottom
            glyph_records.append((ch, pen_x_subpx, g.bitmap_left, g.bitmap_top,
                                  g.advance.x))
            pen_x_subpx += g.advance.x

        # Now allocate canvas: width = total advance + small margin.
        canvas_width = max(1, int(pen_x_subpx / 64.0) + 64)
        canvas_top_pad = max(int(ascent_px), max_top) + 8
        canvas_bottom_pad = max(int(descent_px), max_bottom) + 8
        canvas_height = canvas_top_pad + canvas_bottom_pad
        baseline_y = float(canvas_top_pad)

        image = np.zeros((canvas_height, canvas_width), dtype=np.uint8)

        glyphs: list[GlyphRender] = []
        for (ch, pen_x_26_6, left, top, advance_26_6) in glyph_records:
            face.load_char(ch, flags)
            g = face.glyph
            bm = g.bitmap
            buf = bm.buffer
            rows, width, pitch = bm.rows, bm.width, bm.pitch
            if rows == 0 or width == 0:
                bitmap_np = np.zeros((0, 0), dtype=np.uint8)
            else:
                # FreeType pitch can be negative (origin at top vs bottom);
                # for our LCD-off gray render it's almost always positive.
                # Build a numpy view, then copy out.
                if pitch < 0:
                    arr = np.frombuffer(bytes(buf), dtype=np.uint8)
                    bitmap_np = arr.reshape((rows, -pitch))[:, :width].copy()
                    bitmap_np = bitmap_np[::-1, :].copy()
                else:
                    arr = np.frombuffer(bytes(buf), dtype=np.uint8)
                    bitmap_np = arr.reshape((rows, pitch))[:, :width].copy()

            pen_x_px = pen_x_26_6 / 64.0
            blit_x = int(round(pen_x_px + left))
            blit_y = int(round(baseline_y - top))

            if rows > 0 and width > 0:
                y0, y1 = max(0, blit_y), min(canvas_height, blit_y + rows)
                x0, x1 = max(0, blit_x), min(canvas_width, blit_x + width)
                if y1 > y0 and x1 > x0:
                    bm_y0, bm_x0 = y0 - blit_y, x0 - blit_x
                    bm_y1, bm_x1 = bm_y0 + (y1 - y0), bm_x0 + (x1 - x0)
                    # OR-blit (additive) since canvas starts at 0; clipping
                    # to 255 protects against overlapping glyph rare cases.
                    region = image[y0:y1, x0:x1]
                    addend = bitmap_np[bm_y0:bm_y1, bm_x0:bm_x1]
                    np.maximum(region, addend, out=region)

            glyphs.append(GlyphRender(
                char=ch,
                pen_x=pen_x_px,
                pen_y=baseline_y,
                advance_x=advance_26_6 / 64.0,
                bitmap_left=left,
                bitmap_top=top,
                bitmap=bitmap_np,
            ))

        return RenderResult(
            image=image,
            glyphs=glyphs,
            baseline_y=baseline_y,
            size_px=request.size_px,
            upem=self.reported_upem(),
            extra={"backend": "freetype"},
        )
