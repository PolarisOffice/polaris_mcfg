# 03. 메트릭 추출기 (M1, GPOS는 v0.2)

## 책임

폰트 파일에서 레이아웃에 영향을 주는 메트릭만 읽어 `MetricsSpec`을 생성.

## 입력/출력

- 입력: TTF/OTF 파일 경로 + 옵션 플래그.
- 출력: `MetricsSpec` (Python 객체) 또는 JSON 텍스트 (CLI).

## 동작

1. `TTFont(path, lazy=True)`로 lazy 로드.
2. `cmap`에서 codepoint ↔ glyph_name 매핑 구성 → `_build_glyph_id_map`.
3. `head/hhea/OS/2/post`에서 화이트리스트 필드만 추출 → `GlobalMetrics`.
4. `hmtx.metrics`를 순회하며 글리프별 advance width (선택적 LSB) 수집.
5. 옵션 플래그에 따라 `kern`, `vhea/vmtx` 추가 추출.
6. `source` 메타데이터 (sha256, 파일명, 타임스탬프, extractor 버전) 부착.

## CLI

```
mcfg extract <font> [-o out.json] [--include-lsb] [--include-kerning]
                    [--include-vertical] [--include-gsub]
                    [--deterministic] [--indent N]
```

- `--deterministic`: timestamp를 `1970-01-01T00:00:00Z`로 고정. CI/회귀 테스트용.
- `--include-gsub`: HarfBuzz로 (script, lang) 별 shape-induced advance 차이 감지 (`shapedAdvances`). 느린 옵션, opt-in. 09-gpos / 11-gsub 문서 참조.
- `-o`가 없으면 stdout으로 출력. 있으면 디렉토리 자동 생성 + 줄바꿈으로 끝나는 파일.

## 화이트리스트 강제

```
ALLOWED_TABLES = {
    head, hhea, OS/2, post, hmtx, cmap, kern, vhea, vmtx,  # always
    GPOS,  # for pair kerning (lookup type 2 only)
    GSUB,  # only when include_gsub=True; we shape via HarfBuzz, not parse
}
```

`extract_metrics`는 위 테이블만 인덱싱한다. fontTools의 lazy 모드에서 미접근 테이블은 디컴파일되지 않으므로, `glyf`/`CFF`/`COLR`/`sbix` 등 outline-bearing 테이블이 메모리에 올라오지 않는다. `test_glyf_table_not_loaded_during_extraction`가 회귀를 막는다.

`GPOS`/`GSUB` 추출의 라이센스 영향은 [11-gsub-shaped-advances.md](11-gsub-shaped-advances.md)를 참고.

## 실패 모드

| 상황 | 처리 |
|------|------|
| 파일 없음 | `click`이 stat 실패로 비-0 종료. |
| `OS/2` 테이블 없음 (구식 Mac TTF) | `KeyError` — 명시적 fallback은 후속. |
| `cmap` 없음 | 모든 글리프가 `glyph#name`으로 식별. |
| 개별 글리프 outline 손상 | 영향 없음 — outline을 읽지 않으므로. |
| `--include-gsub`인데 uharfbuzz 미설치 | `RuntimeError` — `pip install -e '.[dev]'` 권장 안내. |

## 커닝 추출 (kern + GPOS)

- classic `kern` 테이블 (format 0): 직접 페어 → 그대로.
- GPOS lookup type 2 PairPos:
  - Format 1 (explicit pairs): coverage × PairValueRecord.
  - Format 2 (class-based): ClassDef 두 개의 카르테시안 곱을 펼침. Class 0은 universe 기반(ClassDef1은 coverage 기반, ClassDef2는 전체 글리프 기반).
  - Extension wrapping (lookup type 9 → effective 2)도 unwrap.
- 같은 (left, right) 페어가 양쪽에 있으면 **classic이 우선** (명시적이고 글리프 단위).

자세한 알고리즘은 [09-gpos-kerning.md](09-gpos-kerning.md).

## Vertical / GSUB / 후속 확장

- Vertical: `vhea/vmtx` 단순 추출. 세로쓰기 한국어는 드물지만 한자 사전류 등 일부 활용처 있음.
- GSUB: 직접 lookup 디컴포지션 대신 HarfBuzz로 (script, lang) 별 shape 차이 측정. `shapedAdvances`로 저장 → generator가 `--apply gsub`로 stub glyph + locl 주입.
