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
APPLY_CATEGORIES = ("global", "advance", "lsb", "kerning", "vertical", "gsub")
SCALE_MODES = ("none", "fit", "center")
MISSING_MODES = ("skip", "notdef")
OUTPUT_FORMATS = ("auto", "ttf", "woff2")


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
        # Align design font's .notdef advance with the source's, so glyphs
        # that fall back to .notdef occupy the same horizontal slot the
        # source font would have used. The source spec exposes .notdef
        # under the ``glyph#.notdef`` identifier (it has no codepoint).
        src_notdef = metrics.glyphs.get("glyph#.notdef")
        if src_notdef is not None:
            notdef_advance = _scaled(src_notdef.advanceWidth, src_upm, dst_upm)
            old_lsb = hmtx.metrics[".notdef"][1]
            hmtx.metrics[".notdef"] = (notdef_advance, old_lsb)
        else:
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
    """Apply kerning to both classic ``kern`` and the GPOS ``kern`` feature.

    Browsers and modern shapers prefer GPOS over the classic ``kern`` table
    for OpenType fonts, so writing only ``kern`` (as v1 did) was effectively
    invisible to most renderers when the design font already had a GPOS
    ``kern`` feature. We now:

    1. Write a classic ``kern`` table for legacy shapers.
    2. Replace the design font's GPOS pair-positioning lookups with a new
       lookup containing the source pairs, and rewire the ``kern`` feature
       to point at it. Other GPOS lookups (mark, cursive, etc.) are kept.
    """
    if not metrics.kerning:
        return {"pairs": 0, "skipped": 0}

    pairs: dict[tuple[str, str], int] = {}
    skipped = 0
    for p in metrics.kerning:
        l = id_to_name.get(p.left)
        r = id_to_name.get(p.right)
        if l is None or r is None:
            skipped += 1
            continue
        pairs[(l, r)] = p.value

    if not pairs:
        return {"pairs": 0, "skipped": skipped}

    _write_classic_kern(font, pairs)
    _write_gpos_kern(font, pairs)
    return {"pairs": len(pairs), "skipped": skipped}


def _write_classic_kern(font: TTFont, pairs: dict[tuple[str, str], int]) -> None:
    from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0
    kern = newTable("kern")
    kern.version = 0
    sub = KernTable_format_0()
    sub.apple = False
    sub.coverage = 1
    sub.version = 0
    sub.format = 0
    sub.kernTable = dict(pairs)
    kern.kernTables = [sub]
    font["kern"] = kern


