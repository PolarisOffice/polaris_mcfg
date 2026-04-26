"""M5 — exercise the optional-metric paths end-to-end.

Most LSB / kerning / vertical paths are already covered piecemeal in
test_extractor / test_comparator / test_generator / test_validator. These
tests glue them together for the round-trip pipeline.
"""
from __future__ import annotations

from pathlib import Path

from polaris_mcfg.comparator import diff_specs, format_text
from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_font
from polaris_mcfg.schema import codepoint_to_id
from polaris_mcfg.validator import validate_font

from .conftest import make_test_font


def test_lsb_round_trip(tmp_font_dir: Path):
    """extract --include-lsb → generate --apply lsb → validate sees lsb_match."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 700})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600})
    spec = extract_metrics(src, include_lsb=True, deterministic=True)
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(spec.to_json(), encoding="utf-8")
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "lsb"))
    report = validate_font(out, spec_path)
    names = {c.name for c in report.checks}
    assert "lsb_match" in names
    lsb_check = next(c for c in report.checks if c.name == "lsb_match")
    assert lsb_check.passed, format_text(diff_specs(
        extract_metrics(out, include_lsb=True, deterministic=True), spec))


def test_kerning_round_trip(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         kerning=[("A", "B", -77), ("B", "A", 25)])
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(spec.to_json(), encoding="utf-8")
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))
    report = validate_font(out, spec_path)
    names = {c.name for c in report.checks}
    assert "kerning_match" in names
    kc = next(c for c in report.checks if c.name == "kerning_match")
    assert kc.passed


def test_vertical_round_trip_with_synthesized_vhea(tmp_font_dir: Path):
    """Source with vhea/vmtx → design without → generator synthesizes vhea/vmtx."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.ttLib.tables._v_h_e_a import table__v_h_e_a
    from fontTools.ttLib.tables._v_m_t_x import table__v_m_t_x

    # Build a source font with manually-attached vhea/vmtx.
    src_path = make_test_font(tmp_font_dir / "src.ttf",
                              glyph_widths={".notdef": 500, "A": 700})
    from fontTools.ttLib import TTFont
    src = TTFont(str(src_path))
    vhea = table__v_h_e_a()
    vhea.tableVersion = 0x00011000
    vhea.ascent = 500
    vhea.descent = -500
    vhea.lineGap = 0
    vhea.advanceHeightMax = 1000
    vhea.minTopSideBearing = 0
    vhea.minBottomSideBearing = 0
    vhea.yMaxExtent = 1000
    vhea.caretSlopeRise = 1
    vhea.caretSlopeRun = 0
    vhea.caretOffset = 0
    vhea.metricDataFormat = 0
    vhea.numberOfVMetrics = 2
    vhea.reserved0 = vhea.reserved1 = vhea.reserved2 = vhea.reserved3 = vhea.reserved4 = 0
    src["vhea"] = vhea
    vmtx = table__v_m_t_x()
    vmtx.metrics = {".notdef": (1000, 0), "A": (1100, 50)}
    src["vmtx"] = vmtx
    src.save(str(src_path))
    src.close()

    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600})
    spec = extract_metrics(src_path, include_vertical=True, deterministic=True)
    assert spec.vertical is not None
    assert spec.vertical.vmtx[codepoint_to_id(0x41)].advanceHeight == 1100
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(spec.to_json(), encoding="utf-8")
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out,
                  apply=("global", "advance", "vertical"))
    report = validate_font(out, spec_path)
    names = {c.name for c in report.checks}
    assert "vertical_match" in names
    vc = next(c for c in report.checks if c.name == "vertical_match")
    assert vc.passed


def test_comparator_emits_vertical_diff(tmp_font_dir: Path):
    # Build two source fonts with different vmtx
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._v_h_e_a import table__v_h_e_a
    from fontTools.ttLib.tables._v_m_t_x import table__v_m_t_x

    def with_vmtx(path: Path, advance_a: int):
        f = TTFont(str(path))
        vhea = table__v_h_e_a()
        vhea.tableVersion = 0x00011000
        vhea.ascent = 500
        vhea.descent = -500
        vhea.lineGap = 0
        vhea.advanceHeightMax = 1000
        vhea.minTopSideBearing = 0
        vhea.minBottomSideBearing = 0
        vhea.yMaxExtent = 1000
        vhea.caretSlopeRise = 1
        vhea.caretSlopeRun = 0
        vhea.caretOffset = 0
        vhea.metricDataFormat = 0
        vhea.numberOfVMetrics = 2
        vhea.reserved0 = vhea.reserved1 = vhea.reserved2 = vhea.reserved3 = vhea.reserved4 = 0
        f["vhea"] = vhea
        v = table__v_m_t_x()
        v.metrics = {".notdef": (1000, 0), "A": (advance_a, 0)}
        f["vmtx"] = v
        f.save(str(path))
        f.close()

    p1 = make_test_font(tmp_font_dir / "a.ttf",
                        glyph_widths={".notdef": 500, "A": 700})
    p2 = make_test_font(tmp_font_dir / "b.ttf",
                        glyph_widths={".notdef": 500, "A": 700})
    with_vmtx(p1, advance_a=1000)
    with_vmtx(p2, advance_a=1100)

    a = extract_metrics(p1, include_vertical=True)
    b = extract_metrics(p2, include_vertical=True)
    diff = diff_specs(a, b)
    assert diff.vertical_diff is not None
    assert codepoint_to_id(0x41) in diff.vertical_diff.advance
