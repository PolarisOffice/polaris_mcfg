# Polaris MCFG

**Metric-Compatible Font Generator** — 재배포가 제한된 폰트(상용 / 사내 / 한컴 폰트류 등 임의의 소스 폰트)의 **레이아웃 메트릭**(advance width, ascender/descender, line gap 등)을 추출하여 자유 라이센스 폰트의 **글리프 디자인**에 결합한 새로운 폰트를 생성합니다. 원본 문서의 줄바꿈/페이지 분할은 유지하면서 라이센스 안전성을 확보합니다.

> 본 도구는 **글리프 외형(outline)을 추출/복제하지 않으며**, 숫자 메트릭만 다룹니다 ([라이센스 안전 경계](docs/design/02-metrics-schema.md#라이센스-안전-경계)).

[![CI](https://github.com/PolarisOffice/polaris_mcfg/actions/workflows/ci.yml/badge.svg)](https://github.com/PolarisOffice/polaris_mcfg/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-154%20passed-green)](tests/)
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
pytest               # 154 tests
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

### 두 가지 모드 — Strict 또는 Full

영역 A (정상 rendering 출력) vs 영역 B (internal table 직접 분석) 의 boundary 가 sharp 하고, 영역 A 안에서 휴리스틱 만으로는 CJK 폰트에서 5% 미만 복원율이라 **운영상 의미 있는 모드는 두 개뿐**입니다:

```bash
# ─── Strict 모드 ────────────────────────────────────
# EULA 가 metric extraction / reverse engineering 명시 금지하는 폰트용
# (일부 한컴 폰트, 사내 전용 폰트 등)
mcfg extract source.ttf --backend render --pixel-only --include-lsb \
     -o spec.json
# → 영역 A 만. ~80% 복원 (advance + LSB + vertical + italic + underline)
# → kerning / shaped advance / unnamed glyph 미복원

# ─── Full 모드 ──────────────────────────────────────
# EULA 가 허용하는 폰트용 (대부분의 OFL, 일반 상용 폰트)
mcfg extract source.ttf --backend render --full-reference source.ttf \
     -o spec.json
# → 영역 A + B 모두. ~100% 복원
# → --full-reference 가 자동으로 include_lsb, include_kerning,
#    include_shaped 활성화
```

### 두 모드 비교

| | **Strict** (`--pixel-only`) | **Full** (`--full-reference`) |
|---|---|---|
| 영역 사용 | A 만 (rendering 결과) | A + B (rendering + internal table) |
| advance / LSB / vertical | ~100% | ~100% |
| kerning | **0** | **~100%** |
| shaped advance | 0 | ~100% |
| unnamed glyph metric | 0 | ~100% |
| 메타데이터 분류 플래그 | pixel-derivable 만 | ~100% |
| **EULA 권장 폰트** | metric extraction 명시 금지 | 일반 폰트 (OFL 등) |

### 왜 중간이 없는가

- **휴리스틱 default (영역 A 안)**: NotoSansKR 의 GPOS 페어 21K 중 ASCII × ASCII 영역이 1K (5%). 한자-한자 클래스 페어 19.9K 는 잡지 못함. **CJK 폰트에서 사실상 무용**.
- **외부 페어 list 입력 (영역 A 안)**: 어차피 그 list 도 어딘가의 file 분석 결과. 결국 영역 B 정보.
- **그래서 의미 있는 선택은 Strict (kerning 포기) 또는 Full (영역 B 포함) 둘 뿐**.

### 영역의 의미

| 영역 A — 정상 rendering 출력 | 영역 B — Internal table 직접 분석 |
|---|---|
| 픽셀 측정 (FreeType / Chromium 렌더 결과) | 페어 list (`kern` + `GPOS PairPos` 안의 페어 tuple) |
| HarfBuzz shape() 결과 (positioning numeric) | 메타데이터 (`head`/`hhea`/`OS/2`/`post` enum) |
| ↑ Chrome/Firefox/OS 가 매일 호출 | unnamed glyph metric (cmap 외 `hmtx` 값) |
| ↑ 픽셀에서도 같은 정보 얻을 수 있음 | ↑ Rendering 시 노출되지 않는 internal lookup |
| **EULA 안전** | **reverse engineering 영역** |

**권장 사용**:

| 폰트 카테고리 | 모드 |
|---|---|
| OFL / 일반 상용 폰트 | 기본 (HB shape 까지 OK), 또는 `--backend file` 으로 빠르게 |
| EULA가 "metric extraction" 또는 "reverse engineering" 명시 금지 폰트 (일부 한컴/사내 폰트) | `--pixel-only` 또는 기본 (HB shape 까지). 영역 B 옵션은 사용 금지 |

자세한 layer 별 EULA 분석: [docs/design/12-render-extractor.md §1](docs/design/12-render-extractor.md#1-라이센스-안전-경계).

### Render 백엔드 옵션 (advanced)

대부분은 두 권장 모드 (`--pixel-only` 또는 `--full-reference`) 면 충분합니다. 세부 제어가 필요한 경우:

| 옵션 | 효과 |
|---|---|
| `--renderer [auto\|freetype\|browser]` | 렌더 엔진 선택. browser 는 가장 강한 EULA 방어선 (Chromium `@font-face` data: URL 로 적재). |
| `--render-size N` | 측정 정밀도 — 1000px (기본) → 1u 정확도. |
| `--workdir DIR` | 측정에 사용된 모든 PNG 를 DIR 에 dump. 디버그 / 검증용. |
| `--include-lsb` | per-glyph LSB 측정 추가 (Strict 모드에서 명시) |
| `--include-kerning` | HB pair shape 으로 페어 간격 측정 (휴리스틱 후보, CJK 에선 ~5% 만 잡음 — `--full-reference` 권장) |
| `--include-shaped` | 언어 컨텍스트별 advance 변화 |
| `--metadata-from FILE` | head/hhea/OS-2/post 분류 플래그 numeric copy (`--full-reference` 의 일부) |
| `--pair-list-from FILE` | 페어 후보 list numeric copy (`--full-reference` 의 일부) |
| `--unnamed-from FILE` | cmap 외 글리프 (notdef variants 등) 의 advance/LSB numeric copy (`--full-reference` 의 일부) |
| `--full-reference FILE` | 위 셋 + `--include-lsb --include-kerning --include-shaped` 자동 활성화. **Full 모드의 단일 옵션** |

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

### 실측 정확도 — NotoSansKR-Bold (전체 cmap, 24,853 글리프)

| 메트릭 | **Strict** (`--pixel-only --include-lsb`) | **Full** (`--full-reference`) |
|---|---:|---:|
| `font_loadable` | ✓ | ✓ |
| `glyph_coverage` | 100% | 100% |
| `advance_widths_match` | ~100% | **100%** (24853/24853) |
| `lsb_match` | ~99% | **99.94%** (24838/24853) |
| `kerning_match` | **0%** | **99.94%** (20985/20997) |
| `shaped_advance` | 0% | ~100% |
| `vertical_match` | 100% | 100% |
| `name_metadata` | (없음) | 100% |
| `global_metrics` | pixel-derivable 만 (cap/x-height 등) | 10/11 fields (head.flags 만 fontTools 자동 재계산) |

**분석 시간 (Full 모드)**: render extract 37분 + incremental Halfwidth 30초 + unnamed copy 0.5초.

> Strict 모드의 한계: NotoSansKR-Bold 의 GPOS PairPos 21K 페어 (한자-한자 클래스 페어 19.9K 포함) 를 모두 잡으려면 영역 B (`--full-reference`) 필요. Strict 모드는 그 정보를 포기하는 대신 EULA-strictest 영역에 머무릅니다.

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
