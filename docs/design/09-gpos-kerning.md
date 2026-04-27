# 09. GPOS pair kerning (P0/A1, P1/A2)

## 배경

v0.1의 추출/적용은 classic `kern` 테이블만 다뤘다. 그러나 거의 모든 현대 폰트는 GPOS lookup type 2 (PairPos)로 커닝을 정의하고, 브라우저/HarfBuzz는 OpenType 폰트에서 GPOS를 우선시한다. classic `kern`만 쓰면 결과 폰트의 커닝이 사실상 무시되고, 디자인 폰트의 GPOS 커닝이 그대로 살아남아 라인 너비가 어긋난다 (visual_test에서 Group A 라틴 부분 ±66u 표류).

## 추출 (extractor)

### 화이트리스트 확장

`ALLOWED_TABLES`에 `GPOS` 추가. 단, **PairPos lookup만 읽는다** (lookup type 2). mark/cursive/contextual lookup은 의도적으로 무시 — 이들은 라인 너비에 거의 영향을 주지 않으면서 코드 복잡도만 키운다.

### Format 1 (explicit pairs)

```
Coverage[i]  → PairSet[i]  → PairValueRecord[(SecondGlyph, Value1, Value2)]
```

각 Value1.XAdvance만 읽음. Value2 (두번째 글리프 advance 조정)와 placement 필드는 폰트 메트릭 호환성 목적엔 부차적이라 lossy하게 제외. 필요 시 v1.1에서 확장.

### Format 2 (class-based)

```
Coverage  → ClassDef1, ClassDef2
Class1Record[c1].Class2Record[c2].Value1 → 모든 (g1 ∈ class[c1], g2 ∈ class[c2]) 페어
```

`_invert_classdef`가 `{class_index: [glyph_names]}`를 만든다. 핵심:
- **Class 0**은 명시적으로 다른 클래스에 속하지 않은 모든 글리프 (universe - explicit). ClassDef1의 universe는 Coverage 글리프 집합, ClassDef2는 폰트 전체 글리프 집합.
- 클래스 카르테시안 곱을 펼쳐서 페어 리스트로 변환. 압축률은 떨어지지만 적용 단계가 단순해진다.

### Extension lookups (type 9)

큰 폰트에서 GPOS 오프셋이 32비트로 부족할 때 Extension wrapper로 lookup을 감싼다. `_resolve_extension`이 `ExtSubTable`로 풀어서 effective lookup type을 회수.

### 중복 처리

같은 (left, right)가 classic `kern`에도, GPOS에도 있을 수 있다. `_extract_kerning`은 **classic을 먼저 추가**하고, GPOS에서 같은 페어가 나오면 무시 — 명시적인 글리프-페어 쪽이 클래스 기반의 일반화된 값보다 정확하다.

## 적용 (generator)

`_write_gpos_kern(font, pairs)`이 핵심:

1. **fontTools `otlLib.builder.buildPairPosGlyphs`**로 PairPosFormat1 subtable 생성. ValueRecord에는 XAdvance만 설정.
2. 디자인 폰트의 GPOS LookupList 순회:
   - lookup type 2 (또는 type 9가 type 2를 wrap)인 lookup을 모두 **제거**.
   - 나머지 lookup의 인덱스를 remap.
3. 우리 새 lookup을 LookupList 끝에 추가.
4. FeatureList의 모든 FeatureRecord에서 LookupListIndex를 새 인덱스로 갱신. `kern` feature가 있으면 우리 새 lookup을 가리키도록 재배선; 없으면 새로 만들어 모든 script langsystem에 등록.

`_lookup_is_pair_pos`가 type 2 + Extension(type 9 wrapping type 2) 둘 다 식별.

`_build_minimal_gpos`는 디자인 폰트에 GPOS가 아예 없을 때 `kern` feature 하나만 가진 minimal GPOS를 새로 생성.

## 호환성 / 한계

- **Mark/Cursive 보존**: 추출은 type 2만, 적용은 type 2만 제거 → 디자인 폰트의 mark positioning, cursive 등은 그대로 살아남는다.
- **Format 3 (대상 advance도 조정)**: 일부 구식 폰트만 사용. 무시.
- **Variation 적용**: GPOS feature variations (FeatureVariations table)는 처리하지 않음. 가변 폰트는 v2.

## 검증

- `tests/test_gpos_kerning.py` 6 tests:
  - Format 1 추출 정확성
  - Format 2 (class-based) 추출 정확성
  - classic `kern` 우선순위
  - 결과 폰트에 GPOS `kern` feature 존재
  - HarfBuzz round-trip 너비 일치
  - 디자인 폰트의 기존 PairPos lookup 교체 (bleed-through 방지)
