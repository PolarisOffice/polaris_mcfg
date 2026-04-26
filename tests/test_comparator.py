"""M2 — comparator tests."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from polaris_mcfg.comparator import (
    compare_cmd,
    diff_specs,
    format_json,
    format_text,
    load_spec,
)
from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.schema import codepoint_to_id

from .conftest import make_test_font


def test_identical_fonts_have_no_advance_differences(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    a = extract_metrics(f, deterministic=True)
    b = extract_metrics(f, deterministic=True)
    diff = diff_specs(a, b)
    assert diff.advance_diff.common == {}
    assert diff.advance_diff.only_in_a == []
    assert diff.advance_diff.only_in_b == []
    assert diff.advance_diff.stats["matchingCount"] == diff.advance_diff.stats["commonCount"]


def test_differing_advance_widths_reported(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 700, "B": 650, "space": 250})
    a = extract_metrics(f1)
    b = extract_metrics(f2)
    diff = diff_specs(a, b)
    aid = codepoint_to_id(0x41)
    assert aid in diff.advance_diff.common
    av, bv, delta = diff.advance_diff.common[aid]
    assert (av, bv, delta) == (600, 700, 100)


def test_threshold_treats_small_diffs_as_matching(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 601, "B": 650, "space": 250})
    a = extract_metrics(f1)
    b = extract_metrics(f2)
    diff_strict = diff_specs(a, b, threshold=0)
    diff_loose = diff_specs(a, b, threshold=1)
    aid = codepoint_to_id(0x41)
    assert aid in diff_strict.advance_diff.common
    assert aid not in diff_loose.advance_diff.common


def test_only_in_a_and_only_in_b(tmp_font_dir: Path):
    # font A has C; font B has D
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "C": 700},
                        cmap={0x0041: "A", 0x0043: "C"})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "D": 700},
                        cmap={0x0041: "A", 0x0044: "D"})
    a = extract_metrics(f1)
    b = extract_metrics(f2)
    diff = diff_specs(a, b)
    assert codepoint_to_id(0x43) in diff.advance_diff.only_in_a
    assert codepoint_to_id(0x44) in diff.advance_diff.only_in_b


def test_global_metric_difference_detected(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf", ascent=800)
    f2 = make_test_font(tmp_font_dir / "b.ttf", ascent=900)
    a = extract_metrics(f1)
    b = extract_metrics(f2)
    diff = diff_specs(a, b)
    hhea = diff.global_diff.differences["hhea"]
    assert "ascent" in hhea
    assert hhea["ascent"] == [800, 900]


def test_normalize_upm_scales_widths(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf", units_per_em=1000,
                        glyph_widths={".notdef": 500, "A": 500},
                        cmap={0x0041: "A"})
    f2 = make_test_font(tmp_font_dir / "b.ttf", units_per_em=2000,
                        glyph_widths={".notdef": 1000, "A": 1000},
                        cmap={0x0041: "A"})
    a = extract_metrics(f1)
    b = extract_metrics(f2)
    # Without normalization, widths look different (500 vs 1000).
    raw = diff_specs(a, b)
    assert codepoint_to_id(0x41) in raw.advance_diff.common
    # With normalization, they're equivalent.
    normed = diff_specs(a, b, normalize_upm=True)
    assert codepoint_to_id(0x41) not in normed.advance_diff.common


def test_kerning_diff_only_when_present(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf", kerning=[("A", "B", -50)])
    f2 = make_test_font(tmp_font_dir / "b.ttf", kerning=[("A", "B", -30)])
    a = extract_metrics(f1, include_kerning=True)
    b = extract_metrics(f2, include_kerning=True)
    diff = diff_specs(a, b)
    assert diff.kerning_diff is not None
    assert any("U+0041|U+0042" == k for k in diff.kerning_diff.common)


def test_text_format_includes_summary(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 700})
    a = extract_metrics(f1)
    b = extract_metrics(f2)
    out = format_text(diff_specs(a, b))
    assert "Glyph advance widths" in out
    assert "U+0041" in out


def test_json_format_round_trippable(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    a = extract_metrics(f, deterministic=True)
    b = extract_metrics(f, deterministic=True)
    out = format_json(diff_specs(a, b))
    obj = json.loads(out)
    assert obj["unitsPerEm"] == [1000, 1000]
    assert obj["advance"]["onlyInA"] == []


def test_load_spec_supports_json_and_font(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec_from_font = load_spec(f)
    j = tmp_font_dir / "spec.json"
    j.write_text(spec_from_font.to_json(), encoding="utf-8")
    spec_from_json = load_spec(j)
    assert spec_from_json.global_metrics.unitsPerEm == spec_from_font.global_metrics.unitsPerEm


def test_cli_compare_text(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 700})
    runner = CliRunner()
    res = runner.invoke(compare_cmd, [str(f1), str(f2)])
    assert res.exit_code == 0, res.output
    assert "Glyph advance widths" in res.output


def test_cli_compare_json(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    runner = CliRunner()
    res = runner.invoke(compare_cmd, [str(f), str(f), "--format", "json"])
    assert res.exit_code == 0
    obj = json.loads(res.output)
    assert "advance" in obj
