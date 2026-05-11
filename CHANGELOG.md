# Changelog

All notable changes to Polaris MCFG.

## [0.3.0] — 2026-05-11 — M8 render-based extractor

EULA-safe metric extraction: instead of reading font tables directly,
this release adds a parallel extraction backend that measures the font
through normal rendering pipelines (FreeType, Playwright/Chromium) and
recovers metrics from pixel measurements + HarfBuzz shaping output.

### Added — `mcfg extract --backend render`

- **FreeType backend** (`--renderer freetype`): rasterizes each cmap
  glyph via FT, measures advance via AAAA linear-fit pattern (±0.25 px),
  per-glyph LSB from ink bbox vs pen position. Works with hinting off
  for sub-pixel precision.
- **Browser backend** (`--renderer browser`): Chromium loads the font
  via `@font-face` data: URL — our code never opens the font file.
  Strongest EULA defense in the suite. Screenshots are measured the
  same way as FreeType output.
- **Hangul monospace fast-path** (`--detect-monospace`, default on):
  probes `가뷁이왈`, replicates the common advance to the 11,172
  Hangul Syllables block if all four agree. Per-syllable LSB still
  measured individually (cheap single render). 30%+ speedup on Korean
  fonts.
- **Kerning** (`--include-kerning`): default candidate set of
  ASCII × ASCII + ASCII × Korean-punctuation + Korean-punct × ASCII
  pairs (~14K), shaped through HarfBuzz, filtered by 2-unit threshold.
  Captures both classic `kern` and GPOS PairPos correctly by reading
  total pair advance (handles HB's classic-kern advance/offset split).
- **Shaped advances** (`--include-shaped` / `--include-gsub`): per-
  (codepoint, script, language) advance overrides via HB shaping.
  Functionally identical to the file backend's GSUB extraction.
- **Auto-cmap**: when called without an explicit codepoint list, reads
  the font's `cmap` table only (numeric whitelist — no outline data).

### Architecture

```
src/polaris_mcfg/render_extractor/
  __init__.py          # extract_via_render() entry point
  orchestrator.py      # decides what to render and assembles the spec
  backends/
    base.py            # RenderBackend ABC + dataclasses
    freetype_backend.py
    browser_backend.py
  analyzer.py          # pixel-bbox + N-repeat linear-fit advance
  units.py             # pixel → font-unit conversion
  kerning.py           # HB pair shaping + threshold filter
  shaped.py            # HB context shaping for shapedAdvances
```

### Design

- `docs/design/12-render-extractor.md` — full design (architecture,
  EULA boundary, per-metric measurement procedure, accuracy gates,
  risks).

### Tests

89 → 121. New `tests/render_extractor/` covers P1-P6:
- backend wiring + FreeType advance ±1u on synth + NotoSansKR
- vertical / advance / LSB on synth + real-font regression
- Hangul monospace detection + replication + perf
- kerning recovery with HB pair distribution (-100 → captured exact)
- browser ↔ FreeType cross-backend agreement (±1u)
- shaped advance parity with file backend (byte-identical via HB)
- full pipeline regression on NotoSansKR-Bold: 13 codepoints, advance
  ≤ 2u, LSB ≤ 5u, kerning exact

### CLI

- `mcfg extract --backend [file|render]` (default `file`).
- `--renderer [auto|freetype|browser]`, `--render-size N`,
  `--no-detect-monospace`, `--include-shaped`.
- All other flags work in both backends.

### Optional dependencies (`pyproject.toml`)

- `[render-extract]`: `freetype-py`, `Pillow`, `numpy`.
- `[render-extract-browser]`: `playwright`, `Pillow`, `numpy`.
- `[dev]` pulls in both for the full test matrix.

---

## [0.2.5] — 2026-05-11 — public release tag

First tagged release after the repository moved to `PolarisOffice/polaris_mcfg`
and went public.

### Fixed
- `README.md` demo badge and "Live demo →" link pointed at the GitHub
  Pages landing page (`/`) instead of the interactive demo at `/demo/`.
  Both now resolve to the actual line-break comparison page.

---

## [0.2.3] — 2026-04-27 — generalize source-font terminology

The "Hancom font" framing was always meant as one motivating example;
the tool itself accepts any source font (corporate, commercial, third
party). Documentation now reflects that — Hancom is mentioned as an
example alongside corporate/commercial fonts rather than as the
exclusive use case.

### Changed
- `Requirements.md` §1, §6 reframed around "재배포가 제한된 소스 폰트
  (한컴 폰트, 사내 전용 폰트, 일부 상용 폰트 등)" with a one-line note
  preserving the original Hancom motivation.
- `README.md` intro, pipeline diagram, end-to-end example, license
  note: "Hancom font" → "Source font".
- `docs/index.html`, `docs/design/01-architecture.md`,
  `docs/design/02-metrics-schema.md`, `docs/design/07-optional-metrics.md`,
  `samples/run_demo.py` similarly generalized.
- Demo paragraph (`samples/visual_test/build.py`,
  `src/polaris_mcfg/render.py` default texts) and `docs/demo/index.html`
  rebuilt with the new text.
- Filename examples `HancomMalang.ttf` → `SourceFont-Regular.ttf` /
  `source.metrics.json`.

### Verified
- All 84 tests still pass.
- `docs/demo/` rebuilt: Group A 17/17 + Group B 16/16 byte-perfect
  line-break match (line counts grew by 1 because the rephrased
  paragraph is slightly longer; matching behavior unchanged).

---

## [0.2.4] — 2026-04-29 — codex review bundle

External code review surfaced four issues, all fixed. Tests 84 → 88.

### Fixed
- **GSUB override no longer hides visible glyphs.** Earlier versions
  created an empty-outline stub for every shaped-advance override and
  routed substitutions there. The extractor records *any* codepoint
  whose shaped advance changes — not just whitespace — so visible
  punctuation (`,` `.` `?` `'` `"` `—` etc., 25+ glyphs in NotoSansKR
  under hang/KOR) was vanishing under `lang="ko"` rendering. The stub
  now `copy.deepcopy`s the design font's glyph outline for that
  codepoint and only overrides the advance + LSB.
- **Kerning values are UPM-scaled.** `_apply_kerning` was writing source
  unit values directly into design-UPM-relative tables. With source
  upm=2000 / design upm=1000 a `-200` pair came out at `-200` instead of
  `-100`, visibly over-kerning. Now passes through `_scaled(value,
  src_upm, dst_upm)` (no-op when `--match-upm` already aligned UPMs).
- **PairPos lookups in non-`kern` features are preserved.** The GPOS
  writer used to drop *every* lookup of type 2 and remap the FeatureList
  indices, which (a) silently broke design-font behavior when a PairPos
  was reused by `cpsp`/`palt`/etc., and (b) left dangling
  SubstLookupRecord indices in contextual lookups (type 7/8). Now
  follows the same pattern as `_strip_locl_feature`: append our new
  lookup, detach existing PairPos indices from the `kern` feature only,
  leave LookupList intact so other features and contextual references
  stay valid.
- **`OFL-NotoSansKR.txt` corrected.** Both `fonts/Noto_Sans_KR/OFL.txt`
  and `docs/demo/fonts/OFL-NotoSansKR.txt` shipped Adobe's Source-Han
  copyright (this is the OFL file Google Fonts bundles in the Noto Sans
  KR zip download — a known packaging issue). Replaced with the
  canonical [notofonts/noto-cjk LICENSE][noto-cjk-license].

[noto-cjk-license]: https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE

### Added (regression tests, +4)
- `tests/test_codex_review.py`:
  - GSUB stub clones design outline (visible glyphs stay visible)
  - kerning UPM scaling (source upm=2000 → design upm=1000 halves values)
  - kerning UPM no-op when UPMs match
  - PairPos lookup referenced by `cpsp` survives our kern injection

### Verified
- 88 pytest tests passing (was 84).
- Demo rebuild: 27 visible-outline stub glyphs land in subsetted PNM
  woff2 (subsetter renames them anonymously but preserves outlines and
  the locl substitution mapping).

---

## [0.2.2] — 2026-04-27 — code review bundle

Bundle of fixes from the v0.2.1 self-review. Tests 79 → 84.

### Fixed
- **`pyproject.toml` version** was stuck at `0.1.0`; now tracks the
  CHANGELOG (`__version__` matches).
- **`_check_lsb` crash on partial-None LSBs**: when one spec extracted
  LSBs and the other didn't, `abs(a - r)` raised on `None`. Now the
  per-glyph filter skips any pair with a `None` side rather than
  failing.
- **WOFF2 reference fonts in `validate --against` and `compare`**:
  `_FONT_SUFFIXES` now includes `.woff` / `.woff2`, and the rendering
  check accepts those suffixes too. `render._hb_readable_path` context
  manager transparently decompresses WOFF/WOFF2 to a temp TTF for
  HarfBuzz, which can't read the compressed flavors directly.
- **`uharfbuzz` install hint**: error messages now direct users to
  `pip install -e '.[dev]'` from a checkout, or `pip install uharfbuzz`
  standalone (PyPI distribution is intentionally not on the roadmap —
  see ROADMAP §3).
- **kerning diff now honors `--threshold`**: was only used for global /
  advance / lsb / vertical; now the kerning section drops
  ±threshold-or-less differences too, matching the rest.
- **`--missing-glyph notdef` actually does what it says**: previously
  only set the design font's `.notdef` advance and counted missings;
  now also routes the missing codepoints to a notdef-equivalent stub
  glyph (`polaris.notdef_fallback`, empty outline + `.notdef`'s
  advance) added to the cmap. fontTools drops cmap-to-`.notdef`
  entries on compile because OpenType treats them as implicit, so a
  distinct stub keeps the routing explicit.

### Cleanup
- Removed unused `asdict` import from `schema.py`.
- Removed orphan comment in `generator.py` (line 509 reference to a
  defunct type-signature change).
- `MetricsSpec` docstring now explains the byte-deterministic fixed
  key order rather than just saying "deterministic".
- Stale milestone references (`v1`, `M6 deferred`) replaced with
  current-state language across module docstrings.
- `EXTRACTED_FIELDS` dangling reference in `schema.py` corrected to
  the actual constant names (`HEAD_FIELDS`, etc.).
- `docs/design/03-extractor.md` updated to reflect GPOS pair
  extraction (was still claiming "kern format 0 only") and the new
  `--include-gsub` flag.

### Added (regression tests)
- `tests/test_review_fixes.py` (5 tests):
  - notdef remap routes missing codepoints to a stub glyph in the cmap.
  - skip mode does NOT add a stub or touch the cmap.
  - kerning diff with `threshold=1` masks ±1u differences.
  - LSB check skips when reference spec has no LSBs (no crash).
  - Validator's rendering check works with WOFF2 reference fonts.

---

## [0.2.1] — 2026-04-27 — GitHub Pages demo + locl strip refinement

### Added
- **`docs/demo/`** — self-contained GitHub Pages demo. 4 fonts subsetted to
  the demo text + common Korean/Latin punctuation, all WOFF2-compressed.
  Total page weight ~175 KB. OFL.txt files for both source families
  bundled alongside.
- **`docs/index.html`** — landing page with project intro + demo CTA.
- **`docs/demo/build.py`** — build script for the demo (subsetting +
  WOFF2 packaging on top of `samples/visual_test/build.py`'s pipeline).

### Fixed
- `_strip_locl_feature` no longer drops GSUB lookups, only the `locl`
  feature records and their LangSys references. Contextual / chaining
  lookups (type 5/6) reference other lookups by index inside their
  SubstLookupRecord, so removing locl-exclusive lookups left dangling
  references that broke `fontTools.subset.Subsetter`. Leaving the
  underlying lookups in place is a small file-size cost; with the locl
  feature gone, browsers no longer auto-activate them under `lang`.

### License
- Polaris NPM / Polaris PNM are derivative works under
  [SIL OFL 1.1](https://scripts.sil.org/OFL). Family names changed per
  the Reserved Font Name policy. Bundled OFL.txt provides the original
  copyrights for NotoSansKR (Adobe / Google) and Pretendard.

---

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
