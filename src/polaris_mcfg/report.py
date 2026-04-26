"""M6 — HTML report renderer for the comparator.

A single self-contained HTML page with inline CSS and an inline SVG histogram
of advance-width deltas. No external assets, no JavaScript.
"""
from __future__ import annotations

import html
from typing import Iterable

from .comparator import MetricsDiff


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _histogram_svg(deltas: Iterable[int], *, width: int = 600,
                   height: int = 160, bins: int = 31) -> str:
    """Tiny inline SVG histogram of ``deltas`` (integer values)."""
    deltas = list(deltas)
    if not deltas:
        return f'<svg width="{width}" height="{height}"></svg>'
    lo, hi = min(deltas), max(deltas)
    if lo == hi:
        lo -= 1
        hi += 1
    span = hi - lo
    counts = [0] * bins
    for d in deltas:
        idx = min(bins - 1, int((d - lo) / span * bins))
        counts[idx] += 1
    cmax = max(counts) or 1
    bw = width / bins
    parts = [f'<svg width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" '
             f'xmlns="http://www.w3.org/2000/svg">']
    # Zero line.
    if lo < 0 < hi:
        zero_x = -lo / span * width
        parts.append(f'<line x1="{zero_x:.1f}" y1="0" x2="{zero_x:.1f}" '
                     f'y2="{height}" stroke="#bbb" stroke-dasharray="3,3"/>')
    for i, c in enumerate(counts):
        h_px = (c / cmax) * (height - 20)
        x = i * bw
        y = height - h_px
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" '
                     f'width="{bw - 1:.2f}" height="{h_px:.2f}" '
                     f'fill="#3672c5"/>')
    parts.append(f'<text x="2" y="{height - 2}" font-size="10" fill="#555">'
                 f'Δ min={lo}, max={hi}, n={len(deltas)}</text>')
    parts.append("</svg>")
    return "".join(parts)


_CSS = """
body { font: 13px -apple-system, BlinkMacSystemFont, sans-serif;
       color: #222; max-width: 960px; margin: 24px auto; padding: 0 16px; }
h1 { font-size: 18px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }
h2 { font-size: 15px; margin-top: 24px; color: #444; }
.summary, table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; }
.summary td, table td, table th { padding: 4px 8px; border-bottom: 1px solid #eee; }
table th { text-align: left; background: #f7f7f7; }
.kv-key { color: #666; width: 30%; }
.fail { color: #c0392b; font-weight: 600; }
.pass { color: #27ae60; font-weight: 600; }
.delta-pos { color: #c0392b; }
.delta-neg { color: #2c4ec9; }
.muted { color: #888; }
code { font: 12px Menlo, Monaco, monospace; background: #f5f5f5;
       padding: 1px 5px; border-radius: 3px; }
.histogram { background: #fafafa; padding: 8px; border: 1px solid #eee; }
"""


def _global_section(diff: MetricsDiff) -> str:
    rows = []
    for tbl, fields in diff.global_diff.differences.items():
        if not fields:
            continue
        rows.append(f'<tr><th colspan="3">{tbl}</th></tr>')
        for k, (av, bv) in fields.items():
            rows.append(f'<tr><td><code>{_esc(k)}</code></td>'
                        f'<td>{_esc(av)}</td><td>{_esc(bv)}</td></tr>')
    if not rows:
        return '<p class="muted">All global metric fields match.</p>'
    return ('<table><tr><th>Field</th><th>A</th><th>B</th></tr>'
            + "".join(rows) + '</table>')


def _advance_section(diff: MetricsDiff, *, top_n: int = 50) -> str:
    s = diff.advance_diff.stats
    parts = [
        '<table class="summary">',
        f'<tr><td class="kv-key">Common glyphs</td><td>{s.get("commonCount", 0)}</td></tr>',
        f'<tr><td class="kv-key">Matching</td><td>{s.get("matchingCount", 0)}</td></tr>',
        f'<tr><td class="kv-key">Differing</td><td>{s.get("differingCount", 0)}</td></tr>',
        f'<tr><td class="kv-key">Match rate</td><td>{s.get("matchRate", 0):.4f}</td></tr>',
        f'<tr><td class="kv-key">Only in A</td><td>{s.get("onlyInACount", 0)}</td></tr>',
        f'<tr><td class="kv-key">Only in B</td><td>{s.get("onlyInBCount", 0)}</td></tr>',
        '</table>',
    ]
    deltas = list(v[2] for v in diff.advance_diff.common.values())
    if deltas:
        parts.append('<div class="histogram">' + _histogram_svg(deltas) + '</div>')
        parts.append(f'<h3>Top {min(top_n, len(deltas))} differing glyphs</h3>')
        sorted_items = sorted(diff.advance_diff.common.items(),
                              key=lambda kv: -abs(kv[1][2]))
        rows = ['<table><tr><th>Glyph</th><th>A</th><th>B</th><th>Δ</th></tr>']
        for k, (av, bv, d) in sorted_items[:top_n]:
            cls = "delta-pos" if d > 0 else "delta-neg"
            rows.append(f'<tr><td><code>{_esc(k)}</code></td>'
                        f'<td>{av}</td><td>{bv}</td>'
                        f'<td class="{cls}">{d:+d}</td></tr>')
        rows.append('</table>')
        parts.append("".join(rows))
    return "\n".join(parts)


def format_html(diff: MetricsDiff, *, render_comparison=None,
                top_n: int = 50) -> str:
    """Render the diff as a self-contained HTML document."""
    a_name = diff.a_source.get("filename", "A")
    b_name = diff.b_source.get("filename", "B")

    rendering = ""
    if render_comparison is not None:
        rc = render_comparison
        marker = ('<span class="pass">PASS</span>' if rc.passed
                  else '<span class="fail">FAIL</span>')
        rows = ['<table><tr><th>Text</th><th>A width</th><th>B width</th>'
                '<th>Δ%</th><th></th></tr>']
        for ln in rc.lines:
            cls = "pass" if ln["passed"] else "fail"
            rows.append(f'<tr><td>{_esc(ln["text"])[:60]}</td>'
                        f'<td>{ln["widthA"]}</td><td>{ln["widthB"]}</td>'
                        f'<td>{ln["deltaPct"]:+.3f}</td>'
                        f'<td class="{cls}">'
                        f'{"OK" if ln["passed"] else "FAIL"}</td></tr>')
        rows.append('</table>')
        rendering = (
            '<h2>Rendering regression (HarfBuzz)</h2>'
            f'<p>Tolerance: {rc.tolerance_pct}% — Result: {marker}</p>'
            + "".join(rows)
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Polaris MCFG diff: {_esc(a_name)} → {_esc(b_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Polaris MCFG diff: <code>{_esc(a_name)}</code> → <code>{_esc(b_name)}</code></h1>
<table class="summary">
  <tr><td class="kv-key">unitsPerEm</td>
      <td>A = {diff.units_per_em[0]} &nbsp;&nbsp; B = {diff.units_per_em[1]}</td></tr>
  <tr><td class="kv-key">threshold</td><td>{diff.threshold} units</td></tr>
</table>

<h2>Global metrics</h2>
{_global_section(diff)}

<h2>Glyph advance widths</h2>
{_advance_section(diff, top_n=top_n)}

{rendering}
</body>
</html>
"""
