# Polaris MCFG (Metric-Compatible Font Generator) 요구사항

## 1. 배경 및 목적

### 1.1 문제 정의
- 한컴 폰트, 사내 전용 폰트, 일부 상용 폰트 등 **재배포가 제한된 소스 폰트(이하 "소스 폰트")** 로 작성된 문서를, 자유 라이센스 환경에서 동일 레이아웃으로 재현할 수 없다.
- 폰트별로 글리프 advance width, ascent/descent, line-gap 등 **레이아웃에 영향을 미치는 메트릭**이 다르다.
- 그 결과, 단순히 다른 폰트로 대체하면 줄바꿈 위치, 페이지 분할, 표 크기 등이 달라져 **원본 문서와 동일한 렌더링을 기대할 수 없다**.

> 본 도구의 일차 동기는 한컴 폰트류를 자유 라이센스 환경에 재현하는 사례였으나, 도구 자체는 임의의 소스 폰트를 입력으로 받는다.

### 1.2 해결 접근
- 소스 폰트로부터 **레이아웃에 영향을 주는 메트릭만** 추출한다 (글리프 외형 데이터는 제외).
- 추출된 메트릭을 **재라이센스 가능한(OFL, Apache 등) 자유 폰트의 글리프 디자인에 적용**하여,
  - **시각적 외형은 자유 폰트의 디자인**을 따르되,
  - **레이아웃은 소스 폰트와 호환되는** 새로운 폰트를 생성한다.

### 1.3 기대 효과
- 소스 폰트로 작성된 문서를 자유 라이센스 환경(웹, PDF 뷰어, 타 워드프로세서)에서 **줄바꿈/페이지 레이아웃을 유지한 채** 렌더링 가능.
- 라이센스 위험 없이 소스 폰트와 메트릭 호환성을 갖는 대체 폰트를 배포 가능.

---

## 2. 시스템 구성

전체 시스템은 다음 4개의 독립 도구로 구성되며, 단일 CLI(`mcfg`)의 서브커맨드로 노출된다.

| 도구 | 서브커맨드 | 역할 |
|------|-----------|------|
| 메트릭 추출기 | `mcfg extract` | 폰트 파일에서 메트릭을 추출하여 명세 파일(JSON)로 저장 |
| 메트릭 비교기 | `mcfg compare` | 두 폰트(또는 명세) 간의 메트릭 차이를 보고 |
| 폰트 생성기 | `mcfg generate` | 메트릭 명세 + 디자인 폰트 → 새로운 폰트 |
| 검증기 | `mcfg validate` | 생성된 폰트가 원본 메트릭과 일치하는지 검증 |

---

## 3. 기능 요구사항

### 3.1 메트릭 추출기 (Extractor)

#### 입력
- TTF 또는 OTF 폰트 파일.

#### 출력
- 메트릭 명세 파일 (JSON, 스키마 v1).
- 사람이 읽을 수 있도록 indent된 형태와 압축 형태 모두 지원.

#### 추출 대상 메트릭

**필수 (Required)**
1. **Global metrics**
   - `head` 테이블: `unitsPerEm`, `xMin/yMin/xMax/yMax`, `flags`, `macStyle`
   - `hhea` 테이블: `ascent`, `descent`, `lineGap`, `advanceWidthMax`
   - `OS/2` 테이블: `sTypoAscender`, `sTypoDescender`, `sTypoLineGap`, `usWinAscent`, `usWinDescent`, `sxHeight`, `sCapHeight`, `panose`
   - `post` 테이블: `underlinePosition`, `underlineThickness`, `italicAngle`
2. **Glyph advance width** (`hmtx`)
   - 각 글리프(유니코드 코드포인트 기반)의 `advanceWidth`.
   - 글리프 식별자: 가능하면 유니코드 코드포인트, 없으면 글리프 이름.

**선택 (Optional, 플래그로 제어)**
3. **Left side bearing (LSB)** — `--include-lsb`
   - 글리프별 `lsb` 값.
4. **Kerning** — `--include-kerning`
   - `kern` 테이블 (구식) 및 `GPOS` 테이블의 pair adjustment 추출.
   - 페어(left-glyph, right-glyph)와 조정값.
5. **Vertical metrics** — `--include-vertical`
   - `vhea`, `vmtx` 테이블 (세로쓰기 지원 폰트의 경우).

