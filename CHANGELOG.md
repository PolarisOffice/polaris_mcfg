# Changelog

All notable changes to Polaris MCFG.

## [0.2.0] — 2026-04-27 — byte-perfect line-break match

Group A (Noto + Polaris PNM) and Group B (Pretendard + Polaris NPM) line
breaks now match byte-perfectly in the visual test page under both
`lang="en"` and `lang="ko"`. Achieved through five compounding fixes:

### Added
- **GPOS pair kerning** (P0/A1, P1/A2): extractor reads GPOS lookup type 2
  (PairPosFormat 1 + 2, including Extension wrapping). Generator replaces
  the design font's pair-pos lookups with a new lookup containing the
  source pairs and rewires the `kern` feature. Mark/cursive/contextual
  lookups are preserved. ~20K Latin pairs/font in NotoSansKR.
- **Missing-glyph notdef advance** (P3/A4): `--missing-glyph notdef` now
  sets the design font's `.notdef` advance to the source's, so glyphs
  that fall back to .notdef occupy the layout slot the source intended.
- **UPM rescaling** (P2/A5): `--match-upm` rescales the design font to
  the source's UPM via fontTools' `scale_upem` before applying metrics,
  eliminating the ±0.5-unit per-glyph rounding that otherwise drifts
  line breaks across UPM-mismatched fonts.
- **Output format `auto`** (P2/A5): `--output-format auto` switches to
  WOFF2 when `--match-upm` rescaled the design font, working around a
  Chromium TTF sanitizer rejection of scale_upem'd large CJK TTFs.
  Forced `ttf` / `woff2` also available.
- **GSUB shape-induced advance overrides** (v2/A3, opt-in):
  `--include-gsub` (extract) detects per-(codepoint, script, language)
  advance changes via HarfBuzz shaping comparison; `--apply gsub`
  (generate) injects them as `locl` feature substitutions with stub
  glyphs (empty outline + override advance). Browsers auto-activate
  `locl` when the page `lang` matches.
- New CLI flags: `--include-gsub`, `--apply gsub`, `--match-upm`,
  `--output-format`, `--missing-glyph notdef`.
- New schema field: `shapedAdvances` (list of overrides).
- New design docs: 09 (GPOS), 10 (UPM/format), 11 (GSUB).

### Tests

62 → 79 (+17): GPOS extraction & application (6), UPM/format (7), GSUB
overrides (4). Visual_test verified end-to-end in Chromium via the
Claude_Preview MCP browser harness.

### Visual test result

```
                       lang="en"        lang="ko"
Group A (Noto + PNM):  16 / 16  ✓       16 / 16  ✓
Group B (Pret + NPM):  15 / 15  ✓       15 / 15  ✓
```

---

## [0.1.0] — 2026-04-27

Initial release. Implements the full M1–M7 milestone set from `Requirements.md`.

### Added

- **M1 — Metric extractor** (`mcfg extract`)
  - JSON schema v1 (`MetricsSpec`) with deterministic serialization.
  - Strict `ALLOWED_TABLES` whitelist; outline tables (`glyf`/`CFF`/`CFF2`)
    are never read, enforced by a regression test.
- **M2 — Metric comparator** (`mcfg compare`)
  - text / json output, glyph match-rate stats, `--threshold`,
    `--normalize-upm`.
- **M3 — Font generator** (`mcfg generate`)
  - `--apply` subset of `{global, advance, lsb, kerning, vertical}`.
  - `--scale-glyph` modes: `none` / `fit` / `center` (TTF only in v1).
  - `--missing-glyph` `skip` / `notdef`.
  - `--family-name` / `--style-name` / `--license-text` / `--license-url`
    update name table IDs 1, 2, 4, 6, 13, 14, 16, 17.
  - Source-vs-design UPM mismatch is handled by scaling source values.
- **M4 — Validator** (`mcfg validate`)
  - Six checks: font_loadable, required_tables, global_metrics_match,
    advance_widths_match, glyph_coverage, name_metadata.
  - Outline-derived global fields (`xMin`/`xMax`, `advanceWidthMax`, …)
    excluded by default; `--strict-global` to opt in.
  - Exits 1 on any failed check.
- **M5 — Optional metrics**
  - LSB / kerning / vertical round-trip from extract → generate → validate.
  - Vertical diff in comparator; `lsb_match` / `kerning_match` /
    `vertical_match` checks in validator.
- **M6 — HTML report + HarfBuzz rendering regression**
  - `mcfg compare --format html`: self-contained HTML (no external
    assets) with inline SVG histogram.
  - `mcfg validate --render-test FILE` / `--render-default`: line-width
    comparison via `uharfbuzz`. Adds a `rendering_match` check.
- **M7 — Packaging, samples, docs**
  - `pyproject.toml` with `mcfg` console script, `[render]` and `[dev]`
    extras.
  - `samples/run_demo.py`: end-to-end pipeline demo using NotoSansKR.
  - 8 design documents under `docs/design/`.
  - 62 pytest tests, all green.

### Out of scope (deferred)

- CFF/OTF design fonts in the generator.
- GPOS pair-positioning extraction (only classic `kern` format 0 in v1).
- Variable-font axis-by-axis metric interpolation.
- GUI.
