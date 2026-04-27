"""Tests for --match-upm + --output-format=auto/ttf/woff2 (P2/A5)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font

from .conftest import make_test_font


def test_match_upm_rescales_design(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=1000,
                         glyph_widths={".notdef": 500, "A": 600, "B": 650, "space": 250})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=2048,
                         glyph_widths={".notdef": 1000, "A": 1300, "B": 1330, "space": 500})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, match_upm=True)
    f = TTFont(str(stats["output"]))
    assert f["head"].unitsPerEm == 1000  # rescaled to source's
    f.close()
    assert stats["upmRescaledFrom"] == 2048


def test_no_match_upm_keeps_design_upm(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=1000)
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=2048,
                         glyph_widths={".notdef": 1000, "A": 1300, "B": 1330, "space": 500})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, match_upm=False)
    f = TTFont(str(stats["output"]))
    assert f["head"].unitsPerEm == 2048
    f.close()
    assert stats["upmRescaledFrom"] is None


def test_output_format_auto_picks_ttf_without_rescale(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=1000)
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=1000)
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, match_upm=True, output_format="auto")
    assert stats["outputFormat"] == "ttf"
    assert stats["output"].endswith(".ttf")


def test_output_format_auto_picks_woff2_after_rescale(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=1000)
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=2048,
                         glyph_widths={".notdef": 1000, "A": 1300, "B": 1330, "space": 500})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, match_upm=True, output_format="auto")
    assert stats["outputFormat"] == "woff2"
    assert stats["output"].endswith(".woff2")


def test_output_format_explicit_woff2(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf")
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, output_format="woff2")
    assert Path(stats["output"]).suffix == ".woff2"
    # Re-load to confirm valid WOFF2
    f = TTFont(stats["output"])
    assert f.flavor == "woff2"
    f.close()


def test_output_format_explicit_ttf_overrides_auto_woff2(tmp_font_dir: Path):
    """Force TTF even when rescale would default to WOFF2."""
    src = make_test_font(tmp_font_dir / "src.ttf", units_per_em=1000)
    dsn = make_test_font(tmp_font_dir / "dsn.ttf", units_per_em=2048,
                         glyph_widths={".notdef": 1000, "A": 1300, "B": 1330, "space": 500})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, match_upm=True, output_format="ttf")
    assert stats["outputFormat"] == "ttf"
    assert stats["output"].endswith(".ttf")


def test_notdef_advance_overridden_by_source(tmp_font_dir: Path):
    """`--missing-glyph notdef` should set design's .notdef advance to source's."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 999, "A": 600, "B": 650, "space": 250})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 250, "A": 600, "B": 650, "space": 250})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, missing_glyph="notdef")
    f = TTFont(str(out))
    assert f["hmtx"].metrics[".notdef"][0] == 999
    f.close()
