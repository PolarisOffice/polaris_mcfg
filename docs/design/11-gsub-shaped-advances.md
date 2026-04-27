# 11. GSUB shaped-advance overrides (v2/A3, opt-in)

## 배경

OpenType 폰트는 같은 코드포인트가 script/lang에 따라 다르게 shaping될 수 있다. 대표 예: NotoSansKR은 `lang="ko"`로 렌더링하면 일반 space (U+0020, advance 224)를 GSUB로 더 넓은 한국어 space (advance 280)로 치환.

cross-pollination 결과 폰트(예: Pretendard outline + Noto metrics)는:
- hmtx의 space는 Noto의 224로 덮어써졌지만,
- GSUB은 디자인 폰트(Pretendard)의 것이라 한국어 wider-space lookup이 없음.
- 따라서 lang="ko"에서 Noto와 다르게 shaping → 라인 너비 어긋남.

## 디자인 결정

GSUB lookup을 그대로 복사하는 건 **글리프 substitution 데이터를 옮기는 행위**라서 라이센스 회색지대가 커진다 (substitution은 디자이너의 의도/감각이 반영됨). 따라서:

1. **Outline은 옮기지 않는다** (기존 정책).
2. GSUB은 기본적으로 옮기지 않는다.
3. **opt-in 플래그**(`--include-gsub` extract, `--apply gsub` generate)로 사용자가 명시적으로 선택할 때만 활성화.
4. GSUB lookup 자체를 복사하지 않고, **shape-induced advance만 추출**해서 디자인 폰트에 stub 글리프 + 새 substitution으로 재구성.

이 접근은 라이센스적으로 가장 안전한 절충안이다 — 추출/이식하는 정보는 advance width(숫자)와 substitution rule(코드포인트→advance 매핑) 뿐.

## 추출 (extractor)

`include_gsub=True` 시 `_extract_shaped_advances`:

1. 폰트의 cmap을 순회.
2. 각 codepoint에 대해 HarfBuzz로 두 가지 shaping 수행:
   - default: `guess_segment_properties`만 호출.
   - context: 명시적 `script` + `language` 설정.
3. 두 결과의 총 advance가 다르면 `ShapedAdvanceOverride(codepoint, script, language, advance)` 기록.

기본 contexts: `[(hang, KOR), (hani, ZHS), (hani, ZHT), (kana, JAN)]` — 한·중·일 주요 스크립트. `gsub_contexts` 인자로 확장 가능.

성능: 24K 글리프 × 4 contexts × HarfBuzz shape ≈ 100K shape calls → 수 초. include_gsub은 다른 추출기보다 느려 opt-in이 적절.

## 스키마

```jsonc
{
  ...
  "shapedAdvances": [
    {"codepoint": "U+0020", "script": "hang", "language": "KOR", "advance": 280},
    {"codepoint": "U+002C", "script": "hang", "language": "KOR", "advance": 950},
    ...
  ]
}
```

정렬: `(codepoint, script, language)` lexicographic — 결정성 유지.

## 적용 (generator)

`--apply gsub` 시 `_apply_shaped_advances`:

1. 각 override에 대해:
   - 디자인 폰트의 cmap에서 codepoint → 글리프 이름 (없으면 skip).
   - **stub glyph 생성**: 빈 outline의 새 글리프 (`polaris.{cp}.{script}_{lang}`), advance만 override 값으로 설정. UPM 환산 적용.
   - (script, lang, source_glyph)별로 dedup — 같은 컨텍스트에서 같은 글리프에 대한 substitution 중복 정의 방지 (FEA 컴파일 에러).
2. **FEA 코드 합성**:
   ```
   languagesystem hang KOR;
   feature locl {
     script hang; language KOR exclude_dflt;
     sub space by polaris.0020.hang_KOR;
   } locl;
   ```
3. `feaLib.builder.addOpenTypeFeaturesFromString`으로 GSUB에 lookup + feature 추가.

### `locl` (Localized Forms) feature 선택 이유

브라우저는 `lang="ko"`가 명시된 텍스트에서 `locl` feature를 자동 활성화한다 (HarfBuzz의 기본 동작). 사용자 측 추가 설정 불필요.

### Stub glyph가 빈 outline인 이유

다음 글자와 겹치는 시각 효과 없이 advance만 늘리고 싶다. space의 경우 원래도 visible glyph가 없으므로 동일. 한국어 wider space는 단어 사이 시각적 균형을 위한 *공간만* 추가하므로 빈 outline이 맞다.

## CLI

```bash
# 추출 시
mcfg extract source.ttf --include-gsub -o source.json

# 생성 시 (다른 옵션과 조합)
mcfg generate \
  --metrics source.json \
  --design  design.ttf \
  --apply   global,advance,kerning,gsub \
  --match-upm \
  --output  out.ttf
```

기본 `--apply`는 `global,advance` 그대로. `gsub`는 명시적으로 추가해야 활성화.

## 결과 (visual_test)

`lang="ko"` 환경에서:
- v0.2 (gsub 미적용): Group A의 Polaris PNM이 Noto와 라인 너비 ~3.36px (= 1자 폭) 표류.
- v0.3 (gsub 적용): Group A 16/16, Group B 15/15 byte-perfect 일치.

## 한계

- **양방향 비대칭**: source font가 GSUB substitution을 가졌고 design font는 안 가진 경우는 깔끔히 처리됨 (Pretendard outline + Noto metrics + gsub). 반대 방향(source 없음, design 있음)은 design의 GSUB이 그대로 살아남아 결과가 source와 다름. v1.1에서 `--strip-design-gsub` 같은 옵션 검토.
- **OpenType feature 다양성**: `locl`로 단일 substitution만 다룸. 합자(`liga`), 분리(`dlig`), contextual(`calt`) 등 multi-glyph substitution은 v2 범위 외.
- **추출 속도**: HarfBuzz shape 호출이 cmap × contexts만큼 일어나므로 큰 CJK 폰트에서 수 초 ~ 십수 초.

## 라이센스 고려

stub 글리프가 outline 데이터를 갖지 않으므로 디자인 폰트의 라이센스에 영향 없음. substitution rule 자체가 source 폰트의 디자인 의도라는 해석 여지는 있으나 numeric/structural 정보로 분류 가능. 보수적 사용 시 `--apply gsub` 사용 자제 권고.

## 검증

`tests/test_gsub_overrides.py` 4 tests:
- 빌트인 Korean wider-space 같은 substitution 추출 정확성
- 적용 후 default와 (hang, KOR) shaping advance 차이 확인
- 디자인 폰트에 없는 codepoint override는 skip
- MetricsSpec round-trip
