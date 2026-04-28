"""M6 — HarfBuzz-based rendering regression helpers.

Used by the validator (``--render-test``) and reused by the HTML report to
measure shaped line widths in font units.

``uharfbuzz`` is an optional dependency; importing this module fails clearly
when it isn't installed, but only at the point of use.
"""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from fontTools.ttLib import TTFont

try:
    import uharfbuzz as hb
except ImportError as e:  # pragma: no cover
    hb = None
    _HB_IMPORT_ERROR = e
else:
    _HB_IMPORT_ERROR = None


def _require_hb() -> None:
    if hb is None:  # pragma: no cover
        raise RuntimeError(
            "uharfbuzz is required for rendering tests but is not installed. "
            "From a checkout: `pip install -e '.[dev]'`. "
            "Standalone: `pip install uharfbuzz`."
        ) from _HB_IMPORT_ERROR


@dataclass
class LineMeasurement:
    text: str
    width: int  # in font units, sum of x_advances
    glyph_count: int

    def to_dict(self) -> dict:
        return {"text": self.text, "width": self.width,
                "glyphCount": self.glyph_count}


@dataclass
class RenderComparison:
    font_a: str
    font_b: str
    upem_a: int
    upem_b: int
    lines: list[dict] = field(default_factory=list)
    """Each entry: ``{text, widthA, widthB, deltaPct, normalizedWidthA/B}``."""
    tolerance_pct: float = 0.0
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "fontA": self.font_a, "fontB": self.font_b,
            "upemA": self.upem_a, "upemB": self.upem_b,
            "tolerancePct": self.tolerance_pct,
            "passed": self.passed,
            "lines": self.lines,
        }


@contextmanager
def _hb_readable_path(font_path: str | Path):
    """Yield a path HarfBuzz can read directly.

    HarfBuzz/uharfbuzz reads OpenType from raw TTF/OTF bytes; it does *not*
    transparently decompress WOFF / WOFF2. For those flavors we materialize
    a TTF copy in a temp file and yield that.

    Implementation note: we use ``mkstemp`` + immediate ``os.close`` rather
    than ``NamedTemporaryFile`` because the latter holds the file open for
    the lifetime of the ``with`` block, which on Windows blocks unlinking
    (PermissionError [WinError 32]). HarfBuzz may also keep a memory-
    mapped view of the file alive after our local handles drop, so on
    Windows the unlink can still race; we treat that as benign and let the
    OS clean up the temp file later.
    """
    import os
    p = Path(font_path)
    if p.suffix.lower() not in (".woff", ".woff2"):
        yield str(p)
        return

    fd, tmp_path = tempfile.mkstemp(suffix=".ttf")
    os.close(fd)
    try:
        ft = TTFont(str(p))
        ft.flavor = None
        ft.save(tmp_path)
        ft.close()
        yield tmp_path
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except (PermissionError, OSError):
            # Windows: HarfBuzz mapping may still be live. Temp file gets
            # collected by the OS on next reboot or %TEMP% sweep.
            pass


def measure_line(font_path: str | Path, text: str) -> LineMeasurement:
    """Shape ``text`` with the font and return the total x-advance."""
    _require_hb()
    with _hb_readable_path(font_path) as path:
        blob = hb.Blob.from_file_path(path)
        face = hb.Face(blob)
        font = hb.Font(face)

        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf)

        width = sum(p.x_advance for p in buf.glyph_positions)
    return LineMeasurement(text=text, width=width,
                           glyph_count=len(buf.glyph_positions))


def measure_lines(font_path: str | Path,
                  texts: Iterable[str]) -> list[LineMeasurement]:
    """Shape multiple texts with one font handle (avoids re-opening)."""
    _require_hb()
    text_list = [t for t in texts if t]
    if not text_list:
        return []
    with _hb_readable_path(font_path) as path:
        blob = hb.Blob.from_file_path(path)
        face = hb.Face(blob)
        font = hb.Font(face)
        out: list[LineMeasurement] = []
        for t in text_list:
            buf = hb.Buffer()
            buf.add_str(t)
            buf.guess_segment_properties()
            hb.shape(font, buf)
            out.append(LineMeasurement(
                text=t,
                width=sum(p.x_advance for p in buf.glyph_positions),
                glyph_count=len(buf.glyph_positions),
            ))
    return out


def compare_rendering(font_a: str | Path, font_b: str | Path,
                      texts: Iterable[str],
                      *, tolerance_pct: float = 1.0,
                      normalize_upm: bool = True) -> RenderComparison:
    """Shape ``texts`` with both fonts and compare normalized line widths.

    ``tolerance_pct`` is the maximum allowed |delta| as a percentage of A's
    line width, after optional UPM normalization.
    """
    _require_hb()
    text_list = [t for t in texts if t]
    a_meas = measure_lines(font_a, text_list)
    b_meas = measure_lines(font_b, text_list)

    with _hb_readable_path(font_a) as p_a, _hb_readable_path(font_b) as p_b:
        a_face = hb.Face(hb.Blob.from_file_path(p_a))
        b_face = hb.Face(hb.Blob.from_file_path(p_b))
        upem_a, upem_b = a_face.upem, b_face.upem

    cmp = RenderComparison(font_a=str(font_a), font_b=str(font_b),
                           upem_a=upem_a, upem_b=upem_b,
                           tolerance_pct=tolerance_pct)
    overall_pass = True
    for a, b in zip(a_meas, b_meas):
        if normalize_upm and upem_a != upem_b:
            ref = max(upem_a, upem_b)
            wa = round(a.width * ref / upem_a)
            wb = round(b.width * ref / upem_b)
        else:
            wa, wb = a.width, b.width
        if wa == 0:
            delta_pct = 0.0 if wb == 0 else float("inf")
        else:
            delta_pct = abs(wb - wa) / wa * 100.0
        line_pass = delta_pct <= tolerance_pct
        overall_pass = overall_pass and line_pass
        cmp.lines.append({
            "text": a.text,
            "widthA": a.width,
            "widthB": b.width,
            "normalizedWidthA": wa,
            "normalizedWidthB": wb,
            "deltaPct": round(delta_pct, 4),
            "passed": line_pass,
        })
    cmp.passed = overall_pass
    return cmp


#: Default sample texts covering Hangul / Latin / digits / common punctuation.
DEFAULT_RENDER_TEXTS = (
    "The quick brown fox jumps over the lazy dog.",
    "0123456789",
    "다람쥐 헌 쳇바퀴에 타고파.",
    "소스 폰트 메트릭 호환성 검증.",
    "Polaris MCFG: Metric-Compatible Font Generator.",
    "한글 + English + 123 + ,.;:'\"!?",
)


def load_render_texts(path: str | Path | None) -> list[str]:
    """Load newline-separated sample texts; falls back to defaults."""
    if path is None:
        return list(DEFAULT_RENDER_TEXTS)
    return [ln.rstrip("\n") for ln in
            Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
