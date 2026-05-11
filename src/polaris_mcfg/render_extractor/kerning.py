"""Kerning pair measurement via HarfBuzz shaping.

We shape each candidate pair through HarfBuzz and read the x_advance of
the first glyph. HarfBuzz applies GPOS pair-positioning during shaping,
so:

    shaped_advance(left in "LR") = advance(left) + kern(left, right)

Subtracting the known per-glyph advance recovers the kerning value.

EULA boundary
-------------
HarfBuzz parses the font file internally. Our code never opens a font
table directly — we call ``hb.shape()`` (the public rendering API used
by every modern text engine including Chromium, FireFox, and Android
Skia). This is the same indirection level as a browser rendering text:
the engine reads the font, our code reads the engine's output. That
makes it a stronger EULA position than the ``file`` backend which uses
``fontTools.ttLib`` to traverse tables directly.

Pair candidates
---------------
Brute-forcing N×N pairs on a CJK font (N ≈ 10K-65K) gives 100M-4B pairs.
Production fonts kern almost exclusively within these categories:

1. ASCII × ASCII (95×95 = 9,025) — Latin body kerning.
2. ASCII × Korean punctuation (95×30 ≈ 2,850) — comma/period kerning.
3. Korean punctuation × ASCII (30×95 ≈ 2,850).

Total: ~14K candidate pairs. ``default_pair_candidates`` builds this
list. The caller can supply custom candidates via ``pair_candidates``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..schema import KerningPair, codepoint_to_id

# Default kerning threshold in font units. Pairs with |kern| < threshold
# are dropped as measurement noise. HB reports advances at font-unit
# precision (no rounding), so this is purely a "ignore tiny adjustments"
# knob, not a noise floor.
DEFAULT_KERN_THRESHOLD_UNITS = 2

# ASCII printable range (0x21..0x7E excluding space).
ASCII_PRINTABLE = list(range(0x21, 0x7F))

# Common Korean punctuation (subset that interacts with Latin kerning).
KOREAN_PUNCT = [
    0x3001,  # ideographic comma
    0x3002,  # ideographic full stop
    0xFF0C,  # fullwidth comma
    0xFF0E,  # fullwidth full stop
    0xFF1A,  # fullwidth colon
    0xFF1B,  # fullwidth semicolon
    0xFF1F,  # fullwidth question mark
    0xFF01,  # fullwidth exclamation mark
    0x2013,  # en dash
    0x2014,  # em dash
    0x2018,  # left single quote
    0x2019,  # right single quote
    0x201C,  # left double quote
    0x201D,  # right double quote
    0x2026,  # horizontal ellipsis
]


@dataclass(frozen=True)
class PairCandidate:
    """One (left_cp, right_cp) pair to probe."""
    left: int
    right: int


def default_pair_candidates(cmap: list[int] | None = None) -> list[PairCandidate]:
    """Build the default candidate list.

    If ``cmap`` is provided, only pairs whose both sides are in the cmap
    are returned. This avoids wasting renders on glyphs the font doesn't
    have.
    """
    cmap_set = set(cmap) if cmap is not None else None

    def _ok(cp: int) -> bool:
        return cmap_set is None or cp in cmap_set

    out: list[PairCandidate] = []
    for l in ASCII_PRINTABLE:
        if not _ok(l):
            continue
        for r in ASCII_PRINTABLE:
            if not _ok(r):
                continue
            out.append(PairCandidate(l, r))
    for l in ASCII_PRINTABLE:
        if not _ok(l):
            continue
        for r in KOREAN_PUNCT:
            if not _ok(r):
                continue
            out.append(PairCandidate(l, r))
    for l in KOREAN_PUNCT:
        if not _ok(l):
            continue
        for r in ASCII_PRINTABLE:
            if not _ok(r):
                continue
            out.append(PairCandidate(l, r))
    return out


def _open_hb_font(font_path: Path):
    """Open a HarfBuzz font from path. Lazily imports hb so missing
    uharfbuzz only errors when this is actually called."""
    try:
        import uharfbuzz as hb
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Render-extractor kerning requires `uharfbuzz`. Install with "
            "`pip install -e '.[dev]'` or `pip install uharfbuzz`."
        ) from e
    blob = hb.Blob.from_file_path(str(font_path))
    face = hb.Face(blob)
    font = hb.Font(face)
    return hb, font, face.upem


def shape_pair_total_advance(hb_font, hb_module, left_cp: int,
                             right_cp: int) -> int | None:
    """Shape ``[left, right]`` and return the total advance of both glyphs.

    HarfBuzz distributes pair-positioning between ``x_advance[0]`` and
    ``x_offset[1]`` (with classic ``kern`` tables) or fully into
    ``x_advance[0]`` (with GPOS PairPos Value1). Reading just
    ``positions[0].x_advance`` therefore under-counts kern by half on
    classic-kern fonts. Summing the total advance — equivalent to
    measuring where the cursor ends up after drawing both glyphs —
    captures the full pair adjustment regardless of distribution::

        total_adv  = sum(p.x_advance for p in positions)
        no_kern    = adv(left) + adv(right)   # singleton shapes
        kern_pair  = total_adv - no_kern

    Returns
    -------
    int | None
        Font-unit total advance of the pair, or ``None`` if either glyph
        mapped to .notdef.
    """
    buf = hb_module.Buffer()
    buf.add_codepoints([left_cp, right_cp])
    buf.guess_segment_properties()
    hb_module.shape(hb_font, buf)
    infos = buf.glyph_infos
    positions = buf.glyph_positions
    if len(infos) != 2 or infos[0].codepoint == 0 or infos[1].codepoint == 0:
        return None
    return int(sum(p.x_advance for p in positions))


def shape_single_advance(hb_font, hb_module, cp: int) -> int | None:
    """Shape a single character and return its advance.

    Used as the reference value for the kerning subtraction.
    """
    buf = hb_module.Buffer()
    buf.add_codepoints([cp])
    buf.guess_segment_properties()
    hb_module.shape(hb_font, buf)
    infos = buf.glyph_infos
    positions = buf.glyph_positions
    if not infos or infos[0].codepoint == 0:
        return None
    return int(positions[0].x_advance)


def extract_kerning_pairs(
    font_path: Path,
    candidates: list[PairCandidate],
    *,
    threshold_units: int = DEFAULT_KERN_THRESHOLD_UNITS,
    progress: bool = False,
) -> list[KerningPair]:
    """Shape each candidate pair through HarfBuzz and keep non-zero kerns.

    Returns a list of :class:`KerningPair` filtered by ``threshold_units``.
    """
    hb, font, upem = _open_hb_font(font_path)

    # Cache singleton advances so each unique codepoint is shaped once.
    singleton_advance: dict[int, int] = {}

    def _adv(cp: int) -> int | None:
        if cp not in singleton_advance:
            v = shape_single_advance(font, hb, cp)
            if v is None:
                return None
            singleton_advance[cp] = v
        return singleton_advance[cp]

    out: list[KerningPair] = []
    for i, pc in enumerate(candidates):
        adv_l = _adv(pc.left)
        adv_r = _adv(pc.right)
        if adv_l is None or adv_r is None:
            continue
        shaped_total = shape_pair_total_advance(font, hb, pc.left, pc.right)
        if shaped_total is None:
            continue
        kern_units = shaped_total - (adv_l + adv_r)
        if abs(kern_units) < threshold_units:
            continue
        out.append(KerningPair(
            left=codepoint_to_id(pc.left),
            right=codepoint_to_id(pc.right),
            value=int(kern_units),
        ))
        if progress and (i + 1) % 2000 == 0:
            print(f"  ... kerning {i + 1}/{len(candidates)} pairs probed, "
                  f"{len(out)} kept")
    return out
