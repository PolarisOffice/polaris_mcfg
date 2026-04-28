# Contributing to Polaris MCFG

기여를 검토해주셔서 감사합니다. 본 문서는 PR/이슈를 효율적으로 처리하기 위한 가이드입니다. 처음 기여하시는 경우 [README.md](README.md) → [Requirements.md](Requirements.md) → [ROADMAP.md](ROADMAP.md) 순서로 읽기를 권장합니다.

## 행동 강령

이 프로젝트는 [Contributor Covenant 2.1](CODE_OF_CONDUCT.md)을 따릅니다. 참여 시 동의하는 것으로 간주합니다.

## 시작하기

### 환경 셋업

```bash
git clone https://github.com/Miles-Haeseok-Lee-80/polaris_mcfg
cd polaris_mcfg
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest -v   # 84 tests, ~0.3s
```

> Python 3.10 이상 필요. 의도적으로 PyPI 배포는 하지 않습니다 ([ROADMAP §3 데이터/인프라](ROADMAP.md)).

### 데모 빌드 (선택)

```bash
python docs/demo/build.py    # docs/demo/{index.html, fonts/*.woff2}
cd docs/demo && python3 -m http.server 8000
```

라이브 데모 검증용. PR이 데모 출력을 바꾸면 빌드 후 브라우저로 직접 확인하세요.

## PR 워크플로우

1. **이슈 먼저** — 큰 변경(아키텍처, 새 의존성, 신규 lookup type 처리 등)은 PR 전에 이슈로 논의를 권장합니다. 작은 fix(오타, 테스트 추가, 문서 수정)는 바로 PR 가능.
2. **브랜치 명명** — `feat/...`, `fix/...`, `docs/...`, `test/...` 접두사 사용.
3. **테스트 추가** — 동작이 바뀌는 PR은 회귀 테스트 동반. 테스트 fixture 패턴은 `tests/conftest.py`의 `make_test_font`를 참조.
4. **커밋 메시지** — 영어 또는 한국어 모두 OK. 첫 줄은 imperative mood (예: `Add GPOS pair-positioning extraction`), 본문은 *왜*를 설명.
5. **CI 통과 필수** — `.github/workflows/ci.yml`이 자동 실행. {Linux, macOS, Windows} × Python {3.10–3.13} 매트릭스 + sdist/wheel 빌드. 빨간 X 있으면 머지 안 됨.

### 머지 전 체크리스트

- [ ] `pytest -v` 로컬에서 모두 통과
- [ ] 새 동작에 회귀 테스트 추가
- [ ] 영향 받는 [docs/design/](docs/design/) 문서 갱신
- [ ] [CHANGELOG.md](CHANGELOG.md)에 변경 기록 (Added / Changed / Fixed / Deprecated 섹션)
- [ ] 새 OpenType 테이블 / lookup type을 다룬다면 [라이센스 안전 경계](docs/design/02-metrics-schema.md#라이센스-안전-경계) 점검
- [ ] CI 매트릭스 모든 잡 통과 (12개 + build 1개)

## 라이센스 안전 정책 (중요)

본 프로젝트의 핵심 보장은 **"글리프 외형(outline) 데이터를 절대 추출/복제하지 않는다"** 입니다. 이 정책을 깨는 PR은 **머지하지 않습니다**:

- ❌ `glyf` / `CFF` / `CFF2` / `COLR` / `sbix` / `SVG` 테이블의 outline/raster 데이터를 읽기
- ❌ `extract_metrics()`가 outline-bearing 테이블에 lazy-access하지 않도록 강제하는 회귀 테스트(`test_glyf_table_not_loaded_during_extraction`) 우회

설계 의도가 강하게 반영되는 데이터(예: contextual GSUB substitution, mark anchor 좌표)를 추가로 다루는 경우:
- **opt-in 플래그로 분리** (현재 `--include-gsub`, `--apply gsub` 패턴 따라하기)
- design 문서에 라이센스 영향 명시
- 보수적 사용자가 기본값으로 회피 가능해야 함

## 새로운 영역에 기여할 때

[ROADMAP.md §3](ROADMAP.md#3-로드맵)에 등재된 항목 (R1, R2, R-ci 등)이 우선순위 가이드입니다. 등재 안 된 신규 영역은 이슈로 먼저 논의:

- **새 스크립트 지원** (Arabic, Indic 등) → 회귀 테스트 + 시각 검증 페이지(`samples/visual_test` 스타일) 동반
- **새 OT 테이블 추출** → §라이센스 안전 정책 점검
- **새 출력 포맷** (예: WOFF, EOT) → 사용 사례 명확히

[ROADMAP §4 명시적 out-of-scope](ROADMAP.md#4-명시적으로-out-of-scope) 영역(AAT/Graphite, color/bitmap, outline 추출, GUI-우선)은 PR로도 받지 않습니다.

## 문서 / 디자인 결정

설계 결정은 `docs/design/<NN>-<topic>.md`에 기록합니다. 새 디자인 문서:
- 번호 순차 (현재 11번까지 사용 중)
- 한국어 본문, 코드 식별자/명령은 영어
- 섹션 구조: 목적 → 책임 → 입출력 → 알고리즘 / 예시 → 알려진 한계 / 향후 확장

## 보안 취약점

공개 이슈에 게시하지 마세요. [SECURITY.md](SECURITY.md)의 비공개 채널을 사용하세요.

## 라이센스

본 프로젝트에 기여하시는 모든 코드/문서/테스트는 [MIT License](LICENSE) 하에 라이센스됩니다. 이를 동의하지 않는 경우 PR을 보내지 마세요.

폰트 자산을 PR에 첨부하지 마세요 — 라이센스 위험이 큽니다. 폰트 정보는 [.github/ISSUE_TEMPLATE/bug_report.yml](.github/ISSUE_TEMPLATE/bug_report.yml)의 양식에 맞춰 *메타데이터만* 제공.
