"""M3 — Generate a new font by stitching source metrics into a design font.

The design font's outlines are preserved; only the metric tables and (when
``--scale-glyph`` is not ``none``) per-glyph horizontal placement are altered.

Supported design font format in v1: TrueType (``glyf``). CFF/OTF designs raise
a clear error and are deferred.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import click
from fontTools.misc.transform import Transform
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable

from .schema import MetricsSpec, parse_id

#: Categories acceptable for ``--apply``.
APPLY_CATEGORIES = ("global", "advance", "lsb", "kerning", "vertical")
SCALE_MODES = ("none", "fit", "center")
MISSING_MODES = ("skip", "notdef")


# ---------- helpers ----------

def _build_id_to_design_name(font: TTFont,
                             metric_ids: Iterable[str]) -> dict[str, str | None]:
    """Map each MetricsSpec glyph identifier to a design-font glyph name."""
    cmap: dict[int, str] = font.getBestCmap() or {}
    glyph_order = set(font.getGlyphOrder())
    out: dict[str, str | None] = {}
    for gid in metric_ids:
        kind, value = parse_id(gid)
        if kind == "cp":
            out[gid] = cmap.get(int(value))
        else:
            out[gid] = value if value in glyph_order else None
    return out


def _scaled(value: int, src_upm: int, dst_upm: int) -> int:
    if src_upm == dst_upm:
        return value
    return round(value * dst_upm / src_upm)


def _transform_glyph(font: TTFont, gname: str,
                     scale_x: float, translate_x: int) -> None:
    """Apply (scale_x, translate_x) to ``gname`` in place, in the ``glyf`` table.

    Composite glyphs are decomposed by ``TTGlyphPen``; this is a known
    side-effect documented in design/05-generator.md.
    """
    if scale_x == 1.0 and translate_x == 0:
        return
    glyph_set = font.getGlyphSet()
    pen = TTGlyphPen(glyph_set)
    transform = Transform(scale_x, 0, 0, 1, translate_x, 0)
    glyph_set[gname].draw(TransformPen(pen, transform))
    new_glyph = pen.glyph()
    new_glyph.recalcBounds(font["glyf"])
    font["glyf"][gname] = new_glyph


def _apply_global(font: TTFont, metrics: MetricsSpec) -> None:
    gm = metrics.global_metrics
    src_upm = gm.unitsPerEm
    dst_upm = font["head"].unitsPerEm
    sc = lambda v: _scaled(v, src_upm, dst_upm) if isinstance(v, int) else v

    for tbl_name, src in (("head", gm.head), ("hhea", gm.hhea),
                           ("OS/2", gm.os2), ("post", gm.post)):
        if tbl_name not in font:
            continue
        tbl = font[tbl_name]
        for k, v in src.items():
            if not hasattr(tbl, k):
                continue
            # Keep design's unitsPerEm (we scale incoming numbers instead).
            if tbl_name == "head" and k == "unitsPerEm":
                continue
            setattr(tbl, k, sc(v) if isinstance(v, int) else v)


def _apply_advance_and_lsb(font: TTFont, metrics: MetricsSpec,
                           id_to_name: dict[str, str | None],
                           scale_mode: str, include_lsb: bool,
                           missing_mode: str) -> dict[str, Any]:
    src_upm = metrics.global_metrics.unitsPerEm
    dst_upm = font["head"].unitsPerEm

    hmtx = font["hmtx"]
    glyf = font.get("glyf")
    stats = {"applied": 0, "missing": 0, "scaled": 0, "centered": 0}

    notdef_advance: int | None = None
    if missing_mode == "notdef" and ".notdef" in hmtx.metrics:
        # Use whatever the design font's .notdef advance is for missing glyphs.
        notdef_advance = hmtx.metrics[".notdef"][0]

    for gid, gm in metrics.glyphs.items():
        gname = id_to_name.get(gid)
        if gname is None or gname not in hmtx.metrics:
            stats["missing"] += 1
            continue

        old_advance, old_lsb = hmtx.metrics[gname]
        new_advance = _scaled(gm.advanceWidth, src_upm, dst_upm)
        explicit_lsb = (_scaled(gm.lsb, src_upm, dst_upm)
                        if include_lsb and gm.lsb is not None else None)

        if scale_mode == "fit" and old_advance > 0 and new_advance != old_advance:
            scale_x = new_advance / old_advance
            _transform_glyph(font, gname, scale_x, 0)
            new_lsb = explicit_lsb if explicit_lsb is not None else round(old_lsb * scale_x)
            stats["scaled"] += 1
        elif scale_mode == "center" and glyf is not None and gname in glyf.glyphs:
            glyph = glyf[gname]
            if getattr(glyph, "numberOfContours", 0) != 0 and hasattr(glyph, "xMin"):
                glyph_width = glyph.xMax - glyph.xMin
                centered_lsb = (new_advance - glyph_width) // 2
                shift_x = centered_lsb - old_lsb
                if shift_x != 0:
                    _transform_glyph(font, gname, 1.0, shift_x)
                    stats["centered"] += 1
                new_lsb = explicit_lsb if explicit_lsb is not None else centered_lsb
            else:
                new_lsb = explicit_lsb if explicit_lsb is not None else old_lsb
        else:
            new_lsb = explicit_lsb if explicit_lsb is not None else old_lsb

        hmtx.metrics[gname] = (new_advance, new_lsb)
        stats["applied"] += 1

    # Apply missing-glyph policy: nothing to do for "skip" (already counted).
    # "notdef" doesn't need us to touch hmtx — the design font's .notdef is
    # already there; consumers shape the missing codepoint to that glyph.
    if missing_mode == "notdef":
        stats["notdefAdvance"] = notdef_advance

    return stats


def _apply_kerning(font: TTFont, metrics: MetricsSpec,
                   id_to_name: dict[str, str | None]) -> dict[str, Any]:
    if not metrics.kerning:
        return {"pairs": 0, "skipped": 0}

    from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0

    pairs: dict[tuple[str, str], int] = {}
    skipped = 0
    for p in metrics.kerning:
        l = id_to_name.get(p.left)
        r = id_to_name.get(p.right)
        if l is None or r is None:
            skipped += 1
            continue
        pairs[(l, r)] = p.value

    kern = newTable("kern")
    kern.version = 0
    sub = KernTable_format_0()
    sub.apple = False
    sub.coverage = 1
    sub.version = 0
    sub.format = 0
    sub.kernTable = pairs
    kern.kernTables = [sub]
    font["kern"] = kern
    return {"pairs": len(pairs), "skipped": skipped}


def _apply_vertical(font: TTFont, metrics: MetricsSpec,
                    id_to_name: dict[str, str | None]) -> dict[str, Any]:
    if metrics.vertical is None:
        return {"applied": 0}
    src_upm = metrics.global_metrics.unitsPerEm
    dst_upm = font["head"].unitsPerEm

    if "vhea" not in font:
        # Most design fonts have no vertical tables. Synthesize a complete
        # vhea (sstruct.pack requires every field, even unused ones) and an
        # empty vmtx to be filled below.
        from fontTools.ttLib.tables._v_h_e_a import table__v_h_e_a
        from fontTools.ttLib.tables._v_m_t_x import table__v_m_t_x
        vhea_tbl = table__v_h_e_a()
        vhea_tbl.tableVersion = 0x00011000
        vhea_tbl.ascent = 0
        vhea_tbl.descent = 0
        vhea_tbl.lineGap = 0
        vhea_tbl.advanceHeightMax = 0
        vhea_tbl.minTopSideBearing = 0
        vhea_tbl.minBottomSideBearing = 0
        vhea_tbl.yMaxExtent = 0
        vhea_tbl.caretSlopeRise = 1
        vhea_tbl.caretSlopeRun = 0
        vhea_tbl.caretOffset = 0
        vhea_tbl.reserved0 = vhea_tbl.reserved1 = 0
        vhea_tbl.reserved2 = vhea_tbl.reserved3 = vhea_tbl.reserved4 = 0
        vhea_tbl.metricDataFormat = 0
        vhea_tbl.numberOfVMetrics = 0
        font["vhea"] = vhea_tbl
        font["vmtx"] = table__v_m_t_x()
        font["vmtx"].metrics = {}
    vhea = font["vhea"]
    for k, v in metrics.vertical.vhea.items():
        if hasattr(vhea, k):
            setattr(vhea, k, _scaled(v, src_upm, dst_upm) if isinstance(v, int) else v)

    vmtx = font["vmtx"]
    applied = 0
    for gid, vgm in metrics.vertical.vmtx.items():
        gname = id_to_name.get(gid)
        if gname is None:
            continue
        adv = _scaled(vgm.advanceHeight, src_upm, dst_upm)
        tsb = (_scaled(vgm.tsb, src_upm, dst_upm) if vgm.tsb is not None else 0)
        vmtx.metrics[gname] = (adv, tsb)
        applied += 1
    return {"applied": applied}


_NAME_IDS = {
    "family": 1,
    "style": 2,
    "fullname": 4,
    "psname": 6,
    "license": 13,
    "license_url": 14,
    "preferred_family": 16,
    "preferred_style": 17,
}


def _update_name_table(font: TTFont, *, family_name: str | None,
                       style_name: str | None, license_text: str | None,
                       license_url: str | None) -> None:
    name = font["name"]
    if family_name:
        name.setName(family_name, _NAME_IDS["family"], 3, 1, 0x409)
        name.setName(family_name, _NAME_IDS["preferred_family"], 3, 1, 0x409)
    if style_name:
        name.setName(style_name, _NAME_IDS["style"], 3, 1, 0x409)
        name.setName(style_name, _NAME_IDS["preferred_style"], 3, 1, 0x409)
    if family_name and style_name:
        full = f"{family_name} {style_name}"
        name.setName(full, _NAME_IDS["fullname"], 3, 1, 0x409)
        psname = f"{family_name}-{style_name}".replace(" ", "")
        name.setName(psname, _NAME_IDS["psname"], 3, 1, 0x409)
    if license_text:
        name.setName(license_text, _NAME_IDS["license"], 3, 1, 0x409)
    if license_url:
        name.setName(license_url, _NAME_IDS["license_url"], 3, 1, 0x409)


# ---------- public API ----------

def generate_font(metrics: MetricsSpec, design_font_path: str | Path,
                  output_path: str | Path,
                  *,
                  apply: Iterable[str] = ("global", "advance"),
                  scale_glyph: str = "none",
                  missing_glyph: str = "skip",
                  family_name: str | None = None,
                  style_name: str | None = None,
                  license_text: str | None = None,
                  license_url: str | None = None) -> dict[str, Any]:
    apply_set = set(apply)
    invalid = apply_set - set(APPLY_CATEGORIES)
    if invalid:
        raise click.UsageError(f"unknown apply categories: {sorted(invalid)}")
    if scale_glyph not in SCALE_MODES:
        raise click.UsageError(f"--scale-glyph must be one of {SCALE_MODES}")
    if missing_glyph not in MISSING_MODES:
        raise click.UsageError(f"--missing-glyph must be one of {MISSING_MODES}")

    font = TTFont(str(design_font_path))
    if "glyf" not in font:
        raise click.UsageError(
            "design font must be TrueType (`glyf` table required); "
            "CFF/OTF designs are not supported in v1.")

    id_to_name = _build_id_to_design_name(font, metrics.glyphs.keys())
    stats: dict[str, Any] = {
        "designFont": str(design_font_path),
        "metricGlyphCount": len(metrics.glyphs),
        "applyCategories": sorted(apply_set),
        "scaleGlyph": scale_glyph,
        "missingGlyph": missing_glyph,
    }

    if "global" in apply_set:
        _apply_global(font, metrics)

    if "advance" in apply_set:
        stats["advance"] = _apply_advance_and_lsb(
            font, metrics, id_to_name,
            scale_mode=scale_glyph,
            include_lsb=("lsb" in apply_set),
            missing_mode=missing_glyph,
        )

    if "kerning" in apply_set:
        stats["kerning"] = _apply_kerning(font, metrics, id_to_name)

    if "vertical" in apply_set:
        stats["vertical"] = _apply_vertical(font, metrics, id_to_name)

    if family_name or style_name or license_text or license_url:
        _update_name_table(font, family_name=family_name, style_name=style_name,
                           license_text=license_text, license_url=license_url)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(out))
    font.close()
    stats["output"] = str(out)
    return stats


# ---------- CLI ----------

@click.command(help="Generate a new font: source metrics + design outlines.")
@click.option("--metrics", "metrics_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Source MetricsSpec JSON.")
@click.option("--design", "design_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Design font (.ttf) to take outlines from.")
@click.option("-o", "--output", "output_path", required=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Output font path.")
@click.option("--apply", default="global,advance", show_default=True,
              help=f"Comma-separated subset of {APPLY_CATEGORIES}.")
@click.option("--scale-glyph", type=click.Choice(SCALE_MODES), default="none",
              show_default=True,
              help="How to align glyph outline to new advance width.")
@click.option("--missing-glyph", type=click.Choice(MISSING_MODES),
              default="skip", show_default=True)
@click.option("--family-name", default=None)
@click.option("--style-name", default=None)
@click.option("--license-text", default=None,
              help="License Description for the name table (ID 13).")
@click.option("--license-url", default=None,
              help="License URL for the name table (ID 14).")
def generate_cmd(metrics_path: Path, design_path: Path, output_path: Path,
                 apply: str, scale_glyph: str, missing_glyph: str,
                 family_name: str | None, style_name: str | None,
                 license_text: str | None, license_url: str | None) -> None:
    spec = MetricsSpec.from_json(metrics_path.read_text(encoding="utf-8"))
    apply_set = [s.strip() for s in apply.split(",") if s.strip()]
    stats = generate_font(
        spec, design_path, output_path,
        apply=apply_set,
        scale_glyph=scale_glyph,
        missing_glyph=missing_glyph,
        family_name=family_name,
        style_name=style_name,
        license_text=license_text,
        license_url=license_url,
    )
    adv = stats.get("advance", {})
    click.echo(f"wrote {output_path}: applied={adv.get('applied', 0)}, "
               f"missing={adv.get('missing', 0)}, "
               f"scaled={adv.get('scaled', 0)}", err=True)
