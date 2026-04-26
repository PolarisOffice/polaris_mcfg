"""MetricsSpec — single data model shared by all subcommands.

The on-disk JSON form follows ``Requirements.md`` §4 (camelCase keys, glyph
identifiers as ``U+XXXX`` or ``glyph#name``). Python attribute names mirror the
JSON keys, except ``global`` which is reserved (we expose it as
``global_metrics`` and serialize as ``global``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class GlyphMetric:
    advanceWidth: int
    lsb: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"advanceWidth": self.advanceWidth}
        if self.lsb is not None:
            d["lsb"] = self.lsb
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GlyphMetric":
        return cls(advanceWidth=int(d["advanceWidth"]),
                   lsb=int(d["lsb"]) if "lsb" in d else None)


@dataclass
class KerningPair:
    left: str
    right: str
    value: int

    def to_dict(self) -> dict[str, Any]:
        return {"left": self.left, "right": self.right, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "KerningPair":
        return cls(left=d["left"], right=d["right"], value=int(d["value"]))


@dataclass
class VerticalGlyphMetric:
    advanceHeight: int
    tsb: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"advanceHeight": self.advanceHeight}
        if self.tsb is not None:
            d["tsb"] = self.tsb
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerticalGlyphMetric":
        return cls(advanceHeight=int(d["advanceHeight"]),
                   tsb=int(d["tsb"]) if "tsb" in d else None)


@dataclass
class GlobalMetrics:
    """Layout-affecting global metrics, mirrored from ``head/hhea/OS/2/post``.

    Every field is a plain dict to keep round-tripping trivial. Field membership
    is fixed by ``EXTRACTED_FIELDS`` in ``extractor.py``.
    """
    unitsPerEm: int
    head: dict[str, Any] = field(default_factory=dict)
    hhea: dict[str, Any] = field(default_factory=dict)
    os2: dict[str, Any] = field(default_factory=dict)
    post: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unitsPerEm": self.unitsPerEm,
            "head": dict(self.head),
            "hhea": dict(self.hhea),
            "os2": dict(self.os2),
            "post": dict(self.post),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GlobalMetrics":
        return cls(
            unitsPerEm=int(d["unitsPerEm"]),
            head=dict(d.get("head", {})),
            hhea=dict(d.get("hhea", {})),
            os2=dict(d.get("os2", {})),
            post=dict(d.get("post", {})),
        )


@dataclass
class VerticalMetrics:
    vhea: dict[str, Any]
    vmtx: dict[str, VerticalGlyphMetric]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vhea": dict(self.vhea),
            "vmtx": {k: v.to_dict() for k, v in sorted(self.vmtx.items())},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerticalMetrics":
        return cls(
            vhea=dict(d.get("vhea", {})),
            vmtx={k: VerticalGlyphMetric.from_dict(v)
                  for k, v in d.get("vmtx", {}).items()},
        )


@dataclass
class MetricsSpec:
    """Top-level spec.

    JSON serialization sorts ``glyphs`` and ``vmtx`` by identifier so that
    output is deterministic for byte-for-byte comparison.
    """
    schemaVersion: int = SCHEMA_VERSION
    source: dict[str, Any] = field(default_factory=dict)
    global_metrics: GlobalMetrics = field(
        default_factory=lambda: GlobalMetrics(unitsPerEm=1000))
    glyphs: dict[str, GlyphMetric] = field(default_factory=dict)
    kerning: list[KerningPair] | None = None
    vertical: VerticalMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schemaVersion": self.schemaVersion,
            "source": dict(self.source),
            "global": self.global_metrics.to_dict(),
            "glyphs": {k: v.to_dict() for k, v in sorted(self.glyphs.items())},
        }
        if self.kerning is not None:
            d["kerning"] = [
                p.to_dict() for p in
                sorted(self.kerning, key=lambda p: (p.left, p.right))
            ]
        if self.vertical is not None:
            d["vertical"] = self.vertical.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MetricsSpec":
        return cls(
            schemaVersion=int(d.get("schemaVersion", SCHEMA_VERSION)),
            source=dict(d.get("source", {})),
            global_metrics=GlobalMetrics.from_dict(d.get("global", {})),
            glyphs={k: GlyphMetric.from_dict(v)
                    for k, v in d.get("glyphs", {}).items()},
            kerning=([KerningPair.from_dict(p) for p in d["kerning"]]
                     if "kerning" in d else None),
            vertical=(VerticalMetrics.from_dict(d["vertical"])
                      if "vertical" in d else None),
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False,
                          sort_keys=False)

    @classmethod
    def from_json(cls, s: str) -> "MetricsSpec":
        return cls.from_dict(json.loads(s))


def codepoint_to_id(cp: int) -> str:
    """``0x41`` -> ``"U+0041"``, ``0x1F600`` -> ``"U+1F600"``."""
    return f"U+{cp:04X}"


def glyphname_to_id(name: str) -> str:
    """Identifier for an un-cmapped glyph (e.g., ``ligature``, ``.notdef``)."""
    return f"glyph#{name}"


def parse_id(identifier: str) -> tuple[str, int | str]:
    """Parse a glyph identifier.

    Returns
    -------
    (kind, value) where kind is ``"cp"`` and value is int, or kind is
    ``"name"`` and value is str.
    """
    if identifier.startswith("U+"):
        return ("cp", int(identifier[2:], 16))
    if identifier.startswith("glyph#"):
        return ("name", identifier[len("glyph#"):])
    raise ValueError(f"unknown glyph identifier format: {identifier!r}")
