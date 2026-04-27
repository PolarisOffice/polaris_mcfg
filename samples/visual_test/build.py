#!/usr/bin/env python3
"""Build a 4-font visual test page.

Takes the two locally-available font families (NotoSansKR Regular,
Pretendard Regular) and produces:

  out/fonts/00-NotoSansKR-Regular.ttf    (original)
  out/fonts/01-Pretendard-Regular.ttf    (original)
  out/fonts/02-Polaris-NotoOutline-PretendardMetrics.ttf
  out/fonts/03-Polaris-PretendardOutline-NotoMetrics.ttf
  out/index.html                         (visual test page)

Run from the project root:

    python samples/visual_test/build.py

Then serve locally (browsers block @font-face from file://):

    cd samples/visual_test/out && python3 -m http.server 8000
    open http://localhost:8000/

The visual hypothesis:

  - "NotoSansKR Regular" and "Polaris (Pretendard outline + Noto metrics)"
    share Noto's metrics, so they should wrap at the same positions.
  - "Pretendard Regular" and "Polaris (Noto outline + Pretendard metrics)"
    share Pretendard's metrics, so they should wrap at the same positions.

  Visually different glyph designs, identical line breaks. That is the
  Polaris MCFG guarantee, made visible.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from polaris_mcfg.extractor import extract_metrics  # noqa: E402
from polaris_mcfg.generator import generate_font  # noqa: E402

NOTO = REPO / "fonts/Noto_Sans_KR/static/NotoSansKR-Regular.ttf"
PRET = REPO / "fonts/Pretendard-1.3.9/public/static/alternative/Pretendard-Regular.ttf"

OUT = Path(__file__).resolve().parent / "out"
OUT_FONTS = OUT / "fonts"


def main() -> int:
    if not NOTO.exists() or not PRET.exists():
        print("missing input fonts:", file=sys.stderr)
        for p in (NOTO, PRET):
            print(f"  {'OK' if p.exists() else 'MISSING'}: {p}", file=sys.stderr)
        return 1

    OUT_FONTS.mkdir(parents=True, exist_ok=True)

    noto_out = OUT_FONTS / "00-NotoSansKR-Regular.ttf"
    pret_out = OUT_FONTS / "01-Pretendard-Regular.ttf"
    polaris_npm = OUT_FONTS / "02-Polaris-NotoOutline-PretendardMetrics.ttf"
    polaris_pnm = OUT_FONTS / "03-Polaris-PretendardOutline-NotoMetrics.ttf"

    print("[1/4] copying originals ...")
    shutil.copy(NOTO, noto_out)
    shutil.copy(PRET, pret_out)

    print("[2/4] extracting metrics ...")
    noto_spec = extract_metrics(NOTO, deterministic=True)
    pret_spec = extract_metrics(PRET, deterministic=True)
    print(f"      Noto:       {len(noto_spec.glyphs):>6} glyphs, "
          f"upm={noto_spec.global_metrics.unitsPerEm}, "
          f"ascent={noto_spec.global_metrics.hhea['ascent']}, "
          f"descent={noto_spec.global_metrics.hhea['descent']}")
    print(f"      Pretendard: {len(pret_spec.glyphs):>6} glyphs, "
          f"upm={pret_spec.global_metrics.unitsPerEm}, "
          f"ascent={pret_spec.global_metrics.hhea['ascent']}, "
          f"descent={pret_spec.global_metrics.hhea['descent']}")

    print("[3/4] generating cross-pollinated fonts ...")
    # Re-extract source metrics with all the features that the generator
    # will apply: kerning (P0/A1) and shape-induced advance overrides
    # (v2/A3). include_gsub probes shaping under common (script, lang)
    # combinations and is slower than the other extractors.
    print("      (also extracting GPOS kern + GSUB shape overrides — slower)")
    pret_spec_full = extract_metrics(PRET, include_kerning=True,
                                      include_gsub=True, deterministic=True)
    noto_spec_full = extract_metrics(NOTO, include_kerning=True,
                                      include_gsub=True, deterministic=True)

    # match_upm=True rescales the design font to the source's UPM before
    # applying metrics — required for byte-perfect advance widths and so
    # line-break positions match exactly across the metric pair.
    # output_format="auto" picks WOFF2 when --match-upm rescaled the font
    # (Chromium TTF sanitizer rejects scale_upem'd CJK TTFs).
    # apply=gsub injects locl substitutions so lang="ko" rendering also
    # matches the source font's shaped widths.
    s1 = generate_font(
        pret_spec_full, NOTO, polaris_npm,
        apply=("global", "advance", "kerning", "gsub"),
        match_upm=True,
        output_format="auto",
        family_name="Polaris NPM",  # Noto outline, Pretendard Metrics
        style_name="Regular",
        license_text="SIL Open Font License 1.1 (see source font)",
    )
    s2 = generate_font(
        noto_spec_full, PRET, polaris_pnm,
        apply=("global", "advance", "kerning", "gsub"),
        match_upm=True,
        output_format="auto",
        family_name="Polaris PNM",  # Pretendard outline, Noto Metrics
        style_name="Regular",
        license_text="SIL Open Font License 1.1 (see source font)",
    )
    print(f"      -> {polaris_npm.name}: applied={s1['advance']['applied']}, "
          f"missing={s1['advance']['missing']}, "
          f"format={s1.get('outputFormat', 'ttf')}, "
          f"gsub={s1.get('gsub', {}).get('applied', 0)}")
    print(f"      -> {polaris_pnm.name}: applied={s2['advance']['applied']}, "
          f"missing={s2['advance']['missing']}, "
          f"format={s2.get('outputFormat', 'ttf')}, "
          f"gsub={s2.get('gsub', {}).get('applied', 0)}")

    print("[4/4] writing index.html ...")
    import time
    cache_buster = str(int(time.time()))
    # The actual files emitted by generate_font (their suffix may be .woff2
    # if --match-upm rescaled the design font). Use the stats output_format
    # to pick the right URL in the @font-face.
    npm_format = s1.get("outputFormat", "ttf")
    pnm_format = s2.get("outputFormat", "ttf")
    (OUT / "index.html").write_text(
        _render_html(cache_buster=cache_buster,
                     npm_format=npm_format, pnm_format=pnm_format),
        encoding="utf-8",
    )
    print(f"      -> {OUT / 'index.html'}  (cache-buster={cache_buster})")
    print(f"      formats: NPM={npm_format}, PNM={pnm_format}")

    print()
    print("Done. To view:")
    print(f"  cd {OUT.relative_to(REPO)}")
    print(f"  python3 -m http.server 8000")
    print(f"  open http://localhost:8000/")
    return 0


# ---------- HTML template ----------

_PARAGRAPH_KO = (
    "재배포가 제한된 폰트(상용·사내·한컴 폰트류 등)를 사용하는데, 문제는 폰트별로 "
    "다른 메트릭 때문에 동일한 렌더링을 기대할 수가 없다. Polaris MCFG는 소스 "
    "폰트로부터 레이아웃에 영향을 미치는 메트릭을 추출하고, 재라이센스 가능한 "
    "폰트의 디자인에 이를 결합하여 새로운 폰트를 만든다. 외형은 자유 폰트의 "
    "디자인을 따르되, 줄바꿈 위치와 페이지 분할은 원본 소스 폰트와 호환된다. "
    "다람쥐 헌 쳇바퀴에 타고파. The quick brown fox jumps over the lazy dog. 0123456789."
)

_PARAGRAPH_EN = (
    "Polaris MCFG is a metric-compatible font generator. It extracts the "
    "layout-affecting metrics (advance widths, ascender/descender, line gap) "
    "from a source font, and applies them to the glyph design of a freely "
    "licensed font. The result preserves line breaks and page layout while "
    "swapping the visual identity. The quick brown fox jumps over the lazy dog "
    "1234567890 — Hangul + English mixed: 한국어 + English."
)

_TABLE_NUMBERS = [
    ("2026-04-01", "1,234,567", "+12.3%"),
    ("2026-04-02", "987,654",   "-3.45%"),
    ("2026-04-03", "1,000,000", "+0.05%"),
    ("2026-04-04", "42",        "0.00%"),
    ("2026-04-05", "777,777",   "+88.8%"),
]


def _render_html(*, cache_buster: str = "0",
                 npm_format: str = "ttf", pnm_format: str = "ttf") -> str:
    npm_ext = "woff2" if npm_format == "woff2" else "ttf"
    pnm_ext = "woff2" if pnm_format == "woff2" else "ttf"
    css = (_CSS
           .replace("__CB__", cache_buster)
           .replace("__NPM_EXT__", npm_ext)
           .replace("__NPM_FMT__", "woff2" if npm_ext == "woff2" else "truetype")
           .replace("__PNM_EXT__", pnm_ext)
           .replace("__PNM_FMT__", "woff2" if pnm_ext == "woff2" else "truetype"))
    legend = _LEGEND_HTML
    sec1 = _section_single_lines()
    sec2 = _section_line_break_pairs()
    sec_lang = _section_lang_effect()
    sec3 = _section_size_ladder()
    sec4 = _section_table_numbers()
    sec5 = _section_paragraph_4col()
    sec6 = _section_glyph_grid()
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Polaris MCFG — visual test page</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>Polaris MCFG <span class="muted">— visual test page</span></h1>
  <p class="lead">
    원본 폰트 2종(NotoSansKR Regular, Pretendard Regular)과 그것을 교차 합성한
    Polaris 폰트 2종, 총 4개 폰트로 구성된 시각 비교 페이지.
  </p>
  <p class="hypothesis">
    <strong>가설</strong>: 같은 메트릭을 공유하는 두 폰트는 외형이 달라도
    <em>같은 위치에서 줄바꿈</em>해야 한다 — Polaris MCFG의 핵심 보장.
  </p>
  {legend}
</header>

{sec1}
{sec2}
{sec_lang}
{sec3}
{sec4}
{sec5}
{sec6}

<footer>
  <p class="muted">
    각 폰트는 <code>@font-face</code>로 직접 로드됩니다.
    브라우저가 file:// 경로의 폰트를 차단할 수 있으므로 로컬 HTTP 서버로 열람 권장:<br>
    <code>cd samples/visual_test/out &amp;&amp; python3 -m http.server 8000</code>
  </p>
</footer>
</body>
</html>
"""