def _write_gpos_kern(font: TTFont, pairs: dict[tuple[str, str], int]) -> None:
    """Inject a GPOS PairPos lookup, replacing existing pair-pos lookups.

    Existing non-pair lookups (mark, cursive, contextual, ...) are preserved.
    The ``kern`` feature record is rewired to reference our new lookup; if
    the design font has no ``kern`` feature, one is added across all scripts
    that already exist in GPOS.
    """
    from fontTools.otlLib import builder as otl
    from fontTools.ttLib.tables import otTables as ot
    from fontTools.ttLib.tables.otBase import ValueRecord

    glyph_order = font.getGlyphOrder()
    glyph_map = {g: i for i, g in enumerate(glyph_order)}
    valid = {(l, r): adj for (l, r), adj in pairs.items()
             if l in glyph_map and r in glyph_map and adj != 0}
    if not valid:
        return

    pair_records: dict[tuple[str, str], tuple[ValueRecord, ValueRecord]] = {}
    for (l, r), adj in valid.items():
        v1 = ValueRecord()
        v1.XAdvance = int(adj)
        v2 = ValueRecord()
        pair_records[(l, r)] = (v1, v2)

    subtables = otl.buildPairPosGlyphs(pair_records, glyph_map)

    kern_lookup = ot.Lookup()
    kern_lookup.LookupType = 2
    kern_lookup.LookupFlag = 0
    kern_lookup.SubTable = subtables
    kern_lookup.SubTableCount = len(subtables)

    if "GPOS" not in font:
        font["GPOS"] = _build_minimal_gpos(kern_lookup)
        return

    gpos = font["GPOS"].table

    # Filter out existing pair-positioning lookups (and Extension wrappers
    # around them); remap surviving lookup indices.
    new_lookups: list = []
    old_to_new: dict[int, int] = {}
    for old_idx, lk in enumerate(gpos.LookupList.Lookup):
        if _lookup_is_pair_pos(lk):
            continue
        old_to_new[old_idx] = len(new_lookups)
        new_lookups.append(lk)
    new_kern_idx = len(new_lookups)
    new_lookups.append(kern_lookup)

    gpos.LookupList.Lookup = new_lookups
    gpos.LookupList.LookupCount = len(new_lookups)

    # Update FeatureList lookup indices and rewire the ``kern`` feature.
    has_kern = False
    for fr in gpos.FeatureList.FeatureRecord:
        old_idxs = list(fr.Feature.LookupListIndex)
        kept = [old_to_new[i] for i in old_idxs if i in old_to_new]
        if fr.FeatureTag == "kern":
            kept = [i for i in kept if i != new_kern_idx]
            kept.append(new_kern_idx)
            has_kern = True
        fr.Feature.LookupListIndex = kept
        fr.Feature.LookupCount = len(kept)

    if not has_kern:
        feat = ot.Feature()
        feat.LookupListIndex = [new_kern_idx]
        feat.LookupCount = 1
        feat.FeatureParams = None
        fr = ot.FeatureRecord()
        fr.FeatureTag = "kern"
        fr.Feature = feat
        new_feat_idx = len(gpos.FeatureList.FeatureRecord)
        gpos.FeatureList.FeatureRecord.append(fr)
        gpos.FeatureList.FeatureCount = len(gpos.FeatureList.FeatureRecord)
        for sr in gpos.ScriptList.ScriptRecord:
            for ls in [sr.Script.DefaultLangSys] + [
                lsr.LangSys for lsr in sr.Script.LangSysRecord
            ]:
                if ls is None:
                    continue
                ls.FeatureIndex.append(new_feat_idx)
                ls.FeatureCount = len(ls.FeatureIndex)


def _lookup_is_pair_pos(lookup) -> bool:
    """True for type-2 (PairPos) lookups, including Extension wrappers."""
    if lookup.LookupType == 2:
        return True
    if lookup.LookupType == 9:
        for sub in lookup.SubTable:
            if getattr(sub, "ExtensionLookupType", None) == 2:
                return True
    return False


def _build_minimal_gpos(kern_lookup):
    """Construct a fresh GPOS table containing only one ``kern`` lookup."""
    from fontTools.ttLib.tables import otTables as ot

    lookup_list = ot.LookupList()
    lookup_list.Lookup = [kern_lookup]
    lookup_list.LookupCount = 1

    feat = ot.Feature()
    feat.FeatureParams = None
    feat.LookupListIndex = [0]
    feat.LookupCount = 1
    fr = ot.FeatureRecord()
    fr.FeatureTag = "kern"
    fr.Feature = feat
    feat_list = ot.FeatureList()
    feat_list.FeatureRecord = [fr]
    feat_list.FeatureCount = 1

    default_ls = ot.DefaultLangSys()
    default_ls.LookupOrder = None
    default_ls.ReqFeatureIndex = 0xFFFF
    default_ls.FeatureIndex = [0]
    default_ls.FeatureCount = 1
    script = ot.Script()
    script.DefaultLangSys = default_ls
    script.LangSysRecord = []
    script.LangSysCount = 0
    script_record = ot.ScriptRecord()
    script_record.ScriptTag = "DFLT"
    script_record.Script = script
    script_list = ot.ScriptList()
    script_list.ScriptRecord = [script_record]
    script_list.ScriptCount = 1

    gpos = ot.GPOS()
    gpos.Version = 0x00010000
    gpos.ScriptList = script_list
    gpos.FeatureList = feat_list
    gpos.LookupList = lookup_list

    tbl = newTable("GPOS")
    tbl.table = gpos
    return tbl


