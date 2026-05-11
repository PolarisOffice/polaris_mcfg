"""M8 — Render-based metric extractor.

This is the EULA-safe alternative to the default file-parsing extractor.
Instead of reading TrueType/OpenType tables directly, it renders the font
through a normal rendering pipeline (FreeType, headless browser, or OS
text API) and measures the resulting pixels to recover metrics.

Design: see ``docs/design/12-render-extractor.md``.

Usage::

    from polaris_mcfg.render_extractor import extract_via_render
    spec = extract_via_render("font.ttf", renderer="freetype")

The output is a :class:`polaris_mcfg.schema.MetricsSpec` identical in shape
to the file-backend output, but with ±1~2 unit measurement noise.
"""
from __future__ import annotations

from .orchestrator import extract_via_render

__all__ = ["extract_via_render"]