_CSS = """
:root {
  /* group A — Noto metrics: original Noto + Polaris (Pretendard outline + Noto metrics) */
  --metric-a:        #2c4ec9;
  --metric-a-soft:   #e8edfa;
  /* group B — Pretendard metrics: original Pretendard + Polaris (Noto outline + Pretendard metrics) */
  --metric-b:        #c0392b;
  --metric-b-soft:   #fbeae8;

  --bg: #fafafa;
  --fg: #222;
  --muted: #888;
  --border: #ddd;
}

@font-face {
  font-family: 'OrigNoto';
  src: url('fonts/00-NotoSansKR-Regular.ttf?cb=__CB__') format('truetype');
  font-display: block;
}
@font-face {
  font-family: 'OrigPretendard';
  src: url('fonts/01-Pretendard-Regular.ttf?cb=__CB__') format('truetype');
  font-display: block;
}
@font-face {
  font-family: 'PolarisNPM';
  src: url('fonts/02-Polaris-NotoOutline-PretendardMetrics.__NPM_EXT__?cb=__CB__') format('__NPM_FMT__');
  font-display: block;
}
@font-face {
  font-family: 'PolarisPNM';
  src: url('fonts/03-Polaris-PretendardOutline-NotoMetrics.__PNM_EXT__?cb=__CB__') format('__PNM_FMT__');
  font-display: block;
}

/* The four font classes are tagged by which METRICS they carry, since that
   is what determines layout. Color groups visualize the pairing. */
.f-noto       { font-family: 'OrigNoto', sans-serif;       border-left-color: var(--metric-a); }
.f-pnm        { font-family: 'PolarisPNM', sans-serif;     border-left-color: var(--metric-a); }
.f-pretendard { font-family: 'OrigPretendard', sans-serif; border-left-color: var(--metric-b); }
.f-npm        { font-family: 'PolarisNPM', sans-serif;     border-left-color: var(--metric-b); }

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg); }
body {
  font: 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 36px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
h3 { font-size: 12px; margin: 12px 0 6px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
p  { margin: 6px 0; line-height: 1.5; }
.muted { color: var(--muted); }
.lead { font-size: 14px; }
.hypothesis { background: #fffbe6; padding: 8px 12px; border-left: 3px solid #f5b400; }
code { font: 12px Menlo, Monaco, monospace; background: #f0f0f0; padding: 1px 5px; border-radius: 3px; }

.legend { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.legend-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--border); border-left-width: 4px; background: #fff; }
.legend-item .swatch { width: 10px; height: 10px; border-radius: 50%; }
.legend-item .name { font-weight: 600; }
.legend-item .desc { color: var(--muted); font-size: 12px; }
.metric-a-bg { background: var(--metric-a-soft); }
.metric-b-bg { background: var(--metric-b-soft); }

/* sample blocks all get a colored left border indicating their METRICS group */
.sample {
  border-left: 4px solid #ccc;
  padding: 6px 12px;
  background: #fff;
  margin: 4px 0;
}
.sample .label {
  display: inline-block;
  font: 11px Menlo, Monaco, monospace;
  color: var(--muted);
  margin-right: 8px;
  min-width: 220px;
}

/* line-break test: two columns side-by-side, fixed width */
.linebreak-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 8px;
}
.linebreak-grid .col {
  border: 1px solid var(--border);
  border-top: 4px solid;
  padding: 12px;
  background: #fff;
}
.linebreak-grid .col h3 { margin-top: 0; color: inherit; }
.linebreak-grid .col p {
  font-size: 15px;
  /* The fixed-width container is what makes the wrap test meaningful. */
  max-width: 26em;
  margin: 8px 0 0;
}
.metric-a .col { border-top-color: var(--metric-a); }
.metric-a h3 { color: var(--metric-a); }
.metric-b .col { border-top-color: var(--metric-b); }
.metric-b h3 { color: var(--metric-b); }
.note { font-size: 12px; color: var(--muted); margin-top: 6px; }

/* size ladder */
.size-ladder { background: #fff; border: 1px solid var(--border); padding: 12px; }
.size-ladder p { margin: 4px 0; }
.size-ladder .row { display: grid; grid-template-columns: 60px 1fr 1fr 1fr 1fr; gap: 12px; align-items: center; padding: 4px 0; border-bottom: 1px solid #f0f0f0; }
.size-ladder .row:last-child { border-bottom: 0; }
.size-ladder .px { color: var(--muted); font: 11px Menlo, monospace; }

/* 4-column paragraph */
.four-col { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px; }
.four-col .col { border-top: 4px solid; padding: 10px; background: #fff; }
.four-col .col h3 { margin-top: 0; color: inherit; }
.four-col .col p { font-size: 13px; }

/* tabular numbers */
table.numbers { width: 100%; border-collapse: collapse; font-size: 14px; background: #fff; }
table.numbers th, table.numbers td { padding: 6px 10px; border-bottom: 1px solid var(--border); text-align: right; }
table.numbers th { background: #f5f5f5; }
table.numbers td:first-child, table.numbers th:first-child { text-align: left; }

/* glyph showcase */
.glyph-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.glyph-grid .cell { border-top: 4px solid; padding: 14px; background: #fff; text-align: center; }
.glyph-grid .cell .big { font-size: 56px; line-height: 1; margin: 8px 0; }
.glyph-grid .cell .small { font-size: 11px; color: var(--muted); }
"""