def _apply_shaped_advances(
    font: TTFont, metrics: MetricsSpec,
    id_to_name: dict[str, str | None],
    *, src_upm: int, dst_upm: int,
) -> dict[str, Any]:
    """Inject `--apply gsub` overrides as ``locl``-feature substitutions.

    For each ``ShapedAdvanceOverride``:
    1. Add a stub glyph (empty outline, override advance) to the design font.
    2. Add a single GSUB substitution under the override's (script, language)
       context, registered in the ``locl`` (Localized Forms) feature so
       browsers auto-apply it when the matching ``lang`` attribute is set.

    The stub glyph carries no outline, so the result reflects the design
    font's other glyphs visually but the line layout under that script/lang
    matches the source font's shaping.
    """
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
    from fontTools.ttLib.tables._g_l_y_f import Glyph

    cmap = font.getBestCmap() or {}
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    glyph_order = list(font.getGlyphOrder())

    # Strip the design font's existing `locl` feature first. `locl` is the
    # OpenType feature browsers auto-activate based on the page ``lang``
    # attribute, and it carries the design font's *own* per-script
    # advance-affecting substitutions (e.g., NotoSansKR's wider Korean
    # space). Leaving them in place would mean the result font behaves like
    # the design under lang="ko" rather than like the source. After
    # stripping we re-inject the source's overrides via FEA below.
    stripped_locl = _strip_locl_feature(font)

    if not metrics.shaped_advances:
        return {"applied": 0, "skipped": 0,
                "strippedDesignLoclLookups": stripped_locl}

    stubs_added: list[str] = []
    # Dedupe: at most one substitution per (script, lang, source_glyph).
    # Same context can yield multiple ShapedAdvanceOverride entries when
    # the source font has overlapping GSUB lookups; FEA forbids redefining
    # a substitution for the same input glyph in the same lang/script.
    contexts: dict[tuple[str, str], dict[str, str]] = {}
    skipped = 0

    for ov in metrics.shaped_advances:
        try:
            cp = int(ov.codepoint[2:], 16)
        except ValueError:
            skipped += 1
            continue
        gn = cmap.get(cp)
        if gn is None or gn not in glyf.glyphs:
            skipped += 1
            continue
        ctx = (ov.script, ov.language)
        if ctx in contexts and gn in contexts[ctx]:
            # Already have a substitution for this glyph in this context;
            # keep the first one (deterministic given sorted spec order).
            continue
        stub_name = f"polaris.{ov.codepoint[2:]}.{ov.script}_{ov.language}"
        if stub_name not in glyf.glyphs:
            stub = Glyph()
            stub.numberOfContours = 0
            glyf[stub_name] = stub
            glyph_order.append(stub_name)
            stubs_added.append(stub_name)
            advance = _scaled(ov.advance, src_upm, dst_upm)
            hmtx.metrics[stub_name] = (advance, 0)
        contexts.setdefault(ctx, {})[gn] = stub_name

    if not contexts:
        return {"applied": 0, "skipped": skipped}

    if stubs_added:
        font.setGlyphOrder(glyph_order)
        font["maxp"].numGlyphs = len(glyph_order)

    # Build a FEA snippet defining a `locl` feature for each (script, lang).
    fea_lines = ["languagesystem DFLT dflt;"]
    for script, lang in contexts:
        fea_lines.append(f"languagesystem {script} {lang};")
    fea_lines.append("feature locl {")
    for (script, lang), gn_to_stub in contexts.items():
        fea_lines.append(f"  script {script};")
        fea_lines.append(f"  language {lang} exclude_dflt;")
        for original, stub in gn_to_stub.items():
            fea_lines.append(f"  sub {original} by {stub};")
    fea_lines.append("} locl;")
    fea = "\n".join(fea_lines)

    addOpenTypeFeaturesFromString(font, fea)

    return {
        "applied": sum(len(v) for v in contexts.values()),
        "skipped": skipped,
        "stubGlyphs": len(stubs_added),
        "contexts": [f"{s}/{l}" for s, l in sorted(contexts.keys())],
        "strippedDesignLoclLookups": stripped_locl,
    }


