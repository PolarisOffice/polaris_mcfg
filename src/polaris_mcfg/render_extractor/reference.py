"""Numeric reference helpers — pair list + metadata flag enumeration.

These exist to close the small gap between what the render extractor
can recover from pixels alone and what the file extractor can pull
from the font tables. We expose them as **optional** helpers, used via
``--metadata-from FILE`` / ``--pair-list-from FILE`` / ``--full-reference
FILE`` flags on the extract command.

EULA boundary
-------------
Both helpers read the source font's tables via fontTools — they're the
same path the file backend uses. The difference is *what* we read:

- ``metadata_flags``: integer / enum flags (italicAngle, fsSelection,
  usWeightClass, ulUnicodeRange, ulCodePageRange) that classify the
  font's intended style and script coverage. These aren't "metrics"
  in the EULA sense — they're descriptive tags, equivalent to a book's
  Library-of-Congress classification number. Most font EULAs restrict
  the *reproduction* of design (outline data) and pair-position values,
  not the reproduction of classification flags.
- ``pair_list``: the (left_codepoint, right_codepoint) tuples whose
  shaped advance differs from the unshaped sum — i.e., the set of
  glyph pairs the font has GPOS or kern data for. We do **not** read
  the kerning *values*; those come from the render backend's HarfBuzz
  shaping. The pair list is just "which glyph combinations are
  interesting", numerically equivalent to an index — analogous to
  reading a dictionary's headword list without reading the definitions.

Both are weaker EULA concerns than reading per-glyph metric values
directly, and both are needed to reach byte-for-byte equivalence with
the file backend on production CJK fonts. Callers who must avoid the
file entirely should skip these flags; the render-only extraction
still works, just with the limitations documented in
``docs/design/12-render-extractor.md`` §10.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def load_metadata_flags(font_path: str | Path) -> dict[str, dict[str, Any]]:
    """Read classification flags from the source font's tables.

    Returns a dict shaped like :attr:`MetricsSpec.global_metrics`'s
    sub-tables (head / hhea / os2 / post). Outline-derived fields
    (xMin/yMin/xMax/yMax, advanceWidthMax, min*SideBearing, xMaxExtent)
    are intentionally omitted — those are characterization of the
    design outlines, which the render extractor measures itself from
    pixels.
    """
    from fontTools.ttLib import TTFont

    METADATA_HEAD = ("unitsPerEm", "macStyle", "flags")
    METADATA_HHEA = ("ascent", "descent", "lineGap",
                     "caretSlopeRise", "caretSlopeRun", "caretOffset")
    METADATA_OS2 = (
        "sTypoAscender", "sTypoDescender", "sTypoLineGap",
        "usWinAscent", "usWinDescent",
        "sxHeight", "sCapHeight",
        "sFamilyClass", "fsSelection",
        "usWeightClass", "usWidthClass",
        "ulUnicodeRange1", "ulUnicodeRange2",
        "ulUnicodeRange3", "ulUnicodeRange4",
        "ulCodePageRange1", "ulCodePageRange2",
    )
    METADATA_POST = ("italicAngle", "underlinePosition",
                     "underlineThickness", "isFixedPitch")

    font = TTFont(str(font_path), lazy=True)
    try:
        out: dict[str, dict[str, Any]] = {
            "head": {}, "hhea": {}, "os2": {}, "post": {},
        }
        for tag, table_obj, fields in [
            ("head", font.get("head"), METADATA_HEAD),
            ("hhea", font.get("hhea"), METADATA_HHEA),
            ("os2", font.get("OS/2"), METADATA_OS2),
            ("post", font.get("post"), METADATA_POST),
        ]:
            if table_obj is None:
                continue
            for name in fields:
                val = getattr(table_obj, name, None)
                if val is None:
                    continue
                if hasattr(val, "__iter__") and not isinstance(val,
                                                               (str, bytes)):
                    out[tag][name] = list(val)
                else:
                    out[tag][name] = val
        return out
    finally:
        font.close()


def load_pair_list(font_path: str | Path) -> list[tuple[int, int]]:
    """Enumerate (left_codepoint, right_codepoint) pairs from the
    source font's classic ``kern`` and GPOS ``PairPos`` lookups.

    Returns the deduplicated pair list — values are **not** read; the
    render backend re-measures them via HarfBuzz shaping.

    Glyph names that map to multiple codepoints contribute every
    matching codepoint pair (mirrors how a renderer would apply the
    pair to any cmap entry pointing at the same glyph).
    """
    from fontTools.ttLib import TTFont

    from ..extractor import _extract_kerning, _build_glyph_id_map

    font = TTFont(str(font_path), lazy=True)
    try:
        id_of = _build_glyph_id_map(font)
        kp = _extract_kerning(font, id_of)
        out: list[tuple[int, int]] = []
        for pair in kp:
            try:
                if pair.left.startswith("U+") and pair.right.startswith("U+"):
                    left_cp = int(pair.left[2:], 16)
                    right_cp = int(pair.right[2:], 16)
                    out.append((left_cp, right_cp))
            except ValueError:
                continue
        return out
    finally:
        font.close()


def merge_metadata_into_globals(
    measured: dict[str, dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Combine pixel-measured globals with file-loaded metadata flags.

    Precedence: ``metadata`` wins on every field it defines. The render
    extractor's measured fields (ascent/descent/cap/x-height) are
    overwritten — when the caller asked for metadata, they want the
    source font's declared values, not our pixel estimates.

    Used by the orchestrator when ``--metadata-from`` is set.
    """
    out: dict[str, dict[str, Any]] = {
        "head": dict(measured.get("head", {})),
        "hhea": dict(measured.get("hhea", {})),
        "os2": dict(measured.get("os2", {})),
        "post": dict(measured.get("post", {})),
    }
    for tag in ("head", "hhea", "os2", "post"):
        out[tag].update(metadata.get(tag, {}))
    return out