_LEGEND_HTML = """
<div class="legend">
  <div class="legend-item metric-a-bg" style="border-left-color: var(--metric-a);">
    <span class="swatch" style="background: var(--metric-a);"></span>
    <div>
      <div class="name f-noto">NotoSansKR Regular (원본)</div>
      <div class="desc">Noto outline + Noto metrics</div>
    </div>
  </div>
  <div class="legend-item metric-a-bg" style="border-left-color: var(--metric-a);">
    <span class="swatch" style="background: var(--metric-a);"></span>
    <div>
      <div class="name f-pnm">Polaris PNM (합성)</div>
      <div class="desc">Pretendard outline + <strong>Noto metrics</strong></div>
    </div>
  </div>
  <div class="legend-item metric-b-bg" style="border-left-color: var(--metric-b);">
    <span class="swatch" style="background: var(--metric-b);"></span>
    <div>
      <div class="name f-pretendard">Pretendard Regular (원본)</div>
      <div class="desc">Pretendard outline + Pretendard metrics</div>
    </div>
  </div>
  <div class="legend-item metric-b-bg" style="border-left-color: var(--metric-b);">
    <span class="swatch" style="background: var(--metric-b);"></span>
    <div>
      <div class="name f-npm">Polaris NPM (합성)</div>
      <div class="desc">Noto outline + <strong>Pretendard metrics</strong></div>
    </div>
  </div>
</div>
"""


