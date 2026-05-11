"""Incremental spec update — merge new measurements into an existing spec.

Full-cmap render extraction on a CJK font takes ~40 minutes. Most of
that cost is the per-glyph LSB single-render loop (11K Hangul + 8K
Hanja). When the user only wants to fix one block's measurement
(e.g., re-measure Halfwidth/Fullwidth after a probe-set fix), it's
wasteful to redo everything.

This module supports the pattern::

    # First-time full extraction (~40 min)
    spec_v1 = extract_via_render(font, cmap=full_cmap, ...)
    spec_v1.to_json() → /tmp/spec_v1.json

    # Iterate on Halfwidth block — re-measure only those 225 chars
    # (~3 minutes) and merge into spec_v1
    spec_v2 = extract_via_render(
        font,
        update_spec="/tmp/spec_v1.json",
        refresh_blocks=["Halfwidth/Fullwidth Forms"],
        ...
    )

The merge precedence: overlay (new measurement) wins on every (glyph
id, kerning pair, shaped advance triple) the new measurement covers;
base values are kept for everything else. ``global_metrics`` and
``vertical`` come from the overlay's render (since those are single
measurements anyway).

The merge keys:
- glyphs: ``"U+XXXX"`` or ``"glyph#name"`` strings
- kerning: ``(left, right)`` codepoint-id tuples
- shaped_advances: ``(codepoint, script, language)`` triples
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..schema import (
    GlyphMetric,
    KerningPair,
    MetricsSpec,
    ShapedAdvanceOverride,
)


def load_spec(path: str | Path) -> MetricsSpec:
    """Read a previously-saved MetricsSpec JSON."""
    return MetricsSpec.from_json(Path(path).read_text(encoding="utf-8"))


def merge_specs(base: MetricsSpec, overlay: MetricsSpec) -> MetricsSpec:
    """Merge two specs. ``overlay`` wins on every entry it defines.

    What survives from base:
    - ``source`` keys not present in overlay
    - ``glyphs`` keys not present in overlay
    - ``kerning`` pairs whose (left, right) is not in overlay
    - ``shaped_advances`` whose (cp, script, lang) is not in overlay
    - ``vertical`` if overlay's is None
    - ``global_metrics`` whole-table values are overwritten by overlay
      (we always re-measure globals on a refresh, even partial)

    Returns a new ``MetricsSpec``.
    """
    # source: overlay wins per-key, base values preserved otherwise
    merged_source = dict(base.source)
    merged_source.update(overlay.source)
    merged_source["mergedFromBase"] = True

    # glyphs: overlay wins per-glyph
    merged_glyphs: dict[str, GlyphMetric] = dict(base.glyphs)
    merged_glyphs.update(overlay.glyphs)

    # kerning: overlay wins per (left, right) key
    merged_kerning: list[KerningPair] | None
    if base.kerning is None and overlay.kerning is None:
        merged_kerning = None
    else:
        by_key: dict[tuple[str, str], KerningPair] = {}
        for p in (base.kerning or []):
            by_key[(p.left, p.right)] = p
        for p in (overlay.kerning or []):
            by_key[(p.left, p.right)] = p
        merged_kerning = list(by_key.values())

    # shaped_advances: overlay wins per (cp, script, lang) key
    merged_shaped: list[ShapedAdvanceOverride] | None
    if base.shaped_advances is None and overlay.shaped_advances is None:
        merged_shaped = None
    else:
        by_triple: dict[tuple[str, str, str], ShapedAdvanceOverride] = {}
        for s in (base.shaped_advances or []):
            by_triple[(s.codepoint, s.script, s.language)] = s
        for s in (overlay.shaped_advances or []):
            by_triple[(s.codepoint, s.script, s.language)] = s
        merged_shaped = list(by_triple.values())

    # vertical: overlay wins if set
    merged_vertical = overlay.vertical if overlay.vertical is not None else base.vertical

    return MetricsSpec(
        schemaVersion=overlay.schemaVersion,
        source=merged_source,
        global_metrics=overlay.global_metrics,  # always use overlay's
        glyphs=merged_glyphs,
        kerning=merged_kerning,
        vertical=merged_vertical,
        shaped_advances=merged_shaped,
    )


def expand_refresh_set(
    refresh_cmap: list[int] | None = None,
    refresh_blocks: list[str] | None = None,
) -> set[int]:
    """Resolve ``refresh_cmap`` codepoints + named ``refresh_blocks`` into
    one set of codepoints to re-measure.

    Block names are matched against ``MONOSPACE_BLOCKS`` in the
    orchestrator (Hangul Syllables / CJK Unified Ideographs / etc.).
    Unknown block names raise ValueError.
    """
    # Local import to avoid circular: orchestrator imports incremental
    from .orchestrator import MONOSPACE_BLOCKS

    out: set[int] = set(refresh_cmap or [])
    if refresh_blocks:
        block_by_name = {name: rng for name, rng, _p in MONOSPACE_BLOCKS}
        for name in refresh_blocks:
            if name not in block_by_name:
                raise ValueError(
                    f"unknown block: {name!r}. "
                    f"Known: {sorted(block_by_name)}"
                )
            out.update(block_by_name[name])
    return out
