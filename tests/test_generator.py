"""M3 — generator tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from fontTools.ttLib import TTFont

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.generator import generate_cmd, generate_font
from polaris_mcfg.schema import codepoint_to_id

from .conftest import make_test_font


def _hmtx(font_path: Path) -> dict[str, tuple[int, int]]:
    font = TTFont(str(font_path))
    metrics = dict(font["hmtx"].metrics)
    font.close()
    return metrics


def test_generate_applies_advance_widths(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 850, "B": 920})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, apply=("advance",), scale_glyph="none")
    assert _hmtx(out)["A"][0] == 850
    assert _hmtx(out)["B"][0] == 920
    assert stats["advance"]["applied"] >= 2


def test_generate_applies_global_metrics(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         ascent=1100, descent=-300, line_gap=20)
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         ascent=800, descent=-200, line_gap=0)
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global",))
    f = TTFont(str(out))
    assert f["hhea"].ascent == 1100
    assert f["hhea"].descent == -300
    assert f["hhea"].lineGap == 20
    assert f["OS/2"].sTypoAscender == 1100
    f.close()


def test_generate_with_scale_fit_modifies_glyph_bounds(tmp_font_dir: Path):
    """Wider source advance + scale=fit should widen the design glyph."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 1200})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("advance",), scale_glyph="fit")
    f = TTFont(str(out))
    glyph = f["glyf"]["A"]
    width = glyph.xMax - glyph.xMin
    f.close()
    # design A glyph was 500u wide (box from 50..550). 2x scale → ~1000u wide.
    assert width > 800


def test_generate_missing_glyph_skip_keeps_advance_unchanged(tmp_font_dir: Path):
    # Source has C; design only has A.
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 800, "C": 999},
                         cmap={0x0041: "A", 0x0043: "C"})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600},
                         cmap={0x0041: "A"})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    stats = generate_font(spec, dsn, out, apply=("advance",),
                          missing_glyph="skip")
    assert stats["advance"]["missing"] >= 1
    # Design glyphs unchanged for the existing one — A becomes source's 800.
    assert _hmtx(out)["A"][0] == 800


def test_generate_updates_family_and_license(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf")
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out,
                  family_name="Polaris Test", style_name="Regular",
                  license_text="OFL 1.1",
                  license_url="https://scripts.sil.org/OFL")
    f = TTFont(str(out))
    name = f["name"]
    assert "Polaris Test" in str(name.getName(1, 3, 1, 0x409))
    assert "OFL" in str(name.getName(13, 3, 1, 0x409))
    assert "https://" in str(name.getName(14, 3, 1, 0x409))
    f.close()


def test_generate_round_trip_metrics_match_source(tmp_font_dir: Path):
    """Extract → generate → re-extract: advance widths should match the source."""
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 777, "B": 888})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600, "B": 650})
    spec = extract_metrics(src, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance"))
    re = extract_metrics(out, deterministic=True)
    aid = codepoint_to_id(0x41)
    bid = codepoint_to_id(0x42)
    assert re.glyphs[aid].advanceWidth == spec.glyphs[aid].advanceWidth
    assert re.glyphs[bid].advanceWidth == spec.glyphs[bid].advanceWidth


def test_generate_kerning_applied(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         kerning=[("A", "B", -77)])
    dsn = make_test_font(tmp_font_dir / "dsn.ttf")
    spec = extract_metrics(src, include_kerning=True, deterministic=True)
    out = tmp_font_dir / "out.ttf"
    generate_font(spec, dsn, out, apply=("global", "advance", "kerning"))
    f = TTFont(str(out))
    assert "kern" in f
    sub = f["kern"].kernTables[0]
    assert sub.kernTable[("A", "B")] == -77
    f.close()


def test_generate_rejects_cff(tmp_font_dir: Path):
    """OTF/CFF designs are deferred — must error clearly."""
    from fontTools.fontBuilder import FontBuilder
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({0x41: "A"})
    fb.setupCFF("Test-Regular", {"FullName": "Test Regular"},
                {".notdef": _empty_t2_charstring(), "A": _empty_t2_charstring()},
                {})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (600, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupPost()
    cff_path = tmp_font_dir / "design.otf"
    fb.save(str(cff_path))

    src = make_test_font(tmp_font_dir / "src.ttf")
    spec = extract_metrics(src, deterministic=True)
    with pytest.raises(click.UsageError):
        generate_font(spec, cff_path, tmp_font_dir / "out.ttf")


def _empty_t2_charstring():
    """Minimal valid CFF charstring (just endchar)."""
    from fontTools.misc.psCharStrings import T2CharString
    return T2CharString(program=["endchar"])


# Need this import only for the CFF rejection test
import click  # noqa: E402


def test_cli_generate(tmp_font_dir: Path):
    src = make_test_font(tmp_font_dir / "src.ttf",
                         glyph_widths={".notdef": 500, "A": 999})
    dsn = make_test_font(tmp_font_dir / "dsn.ttf",
                         glyph_widths={".notdef": 500, "A": 600})
    spec = extract_metrics(src, deterministic=True)
    spec_path = tmp_font_dir / "src.json"
    spec_path.write_text(spec.to_json(), encoding="utf-8")
    out = tmp_font_dir / "out.ttf"
    runner = CliRunner()
    res = runner.invoke(generate_cmd, [
        "--metrics", str(spec_path),
        "--design", str(dsn),
        "-o", str(out),
        "--apply", "global,advance",
        "--scale-glyph", "none",
    ])
    assert res.exit_code == 0, res.output
    assert out.exists()
    assert _hmtx(out)["A"][0] == 999
