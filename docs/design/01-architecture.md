# 01. 아키텍처 개요

## 모듈 레이아웃

```
src/polaris_mcfg/
├── __init__.py
├── cli.py          # click 진입점, 서브커맨드 lazy 등록
├── schema.py       # MetricsSpec dataclass + JSON 직렬화
├── extractor.py    # M1: 폰트 → MetricsSpec
├── comparator.py   # M2: MetricsSpec × MetricsSpec → diff
├── generator.py    # M3: MetricsSpec + 디자인 폰트 → 새 폰트
├── validator.py    # M4: 폰트 vs MetricsSpec → 검증 리포트
├── render.py       # M6: HarfBuzz로 라인 길이 비교
└── report.py       # M6: HTML 리포트 렌더링
```

## 데이터 흐름

```
[Hancom font.ttf]                          [Free font.ttf]
       │                                          │
       ▼ extract                                  │
[metrics.json] ──────► compare ◄─────── extract ──┘
       │                                          │
       │                                          ▼
       └──────────► generate ◄────────── [Free font.ttf]
                       │
                       ▼
               [Polaris font.ttf]
                       │
                       ▼
                   validate
                       │
                       ▼
              [validation report]
```

## 단일 진실 공급원: `MetricsSpec`

모든 도구가 동일 데이터 모델을 공유한다. JSON으로 직렬화 가능한 dataclass.
- `extractor`는 폰트에서 `MetricsSpec`을 만든다.
- `comparator`는 두 `MetricsSpec`을 받아 차이를 계산한다.
- `generator`는 `MetricsSpec`을 받아 디자인 폰트의 `head/hhea/OS/2/post/hmtx` 테이블을 갱신한다.
- `validator`는 결과 폰트에서 `MetricsSpec`을 다시 추출하여 기준 `MetricsSpec`과 비교한다.

## 글리프 식별자

- 1순위: 유니코드 코드포인트 `U+XXXX` (대문자 hex, 4자리 zero-pad, 5자리 이상도 허용).
- 2순위: 글리프 PostScript 이름 `glyph#name` (코드포인트 없는 글리프).

`extractor`는 `cmap` 테이블에서 코드포인트 ↔ 글리프 이름 매핑을 만들고, MetricsSpec의 키는 식별자 문자열이다. `generator`는 디자인 폰트의 `cmap`을 통해 식별자를 다시 글리프 이름으로 해석한다.

## 결정성 (Determinism)

- JSON 출력은 `sort_keys=True`, `indent=2`, `ensure_ascii=False`.
- `extractedAt` 같은 시간 필드는 `--deterministic` 플래그로 고정 가능.
- 글리프 dict는 식별자 정렬 순으로 직렬화.

## 라이센스 안전 경계

- `extractor`는 `glyf`/`CFF`/`CFF2` 테이블을 절대 읽지 않는다 (테이블 이름을 화이트리스트로 제한).
- `MetricsSpec`은 outline 데이터를 표현할 수 없는 형태(숫자 dict)로만 정의한다.
- `generator`는 디자인 폰트의 outline을 보존하고 메트릭 테이블만 교체한다.

## 의존성

- `fontTools` — TTF/OTF I/O, 테이블 조작.
- `click` — CLI.
- `uharfbuzz` (선택) — M6 렌더링 회귀 테스트.
- `pytest` — 테스트.
