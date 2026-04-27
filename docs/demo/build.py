#!/usr/bin/env python3
"""Build the GitHub Pages demo at ``docs/demo/``.

Differences vs ``samples/visual_test/build.py``:

- All 4 fonts are *subsetted* to the codepoints actually used in the demo
  page plus common Korean/Latin punctuation, so each artifact is tens of
  KB instead of single-digit MB. Total page weight ~200 KB.
- Output container is always WOFF2.
- OFL.txt files for both source families are copied alongside.
- A tiny landing wrapper (`docs/index.html`) links here.

Run:

    python docs/demo/build.py

Then commit ``docs/`` and enable Pages (Settings → Pages → Branch: main,
Folder: /docs).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from polaris_mcfg.extractor import extract_metrics  # noqa: E402
from polaris_mcfg.generator import generate_font  # noqa: E402

# Reuse the visual_test page's HTML / CSS / sample texts.
sys.path.insert(0, str(REPO / "samples" / "visual_test"))
import build as vt  # noqa: E402

NOTO = REPO / "fonts/Noto_Sans_KR/static/NotoSansKR-Regular.ttf"
PRET = REPO / "fonts/Pretendard-1.3.9/public/static/alternative/Pretendard-Regular.ttf"
NOTO_OFL = REPO / "fonts/Noto_Sans_KR/OFL.txt"
PRET_OFL_DIR = REPO / "fonts/Pretendard-1.3.9"

OUT = REPO / "docs" / "demo"
OUT_FONTS = OUT / "fonts"


# ---------- subsetter ----------

#: Unicode ranges to retain in addition to the chars actually used in the demo.
#: We include enough common Korean + Latin codepoints that the page works for
#: light interactive exploration even though it's nominally a fixed demo.
_EXTRA_UNICODES = sorted(set(
    list(range(0x20, 0x7F))                         # ASCII printable
    + list(range(0x00A0, 0x0100))                   # Latin-1 Supplement
    + list(range(0x2010, 0x2070))                   # General punctuation
    + list(range(0x3000, 0x3040))                   # CJK symbols + punctuation
    + list(range(0x3130, 0x3190))                   # Hangul Compat Jamo
    + list(range(0xFF00, 0xFFF0))                   # Halfwidth/fullwidth forms
))


def _demo_chars() -> set[int]:
    """Codepoints referenced anywhere in the visual_test sample text constants."""
    seen: set[int] = set()
    for text in (
        vt._PARAGRAPH_KO,
        vt._PARAGRAPH_EN,
        # Plus the literal strings sprinkled in section builders. We can't
        # introspect those reliably, so include the worst-case Korean/Latin
        # extras here.
        "다람쥐 헌 쳇바퀴에 타고파.",
        "한컴 폰트 메트릭 호환성 (compat) 검증 — 2026.",
        "0123456789  ,.:;!?'\"()[]{}<>+=−×÷",
        "한 글  English  0123",
        "한글 사이 영문 mixed text 입니다",
        "한글 + English + 123 + ,.;:'\"!?",
        "Polaris MCFG: Metric-Compatible Font Generator.",
        "가M8@",
    ):
        for ch in text:
            seen.add(ord(ch))
    for date, n, p in vt._TABLE_NUMBERS:
        for s in (date, n, p):
            for ch in s:
                seen.add(ord(ch))
    return seen


def _subset_to_woff2(src_path: Path, dst_path: Path,
                     unicodes: set[int]) -> int:
    """Subset ``src_path`` to ``unicodes`` and write ``dst_path`` as WOFF2.

    Returns the resulting file size in bytes.
    """
    from fontTools.ttLib import TTFont
    from fontTools.subset import Subsetter, Options

    options = Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.recalc_timestamp = False  # determinism
    options.drop_tables = ["DSIG"]

    font = TTFont(str(src_path))
    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=sorted(unicodes))
    subsetter.subset(font)
    font.flavor = "woff2"
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(dst_path))
    font.close()
    return dst_path.stat().st_size


# ---------- main ----------

def main() -> int:
    if not NOTO.exists() or not PRET.exists():
        print("missing input fonts:", file=sys.stderr)
        for p in (NOTO, PRET):
            print(f"  {'OK' if p.exists() else 'MISSING'}: {p}", file=sys.stderr)
        return 1
    OUT_FONTS.mkdir(parents=True, exist_ok=True)

    chars = _demo_chars() | set(_EXTRA_UNICODES)
    print(f"[1/5] subset universe: {len(chars)} codepoints")

    print("[2/5] extracting source metrics (with kerning + GSUB) ...")
    pret_spec = extract_metrics(PRET, include_kerning=True,
                                 include_gsub=True, deterministic=True)
    noto_spec = extract_metrics(NOTO, include_kerning=True,
                                 include_gsub=True, deterministic=True)

    # Generate at full resolution; subset afterwards.
    tmp = OUT / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    npm_full = tmp / "npm_full.woff2"
    pnm_full = tmp / "pnm_full.woff2"

    print("[3/5] generating Polaris NPM + PNM (full) ...")
    s1 = generate_font(
        pret_spec, NOTO, npm_full,
        apply=("global", "advance", "kerning", "gsub"),
        match_upm=True,
        output_format="woff2",
        family_name="Polaris NPM",
        style_name="Regular",
        license_text="SIL Open Font License 1.1 — derived metrics from Pretendard, "
                     "outline from Noto Sans KR. Distributed under OFL terms.",
        license_url="https://scripts.sil.org/OFL",
    )
    s2 = generate_font(
        noto_spec, PRET, pnm_full,
        apply=("global", "advance", "kerning", "gsub"),
        match_upm=True,
        output_format="woff2",
        family_name="Polaris PNM",
        style_name="Regular",
        license_text="SIL Open Font License 1.1 — derived metrics from Noto Sans KR, "
                     "outline from Pretendard. Distributed under OFL terms.",
        license_url="https://scripts.sil.org/OFL",
    )
    print(f"      Polaris NPM (full): {Path(s1['output']).stat().st_size:,} bytes")
    print(f"      Polaris PNM (full): {Path(s2['output']).stat().st_size:,} bytes")

    print("[4/5] subsetting all 4 fonts to demo chars + common punctuation ...")
    out_files = {
        "00-NotoSansKR-Regular.woff2":   NOTO,
        "01-Pretendard-Regular.woff2":   PRET,
        "02-Polaris-NPM-Regular.woff2":  Path(s1["output"]),
        "03-Polaris-PNM-Regular.woff2":  Path(s2["output"]),
    }
    for name, src in out_files.items():
        dst = OUT_FONTS / name
        size = _subset_to_woff2(src, dst, chars)
        print(f"      {name}: {size:,} bytes")

    # Cleanup tmp
    shutil.rmtree(tmp, ignore_errors=True)

    print("[5/5] copying OFL licenses + writing index.html ...")
    if NOTO_OFL.exists():
        shutil.copy(NOTO_OFL, OUT_FONTS / "OFL-NotoSansKR.txt")
    pret_ofl_candidates = list(PRET_OFL_DIR.glob("**/*OFL*")) + list(PRET_OFL_DIR.glob("**/LICENSE*"))
    for cand in pret_ofl_candidates[:1]:
        shutil.copy(cand, OUT_FONTS / "OFL-Pretendard.txt")
        break

    import time
    cache_buster = str(int(time.time()))
    html = _render_demo_html(cache_buster=cache_buster)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"      -> {OUT / 'index.html'}")

    total = sum(p.stat().st_size for p in OUT_FONTS.glob("*.woff2"))
    print(f"\nTotal font payload: {total/1024:.1f} KB across 4 woff2 files")
    print(f"Output: {OUT}")
    print()
    print("To enable GitHub Pages: Settings → Pages → Branch: main, Folder: /docs")
    return 0


# ---------- HTML ----------

def _render_demo_html(*, cache_buster: str) -> str:
    """Render the demo page using the visual_test sections, but with new
    @font-face URLs and a Pages-friendly intro banner."""
    css = (vt._CSS
           .replace("__CB__", cache_buster)
           .replace("__NPM_EXT__", "woff2")
           .replace("__NPM_FMT__", "woff2")
           .replace("__PNM_EXT__", "woff2")
           .replace("__PNM_FMT__", "woff2"))
    # Override original-font @font-face to point at the WOFF2 files we
    # produced via subsetting (different filenames than visual_test/).
    css = (css
           .replace("00-NotoSansKR-Regular.ttf", "00-NotoSansKR-Regular.woff2")
           .replace("01-Pretendard-Regular.ttf", "01-Pretendard-Regular.woff2")
           .replace("02-Polaris-NotoOutline-PretendardMetrics", "02-Polaris-NPM-Regular")
           .replace("03-Polaris-PretendardOutline-NotoMetrics", "03-Polaris-PNM-Regular")
           .replace("format('truetype')", "format('woff2')"))

    intro = """
