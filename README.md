# Polaris MCFG

**Metric-Compatible Font Generator** — 재배포가 제한된 폰트(상용 / 사내 / 한컴 폰트류 등 임의의 소스 폰트)의 **레이아웃 메트릭**(advance width, ascender/descender, line gap 등)을 추출하여 자유 라이센스 폰트의 **글리프 디자인**에 결합한 새로운 폰트를 생성합니다. 원본 문서의 줄바꿈/페이지 분할은 유지하면서 라이센스 안전성을 확보합니다.

> 본 도구는 **글리프 외형(outline)을 추출/복제하지 않으며**, 숫자 메트릭만 다룹니다 ([라이센스 안전 경계](docs/design/02-metrics-schema.md#라이센스-안전-경계)).

[![CI](https://github.com/PolarisOffice/polaris_mcfg/actions/workflows/ci.yml/badge.svg)](https://github.com/PolarisOffice/polaris_mcfg/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-150%20passed-green)](tests/)
[![demo](https://img.shields.io/badge/demo-GitHub%20Pages-blue)](https://polarisoffice.github.io/polaris_mcfg/demo/)
[![python](https://img.shields.io/badge/python-3.10+-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![code of conduct](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa)](CODE_OF_CONDUCT.md)

**🎯 [Live demo →](https://polarisoffice.github.io/polaris_mcfg/demo/)** — NotoSansKR/Pretendard 교차 합성 결과 4개 폰트로 라인브레이크가 메트릭 그룹별로 일치하는지 직접 비교.

---

## 무엇을 하는가

```
[Source font.ttf]                         [Free font.ttf]
       │                                          │
       │ extract (메트릭만, outline 미접근)        │
       ▼                                          │
[metrics.json] ──────► compare ◄──────── extract ─┘
       │                                          │
       │                                          ▼
       └──────────► generate ◄──────────  [Free font.ttf]
                       │
                       ▼
               [Polaris font.ttf]  ← 외형은 free, 레이아웃은 source와 호환
                       │
                       ▼
                   validate
                       │
                       ▼
              [pass / fail report]
```

## 빠른 시작

```bash
git clone https://github.com/PolarisOffice/polaris_mcfg
cd polaris_mcfg
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest               # 150 tests
mcfg --help
```

## CLI

| 서브커맨드 | 설명 |
|-----------|------|
| `mcfg extract <font.ttf>` | 메트릭을 JSON 스펙으로 추출 (기본 `--backend file`) |
| `mcfg extract <font.ttf> --backend render` | **EULA-safe** 추출: 폰트를 렌더링한 결과 + HarfBuzz shape 로 메트릭 복원. FreeType / Chromium 백엔드. ±1~2u 정확도. |
| `mcfg compare a b` | 두 폰트(또는 메트릭 JSON) 비교 — text / json / html |
| `mcfg generate --metrics … --design …` | 메트릭 + 디자인 폰트 → 새 폰트 |
| `mcfg validate <font> --against …` | 결과 폰트가 메트릭을 만족하는지 검증 |

각 커맨드에 `--help`로 옵션 확인.

### Backend 선택 — file vs render

| | `--backend file` (기본) | `--backend render` (v0.3+) |
|---|---|---|
| 추출 방식 | fontTools 로 테이블 직접 파싱 | FreeType / Chromium 렌더링 + HarfBuzz shape |
| 속도 | 빠름 (수십 ms) | 느림 (수 초 ~ 수십 분) |
| 정확도 | 정확 (정수 unit) | ±1~2 unit |
| EULA 가 file parsing 금지하는 폰트 | ❌ | ✅ |
| 컨텍스트 룩업 (calt, mark pos) | 부분 지원 | 미지원 |

자세한 내용: [docs/design/12-render-extractor.md](docs/design/12-render-extractor.md).

### EULA 강도별 4가지 모드 (`--backend render`)

폰트 EULA 가 어디까지 허용하느냐에 따라 layer 를 선택합니다. **HarfBuzz shape 와 file numeric copy 는 엄격한 EULA 해석에서는 reverse engineering 으로 분류될 수 있다**는 점을 정직하게 고지합니다:

| 모드 | 사용 layer | EULA 위치 | 메트릭 복원율 |
|---|---|---|---:|
| `--pixel-only` | 순수 픽셀 측정만 | "디자이너가 화면 보고 자로 잰다" 와 동등. **모든 EULA 안전** | ~80% (advance + LSB + vertical + italic + underline) |
| (기본) | + HarfBuzz shape | HB 는 텍스트 엔진 (브라우저/OS 가 매일 사용). "정상 사용" 으로 일반 인정 | ~90% (+ kerning + shaped advance) |
| `--full-reference FILE` | + file numeric copy (pair list, metadata, unnamed glyph) | fontTools 로 file table read. **numeric only** (outline 안 봄). 엄격한 EULA 해석 시 reverse engineering 으로 분류 가능 | ~100% |
| `--backend file` | 전체 file parsing | 강한 reverse engineering. EULA 가 명시 금지 시 위반 | 100% (정수 정확) |

**권장 사용**:
- **OFL / 일반 상용 폰트**: 기본 모드 (HB shape 까지 OK)
- **EULA가 "metric extraction" 명시 금지 폰트** (일부 한컴 폰트 등): `--pixel-only`
- **공개 폰트로 빠른 작업**: `--backend file` (수십 ms)

자세한 layer 별 EULA 분석: [docs/design/12-render-extractor.md §1](docs/design/12-render-extractor.md#1-라이센스-안전-경계).

### Render 백엔드 옵션 매트릭스

| 옵션 | 효과 |
|---|---|
| `--renderer [auto\|freetype\|browser]` | 렌더 엔진 선택. browser 는 가장 강한 EULA 방어선 (Chromium `@font-face` data: URL 로 적재). |
| `--render-size N` | 측정 정밀도 — 1000px (기본) → 1u 정확도. |
| `--workdir DIR` | 측정에 사용된 모든 PNG 를 DIR 에 dump. 디버그 / 검증용. |
| `--include-lsb` | per-glyph LSB 측정 추가 |
| `--include-kerning` | HB pair shape 으로 페어 간격 측정 (`--pixel-only` 시 자동 비활성) |
| `--include-shaped` | 언어 컨텍스트별 advance 변화 (`--pixel-only` 시 자동 비활성) |
| `--metadata-from FILE` | head/hhea/OS-2/post 분류 플래그 numeric copy |
| `--pair-list-from FILE` | 페어 후보 list numeric copy (값은 HB 가 측정) |
| `--unnamed-from FILE` | cmap 외 글리프 (notdef variants 등) 의 advance/LSB numeric copy |
| `--full-reference FILE` | 위 셋의 shorthand |

### Incremental 업데이트 (v0.3.2+)

전체 cmap 측정은 CJK 폰트에서 ~40분. 작은 fix 마다 다시 돌릴 수는 없으니, **이전 결과 spec 위에 일부 영역만 다시 측정**해서 머지하는 메커니즘:

```bash
# 1) 최초 전체 분석 (한 번만, ~40분)
mcfg extract source.ttf --backend render --full-reference source.ttf \
    --include-lsb --include-kerning --include-shaped \
    -o ~/work/source.spec.json

# 2) 이후 한 블록만 다시 측정 (예: probe 수정 후, 30초)
mcfg extract source.ttf --backend render \
    --update-spec ~/work/source.spec.json \
    --refresh-block "Halfwidth/Fullwidth Forms" \
    --full-reference source.ttf \
    -o ~/work/source.spec.json   # 같은 파일 덮어쓰면 누적

# 3) 특정 codepoint 만 갱신 (예: 새 글자 추가)
mcfg extract source.ttf --backend render \
    --update-spec ~/work/source.spec.json \
    --refresh-cmap "0xAC00-0xAC10,0x1F600-0x1F60F" \
    -o ~/work/source.spec.json
```

매 머지마다 `spec.source.updateHistory` 에 자동 기록 (timestamp + 오버레이 크기) — 분석 파일의 진화 이력이 spec 자체에 남습니다.

### CJK 폰트 fast-path (자동)

다음 monospace 블록을 자동 감지해 4-probe 측정으로 단축 (전체의 ~78%):

| 블록 | 범위 | NotoSansKR-Bold 글리프 수 |
|---|---|---:|
| Hangul Syllables | U+AC00..U+D7A3 | 11,172 |
| CJK Unified Ideographs | U+4E00..U+9FFF | 7,867 |
| CJK Compatibility Ideographs | U+F900..U+FAFF | 510 |
| Halfwidth/Fullwidth Forms | U+FF00..U+FFEF | 170 |

24K 글리프 advance probe → 약 16 probe 로 99.9%+ 절감.

### 실측 정확도 — NotoSansKR-Bold (전체 cmap)

| 메트릭 | 매치 비율 | 비고 |
|---|---:|---|
| `font_loadable` | ✓ | — |
| `glyph_coverage` | 100% | — |
| `advance_widths_match` | **100%** (24853/24853) | 모든 글자 너비 정확 |
| `lsb_match` | **99.94%** (24838/24853) | 잔여 15 측정 잡음 |
| `kerning_match` | **99.94%** (20985/20997) | 12 페어 누락 (base spec 잔재) |
| `vertical_match` | 100% | — |
| `name_metadata` | 100% | — |
| `global_metrics` | 10/11 fields | head.flags 만 fontTools 자동 재계산 |

전체 분석 시간: **render extract 37분 + incremental Halfwidth 30초 + unnamed copy 0.5초**.

## 엔드 투 엔드 예시

```bash
# 1. 소스 폰트(예시: NotoSansKR-Bold; 실제로는 한컴 폰트 등 임의의 소스)에서 메트릭 추출
mcfg extract NotoSansKR-Bold.ttf --deterministic -o bold.json

# 2. NotoSansKR-Regular의 외형 + Bold의 메트릭으로 새 폰트 생성
mcfg generate \
  --metrics bold.json \
  --design  NotoSansKR-Regular.ttf \
  --output  PolarisBoldMetrics-Regular.ttf \
  --apply   global,advance \
  --family-name "Polaris Bold-Metrics" \
  --style-name  "Regular" \
  --license-text "SIL Open Font License 1.1" \
  --license-url  "https://scripts.sil.org/OFL"

# 3. 검증 + 렌더링 회귀 (HarfBuzz 라인 너비 비교)
mcfg validate PolarisBoldMetrics-Regular.ttf \
  --against NotoSansKR-Bold.ttf \
  --render-default \
  --render-tolerance-pct 0.5
# → result: PASS  (advance widths 일치, 렌더링 ±0.5% 이내)

# 4. 시각적 차이 확인
mcfg compare NotoSansKR-Bold.ttf PolarisBoldMetrics-Regular.ttf \
     --format html -o diff.html
open diff.html
```

전체 파이프라인 자동화 스크립트는 [samples/run_demo.py](samples/run_demo.py).

## 마일스톤

| | 내용 | 상태 |
|---|------|------|
| M1 | 메트릭 추출기 + JSON 스키마 v1 + 단위 테스트 | ✓ |
| M2 | 메트릭 비교기 (text/json) | ✓ |
| M3 | 폰트 생성기 (global + advance, scale-glyph none/fit/center) | ✓ |
| M4 | 검증기 (구조/메트릭/커버리지/name) | ✓ |
| M5 | 옵션 메트릭 (LSB, kerning, vertical) 라운드트립 | ✓ |
| M6 | HTML 리포트 + HarfBuzz 렌더링 회귀 | ✓ |
| M7 | 패키징, 샘플, 문서 | ✓ |

## 문서

- **[로드맵 / 지원 범위](ROADMAP.md)** — 공개 사용 전 반드시 확인 (TTF 외 컨테이너·RTL/Indic·mark positioning 등 한계 매트릭스).
- [요구사항](Requirements.md)
- [설계 문서](docs/design/)
  - [01. 아키텍처 개요](docs/design/01-architecture.md)
  - [02. MetricsSpec 스키마](docs/design/02-metrics-schema.md)
  - [03. 메트릭 추출기](docs/design/03-extractor.md)
  - [04. 메트릭 비교기](docs/design/04-comparator.md)
  - [05. 폰트 생성기](docs/design/05-generator.md)
  - [06. 검증기](docs/design/06-validator.md)
  - [07. 옵션 메트릭](docs/design/07-optional-metrics.md)
  - [08. HTML/렌더링](docs/design/08-html-and-render.md)
  - [12. Render 추출기 — EULA-safe pixel/HB layer](docs/design/12-render-extractor.md)
- [변경 로그](CHANGELOG.md)

## 라이센스

- 본 도구의 코드: [MIT](LICENSE).
- 도구가 생성한 폰트의 라이센스는 입력으로 사용한 **디자인 폰트의 라이센스**(OFL 등)를 따릅니다 — 본 도구는 메트릭 외 어떤 글리프 데이터도 만들거나 복제하지 않습니다.
- 라이센스 제한이 있는 소스 폰트(한컴 폰트, 사내/상용 폰트 등)로부터 메트릭을 추출해 사용하는 경우, 해당 폰트 EULA의 메트릭 추출 허용 여부를 별도로 검토할 책임은 사용자에게 있습니다 (Requirements.md §6).
