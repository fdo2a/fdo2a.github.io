# DART(OpenDART) 공시 연동 — thesis 파이프라인 사건 트리거 기계화

작성 2026-09-21. 대상 `scripts/thesis/disclosure.py`, `scripts/collect_thesis_data.py`,
`.github/workflows/collect-thesis-data.yml`.

## 왜 했나

`scripts/thesis/CLAUDE.md` 의 미완 항목이 **「사건 트리거가 아직 프롬프트 규칙뿐(수치 트리거만
기계화됨)」** 이었다. 이 파이프라인의 존재 이유는 "변화가 없는 날엔 아무것도 하지 마"를
프롬프트가 아니라 상태 파일과 게이트로 못 박은 것인데, 판정의 두 축 중 사건 축만 프롬프트에
남아 있었다. 매일 저녁 "thesis 가 움직였나"를 묻는 에이전트는 충분한 저녁이 지나면 움직였다고
답한다 — `gate.check_silence` 가 수치 축에 대해 막고 있던 바로 그 실패가 사건 축에는 열려
있었다.

## 설계 원칙: 구멍을 채운다, 넓히지 않는다

코드에 사건 축을 받을 자리가 이미 셋 뚫려 있었고, 전부 빈 인자로 호출되고 있었다.

| 자리 | 원래 상태 | 지금 |
|---|---|---|
| `triggers.kill_axes(hits, event_axes=())` | `event_axes` 항상 빔 | `disclosure.event_axes()` 가 공급 |
| `gate.check_silence(triggers, events, …)` | `events` 를 채우는 기계 없음 | 공시가 `confirmed` 로 채움 |
| `state.propose(…, kill_evidence=())` | contract 축 도달 불가 | 공시로만 도달 |

`triggers.evaluate()` 는 **건드리지 않았다.** 그 함수는 순수·수치 전용 계약이고, 공시는
성격이 다르므로 별도 모듈로 분리했다. `watch.json`·`history.jsonl` 에도 넣지 않는다 —
세 번째 산출물 `thesis/data/disclosures.json` 이다.

## 급소: 화이트리스트

삼성전자·SK하이닉스는 하루 공시가 수십 건이다(계열사, 임원 소유변동, 정정). 전부
`confirmed: True` 로 넘기면 **매일이 사건인 날이 되어 침묵 게이트가 죽는다.** 이 파이프라인이
막으려던 실패가 정확히 재현된다. 따라서 `confirmed` 는 화이트리스트로만 준다.

`disclosure.CONFIRMED` 가 정본이다. 축 배정의 규율:

- **`contract`** — 단일판매·공급계약체결, 영업(잠정)실적, 매출액또는손익구조 변동.
  `state.KILL_AXES` 에 들어가는 **유일한** 사건 축이다.
- **`capital`** — 유·무상증자, CB·BW·EB 발행, 자기주식 취득·처분·소각.
- **`ownership`** — 주식등의대량보유상황보고서(5% 룰).
- **`financials`** — 정기보고서. BVPS 갱신 신호.

`capital`·`ownership`·`financials` 는 **kill 축이 아니다.** 한 문장 쓸 가치가 있는 사건이지
thesis 가 깨졌다는 증거가 아니다. 증자 공시로 kill 이 열려선 안 된다.

`confirmed: False` 로 기록만 하는 것:

- **정정공시** (`[기재정정]` `[첨부정정]` 등) — 원 공시가 이미 사건으로 잡혔다. 다시 세면
  하나의 사건이 두 번 보고된다. `triggers._armed` 가 수치 쪽에서 막는 것과 같은 실패다.
- **임원·주요주주특정증권등소유상황보고서** — 빈도가 높고 신호가 약하다.
- 화이트리스트 밖 전부.

**화이트리스트가 너무 넓어지는 것이 이 연동의 유일한 위험한 실패 방향이다.** 발행 후
`disclosures.json` 의 `confirmed_count` 를 세어 검증한다. 조용한 날이 실제로 조용한지가 기준.

## 표기 정규화

DART 는 같은 공시명을 `ㆍ`(U+318D)·`·`(U+00B7)·`・`(U+30FB) 로 섞어 쓴다. 리터럴 비교는
공시를 조용히 놓친다. `_NOISE` 가 중점·공백·괄호를 걷어낸 뒤 부분일치로 판정한다.

## 조회 창

`history.jsonl` 마지막 기록일 ~ 오늘, 최대 30일. 오늘 행을 **append 하기 전에** 이력을 읽어야
한다 — 순서가 뒤집히면 창이 오늘 하루로 줄어 실패했던 날이 영영 안 메워진다.