def _strip_locl_feature(font: TTFont) -> int:
    """Remove the design font's ``locl`` feature and any lookups exclusively
    referenced by it. Returns the number of lookups removed.

    Other features (mark, liga, calt, ...) are preserved. We don't touch
    GSUB if the font has no GSUB table at all.
    """
    if "GSUB" not in font:
        return 0
    gsub = font["GSUB"].table
    if not gsub or not gsub.FeatureList:
        return 0

    # Identify all lookup indices used by `locl` and by every other feature
    # so we can drop lookups that are *only* used by locl.
    locl_indices: set[int] = set()
    other_indices: set[int] = set()
    for fr in gsub.FeatureList.FeatureRecord:
        idxs = set(fr.Feature.LookupListIndex)
        if fr.FeatureTag == "locl":
            locl_indices |= idxs
        else:
            other_indices |= idxs
    droppable = locl_indices - other_indices
    if not droppable:
        return 0

    # Renumber surviving lookups; drop the locl-only ones.
    new_lookups: list = []
    old_to_new: dict[int, int] = {}
    for old_idx, lk in enumerate(gsub.LookupList.Lookup):
        if old_idx in droppable:
            continue
        old_to_new[old_idx] = len(new_lookups)
        new_lookups.append(lk)
    gsub.LookupList.Lookup = new_lookups
    gsub.LookupList.LookupCount = len(new_lookups)

    # Remap remaining feature lookup indices and drop the `locl` feature
    # records entirely; ScriptList's FeatureIndex lists need parallel updating.
    surviving_features: list = []
    feat_idx_remap: dict[int, int] = {}
    for old_fi, fr in enumerate(gsub.FeatureList.FeatureRecord):
        if fr.FeatureTag == "locl":
            continue
        fr.Feature.LookupListIndex = [old_to_new[i] for i in fr.Feature.LookupListIndex
                                       if i in old_to_new]
        fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
        feat_idx_remap[old_fi] = len(surviving_features)
        surviving_features.append(fr)
    gsub.FeatureList.FeatureRecord = surviving_features
    gsub.FeatureList.FeatureCount = len(surviving_features)

    for sr in gsub.ScriptList.ScriptRecord:
        for ls in [sr.Script.DefaultLangSys] + [
            lsr.LangSys for lsr in sr.Script.LangSysRecord
        ]:
            if ls is None:
                continue
            ls.FeatureIndex = [feat_idx_remap[i] for i in ls.FeatureIndex
                                if i in feat_idx_remap]
            ls.FeatureCount = len(ls.FeatureIndex)

    return len(droppable)


