# 12. Render-based Extractor (M8)

> **상태**: 설계 단계 (v0.3.0 작업 중).
> **선행 문서**: [01. 아키텍처](01-architecture.md), [03. 추출기](03-extractor.md).

## 0. 목표

EULA가 file parsing("metric extraction" / "reverse engineering")을 명시
금지한 폰트에 대해, 폰트를 정상 사용(렌더링)한 결과 이미지에서 메트릭을
복원하는 **2차 백엔드**. 기존 file 백엔드와 동일한 `MetricsSpec` 을 출력한다.

> **비목표**: file 백엔드를 대체하지 않는다. file 백엔드가 EULA 상 가능하면
> 그쪽이 항상 우월하다 (정확도, 속도, 컨텍스트 룩업 복원). render 백엔드는
> 회피 수단.

## 1. 라이센스 안전 경계

폰트 EULA 가 허용하는 범위가 다양하므로 본 도구는 layer 별로 모드를 선택할
수 있도록 설계되었다.

### 1.1 레이어별 EULA 위치

```
강한 reverse engineering  ↑                                  ↓ 일반 사용
   file 직접 파싱        HB shape       Pixel 측정       사람 손 + 자
  (fontTools)           (HarfBuzz)     (FreeType)
       ↓                    ↓              ↓
   table 데이터          internal       render output     자로 측정
   직접 추출             access only    만 측정
```

| Layer | "정상 사용" 정의 부합 | 주요 한계 |
|---|---|---|
| **Pure pixel rendering + measurement** | ✅ "화면 자로 측정" 과 동등. 모든 EULA 안전 | advance/LSB/vertical 만 (no kerning, no shaped advance) |
| **+ HarfBuzz shape** | ⚠️ HB 는 OS/브라우저 표준 텍스트 엔진. 결과 numeric 만 사용 | HB 가 내부적으로 file 파싱. "내부 reverse engineering" 논쟁 여지 |
| **+ file pair list (numeric)** | ❌ fontTools 로 직접 파싱. 단, metric *값* 이 아니라 *list* (pair tuple) 만 | 메트릭 list 도 추출로 해석 가능 |
| **+ file metadata flags** | ❌ 직접 파싱. 단, 분류 라벨만 (italicAngle, fsSelection 등) | 분류 정보 추출도 위반 가능 |
| **+ file unnamed glyph numeric** | ❌ 명백한 file parsing. metric 값 직접 read | 가장 위 layer |

### 1.2 우리 도구의 모드별 매핑

| 모드 | 활성 layer | EULA 강도 | 복원율 |
|---|---|---|---:|
| `--pixel-only` | Pixel 만 | **모든 EULA 안전** | ~80% |
| (기본) | + HB shape | 중간 | ~90% |
| `--full-reference FILE` | + file numeric copy | 약-중 | ~100% |
| `--backend file` | 전체 file parsing | 가장 약 | 100% |

### 1.3 행위별 매트릭스

| 행위 | file 백엔드 | render 기본 | render `--pixel-only` |
|---|:---:|:---:|:---:|
| 폰트 테이블 직접 파싱 (fontTools) | ✅ | ❌ (cmap 만) | ❌ (cmap 만) |
| 글리프 outline 좌표 추출 | ❌ | ❌ | ❌ |
| 폰트 렌더링 결과 (픽셀) 측정 | n/a | ✅ | ✅ |
| HarfBuzz shape() 호출 (kerning, shaped 추출) | n/a | ✅ | ❌ |
| File numeric copy (pair list, metadata, unnamed) | n/a | opt-in | ❌ |
| OS 텍스트 API (`CTRunGetAdvances` 등) 호출 | n/a | (browser 백엔드만) | ✅ |
| `@font-face` 로 브라우저에서 텍스트 렌더 | n/a | (browser 백엔드만) | ✅ |

### 1.4 권장 선택 가이드

