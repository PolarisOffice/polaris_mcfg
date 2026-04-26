# 02. MetricsSpec 스키마 (v1)

## 목적

모든 도구(extractor / comparator / generator / validator)가 공유하는 단일 데이터 모델. JSON 직렬화로 디스크에 저장된다.

## 스키마

```jsonc
{
  "schemaVersion": 1,
  "source": {
    "filename": "HancomMalang.ttf",
    "sha256": "<hex64>",
    "extractedAt": "2026-04-27T10:00:00Z",  // 또는 "1970-01-01T00:00:00Z" (--deterministic)
    "extractorVersion": "0.1.0"
  },
  "global": {
    "unitsPerEm": 1000,
    "head": { "unitsPerEm": 1000, "xMin": -100, "xMax": 1100, ... },
    "hhea": { "ascent": 880, "descent": -120, "lineGap": 0, ... },
    "os2":  { "sTypoAscender": 880, "sTypoDescender": -120, "sxHeight": 500, ... },
    "post": { "italicAngle": 0.0, "underlinePosition": -100, ... }
  },
  "glyphs": {
    "U+0041": { "advanceWidth": 600 },
    "U+0042": { "advanceWidth": 650, "lsb": 10 },
    "glyph#.notdef": { "advanceWidth": 500 },
    ...
  },
  "kerning": [
    { "left": "U+0041", "right": "U+0056", "value": -80 }
  ],
  "vertical": {
    "vhea": { "ascent": 500, ... },
    "vmtx": { "U+0041": { "advanceHeight": 1000, "tsb": 0 } }
  }
}
```

## 필드 규약

### 글리프 식별자
- `U+XXXX` — 유니코드 코드포인트 (대문자 hex, 최소 4자리 zero-pad).
- `glyph#<postscript-name>` — `cmap`에 등재되지 않은 글리프 (`.notdef`, ligature 등).

식별자 정책의 이유:
- 폰트 간 글리프 매칭을 코드포인트 기반으로 안정적으로 수행하기 위함.
- 디자인 폰트에 동일 코드포인트가 있으면 글리프 이름이 다르더라도 매핑 가능.

### `global` 객체

`extractor.HEAD_FIELDS` / `HHEA_FIELDS` / `OS2_FIELDS` / `POST_FIELDS` / `VHEA_FIELDS` 상수에 화이트리스트로 정의. 추가 필드가 필요하면 화이트리스트만 확장.

레이아웃에 영향을 주지 않는 필드(`fontRevision`, `created`, `modified`, name 테이블 등)는 의도적으로 제외한다.

### `glyphs` 객체

키 정렬 순서로 직렬화 (결정성). `advanceWidth`는 필수, `lsb`는 `--include-lsb` 시에만 포함.

### `kerning` 배열

`(left, right)` 정렬 순. `--include-kerning` 시에만 키가 존재. v1은 classic `kern` (format 0) 만 지원, GPOS는 v2.

### `vertical` 객체

`vhea`/`vmtx` 테이블이 있는 폰트에서만, `--include-vertical` 시 포함.

## 결정성 (Determinism)

- `to_json()`은 `indent=2`, `ensure_ascii=False`, 글리프/kerning/vmtx는 키 정렬.
- `--deterministic` 플래그로 timestamp 고정 → 동일 입력에 대해 동일 출력 (byte-exact).
- 이는 회귀 테스트와 CI에서 골든 파일 비교를 가능하게 한다.

## 라이센스 안전 경계

`extractor.ALLOWED_TABLES` 화이트리스트:

```
head, hhea, OS/2, post, hmtx, cmap, kern, vhea, vmtx
```

`glyf`, `CFF`, `CFF2`, `COLR`, `sbix` 등 **외형 데이터 테이블은 절대 로드하지 않는다**. `tests/test_extractor.py::test_glyf_table_not_loaded_during_extraction`이 이를 강제한다.

## 마이그레이션

`schemaVersion`이 도입되어 있으나 v1 외에는 아직 없음. 추후 v2 도입 시:
- `from_dict`에서 `schemaVersion` 분기.
- 가능하면 v1 → v2 자동 변환.
- 하위 호환 깨질 경우 명시적 에러.
