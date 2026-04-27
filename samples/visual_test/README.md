# Visual test page

원본 폰트 2종 + 교차 합성 2종 = 4개 폰트로 구성된 시각적 비교 테스트 페이지.

## 빌드

```bash
# 프로젝트 루트에서:
python samples/visual_test/build.py

# 그러면 다음 산출물이 생성됨:
#   samples/visual_test/out/index.html
#   samples/visual_test/out/fonts/{4 ttf 파일}
```

## 열람

브라우저는 `file://` 스킴에서 `@font-face` 로딩을 차단하는 경우가 많으므로 로컬 HTTP 서버로 열람합니다:

```bash
cd samples/visual_test/out
python3 -m http.server 8000
# 브라우저: http://localhost:8000/
```

## 페이지 구성

1. **단일 라인 — 4 폰트 동시 비교**
2. **라인브레이크 비교 (핵심)** — 같은 너비 컨테이너에 같은 메트릭 그룹의 두 폰트가 같은 위치에서 줄바꿈하는지 확인.
3. **사이즈 사다리** — 10px ~ 48px.
4. **표 / 숫자 정렬** — 컬럼 너비 비교.
5. **문단 4분할** — 동일 너비, 동일 사이즈에서 메트릭 그룹별 줄바꿈 일치.
6. **글리프 클로즈업** — 외형 차이 직접 확인.

## 메트릭 그룹

| 그룹 | 폰트 | 외형 | 메트릭 |
|------|------|------|--------|
| **A** (파랑) | NotoSansKR Regular (원본) | Noto | Noto |
| **A** (파랑) | Polaris PNM | Pretendard | **Noto** |
| **B** (빨강) | Pretendard Regular (원본) | Pretendard | Pretendard |
| **B** (빨강) | Polaris NPM | Noto | **Pretendard** |

같은 그룹의 두 폰트는 외형이 달라도 advance widths/global metrics가 같으므로 동일한 위치에서 줄바꿈해야 합니다 — Polaris MCFG의 핵심 보장입니다.

## 입력 폰트

- `fonts/Noto_Sans_KR/static/NotoSansKR-Regular.ttf` (OFL, upm=1000)
- `fonts/Pretendard-1.3.9/public/static/alternative/Pretendard-Regular.ttf` (OFL, upm=2048)

UPM 차이는 generator가 자동 스케일링.

## 산출물 디렉토리

`out/`는 `.gitignore`에 의해 제외됩니다. 빌드는 로컬에서만 보관.
