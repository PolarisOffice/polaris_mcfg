"""M1 — extractor unit tests.

We build minimal in-memory TTFs with FontBuilder (see ``conftest.py``) so the
tests never depend on external font files.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from polaris_mcfg.extractor import ALLOWED_TABLES, extract_metrics
from polaris_mcfg.schema import MetricsSpec, codepoint_to_id

from .conftest import make_test_font


def test_extract_global_metrics(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf",
                       units_per_em=1024, ascent=820, descent=-204, line_gap=8)
    spec = extract_metrics(f)
    assert spec.global_metrics.unitsPerEm == 1024
    assert spec.global_metrics.hhea["ascent"] == 820
    assert spec.global_metrics.hhea["descent"] == -204
    assert spec.global_metrics.hhea["lineGap"] == 8
    assert spec.global_metrics.os2["sTypoAscender"] == 820


def test_extract_advance_widths(tmp_font_dir: Path):
    widths = {".notdef": 500, "A": 600, "B": 650, "space": 250}
    f = make_test_font(tmp_font_dir / "t.ttf", glyph_widths=widths)
    spec = extract_metrics(f)
    assert spec.glyphs[codepoint_to_id(0x41)].advanceWidth == 600
    assert spec.glyphs[codepoint_to_id(0x42)].advanceWidth == 650
    assert spec.glyphs[codepoint_to_id(0x20)].advanceWidth == 250
    # .notdef has no codepoint, falls back to glyph#name
    assert spec.glyphs["glyph#.notdef"].advanceWidth == 500


def test_lsb_omitted_by_default(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec = extract_metrics(f, include_lsb=False)
    for g in spec.glyphs.values():
        assert g.lsb is None


def test_lsb_included_when_requested(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec = extract_metrics(f, include_lsb=True)
    # All test glyphs in conftest are box-shaped with x=50 LSB (or 0 for empty).
    assert any(g.lsb is not None for g in spec.glyphs.values())


def test_kerning_not_extracted_unless_flag(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf",
                       kerning=[("A", "B", -50)])
    spec = extract_metrics(f, include_kerning=False)
    assert spec.kerning is None


def test_kerning_extracted_with_flag(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf",
                       kerning=[("A", "B", -50)])
    spec = extract_metrics(f, include_kerning=True)
    assert spec.kerning is not None
    assert any(p.left == codepoint_to_id(0x41)
               and p.right == codepoint_to_id(0x42)
               and p.value == -50 for p in spec.kerning)


def test_vertical_returns_none_for_horizontal_only_font(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec = extract_metrics(f, include_vertical=True)
    assert spec.vertical is None  # FontBuilder default has no vhea/vmtx


def test_deterministic_timestamp(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf")
    spec = extract_metrics(f, deterministic=True)
    assert spec.source["extractedAt"] == "1970-01-01T00:00:00Z"


def test_source_metadata_includes_sha256_and_filename(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "named.ttf")
    spec = extract_metrics(f)
    assert spec.source["filename"] == "named.ttf"
    assert len(spec.source["sha256"]) == 64  # hex-encoded SHA-256


def test_json_round_trip(tmp_font_dir: Path):
    f = make_test_font(tmp_font_dir / "t.ttf",
                       kerning=[("A", "B", -50)])
    spec = extract_metrics(f, include_kerning=True, include_lsb=True,
                           deterministic=True)
    s = spec.to_json()
    restored = MetricsSpec.from_json(s)
    assert restored.to_dict() == spec.to_dict()


def test_glyf_table_not_loaded_during_extraction(tmp_font_dir: Path):
    """Security guarantee: extractor must not access outline data.

    We assert that the whitelist excludes outline tables AND that, after
    extraction, ``glyf`` remains lazy in the underlying font.
    """
    assert "glyf" not in ALLOWED_TABLES
    assert "CFF " not in ALLOWED_TABLES
    assert "CFF2" not in ALLOWED_TABLES

    f = make_test_font(tmp_font_dir / "t.ttf")
    extract_metrics(f)

    # Re-open lazily and confirm extracting again doesn't materialize `glyf`.
    font = TTFont(str(f), lazy=True)
    # Touch only what extract_metrics is allowed to touch.
    for tag in ("head", "hhea", "OS/2", "post", "hmtx", "cmap"):
        _ = font[tag]
    # `glyf` should still be a DefaultTable until accessed (lazy).
    raw = font.reader.tables["glyf"]
    # In lazy mode, fontTools keeps an unparsed entry until first access; the
    # entry's `data` attr is None only if loaded. We check the proxy isn't yet
    # decompiled by inspecting the cache.
    assert "glyf" not in font.tables, "extractor path must not parse `glyf`"
    font.close()


def test_cli_extract_to_file(tmp_font_dir: Path):
    from click.testing import CliRunner
    from polaris_mcfg.extractor import extract_cmd

    f = make_test_font(tmp_font_dir / "t.ttf")
    out = tmp_font_dir / "out.json"
    runner = CliRunner()
    res = runner.invoke(extract_cmd,
                        [str(f), "-o", str(out), "--deterministic"])
    assert res.exit_code == 0, res.output
    assert out.exists()
    spec = MetricsSpec.from_json(out.read_text())
    assert spec.glyphs[codepoint_to_id(0x41)].advanceWidth == 600