#### 비기능 요건
- 글리프 외형(`glyf`/`CFF`/`CFF2`) 데이터는 **추출하지 않는다** (라이센스 안전성).
- 동일 입력에 대해 **결정적(deterministic)** 출력을 보장.
- 한글, CJK 통합 한자, 라틴, 숫자, 기호 등 다국어 글리프 모두 지원.

#### CLI 예시
```
mcfg extract SourceFont-Regular.ttf -o source.metrics.json
mcfg extract SourceFont-Regular.ttf --include-kerning --include-lsb -o source.metrics.json
```

---

### 3.2 메트릭 비교기 (Comparator)

#### 입력
- 두 개의 입력. 각각 폰트 파일(.ttf/.otf) 또는 메트릭 명세(.json).
- 폰트 파일이 주어지면 내부적으로 추출 후 비교.

#### 출력
- 차이점 리포트. 다음 형식 중 선택 가능:
  - `--format json` (기본)
  - `--format html` (시각적 리포트, 글리프별 차이 그래프)
  - `--format csv` (스프레드시트 분석용)
  - `--format text` (터미널 요약)

#### 비교 항목
1. **Global metrics 차이**: 항목별 절대값/상대값(%) 표.
2. **Glyph advance width 차이**:
   - 공통 글리프(유니코드 기준 교집합)에 대한 차이.
   - A에만 있는 글리프 / B에만 있는 글리프 목록.
   - 통계 요약: 평균 차이, 표준편차, 최대 차이, 일치율.
3. **LSB, kerning, vertical metrics 차이** (해당 데이터가 있을 때만).

#### 임계값 옵션
- `--threshold N`: N units 이하의 차이는 "동일"로 간주.
- `--unitsPerEm-normalize`: 두 폰트의 unitsPerEm이 다른 경우 정규화하여 비교.

#### CLI 예시
```
mcfg compare SourceFont-Regular.ttf NotoSansKR-Regular.ttf --format html -o diff.html
mcfg compare source.metrics.json gothic.metrics.json --format text
```

---

### 3.3 폰트 생성기 (Generator)

#### 입력
- `--metrics <source.json>`: 따를 메트릭 명세 (소스 폰트에서 추출한 것).
- `--design <target.ttf>`: 글리프 디자인을 가져올 자유 라이센스 폰트.
- `--output <out.ttf>`: 결과 폰트 경로.
- 옵션:
  - `--apply <list>`: 적용할 메트릭 카테고리 선택 (`global,advance,lsb,kerning,vertical` 중 콤마 구분).
  - `--scale-glyph <mode>`: advance width가 다를 때 글리프를 어떻게 맞출지.
    - `none` (기본): advance만 변경, 글리프 외형은 그대로 (충돌/공백 발생 가능).
    - `fit`: advance width에 맞게 글리프를 가로 스케일링.
    - `center`: 글리프 중앙 정렬, advance만 조정.
  - `--missing-glyph <mode>`: 메트릭에는 있으나 디자인 폰트에 없는 글리프 처리.
    - `skip`: 무시.
    - `notdef`: `.notdef` 사용.
    - `fallback <font>`: 다른 폰트에서 가져옴.
  - `--family-name <name>`, `--style-name <name>`: 결과 폰트의 family/style 이름 지정.
  - `--license <text|file>`: `name` 테이블의 라이센스 필드 갱신.

#### 동작
1. 디자인 폰트를 로드하고 글리프 외형을 보존.
2. 메트릭 명세의 글로벌 메트릭을 결과 폰트의 `head/hhea/OS/2/post` 테이블에 적용.
3. 글리프별로:
   - 메트릭 명세의 `advanceWidth`를 `hmtx`에 적용.
   - `--scale-glyph` 옵션에 따라 글리프 외형 처리.
   - `--include-lsb`가 적용된 경우 LSB도 적용.
4. Kerning이 적용된 경우 `kern`/`GPOS` 페어 정보를 디자인 폰트의 글리프 이름에 매핑하여 삽입.
5. `name` 테이블 업데이트: family name, license, version, designer 정보 갱신.
6. 결과 폰트 검증 후 저장.

