"""Shaped-advance override extraction.

Same job as the file backend's ``_extract_shaped_advances`` (extractor.py)
— detect per-(codepoint, script, language) advance changes induced by
GSUB / GPOS — but driven through HarfBuzz shaping only, no direct
table inspection in our code.

Mechanism
---------
For each cmap codepoint we shape it twice:

1. With ``buf.guess_segment_properties()`` → "default" shape.
2. With ``buf.script = script; buf.language = lang`` → context shape.

If the total advance differs, the difference is a shape-induced override
that downstream consumers (the generator's ``--apply gsub``) can re-inject
into the design font.

EULA boundary
-------------
Identical to ``kerning.py``: HarfBuzz parses the file, our code reads
the shaped advance only. This matches what a web browser would observe
under different ``lang`` attributes.
"""
from __future__ import annotations

from pathlib import Path

from ..schema import ShapedAdvanceOverride, codepoint_to_id
from .kerning import _open_hb_font

# Same shaping contexts as the file extractor for parity.
DEFAULT_SHAPING_CONTEXTS = (
    ("hang", "KOR"),
    ("hani", "ZHS"),
    ("hani", "ZHT"),
    ("kana", "JAN"),
)


def _shape_total_advance(hb_module, hb_font, cp: int,
                         script: str | None = None,
                         language: str | None = None) -> int | None:
    """Shape one codepoint and return its total advance.

    None when the codepoint maps to .notdef (font doesn't cover it).
    """
    buf = hb_module.Buffer()
    buf.add_codepoints([cp])
    if script is not None and language is not None:
        buf.script = script
        buf.language = language
        buf.direction = "ltr"
    else:
        buf.guess_segment_properties()
    hb_module.shape(hb_font, buf)
    infos = buf.glyph_infos
    if not infos or any(info.codepoint == 0 for info in infos):
        return None
    return int(sum(p.x_advance for p in buf.glyph_positions))


def extract_shaped_advances(
    font_path: Path,
    cmap: list[int],
    contexts: tuple[tuple[str, str], ...] = DEFAULT_SHAPING_CONTEXTS,
    *,
    progress: bool = False,
) -> list[ShapedAdvanceOverride]:
    """Return per-(codepoint, script, language) overrides where shape
    differs from default.

    Reads no font tables in Python code — only HarfBuzz shaping output.
    """
    hb, font, _upem = _open_hb_font(font_path)

    out: list[ShapedAdvanceOverride] = []
    for i, cp in enumerate(cmap):
        default_adv = _shape_total_advance(hb, font, cp)
        if default_adv is None:
            continue
        for script, lang in contexts:
            ctx_adv = _shape_total_advance(hb, font, cp,
                                           script=script, language=lang)
            if ctx_adv is None or ctx_adv == default_adv:
                continue
            out.append(ShapedAdvanceOverride(
                codepoint=codepoint_to_id(cp),
                script=script,
                language=lang,
                advance=int(ctx_adv),
            ))
        if progress and (i + 1) % 2000 == 0:
            print(f"  ... shaped {i + 1}/{len(cmap)} codepoints probed, "
                  f"{len(out)} overrides kept")
    return out
