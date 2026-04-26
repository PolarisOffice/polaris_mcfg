"""Schema round-trip and identifier helper tests."""
from __future__ import annotations

import json

from polaris_mcfg.schema import (
    GlobalMetrics,
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    VerticalGlyphMetric,
    VerticalMetrics,
    codepoint_to_id,
    glyphname_to_id,
    parse_id,
)


def test_codepoint_id_zero_pads_to_four():
    assert codepoint_to_id(0x41) == "U+0041"
    assert codepoint_to_id(0xAC00) == "U+AC00"
    assert codepoint_to_id(0x1F600) == "U+1F600"


def test_glyphname_id_prefix():
    assert glyphname_to_id(".notdef") == "glyph#.notdef"


def test_parse_id_round_trip():
    assert parse_id("U+0041") == ("cp", 0x41)
    assert parse_id("U+1F600") == ("cp", 0x1F600)
    assert parse_id("glyph#liga_AB") == ("name", "liga_AB")


def test_metricspec_round_trip():
    spec = MetricsSpec(
        source={"filename": "x.ttf", "sha256": "abc", "extractedAt": "x",
                "extractorVersion": "0.0"},
        global_metrics=GlobalMetrics(unitsPerEm=1000,
                                     head={"unitsPerEm": 1000},
                                     hhea={"ascent": 800, "descent": -200},
                                     os2={"sTypoAscender": 800},
                                     post={"italicAngle": 0.0}),
        glyphs={
            "U+0042": GlyphMetric(advanceWidth=650, lsb=10),
            "U+0041": GlyphMetric(advanceWidth=600),
        },
        kerning=[KerningPair(left="U+0041", right="U+0056", value=-80)],
        vertical=VerticalMetrics(
            vhea={"ascent": 500},
            vmtx={"U+0041": VerticalGlyphMetric(advanceHeight=1000, tsb=0)},
        ),
    )
    s = spec.to_json()
    restored = MetricsSpec.from_json(s)
    assert restored.to_dict() == spec.to_dict()


def test_glyphs_serialized_in_sorted_order():
    spec = MetricsSpec(
        source={},
        global_metrics=GlobalMetrics(unitsPerEm=1000),
        glyphs={
            "U+0042": GlyphMetric(advanceWidth=2),
            "U+0041": GlyphMetric(advanceWidth=1),
            "U+0040": GlyphMetric(advanceWidth=0),
        },
    )
    keys = list(json.loads(spec.to_json())["glyphs"].keys())
    assert keys == sorted(keys)


def test_optional_lsb_omitted_when_none():
    gm = GlyphMetric(advanceWidth=600)
    assert "lsb" not in gm.to_dict()
    gm2 = GlyphMetric(advanceWidth=600, lsb=10)
    assert gm2.to_dict()["lsb"] == 10
