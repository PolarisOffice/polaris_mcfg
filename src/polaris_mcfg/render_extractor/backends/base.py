"""RenderBackend abstract interface.

A backend is anything that can:
1. Open a font from disk (or load it into a rendering context).
2. Render a sequence of characters at a given size to a grayscale buffer.
3. Report the pixel buffer + per-character pen-position (cursor x).

Crucially, the backend is the only component that ever touches the font
file. Higher layers (analyzer, assembler) only see pixel arrays — that
keeps the EULA-safe boundary inside this one module.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class RenderRequest:
    """A single text snippet to render.

    ``text`` is the unicode string. ``size_px`` is the requested EM size in
    pixels (FreeType "26.6" pixel size; for the browser backend this maps
    to CSS ``font-size``). ``lang`` is an optional BCP-47 tag used by
    backends that honor it (browser). ``hinting`` defaults to off because
    grid-fitting introduces integer snap noise that destroys sub-pixel
    measurement accuracy.
    """
    text: str
    size_px: int = 1000
    lang: str | None = None
    hinting: bool = False


@dataclass
class GlyphRender:
    """One glyph's rasterized bitmap + the pen position before drawing it.

    All values are in *pixels*, in the coordinate system of the returned
    pixel buffer. ``pen_x`` is the cursor x position at the moment this
    glyph was drawn (relative to render origin). ``advance_x`` is the
    backend-reported pen advance after this glyph; the analyzer doesn't
    trust this — it re-measures from pixels — but it's exposed here as
    a sanity check.
    """
    char: str
    pen_x: float
    pen_y: float
    advance_x: float
    bitmap_left: int
    bitmap_top: int
    bitmap: np.ndarray  # 2D uint8, 0=blank, 255=ink


@dataclass
class RenderResult:
    """Output of one :meth:`RenderBackend.render` call.

    ``image`` is the final composited grayscale buffer. ``glyphs`` is the
    per-glyph data; for a request of N characters there are N entries.
    ``baseline_y`` is the pixel row of the rendering baseline (positive
    descent below).
    """
    image: np.ndarray  # 2D uint8
    glyphs: list[GlyphRender]
    baseline_y: float
    size_px: int
    upem: int | None = None  # If the backend can report it without
                              # parsing the font ourselves. Browser backend
                              # leaves this None; FreeType fills it.
    extra: dict = field(default_factory=dict)


class RenderBackend(ABC):
    """Abstract render backend.

    Concrete backends must implement :meth:`render`. Backends are stateful
    (they hold an open font handle) and used as context managers::

        with FreeTypeBackend(font_path) as be:
            result = be.render(RenderRequest(text="HHHH"))
    """

    name: str = "base"

    def __init__(self, font_path: str | Path) -> None:
        self.font_path = Path(font_path)

    def __enter__(self) -> "RenderBackend":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:  # pragma: no cover - default no-op
        pass

    def close(self) -> None:  # pragma: no cover - default no-op
        pass

    @abstractmethod
    def render(self, request: RenderRequest) -> RenderResult:
        """Rasterize the request and return the result."""

    @abstractmethod
    def reported_upem(self) -> int | None:
        """UPM as reported by the backend, if available without parsing.

        For FreeType this is ``face.units_per_EM``. For browser backends
        this is generally not available (returns None) and must be
        inferred by the analyzer.
        """
