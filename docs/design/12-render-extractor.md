# 12. Render-based Extractor (M8)

> **상태**: v0.3.4 출시 완료.
> **선행 문서**: [01. 아키텍처](01-architecture.md), [03. 추출기](03-extractor.md).
>
> **TL;DR**: file 백엔드(`fontTools`로 테이블 직접 파싱) 외에 두 가지 추가
> 모드 — Strict (render 만, EULA-strictest) 와 Full (render + file 의
> numeric 보조, hybrid).

## 0. 목표

EULA가 file parsing("metric extraction" / "reverse engineering")을 명시
금지한 폰트에 대해, 폰트를 정상 사용(렌더링)한 결과 이미지에서 메트릭을
복원하는 **2차 백엔드**. 기존 file 백엔드와 동일한 `MetricsSpec` 을 출력한다.

> **비목표**: file 백엔드를 대체하지 않는다. file 백엔드가 EULA 상 가능하면
> 그쪽이 항상 우월하다 (정확도, 속도, 컨텍스트 룩업 복원). render 백엔드는
> 회피 수단.

## 사용 모드 요약

```bash
# Strict — EULA 가 모든 metric extraction 금지
mcfg extract source.ttf --backend render --pixel-only --include-lsb \
     -o spec.json
# 영역 A 만. ~80% 복원 (advance + LSB + vertical + italic + underline).
# kerning / shaped advance / unnamed glyph 미복원.

# Full — EULA 가 outline 만 금지 (대부분의 케이스)
mcfg extract source.ttf --backend render --full-reference source.ttf \
     -o spec.json
# 영역 A + B 의 일부. ~100% 복원.
# --full-reference 가 metadata-from, pair-list-from, unnamed-from,
# include-lsb, include-kerning, include-shaped 자동 활성화.

# 비교: file 백엔드 — 일반 OFL/상용 폰트
mcfg extract source.ttf --include-lsb --include-kerning -o spec.json
# < 1초, 100% 정수 정확.
```

## 1. 라이센스 안전 경계

### 1.1 두 영역의 결정적 차이

폰트에 대한 행위는 **정상 rendering 의 출력 사용** vs **internal table 의
직접 분석** 두 영역으로 정확히 나뉜다. 이 분리가 EULA 해석의 핵심이다.

```
영역 A — 정상 rendering 의 출력 사용                 영역 B — internal table 의 직접 분석
─────────────────────────────────────                ─────────────────────────────────────

  Pixel 측정              HB shape                    file backend         pair-list / unnamed / metadata
  (FreeType /            (HarfBuzz                     (fontTools)         (fontTools 부분 사용)
   Chromium 결과)          numeric)                         │                       │
       │                       │                            ▼                       ▼
       ▼                       ▼                       table 전체 분석          internal lookup
   화면에 보이는           shaper 가 사용자             모든 메트릭값            데이터 enumerate
   결과 측정              에게 주는 결과                직접 추출               (rendering 시
       │                       │                           │                  노출 안 됨)
       └─────── 등가 정보 ─────┘
                                                            └──────── 둘 다 reverse engineering ────┘
       (시각적 텍스트의                                       (rendering 결과가 아닌
        positioning 정보)                                      internal data 직접 access)
```

| 영역 | 행위 | EULA 위치 |
|---|---|---|
| **A** | Pixel 측정 (FreeType/Chromium 렌더 결과 자로 측정) | "사용자가 화면 자로 측정" 과 동등. EULA 안전 |
| **A** | HarfBuzz shape() 결과 (positioning numeric) | **Chrome, Firefox, Safari, Android, iOS, Office 가 매일 호출**. 정상 rendering 의 일부 |
| **B** | `--pair-list-from FILE` 페어 tuple list | 폰트의 `kern` + `GPOS PairPos` internal lookup 추출. **rendering 시 노출되지 않음** — reverse engineering |
| **B** | `--metadata-from FILE` 분류 플래그 | `head/hhea/OS-2/post` enum 직접 read. 분류 정보의 직접 추출 |
| **B** | `--unnamed-from FILE` cmap 외 글리프 메트릭 | `hmtx` 의 unnamed 행 직접 read. 가장 명백한 metric 추출 |
| **B** | `--backend file` 전체 table parsing | 모든 영역 B 행위의 합 |

