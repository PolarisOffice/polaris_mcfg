# Changelog

All notable changes to Polaris MCFG.

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