def _section_single_lines() -> str:
    samples = [
        ("Hangul pangram", "다람쥐 헌 쳇바퀴에 타고파."),
        ("English pangram", "The quick brown fox jumps over the lazy dog."),
        ("Mixed script", "소스 폰트 메트릭 호환성 (compat) 검증 — 2026."),
        ("Numerals + punct", "0123456789  ,.:;!?'\"()[]{}<>+=−×÷"),
    ]
    rows = []
    for label, text in samples:
        rows.append(f'<h3>{label}</h3>')
        for cls, who in (
            ("f-noto",       "Noto (orig)"),
            ("f-pnm",        "Polaris PNM"),
            ("f-pretendard", "Pretendard (orig)"),
            ("f-npm",        "Polaris NPM"),
        ):
            rows.append(
                f'<div class="sample {cls}"><span class="label">{who}</span>{text}</div>'
            )
    body = "\n".join(rows)
    return f"""
<section>
  <h2>1. 같은 텍스트, 4 폰트</h2>
  <p class="muted">동일한 한 줄 텍스트가 폰트별로 어떻게 보이는지. 색상은
    <strong>메트릭 그룹</strong>을 의미합니다 (외형 그룹이 아님).</p>
  {body}
</section>
"""


def _section_line_break_pairs() -> str:
    p = _PARAGRAPH_KO
    return f"""
<section>
  <h2>2. 라인브레이크 비교 (핵심)</h2>
  <p>같은 너비 컨테이너에 같은 텍스트. <strong>같은 메트릭 그룹의 두 폰트는
    동일한 위치에서 줄바꿈</strong>해야 합니다 — 외형이 달라도.</p>
  <p class="note">
    Group A (Noto 메트릭): Pretendard 외형을 Noto의 UPM(1000)으로
    rescale → Noto 메트릭 적용 + GPOS 커닝 + GSUB locl 치환 이식.<br>
    Group B (Pretendard 메트릭): Noto 외형을 Pretendard UPM(2048)으로
    rescale → Pretendard 메트릭/커닝 적용. (rescale 결과가 Chromium TTF
    sanitizer와 호환 안 되어 자동으로 WOFF2 컨테이너로 출력.)<br>
    아래 컬럼은 모두 <code>lang="ko"</code>로 렌더링됩니다.
  </p>

  <h3 style="margin-top: 18px;">Group A — Noto metrics</h3>
  <div class="linebreak-grid metric-a">
    <div class="col">
      <h3>NotoSansKR (원본)</h3>
      <p class="f-noto" lang="ko">{p}</p>
    </div>
    <div class="col">
      <h3>Polaris PNM <span class="muted">(Pretendard outline + Noto metrics)</span></h3>
      <p class="f-pnm" lang="ko">{p}</p>
    </div>
  </div>
  <p class="note">↑ 두 컬럼의 줄바꿈 위치가 같아야 정상. 글자의 굵기/형태는 달라도 됨.</p>

  <h3 style="margin-top: 24px;">Group B — Pretendard metrics</h3>
  <div class="linebreak-grid metric-b">
    <div class="col">
      <h3>Pretendard (원본)</h3>
      <p class="f-pretendard" lang="ko">{p}</p>
    </div>
    <div class="col">
      <h3>Polaris NPM <span class="muted">(Noto outline + Pretendard metrics)</span></h3>
      <p class="f-npm" lang="ko">{p}</p>
    </div>
  </div>
  <p class="note">↑ 마찬가지로, 두 컬럼의 줄바꿈 위치가 같아야 정상.</p>
</section>
"""


