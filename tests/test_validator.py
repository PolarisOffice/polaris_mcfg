"""M4 — validator tests."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.validator import (
    format_json,
    format_text,
    validate_cmd,
    validate_font,
)

from .conftest import make_test_font


def test_validate_self_passes(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec_path = tmp_font_dir / "t.json"
    spec_path.write_text(extract_metrics(f, deterministic=True).to_json(),
                         encoding="utf-8")
    report = validate_font(f, spec_path)
    assert report.passed, format_text(report)
    names = [c.name for c in report.checks]
    assert "required_tables" in names
    assert "advance_widths_match" in names


def test_validate_detects_advance_mismatch(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 999})
    other = make_test_font(tmp_font_dir / "other.ttf",
                           glyph_widths={".notdef": 500, "A": 600})
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(extract_metrics(src, deterministic=True).to_json(),
                         encoding="utf-8")
    report = validate_font(other, spec_path)
    assert not report.passed
    advance_check = next(c for c in report.checks
                         if c.name == "advance_widths_match")
    assert not advance_check.passed
    assert advance_check.details["differingCount"] >= 1


def test_validate_tolerance_allows_small_diff(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 600})
    other = make_test_font(tmp_font_dir / "other.ttf",
                           glyph_widths={".notdef": 500, "A": 601})
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(extract_metrics(src, deterministic=True).to_json(),
                         encoding="utf-8")
    strict = validate_font(other, spec_path, tolerance=0)
    loose = validate_font(other, spec_path, tolerance=1)
    assert not strict.passed
    assert loose.passed, format_text(loose)


def test_validate_glyph_coverage_failure(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650},
                         cmap={0x0041: "A", 0x0042: "B"})
    other = make_test_font(tmp_font_dir / "other.ttf",
                           glyph_widths={".notdef": 500, "A": 600},
                           cmap={0x0041: "A"})
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(extract_metrics(src, deterministic=True).to_json(),
                         encoding="utf-8")
    report = validate_font(other, spec_path)
    coverage = next(c for c in report.checks if c.name == "glyph_coverage")
    assert not coverage.passed
    assert coverage.details["missingCount"] >= 1


def test_validate_against_font_directly(tmp_font_dir: Path):
    """`--against` accepts a font, not just a JSON."""
    f = make_test_font(tmp_font_dir / "t.ttf")
    report = validate_font(f, f)
    assert report.passed, format_text(report)


def test_validate_round_trip_after_generate(tmp_font_dir: Path):
    """Pipeline: extract source → generate → validate against source spec."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 777, "B": 888})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650})
    spec = extract_metrics(src, deterministic=True)
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(spec.to_json(), encoding="utf-8")
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance"))
    report = validate_font(out, spec_path)
    advance = next(c for c in report.checks if c.name == "advance_widths_match")
    assert advance.passed, format_text(report)


def test_text_format_marks_pass_fail(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    report = validate_font(f, f)
    assert "PASS" in format_text(report)


def test_json_format_machine_readable(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    report = validate_font(f, f)
    obj = json.loads(format_json(report))
    assert obj["passed"] is True
    assert obj["summary"]["failed"] == 0


def test_cli_validate_exit_codes(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 999})
    other = make_test_font(tmp_font_dir / "other.ttf",
                           glyph_widths={".notdef": 500, "A": 600})
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(extract_metrics(src, deterministic=True).to_json(),
                         encoding="utf-8")
    runner = CliRunner()
    fail = runner.invoke(validate_cmd, [str(other), "--against", str(spec_path)])
    assert fail.exit_code == 1
    ok = runner.invoke(validate_cmd, [str(src), "--against", str(spec_path)])
    assert ok.exit_code == 0