#### 라이센스/메타데이터
- 결과 폰트의 라이센스는 **디자인 폰트의 라이센스를 기본값**으로 한다.
- `name` 테이블의 `License Description`, `License URL`, `Copyright`, `Designer` 등을 명시적으로 설정.
- 메트릭이 특정 소스 폰트에서 유래했음을 별도 메타데이터에 표기 (선택적, `--credit-source`).

#### CLI 예시
```
mcfg generate \
  --metrics source.metrics.json \
  --design NotoSansKR-Regular.ttf \
  --apply global,advance,kerning \
  --scale-glyph fit \
  --family-name "Polaris Malang" \
  --output PolarisMalang-Regular.ttf
```

---

### 3.4 검증기 (Validator)

#### 입력
- 검증 대상 폰트 (`<font.ttf>`).
- 비교 기준:
  - `--against <metrics.json>`: 메트릭 명세와 일치하는지 검증, 또는
  - `--against <reference.ttf>`: 다른 폰트와 메트릭 호환성 검증.

#### 출력
- 검증 리포트 (JSON/HTML/text). pass/fail과 항목별 결과 포함.
- 종료 코드: 모든 검증 통과 시 0, 실패 시 비-0.

#### 검증 항목
1. **폰트 구조 유효성**
   - `fontTools`의 sanity check, 필수 테이블 존재, 무결성 확인.
2. **메트릭 일치도**
   - Global metrics가 명세와 정확히 일치하는지.
   - 모든 글리프의 advance width가 명세와 일치하는지 (허용 오차 `--tolerance N`).
   - LSB, kerning, vertical metrics 일치도 (옵션 적용된 경우).
3. **글리프 커버리지**
   - 명세에 있는 글리프가 결과 폰트에도 존재하는지.
   - 누락 글리프 목록.
4. **렌더링 비교 (옵션)** — `--render-test <text-file>`
   - 샘플 텍스트(다양한 한글, 한자, 라틴 조합)를 HarfBuzz로 shape하여 라인 길이를 비교.
   - 원본 메트릭과 결과 폰트의 라인 길이 차이를 보고 (시각적 회귀 테스트).
5. **라이센스 메타데이터**
   - `name` 테이블의 라이센스 필드가 적절히 설정되었는지.
   - 디자인 폰트 원본의 저작권 표시가 보존되었는지.

#### CLI 예시
```
mcfg validate PolarisOutput-Regular.ttf --against source.metrics.json
mcfg validate PolarisOutput-Regular.ttf --against SourceFont-Regular.ttf --tolerance 1 --render-test samples/korean.txt
```

---

## 4. 데이터 형식

### 4.1 메트릭 명세 JSON 스키마 (v1, 개요)
```json
{
  "schemaVersion": 1,
  "source": {
    "filename": "SourceFont-Regular.ttf",
    "sha256": "…",
    "extractedAt": "2026-04-27T10:00:00Z",
    "extractorVersion": "0.1.0"
  },
  "global": {
    "unitsPerEm": 1000,
    "head": { "...": "..." },
    "hhea": { "ascent": 880, "descent": -120, "lineGap": 0, "...": "..." },
    "os2":  { "sTypoAscender": 880, "sTypoDescender": -120, "...": "..." },
    "post": { "...": "..." }
  },
  "glyphs": {
    "U+0041": { "advanceWidth": 600, "lsb": 50 },
    "U+AC00": { "advanceWidth": 1000, "lsb": 0 },
    "...":    { "...": "..." }
  },
  "kerning": [
    { "left": "U+0041", "right": "U+0056", "value": -80 }
  ],
  "vertical": {
    "vhea": { "...": "..." },
    "vmtx": { "U+AC00": { "advanceHeight": 1000, "tsb": 0 } }
  }
}
```

### 4.2 식별자 정책
- 글리프 식별자는 우선 유니코드 코드포인트(`U+XXXX`).
- 코드포인트가 없는 글리프(예: 변형, ligature)는 글리프 이름(`postscript name`)으로 fallback.
- 합자(ligature) 등 GSUB로 형성되는 글리프는 v1에서 제외, 후속 버전에서 검토.

---

## 5. 비기능 요구사항