<header style="border-bottom: 1px solid #ddd; padding-bottom: 12px; margin-bottom: 24px;">
  <p style="margin: 0; font-size: 12px; color: #888;">
    <a href="../" style="color: inherit;">&larr; polaris_mcfg</a> &middot;
    <a href="https://github.com/Miles-Haeseok-Lee-80/polaris_mcfg" style="color: inherit;">GitHub</a>
  </p>
  <h1 style="margin: 6px 0 4px; font-size: 22px;">Polaris MCFG &mdash; Live demo</h1>
  <p style="margin: 0; color: #555; font-size: 14px;">
    NotoSansKR &amp; Pretendard 두 OFL 폰트로 메트릭 교차 합성한 결과.
    같은 메트릭 그룹의 두 폰트는 외형이 달라도 동일 위치에서 줄바꿈해야 합니다.
    폰트 파일은 데모 텍스트에 맞춰 subset 후 WOFF2로 압축됨 (~50 KB/font).
  </p>
</header>
"""
    legend = vt._LEGEND_HTML
    sec1 = vt._section_single_lines()
    sec2 = vt._section_line_break_pairs()
    sec_lang = vt._section_lang_effect()
    sec3 = vt._section_size_ladder()
    sec4 = vt._section_table_numbers()
    sec5 = vt._section_paragraph_4col()
    sec6 = vt._section_glyph_grid()
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polaris MCFG — Live demo</title>
<style>{css}</style>
</head>
<body>
{intro}
{legend}

{sec1}
{sec2}
{sec_lang}
{sec3}
{sec4}
{sec5}
{sec6}

<footer style="margin-top: 48px; border-top: 1px solid #ddd; padding-top: 12px; font-size: 12px; color: #888;">
  <p>
    <strong>License:</strong> Polaris NPM &amp; Polaris PNM are derivative works
    of NotoSansKR / Pretendard, distributed under the
    <a href="https://scripts.sil.org/OFL">SIL Open Font License 1.1</a>
    with new family names per OFL Reserved Font Name policy.
    See <a href="fonts/OFL-NotoSansKR.txt">OFL-NotoSansKR.txt</a> /
    <a href="fonts/OFL-Pretendard.txt">OFL-Pretendard.txt</a> for the original copyrights.
  </p>
</footer>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
