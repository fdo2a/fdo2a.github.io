# scripts/us/CLAUDE.md 에서 옮긴 이력 (2026-10-27)

일본 일간 마감브리프를 AGENTS.md 파이프라인 표에 한 줄 더하려면 US 체인(AGENTS.md + US 잎사귀)의
여유가 모자랐다(31,641 / 31,744 B). 규칙 4 대로 잎사귀를 줄이지 않고 **날짜·경위만** 여기로 옮겼다.
의무는 잎사귀에 그대로 남아 있다.

- US 루틴 cron `CRON_TZ=America/New_York 30 17 * * 1-5` 는 2026-10-13 사용자 선택이다. 17:05 국채 마감 뒤라
  EDT 에는 06:30 KST 시작(~07:00 발행), EST 에는 07:30 KST 시작(~08:00 발행) — 계절마다 손댈 일이 없다.
- US 루틴의 MCP 커넥터는 2026-09-24 에 뺐다.
- 섹터 표 세션 검사(`check_sector_perf.py`)는 2026-10-12 사고에서 나왔다.
- FedWatch 확률의 moomoo 원천은 2026-10-01 에 뺐다(이후 웹 리서치만).
- FRED 키 건강 검사가 `api_key_rejected` 에서만 빨강인 것은 2026-10-22 사용자 지시다.

## 2026-11-06 — 「국채 입찰」 한 줄을 넣으려고 더 옮긴 것

US 체인 31,631 / 31,744 B 에서 입찰 섹션 안내가 들어가지 않아 같은 방식으로 날짜·경위만 옮겼다.

- `data-standing` 문단의 120자 하한은 2026-10-13 에 없앴다.
- 월간 정리는 2026-10-27 에 폐지됐다(주간만 남았다).
- US 주간이 인사이트 리포트가 된 것과 루틴 잠금·뉴스 동결은 둘 다 2026-09-26 이다.
- 무게중심 게이트가 막으려던 실패(판단·포지션에 분량을 쓰고 `price_context` 의 위치 어휘를 매일 버린 것)는
  `2026-08-30-recap-weight-rebalance-design.md` 에 있다.
- 2Y 만 FRED DGS2 인 이유: Yahoo 에 쓸 만한 2년 현물 지수가 없다(`2026-09-05-us-fred-api-design.md`).

## 2026-11-06 — 원문 수집 계약 한 줄을 넣으려고 더 옮긴 것

- US 브리프의 전체 이력은 프로젝트 메모리 `us-morning-brief-project` 에 있다(잎사귀 머리에서 뺀 문장).
- 원문 수집의 TLS 위장 이유(bls.gov·dol.gov 가 일반 클라이언트에 403)는 `scripts/fetch_releases.py` 머리 주석에 있다.


## 2026-11-07 — 「유동성·수급」 항목을 넣으려고 옮긴 근거 문장

US 체인이 31,744 B 를 넘어 잎사귀의 근거·이력 문장을 여기로 옮겼다(의무 문장은 잎사귀에 그대로).

- §4 (yield moves) used to say only "how much" and leave the cause blank; that is why it is decomposed.
- Fed transcript: the failure being prevented is invented quotes, not invented numbers.
- Macro falsifier: the reader must be able to distinguish the policy hypothesis from its falsifier.
- macro_next.axis_directions: miss it and a day whose axes actually flipped still folds.
- data-cause exemption for 미미/보통 is why there is no fixed character-count floor.
- fred_series full history: macro_metrics computes 60-point momentum and 12-point YoY from it.
- Weekly trigger check: the routine file existing is not the same as it being scheduled.