### 5.1 기술 스택
- 언어: Python 3.10+.
- 핵심 라이브러리:
  - [`fontTools`](https://github.com/fonttools/fonttools) — TTF/OTF 읽기/쓰기, 테이블 조작.
  - [`uharfbuzz`](https://github.com/harfbuzz/uharfbuzz) — 렌더링/shaping 검증.
  - `pytest` — 테스트.
- CLI: `click` 또는 `typer`.
- 패키징: `pyproject.toml` 기반, `pip install .`로 설치 가능.

### 5.2 호환성
- macOS, Linux, Windows 지원.
- 입력 폰트 포맷: TTF, OTF (TrueType outlines, CFF outlines 모두).
- 출력 폰트 포맷: TTF (기본), OTF (옵션).

### 5.3 성능
- 단일 CJK 폰트(약 20,000 글리프) 추출: 30초 이내.
- 생성: 1분 이내.
- 메모리 사용량: 1GB 이하.

### 5.4 결정성/재현성
- 모든 도구는 동일 입력에 대해 동일 출력 (시간/타임스탬프 필드는 고정 가능 옵션 제공).
- `--deterministic` 플래그로 timestamp 등 가변 필드 고정.

### 5.5 에러 처리
- 손상된 폰트 파일에 대한 명확한 오류 메시지.
- 누락된 테이블/필드는 옵션의 적용 여부에 따라 경고 또는 무시.

---

## 6. 라이센스 및 법적 고려사항

### 6.1 메트릭 추출의 안전성
- 본 시스템은 **글리프 외형(outline) 데이터를 추출/복제하지 않는다**.
- 추출되는 것은 숫자값(메트릭) 뿐이며, 이는 일반적으로 저작권 보호 대상에서 제외되는 사실 정보로 해석될 여지가 있다.
- 그럼에도 불구하고 소스 폰트의 EULA/라이센스(예: 한컴 폰트, 사내 폰트, 상용 라이브러리)를 사전에 검토하고, 메트릭 추출 및 파생 사용에 대한 법적 검토를 별도로 수행할 것을 권고.

### 6.2 결과 폰트의 라이센스
- 글리프 디자인의 출처가 자유 라이센스(OFL 등) 폰트이므로, 결과 폰트는 해당 라이센스의 조건을 따라야 한다.
- 디자인 폰트의 OFL Reserved Font Name 정책 등을 준수하여 family name을 변경.

### 6.3 메타데이터
- 결과 폰트의 `name` 테이블에 디자인 폰트의 원저자 표시를 보존.
- 메트릭 호환성에 대한 별도 표기는 옵션으로 제공 (소스 폰트의 상표 사용 회피).

---

## 7. 검증 및 테스트 전략

### 7.1 단위 테스트
- 각 메트릭 추출 함수(global, hmtx, kern, vmtx)의 정확도.
- JSON 직렬화/역직렬화 round-trip.

### 7.2 통합 테스트
- 샘플 폰트(자유 라이센스의 소규모 폰트)에 대한 end-to-end 파이프라인.
- 추출 → 비교 → 생성 → 검증의 전체 흐름.

### 7.3 회귀 테스트
- 골든 메트릭 명세 파일을 저장소에 보관, 변경 시 차이 감지.

### 7.4 시각적 회귀 테스트
- 사전 정의된 한국어/한자/라틴 샘플 텍스트를 두 폰트로 shape하여 라인 길이를 비교.
- 차이가 임계치를 초과하면 실패.

---

## 8. 마일스톤 (제안)

| 단계 | 내용 |
|------|------|
| M1 | 메트릭 추출기 (필수 메트릭만), JSON 스키마 v1, 단위 테스트 |
| M2 | 메트릭 비교기 (text/json 출력) |
| M3 | 폰트 생성기 (global + advance width 적용, scale-glyph: none/fit) |
| M4 | 검증기 (구조/메트릭/커버리지 검증) |
| M5 | 선택 메트릭(LSB, kerning, vertical) 지원 추가 |
| M6 | HTML 리포트, 렌더링 회귀 테스트 |
| M7 | 패키징, 문서화, 샘플 |

---

## 9. 범위 외 (Out of Scope, v1)

- GSUB 기반 합자/변형 글리프의 메트릭 처리.
- 컬러 폰트(`COLR`/`CPAL`, `sbix`).
- 가변 폰트(`fvar`/`gvar`)의 축별 메트릭 보간 — v2에서 고려.
- 소스 폰트의 글리프 외형 추출/사용 (의도적으로 영구 배제).
- GUI — CLI만 제공, 추후 별도 도구로 분리 가능.