### 1.2 영역 A 가 안전한 이유

영역 A 의 두 layer (픽셀, HB shape) 는 **시각적 텍스트의 등가 정보**:

- "AV" 라는 페어를 영역 A 의 두 방법으로 측정하면:
  - **픽셀**: 브라우저 렌더 결과에서 V 의 시작 좌표 = 50px 위치
  - **HB shape**: `positions[0].x_advance + positions[1].x_offset` = 50u
  - → 둘 다 "kerning 적용된 후의 positioning" 정보
  - → 시각적으로 본 결과를 numeric 으로 받느냐 픽셀로 보느냐 차이

영역 A 는 모든 OS/브라우저가 매일 호출하는 표준 rendering. EULA 가 영역 A
를 금지하면 폰트 자체를 사용 불가능.

### 1.3 영역 B 가 reverse engineering 인 이유

폰트 작가가 `GPOS PairPos lookup` 에 `(A, V) → -50u, (T, o) → -80u, ...`
같은 페어 list 를 정의했을 때, 일반 사용자가 폰트를 사용하는 동안 그
**list 자체** 는 절대 노출되지 않는다:

- HB 가 lookup 으로 사용해 결과 positioning 만 출력
- 픽셀에 적용된 효과 만 표시
- 사용자는 어떤 페어가 정의되어 있는지 모름

**페어 list 를 얻는 방법**:

| 방법 | 비용 | 평가 |
|---|---|---|
| `fontTools` 로 GPOS table 직접 파싱 | ~10ms | 명백한 reverse engineering |
| Brute-force: cmap × cmap 모든 페어 HB shape, 0 아닌 것만 keep | N² × ~1ms ≈ ~수개월 (24K 글리프 폰트) | 시간상 비현실적 |

페어 list 는 폰트의 **internal lookup 데이터**로, "표준 rendering 의
출력" 이 아닌 "폰트 작가의 내부 결정" 영역이다. 이걸 추출하는 행위는
명백히 영역 B (reverse engineering).

### 1.4 두 가지 운영 모드 — Strict 와 Full

영역 A 안에서 휴리스틱 단독은 CJK 폰트에서 ~5% kerning 만 복원하므로 (§1.4.2 실측), **운영상 의미 있는 모드는 두 개뿐**:

```bash
# Strict — 영역 A 만, EULA-strictest
mcfg extract source.ttf --backend render --pixel-only --include-lsb \
     -o spec.json

# Full — 영역 A + B, 100% 복원
mcfg extract source.ttf --backend render --full-reference source.ttf \
     -o spec.json
```

`--full-reference FILE` 는 다음을 한 번에 활성화:
- `--metadata-from FILE` (head/hhea/OS-2/post 분류 플래그)
- `--pair-list-from FILE` (폰트의 internal pair list)
- `--unnamed-from FILE` (cmap 외 글리프 metric)
- `--include-lsb` / `--include-kerning` / `--include-shaped` (자동 켜짐)

| 모드 | Pair 후보 출처 | Pair 값 측정 방법 | 영역 | CJK kerning | Latin kerning |
|---|---|---|---|---:|---:|
| `--pixel-only` | (시도 안 함) | (불가) | A 만 | 0% | 0% |
| **`--full-reference FILE`** | **file 의 internal lookup** | HB shape | A + B | **~100%** | **~100%** |
| (수동 조합) `--include-kerning` 만 | 하드코딩 휴리스틱 | HB shape | A 만 | ~5% | 70-95% |
| (수동 조합) `--include-kerning --pair-list-from` | file | HB shape | A + B | ~100% | ~100% |
| `--backend file` | 전체 file parsing | 전체 file parsing | B | 100% | 100% |

> **왜 휴리스틱 단독 (`--include-kerning` 만) 은 권장하지 않는가**:
> - NotoSansKR 21K 페어 중 ASCII × ASCII 영역이 1K (5%). 나머지 19.9K (한자-한자 클래스, Cyrillic 등) 누락.
> - 외부 페어 list 를 받아도 — 그 list 도 결국 누군가의 file 분석 결과. 실질적으로 영역 B 정보.
> - 그래서 의미 있는 선택은 "kerning 포기 (Strict)" 또는 "영역 B 포함 (Full)" 둘 뿐.

