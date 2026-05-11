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
| `mcfg extract <font>` | 메트릭을 JSON 으로 추출 |
| `mcfg compare a b` | 두 폰트 / 스펙 비교 (text / json / html) |
| `mcfg generate --metrics … --design …` | 메트릭 + 디자인 폰트 → 새 폰트 |
| `mcfg validate <font> --against …` | 결과 폰트 검증 |

각 커맨드는 `--help` 로 자세한 옵션 확인.

## 폰트 라이센스에 따른 모드 선택

```bash
# ① 일반 OFL / 상용 폰트 — 빠르고 정확
mcfg extract source.ttf --include-lsb --include-kerning -o spec.json
# < 1초, 100% 정확

# ② EULA 가 outline 추출만 금지 — render 백엔드 + 보조 file 분석
mcfg extract source.ttf --backend render --full-reference source.ttf -o spec.json
# ~40분, ~100% 복원 (render 측정 + file 의 numeric 보조 정보)

# ③ EULA 가 모든 metric extraction 금지 — render 만
mcfg extract source.ttf --backend render --pixel-only --include-lsb -o spec.json
# ~40분, ~80% 복원 (kerning 손실, 픽셀 측정만)
```

폰트 EULA 가 어디까지 허용하는지에 따라 셋 중 선택. 자세한 EULA 분석, 모드 비교, 옵션 매트릭스: **[docs/design/12-render-extractor.md](docs/design/12-render-extractor.md)**.

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

## Render 백엔드 — incremental 업데이트

CJK 폰트 전체 cmap 측정은 ~40분. 작은 fix 마다 다시 돌리지 않도록 **이전 결과 spec 에 부분 업데이트**:

```bash
# 한 번만 전체 측정 (40분), 결과 spec 보존
mcfg extract source.ttf --backend render --full-reference source.ttf \
    -o ~/work/source.spec.json

# 이후 일부 영역만 재측정 (30초)
mcfg extract source.ttf --backend render \
    --update-spec ~/work/source.spec.json \
    --refresh-block "Halfwidth/Fullwidth Forms" \
    --full-reference source.ttf \
    -o ~/work/source.spec.json
```

자세히: [docs/design/12-render-extractor.md §6](docs/design/12-render-extractor.md#6-incremental-update).

## 마일스톤

| | 내용 | 상태 |
|---|------|------|
| M1 | 메트릭 추출기 + JSON 스키마 v1 | ✓ |
| M2 | 메트릭 비교기 (text/json) | ✓ |
| M3 | 폰트 생성기 (global + advance, scale-glyph) | ✓ |
| M4 | 검증기 (구조/메트릭/커버리지/name) | ✓ |
| M5 | 옵션 메트릭 (LSB, kerning, vertical) | ✓ |
| M6 | HTML 리포트 + HarfBuzz 렌더링 회귀 | ✓ |
| M7 | 패키징, 샘플, 문서 | ✓ |
| **M8** | **Render-based 추출기 (EULA-safe) + incremental update** | **✓** |

## 문서

- **[로드맵 / 지원 범위](ROADMAP.md)** — 공개 사용 전 반드시 확인.
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
