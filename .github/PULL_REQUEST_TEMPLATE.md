<!--
PR 제출 전 [CONTRIBUTING.md](../CONTRIBUTING.md)의 머지 전 체크리스트를 확인해주세요.
큰 변경은 이슈로 먼저 논의 권장.
-->

## 변경 사항 요약

<!-- 한 문단으로: 무엇을, 왜 바꿨는지 -->


## 종류

- [ ] 🐛 Bug fix (회귀 테스트 동반)
- [ ] ✨ Feature
- [ ] 🔬 Refactor (동작 변경 없음)
- [ ] 📚 Docs / Design
- [ ] 🧪 Tests
- [ ] 🏗 Infra (CI, packaging, gitignore 등)

## 영향 받는 모듈

- [ ] `extractor` (메트릭 추출 정책 / OpenType 테이블 처리)
- [ ] `generator` (cross-pollination 알고리즘 / 출력 포맷)
- [ ] `comparator` (diff 형식 / threshold 정책)
- [ ] `validator` (검증 체크 / SLA)
- [ ] `render` (HarfBuzz 통합)
- [ ] `report` (HTML 출력)
- [ ] `schema` (MetricsSpec)
- [ ] `cli` (인터페이스)
- [ ] docs / 문서
- [ ] CI / packaging / infra

## 라이센스 안전 점검

본 PR이 새 OpenType 테이블이나 lookup type을 추출하나요?

- [ ] 아니요 (스킵)
- [ ] 예 — outline 데이터에 접근하지 않음을 회귀 테스트로 검증
- [ ] 예 — 디자이너 의도가 반영되는 데이터(예: GSUB)는 opt-in 플래그로 분리

자세한 정책: [docs/design/02-metrics-schema.md §라이센스 안전 경계](../docs/design/02-metrics-schema.md#라이센스-안전-경계)

## 체크리스트

- [ ] 로컬 `pytest -v` 통과
- [ ] 새 동작에 회귀 테스트 추가 (또는 N/A 사유 기재)
- [ ] 영향 받는 `docs/design/*.md` 문서 갱신
- [ ] [CHANGELOG.md](../CHANGELOG.md)에 변경 기록
- [ ] [ROADMAP.md](../ROADMAP.md) 갱신 필요 시 반영 (지원 매트릭스 / 한계 / 로드맵 항목 이동)

## 관련 이슈 / 로드맵

<!-- Closes #N, Refs #M, ROADMAP R-ci 등 -->


## 추가 컨텍스트

<!-- 스크린샷, 대안, trade-off 등 -->