> **결정적 통찰**:
> - "페어 list 를 폰트에서 읽음" = `--pair-list-from` (또는 `--full-reference`) 일 때만 (영역 B)
> - "HB shape 호출" = 영역 A 의 kerning 측정 메커니즘 (Strict 가 아닐 때)
> - 두 행위는 독립적이지만 CJK 폰트에서 영역 A 단독 의미 없음.

### 1.5 Full 모드는 hybrid 라는 점 정직하게

`--full-reference SOURCE` 는 **render 측정 + file 분석의 hybrid**.

| 메트릭 | 출처 |
|---|---|
| advance value | render 측정 |
| LSB value (cmap glyph) | render 측정 |
| vertical metrics | render 측정 + metadata override |
| kerning value | HB shape (rendering pipeline) |
| shaped advance value | HB shape |
| pair list (어떤 페어가 있는지) | **file 분석** (영역 B) |
| metadata flags (italicAngle 등) | **file 분석** (영역 B) |
| unnamed glyph metric | **file 분석** (영역 B) |

| | `--backend file` | Full mode (`--full-reference`) |
|---|---|---|
| 측정값 자체 | hmtx / GPOS 직접 read | **render 측정** |
| enumeration / 분류 / unnamed | 직접 read | file 분석 (영역 B) |
| **글리프 outline (`glyf`/`CFF`)** | ❌ never | ❌ never |
| 시간 | < 1초 | ~40분 |

Full 모드의 진짜 가치:
1. **outline 절대 미접근** — 가장 명백한 reverse engineering 회피
2. **자기 검증** — render 측정값이 file 의 값과 일치하는지 확인 (정확도 보장)

**EULA 가 metric extraction 자체를 명시 금지하는 폰트**라면 Full 모드도 위반 — `--pair-list-from`, `--metadata-from`, `--unnamed-from` 모두 file 분석. 그럴 땐 **Strict 만 사용** (영역 A 만, kerning 포기).

### 1.6 결론 — 두 가지 운영 모드

영역 A 안에서 휴리스틱 단독은 CJK 폰트에서 ~5% kerning 만 복원하므로 (§1.4.2 실측), **운영상 의미 있는 모드는 두 개뿐**:

```bash
# Strict — 영역 A 만, EULA-strictest
mcfg extract source.ttf --backend render --pixel-only --include-lsb \
     -o spec.json

# Full — 영역 A + B, 100% 복원
mcfg extract source.ttf --backend render --full-reference source.ttf \
     -o spec.json
```

| | **Strict** | **Full** |
|---|---|---|
| 영역 | A 만 | A + B (hybrid) |
| advance / LSB / vertical | ~100% | ~100% |
| kerning | **0** | **~100%** |
| shaped advance | 0 | ~100% |
| unnamed glyph metric | 0 | ~100% |
| 메타데이터 분류 플래그 | pixel-derivable 만 | ~100% |
| EULA 권장 폰트 | metric extraction 명시 금지 | outline 만 금지 |

### 1.4.1 기본 모드의 정확한 동작

```python
# 기본 모드에서 kerning=True 일 때 (`extract_via_render` 호출 흐름):

# 1. 후보 enumeration (영역 A — 우리 코드의 휴리스틱)
ASCII = list(range(0x21, 0x7F))           # 하드코딩
KOREAN_PUNCT = [0x3001, 0x3002, ...]       # 하드코딩
candidates = (
    ASCII × ASCII +                         # 8,836 후보
    ASCII × KOREAN_PUNCT +                  # 1,410
    KOREAN_PUNCT × ASCII                    # 1,410
)                                          # 합 ~11,656

# 2. 각 후보의 값 측정 (영역 A — HB shape)
for (l, r) in candidates:
    shaped = hb.shape([l, r], font)         # HB 내부에서 GPOS lookup
    kern = sum(shaped.x_advance) - (adv_l + adv_r)
    if abs(kern) >= threshold:
        keep
```

- 1단계의 후보 list 는 폰트와 무관한 휴리스틱
- 2단계의 HB shape 는 폰트 file 을 *내부적으로* 읽지만 우리에게는 **rendering 결과** (positioning numeric) 만 줌
- 폰트의 internal pair list (어떤 페어가 정의되어 있는지) 는 **우리 코드가 알 길 없음** — 그저 우리 휴리스틱 후보가 폰트에 정의된 페어와 우연히 겹치면 0 이 아닌 값이 나옴

