"""GPOS pair kerning extraction + application tests (P0/P1)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.ttLib import TTFont

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.schema import codepoint_to_id

from .conftest import make_test_font


def _add_fea(font_path: Path, fea: str) -> None:
    """Append OpenType features from FEA source to a TTF in place."""
    font = TTFont(str(font_path))
    addOpenTypeFeaturesFromString(font, fea)
    font.save(str(font_path))


def test_extracts_gpos_pair_format1(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf")
    _add_fea(src, "feature kern { pos A B -50; pos B A -25; } kern;")
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    pairs = {(p.left, p.right): p.value for p in spec.kerning or []}
    assert pairs[(codepoint_to_id(0x41), codepoint_to_id(0x42))] == -50
    assert pairs[(codepoint_to_id(0x42), codepoint_to_id(0x41))] == -25


def test_extracts_gpos_pair_format2_class_based(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf")
    fea = """
    @CLASS_LEFT = [A];
    @CLASS_RIGHT = [B];
    feature kern {
      pos @CLASS_LEFT @CLASS_RIGHT -77;
    } kern;
    """
    _add_fea(src, fea)
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    pairs = {(p.left, p.right): p.value for p in spec.kerning or []}
    assert pairs[(codepoint_to_id(0x41), codepoint_to_id(0x42))] == -77


def test_classic_kern_takes_precedence_over_gpos(tmp_font_dir: Path):
    """When the same pair appears in both classic kern and GPOS, classic wins."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         kerning=[("A", "B", -10)])  # classic kern -10
    _add_fea(src, "feature kern { pos A B -90; } kern;")  # GPOS -90
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    pairs = {(p.left, p.right): p.value for p in spec.kerning or []}
    # Classic kern (added first in _extract_kerning) should win.
    assert pairs[(codepoint_to_id(0x41), codepoint_to_id(0x42))] == -10


def test_generator_writes_gpos_kern_lookup(tmp_font_dir: Path):
    """generate --apply kerning should produce a GPOS kern lookup the
    shaper can find (not just classic kern)."""
    src = make_test_font(tmp_font_dir / "src.ttf")
    _add_fea(src, "feature kern { pos A B -88; } kern;")
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))
    f = TTFont(str(out))
    assert "GPOS" in f, "result must have a GPOS table"
    gpos = f["GPOS"].table
    feature_tags = {fr.FeatureTag for fr in gpos.FeatureList.FeatureRecord}
    assert "kern" in feature_tags
    f.close()


def test_generator_kerning_round_trip_via_shaping(tmp_font_dir: Path):
    """End-to-end: extract → generate → re-shape proves the pair is active."""
    import uharfbuzz as hb
    src = make_test_font(tmp_font_dir / "src.ttf")
    _add_fea(src, "feature kern { pos A B -100; } kern;")
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))

    def shape(path: Path, text: str) -> int:
        blob = hb.Blob.from_file_path(str(path))
        face = hb.Face(blob); fnt = hb.Font(face)
        buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
        hb.shape(fnt, buf)
        return sum(p.x_advance for p in buf.glyph_positions)

    src_w = shape(src, "AB")
    out_w = shape(out, "AB")
    # Same kerning, same advance widths (we copied source's advances) → same total
    assert src_w == out_w


def test_existing_pairpos_lookups_are_replaced(tmp_font_dir: Path):
    """Design font's pre-existing kerning shouldn't bleed through."""
    import uharfbuzz as hb
    src = make_test_font(tmp_font_dir / "src.ttf")
    _add_fea(src, "feature kern { pos A B -10; } kern;")
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    _add_fea(dsn, "feature kern { pos A B -200; } kern;")  # design has aggressive kern
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))

    blob = hb.Blob.from_file_path(str(out))
    face = hb.Face(blob); fnt = hb.Font(face)
    buf = hb.Buffer(); buf.add_str("AB"); buf.guess_segment_properties()
    hb.shape(fnt, buf)
    out_w = sum(p.x_advance for p in buf.glyph_positions)

    # Source pair is -10, design's was -200. Result should reflect source's -10.
    # Total = 600 (A) + 650 (B) - 10 = 1240.
    assert out_w == 1240
