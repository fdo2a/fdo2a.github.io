# 미국·한국 증시 일간 브리프 — fdo2a.github.io

미국장과 한국장이 끝날 때마다 시장 브리프를 자동으로 만들어 발행하는 개인 리서치 프로젝트입니다. 2026년 7월부터 발행하고 있습니다.

- **미국 브리프**: 한국 시간 아침, 전 거래일 미국장 마감 기준 → [사이트](https://fdo2a.github.io/) · [발행본 폴더](posts/)
- **한국 브리프**: 평일 저녁, 당일 한국장 마감 기준 → [발행본 폴더](kr/posts/)

브리프 문장은 AI(Claude)가 씁니다. 이 레포의 핵심은 **AI가 쓴 글의 숫자를 발행 전에 어떻게 검증하는가**입니다.

---

## 숫자가 글에 들어가기까지: 검증 4단계

원칙은 세 가지입니다.

1. AI가 숫자를 직접 찾아오지 못하게 한다.
2. AI가 쓴 숫자는 프로그램이 원천 데이터와 대조한다.
3. 프로그램이 못 보는 부분은 발행 후 다시 검토하고, 최종 판단은 사람이 한다.

### 1단계 · 수집 — 다 모이지 않으면 쓰지 않는다

장이 끝나면 GitHub Actions가 파이썬 코드로 데이터를 받아 파일 하나(`data/market_data.json`)에 저장합니다.

| 데이터 | 출처 |
|---|---|
| 미국 금리·경제지표 | FRED 공식 API |
| 경제지표 보도자료 원문 | BLS·BEA·Census 등 발표 기관 |
| 지수·원자재·환율 | Yahoo Finance |
| 한국 국고채·기준금리 | 한국은행 ECOS API |
| 한국 수급·업종 | 네이버 증권 |

받은 뒤 **완성도 검사**가 돕니다. 주요 지수·섹터·국채 4개 만기·환율·원자재 중 하나라도 비거나 날짜가 맞지 않으면 그 항목을 `missing`에 적고, 브리프를 발행하지 않습니다. 빈칸을 다른 값으로 채우지 않습니다.

- [수집 코드 `collect_market_data.py`](https://github.com/fdo2a/fdo2a.github.io/blob/main/scripts/collect_market_data.py) · [완성도 검사 (732행)](https://github.com/fdo2a/fdo2a.github.io/blob/main/scripts/collect_market_data.py#L732)
- [매일 자동 실행 설정](.github/workflows/collect-market-data.yml) · [실행 기록 (Actions)](https://github.com/fdo2a/fdo2a.github.io/actions)
- [FRED 연결](scripts/us/fred.py) · [ECOS 연결](scripts/kr/econ.py) · [보도자료 원문 받기](scripts/fetch_releases.py)

### 2단계 · 기준 맞추기 — 같은 표의 숫자는 같은 시점이어야 한다

Yahoo 일봉의 원자재 종가가 장 마감가가 아니라 수집 시각의 시간외 가격인 것을 발견했습니다(2026-10-12 Brent: 발행 105.70, 결제가 106.65). 환율 일봉도 ECB 기준환율 역산과 맞지 않았습니다. 그래서 원자재·환율은 **30분봉에서 뉴욕 16:00 ET 가격**을 쓰도록 바꿔 주식 마감과 시점을 맞췄고, 선물은 연속 티커 대신 해당 월물 티커로 잽니다.

- [기준 맞추기 코드 `close_cut.py`](scripts/us/close_cut.py) — 파일 맨 위에 발견 경위와 바꾼 이유가 있습니다.

### 3단계 · 작성 — AI는 수집한 파일만 보고 쓴다

Claude는 인터넷에 직접 접속하지 않고 1·2단계에서 만든 파일만 읽고 씁니다. 작성 규칙은 코드가 아니라 지시문으로 정합니다.

- [작성 지시문](.claude/agents/brief-report-writer.md) · [전체 진행 순서](.claude/ORCHESTRATOR.md)

### 4단계 · 발행 게이트 — 본문을 데이터와 대조한다

글이 완성되면 섹션마다 만든 검사 스크립트가 순서대로 돕니다. 하나라도 어긋나면 어느 문장이 왜 틀렸는지 출력하고 발행을 멈춥니다. 그 출력을 AI에게 그대로 돌려줘 그 문단만 고치게 하고, 전부 통과해야 발행됩니다.

| 검사 | 보는 것 |
|---|---|
| [숫자 대조 `number_forms`](https://github.com/fdo2a/fdo2a.github.io/blob/main/scripts/us/section.py#L76) | 본문 숫자가 데이터 값에서 나올 수 있는 표기(반올림 포함)인지 |
| [매크로 `macro_gate.py`](scripts/us/macro_gate.py) | 경기 판단 숫자, 새 지표 발표 없이 판단을 바꾸지 않았는지 |
| [연준 인용 `fed_gate.py`](scripts/us/fed_gate.py) | 발언 인용이 수집한 원문에 글자 그대로 있는지 |
| [출처 `check_sources.py`](scripts/check_sources.py) | 링크가 그날 수집한 문서인지 |

전체 검사 목록은 [`scripts/`](scripts/) 폴더의 `check_*.py` 파일입니다.

---

## 한계와 보완: 발행 후 검토

숫자 검사는 그 숫자가 데이터에 **있는지**만 봅니다. **맞는 자리에 쓰였는지**는 모릅니다. 그래서 발행 후 Codex가 읽기 전용으로 수치·방향·날짜를 다시 대조하고, 지적은 원자료로 확인해 사실 오류면 정정하고 오독이면 기각합니다.

- [정정 기록 모아 보기](https://github.com/fdo2a/fdo2a.github.io/commits/main?search=정정)
- 정정 예: [2026-10-26 「2년물만 올랐다」 → 「2·5년물만 올랐다」](https://github.com/fdo2a/fdo2a.github.io/commit/9ed54cb) — 숫자는 맞았지만 문장이 틀린 경우
- 기각 예: [2026-11-03 지적 5건 모두 기각·보류](https://github.com/fdo2a/fdo2a.github.io/commit/fe3d2bb)
- [검토 원장 `reviews/index.json`](reviews/index.json)

---

## 폴더 안내

| 폴더 | 내용 |
|---|---|
| `posts/` · `kr/posts/` | 미국·한국 일간 발행본 |
| `data/` · `kr/data/` | 수집 데이터 (`history/` 에 날짜별 이력) |
| `scripts/` | 수집·검사·조판 코드 |
| `.claude/` | AI 작성 지시문과 진행 순서 |
| `reviews/` | 발행 후 검토 원장 |
| `weekly/` · `japan/` · `news/` · `thesis/` | 주간 정리, 일본 시장, 뉴스·산업, 종목 점검 |

정보 제공 목적이며 투자 권유가 아닙니다.