### 1.4.2 휴리스틱의 한계 — CJK 폰트에선 거의 무용

실측 (`fonts/` 디렉토리의 샘플들):

| 폰트 | 폰트의 전체 페어 | 휴리스틱 ∩ 폰트 페어 | 휴리스틱 coverage |
|---|---:|---:|---:|
| NotoSansKR-Bold | 20,997 | 1,038 | **5.0%** |
| NotoSansKR-Regular | 20,948 | 1,036 | 5.0% |
| Pretendard-Regular | 402,119 | 1,071 | **0.3%** |
| Pretendard-Bold | 403,019 | 1,073 | 0.3% |

해석:
- **NotoSansKR**: 21K 페어 중 휴리스틱이 1K (5%) 만 겹침. 나머지 19.9K 는 한자-한자 클래스 페어, Hangul-Latin 크로스 페어, Cyrillic 페어 — **휴리스틱이 가정한 ASCII 영역 밖**.
- **Pretendard**: GPOS PairPos format 2 (class kerning) 가 ~400K 페어로 expand 됨. 휴리스틱 0.3% 만 겹침.
- **일반 라틴 폰트**: 페어 거의 다 ASCII × ASCII → 휴리스틱이 70~95% 잡음.

따라서:
- 휴리스틱 (영역 A) 단독은 **라틴 본문 폰트에서만 의미 있는 결과**.
- CJK 폰트의 kerning 을 제대로 복원하려면 `--pair-list-from FILE` (영역 B) **사실상 필수**.

만약 EULA 가 영역 B 를 금지하는 폰트라면, kerning 복원을 포기하거나, 사용자가 직접 cmap × cmap brute-force 의 일부를 시도해야 함 (시간상 비현실적 — 24K 글리프 폰트면 ~수개월).

### 1.5 행위별 매트릭스

| 행위 | file backend | render 기본 | render `--pixel-only` |
|---|:---:|:---:|:---:|
| 폰트 테이블 직접 파싱 (fontTools) | ✅ 전체 | ❌ (cmap-table read 만) | ❌ (cmap-table read 만) |
| 글리프 outline 좌표 추출 | ❌ never | ❌ never | ❌ never |
| 픽셀 측정 (영역 A) | n/a | ✅ | ✅ |
| HarfBuzz shape() (영역 A) | n/a | ✅ | ❌ |
| **페어 list 추출 (영역 B)** | ✅ | opt-in (`--pair-list-from`) | ❌ |
| **메타데이터 flag 추출 (영역 B)** | ✅ | opt-in (`--metadata-from`) | ❌ |
| **Unnamed glyph metric 추출 (영역 B)** | ✅ | opt-in (`--unnamed-from`) | ❌ |
| OS 텍스트 API 호출 | n/a | (browser 백엔드만) | ✅ |
| `@font-face` 로 브라우저 적재 | n/a | (browser 백엔드만) | ✅ |

> **참고 — cmap-table read**: `_enumerate_cmap_from_font()` 는 cmap table
> 만 fontTools 로 읽어 "어떤 codepoint 가 폰트에 있는가" 를 알아낸다.
> cmap 은 "지원 목록" 으로, 메트릭 정보가 아니며 일반적으로 EULA 가 이걸
> 금지하지 않는다 (예: 도서관 분류번호와 책 내용의 관계). 그래도
> 회피하려면 사용자가 `--cmap` 으로 codepoint 직접 명시 (현재 API 지원).

### 1.6 권장 선택 가이드

- **OFL / 일반 상용 폰트** (대부분): 기본 모드 (HB shape 까지). 또는
  `--backend file` 으로 빠르게 (수십 ms).
- **EULA 가 "metric extraction" / "reverse engineering" 명시 금지 폰트**
  (일부 한컴 폰트, 사내 전용 폰트): `--pixel-only` 또는 기본 (HB shape
  까지). **영역 B 옵션 (`--pair-list-from`, `--unnamed-from`,
  `--metadata-from`, `--backend file`) 은 사용 금지**.
- **EULA 가 모든 reverse engineering 을 절대 금지**: 더 엄격하게는
  사용자가 `--cmap` 으로 codepoint list 까지 직접 명시 → fontTools 호출
  완전 회피. 이 모드에서는 모든 정보가 영역 A (pixel + HB shape) 만에서
  나오므로 EULA-perfect.

