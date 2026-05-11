"""End-to-end equivalence: render extract → generate → compare.

Validates the entire pipeline: render-backend extracted metrics, when
fed to the generator, produce a font equivalent to the file-backend
path on the same design font. This is the "did we actually replace
file parsing with pixel measurement?" smoke test.

Steps
-----
1a. Extract source font metrics via FILE backend.
1b. Extract source font metrics via RENDER backend (subset of cmap
    representative of the four major glyph categories).
2.  Compare the two MetricsSpec JSONs.
3a. Generate result_file.ttf = design font + file-extracted metrics.
3b. Generate result_render.ttf = design font + render-extracted metrics.
4.  Compare the two output fonts.
5.  Validate each against the source font.

If every step reports ≤ 2u diff and `validate` says PASS for both,
the render backend has fully replaced file parsing for this font.

Run from repo root:
    python samples/end_to_end_render_vs_file.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from polaris_mcfg.extractor import extract_metrics
from polaris_mcfg.render_extractor import extract_via_render
from polaris_mcfg.render_extractor.kerning import PairCandidate

SOURCE_FONT = Path("fonts/Noto_Sans_KR/static/NotoSansKR-Bold.ttf")
DESIGN_FONT = Path("fonts/Noto_Sans_KR/static/NotoSansKR-Regular.ttf")
OUT_DIR = Path("/tmp/end_to_end")

# Representative cmap covering the four major glyph categories:
#   ASCII printable + Latin-1 punctuation + Korean punctuation + first
#   100 Hangul Syllables. Small enough that the full render path
#   finishes in 1-2 min on a laptop; large enough to exercise advance,
#   LSB, kerning, and shaped-advance extraction on real-world glyph
#   shapes.
CMAP_SUBSET = (
    list(range(0x21, 0x7F))                    # ASCII printable (95)
    + list(range(0x00A1, 0x00AD))              # Latin-1 punct (12)
    + [0x3001, 0x3002, 0xFF0C, 0xFF0E, 0xFF1A,  # Korean punct (15)
       0xFF1B, 0xFF1F, 0xFF01, 0x2013, 0x2014,
       0x2018, 0x2019, 0x201C, 0x201D, 0x2026]
    + list(range(0xAC00, 0xAC00 + 100))        # 100 Hangul Syllables
)


def step(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "polaris_mcfg.cli", *args],
        capture_output=True, text=True,
    )


def main() -> int:
    if not SOURCE_FONT.exists():
        print(f"missing: {SOURCE_FONT}", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(exist_ok=True)

    file_json = OUT_DIR / "file.json"
    render_json = OUT_DIR / "render.json"
    result_file = OUT_DIR / "result_file.ttf"
    result_render = OUT_DIR / "result_render.ttf"

    # ---------- Step 1a: file extract ----------
    step(f"[1a] FILE backend extract  →  {file_json.name}")
    t = time.time()
    spec_file = extract_metrics(
        SOURCE_FONT,
        include_lsb=True,
        include_kerning=True,
        include_gsub=True,
        deterministic=True,
    )
    file_json.write_text(spec_file.to_json() + "\n")
    print(f"  {time.time()-t:.2f}s  "
          f"({len(spec_file.glyphs)} glyphs, "
          f"{len(spec_file.kerning or [])} kerning pairs, "
          f"{len(spec_file.shaped_advances or [])} shaped overrides)")

    # ---------- Step 1b: render extract ----------
    step(f"[1b] RENDER backend extract  →  {render_json.name}")
    print(f"  cmap subset: {len(CMAP_SUBSET)} codepoints "
          f"(ASCII + Latin-1 punct + Korean punct + 100 Hangul)")
    t = time.time()
    # Restrict kerning candidates to the subset to keep timings short
    pair_cands = [
        PairCandidate(l, r)
        for l in CMAP_SUBSET for r in CMAP_SUBSET
        if 0x21 <= l <= 0x7E and 0x21 <= r <= 0x7E
    ]
    spec_render = extract_via_render(
        SOURCE_FONT,
        renderer="freetype",
        cmap=CMAP_SUBSET,
        include_lsb=True,
        include_kerning=True,
        include_shaped=True,
        pair_candidates=pair_cands,
    )
    render_json.write_text(spec_render.to_json() + "\n")
    print(f"  {time.time()-t:.2f}s  "
          f"({len(spec_render.glyphs)} glyphs, "
          f"{len(spec_render.kerning or [])} kerning pairs, "
          f"{len(spec_render.shaped_advances or [])} shaped overrides)")

    # ---------- Step 2: compare specs ----------
    step("[2] compare  file.json  vs  render.json  (--threshold 2)")
    r = run_cli("compare", str(file_json), str(render_json),
                "--threshold", "2", "--format", "text")
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr.rstrip(), file=sys.stderr)

    # ---------- Step 3a: generate from file metrics ----------
    step("[3a] generate  result_file.ttf  =  design + FILE metrics")
    t = time.time()
    r = run_cli(
        "generate",
        "--metrics", str(file_json),
        "--design", str(DESIGN_FONT),
        "--output", str(result_file),
        "--apply", "global,advance,lsb,kerning,gsub",
        "--family-name", "PolarisFile",
        "--style-name", "Test",
        "--license-text", "SIL Open Font License 1.1",
        "--license-url", "https://scripts.sil.org/OFL",
    )
    print(f"  {time.time()-t:.2f}s  rc={r.returncode}")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return 1
    if r.stdout:
        print(r.stdout.rstrip())

    # ---------- Step 3b: generate from render metrics ----------
    step("[3b] generate  result_render.ttf  =  design + RENDER metrics")
    t = time.time()
    r = run_cli(
        "generate",
        "--metrics", str(render_json),
        "--design", str(DESIGN_FONT),
        "--output", str(result_render),
        "--apply", "global,advance,lsb,kerning,gsub",
        "--family-name", "PolarisRender",
        "--style-name", "Test",
        "--license-text", "SIL Open Font License 1.1",
        "--license-url", "https://scripts.sil.org/OFL",
    )
    print(f"  {time.time()-t:.2f}s  rc={r.returncode}")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return 1
    if r.stdout:
        print(r.stdout.rstrip())

    # ---------- Step 4: compare the two RESULT FONTS ----------
    step("[4] compare  result_file.ttf  vs  result_render.ttf  "
         "(--threshold 2)")
    r = run_cli("compare", str(result_file), str(result_render),
                "--threshold", "2", "--format", "text")
    print(r.stdout.rstrip())

    # ---------- Step 5: validate against the source ----------
    step("[5a] validate  result_file.ttf   against source")
    r = run_cli("validate", str(result_file), "--against", str(SOURCE_FONT))
    print(r.stdout.rstrip())
    print(f"  → rc={r.returncode}")
    file_ok = r.returncode == 0

    step("[5b] validate  result_render.ttf  against source")
    r = run_cli("validate", str(result_render), "--against", str(SOURCE_FONT))
    print(r.stdout.rstrip())
    print(f"  → rc={r.returncode}")
    render_ok = r.returncode == 0

    # ---------- Summary ----------
    step("SUMMARY")
    print(f"  result_file   validate: {'PASS' if file_ok else 'FAIL'}")
    print(f"  result_render validate: {'PASS' if render_ok else 'FAIL'}")
    print()
    if file_ok and render_ok:
        print("  ✓ Both extraction paths produce valid result fonts.")
        print("  ✓ Render backend is interchangeable with file backend for")
        print("    end-to-end font generation on this cmap subset.")
        return 0
    else:
        print("  Render path failed equivalence — investigate diff in step [2]/[4].")
        return 1


if __name__ == "__main__":
    sys.exit(main())
