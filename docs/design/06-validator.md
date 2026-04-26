# 06. 검증기 (M4)

## 책임

생성된 폰트가 기준 메트릭과 일치하는지 자동으로 점검. CI/회귀 테스트의 마지막 관문.

## 검증 항목 (v1)

| 이름 | 설명 |
|------|------|
| `font_loadable` | `TTFont(path)`가 예외 없이 로드되는지. |
| `required_tables` | head, hhea, OS/2, post, hmtx, cmap, name, maxp 모두 존재. |
| `global_metrics_match` | `head/hhea/OS/2/post`의 *authored* 필드가 ±tolerance 이내. outline-derived 필드(아래)는 기본 제외. |
| `advance_widths_match` | 공통 글리프의 advanceWidth 차이가 ±tolerance 이내. |
| `glyph_coverage` | 기준 spec의 모든 글리프가 폰트에도 존재. |
| `name_metadata` | name 테이블에 family(ID 1)가 있는지. license(ID 13) 존재 여부 보고. |

## 결과 모델

```python
@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: dict

@dataclass
class ValidationReport:
    font_path: str
    against_path: str
    tolerance: int
    checks: list[CheckResult]
    @property def passed(self) -> bool   # all(checks)
```

## CLI 동작

```
mcfg validate <font.ttf> --against <metrics.json|ref.ttf> [--tolerance N]
              [--format text|json] [-o file]
```

- 실패한 체크가 하나라도 있으면 종료 코드 1.
- text 포맷은 ✓/✗로 한 줄 요약 + 실패 시 details 펼침.
- json 포맷은 모든 details 포함 — CI에서 골든 비교 가능.

## Outline-derived 필드 처리

다음 필드들은 글리프 outline 또는 hmtx로부터 *자동 계산*되는 것이므로, 디자인 폰트의 outline을 보존하는 MCFG의 결과 폰트에서는 소스와 항상 다르다. 기본적으로 `global_metrics_match`에서 제외된다.

- `head`: `xMin`, `yMin`, `xMax`, `yMax`
- `hhea`: `advanceWidthMax`, `minLeftSideBearing`, `minRightSideBearing`, `xMaxExtent`

`--strict-global` 플래그로 강제로 포함시킬 수 있다 (내부 디버깅용).

## tolerance 적용

숫자 필드: `abs(actual - ref) > tolerance` 시 실패.
비숫자 필드(panose 리스트, isFixedPitch 등): 정확히 동일해야 통과.

권장값:
- 0 — 결정적 빌드 검증 (소스 메트릭과 byte-exact).
- 1 — 반올림 허용 (UPM 변환 등).
- 2~5 — 다른 도구 체인의 결과 비교.

## 글리프 커버리지

`spec.glyphs` 키 집합 ⊆ `font.glyphs` 키 집합 인지 확인.
- 디자인 폰트가 부족할 경우 generator의 `--missing-glyph` 정책에 따라 결과가 달라지므로, 이 체크가 먼저 실패하는지 확인하면 디버깅이 쉬워진다.

## name 메타데이터

v1에서는 family 존재 여부와 license 설정 여부만 확인. v2 후보:
- license가 디자인 폰트의 라이센스(OFL 등)와 일치하는지.
- 디자인 폰트의 designer/copyright이 보존되었는지.
- family-name이 reserved name 정책을 위반하지 않는지.

## 향후 (M6)

- 렌더링 회귀 (`--render-test <text-file>`): HarfBuzz로 라인 길이 비교.
- 결과를 ValidationReport.checks에 `rendering_match` 항목으로 추가.