## 2. 아키텍처

```
mcfg extract <font> --backend render [--renderer ...] [...]
                          │
                          ▼
   ┌─ render_extractor/ ─────────────────────────────────────┐
   │  Orchestrator (orchestrator.py)                          │
   │     ↓ "이런 글리프/페어를 이 크기로 그려달라"            │
   │  RenderBackend (backends/base.py)                        │
   │     ↓ pixel buffer                                       │
   │  ImageAnalyzer (analyzer.py)                             │
   │     ↓ glyph bbox, baseline, advance (in px)              │
   │  UnitConverter (units.py)                                │
   │     ↓ pixel → font unit                                  │
   │  SpecAssembler (assembler.py)                            │
   │     ↓ MetricsSpec                                        │
   └──────────────────────────────────────────────────────────┘
```

### 백엔드 매트릭스

| 백엔드 | EULA 회피 강도 | 정확도 | 의존성 | 상태 |
|---|:---:|:---:|---|:---:|
| `freetype` | 약 (FT가 파일을 파싱) | 최고 | `freetype-py` | P1~P4 1차 |
| `browser` | **강** | 중-상 | `playwright` | P5 |
| `coretext` (macOS) | 강 | 높음 | OS 종속 | 후순위 |
| `directwrite` (Win) | 강 | 높음 | OS 종속 | 후순위 |

기본 동작: `--renderer` 미지정 시 환경에 따라 best-effort 선택
(`freetype` 우선, 없으면 `browser`). EULA 회피 명시 사용은 `--renderer
browser` 강제 권장.

## 3. 메트릭별 측정 절차

### 3.1 Vertical metrics (1장 렌더링)

`"HxgjQ"` 2줄을 알려진 폰트 사이즈로 렌더. baseline 간격에서
`ascent + descent + lineGap` 산출, `H` top → capHeight, `x` top → xHeight,
`g`/`j` 의 아래쪽 픽셀까지 → descent.

### 3.2 Per-glyph advance + LSB + BBox

각 글리프를 `"AAAA"` 4반복 패턴으로 한 줄에 단독 렌더. 같은 글리프 4개의
시작 x 좌표를 linear-fit 하여 advance 추정 (±0.25 px 정확도).

```
A  A  A  A          ← 줄 1: glyph "A"
B  B  B  B          ← 줄 2: glyph "B"
...
```

LSB = (글리프 첫 픽셀 x) − (셀 시작 x). BBox = 글리프 픽셀의 min/max 합집합.

### 3.3 Hangul monospace 자동 감지

`"가"`, `"뷁"`, `"이"`, `"왈"` 4자 advance 측정 → 모두 같으면 한글
monospace 가정 → 1자만 측정하고 11,172 음절 모두 같은 값으로 복제.
→ **렌더링 95% 절감.**

### 3.4 Kerning pairs (페어 후보 enumeration)

| 페어 카테고리 | 페어 수 | 측정 가치 |
|---|---:|---|
| ASCII × ASCII (95×95) | 9,025 | 필수 |
| ASCII × 한글 대표음절 (95×100) | 9,500 | 필수 |
| 한글 × ASCII (구두점 30자) (11,172×30) | 335,160 | 클래스 압축으로 1/10 |
| 한글 × 한글 | 0 | skip (monospace 가정) |

페어당 `"AB"` 렌더링:
- B 시작 x − A 시작 x − advance(A) = kerning value
- `|value| < threshold` 면 0 으로 간주 (잡음 제거, 기본 threshold = 2 unit)
- 잔존 sparse 페어만 저장

### 3.5 Shaped advance (브라우저 백엔드 전용)

같은 글자를 `<span lang="ko">`, `<span lang="ja">`, `<span lang="en">` 으로
각각 렌더. advance 가 다르면 `shapedAdvances` 에 `(codepoint, script,
language, advance)` 로 기록.

### 3.6 보조 메트릭

| 항목 | 측정법 |
|---|---|
| italicAngle | `I` 양쪽 edge slope 측정 |
| underlinePosition / Thickness | `<u>HHHHH</u>` 의 밑줄 픽셀 y / 두께 |
| BBox 전역 | 모든 글리프 픽셀의 min/max 합집합 |
| UPM 추론 | 메타데이터 없으면 capHeight × 1.33 휴리스틱 |

