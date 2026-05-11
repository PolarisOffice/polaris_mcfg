"""M3 — Generate a new font by stitching source metrics into a design font.

The design font's outlines are preserved; only the metric tables and (when
``--scale-glyph`` is not ``none``) per-glyph horizontal placement are altered.

Currently supported design font format: TrueType (``glyf``). CFF/OTF designs
raise a clear error; CFF rescaling support is deferred to a later release.
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

    Caller must ensure that any composite glyphs sharing ``gname`` as a
    component have already been decomposed (see ``_decompose_all_composites``).
    Otherwise the transform leaks into every parent composite — e.g.,
    Pretendard's ``dotaccent`` (the dot used by i/j/ä/ö/...) is also
    cmap-mapped to U+02D9; transforming it at the top-level loop without
    pre-decomposing breaks every glyph that uses it as the dot.
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


def _decompose_all_composites(font: TTFont) -> int:
    """Convert every composite glyph in ``glyf`` into a simple glyph that
    bakes in component transformations and contours.

    Required before any per-glyph horizontal shift (``--scale-glyph
    fit``/``center``). Without it, a simple glyph that's also referenced
    as a component (e.g., ``dotaccent`` shared by ``i``/``j``/``ä``/``ö``
    and cmap-mapped at U+02D9) would, when transformed in the main loop,
    propagate its translation to every parent composite — visibly
    detaching the dot from the stem.

    Returns the number of composites decomposed.
    """
    from fontTools.pens.recordingPen import DecomposingRecordingPen

    glyf = font["glyf"]
    glyph_set = font.getGlyphSet()
    n = 0
    for name in list(glyf.glyphs):
        if not glyf[name].isComposite():
            continue
        rec = DecomposingRecordingPen(glyph_set)
        glyph_set[name].draw(rec)
        out = TTGlyphPen(glyph_set)
        rec.replay(out)
        new_glyph = out.glyph()
        new_glyph.recalcBounds(glyf)
        glyf[name] = new_glyph
        n += 1
    return n


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
    # When scale_mode is fit/center, any glyph we shift could be shared
    # as a component by other composites. Pre-decompose all composites
    # so each parent owns its outline contours independently.
    if scale_mode != "none":
        _decompose_all_composites(font)

    """Apply advance widths (and optionally LSBs) from ``metrics`` to ``font``.

    ``missing_mode`` controls what happens to source codepoints that the
    design font doesn't carry:

    * ``skip``: count and ignore. Browsers fall back to a system font for
      that codepoint, with whatever advance the system font defines.
    * ``notdef``: route the missing codepoint to the design font's
      ``.notdef`` glyph by inserting it into the cmap, *and* set
      ``.notdef``'s advance to match the source font's ``.notdef`` so
      the layout slot matches the source font's intent.

    The ``.notdef`` advance update is done at the end of the per-glyph loop
    rather than the start, so a source spec that explicitly carries
    ``glyph#.notdef`` still wins (it goes through the normal loop path).
    """
    src_upm = metrics.global_metrics.unitsPerEm
    dst_upm = font["head"].unitsPerEm

    hmtx = font["hmtx"]
    glyf = font.get("glyf")
    stats: dict[str, Any] = {
        "applied": 0, "missing": 0, "scaled": 0, "centered": 0,
        "notdefRemapped": 0,
    }

    missing_codepoints: list[int] = []

    for gid, gm in metrics.glyphs.items():
        gname = id_to_name.get(gid)
        if gname is None or gname not in hmtx.metrics:
            stats["missing"] += 1
            # Track codepoints we could re-route to .notdef later.
            if gid.startswith("U+"):
                try:
                    missing_codepoints.append(int(gid[2:], 16))
                except ValueError:
                    pass
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

    if missing_mode == "notdef" and ".notdef" in hmtx.metrics:
        stats["notdefAdvance"] = _route_missing_to_notdef(
            font, metrics, missing_codepoints, src_upm, dst_upm,
        )
        stats["notdefRemapped"] = len(missing_codepoints)

    return stats


#: Name of the synthetic stub glyph the generator inserts so missing-glyph
#: codepoints can survive cmap compile (fontTools drops .notdef-targeted
#: cmap entries because OpenType treats them as implicit). Internally the
#: glyph is a copy of ``.notdef``'s advance with no outline, so behaviour
#: is identical to falling back to ``.notdef`` while remaining explicit
#: in the cmap.
_NOTDEF_STUB_NAME = "polaris.notdef_fallback"


def _sync_vmtx_for_stub(font: TTFont, stub_name: str,
                        source_glyph: str | None = None) -> None:
    """If the font has ``vhea``/``vmtx``, register a vertical metric for
    a newly-added stub glyph.

    Without this, the design font's ``vmtx`` ends up shorter than
    ``numGlyphs`` after any stub insertion (``_apply_gsub_overrides``,
    ``_route_missing_to_notdef``), and fontTools' next load of the result
    fails with ``not enough 'vmtx' table data: expected N bytes, got M``.

    The synthetic glyph has no real vertical extents, so we copy the
    metric of ``source_glyph`` when given (semantically closest), and
    otherwise fall back to the table's first entry (any valid value
    keeps the table the right length).
    """
    if "vmtx" not in font or "vhea" not in font:
        return
    vmtx = font["vmtx"]
    if stub_name in vmtx.metrics:
        return
    if source_glyph and source_glyph in vmtx.metrics:
        vmtx.metrics[stub_name] = vmtx.metrics[source_glyph]
        return
    if vmtx.metrics:
        # Use the first existing entry as a default; arbitrary choice
        # but keeps the table valid. Stub is logically empty so its
        # vertical advance / TSB don't carry semantic meaning.
        sample = next(iter(vmtx.metrics.values()))
        vmtx.metrics[stub_name] = sample
    else:
        # No existing metrics; fall back to font's vhea advance.
        vhea = font["vhea"]
        adv = int(getattr(vhea, "advanceHeightMax", 1000) or 1000)
        vmtx.metrics[stub_name] = (adv, 0)


def _route_missing_to_notdef(
    font: TTFont, metrics: MetricsSpec,
    missing_codepoints: list[int],
    src_upm: int, dst_upm: int,
) -> int:
    """Route ``missing_codepoints`` to a notdef-equivalent stub glyph.

    1. Update ``.notdef``'s advance to match the source's (visual slot).
    2. Insert a stub glyph with the same advance (empty outline, OpenType
       considers .notdef-as-cmap-target implicit and drops it on compile,
       so we use a distinct stub to keep the routing explicit).
    3. Add the stub to every Unicode cmap subtable for each missing
       codepoint that wasn't already present.

    Returns the resulting ``.notdef`` advance in design units.
    """
    from fontTools.ttLib.tables._g_l_y_f import Glyph

    hmtx = font["hmtx"]

    src_notdef = metrics.glyphs.get("glyph#.notdef")
    if src_notdef is not None:
        notdef_advance = _scaled(src_notdef.advanceWidth, src_upm, dst_upm)
        old_lsb = hmtx.metrics[".notdef"][1]
        hmtx.metrics[".notdef"] = (notdef_advance, old_lsb)
    else:
        notdef_advance = hmtx.metrics[".notdef"][0]

    if not missing_codepoints or "cmap" not in font:
        return notdef_advance

    # Add the stub glyph if not already present.
    glyph_order = list(font.getGlyphOrder())
    if _NOTDEF_STUB_NAME not in glyph_order:
        # Force-load vmtx (if present) BEFORE bumping numGlyphs.
        # fontTools' lazy vmtx decompile checks the raw byte size
        # against maxp.numGlyphs, so once numGlyphs is increased the
        # original vmtx bytes look "short" and decompile fails.
        if "vmtx" in font:
            font["vmtx"]  # noqa: B018 - triggers decompile

        stub = Glyph()
        stub.numberOfContours = 0
        font["glyf"][_NOTDEF_STUB_NAME] = stub
        glyph_order.append(_NOTDEF_STUB_NAME)
        font.setGlyphOrder(glyph_order)
        font["maxp"].numGlyphs = len(glyph_order)
        hmtx.metrics[_NOTDEF_STUB_NAME] = (notdef_advance, 0)
        _sync_vmtx_for_stub(font, _NOTDEF_STUB_NAME, source_glyph=".notdef")

    cmap_table = font["cmap"]
    for sub in cmap_table.tables:
        if not sub.isUnicode():
            continue
        for cp in missing_codepoints:
            if cp not in sub.cmap:
                sub.cmap[cp] = _NOTDEF_STUB_NAME
    return notdef_advance


def _apply_kerning(font: TTFont, metrics: MetricsSpec,
                   id_to_name: dict[str, str | None]) -> dict[str, Any]:
    """Apply kerning to both classic ``kern`` and the GPOS ``kern`` feature.

    Browsers and modern shapers prefer GPOS over the classic ``kern`` table
    for OpenType fonts, so writing only ``kern`` (as the v0.1 generator did)
    was effectively invisible to most renderers when the design font
    already had a GPOS ``kern`` feature. We now:

    1. Write a classic ``kern`` table for legacy shapers.
    2. Replace the design font's GPOS pair-positioning lookups with a new
       lookup containing the source pairs, and rewire the ``kern`` feature
       to point at it. Other GPOS lookups (mark, cursive, etc.) are kept.
    """
    if not metrics.kerning:
        return {"pairs": 0, "skipped": 0}

    # Kerning values are in source-font units, so they need the same UPM
    # scaling that advance widths get. Without this, generating into a
    # design font with a different UPM produces visibly over- or
    # under-kerned text (e.g., source UPM 2000 -> design UPM 1000 doubles
    # the apparent kern). When --match-upm is in effect the design has
    # been rescaled to source UPM and this becomes a no-op.
    src_upm = metrics.global_metrics.unitsPerEm
    dst_upm = font["head"].unitsPerEm

    pairs: dict[tuple[str, str], int] = {}
    skipped = 0
    for p in metrics.kerning:
        l = id_to_name.get(p.left)
        r = id_to_name.get(p.right)
        if l is None or r is None:
            skipped += 1
            continue
        pairs[(l, r)] = _scaled(p.value, src_upm, dst_upm)

    if not pairs:
        return {"pairs": 0, "skipped": skipped}

    classic_written = _write_classic_kern(font, pairs)
    _write_gpos_kern(font, pairs)
    return {
        "pairs": len(pairs),
        "skipped": skipped,
        "classicKernWritten": classic_written,
        # If the classic kern table was skipped due to the 16-bit
        # subtable-length limit, modern shapers still get the full pair
        # set via GPOS — only ancient shapers that ignore GPOS would
        # notice.
        "classicKernSkippedReason": ("size>16bit-limit"
                                     if classic_written == 0
                                     and len(pairs) > MAX_CLASSIC_KERN_PAIRS
                                     else None),
    }


#: Maximum pairs a single classic ``kern`` format-0 subtable can encode.
#:
#: The subtable header has a 16-bit ``length`` field (max 65535 bytes).
#: Layout: 14-byte header + 6 bytes per pair, so::
#:
#:     max_pairs = (65535 - 14) // 6 = 10920
#:
#: Above this, fontTools' kern compiler silently truncates the length
#: field, leaving the font with a length value 16-bit-wrapped from the
#: real byte count. fontTools (and every other parser following the
#: spec) then refuses to read the table at load time. We don't try to
#: split into multiple subtables — modern shapers (HarfBuzz, DirectWrite,
#: CoreText, Skia) all prefer GPOS pair-positioning, and we write that
#: in ``_write_gpos_kern`` regardless, so legacy ``kern`` is purely a
#: fallback for very old shapers. Skipping the classic table when it
#: would overflow is the safer trade-off.
MAX_CLASSIC_KERN_PAIRS = 10920


def _write_classic_kern(font: TTFont, pairs: dict[tuple[str, str], int]) -> int:
    """Write a classic ``kern`` table. Returns the pair count written
    (0 if skipped due to size).

    When ``len(pairs)`` exceeds the 16-bit subtable length limit, this
    function refuses to write the classic ``kern`` table — GPOS still
    carries the same pairs via ``_write_gpos_kern``, so no visible
    layout is lost on modern shapers.
    """
    if len(pairs) > MAX_CLASSIC_KERN_PAIRS:
        return 0
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
    return len(pairs)


def _write_gpos_kern(font: TTFont, pairs: dict[tuple[str, str], int]) -> None:
    """Inject a GPOS PairPos lookup and rewire only the ``kern`` feature.

    Strategy (mirrors ``_strip_locl_feature``): we **never delete existing
    GPOS lookups**. The same PairPos lookups can be referenced from
    multiple features (``cpsp``/``palt``/``halt``/...) or from contextual
    positioning lookups (type 7/8) via SubstLookupRecord, so dropping them
    risks silently breaking unrelated positioning or leaving dangling
    nested-lookup indices.

    Instead:
    1. Append our new pair lookup at the end of LookupList.
    2. From the ``kern`` FeatureRecord (only), remove any LookupListIndex
       that points at an existing PairPos lookup, then append our index.
    3. Other feature records and contextual lookups stay byte-identical.

    The unhooked-from-kern existing PairPos lookups remain reachable from
    whatever other feature/lookup referenced them. If they were exclusive
    to ``kern`` they become dead but harmless (small file-size cost).
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

    # Append our new lookup. Existing lookup indices are preserved so any
    # reference (from features or contextual SubstLookupRecords) stays valid.
    new_kern_idx = len(gpos.LookupList.Lookup)
    gpos.LookupList.Lookup.append(kern_lookup)
    gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)

    # Detach existing PairPos lookups from the ``kern`` feature only.
    # They remain in LookupList for any other feature that references them.
    has_kern = False
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag != "kern":
            continue
        kept = [i for i in fr.Feature.LookupListIndex
                if i < new_kern_idx
                and not _lookup_is_pair_pos(gpos.LookupList.Lookup[i])]
        kept.append(new_kern_idx)
        fr.Feature.LookupListIndex = kept
        fr.Feature.LookupCount = len(kept)
        has_kern = True

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
    1. Add a stub glyph that **copies the design font's outline** for that
       codepoint and only changes the advance to the source's override
       value. (Earlier versions used an empty-outline stub, which made
       visible glyphs disappear under the override's script/language.)
    2. Add a single GSUB substitution under the override's (script, language)
       context, registered in the ``locl`` (Localized Forms) feature so
       browsers auto-apply it when the matching ``lang`` attribute is set.

    The result preserves the design font's visual identity while applying
    the source font's per-(script, lang) advance shifts (e.g., wider
    Korean punctuation, wider Korean space).
    """
    import copy
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

    cmap = font.getBestCmap() or {}
    glyf = font["glyf"]
    hmtx = font["hmtx"]
    glyph_order = list(font.getGlyphOrder())

    # Force-load vmtx (if present) before any stub glyph insertion. Once
    # we bump maxp.numGlyphs the raw vmtx byte size looks short to
    # fontTools' lazy decompile and the table fails to load.
    if "vmtx" in font:
        font["vmtx"]  # noqa: B018 - triggers decompile

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
            # Clone the design's glyph outline so visible glyphs stay
            # visible under the substitution. Composite glyphs reference
            # other glyphs by name, which deepcopy preserves intact.
            glyf[stub_name] = copy.deepcopy(glyf[gn])
            glyph_order.append(stub_name)
            stubs_added.append(stub_name)
            advance = _scaled(ov.advance, src_upm, dst_upm)
            # Keep the design glyph's LSB so the visible outline stays
            # positioned the same; only the advance reflects the override.
            old_lsb = hmtx.metrics[gn][1] if gn in hmtx.metrics else 0
            hmtx.metrics[stub_name] = (advance, old_lsb)
            # If the design has vertical metrics, the stub must too —
            # otherwise vmtx ends up shorter than numGlyphs and the
            # font fails to reload.
            _sync_vmtx_for_stub(font, stub_name, source_glyph=gn)
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
    """Remove the design font's ``locl`` feature records and unhook them
    from every script's LangSys.

    We deliberately do NOT delete the underlying GSUB lookups — contextual
    and chaining lookups (type 5/6) reference other lookups by index inside
    their SubstLookupRecords, and tracking those indirections to safely
    drop dead lookups is fragile. Leaving the lookups in place is a small
    file-size cost; with the ``locl`` feature gone, browsers won't auto-
    activate them based on the page ``lang`` attribute, which is what
    matters for layout reproducibility.

    Returns the number of ``locl`` feature records removed.
    """
    if "GSUB" not in font:
        return 0
    gsub = font["GSUB"].table
    if not gsub or not gsub.FeatureList:
        return 0

    # Find indices of locl feature records.
    locl_feat_indices = {
        i for i, fr in enumerate(gsub.FeatureList.FeatureRecord)
        if fr.FeatureTag == "locl"
    }
    if not locl_feat_indices:
        return 0

    # Drop the locl feature records and remap remaining feature indices.
    surviving: list = []
    feat_idx_remap: dict[int, int] = {}
    for old_idx, fr in enumerate(gsub.FeatureList.FeatureRecord):
        if old_idx in locl_feat_indices:
            continue
        feat_idx_remap[old_idx] = len(surviving)
        surviving.append(fr)
    gsub.FeatureList.FeatureRecord = surviving
    gsub.FeatureList.FeatureCount = len(surviving)

    # Update every LangSys's FeatureIndex list to drop locl refs and remap
    # surviving ones.
    for sr in gsub.ScriptList.ScriptRecord:
        for ls in [sr.Script.DefaultLangSys] + [
            lsr.LangSys for lsr in sr.Script.LangSysRecord
        ]:
            if ls is None:
                continue
            ls.FeatureIndex = [feat_idx_remap[i] for i in ls.FeatureIndex
                                if i in feat_idx_remap]
            ls.FeatureCount = len(ls.FeatureIndex)

    return len(locl_feat_indices)


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
            "CFF/OTF designs are not currently supported.")

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

    if "vertical" in apply_set:
        stats["vertical"] = _apply_vertical(font, metrics, id_to_name)

    # NOTE: gsub MUST run before kerning. _apply_shaped_advances calls
    # fontTools' addOpenTypeFeaturesFromString to install the `locl`
    # GSUB substitutions, and that call rebuilds the GPOS FeatureList
    # from the FEA snippet — if kerning's GPOS PairPos lookup was
    # already written, it gets unhooked from the GPOS FeatureList
    # (the underlying lookup survives in LookupList but no feature
    # references it, so shapers see no kerning). Running kerning last
    # ensures GPOS ends in the state _apply_kerning created.
    if "gsub" in apply_set:
        src_upm_for_gsub = metrics.global_metrics.unitsPerEm
        dst_upm_for_gsub = font["head"].unitsPerEm
        stats["gsub"] = _apply_shaped_advances(
            font, metrics, id_to_name,
            src_upm=src_upm_for_gsub, dst_upm=dst_upm_for_gsub,
        )

    if "kerning" in apply_set:
        stats["kerning"] = _apply_kerning(font, metrics, id_to_name)

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