# Backward compat for the type signature change in the inline dict above.


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
                  match_upm: bool = False,
                  output_format: str = "auto",
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
    if output_format not in OUTPUT_FORMATS:
        raise click.UsageError(f"--output-format must be one of {OUTPUT_FORMATS}")

    font = TTFont(str(design_font_path))
    if "glyf" not in font:
        raise click.UsageError(
            "design font must be TrueType (`glyf` table required); "
            "CFF/OTF designs are not supported in v1.")

    # When source and design UPMs differ, applying source metrics to the
    # design at design's UPM introduces ±0.5-unit per-glyph rounding. That
    # accumulates and shifts line-break positions in browser rendering even
    # though absolute widths look identical. --match-upm rescales the entire
    # design font (outlines, kerning, etc.) to the source's UPM first, so
    # incoming metric values land on integer units exactly.
    #
    # KNOWN ISSUE: scale_upem applied to NotoSansKR (and likely other large
    # CJK fonts) produces TTFs that Chromium's TTF sanitizer rejects, even
    # though fontTools/HarfBuzz consider them valid and the same data
    # serialized as WOFF2 loads fine. We therefore allow upscale here and
    # surface the workaround at the output-format layer below
    # (output_format='auto' switches to WOFF2 when rescale was performed).
    upm_rescaled_from = None
    if match_upm:
        src_upm = metrics.global_metrics.unitsPerEm
        dst_upm = font["head"].unitsPerEm
        if dst_upm != src_upm:
            from fontTools.ttLib.scaleUpem import scale_upem
            upm_rescaled_from = dst_upm
            scale_upem(font, src_upm)

    id_to_name = _build_id_to_design_name(font, metrics.glyphs.keys())
    stats: dict[str, Any] = {
        "designFont": str(design_font_path),
        "metricGlyphCount": len(metrics.glyphs),
        "applyCategories": sorted(apply_set),
        "scaleGlyph": scale_glyph,
        "missingGlyph": missing_glyph,
        "upmRescaledFrom": upm_rescaled_from,
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

    if "gsub" in apply_set:
        src_upm_for_gsub = metrics.global_metrics.unitsPerEm
        dst_upm_for_gsub = font["head"].unitsPerEm
        stats["gsub"] = _apply_shaped_advances(
            font, metrics, id_to_name,
            src_upm=src_upm_for_gsub, dst_upm=dst_upm_for_gsub,
        )

    if family_name or style_name or license_text or license_url:
        _update_name_table(font, family_name=family_name, style_name=style_name,
                           license_text=license_text, license_url=license_url)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Resolve output format. When fontTools' scale_upem has rescaled the
    # design (typically the upscale path), the resulting TTF can be rejected
    # by Chromium's TTF sanitizer even though the same bytes round-trip
    # cleanly as WOFF2. ``output_format='auto'`` switches to WOFF2 in that
    # case; users can force ``ttf`` or ``woff2`` explicitly.
    chosen_format = output_format
    if chosen_format == "auto":
        if upm_rescaled_from is not None:
            chosen_format = "woff2"
        else:
            chosen_format = "ttf"

    if chosen_format == "woff2":
        font.flavor = "woff2"
        if out.suffix.lower() != ".woff2":
            out = out.with_suffix(".woff2")
    else:
        font.flavor = None
        if out.suffix.lower() not in (".ttf", ".otf"):
            out = out.with_suffix(".ttf")

    font.save(str(out))
    font.close()
    stats["output"] = str(out)
    stats["outputFormat"] = chosen_format
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
@click.option("--match-upm/--no-match-upm", default=False, show_default=True,
              help="Rescale the design font's UPM to match the source's "
                   "before applying metrics. Eliminates per-glyph rounding "
                   "that otherwise shifts line breaks when UPMs differ.")
@click.option("--output-format", type=click.Choice(OUTPUT_FORMATS),
              default="auto", show_default=True,
              help="Output container. ``auto`` picks WOFF2 when --match-upm "
                   "rescaled the design font (Chromium TTF sanitizer "
                   "incompatibility workaround) and TTF otherwise.")
@click.option("--family-name", default=None)
@click.option("--style-name", default=None)
@click.option("--license-text", default=None,
              help="License Description for the name table (ID 13).")
@click.option("--license-url", default=None,
              help="License URL for the name table (ID 14).")
def generate_cmd(metrics_path: Path, design_path: Path, output_path: Path,
                 apply: str, scale_glyph: str, missing_glyph: str,
                 match_upm: bool, output_format: str,
                 family_name: str | None, style_name: str | None,
                 license_text: str | None, license_url: str | None) -> None:
    spec = MetricsSpec.from_json(metrics_path.read_text(encoding="utf-8"))
    apply_set = [s.strip() for s in apply.split(",") if s.strip()]
    stats = generate_font(
        spec, design_path, output_path,
        apply=apply_set,
        scale_glyph=scale_glyph,
        missing_glyph=missing_glyph,
        match_upm=match_upm,
        output_format=output_format,
        family_name=family_name,
        style_name=style_name,
        license_text=license_text,
        license_url=license_url,
    )
    adv = stats.get("advance", {})
    extra = f" [{stats.get('outputFormat', 'ttf')}]"
    if stats.get("upmRescaledFrom"):
        extra += f", upm rescaled {stats['upmRescaledFrom']}->{spec.global_metrics.unitsPerEm}"
    click.echo(f"wrote {stats['output']}: applied={adv.get('applied', 0)}, "
               f"missing={adv.get('missing', 0)}, "
               f"scaled={adv.get('scaled', 0)}{extra}", err=True)