## 4. 정확도 확보

| 기법 | 효과 |
|---|---|
| 1000pt 렌더 (1 unit ≈ 1 px) | 양자화 잡음 제거 |
| 힌팅/그리드피팅 OFF | 정수 그리드 스냅 제거 |
| subpixel AA OFF (alpha only) | RGB 분리 잡음 제거 |
| Edge centroid (sub-pixel) | ±0.1 px 정확도 |
| 4-반복 linear-fit | 페어 비교 ±0.25 px |

**목표 정확도** (1000 UPM 기준):
- per-glyph advance: ±1 unit
- kerning pair: ±2 unit
- vertical metrics: ±2 unit

## 5. CLI

### 5.1 전체 옵션 매트릭스

| 옵션 | 효과 |
|---|---|
| `--backend [file\|render]` | 기본 `file`. EULA 회피 시 `render` |
| `--renderer [auto\|freetype\|browser]` | render 엔진. browser 가 가장 강한 EULA 방어선 (Chromium `@font-face` data: URL 적재) |
| `--render-size N` | 측정 정밀도 — 1000px 기본 → 1u 정확도 |
| `--workdir DIR` | 측정에 사용된 모든 PNG 를 DIR 에 dump (디버그/검증) |
| `--detect-monospace / --no-detect-monospace` | Hangul/한자 monospace fast-path 자동 감지 (기본 ON) |
| `--include-lsb` | per-glyph LSB 측정 |
| `--include-kerning` | HB pair shape 으로 페어 간격 측정 (단독으로는 휴리스틱 후보, CJK 에선 ~5% 만 잡음) |
| `--include-shaped` | 언어 컨텍스트별 advance 변화 |
| `--metadata-from FILE` | head/hhea/OS-2/post 분류 플래그 numeric copy (영역 B) |
| `--pair-list-from FILE` | 페어 후보 list numeric copy — 값은 HB shape 가 측정 (영역 B) |
| `--unnamed-from FILE` | cmap 외 글리프 의 advance/LSB numeric copy (영역 B) |
| `--full-reference FILE` | 위 셋 + `--include-lsb` / `--include-kerning` / `--include-shaped` 모두 활성화. **Full 모드의 단일 옵션** |
| `--pixel-only` | HB shape + 모든 reference 옵션 force-disable. **Strict 모드** |
| `--update-spec FILE` | incremental: base spec 위에 머지 (§6) |
| `--refresh-cmap CPS` | incremental 시 재측정할 codepoint (e.g. "0xAC00-0xD7A3") |
| `--refresh-block NAME` | incremental 시 재측정할 monospace block (repeatable) |

## 6. Incremental update

CJK 폰트 전체 cmap 측정은 ~40분. 작은 fix 마다 다시 돌리지 않도록 spec 위에 부분 머지:

```bash
# 최초 전체 측정 (한 번만, ~40분)
mcfg extract source.ttf --backend render --full-reference source.ttf \
    -o ~/work/source.spec.json

# 이후 부분 업데이트 (수초~수십초)
mcfg extract source.ttf --backend render \
    --update-spec ~/work/source.spec.json \
    --refresh-block "Halfwidth/Fullwidth Forms" \
    --full-reference source.ttf \
    -o ~/work/source.spec.json   # 같은 파일 덮어쓰면 누적
```

Merge precedence: overlay 가 모든 entry 에서 base 를 이김. base 의 그 외 entry 는 그대로 유지. `spec.source.updateHistory` 에 timestamp + 오버레이 통계 자동 기록.

### 6.1 Monospace block fast-path (자동)

다음 블록이 monospace 면 4-probe 측정 후 블록 전체에 복제 (영역 A 안의 최적화, file 안 봄):

| 블록 | 범위 | NotoSansKR-Bold |
|---|---|---:|
| Hangul Syllables | U+AC00..U+D7A3 | 11,172 |
| CJK Unified Ideographs | U+4E00..U+9FFF | 7,867 |
| CJK Compatibility Ideographs | U+F900..U+FAFF | 510 |
| Halfwidth/Fullwidth Forms | U+FF00..U+FFEF | 170 |

