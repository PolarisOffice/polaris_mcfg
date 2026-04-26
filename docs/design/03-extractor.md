# 03. 메트릭 추출기 (M1)

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
                    [--include-vertical] [--deterministic] [--indent N]
```

- `--deterministic`: timestamp를 `1970-01-01T00:00:00Z`로 고정. CI/회귀 테스트용.
- `-o`가 없으면 stdout으로 출력. 있으면 디렉토리 자동 생성 + 줄바꿈으로 끝나는 파일.

## 화이트리스트 강제

`ALLOWED_TABLES = {head, hhea, OS/2, post, hmtx, cmap, kern, vhea, vmtx}`

`extract_metrics`는 위 테이블만 인덱싱한다. fontTools의 lazy 모드에서 미접근 테이블은 디컴파일되지 않으므로, `glyf`/`CFF` 등이 메모리에 올라오지 않는다. `test_glyf_table_not_loaded_during_extraction`가 회귀를 막는다.

## 실패 모드

| 상황 | 처리 |
|------|------|
| 파일 없음 | `click`이 stat 실패로 비-0 종료. |
| `OS/2` 테이블 없음 (구식 Mac TTF) | `KeyError` — 명시적 fallback은 v2. |
| `cmap` 없음 | 모든 글리프가 `glyph#name`으로 식별. |
| 개별 글리프 outline 손상 | 영향 없음 — outline을 읽지 않으므로. |

## 향후 확장 (M5)

- LSB는 이미 옵션으로 지원.
- Kerning: `kern` format 0만 지원. format 2/GPOS pair-positioning은 M5에서 검토.
- Vertical: `vhea/vmtx` 단순 추출. 세로쓰기 폰트가 드물어 한국어 환경에서 실효성은 제한적.
