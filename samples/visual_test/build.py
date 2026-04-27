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
    s1 = generate_font(
        pret_spec, NOTO, polaris_npm,
        apply=("global", "advance"),
        family_name="Polaris NPM",  # Noto outline, Pretendard Metrics
        style_name="Regular",
        license_text="SIL Open Font License 1.1 (see source font)",
    )
    s2 = generate_font(
        noto_spec, PRET, polaris_pnm,
        apply=("global", "advance"),
        family_name="Polaris PNM",  # Pretendard outline, Noto Metrics
        style_name="Regular",
        license_text="SIL Open Font License 1.1 (see source font)",
    )
    print(f"      -> {polaris_npm.name}: applied={s1['advance']['applied']}, "
          f"missing={s1['advance']['missing']}")
    print(f"      -> {polaris_pnm.name}: applied={s2['advance']['applied']}, "
          f"missing={s2['advance']['missing']}")

    print("[4/4] writing index.html ...")
    (OUT / "index.html").write_text(_render_html(), encoding="utf-8")
    print(f"      -> {OUT / 'index.html'}")

    print()
    print("Done. To view:")
    print(f"  cd {OUT.relative_to(REPO)}")
    print(f"  python3 -m http.server 8000")
    print(f"  open http://localhost:8000/")
    return 0


# ---------- HTML template ----------

_PARAGRAPH_KO = (
    "한컴이 저작권 있는 폰트를 사용하는데, 문제는 폰트별로 다른 메트릭 때문에 "
    "동일한 렌더링을 기대할 수가 없다. Polaris MCFG는 한컴 폰트로부터 레이아웃에 "
    "영향을 미치는 메트릭을 추출하고, 재라이센스 가능한 폰트의 디자인에 이를 "
    "결합하여 새로운 폰트를 만든다. 외형은 자유 폰트의 디자인을 따르되, "
    "줄바꿈 위치와 페이지 분할은 원본 한컴 폰트와 호환된다. "
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


def _render_html() -> str:
    css = _CSS
    legend = _LEGEND_HTML
    sec1 = _section_single_lines()
    sec2 = _section_line_break_pairs()
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
  src: url('fonts/00-NotoSansKR-Regular.ttf') format('truetype');
  font-display: block;
}
@font-face {
  font-family: 'OrigPretendard';
  src: url('fonts/01-Pretendard-Regular.ttf') format('truetype');
  font-display: block;
}
@font-face {
  font-family: 'PolarisNPM';
  src: url('fonts/02-Polaris-NotoOutline-PretendardMetrics.ttf') format('truetype');
  font-display: block;
}
@font-face {
  font-family: 'PolarisPNM';
  src: url('fonts/03-Polaris-PretendardOutline-NotoMetrics.ttf') format('truetype');
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
        ("Mixed script", "한컴 폰트 메트릭 호환성 (compat) 검증 — 2026."),
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

  <h3 style="margin-top: 18px;">Group A — Noto metrics</h3>
  <div class="linebreak-grid metric-a">
    <div class="col">
      <h3>NotoSansKR (원본)</h3>
      <p class="f-noto">{p}</p>
    </div>
    <div class="col">
      <h3>Polaris PNM <span class="muted">(Pretendard outline + Noto metrics)</span></h3>
      <p class="f-pnm">{p}</p>
    </div>
  </div>
  <p class="note">↑ 두 컬럼의 줄바꿈 위치가 같아야 정상. 글자의 굵기/형태는 달라도 됨.</p>

  <h3 style="margin-top: 24px;">Group B — Pretendard metrics</h3>
  <div class="linebreak-grid metric-b">
    <div class="col">
      <h3>Pretendard (원본)</h3>
      <p class="f-pretendard">{p}</p>
    </div>
    <div class="col">
      <h3>Polaris NPM <span class="muted">(Noto outline + Pretendard metrics)</span></h3>
      <p class="f-npm">{p}</p>
    </div>
  </div>
  <p class="note">↑ 마찬가지로, 두 컬럼의 줄바꿈 위치가 같아야 정상.</p>
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
  <h2>3. 사이즈 사다리 (10 → 48px)</h2>
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
  <h2>4. 표 / 숫자 정렬</h2>
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
  <h2>5. 문단 4분할 비교</h2>
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
  <h2>6. 글리프 클로즈업</h2>
  <p class="muted">큰 사이즈에서 외형 차이를 직접 확인. 같은 그룹(같은 색)은 advance 폭이
    동일하고, 다른 그룹은 advance가 다릅니다 — 셀의 너비를 보세요.</p>
  {''.join(cells)}
</section>
"""


if __name__ == "__main__":
    raise SystemExit(main())
