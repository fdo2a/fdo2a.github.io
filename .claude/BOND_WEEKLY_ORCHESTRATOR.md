# 글로벌 채권 주간 정리 — 파이프라인

일요일 실행. 그 주에 발행한 일간 리포트들의 **총정리**다. 시장을 새로 취재하는 글이
아니라 이미 나간 글을 읽고 한 편으로 묶는 글 — **웹 검색 금지·시세 재수집 금지**.

## STEP 0 — 커버 기간 확정

`bond/data/history/bond_market.jsonl`의 마지막 행에서 ISO 주를 잡는다
(`scripts/bond/period.py`의 `iso_week_key`). 그 주에 발행본이 2편 미만이면
**아무것도 하지 않고 끝낸다.**

## STEP 1 — 집계

```
python3 scripts/build_bond_period.py --span weekly
```

산출은 `bond/weekly/<키>.html` 과 집계 파일 `bond/data/period_weekly_<키>.json` 이다. 집계는 원장의 양 끝을 맞댄 값이라
중간 경로는 담기지 않는다 — 경로는 일간 리포트에 있다.

```
```

`period.build()`가 원장을 굴려 기간 성과표를 만든다. **본문 서술은 발행본, 성과표는
집계 파일** — 소스가 갈린다. 「이번 주 10년물 +12bp」는 하루 변화의 합이라
에이전트가 계산하면 안 된다.

## STEP 2 — 작성

`period-report-writer`가 market=`bond`, span=`weekly`로 쓴다.

- **5편 요약 나열 금지.** 한 편의 서사로 묶는다 — 월요일에 던져진 질문이 목요일에
  어떻게 답해졌는지가 보이게.
- 복기는 **틀린 것부터**. 뷰 3축이 움직였다면 `stance_changes()`가 뽑은 지점마다
  「트리거는 옳았는데 시장이 안 따라왔나」와 「트리거 설계가 틀렸나」를 구분한다.
- 표본이 모자라면 「누적 표본 부족」을 명시한다. 몇 개로 적중률을 인쇄하는 것은
  성적표가 아니라 소음이다.

산출은 `bond/weekly/<ISO주>.html`.

## STEP 3 — 게이트·발행

```
python3 scripts/apply_readability.py    bond/weekly/<키>.html
python3 scripts/check_bond_period.py --html bond/weekly/<키>.html
python3 scripts/check_readability.py --html bond/weekly/<키>.html
python3 scripts/check_style.py             bond/weekly/<키>.html
```

기간 게이트는 일간과 **다른 것**을 본다 — 인용 가능한 수치가 집계 파일과 그 기간
발행본 둘뿐이고, 커버 기간·실제 세션 경계를 반드시 밝혀야 하며, 구간을 다 못 덮으면
그 사실을 고지해야 하고, 표본이 모자란데 적중률을 인쇄하면 막힌다.
그 기간 발행본을 하나라도 목록에서 빠뜨려도 막힌다.

통과하면 `bond/weekly.json`에 등록하고 sitemap 갱신 후 push.
