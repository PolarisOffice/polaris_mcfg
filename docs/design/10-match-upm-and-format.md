# 10. UPM 정합 + 출력 포맷 (P2/A5)

## 문제

UPM이 다른 두 폰트로 cross-pollination 할 때 (예: Noto upm=1000, Pretendard upm=2048):
- 소스 메트릭을 디자인 UPM으로 비례 스케일하면 글리프당 ±0.5 unit 라운딩이 발생.
- 누적 효과로 긴 라인의 줄바꿈 위치가 1~2자 표류 (브라우저 측정 기준).
- HarfBuzz/canvas로는 동일하게 보이지만 `getBoundingClientRect`는 sub-pixel 차이를 감지함.

## 해결 (P2/A5): `--match-upm`

소스 메트릭을 적용하기 *전에* 디자인 폰트의 UPM을 소스 UPM으로 rescale. fontTools `scale_upem`이 글리프 좌표/메트릭/GPOS 값을 비례 변환.

```python
if match_upm:
    if dst_upm != src_upm:
        scale_upem(font, src_upm)  # design glyf, hmtx, GPOS, ... all scaled
    # 이후 메트릭 적용은 동일 단위에서 수행 → 라운딩 0
```

## Chromium TTF 호환성 이슈

발견: `fontTools.scale_upem`을 NotoSansKR에 적용해 저장한 TTF는 **Chromium의 TTF sanitizer가 거부**한다 (FontFace.load() → NetworkError). 한편:
- 동일 데이터를 WOFF2로 저장하면 Chrome이 정상 로드.
- HarfBuzz는 양쪽 다 valid로 인식.
- 디버그: 글리프를 후반부(idx 23000+)부터 스케일하면 실패, 단일 글리프 스케일은 OK — 누적 효과.
- 어떤 단일 테이블을 strip해도 해결 안 됨 (BASE/STAT/gasp/prep/vhea/vmtx 모두 시도).
- WOFF2 변환은 fontTools 내부에서 woff2 인코딩을 거치며 정규화 발생.

이 패턴은 fontTools나 OTS 어딘가의 미세한 호환성 갭으로 보이며, 본 프로젝트 범위 외에서 추적해야 할 별도 이슈.

## 워크어라운드: `--output-format auto`

```python
output_format ∈ {auto, ttf, woff2}
```

- `auto` (기본): `match_upm` rescale을 수행했으면 WOFF2, 아니면 TTF.
- `ttf`: 항상 TTF. CJK rescale 시 Chromium에서 안 보일 수 있음을 사용자가 감수.
- `woff2`: 항상 WOFF2. 폰트 크기 ~50% 감소 부수 효과 (brotli 압축).

생성기는 stats에 `outputFormat`을 노출하고, CLI 출력에 `[ttf]` / `[woff2]`를 표시.

## 호환성 매트릭스

| 사용처 | TTF | WOFF2 |
|--------|-----|-------|
| Chrome / Edge / Firefox / Safari | ✓ (단, scale_upem 결과는 NG) | ✓ |
| 시스템 폰트 (macOS / Windows 설치) | ✓ | ✗ (운영체제 미지원) |
| Adobe / 오피스 | ✓ | △ (제품 의존) |
| 인쇄 워크플로우 | ✓ | △ |

웹/문서 표시 용도 → WOFF2. OS 설치/디자인 툴 사용 → TTF. v0.2 시점에선 사용자가 명시적으로 골라야 함.

## 결과 (visual_test)

`--match-upm` + `--output-format auto`로:
- Group A (Noto orig vs Polaris PNM): 라인 16/16 byte-perfect 일치.
- Group B (Pretendard orig vs Polaris NPM): 라인 15/15 byte-perfect 일치.

## 검증

`tests/test_match_upm_and_format.py` 7 tests:
- match_upm rescale 정확성
- match_upm 없을 때 디자인 UPM 보존
- output_format auto: rescale 시 woff2, 아니면 ttf
- 명시적 ttf/woff2 강제
- notdef advance 적용 (P3/A4)
