"""M2 — Compare two MetricsSpec instances (or two fonts).

Produces a :class:`MetricsDiff` capturing:
* per-table global metric differences
* glyph advance-width differences (common / only-in-a / only-in-b / stats)
* optional LSB / kerning / vertical diffs (when both specs include them)

Output formatters: ``text`` (human summary), ``json`` (machine-readable).
HTML output is added in M6.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from .extractor import extract_metrics
from .schema import GlyphMetric, MetricsSpec

#: Filename suffixes treated as JSON metric specs.
_JSON_SUFFIXES = frozenset({".json"})
#: Filename suffixes treated as font files.
_FONT_SUFFIXES = frozenset({".ttf", ".otf"})


def load_spec(path: str | Path, *, deterministic: bool = True,
              include_lsb: bool = True, include_kerning: bool = True,
              include_vertical: bool = True) -> MetricsSpec:
    """Load a MetricsSpec from a JSON file or extract one from a font.

    Optional sections are always included when extracting so that the
    comparator has everything to work with; the JSON branch passes them
    through unchanged.
    """
    p = Path(path)
    suf = p.suffix.lower()
    if suf in _JSON_SUFFIXES:
        return MetricsSpec.from_json(p.read_text(encoding="utf-8"))
    if suf in _FONT_SUFFIXES:
        return extract_metrics(
            p,
            include_lsb=include_lsb,
            include_kerning=include_kerning,
            include_vertical=include_vertical,
            deterministic=deterministic,
        )
    raise click.BadParameter(
        f"unrecognised file type {suf!r} (want .json/.ttf/.otf): {p}")


# ---------- diff data model ----------

@dataclass
class GlobalDiff:
    """Field-by-field differences inside the ``global`` object."""
    differences: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    """``{table_name: {field_name: [a_value, b_value]}}`` for fields that differ."""

    def to_dict(self) -> dict[str, Any]:
        return {"differences": self.differences}

    @property
    def is_empty(self) -> bool:
        return not any(self.differences.values())


@dataclass
class AdvanceDiff:
    """Per-glyph advance-width comparison."""
    common: dict[str, list[int]] = field(default_factory=dict)
    """``{glyph_id: [a_advance, b_advance, delta]}`` where ``delta = b - a``."""
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "common": self.common,
            "onlyInA": self.only_in_a,
            "onlyInB": self.only_in_b,
            "stats": self.stats,
        }


@dataclass
class KerningDiff:
    common: dict[str, list[int]] = field(default_factory=dict)
    """``{"left|right": [a_value, b_value, delta]}``"""
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "common": self.common,
            "onlyInA": self.only_in_a,
            "onlyInB": self.only_in_b,
        }


@dataclass
class VerticalDiff:
    """Per-glyph vertical advance / TSB comparison."""
    vhea: dict[str, list[Any]] = field(default_factory=dict)
    """``{field: [a_value, b_value]}`` for vhea fields that differ."""
    advance: dict[str, list[int]] = field(default_factory=dict)
    """``{glyph_id: [a_advanceHeight, b_advanceHeight, delta]}``"""
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vhea": self.vhea,
            "advance": self.advance,
            "onlyInA": self.only_in_a,
            "onlyInB": self.only_in_b,
            "stats": self.stats,
        }


@dataclass
class MetricsDiff:
    a_source: dict[str, Any] = field(default_factory=dict)
    b_source: dict[str, Any] = field(default_factory=dict)
    units_per_em: list[int] = field(default_factory=list)  # [a_upm, b_upm]
    threshold: int = 0
    global_diff: GlobalDiff = field(default_factory=GlobalDiff)
    advance_diff: AdvanceDiff = field(default_factory=AdvanceDiff)
    lsb_diff: AdvanceDiff | None = None
    kerning_diff: KerningDiff | None = None
    vertical_diff: VerticalDiff | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "aSource": self.a_source,
            "bSource": self.b_source,
            "unitsPerEm": self.units_per_em,
            "threshold": self.threshold,
            "global": self.global_diff.to_dict(),
            "advance": self.advance_diff.to_dict(),
        }
        if self.lsb_diff is not None:
            d["lsb"] = self.lsb_diff.to_dict()
        if self.kerning_diff is not None:
            d["kerning"] = self.kerning_diff.to_dict()
        if self.vertical_diff is not None:
            d["vertical"] = self.vertical_diff.to_dict()
        return d


# ---------- diff computation ----------

def _diff_dict(a: dict[str, Any], b: dict[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for k in sorted(set(a) | set(b)):
        av, bv = a.get(k, None), b.get(k, None)
        if av != bv:
            out[k] = [av, bv]
    return out


def _stats(deltas: list[int]) -> dict[str, Any]:
    if not deltas:
        return {"count": 0}
    abs_deltas = [abs(d) for d in deltas]
    return {
        "count": len(deltas),
        "meanDelta": round(statistics.fmean(deltas), 3),
        "meanAbsDelta": round(statistics.fmean(abs_deltas), 3),
        "stdevAbsDelta": round(statistics.pstdev(abs_deltas), 3) if len(deltas) > 1 else 0.0,
        "maxAbsDelta": max(abs_deltas),
        "minDelta": min(deltas),
        "maxDelta": max(deltas),
    }


def _scaled(value: int, from_upm: int, to_upm: int) -> int:
    if from_upm == to_upm:
        return value
    return round(value * to_upm / from_upm)


def _advance_diff(a_glyphs: dict[str, GlyphMetric],
                  b_glyphs: dict[str, GlyphMetric],
                  *, threshold: int,
                  normalize_upm: tuple[int, int] | None) -> AdvanceDiff:
    """Compare advance widths.

    If ``normalize_upm=(a_upm, b_upm)`` is given, both values are scaled to a
    common reference (the larger upm) before comparing — useful when the two
    fonts use different units-per-em.
    """
    common_keys = sorted(set(a_glyphs) & set(b_glyphs))
    only_a = sorted(set(a_glyphs) - set(b_glyphs))
    only_b = sorted(set(b_glyphs) - set(a_glyphs))

    if normalize_upm is not None:
        ref = max(normalize_upm)
        a_upm, b_upm = normalize_upm
    else:
        ref = a_upm = b_upm = 0  # unused

    diff = AdvanceDiff(only_in_a=only_a, only_in_b=only_b)
    deltas: list[int] = []
    matching = 0
    for k in common_keys:
        av = a_glyphs[k].advanceWidth
        bv = b_glyphs[k].advanceWidth
        if normalize_upm is not None:
            av = _scaled(av, a_upm, ref)
            bv = _scaled(bv, b_upm, ref)
        delta = bv - av
        if abs(delta) <= threshold:
            matching += 1
            continue
        diff.common[k] = [av, bv, delta]
        deltas.append(delta)

    diff.stats = {
        "commonCount": len(common_keys),
        "matchingCount": matching,
        "differingCount": len(common_keys) - matching,
        "matchRate": (matching / len(common_keys)) if common_keys else 1.0,
        "deltas": _stats(deltas),
        "onlyInACount": len(only_a),
        "onlyInBCount": len(only_b),
    }
    return diff


def _lsb_diff(a_glyphs: dict[str, GlyphMetric],
              b_glyphs: dict[str, GlyphMetric],
              *, threshold: int) -> AdvanceDiff | None:
    pairs = [(k, a_glyphs[k].lsb, b_glyphs[k].lsb)
             for k in sorted(set(a_glyphs) & set(b_glyphs))
             if a_glyphs[k].lsb is not None or b_glyphs[k].lsb is not None]
    if not pairs:
        return None
    diff = AdvanceDiff()
    deltas: list[int] = []
    matching = 0
    for k, av, bv in pairs:
        if av is None or bv is None:
            diff.common[k] = [av, bv, None]
            continue
        delta = bv - av
        if abs(delta) <= threshold:
            matching += 1
            continue
        diff.common[k] = [av, bv, delta]
        deltas.append(delta)
    diff.stats = {
        "commonCount": len(pairs),
        "matchingCount": matching,
        "differingCount": len(pairs) - matching,
        "deltas": _stats(deltas),
    }
    return diff


def _kerning_diff(a_pairs, b_pairs) -> KerningDiff | None:
    if a_pairs is None and b_pairs is None:
        return None
    a_map = {f"{p.left}|{p.right}": p.value for p in (a_pairs or [])}
    b_map = {f"{p.left}|{p.right}": p.value for p in (b_pairs or [])}
    diff = KerningDiff(
        only_in_a=sorted(set(a_map) - set(b_map)),
        only_in_b=sorted(set(b_map) - set(a_map)),
    )
    for k in sorted(set(a_map) & set(b_map)):
        if a_map[k] != b_map[k]:
            diff.common[k] = [a_map[k], b_map[k], b_map[k] - a_map[k]]
    return diff


def _vertical_diff(a, b, *, threshold: int) -> VerticalDiff | None:
    if a is None and b is None:
        return None
    a_vhea = a.vhea if a is not None else {}
    b_vhea = b.vhea if b is not None else {}
    a_vmtx = a.vmtx if a is not None else {}
    b_vmtx = b.vmtx if b is not None else {}
    diff = VerticalDiff(
        vhea=_diff_dict(a_vhea, b_vhea),
        only_in_a=sorted(set(a_vmtx) - set(b_vmtx)),
        only_in_b=sorted(set(b_vmtx) - set(a_vmtx)),
    )
    common = sorted(set(a_vmtx) & set(b_vmtx))
    deltas: list[int] = []
    matching = 0
    for k in common:
        av = a_vmtx[k].advanceHeight
        bv = b_vmtx[k].advanceHeight
        delta = bv - av
        if abs(delta) <= threshold:
            matching += 1
            continue
        diff.advance[k] = [av, bv, delta]
        deltas.append(delta)
    diff.stats = {
        "commonCount": len(common),
        "matchingCount": matching,
        "differingCount": len(common) - matching,
        "deltas": _stats(deltas),
    }
    return diff


def diff_specs(a: MetricsSpec, b: MetricsSpec, *,
               threshold: int = 0,
               normalize_upm: bool = False) -> MetricsDiff:
    a_upm = a.global_metrics.unitsPerEm
    b_upm = b.global_metrics.unitsPerEm

    g = GlobalDiff(differences={
        "head": _diff_dict(a.global_metrics.head, b.global_metrics.head),
        "hhea": _diff_dict(a.global_metrics.hhea, b.global_metrics.hhea),
        "os2": _diff_dict(a.global_metrics.os2, b.global_metrics.os2),
        "post": _diff_dict(a.global_metrics.post, b.global_metrics.post),
    })

    adv = _advance_diff(
        a.glyphs, b.glyphs, threshold=threshold,
        normalize_upm=(a_upm, b_upm) if normalize_upm else None,
    )
    lsb = _lsb_diff(a.glyphs, b.glyphs, threshold=threshold)
    kern = _kerning_diff(a.kerning, b.kerning)
    vert = _vertical_diff(a.vertical, b.vertical, threshold=threshold)

    return MetricsDiff(
        a_source=a.source, b_source=b.source,
        units_per_em=[a_upm, b_upm],
        threshold=threshold,
        global_diff=g,
        advance_diff=adv,
        lsb_diff=lsb,
        kerning_diff=kern,
        vertical_diff=vert,
    )


# ---------- formatters ----------

def format_json(diff: MetricsDiff, *, indent: int = 2) -> str:
    return json.dumps(diff.to_dict(), indent=indent, ensure_ascii=False,
                      sort_keys=False)


def format_text(diff: MetricsDiff, *, max_glyph_rows: int = 20) -> str:
    lines: list[str] = []
    a_name = diff.a_source.get("filename", "A")
    b_name = diff.b_source.get("filename", "B")
    lines.append(f"# Metrics diff: {a_name}  →  {b_name}")
    lines.append(f"  unitsPerEm: A={diff.units_per_em[0]}  B={diff.units_per_em[1]}")
    lines.append(f"  threshold: {diff.threshold}")
    lines.append("")

    # Global
    lines.append("## Global differences")
    if diff.global_diff.is_empty:
        lines.append("  (none)")
    else:
        for table, fields in diff.global_diff.differences.items():
            if not fields:
                continue
            lines.append(f"  [{table}]")
            for fname, (av, bv) in fields.items():
                lines.append(f"    {fname:<22} A={av!r:<14} B={bv!r}")
    lines.append("")

    # Advance widths
    s = diff.advance_diff.stats
    lines.append("## Glyph advance widths")
    lines.append(f"  common: {s.get('commonCount', 0)}    "
                 f"matching: {s.get('matchingCount', 0)}    "
                 f"differing: {s.get('differingCount', 0)}    "
                 f"match rate: {s.get('matchRate', 0):.3f}")
    lines.append(f"  only in A: {s.get('onlyInACount', 0)}    "
                 f"only in B: {s.get('onlyInBCount', 0)}")
    deltas = s.get("deltas", {})
    if deltas.get("count", 0):
        lines.append(f"  delta stats: mean={deltas['meanDelta']}  "
                     f"|mean|={deltas['meanAbsDelta']}  "
                     f"max|Δ|={deltas['maxAbsDelta']}  "
                     f"range=[{deltas['minDelta']}, {deltas['maxDelta']}]")
    if diff.advance_diff.common:
        lines.append(f"  top {min(max_glyph_rows, len(diff.advance_diff.common))} differing glyphs:")
        sorted_items = sorted(diff.advance_diff.common.items(),
                              key=lambda kv: -abs(kv[1][2]))
        for k, (av, bv, delta) in sorted_items[:max_glyph_rows]:
            lines.append(f"    {k:<14} A={av:<6} B={bv:<6} Δ={delta:+d}")
    lines.append("")

    # LSB
    if diff.lsb_diff is not None:
        s = diff.lsb_diff.stats
        lines.append("## LSB")
        lines.append(f"  common: {s.get('commonCount', 0)}  "
                     f"matching: {s.get('matchingCount', 0)}  "
                     f"differing: {s.get('differingCount', 0)}")
        lines.append("")

    # Kerning
    if diff.kerning_diff is not None:
        kd = diff.kerning_diff
        lines.append("## Kerning")
        lines.append(f"  differing pairs: {len(kd.common)}    "
                     f"only in A: {len(kd.only_in_a)}    "
                     f"only in B: {len(kd.only_in_b)}")
        lines.append("")

    # Vertical
    if diff.vertical_diff is not None:
        vd = diff.vertical_diff
        s = vd.stats
        lines.append("## Vertical metrics")
        if vd.vhea:
            lines.append("  [vhea]")
            for k, (av, bv) in vd.vhea.items():
                lines.append(f"    {k:<22} A={av!r:<14} B={bv!r}")
        lines.append(f"  vmtx common: {s.get('commonCount', 0)}    "
                     f"matching: {s.get('matchingCount', 0)}    "
                     f"differing: {s.get('differingCount', 0)}")
        lines.append(f"  only in A: {len(vd.only_in_a)}    "
                     f"only in B: {len(vd.only_in_b)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------- CLI ----------

@click.command(help="Compare two fonts (or two metric JSONs).")
@click.argument("a", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("b", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True)
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Output path (default: stdout).")
@click.option("--threshold", type=int, default=0, show_default=True,
              help="Differences <= N units are treated as matching.")
@click.option("--normalize-upm/--no-normalize-upm", default=False,
              show_default=True,
              help="Scale advance widths to a common upm before comparing.")
@click.option("--max-rows", type=int, default=20, show_default=True,
              help="(text format) max differing glyphs to list.")
def compare_cmd(a: Path, b: Path, fmt: str, output: Path | None,
                threshold: int, normalize_upm: bool, max_rows: int) -> None:
    spec_a = load_spec(a)
    spec_b = load_spec(b)
    diff = diff_specs(spec_a, spec_b, threshold=threshold,
                      normalize_upm=normalize_upm)

    if fmt == "json":
        text = format_json(diff)
    else:
        text = format_text(diff, max_glyph_rows=max_rows)

    if output is None:
        click.echo(text, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        click.echo(f"wrote {output}", err=True)
