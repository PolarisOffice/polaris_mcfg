# Polaris MCFG — Roadmap

> 본 문서는 **현재 지원 범위(v0.2.3 시점)** 와 **향후 계획**을 정리합니다. 폰트 생태계는 컨테이너 포맷·outline 종류·OpenType 테이블·스크립트 등 차원이 많아, 모든 조합을 한꺼번에 다루지 않습니다. 의도적으로 다루지 않는 영역과 의도적으로 deferred한 영역을 분리해 명시합니다.

---

## 0. 한 줄 요약

**v0.2.3 코어 사용처**: TrueType outline (`glyf`) 기반의 라틴/한글/한자 폰트 페어. 입력은 TTF/OTF/WOFF/WOFF2, 디자인 폰트는 TTF만. 메트릭 + GPOS pair 커닝 + (opt-in) GSUB 단일 substitution 효과까지 이식. RTL/Indic·color/bitmap·CFF 디자인 폰트는 미지원 또는 부분 지원.

---

## 1. 지원 범위 매트릭스 (v0.2.3)

### 1.1 폰트 컨테이너

| 포맷 | 소스(extract) | 디자인(generate input) | 결과(generate output) | 비교(compare) | 검증(validate) |
|------|:-------------:|:---------------------:|:--------------------:|:-------------:|:--------------:|
| `.ttf` (TrueType) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.otf` (CFF) | ✅ (메트릭 테이블만) | ❌ (`glyf` 부재) | — | ✅ | ✅ |
| `.otf` (CFF2) | ⚠️ 미테스트 | ❌ | — | ⚠️ | ⚠️ |
| `.woff` | ✅ | ⚠️ 미테스트 | ❌ | ✅ | ✅ |
| `.woff2` | ✅ | ⚠️ 미테스트 | ✅ (`--match-upm` 시 자동 선택) | ✅ | ✅ |
| `.ttc` (Collection) | ❌ | ❌ | — | ❌ | ❌ |
| EOT | ❌ | ❌ | — | ❌ | ❌ |
| Variable (`fvar`) | ⚠️ default 인스턴스만 | ⚠️ default 인스턴스 | ⚠️ axis 정보 보존 안 됨 | ⚠️ | ⚠️ |
| AAT (Apple) | ❌ | ❌ | — | ❌ | ❌ |

### 1.2 Outline 형식

| Outline | 소스 추출 | 디자인 outline 사용 | scale-glyph 변형 |
|---------|:---------:|:------------------:|:----------------:|
| TrueType (`glyf` simple) | n/a (사용 안 함) | ✅ | ✅ |
| TrueType (`glyf` composite) | n/a | ✅ | ✅ (decompose됨) |
| CFF / Type 2 Charstrings | n/a | ❌ | ❌ |
| CFF2 / Variable Charstrings | n/a | ❌ | ❌ |
| COLRv0/v1 (color) | n/a | ❌ | ❌ |
| `sbix` / `CBDT` (bitmap) | n/a | ❌ | ❌ |
| SVG | n/a | ❌ | ❌ |

> `n/a`: 추출기는 outline 데이터를 일체 읽지 않으므로 outline 형식과 무관.

### 1.3 추출되는 메트릭 (extractor)

| 카테고리 | 테이블 | 기본 | 옵션 |
|---------|--------|:----:|:----:|
| Global | `head` (unitsPerEm, xMin/yMin/xMax/yMax, macStyle, flags) | ✅ | |
| Global | `hhea` (ascent, descent, lineGap, advanceWidthMax, …) | ✅ | |
| Global | `OS/2` (sTypoAsc/Desc/Gap, usWinAsc/Desc, sxHeight, sCapHeight, panose, fsSelection, ulUnicodeRange1-4, ulCodePageRange1-2) | ✅ | |
| Global | `post` (italicAngle, underline*, isFixedPitch) | ✅ | |
| Per-glyph | `hmtx` advance width | ✅ | |
| Per-glyph | `hmtx` LSB | | `--include-lsb` |
| Per-glyph | `vhea`/`vmtx` | | `--include-vertical` |
| Pair | classic `kern` (format 0) | | `--include-kerning` |
| Pair | GPOS PairPos (lookup type 2, format 1+2, Extension) | | `--include-kerning` |
| Shaped | per-(codepoint, script, lang) advance overrides via HarfBuzz | | `--include-gsub` |

### 1.4 GPOS / GSUB 처리 매트릭스

GPOS 처리 (생성 시 디자인 폰트 영향):

| Lookup type | 추출 | 적용 | 보존 (다른 lookup) |
|-------------|:----:|:----:|:------:|
| 1: Single adjustment | ❌ | ❌ | ✅ |
| 2: Pair (kerning) | ✅ format 1+2 | ✅ 새 lookup으로 교체 | n/a |
| 3: Cursive attachment | ❌ | ❌ | ✅ |
| 4: Mark-to-base | ❌ | ❌ | ✅ |
| 5: Mark-to-ligature | ❌ | ❌ | ✅ |
| 6: Mark-to-mark | ❌ | ❌ | ✅ |
| 7: Context positioning | ❌ | ❌ | ✅ |
| 8: Chained context | ❌ | ❌ | ✅ |
| 9: Extension (wraps 1-8) | ✅ type 2 unwrap | ✅ | ✅ |

GSUB 처리 (`--apply gsub` 시):

| Lookup type | 추출 (HarfBuzz 효과 측정) | 적용 (stub glyph + locl) | 보존 |
|-------------|:------------------------:|:------------------------:|:----:|
| 1: Single | ✅ | ✅ | locl만 strip, 나머지 보존 |
| 2: Multiple | 부분 (advance 합만) | ❌ (단일 substitution으로 표현 불가) | ✅ |
| 3: Alternate | ❌ (default만 사용) | ❌ | ✅ |
| 4: Ligature | ❌ (multi-codepoint 입력) | ❌ | ✅ |
| 5: Context | ❌ (multi-codepoint) | ❌ | ✅ |
| 6: Chained context | ❌ | ❌ | ✅ |
| 7: Extension | 효과만 캡처됨 | ❌ | ✅ |
| 8: Reverse chained | ❌ | ❌ | ✅ |

> **핵심 한계**: GSUB 추출은 **단일 codepoint 별 shape advance**만 측정합니다. ligature(여러 글자 → 하나)나 contextual substitution(주변 글자 영향) 같은 multi-glyph 효과는 캡처하지 못합니다.

### 1.5 검증된 스크립트 / 언어

| 스크립트 | 상태 | 비고 |
|----------|:----:|------|
| Latin (basic, extended-A) | ✅ 회귀 테스트 | |
| Hangul (precomposed syllables U+AC00-U+D7A3) | ✅ 회귀 테스트 + 데모 | |
| Hangul Jamo (U+1100-U+11FF) | ⚠️ 미테스트 | jamo composition GSUB 의존 |
| CJK Unified Ideographs (basic block) | ⚠️ 부분 테스트 | NotoSansKR로 cross-pollination 검증 |
| CJK Extension A-F | ❌ 미테스트 | |
| Cyrillic, Greek | ⚠️ 미테스트 | LTR 단순 스크립트라 동작 가능성 높음 |
| Arabic / Hebrew (RTL) | ❌ 미테스트 | bidi + 강한 contextual 의존 → 현재 GSUB 한계 노출 가능성 큼 |
| Indic (Devanagari, Bengali, Tamil, …) | ❌ 미테스트 | reordering + ligature 의존 → 현재 미지원으로 간주 |
| Thai / Lao / Khmer | ❌ 미테스트 | mark stacking 의존 |
| Emoji | ❌ 미지원 | color font 미지원과 동일 사유 |

### 1.6 파이프라인 동작

| 동작 | CLI | 입력 | 출력 |
|------|-----|------|------|
| extract | `mcfg extract` | 폰트 파일 | JSON (`MetricsSpec`) |
| compare | `mcfg compare` | 폰트 또는 JSON × 2 | text / json / html |
| generate | `mcfg generate` | JSON + 디자인 TTF | TTF 또는 WOFF2 |
| validate | `mcfg validate` | 폰트 + (JSON 또는 폰트) | text / json (exit 0/1) |

---

## 2. 알려진 한계 (워크어라운드 포함)

### L1. CFF/OTF 디자인 폰트 미지원
- **현상**: `mcfg generate --design font.otf`는 `UsageError` 발생.
- **원인**: outline 변형(scale-glyph fit/center)과 advance 적용이 `glyf` 테이블에 직접 의존. CFF는 Type 2 Charstring으로 다른 자료 구조.
- **워크어라운드**: 디자인 폰트를 fontmake/AFDKO로 TTF로 사전 변환.
- **로드맵**: 후술 (R3).

### L2. Variable font 부분 지원
- **현상**: 가변 폰트의 default 인스턴스에서 메트릭이 추출되며, 결과 폰트는 가변성을 잃지는 않으나 axis별 메트릭 보간은 처리되지 않음.
- **원인**: `fvar`/`gvar`/`HVAR`/`MVAR` 미처리.
- **워크어라운드**: 인스턴스화(`fonttools varLib.instancer`)된 정적 폰트를 입력으로 사용.
- **로드맵**: R5.

### L3. Multi-glyph GSUB 효과 미캡처
- **현상**: ligature(예: `f + i → ﬁ`), contextual alt, RTL contextual shaping 등 다중 글자 입력에 의한 advance/positioning 변화가 cross-pollination 결과 폰트에 반영되지 않음.
- **워크어라운드**: 텍스트가 라틴 ligature를 강제 활성화하지 않거나(`font-feature-settings: "liga" 0`), `--apply gsub` 미사용.
- **로드맵**: R4.

### L4. GPOS mark/cursive positioning 미이식
- **현상**: 디아크리틱(é, ñ, …), 아랍어 마크, 한글 옛한글 자모 결합 등의 mark positioning은 디자인 폰트의 GPOS를 그대로 사용 — 소스 폰트와 다른 결과 가능.
- **워크어라운드**: 라틴 기본 글자 위주의 텍스트라면 영향 무시 가능.
- **로드맵**: R6.

### L5. fontTools `scaleUpem` ↔ Chromium TTF sanitizer 충돌
- **현상**: NotoSansKR을 포함한 일부 큰 CJK 폰트를 `scale_upem`으로 rescale하면 Chromium이 TTF를 거부 (`NetworkError`). 동일 데이터의 WOFF2는 정상.
- **워크어라운드**: `--output-format auto` (rescale 시 자동 WOFF2 선택). 또는 `--no-match-upm`으로 ±0.5u rounding을 감수.
- **로드맵**: R7.

### L6. RTL / 복잡 스크립트 미테스트
- **현상**: Arabic/Hebrew/Devanagari 등은 회귀 테스트 없음. 동작 가능성 있으나 보장 안 됨.
- **워크어라운드**: 사용 전 `samples/visual_test`와 비슷한 시각 검증 직접 수행.
- **로드맵**: R2.

### L7. TTC (TrueType Collection) 미지원
- **현상**: `.ttc` 입력 시 fontTools가 첫 서브폰트만 로드, 사용자가 명시적으로 인덱스 지정 불가.
- **워크어라운드**: `fonttools ttCollection extract`로 사전에 분리.
- **로드맵**: R8.

### L8. AAT/Graphite 미지원
- **현상**: macOS/Apple-specific tables (`morx`, `mort`, `kerx`, `lcar`) 와 SIL Graphite (`Silf`, `Glat`) 미처리.
- **로드맵**: 의도적 out-of-scope (§4.A 참고).

### L9. 색상/비트맵 폰트 미지원
- **현상**: `COLR/CPAL`, `sbix`, `CBDT/CBLC`, `SVG` 글리프 무시.
- **로드맵**: 의도적 out-of-scope (§4.B).

### L10. 라이센스 회색지대
- **현상**: GPOS 페어와 GSUB 룩업 효과는 디자이너 의도가 반영된 데이터로, "메트릭만 추출"이라는 정책의 경계에 있음. 보수적 사용자에게는 `--include-kerning` / `--include-gsub` 옵트인이 안전 장치.
- **사용자 책임**: 소스 폰트 EULA의 메트릭/룩업 추출 허용 여부를 별도 검토.

---

## 3. 로드맵

우선순위 = **사용자 영향** × (1 / **구현 난이도**). 마일스톤은 임시이며 PR/이슈 따라 조정.

### v0.3 — 가까운 우선순위 (다음 1~2 릴리즈)

| ID | 항목 | 영향 | 난이도 |
|----|------|------|--------|
| **R1** | 기본 스크립트 별 회귀 테스트 (Cyrillic, Greek, 추가 CJK) | 보장 범위 명확화 | 소 |
| **R2** | RTL 스크립트 first-pass 지원 (Arabic/Hebrew). 메트릭은 동작 검증, 복잡 shaping은 한계 명시 | 사용자 폭 확대 | 중 |
| **R7** | `scale_upem` Chromium 호환성 추적 — fontTools 또는 OTS 업스트림 이슈 작성, 가능 시 우회 patch | TTF 출력 사용성 | 중 |
| **R8** | TTC 입력 지원 (`--ttc-index`) | 일반 시스템 폰트 진입 장벽 | 소 |
| **R-ux1** | CLI 진단 모드 (`mcfg doctor <font>`) — 어떤 lookup이 들어있고 본 도구가 무엇을 다룰 수 있는지 한눈에 보고 | 신규 사용자 온보딩 | 소 |
| **R-render** | Render-based extractor (M8): EULA가 file parsing을 금지한 폰트를 위해, 폰트를 정상 렌더링한 결과 이미지에서 메트릭을 측정해 복원. FreeType / 브라우저 백엔드. 정확도 ±1~2 unit. → [docs/design/12-render-extractor.md](docs/design/12-render-extractor.md) | 라이센스 회피 우회로 확보 | 중-상 |

### v0.4 — 중기 (3~6개월)

| ID | 항목 | 영향 | 난이도 |
|----|------|------|--------|
| **R3** | CFF 디자인 폰트 지원 — `fontTools.subset.cff` 의 charstring 변형 활용해 advance/scale 적용 | 디자인 폰트 선택지 대폭 확대 | 중-상 |
| **R4** | GSUB 단일 substitution을 multi-glyph 컨텍스트(ligature 등)까지 확장. HarfBuzz 측정을 코드포인트 시퀀스(2-3-gram)로 확장 후 contextual rule 합성 | 라틴 ligature, 한글 옛한글 jamo | 상 |
| **R6** | GPOS mark positioning 이식 (lookup type 4/5/6). 디아크리틱이 많은 라틴 + 아랍어 시 필수 | 비-라틴 정확도 | 상 |
| **R9** | 가변 폰트 first-class 지원 — 입력 시 인스턴스 선택, 출력 시 axis 보존 또는 명시적 instantiation | 모던 폰트 대응 | 중-상 |

### v1.0 — 장기

| ID | 항목 | 영향 | 난이도 |
|----|------|------|--------|
| **R10** | Indic 스크립트 (reordering, conjunct ligature) 지원 또는 명시적 권고 | 글로벌 사용 | 매우 상 |
| **R11** | 결과 폰트의 OTS 자체 검증 (사용자 환경 의존성 제거) | CI 신뢰성 | 중 |
| **R12** | GUI / 웹 빌더 — 비-CLI 사용자 대상 | 진입 장벽 ↓ | 중 |
| **R13** | OFL/EULA 자동 메타데이터 합성 (디자인 폰트 라이센스 인식 → 결과 폰트 `name` 테이블 자동 충전 + 라이센스 충돌 경고) | 라이센스 휴먼 에러 ↓ | 소-중 |
| **R-ux2** | 결정적 빌드 매니페스트 (`mcfg.lock` 같은 파일) — 입력 SHA256 + 옵션 + 결과 SHA256 기록 | 재현성 / 감사 | 소 |

### 데이터 / 인프라

현재 활성화된 인프라 (§1 매트릭스에 반영됨):

- **CI**: `.github/workflows/ci.yml` — push/PR마다 Linux × macOS × Windows × Python 3.10/3.11/3.12/3.13 매트릭스로 `pytest` + CLI smoke test, sdist/wheel 빌드 검증.

> **PyPI 배포는 의도적으로 로드맵에서 제외**합니다. 본 도구는 git 체크아웃 + `pip install -e .` 워크플로우만 지원하며, 그 결정은 다음 사유에 기반합니다:
> - 폰트 라이센스 / 메트릭 추출 정책 검토가 사용자별로 필수 — `pip install` 한 줄로 무분별하게 보급되는 것은 본 도구의 사용 의도와 맞지 않음
> - 사용자 워크플로우가 보통 1회성 또는 프로젝트별 단발성이라 글로벌 패키지 매니저 등록의 가치가 작음
> - 결과 폰트의 라이센스/EULA 책임을 사용자가 명시적으로 인지하도록, 진입 장벽을 의도적으로 git 체크아웃 수준으로 둠
>
> **성능 벤치마크(R-bench)도 의도적으로 제외**합니다. 본 도구는 1회성 배치 워크플로우(extract → 끝, generate → 끝)이고 fontTools 위에 얇게 얹혀 있어 자체 성능 회귀 가능성이 작습니다. baseline 유지 비용 대비 가치가 낮다고 판단했습니다.

---

## 4. 명시적으로 out-of-scope

### 4.A AAT / Graphite 전용 기능
Apple 고유 (`morx`/`kerx`/`lcar` 등) 및 SIL Graphite (`Silf`/`Glat`)는 OpenType 표준 밖. 본 도구의 추상화는 OpenType 기준이므로, 이들 테이블에 의존하는 layout 행동은 다루지 않습니다.

### 4.B 색상/비트맵 글리프
`COLR/CPAL`, `sbix`, `CBDT/CBLC`, SVG 글리프는 outline이 아니거나 outline 외 추가 데이터가 큰 비중. cross-pollination에서 시각적 외형의 일관성 자체가 정의되지 않으므로 다루지 않습니다.

### 4.C 글리프 외형(outline) 추출
**영구 out-of-scope.** 본 도구의 라이센스 안전성 보장의 핵심은 "outline 데이터를 절대 추출/복제하지 않는다"입니다. 이 정책을 깰 기능은 추가하지 않습니다 ([Requirements.md §6](Requirements.md), [docs/design/02-metrics-schema.md](docs/design/02-metrics-schema.md) 참고).

### 4.D 모든 가능한 (script, language) 조합 자동 추출
`--include-gsub` 의 기본 컨텍스트는 한·중·일·라틴. 모든 ISO-639 / OpenType 스크립트 태그 매트릭스를 자동 probe하지 않습니다 (시간 비용). 사용자가 `gsub_contexts`로 직접 지정 가능.

### 4.E GUI 우선 워크플로우
v1.0 후보(R12)는 부가 기능이지, CLI를 대체하지 않습니다. 도구의 본질은 자동화/CI에 친화적인 CLI.

---

## 5. 우선순위 결정 원칙

다음 사용자 시나리오 순서로 가치가 정렬되어 있습니다:

1. **한국어 문서의 한컴-호환 자유 라이센스 폰트 생성** (현재 ✅)
2. **라틴 + CJK 혼합 텍스트의 줄바꿈 보존** (현재 ✅, 일부 GSUB 한계 R4)
3. **CJK 외 동아시아 (일본어 가나, 중국어 GB/big5) 보존** (현재 부분 ✅)
4. **Latin 위주 사용자가 Adobe 등 상용 폰트 메트릭 호환을 위해 사용** (R3 — CFF 디자인 폰트 지원이 관건)
5. **Arabic/Hebrew RTL 문서 레이아웃 보존** (R2 + R6 + R10 합산)

새 이슈/PR이 생기면 위 우선순위 매트릭스를 기준으로 재배치합니다.

---

## 6. 기여 가이드 (간략)

- 신규 스크립트 지원은 **회귀 테스트** + **샘플 페이지 시각 검증**이 함께 와야 합니다 (samples/visual_test 스타일).
- 새로운 OpenType 테이블 추출 시 [§라이센스 안전 경계](docs/design/02-metrics-schema.md#라이센스-안전-경계) 점검:
  - outline / glyph design 데이터를 노출하지 않는가?
  - 디자이너 의도가 강하게 반영된 데이터(예: contextual GSUB)는 opt-in 플래그로 분리.
- 회귀 테스트 위치: `tests/test_*.py`. 새 동작은 `tests/test_review_fixes.py` 패턴(목적 + 가드 코멘트)을 따릅니다.
- 설계 결정은 `docs/design/<NN>-<topic>.md` 에 기록 후 PR.

---

## 부록 A — 변경 이력 추적

본 ROADMAP은 살아있는 문서로, 마일스톤 진척에 따라 갱신됩니다. v0.3.0 cut 시점에 §3 v0.3 항목들을 §1 지원 매트릭스로 이동하고, 새 항목들을 §3에 추가합니다.

직전 갱신: v0.2.3 시점.
