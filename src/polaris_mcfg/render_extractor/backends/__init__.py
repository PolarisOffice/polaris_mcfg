"""Render backends for the M8 image-based extractor.

Each backend implements :class:`base.RenderBackend`. The orchestrator
picks one based on ``--renderer`` (or auto-selects).
"""
from __future__ import annotations

from .base import GlyphRender, RenderBackend, RenderRequest, RenderResult

__all__ = ["RenderBackend", "RenderRequest", "RenderResult", "GlyphRender"]
