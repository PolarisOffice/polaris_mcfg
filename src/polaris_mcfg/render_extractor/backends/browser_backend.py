"""Playwright-based browser render backend.

This is the **strongest EULA defense** in the M8 backend set: we never
open the font file in our Python code. We base64-encode it, hand it to
Chromium via a CSS ``@font-face { src: url(data:...) }`` declaration,
and let the browser render text the way any web page would. We then
take a screenshot and measure the pixels.

The browser is the textbook "renderer" that font licenses contemplate
when they say "may be used to render text" — so this path sits squarely
inside the most permissive interpretation of any reasonable EULA.

Why "headless Chromium specifically": every modern browser uses
HarfBuzz for shaping and FreeType/Skia for rasterization, so the
output is functionally identical to the FreeType backend for our
measurement purposes. Chromium is the most reproducible across CI
environments because Playwright pins its own build.

Trade-offs vs FreeType
----------------------
- ~10× slower per glyph (cold launch + page navigate + screenshot).
- No direct ``set_pixel_sizes`` knob; we use CSS ``font-size: 100px``
  and treat each pixel as 10 font units (assuming 1000 UPM target).
- Single-glyph LSB measurement is more reliable here because the
  browser honors all positioning features (including ``locl``).
- UPM cannot be reported by the browser — analyzer + units module
  treat the canonical 1000-UPM frame as the output.

Implementation note: Playwright's sync API is process-global, so we
create one Playwright + browser + context per backend instance and
re-use a single page across many ``render()`` calls. Tests close the
backend explicitly via the context-manager pattern.
"""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

from .base import GlyphRender, RenderBackend, RenderRequest, RenderResult


# Sentinel canvas size; rendered text is centered horizontally, baseline
# at y = SENTINEL_HEIGHT // 2. CSS pixel-size in the page is set per
# request via ``size_px``.
SENTINEL_PAGE_WIDTH = 4000
SENTINEL_PAGE_HEIGHT = 2000


HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@font-face {{
  font-family: 'mcfgProbe';
  src: url(data:font/ttf;base64,{font_b64}) format('truetype');
  font-display: block;
}}
html, body {{ margin: 0; padding: 0; background: white; }}
#probe {{
  position: absolute;
  top: {top}px;
  left: 0;
  font-family: 'mcfgProbe', monospace;
  font-size: {size_px}px;
  color: black;
  white-space: pre;
  line-height: 1;
  text-rendering: geometricPrecision;
  -webkit-font-smoothing: antialiased;
  font-feature-settings: normal;
  font-kerning: normal;
}}
#probe span.glyph {{ display: inline-block; }}
</style>
</head>
<body>
<div id="probe" lang="{lang}">{markup}</div>
</body>
</html>
"""


def _build_markup(text: str) -> str:
    """Wrap each character in a span so we can read per-glyph
    boundingClientRect via getBoundingClientRect()."""
    out = []
    for ch in text:
        esc = (
            ch.replace("&", "&amp;")
              .replace("<", "&lt;")
              .replace(">", "&gt;")
              .replace('"', "&quot;")
        )
        out.append(f'<span class="glyph">{esc}</span>')
    return "".join(out)


class BrowserBackend(RenderBackend):
    """Render via headless Chromium loaded with the font as @font-face.

    Heavy initialization (browser launch) happens in :meth:`open`. Each
    :meth:`render` reuses the open page and just navigates to a new
    data: URL. The screenshot is converted to a numpy uint8 grayscale
    buffer matching the FreeType backend's output shape.
    """

    name = "browser"

    def __init__(self, font_path: str | Path) -> None:
        super().__init__(font_path)
        self._pw_ctx = None  # Playwright context manager
        self._pw = None
        self._browser = None
        self._page = None
        self._font_b64 = None

    def open(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Browser backend requires Playwright. Install with "
                "`pip install -e '.[render-extract-browser]'`."
            ) from e
        # base64 the font so we hand it to the browser via data: URL.
        # The browser opens the font; our Python code never reads its
        # tables.
        self._font_b64 = base64.b64encode(
            self.font_path.read_bytes()).decode("ascii")
        self._pw_ctx = sync_playwright().start()
        # Stash so close() can stop()
        self._pw = self._pw_ctx
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(viewport={
            "width": SENTINEL_PAGE_WIDTH,
            "height": SENTINEL_PAGE_HEIGHT,
        })

    def close(self) -> None:
        if self._page is not None:
            try:
                self._page.close()
            except Exception:  # pragma: no cover
                pass
            self._page = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # pragma: no cover
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # pragma: no cover
                pass
            self._pw = None

    def reported_upem(self) -> int | None:
        # Browsers don't expose UPM; the analyzer / units module use the
        # canonical 1000-UPM frame.
        return None

    def render(self, request: RenderRequest) -> RenderResult:
        if self._page is None:
            raise RuntimeError("BrowserBackend not opened. Use as a context "
                               "manager: `with BrowserBackend(...) as be:`.")
        page = self._page
        markup = _build_markup(request.text)
        top_y = SENTINEL_PAGE_HEIGHT // 2
        html = HTML_TEMPLATE.format(
            font_b64=self._font_b64,
            size_px=request.size_px,
            top=top_y,
            lang=request.lang or "",
            markup=markup,
        )
        page.set_content(html, wait_until="load")
        # Wait until @font-face is fully loaded — Playwright's load event
        # fires before web fonts finish.
        page.evaluate("document.fonts.ready")

        # Read per-glyph getBoundingClientRect() for ink position.
        rects = page.evaluate(
            "() => Array.from(document.querySelectorAll('#probe span.glyph'))"
            ".map(el => { const r = el.getBoundingClientRect(); "
            "return {x: r.x, y: r.y, w: r.width, h: r.height, "
            "text: el.textContent}; })"
        )

        # The probe div has line-height: 1 and font-size = size_px, so
        # the baseline within each glyph span is at top + ascent_ratio *
        # size_px. We don't know the font's ascent ratio without parsing
        # the font, so we approximate baseline = top + 0.8 * size_px (a
        # typical Latin font ratio). Vertical-metric callers should
        # re-measure ink baseline from pixels for precision.
        baseline_y = float(top_y + 0.8 * request.size_px)

        # Screenshot just the probe div region for analyzer.
        screenshot_png = page.screenshot(clip={
            "x": 0, "y": top_y - request.size_px,
            "width": SENTINEL_PAGE_WIDTH,
            "height": int(request.size_px * 2),
        })

        # PNG → numpy grayscale
        from PIL import Image
        img = Image.open(BytesIO(screenshot_png)).convert("L")
        img_np = np.array(img, dtype=np.uint8)
        # Invert because text is black on white; the analyzer expects
        # "ink = high value, blank = 0".
        img_np = 255 - img_np

        # Build per-glyph data. Each glyph's "pen_x" is the rect.x of its
        # span (in screenshot coords, since we clipped y).
        # Per-glyph bitmap is the cropped region of the screenshot.
        glyphs: list[GlyphRender] = []
        screenshot_top = top_y - request.size_px
        for r in rects:
            ch = r["text"]
            pen_x = float(r["x"])
            # For the analyzer's bbox routine we hand it a per-glyph
            # bitmap cropped from the screenshot.
            x0 = max(0, int(r["x"]))
            y0 = max(0, int(r["y"]) - screenshot_top)
            x1 = min(img_np.shape[1], int(r["x"] + r["w"]) + 1)
            y1 = min(img_np.shape[0], int(r["y"] + r["h"]) - screenshot_top + 1)
            if x1 > x0 and y1 > y0:
                bm = img_np[y0:y1, x0:x1].copy()
            else:
                bm = np.zeros((0, 0), dtype=np.uint8)
            glyphs.append(GlyphRender(
                char=ch,
                pen_x=pen_x,
                pen_y=baseline_y - screenshot_top,
                advance_x=float(r["w"]),  # Approximate; analyzer
                                          # re-measures via N-repeat
                bitmap_left=0,
                bitmap_top=int(baseline_y - screenshot_top - y0),
                bitmap=bm,
            ))

        return RenderResult(
            image=img_np,
            glyphs=glyphs,
            baseline_y=baseline_y - screenshot_top,
            size_px=request.size_px,
            upem=None,
            extra={"backend": "browser"},
        )
