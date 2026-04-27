# 07. 옵션 메트릭 (M5)

## 개요

LSB, kerning, vertical 메트릭은 옵션으로 처리한다 — 모든 폰트가 이를 가지고 있지도 않고, 사용 사례에 따라 비활성화하는 게 합리적일 때도 있다.

## 일관된 옵션 흐름

```
extract  --include-lsb / --include-kerning / --include-vertical
generate --apply lsb / --apply kerning / --apply vertical
validate (자동: spec에 데이터가 있을 때만 lsb_match / kerning_match / vertical_match 체크 추가)
compare  (자동: 양쪽 spec에 데이터가 있을 때만 diff 섹션 추가)
```

각 단계는 독립적이다 — `extract`에서 LSB만 켜고 kerning은 끄는 것이 가능.

## LSB

- 추출: `hmtx` 테이블의 LSB.
- 생성: `--scale-glyph fit` 시 LSB가 자동 스케일링됨. `--apply lsb`가 켜지면 spec의 명시적 LSB로 덮어씀.
- 검증: `lsb_match` 체크는 `actual.glyphs[g].lsb`와 `ref.glyphs[g].lsb`가 둘 다 존재할 때만 수행.

## Kerning

- 추출: classic `kern` 테이블 format 0만 지원.
- 생성: `--apply kerning` 시 `kern` 테이블을 새로 만들어 삽입. 디자인 폰트에 없던 글리프 페어는 skip.
- 비교: 페어 단위로 (left, right) 키 정렬해 차이 보고.
- 검증: `kerning_match` 체크는 양쪽에 kerning 데이터가 있을 때만.

### v2 후보

- GPOS lookup type 2 (pair adjustment) 추출 — fontTools에 도우미가 있으나 lookup unit 다양성 처리 필요.
- GPOS class-based kerning 단순화 → pair list 변환.

## Vertical (vhea/vmtx)

- 추출: `vhea`, `vmtx`가 모두 있을 때만. `vmtx`는 글리프별 advance height와 TSB.
- 생성: 디자인 폰트에 vhea가 없으면 generator가 합성한다 (`fontTools` 빈 테이블 + spec 값 채움).
- 비교/검증: 양쪽에 vertical 섹션이 있을 때만.

세로쓰기 폰트는 한국어 환경에서 드물지만, CJK 한자 사전류, 일본어 작품 등에 필요.

## 결정성 (Determinism)

옵션 메트릭이 추가되어도 `to_json()` 출력은 정렬되어 결정적. 누락된 옵션 섹션은 dict에서 제외됨 → byte-exact 비교에 안전.

## 옵션 메트릭의 라이센스 영향

- LSB는 outline의 일부 정보를 추론할 수 있음 (글리프 폭이 noticeable). 일반적으로 EULA가 메트릭 추출을 명시 금지하지 않으면 문제 없으나, 보수적으로 사용 시에는 LSB를 끄는 것이 안전.
- Kerning 페어 자체는 디자이너의 선택이 반영되므로 저작권 회색지대일 수 있음. 소스 폰트의 EULA/라이센스 검토 시 별도 항목으로 다룰 것.