def _section_lang_effect() -> str:
    """Show how lang attribute changes shaping for fonts with Korean GSUB."""
    short = "한글 사이 영문 mixed text 입니다"
    return f"""
<section>
  <h2>3. <code>lang</code>이 라인브레이크에 미치는 영향 (스크립트별 GSUB)</h2>
  <p>한국어 폰트는 종종 GSUB lookup으로 한국어 스크립트(<code>script=hang</code>) 컨텍스트에서
    공백/구두점을 더 넓은 변형으로 치환합니다. 브라우저가 <code>lang="ko"</code>를
    감지하면 이 치환이 활성화되어 폰트가 같은 메트릭이라도 라인 너비가 달라집니다.
    Polaris MCFG는 메트릭(<code>hmtx</code>, <code>OS/2</code>, <code>head</code> 등)만 이식하며
    GSUB은 디자인 폰트의 것을 그대로 사용합니다 — 따라서 lang에 따른 치환은
    원본 폰트와 합성 폰트가 다르게 동작합니다.
  </p>

  <h3 style="margin-top: 18px;">같은 텍스트, 같은 폰트, lang만 다름</h3>
  <table class="numbers" style="font-size: 14px;">
    <thead>
      <tr><th>Font</th><th>lang="en"</th><th>lang="ko"</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>NotoSansKR (원본)</td>
        <td><span class="f-noto" lang="en">{short}</span></td>
        <td><span class="f-noto" lang="ko">{short}</span></td>
      </tr>
      <tr>
        <td>Polaris PNM</td>
        <td><span class="f-pnm" lang="en">{short}</span></td>
        <td><span class="f-pnm" lang="ko">{short}</span></td>
      </tr>
      <tr>
        <td>Pretendard (원본)</td>
        <td><span class="f-pretendard" lang="en">{short}</span></td>
        <td><span class="f-pretendard" lang="ko">{short}</span></td>
      </tr>
      <tr>
        <td>Polaris NPM</td>
        <td><span class="f-npm" lang="en">{short}</span></td>
        <td><span class="f-npm" lang="ko">{short}</span></td>
      </tr>
    </tbody>
  </table>
  <p class="note">
    Noto는 <code>lang="ko"</code>일 때 공백 advance를 약 25% 늘리는 GSUB lookup을 가집니다
    (한글-라틴 사이 시각적 균형). Pretendard는 이 lookup이 없습니다.<br>
    이 GSUB 차이는 메트릭 추출/적용 범위 밖입니다 — 글리프 substitution 데이터를
    이식하려면 outline 데이터 권한(라이센스)이 필요해 의도적으로 제외했습니다.
  </p>
</section>
"""


