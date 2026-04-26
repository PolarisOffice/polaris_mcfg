# 05. 폰트 생성기 (M3)

## 책임

소스 `MetricsSpec` + 디자인 폰트 → 새로운 TTF.

- **글리프 외형**은 디자인 폰트 그대로.
- **레이아웃 메트릭**(global, advance width, 선택적 LSB/kerning/vertical)은 소스 메트릭 적용.
- `name` 테이블의 family/style/license를 명시적으로 갱신.

## 입력 → 출력 매핑

```
MetricsSpec (source-upm)              Design font (design-upm)
       │                                       │
       │ ① 글리프 식별자 → 디자인 글리프 이름   │
       │    (cmap 기반)                          │
       │                                       │
       ▼                                       ▼
              ② head/hhea/OS/2/post  ◄─ apply_global
              ③ hmtx (advance, LSB?) ◄─ apply_advance_and_lsb
              ④ kern                 ◄─ apply_kerning
              ⑤ vhea/vmtx            ◄─ apply_vertical
              ⑥ name                 ◄─ update_name_table
                              │
                              ▼
                    [Polaris-Family.ttf]
```

## UPM 처리

소스 폰트의 unitsPerEm과 디자인 폰트의 unitsPerEm이 다를 수 있다.

**전략**: 디자인 폰트의 UPM을 유지하고, 소스 메트릭 값을 디자인 UPM으로 비례 스케일링한다.

이유:
- 디자인 폰트의 outline 좌표는 design-upm 기준이라 UPM 변경은 outline rescale을 의미하는데, v1 범위 외.
- 레이아웃은 em 비율로 결정되므로, advance=500 @ upm=1000과 advance=1000 @ upm=2000은 동일한 시각적 결과.

`_scaled(value, src_upm, dst_upm) = round(value * dst_upm / src_upm)`

## `--scale-glyph` 모드

| 모드 | 동작 | 부작용 |
|------|------|---------|
| `none` (기본) | hmtx의 advance만 변경. 글리프 outline 그대로. | 새 advance가 글리프 폭보다 작으면 글리프가 다음 글리프와 겹침. |
| `fit` | scale_x = new_advance / old_advance. 모든 contour 좌표를 가로로 스케일링. | 글리프 비율이 가로로 늘어나거나 줄어듦. composite 글리프는 decompose됨. |
| `center` | 글리프 폭 유지, 가로 위치만 이동하여 새 advance 내 중앙 정렬. | 글리프가 새 advance보다 넓으면 양옆 음수 LSB로 잘릴 수 있음. |

`fit`/`center`는 `glyf` 테이블의 글리프를 `TTGlyphPen` + `TransformPen`으로 다시 그린다.

### 알려진 부작용
- **Composite 글리프 decomposition**: `fit`/`center`로 변형되는 composite 글리프는 단순 outline으로 평탄화된다 → 파일 크기 증가, hinting 일부 소실.
- **Hinting 손실**: outline 변형은 instructions를 무효화한다 (현재는 그대로 보존하므로 화면 렌더링에서 hinting bug 가능). v2에서 instruction strip 검토.

## `--missing-glyph` 모드

소스 메트릭에는 있지만 디자인 폰트에 없는 글리프 처리:
- `skip` (기본): 무시. stats에 카운트만.
- `notdef`: 디자인의 `.notdef`로 대체. (현재는 cmap 변경 없이 카운트만; 실제 cmap 매핑은 v2에서 필요 시 추가.)

## `--apply` 카테고리

콤마 구분 부분집합. 기본 `global,advance`. 가능 값: `global, advance, lsb, kerning, vertical`.

- `lsb`는 단독 의미가 약하므로 `advance`와 함께 사용.
- `vertical`은 디자인 폰트에 `vhea`가 없으면 합성한다.

## `name` 테이블 갱신

`--family-name`/`--style-name`이 주어지면 다음 name ID를 모두 영어(0x409)로 설정:
- 1 (family), 2 (subfamily), 4 (full name), 6 (PS name), 16/17 (preferred).

`--license-text` → ID 13 (License Description).
`--license-url` → ID 14 (License URL).

OFL Reserved Font Name 정책 등 디자인 폰트 라이센스의 family-name 제약을 호출자가 지킬 책임이 있다.

## CFF/OTF는 v1 범위 외

`glyf` 테이블이 없으면 명시적으로 에러. CFF 글리프 변형은 별도 도구(`fontTools.subset.cff` 등)가 필요하고 비용이 크므로 후속 마일스톤.

## 결과 검증

`generate_font`는 stats dict를 반환:
```python
{
  "designFont": "...",
  "metricGlyphCount": N,
  "applyCategories": [...],
  "advance": {"applied": ..., "missing": ..., "scaled": ..., "centered": ...},
  "kerning": {"pairs": ..., "skipped": ...},
  "vertical": {"applied": ...},
}
```

생성 후 `mcfg validate out.ttf --against source.json`으로 검증 (M4).
