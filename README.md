# Polaris MCFG

**Metric-Compatible Font Generator**

한컴 폰트와 같이 라이센스가 제한된 폰트의 **레이아웃 메트릭**(advance width, ascender/descender, line gap 등)을 추출하여, 자유 라이센스 폰트의 **글리프 디자인**에 결합한 새로운 폰트를 생성하는 도구. 원본 문서의 줄바꿈/페이지 분할을 유지하면서도 라이센스 안전성을 확보합니다.

> 본 도구는 글리프 외형(outline)을 추출/복제하지 않으며, 숫자 메트릭만 다룹니다. 자세한 내용은 [Requirements.md](Requirements.md) 6장 참고.

## 구성

| 서브커맨드 | 설명 |
|-----------|------|
| `mcfg extract` | 폰트에서 메트릭을 추출하여 JSON으로 저장 |
| `mcfg compare` | 두 폰트(또는 메트릭 JSON) 비교 |
| `mcfg generate` | 메트릭 + 디자인 폰트 → 새 폰트 |
| `mcfg validate` | 결과 폰트가 메트릭과 일치하는지 검증 |

## 빠른 시작

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
mcfg --help
pytest
```

자세한 요구사항/설계는 [Requirements.md](Requirements.md), [docs/design/](docs/design/) 참고.