def _section_size_ladder() -> str:
    text = "한 글  English  0123"
    sizes = [10, 12, 14, 18, 24, 32, 48]
    rows = ['<h3>NotoSansKR (orig) | Polaris PNM | Pretendard (orig) | Polaris NPM</h3>']
    rows.append('<div class="size-ladder">')
    for px in sizes:
        rows.append(
            f'<div class="row" style="font-size: {px}px;">'
            f'<span class="px">{px}px</span>'
            f'<span class="f-noto">{text}</span>'
            f'<span class="f-pnm">{text}</span>'
            f'<span class="f-pretendard">{text}</span>'
            f'<span class="f-npm">{text}</span>'
            '</div>'
        )
    rows.append('</div>')
    return f"""
<section>
  <h2>4. 사이즈 사다리 (10 → 48px)</h2>
  <p class="muted">동일 텍스트를 사이즈별로 나란히. 좌우 너비 차이가 메트릭 차이.</p>
  {''.join(rows)}
</section>
"""


def _section_table_numbers() -> str:
    body_rows = []
    for date, n, p in _TABLE_NUMBERS:
        body_rows.append(
            f'<tr><td>{date}</td>'
            f'<td class="f-noto">{n}</td>'
            f'<td class="f-pnm">{n}</td>'
            f'<td class="f-pretendard">{n}</td>'
            f'<td class="f-npm">{n}</td>'
            f'<td class="f-noto">{p}</td></tr>'
        )
    return f"""
<section>
  <h2>5. 표 / 숫자 정렬</h2>
  <p class="muted">컬럼 너비가 메트릭에 따라 달라지는지 — 합성된 폰트는 원본 메트릭과 동일한 컬럼 너비를 가져야 합니다.</p>
  <table class="numbers">
    <thead>
      <tr>
        <th>Date</th>
        <th>Noto orig</th>
        <th>Polaris PNM</th>
        <th>Pretendard orig</th>
        <th>Polaris NPM</th>
        <th>%</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</section>
"""


