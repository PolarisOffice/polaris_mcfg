# 08. HTML 리포트 + 렌더링 회귀 (M6)

## 목표

1. 사람이 검토할 수 있는 시각적 비교 리포트.
2. HarfBuzz로 두 폰트의 같은 텍스트 렌더링 결과(라인 너비)를 비교하는 회귀 테스트.

## HTML 리포트

`comparator --format html` 또는 `report.format_html(diff)`.

자기 완결적(self-contained) 단일 HTML:
- 외부 CSS/JS 없음 — 메일 첨부, 브라우저 직접 열람 가능.
- 인라인 SVG 히스토그램으로 advance width delta 분포 표시.
- 색상 강조: 양수 delta(빨강) / 음수 delta(파랑).

### 구성

1. 헤더: A/B 파일명, unitsPerEm, threshold.
2. Global metrics: 차이가 있는 필드만 테이블로 표시.
3. Glyph advance widths: 통계 → SVG 히스토그램 → 상위 N개 차이 글리프 테이블.
4. (옵션) Rendering regression: 라인별 너비 비교 결과.

### 의도적 제약

- 글리프를 시각적으로 그리지 않는다 (라이센스 안전 — outline은 다루지 않음).
- 너비/델타 같은 숫자 데이터만 시각화.

## 렌더링 회귀 (`render.py`)

### 동기

메트릭 매치는 정확하지만, 실제 HarfBuzz shaping 결과가 동일한지를 직접 확인하는 게 더 강한 보증이다. 특히:
- ligature 형성으로 인한 advance 변화.
- GPOS positioning(`mark`, `cursive`) 영향.
- `kern` vs `GPOS kern` lookup의 차이.

### API

```python
measure_line(font_path, text) -> LineMeasurement(text, width_in_font_units, glyph_count)
compare_rendering(font_a, font_b, texts, *, tolerance_pct=1.0, normalize_upm=True) -> RenderComparison
```

`width`는 HarfBuzz의 `glyph_positions[*].x_advance` 합 (font units).

`tolerance_pct`는 라인별 |delta|/widthA × 100 의 상한. 기본 1%.

### 기본 샘플 텍스트

`DEFAULT_RENDER_TEXTS`: 한글, 라틴, 숫자, 구두점 포함 6줄. 사용자 텍스트 파일도 `--render-test FILE`로 지정 가능.

### Validator 통합

`--against` 가 폰트 파일인 경우 `--render-test` 가 활성화된다. JSON spec에는 outline이 없으므로 shape 불가 — 자동으로 skip.

체크 이름: `rendering_match`. 실패 시 `failingLines` 에 라인별 delta 포함.

## 의존성

`uharfbuzz` — 옵셔널. `pip install 'polaris-mcfg[render]'`.
미설치 시 `compare_rendering`/`measure_line` 호출 시점에 명확한 RuntimeError.

## 향후

- Glyph metric만으로 잡기 어려운 GPOS positioning 회귀 (커닝/마크) 분리.
- 동일 텍스트의 라인 분할(width-budget 기반 wrap) 시뮬레이션 → 줄바꿈 위치 비교.
- 다양한 font-size에서의 rounding 영향 측정.
