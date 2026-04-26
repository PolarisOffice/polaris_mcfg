"""M1 — Extract layout metrics from a TTF/OTF font.

Security boundary: the extractor must never touch glyph outline tables
(``glyf``, ``CFF``, ``CFF2``). ``fontTools.ttLib.TTFont(lazy=True)`` defers
parsing per-table on first access; we limit ourselves to the
``ALLOWED_TABLES`` whitelist below. ``test_extractor.py`` enforces this.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from pathlib import Path
from typing import Iterable

import click
from fontTools.ttLib import TTFont

from . import __version__
from .schema import (
    GlobalMetrics,
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    VerticalGlyphMetric,
    VerticalMetrics,
    codepoint_to_id,
    glyphname_to_id,
)

#: Tables the extractor is permitted to load. Every other table — notably
#: ``glyf``/``CFF``/``CFF2`` which carry copyrighted outline data — must remain
#: unread. See ``docs/design/02-metrics-schema.md`` §라이센스 안전 경계.
ALLOWED_TABLES = frozenset({
    "head", "hhea", "OS/2", "post", "hmtx", "cmap",
    "kern", "vhea", "vmtx",
    # GPOS would unlock advanced kerning extraction but is deferred to a later
    # milestone — the classic ``kern`` table is sufficient for v1.
})

HEAD_FIELDS = ("unitsPerEm", "xMin", "yMin", "xMax", "yMax", "macStyle", "flags")
HHEA_FIELDS = (
    "ascent", "descent", "lineGap", "advanceWidthMax",
    "minLeftSideBearing", "minRightSideBearing", "xMaxExtent",
    "caretSlopeRise", "caretSlopeRun", "caretOffset",
)
OS2_FIELDS = (
    "sTypoAscender", "sTypoDescender", "sTypoLineGap",
    "usWinAscent", "usWinDescent",
    "sxHeight", "sCapHeight",
    "sFamilyClass", "fsSelection",
)
POST_FIELDS = ("italicAngle", "underlinePosition", "underlineThickness",
               "isFixedPitch")
VHEA_FIELDS = ("ascent", "descent", "lineGap", "advanceHeightMax",
               "minTopSideBearing", "minBottomSideBearing", "yMaxExtent")


def _pick(table: object, fields: Iterable[str]) -> dict:
    out: dict = {}
    for name in fields:
        val = getattr(table, name, None)
        if val is None:
            continue
        # Coerce numeric tuples (e.g., panose) to plain lists for JSON.
        if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
            out[name] = list(val)
        else:
            out[name] = val
    return out


def _build_glyph_id_map(font: TTFont) -> dict[str, str]:
    """glyph_name → identifier (``U+XXXX`` if cmapped, else ``glyph#name``)."""
    cmap: dict[int, str] = font.getBestCmap() or {}
    name_to_cp: dict[str, int] = {}
    for cp, name in cmap.items():
        # First codepoint wins; cmap iteration order is stable per Python 3.7+.
        name_to_cp.setdefault(name, cp)

    glyph_order = font.getGlyphOrder()
    return {
        gn: codepoint_to_id(name_to_cp[gn]) if gn in name_to_cp
        else glyphname_to_id(gn)
        for gn in glyph_order
    }


def _extract_kerning(font: TTFont, id_of: dict[str, str]) -> list[KerningPair]:
    pairs: list[KerningPair] = []
    if "kern" not in font:
        return pairs
    kern = font["kern"]
    for sub in getattr(kern, "kernTables", []):
        if sub.format != 0:
            continue
        for (left_name, right_name), value in sub.kernTable.items():
            if left_name not in id_of or right_name not in id_of:
                continue
            pairs.append(KerningPair(
                left=id_of[left_name],
                right=id_of[right_name],
                value=int(value),
            ))
    return pairs


def _extract_vertical(font: TTFont, id_of: dict[str, str]) -> VerticalMetrics | None:
    if "vhea" not in font or "vmtx" not in font:
        return None
    vhea_dict = _pick(font["vhea"], VHEA_FIELDS)
    vmtx = font["vmtx"]
    vmtx_dict: dict[str, VerticalGlyphMetric] = {}
    for gname, (advance, tsb) in vmtx.metrics.items():
        if gname not in id_of:
            continue
        vmtx_dict[id_of[gname]] = VerticalGlyphMetric(
            advanceHeight=int(advance), tsb=int(tsb))
    return VerticalMetrics(vhea=vhea_dict, vmtx=vmtx_dict)


def extract_metrics(
    font_path: str | Path,
    *,
    include_lsb: bool = False,
    include_kerning: bool = False,
    include_vertical: bool = False,
    deterministic: bool = False,
) -> MetricsSpec:
    """Extract a :class:`MetricsSpec` from a font file.

    The font is loaded lazily; only the whitelisted tables are touched.
    """
    font_path = Path(font_path)
    font = TTFont(str(font_path), lazy=True)

    head = font["head"]
    hhea = font["hhea"]
    os2 = font["OS/2"]
    post = font["post"]
    hmtx = font["hmtx"]

    id_of = _build_glyph_id_map(font)

    glyphs: dict[str, GlyphMetric] = {}
    for gname, (advance, lsb) in hmtx.metrics.items():
        if gname not in id_of:
            continue  # pragma: no cover - shouldn't happen for valid fonts
        gid = id_of[gname]
        glyphs[gid] = GlyphMetric(
            advanceWidth=int(advance),
            lsb=int(lsb) if include_lsb else None,
        )

    global_metrics = GlobalMetrics(
        unitsPerEm=int(head.unitsPerEm),
        head=_pick(head, HEAD_FIELDS),
        hhea=_pick(hhea, HHEA_FIELDS),
        os2=_pick(os2, OS2_FIELDS),
        post=_pick(post, POST_FIELDS),
    )

    kerning = _extract_kerning(font, id_of) if include_kerning else None
    vertical = _extract_vertical(font, id_of) if include_vertical else None

    if deterministic:
        extracted_at = "1970-01-01T00:00:00Z"
    else:
        extracted_at = _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    sha256 = hashlib.sha256(font_path.read_bytes()).hexdigest()

    spec = MetricsSpec(
        source={
            "filename": font_path.name,
            "sha256": sha256,
            "extractedAt": extracted_at,
            "extractorVersion": __version__,
        },
        global_metrics=global_metrics,
        glyphs=glyphs,
        kerning=kerning,
        vertical=vertical,
    )
    font.close()
    return spec


# ---------- CLI ----------

@click.command(help="Extract metrics from a font into a JSON spec.")
@click.argument("font", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Output JSON path (default: stdout).")
@click.option("--include-lsb", is_flag=True, help="Include left side bearings.")
@click.option("--include-kerning", is_flag=True,
              help="Include classic `kern` table pairs.")
@click.option("--include-vertical", is_flag=True,
              help="Include vhea/vmtx vertical metrics.")
@click.option("--deterministic", is_flag=True,
              help="Fix volatile fields (timestamp) for reproducible output.")
@click.option("--indent", type=int, default=2, show_default=True)
def extract_cmd(font: Path, output: Path | None, include_lsb: bool,
                include_kerning: bool, include_vertical: bool,
                deterministic: bool, indent: int) -> None:
    spec = extract_metrics(
        font,
        include_lsb=include_lsb,
        include_kerning=include_kerning,
        include_vertical=include_vertical,
        deterministic=deterministic,
    )
    text = spec.to_json(indent=indent)
    if output is None:
        click.echo(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        click.echo(f"wrote {output} ({len(spec.glyphs)} glyphs)", err=True)
