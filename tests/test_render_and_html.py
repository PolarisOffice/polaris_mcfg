"""M6 — HarfBuzz rendering helpers + HTML report tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from polaris_mcfg.comparator import diff_specs
from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.render import (
    DEFAULT_RENDER_TEXTS,
    compare_rendering,
    load_render_texts,
    measure_line,
)
from polaris_mcfg.report import format_html
from polaris_mcfg.validator import validate_font

from .conftest import make_test_font


def test_measure_line_returns_advance_sum(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf",
                       glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    m = measure_line(f, "AB")
    # x_advances reported by HarfBuzz are in font units = 600 + 650.
    assert m.width == 1250
    assert m.glyph_count == 2


def test_compare_rendering_pass_when_widths_match(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 800, "B": 850, "space": 250})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance"))
    cmp = compare_rendering(out, src, ["A B", "BA"], tolerance_pct=0.1)
    assert cmp.passed, cmp.lines


def test_compare_rendering_fail_when_widths_differ(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 1200, "B": 650, "space": 250})
    cmp = compare_rendering(f1, f2, ["AAAA"], tolerance_pct=1.0)
    assert not cmp.passed
    assert cmp.lines[0]["deltaPct"] > 1.0


def test_load_render_texts_uses_defaults_for_none():
    assert load_render_texts(None) == list(DEFAULT_RENDER_TEXTS)


def test_load_render_texts_reads_file(tmp_path: Path):
    p = tmp_path / "samples.txt"
    p.write_text("hello\n\nworld\n", encoding="utf-8")
    assert load_render_texts(p) == ["hello", "world"]


def test_format_html_smoke(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 700})
    diff = diff_specs(extract_metrics(f1, deterministic=True),
                      extract_metrics(f2, deterministic=True))
    html_text = format_html(diff)
    assert html_text.startswith("<!DOCTYPE html>")
    assert "Polaris MCFG diff" in html_text
    assert "Glyph advance widths" in html_text
    assert "U+0041" in html_text
    # SVG histogram is present when there are deltas.
    assert "<svg" in html_text


def test_format_html_with_render_comparison(tmp_font_dir: Path):
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    diff = diff_specs(extract_metrics(f1, deterministic=True),
                      extract_metrics(f2, deterministic=True))
    rc = compare_rendering(f1, f2, ["A B"], tolerance_pct=0.1)
    html_text = format_html(diff, render_comparison=rc)
    assert "Rendering regression" in html_text


def test_validator_rendering_check_added_when_against_font(tmp_font_dir: Path):
    """`--render-test` against a font file inserts a `rendering_match` check."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 800, "B": 850, "space": 250})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance"))
    report = validate_font(out, src, render_texts=["A B", "BA"],
                           render_tolerance_pct=0.1)
    names = {c.name for c in report.checks}
    assert "rendering_match" in names
    rc = next(c for c in report.checks if c.name == "rendering_match")
    assert rc.passed


def test_validator_rendering_skipped_when_against_json(tmp_font_dir: Path):
    """No rendering test if `--against` is a JSON spec."""
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec_path = tmp_font_dir / "t.json"
    spec_path.write_text(extract_metrics(f, deterministic=True).to_json(),
                         encoding="utf-8")
    report = validate_font(f, spec_path, render_texts=list(DEFAULT_RENDER_TEXTS))
    names = {c.name for c in report.checks}
    assert "rendering_match" not in names


def test_html_output_is_valid_xml_ish(tmp_font_dir: Path):
    """Sanity: every opened tag we know of should close."""
    f1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 600})
    f2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 700})
    diff = diff_specs(extract_metrics(f1, deterministic=True),
                      extract_metrics(f2, deterministic=True))
    html_text = format_html(diff)
    for tag in ("html", "head", "body", "table", "svg"):
        assert html_text.count(f"<{tag}") <= html_text.count(f"</{tag}")