24K 글리프 advance probe → 약 16 probe 로 99.9%+ 절감.

LSB 는 음절마다 다르므로 fast-path 가 advance 만 복제하고 LSB 는 글자 단위 single-render.

## 7. CLI / 코드 통합 지점

- `cli.py`: `extract_cmd` 에 `--backend render|file` 추가 (기본 `file`).
- `extractor.py`: `extract_metrics(...)` 가 `backend="render"` 분기로
  `render_extractor.extract_via_render(...)` 호출.
- `render_extractor/__init__.py`: `extract_via_render()` 진입점.
- `render_extractor/incremental.py`: `merge_specs`, `load_spec`, `expand_refresh_set`.
- `render_extractor/reference.py`: `load_metadata_flags`, `load_pair_list`, `load_unnamed_glyph_metrics`.

## 8. 정확도 검증 전략

### Ground-truth diff
- ground truth = 동일 폰트에 대한 `--backend file` 결과
- `--backend render` 결과와 per-glyph / per-pair diff 분포 산출
- **합격선**:
  - advance p95 ≤ 2u, max ≤ 5u
  - kerning p95 ≤ 3u
  - vertical ±2u
- 미달 시 fail.

### 회귀 스냅샷
- 표본 폰트마다 expected metrics JSON 저장
- CI 에서 새 결과와 diff 비교
- FreeType 버전 / Playwright Chromium 버전 핀 고정

### 라운드트립
- render extract → generate → validate → 비교
- end-to-end 회귀 신호

### 8.1 실측 결과 — NotoSansKR-Bold (전체 cmap, 24,853 글리프)

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
| `global_metrics` | pixel-derivable 만 | 10/11 fields |

**Full 모드 분석 시간**: render extract 37분 + incremental Halfwidth 30초 + unnamed copy 0.5초.

## 9. 단계별 마일스톤 (Phase plan)

| Phase | 산출물 | 검증 게이트 |
|:---:|---|---|
| **P1** | `render_extractor/` 모듈, `RenderBackend` ABC, FreeType 백엔드 PoC, 단일 글리프 advance 측정 | 단위 테스트 통과, NotoSansKR "H" advance ±1u |
| **P2** | vertical / per-glyph advance / LSB / BBox 측정 + assembler | NotoSansKR file vs render diff p95 ≤ 2u |
| **P3** | Hangul monospace 자동 감지, 단일자 복제 | 11K 음절 처리 5s 이내 |
| **P4** | 페어 enumeration + 측정 + noise threshold | 페어 회수율 90% 이상, file diff p95 ≤ 3u |
| **P5** | Playwright 브라우저 백엔드, HTML 템플릿 | 동일 입력 freetype 결과와 ±1u 일치 |
| **P6** | shaped advance + 통합 테스트 + `compare` 자동 diff | 5개 표본 폰트 정확도 회귀 통과 |
| **P7** | 문서, ROADMAP 갱신, v0.3.0 태그 | 릴리스 |

## 10. 위험과 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| 렌더 엔진 버전 차이 잡음 | 정확도 ±5u 이상 | Docker / 핀 고정 |
| 힌팅이 격자 스냅 강제 | per-glyph ±2-3u | `--no-hinting` 강제, 거부 폰트는 별도 분기 |
| 큰 PNG 메모리 OOM | 50 MP 초과 시 1 GB+ | 행 단위 스트리밍 |
| Pan-CJK 65K → 30분 처리 | UX 저하 | 진행률, resume, multiproc |
| 페어 후보 누락 | 일부 페어 미복원 | `--pair-list` 사용자 정의 |
| OS API EULA 해석 차이 | 법적 회색 | 운영 권장은 `browser` |

## 11. 한계 (문서에 명시)

- 정확도: ±1~2 unit 잡음 있음 (file 백엔드 = 정확)
- 컨텍스트 룩업 (`calt`, chained ctx, mark pos) 복원 **불가**
- 라이센스 검토 후 file 추출 가능하면 그쪽이 항상 우월
- 출력 메트릭은 "본 도구가 측정한 근사값" 이며 폰트 EULA 가 측정값 사용까지
  금지하는 경우엔 별도 검토 필요 (전형적 EULA 는 측정값 사용까지 금지하지
  않음 — 메트릭 수치는 저작권 보호 대상이 아닌 단순 수치 사실)
