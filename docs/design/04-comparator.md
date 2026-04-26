# 04. 메트릭 비교기 (M2)

## 책임

두 `MetricsSpec`(또는 두 폰트)을 받아 차이점을 구조화된 리포트로 만든다.

## 데이터 모델

```
MetricsDiff
├── a_source / b_source          # 메타데이터
├── units_per_em: [a_upm, b_upm]
├── threshold                    # 비교 임계값
├── global_diff: GlobalDiff      # head/hhea/os2/post 필드별 (a, b)
├── advance_diff: AdvanceDiff    # 글리프별 advance width
│   ├── common: {gid: [a, b, delta]}    # 차이가 임계값을 넘은 항목만
│   ├── only_in_a / only_in_b
│   └── stats: {matchRate, deltas: {mean, |mean|, max, ...}}
├── lsb_diff: AdvanceDiff?       # LSB가 양쪽에 있을 때만
└── kerning_diff: KerningDiff?   # kerning이 양쪽에 있을 때만
```

## 입력 자동 감지

`load_spec(path)`가 확장자로 분기:
- `.json` → `MetricsSpec.from_json`
- `.ttf` / `.otf` → `extract_metrics(deterministic=True, ...)`

폰트 직접 비교 시에도 결정성을 유지하기 위해 `deterministic=True`로 추출.

## 옵션

| 옵션 | 의미 |
|------|------|
| `--threshold N` | abs(delta) ≤ N units는 일치로 처리. 0이 기본값(엄격). |
| `--normalize-upm` | 두 폰트의 unitsPerEm이 다르면 더 큰 쪽에 맞춰 advance width 스케일링. CJK 폰트(보통 1000)와 라틴 폰트(보통 2048)를 비교할 때 유용. |
| `--max-rows N` | text 포맷에서 표시할 차이 글리프 최대 개수 (기본 20). |

## 통계 산출

`AdvanceDiff.stats`:
- `commonCount`, `matchingCount`, `differingCount`, `matchRate`
- `deltas`: 차이가 발생한 글리프들에 대한 평균/절댓값 평균/표준편차/최대/범위
- `onlyInACount`, `onlyInBCount`

`matchRate`는 회귀 테스트 임계값(예: 0.99 이상이면 호환 OK)으로 활용 가능.

## 출력 포맷

| 포맷 | 용도 | 마일스톤 |
|------|------|----------|
| `text` | 터미널 요약, 사람 읽기용 | M2 |
| `json` | 다른 도구가 소비하거나 회귀 테스트 골든 비교 | M2 |
| `html` | 시각적 막대차트 / 글리프 grid | M6 |
| `csv` | 스프레드시트 분석 | M6 |

## 향후

- v1.1: 라틴/한글/한자 등 유니코드 블록별 통계 분리.
- v1.1: 글리프 차이 분포 히스토그램(text 포맷에서 ASCII 차트).