def _section_paragraph_4col() -> str:
    p_ko = _PARAGRAPH_KO
    return f"""
<section>
  <h2>6. 문단 4분할 비교</h2>
  <p class="muted">동일 너비, 동일 폰트 사이즈. 메트릭 그룹별로 줄바꿈이 일치해야 합니다.</p>
  <div class="four-col">
    <div class="col" style="border-top-color: var(--metric-a);">
      <h3 style="color: var(--metric-a);">Noto (orig)</h3>
      <p class="f-noto">{p_ko}</p>
    </div>
    <div class="col" style="border-top-color: var(--metric-a);">
      <h3 style="color: var(--metric-a);">Polaris PNM</h3>
      <p class="f-pnm">{p_ko}</p>
    </div>
    <div class="col" style="border-top-color: var(--metric-b);">
      <h3 style="color: var(--metric-b);">Pretendard (orig)</h3>
      <p class="f-pretendard">{p_ko}</p>
    </div>
    <div class="col" style="border-top-color: var(--metric-b);">
      <h3 style="color: var(--metric-b);">Polaris NPM</h3>
      <p class="f-npm">{p_ko}</p>
    </div>
  </div>
</section>
"""


def _section_glyph_grid() -> str:
    samples = ["가", "M", "8", "@"]
    cells = []
    for ch in samples:
        cells.append(f"""
<div class="glyph-grid">
  <div class="cell" style="border-top-color: var(--metric-a);">
    <div class="small">Noto (orig)</div>
    <div class="big f-noto">{ch}</div>
  </div>
  <div class="cell" style="border-top-color: var(--metric-a);">
    <div class="small">Polaris PNM</div>
    <div class="big f-pnm">{ch}</div>
  </div>
  <div class="cell" style="border-top-color: var(--metric-b);">
    <div class="small">Pretendard (orig)</div>
    <div class="big f-pretendard">{ch}</div>
  </div>
  <div class="cell" style="border-top-color: var(--metric-b);">
    <div class="small">Polaris NPM</div>
    <div class="big f-npm">{ch}</div>
  </div>
</div>
""")
    return f"""
<section>
  <h2>7. 글리프 클로즈업</h2>
  <p class="muted">큰 사이즈에서 외형 차이를 직접 확인. 같은 그룹(같은 색)은 advance 폭이
    동일하고, 다른 그룹은 advance가 다릅니다 — 셀의 너비를 보세요.</p>
  {''.join(cells)}
</section>
"""


if __name__ == "__main__":
    raise SystemExit(main())
