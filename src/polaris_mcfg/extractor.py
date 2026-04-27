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
    ShapedAdvanceOverride,
    VerticalGlyphMetric,
    VerticalMetrics,
    codepoint_to_id,
    glyphname_to_id,
)

#: Default (script, language) tuples probed for shape-induced advance
#: differences. Extend as needed; keeping this list short keeps extraction
#: snappy on huge CJK fonts (one shape call per (codepoint, context)).
DEFAULT_SHAPING_CONTEXTS = (
    ("hang", "KOR"),  # Korean
    ("hani", "ZHS"),  # Simplified Chinese
    ("hani", "ZHT"),  # Traditional Chinese
    ("kana", "JAN"),  # Japanese
)

#: Tables the extractor is permitted to load. Every other table — notably
#: ``glyf``/``CFF``/``CFF2`` which carry copyrighted outline data — must remain
#: unread. See ``docs/design/02-metrics-schema.md`` §라이센스 안전 경계.
ALLOWED_TABLES = frozenset({
    "head", "hhea", "OS/2", "post", "hmtx", "cmap",
    "kern", "vhea", "vmtx",
    # GPOS for pair-positioning (kerning) extraction. We only read PairPos
    # subtables (lookup type 2); other lookups (mark/cursive/context) are
    # ignored. This is still purely numeric data, not outline data.
    "GPOS",
    # GSUB is read only when ``include_gsub=True`` is requested. Substitution
    # data is structural / lookup-table information, not glyph outlines.
    "GSUB",
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
    # Script-coverage bits. Browsers consult these (along with ``cmap``) to
    # decide whether the font is suitable for a given lang/script and to
    # apply per-script text spacing (e.g., Korean inter-character spacing
    # when ``lang="ko"`` is set). When they disagree with the source font
    # the result diverges from the reference at the layout level.
    "ulUnicodeRange1", "ulUnicodeRange2", "ulUnicodeRange3", "ulUnicodeRange4",
    "ulCodePageRange1", "ulCodePageRange2",
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


def _extract_classic_kern(font: TTFont, id_of: dict[str, str]) -> list[KerningPair]:
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


def _invert_classdef(classdef, universe: set[str]) -> dict[int, list[str]]:
    """Invert ``ClassDef`` into ``{class_index: [glyph_names]}``.

    Class 0 is the implicit "everything not in another class" bucket — it
    must be populated from the caller-provided universe.
    """
    out: dict[int, list[str]] = {0: []}
    explicit: set[str] = set()
    for g, c in classdef.classDefs.items():
        out.setdefault(c, []).append(g)
        explicit.add(g)
    out[0].extend(g for g in universe if g not in explicit)
    return out


def _resolve_extension(subtable):
    """Unwrap a Lookup type 9 (Extension Positioning) subtable."""
    if hasattr(subtable, "ExtSubTable"):
        return subtable.ExtSubTable, subtable.ExtensionLookupType
    return subtable, None


def _extract_gpos_pairs(font: TTFont, id_of: dict[str, str]) -> list[KerningPair]:
    """Extract GPOS lookup type 2 (PairPos) Format 1 + 2 as KerningPairs.

    Mark/cursive/context lookups are ignored. Only the X-advance adjustment of
    Value1 is read; complex value records (XPlacement, YAdvance, YPlacement)
    don't survive the lossy conversion to a plain pair list.
    """
    out: list[KerningPair] = []
    if "GPOS" not in font:
        return out
    table = font["GPOS"].table
    if not table or not getattr(table, "LookupList", None):
        return out
    glyph_universe = set(font.getGlyphOrder())
    seen: dict[tuple[str, str], int] = {}

    for lookup in table.LookupList.Lookup:
        # Lookup may be wrapped in Extension (type 9). Resolve.
        for raw in lookup.SubTable:
            sub, ext_type = _resolve_extension(raw)
            effective_type = ext_type if ext_type is not None else lookup.LookupType
            if effective_type != 2:
                continue
            fmt = getattr(sub, "Format", None)
            if fmt == 1:
                _harvest_pairpos1(sub, id_of, seen)
            elif fmt == 2:
                _harvest_pairpos2(sub, glyph_universe, id_of, seen)

    for (l, r), v in seen.items():
        out.append(KerningPair(left=l, right=r, value=v))
    return out


def _value_x_advance(value_record) -> int:
    if value_record is None:
        return 0
    v = getattr(value_record, "XAdvance", 0)
    return int(v) if v is not None else 0


def _harvest_pairpos1(sub, id_of: dict[str, str],
                      seen: dict[tuple[str, str], int]) -> None:
    coverage = sub.Coverage.glyphs
    for first_idx, pair_set in enumerate(sub.PairSet):
        g1 = coverage[first_idx]
        if g1 not in id_of:
            continue
        for pvr in pair_set.PairValueRecord:
            g2 = pvr.SecondGlyph
            if g2 not in id_of:
                continue
            adj = _value_x_advance(pvr.Value1)
            if adj == 0:
                continue
            seen.setdefault((id_of[g1], id_of[g2]), adj)


def _harvest_pairpos2(sub, glyph_universe: set[str], id_of: dict[str, str],
                      seen: dict[tuple[str, str], int]) -> None:
    coverage = set(sub.Coverage.glyphs)
    class1 = _invert_classdef(sub.ClassDef1, coverage)
    class2 = _invert_classdef(sub.ClassDef2, glyph_universe)
    for c1 in range(sub.Class1Count):
        c1_record = sub.Class1Record[c1]
        for c2 in range(sub.Class2Count):
            rec = c1_record.Class2Record[c2]
            adj = _value_x_advance(rec.Value1)
            if adj == 0:
                continue
            for g1 in class1.get(c1, []):
                if g1 not in id_of:
                    continue
                gid1 = id_of[g1]
                for g2 in class2.get(c2, []):
                    if g2 not in id_of:
                        continue
                    seen.setdefault((gid1, id_of[g2]), adj)


def _extract_kerning(font: TTFont, id_of: dict[str, str]) -> list[KerningPair]:
    """Combine classic ``kern`` and GPOS pair-positioning lookups.

    For pairs that appear in both sources, classic ``kern`` wins (it's
    explicit and per-glyph; GPOS class-based often produces noisier values).
    """
    pairs: list[KerningPair] = []
    seen: set[tuple[str, str]] = set()
    for p in _extract_classic_kern(font, id_of):
        pairs.append(p)
        seen.add((p.left, p.right))
    for p in _extract_gpos_pairs(font, id_of):
        if (p.left, p.right) in seen:
            continue
        pairs.append(p)
        seen.add((p.left, p.right))
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


def _extract_shaped_advances(
    font_path: Path,
    cmap: dict[int, str],
    contexts: tuple[tuple[str, str], ...] = DEFAULT_SHAPING_CONTEXTS,
) -> list[ShapedAdvanceOverride]:
    """Detect cmap codepoints whose total shaped advance differs under any
    of the given (script, language) contexts vs the default shape.

    Uses HarfBuzz to drive the comparison so substitutions, contextual
    positioning, and lookups all participate. Only the resulting *advance*
    is recorded; the substituted glyph itself isn't extracted.
    """
    try:
        import uharfbuzz as hb
    except ImportError as e:
        raise RuntimeError(
            "include_gsub=True requires uharfbuzz but it is not installed. "
            "From a checkout: `pip install -e '.[dev]'`. "
            "Standalone: `pip install uharfbuzz`."
        ) from e

    blob = hb.Blob.from_file_path(str(font_path))
    face = hb.Face(blob)
    font = hb.Font(face)
    upem = face.upem

    out: list[ShapedAdvanceOverride] = []
    for cp in cmap:
        # default
        buf = hb.Buffer()
        buf.add_codepoints([cp])
        buf.guess_segment_properties()
        hb.shape(font, buf)
        default_adv = sum(p.x_advance for p in buf.glyph_positions)

        for script, lang in contexts:
            buf = hb.Buffer()
            buf.add_codepoints([cp])
            buf.script = script
            buf.language = lang
            buf.direction = "ltr"
            hb.shape(font, buf)
            ctx_adv = sum(p.x_advance for p in buf.glyph_positions)
            if ctx_adv != default_adv:
                out.append(ShapedAdvanceOverride(
                    codepoint=codepoint_to_id(cp),
                    script=script,
                    language=lang,
                    advance=int(ctx_adv),
                ))
    return out


def extract_metrics(
    font_path: str | Path,
    *,
    include_lsb: bool = False,
    include_kerning: bool = False,
    include_vertical: bool = False,
    include_gsub: bool = False,
    gsub_contexts: tuple[tuple[str, str], ...] = DEFAULT_SHAPING_CONTEXTS,
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
    shaped_advances = None
    if include_gsub:
        cmap_dict: dict[int, str] = font.getBestCmap() or {}
        shaped_advances = _extract_shaped_advances(font_path, cmap_dict,
                                                    gsub_contexts)

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
        shaped_advances=shaped_advances,
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
@click.option("--include-gsub", is_flag=True,
              help="Detect script/language-specific shape-induced advance "
                   "overrides (e.g., Korean wider space) via HarfBuzz. "
                   "Stored as `shapedAdvances` for opt-in `--apply gsub` "
                   "in the generator. Slower than other extractors.")
@click.option("--deterministic", is_flag=True,
              help="Fix volatile fields (timestamp) for reproducible output.")
@click.option("--indent", type=int, default=2, show_default=True)
def extract_cmd(font: Path, output: Path | None, include_lsb: bool,
                include_kerning: bool, include_vertical: bool,
                include_gsub: bool,
                deterministic: bool, indent: int) -> None:
    spec = extract_metrics(
        font,
        include_lsb=include_lsb,
        include_kerning=include_kerning,
        include_vertical=include_vertical,
        include_gsub=include_gsub,
        deterministic=deterministic,
    )
    text = spec.to_json(indent=indent)
    if output is None:
        click.echo(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        click.echo(f"wrote {output} ({len(spec.glyphs)} glyphs)", err=True)