**18:00 문제**: thesis 수집은 08:40 UTC = 17:40 KST 인데 DART 는 18:00 까지 접수한다. 그날
늦은 공시는 다음 창에 걸린다 — 누락이 아니라 하루 지연이며, 창이 날짜 범위라 새지 않는다.
수집 시각을 늦추는 것은 해법이 아니다(KR 브리프 09:00 UTC push 와 부딪힌다).

## corp_code

매핑표 전체(`corpCode.xml`)는 20MB 짜리 zip 이라 두 종목은 `DART_CORPS` 상수로 둔다. 대신
**매 수집마다 `company.json` 의 `stock_code` 로 대조**한다(`verify_corp`). ECOS 의 교훈은
"코드를 하드코딩하지 마라"가 아니라 **"조용히 실패하게 두지 마라"** 였다 — 틀린 고유번호는
오류가 아니라 「조회 결과 없음」으로 돌아와 조용한 날과 구분되지 않는다. 검증 실패는 그 종목만
건너뛰고 `missing` 에 남긴다.

Micron 은 미국 상장사라 DART 에 없다. `DART_CORPS` 에 넣지 않는다.

## BVPS (P/B 분모)

`collect_thesis_data.apply_dart_book_value()` 가 yfinance 장부가를 공시 재무제표로 갈아끼운다.

- 자본: `fnlttSinglAcntAll.json` — **지배기업 소유주지분 우선**, 없으면 자본총계.
  비지배지분을 섞으면 P/B 가 조용히 낮아진다.
- 주식수: `stockTotqySttus.json` 보통주 발행총수 − 자기주식.
- **둘을 같은 보고서에서 가져온다.** 섞으면 어느 공시에도 없는 숫자가 나온다.
- `bvps_source` 로 `dart|yfinance` 를 명시하고 `bvps_as_of` 는 `2026-Q2` 형태 기간 라벨.

**정직한 한계**: 이득은 "공시 당일 반영"이 아니다. 분기보고서는 분기 종료 후 약 45일에
접수되고 잠정실적 공시는 자본총계를 담지 않는다. **yfinance 대비 약 한 분기 단축**이 전부다.
2026-08 하이닉스가 8월에 Q1 기준 P/B 7.46배를 띄우던 지연이 사라지는 것.

**부작용을 알고 넣었다**: `bvps` 는 `valuation.fair_value()` 의 자산법 다리를 움직인다.
전환되는 날 bear 선이 이동하며 `bear_proximity` 가 한 번 발화할 수 있다. `triggers.evaluate()`
가 그것을 「추정치가 무너져 기준선이 이동」으로 보고하는데, 실제로 일어난 일이 그것이므로
오탐이 아니다. 주가가 움직인 것이 아니라 선이 움직였다고 정확히 말한다.

## 보안 — ECOS 와 패턴이 다르다

ECOS 는 인증키를 **URL 경로**에 넣고 `kr/econ.py` 의 `scrub()` 이 `(/api/[A-Za-z]+/)([^/\s]+)`
로 가린다. DART 는 **쿼리스트링**(`crtfc_key=`)에 넣는다. **그 정규식을 복사하면 구멍이
남는다.** `disclosure.scrub()` 은 쿼리 파라미터 패턴과 `os.environ` 값을 **둘 다** 지운다 —
한쪽만으로는 부족하다(키 미설정 시 URL 이 그대로 나가거나, URL 밖 에코를 놓친다).
`_get()` 은 원본 예외를 절대 올리지 않는다. 예외 문자열에 URL 이, URL 에 키가 들어 있다.

키는 레포 시크릿 `DART_API_KEY`, 워크플로 `env` 로만 주입. 로컬 env 에 두지 않는다.

## 비-코어

키 미설정·DART 장애·네트워크 실패 모두 "오늘 사건 없음"으로 끝난다. 안전한 방향으로
실패한다. `REQUIRED` 에 넣지 않으며 수집을 막지 않는다. 키가 없으면 `disclosures.json` 에
`pending: true` 를 쓴다(`kr_econ.json` 선례).

## 열린 항목

- `check_thesis.py` 에 「페이지가 인용한 rcept_no 가 `disclosures.json` 에 실재하는가」 검사
  미추가. 모든 `<cite>` 를 DART 로 강제하면 IR·고객사 발표를 못 쓰므로 범위를 좁혀야 한다.
- `DART_CORPS` 의 고유번호 두 개는 첫 Actions 실행의 `verify_corp` 로 확인된다. 실패하면
  `missing` 에 `005930.KS:corp_code` 형태로 남으므로 그때 정정한다.
- KR 브리프 §9 특징주 연동은 2단계. 종목명 → 종목코드 → 고유번호 2단 매핑이 필요하고,
  이름 매칭은 ETF 정규화에서 이미 깨진 전례가 있다.
- codex 검토 미실시(7단계 루틴 STEP 2·5). 커밋 전 필수.
