"""M4 — Validate a generated font against a reference (MetricsSpec or font).

Performs a series of independent checks. Exits with status 0 if all checks
pass and 1 otherwise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
from fontTools.ttLib import TTFont

from .comparator import load_spec
from .extractor import extract_metrics
from .schema import MetricsSpec

#: Tables every horizontally-laid-out font is expected to have.
REQUIRED_TABLES = ("head", "hhea", "OS/2", "post", "hmtx", "cmap", "name", "maxp")

#: Global-metric fields that are *derived* from outlines / hmtx by the font
#: tooling (xMin, xMax, etc.). Including them in equality checks would force
#: the design font's outlines to match the source's, which contradicts the
#: whole point of MCFG. They are skipped by default in
#: ``global_metrics_match`` and re-enabled with ``--strict-global``.
DERIVED_GLOBAL_FIELDS = {
    "head": {"xMin", "yMin", "xMax", "yMax"},
    "hhea": {"advanceWidthMax", "minLeftSideBearing",
             "minRightSideBearing", "xMaxExtent"},
    "os2": set(),
    "post": set(),
}


# ---------- result types ----------

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed,
                "message": self.message, "details": self.details}


@dataclass
class ValidationReport:
    font_path: str
    against_path: str
    tolerance: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fontPath": self.font_path,
            "againstPath": self.against_path,
            "tolerance": self.tolerance,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "summary": {
                "total": len(self.checks),
                "passed": sum(1 for c in self.checks if c.passed),
                "failed": sum(1 for c in self.checks if not c.passed),
            },
        }


# ---------- individual checks ----------

def _check_font_loadable(font_path: Path) -> tuple[CheckResult, TTFont | None]:
    try:
        font = TTFont(str(font_path))
    except Exception as e:  # pragma: no cover - hard to provoke
        return CheckResult("font_loadable", False, f"TTFont raised: {e!r}"), None
    return CheckResult("font_loadable", True, "TTFont loaded OK"), font


def _check_required_tables(font: TTFont) -> CheckResult:
    missing = [t for t in REQUIRED_TABLES if t not in font]
    if missing:
        return CheckResult("required_tables", False,
                           f"missing tables: {missing}",
                           {"missing": missing})
    return CheckResult("required_tables", True,
                       f"all {len(REQUIRED_TABLES)} required tables present",
                       {"required": list(REQUIRED_TABLES)})


def _check_global_metrics(actual: MetricsSpec, ref: MetricsSpec,
                          tolerance: int, *,
                          strict: bool = False) -> CheckResult:
    """Compare global metric fields (numbers within tolerance, others equal).

    Outline-derived fields (head.xMin/xMax/..., hhea.advanceWidthMax/...) are
    excluded by default — they reflect the design font's outlines, not the
    authored typographic metrics. Pass ``strict=True`` to include them.
    """
    skipped: dict[str, list[str]] = {}
    diffs: dict[str, dict[str, list[Any]]] = {}
    for tbl in ("head", "hhea", "os2", "post"):
        derived = DERIVED_GLOBAL_FIELDS.get(tbl, set())
        a = getattr(actual.global_metrics, tbl)
        b = getattr(ref.global_metrics, tbl)
        for key in sorted(set(a) | set(b)):
            if not strict and key in derived:
                skipped.setdefault(tbl, []).append(key)
                continue
            av, bv = a.get(key), b.get(key)
            if isinstance(av, int) and isinstance(bv, int):
                if abs(av - bv) > tolerance:
                    diffs.setdefault(tbl, {})[key] = [av, bv]
            else:
                if av != bv:
                    diffs.setdefault(tbl, {})[key] = [av, bv]
    if diffs:
        return CheckResult(
            "global_metrics_match", False,
            f"global metric mismatch in {sum(len(v) for v in diffs.values())} fields",
            {"diffs": diffs, "skippedDerived": skipped, "strict": strict},
        )
    msg = "all global metric fields match within tolerance"
    if skipped and not strict:
        msg += f" ({sum(len(v) for v in skipped.values())} derived fields skipped)"
    return CheckResult("global_metrics_match", True, msg,
                       {"skippedDerived": skipped, "strict": strict})


def _check_advance_widths(actual: MetricsSpec, ref: MetricsSpec,
                          tolerance: int) -> CheckResult:
    common = set(actual.glyphs) & set(ref.glyphs)
    bad: list[tuple[str, int, int]] = []
    for gid in common:
        av = actual.glyphs[gid].advanceWidth
        bv = ref.glyphs[gid].advanceWidth
        if abs(av - bv) > tolerance:
            bad.append((gid, av, bv))
    if not common:
        return CheckResult("advance_widths_match", False,
                           "no common glyphs to compare",
                           {"common": 0})
    rate = (len(common) - len(bad)) / len(common)
    if bad:
        sample = sorted(bad, key=lambda x: -abs(x[1] - x[2]))[:10]
        return CheckResult(
            "advance_widths_match", False,
            f"{len(bad)}/{len(common)} glyphs differ "
            f"(match rate {rate:.4f}, tolerance {tolerance}u)",
            {"common": len(common), "differingCount": len(bad),
             "matchRate": round(rate, 6),
             "topDiffs": [{"id": g, "actual": a, "ref": r, "delta": a - r}
                          for g, a, r in sample]},
        )
    return CheckResult("advance_widths_match", True,
                       f"all {len(common)} common glyph advances match",
                       {"common": len(common), "matchRate": 1.0})


def _check_glyph_coverage(actual: MetricsSpec, ref: MetricsSpec) -> CheckResult:
    missing = sorted(set(ref.glyphs) - set(actual.glyphs))
    if missing:
        return CheckResult(
            "glyph_coverage", False,
            f"{len(missing)} glyphs in reference are missing from font",
            {"missingCount": len(missing), "sample": missing[:20]},
        )
    return CheckResult("glyph_coverage", True,
                       f"font covers all {len(ref.glyphs)} reference glyphs")


def _check_lsb(actual: MetricsSpec, ref: MetricsSpec,
               tolerance: int) -> CheckResult | None:
    """Compare LSB only when *both* specs include it."""
    pairs = [(k, actual.glyphs[k].lsb, ref.glyphs[k].lsb)
             for k in set(actual.glyphs) & set(ref.glyphs)
             if actual.glyphs[k].lsb is not None
             and ref.glyphs[k].lsb is not None]
    if not pairs:
        return None
    bad = [(g, a, r) for g, a, r in pairs if abs(a - r) > tolerance]
    if bad:
        return CheckResult(
            "lsb_match", False,
            f"{len(bad)}/{len(pairs)} LSBs differ (tolerance {tolerance}u)",
            {"common": len(pairs), "differingCount": len(bad),
             "topDiffs": [{"id": g, "actual": a, "ref": r}
                          for g, a, r in sorted(bad, key=lambda x: -abs(x[1] - x[2]))[:10]]},
        )
    return CheckResult("lsb_match", True,
                       f"all {len(pairs)} LSBs match within tolerance",
                       {"common": len(pairs)})


def _check_kerning(actual: MetricsSpec, ref: MetricsSpec) -> CheckResult | None:
    if actual.kerning is None or ref.kerning is None:
        return None
    a = {(p.left, p.right): p.value for p in actual.kerning}
    r = {(p.left, p.right): p.value for p in ref.kerning}
    common = set(a) & set(r)
    only_in_ref = sorted(set(r) - set(a))
    differ = [k for k in common if a[k] != r[k]]
    if differ or only_in_ref:
        return CheckResult(
            "kerning_match", False,
            f"{len(differ)} pair(s) differ, "
            f"{len(only_in_ref)} reference pair(s) missing from font",
            {"differingCount": len(differ),
             "missingFromFont": only_in_ref[:20]},
        )
    return CheckResult("kerning_match", True,
                       f"all {len(common)} reference kerning pairs present and matching",
                       {"common": len(common)})


def _check_vertical(actual: MetricsSpec, ref: MetricsSpec,
                    tolerance: int) -> CheckResult | None:
    if actual.vertical is None or ref.vertical is None:
        return None
    a_vmtx = actual.vertical.vmtx
    r_vmtx = ref.vertical.vmtx
    common = set(a_vmtx) & set(r_vmtx)
    bad = [k for k in common
           if abs(a_vmtx[k].advanceHeight - r_vmtx[k].advanceHeight) > tolerance]
    if bad:
        return CheckResult(
            "vertical_match", False,
            f"{len(bad)}/{len(common)} vertical advances differ "
            f"(tolerance {tolerance}u)",
            {"common": len(common), "differingCount": len(bad)},
        )
    return CheckResult("vertical_match", True,
                       f"all {len(common)} vertical advances match",
                       {"common": len(common)})


def _check_name_metadata(font: TTFont) -> CheckResult:
    """Sanity-check the name table for required IDs."""
    name = font["name"]
    family = name.getName(1, 3, 1, 0x409) or name.getName(1, 1, 0, 0)
    if family is None:
        return CheckResult("name_metadata", False,
                           "name table is missing family name (ID 1)")
    license_desc = name.getName(13, 3, 1, 0x409)
    return CheckResult(
        "name_metadata", True,
        f"name table has family={str(family)!r}, "
        f"license={'set' if license_desc else 'unset'}",
        {"family": str(family),
         "licenseSet": license_desc is not None},
    )


# ---------- public API ----------

def validate_font(font_path: str | Path, against: str | Path,
                  *, tolerance: int = 0,
                  strict_global: bool = False,
                  include_lsb: bool = True,
                  include_kerning: bool = True,
                  include_vertical: bool = True) -> ValidationReport:
    """Run all checks. Returns a :class:`ValidationReport`."""
    font_path = Path(font_path)
    against = Path(against)
    report = ValidationReport(font_path=str(font_path),
                              against_path=str(against),
                              tolerance=tolerance)

    loadable, font = _check_font_loadable(font_path)
    report.checks.append(loadable)
    if font is None:
        return report

    report.checks.append(_check_required_tables(font))

    actual = extract_metrics(
        font_path,
        include_lsb=include_lsb,
        include_kerning=include_kerning,
        include_vertical=include_vertical,
        deterministic=True,
    )
    ref = load_spec(against, deterministic=True,
                    include_lsb=include_lsb,
                    include_kerning=include_kerning,
                    include_vertical=include_vertical)

    report.checks.append(_check_global_metrics(actual, ref, tolerance,
                                                strict=strict_global))
    report.checks.append(_check_advance_widths(actual, ref, tolerance))
    report.checks.append(_check_glyph_coverage(actual, ref))
    for opt in (
        _check_lsb(actual, ref, tolerance),
        _check_kerning(actual, ref),
        _check_vertical(actual, ref, tolerance),
    ):
        if opt is not None:
            report.checks.append(opt)
    report.checks.append(_check_name_metadata(font))

    font.close()
    return report


# ---------- formatters ----------

def format_text(report: ValidationReport) -> str:
    lines: list[str] = []
    lines.append(f"# Validation: {report.font_path}")
    lines.append(f"  against: {report.against_path}")
    lines.append(f"  tolerance: {report.tolerance}")
    lines.append(f"  result: {'PASS' if report.passed else 'FAIL'}")
    lines.append("")
    for c in report.checks:
        marker = "✓" if c.passed else "✗"
        lines.append(f"  {marker} {c.name:<24} {c.message}")
        if not c.passed and c.details:
            # Show a compact detail dump under failed checks.
            for k, v in c.details.items():
                if isinstance(v, list) and len(v) > 5:
                    v = f"{v[:5]} ... (+{len(v)-5})"
                lines.append(f"      {k}: {v}")
    return "\n".join(lines) + "\n"


def format_json(report: ValidationReport, *, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, ensure_ascii=False)


# ---------- CLI ----------

@click.command(help="Validate a font against a MetricsSpec or reference font.")
@click.argument("font", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--against", "against_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Reference: a MetricsSpec JSON or another font.")
@click.option("--tolerance", type=int, default=0, show_default=True,
              help="Allowed |delta| in font units for numeric checks.")
@click.option("--strict-global/--no-strict-global", default=False,
              show_default=True,
              help="Also check outline-derived global fields (head.xMin/xMax, "
                   "hhea.advanceWidthMax, ...). These reflect the design "
                   "font's outlines, so a mismatch is expected with MCFG.")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", show_default=True)
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              default=None)
def validate_cmd(font: Path, against_path: Path, tolerance: int,
                 strict_global: bool, fmt: str, output: Path | None) -> None:
    report = validate_font(font, against_path, tolerance=tolerance,
                           strict_global=strict_global)
    text = format_json(report) if fmt == "json" else format_text(report)
    if output is None:
        click.echo(text, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        click.echo(f"wrote {output}", err=True)
    if not report.passed:
        raise SystemExit(1)
