"""Quantitative accuracy comparison: file backend vs render backend.

Extracts the same font twice — once via `extract_metrics` (file
backend, reads TTF tables) and once via `extract_via_render` (render
backend, FreeType + HarfBuzz). Reports per-metric diff distributions:

    - per-glyph advance width
    - per-glyph LSB
    - kerning pair values (where both backends extract them)
    - shaped advance overrides (where both detect them)

Use this to validate that the render backend stays within its
documented tolerance (±1-2 unit) on a real-world font. Run from
the repo root::

    python samples/render_vs_file_accuracy.py [<font-path>]

Default font: ``fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf``.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.render_extractor import extract_via_render
from polaris_mcfg.render_extractor.kerning import PairCandidate


# A representative cmap subset that exercises the four major categories:
#   ASCII printable (95), Latin-1 supplement (12), Korean punctuation (15),
#   first 200 Hangul syllables (so the monospace fast-path can also fire).
# Keeping this under ~400 codepoints keeps full extraction under ~1 min.
DEFAULT_SAMPLE = (
    list(range(0x21, 0x7F))  # ASCII printable
    + list(range(0x00A1, 0x00AD))  # selected Latin-1 punctuation
    + [0x3001, 0x3002, 0xFF0C, 0xFF0E, 0xFF1A, 0xFF1B,  # Korean punctuation
       0xFF1F, 0xFF01, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C,
       0x201D, 0x2026]
    + list(range(0xAC00, 0xAC00 + 200))  # 200 Hangul syllables
)


def stats(diffs: list[int], name: str) -> None:
    if not diffs:
        print(f"  {name}: no samples")
        return
    abs_d = sorted(abs(d) for d in diffs)
    n = len(abs_d)
    p50 = abs_d[int(n * 0.50)]
    p95 = abs_d[int(n * 0.95)] if n >= 20 else abs_d[-1]
    p99 = abs_d[int(n * 0.99)] if n >= 100 else abs_d[-1]
    mx = abs_d[-1]
    mean = statistics.mean(diffs)
    print(f"  {name:<32} n={n:>4}  mean={mean:+.2f}u  "
          f"|p50|={p50:>3}u  |p95|={p95:>3}u  |p99|={p99:>3}u  "
          f"|max|={mx:>3}u")


def main(font_path: Path) -> int:
    if not font_path.exists():
        print(f"font not found: {font_path}", file=sys.stderr)
        return 2

    print(f"font: {font_path}")
    print(f"sample size: {len(DEFAULT_SAMPLE)} codepoints "
          f"(ASCII + Latin-1 punct + Korean punct + 200 Hangul syllables)")
    print()

    # 1. file backend (full font; cheap)
    print("[1/2] file backend (full font, --include-lsb --include-kerning "
          "--include-gsub)...")
    t0 = time.time()
    file_spec = extract_metrics(
        font_path,
        include_lsb=True,
        include_kerning=True,
        include_gsub=True,
        deterministic=True,
    )
    t_file = time.time() - t0
    print(f"  {t_file:.2f}s  ({len(file_spec.glyphs)} glyphs, "
          f"{len(file_spec.kerning or [])} kerning pairs, "
          f"{len(file_spec.shaped_advances or [])} shaped overrides)")

    # 2. render backend (sampled cmap)
    print(f"[2/2] render backend (FreeType, subset of {len(DEFAULT_SAMPLE)} "
          "codepoints, --include-lsb --include-kerning --include-shaped)...")

    # Restrict kerning candidates to the sample (otherwise default
    # candidate list re-introduces ASCII codepoints we don't measure).
    sample_set = set(DEFAULT_SAMPLE)
    pair_cands = []
    for l in sample_set:
        for r in sample_set:
            if 0x21 <= l <= 0x7E and 0x21 <= r <= 0x7E:
                pair_cands.append(PairCandidate(l, r))
    print(f"  ({len(pair_cands)} kerning candidates)")

    t0 = time.time()
    render_spec = extract_via_render(
        font_path,
        renderer="freetype",
        cmap=DEFAULT_SAMPLE,
        include_lsb=True,
        include_kerning=True,
        include_shaped=True,
        pair_candidates=pair_cands,
    )
    t_render = time.time() - t0
    print(f"  {t_render:.2f}s  ({len(render_spec.glyphs)} glyphs, "
          f"{len(render_spec.kerning or [])} kerning pairs, "
          f"{len(render_spec.shaped_advances or [])} shaped overrides)")
    print(f"  speed ratio: render is {t_render / t_file:.1f}× slower per glyph")
    print()

    # Diff analysis
    print("=" * 78)
    print("DIFF ANALYSIS (render − file)")
    print("=" * 78)

    # Per-glyph advance + LSB
    adv_diffs: list[int] = []
    adv_diffs_latin: list[int] = []
    adv_diffs_hangul: list[int] = []
    lsb_diffs: list[int] = []
    for cp in DEFAULT_SAMPLE:
        gid = f"U+{cp:04X}"
        if gid not in file_spec.glyphs or gid not in render_spec.glyphs:
            continue
        fa = file_spec.glyphs[gid].advanceWidth
        ra = render_spec.glyphs[gid].advanceWidth
        d = ra - fa
        adv_diffs.append(d)
        if 0x21 <= cp <= 0x7E or 0xA1 <= cp <= 0xFF:
            adv_diffs_latin.append(d)
        elif 0xAC00 <= cp <= 0xD7A3:
            adv_diffs_hangul.append(d)
        fl = file_spec.glyphs[gid].lsb
        rl = render_spec.glyphs[gid].lsb
        if fl is not None and rl is not None:
            lsb_diffs.append(rl - fl)
    print("\nPer-glyph advance (overall + by category):")
    stats(adv_diffs, "advance — all")
    stats(adv_diffs_latin, "advance — Latin / Latin-1")
    stats(adv_diffs_hangul, "advance — Hangul Syllables")

    print("\nPer-glyph LSB:")
    stats(lsb_diffs, "lsb — all")

    # Kerning agreement
    file_kerns = {(p.left, p.right): p.value
                  for p in (file_spec.kerning or [])}
    render_kerns = {(p.left, p.right): p.value
                    for p in (render_spec.kerning or [])}
    overlap = set(file_kerns.keys()) & set(render_kerns.keys())
    kern_diffs = [render_kerns[k] - file_kerns[k] for k in overlap]
    print(f"\nKerning pairs (overlap of {len(overlap)} pairs out of "
          f"file's {len(file_kerns)} / render's {len(render_kerns)}):")
    stats(kern_diffs, "kerning value")
    file_only = set(file_kerns) - set(render_kerns)
    render_only = set(render_kerns) - set(file_kerns)
    print(f"  file-only pairs not measured by render: {len(file_only)}")
    print(f"  render-only pairs absent from file: {len(render_only)}")

    # Shaped advance agreement
    file_shaped = {(s.codepoint, s.script, s.language): s.advance
                   for s in (file_spec.shaped_advances or [])}
    render_shaped = {(s.codepoint, s.script, s.language): s.advance
                     for s in (render_spec.shaped_advances or [])}
    overlap_sh = set(file_shaped) & set(render_shaped)
    sh_diffs = [render_shaped[k] - file_shaped[k] for k in overlap_sh]
    print(f"\nShaped-advance overrides (overlap of {len(overlap_sh)}, "
          f"file {len(file_shaped)} / render {len(render_shaped)}):")
    stats(sh_diffs, "shaped advance")

    # Pass / fail gate (matches the gates from
    # docs/design/12-render-extractor.md §7)
    print()
    print("=" * 78)
    print("ACCURACY GATES (docs/design/12-render-extractor.md §7)")
    print("=" * 78)
    gates = [
        ("advance p95 ≤ 2u",
         max(abs(d) for d in adv_diffs[: int(0.95 * len(adv_diffs)) + 1])
         <= 2 if adv_diffs else True),
        ("advance |max| ≤ 5u",
         max(abs(d) for d in adv_diffs) <= 5 if adv_diffs else True),
        ("LSB p95 ≤ 5u",
         (sorted(abs(d) for d in lsb_diffs)[int(0.95 * len(lsb_diffs))]
          <= 5 if lsb_diffs else True)),
        ("kerning exact (overlap diff = 0)",
         all(d == 0 for d in kern_diffs)),
        ("shaped advance exact",
         all(d == 0 for d in sh_diffs)),
    ]
    all_pass = True
    for name, ok in gates:
        mark = "PASS" if ok else "FAIL"
        all_pass = all_pass and ok
        print(f"  [{mark}] {name}")
    print()
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    font = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf")
    sys.exit(main(font))