- **OFL / 일반 상용 폰트** (대부분): 기본 모드. HB shape 까지 사용 OK.
- **EULA 가 "metric extraction" 명시 금지 폰트** (일부 한컴 폰트, 일부 사내 폰트): `--pixel-only` 사용. kerning 손실 있지만 EULA 안전.
- **EULA 가 모든 reverse engineering 금지 폰트**: 진정한 EULA-safe 는 사실 폰트를 자로 측정하는 것뿐. `--pixel-only` 가 가장 가깝지만 fontTools cmap-read 도 회피하려면 사용자가 `--cmap` 직접 명시 필요 (TODO).

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

```
mcfg extract <font> --backend render \
    [--renderer freetype|browser|coretext]   (default: auto)
    [--render-size 1000]                     (default: 1000pt)
    [--no-hinting]                           (default: ON)
    [--detect-monospace / --no-detect-monospace]  (default: ON)
    [--skip-kerning]
    [--include-shaped]                       (browser only)
    [--locales en,ko,ja]                     (--include-shaped 시)
    [--pair-list FILE]                       (커스텀 페어 후보)
    [--workdir DIR]                          (중간 PNG 디버그 출력)
    [--include-lsb / --include-kerning / --include-vertical]  (file 백엔드와 동일)
    -o metrics.json
```

## 6. CLI / 코드 통합 지점

- `cli.py`: `extract_cmd` 에 `--backend render|file` 추가 (기본 `file`).
- `extractor.py`: `extract_metrics(...)` 가 `backend="render"` 분기로
  `render_extractor.extract_via_render(...)` 호출.
- `render_extractor/__init__.py`: `extract_via_render()` 진입점.

## 7. 정확도 검증 전략

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

## 8. 단계별 마일스톤 (Phase plan)

| Phase | 산출물 | 검증 게이트 |
|:---:|---|---|
| **P1** | `render_extractor/` 모듈, `RenderBackend` ABC, FreeType 백엔드 PoC, 단일 글리프 advance 측정 | 단위 테스트 통과, NotoSansKR "H" advance ±1u |
| **P2** | vertical / per-glyph advance / LSB / BBox 측정 + assembler | NotoSansKR file vs render diff p95 ≤ 2u |
| **P3** | Hangul monospace 자동 감지, 단일자 복제 | 11K 음절 처리 5s 이내 |
| **P4** | 페어 enumeration + 측정 + noise threshold | 페어 회수율 90% 이상, file diff p95 ≤ 3u |
| **P5** | Playwright 브라우저 백엔드, HTML 템플릿 | 동일 입력 freetype 결과와 ±1u 일치 |
| **P6** | shaped advance + 통합 테스트 + `compare` 자동 diff | 5개 표본 폰트 정확도 회귀 통과 |
| **P7** | 문서, ROADMAP 갱신, v0.3.0 태그 | 릴리스 |

## 9. 위험과 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| 렌더 엔진 버전 차이 잡음 | 정확도 ±5u 이상 | Docker / 핀 고정 |
| 힌팅이 격자 스냅 강제 | per-glyph ±2-3u | `--no-hinting` 강제, 거부 폰트는 별도 분기 |
| 큰 PNG 메모리 OOM | 50 MP 초과 시 1 GB+ | 행 단위 스트리밍 |
| Pan-CJK 65K → 30분 처리 | UX 저하 | 진행률, resume, multiproc |
| 페어 후보 누락 | 일부 페어 미복원 | `--pair-list` 사용자 정의 |
| OS API EULA 해석 차이 | 법적 회색 | 운영 권장은 `browser` |

## 10. 한계 (문서에 명시)

- 정확도: ±1~2 unit 잡음 있음 (file 백엔드 = 정확)
- 컨텍스트 룩업 (`calt`, chained ctx, mark pos) 복원 **불가**
- 라이센스 검토 후 file 추출 가능하면 그쪽이 항상 우월
- 출력 메트릭은 "본 도구가 측정한 근사값" 이며 폰트 EULA 가 측정값 사용까지
  금지하는 경우엔 별도 검토 필요 (전형적 EULA 는 측정값 사용까지 금지하지
  않음 — 메트릭 수치는 저작권 보호 대상이 아닌 단순 수치 사실)
