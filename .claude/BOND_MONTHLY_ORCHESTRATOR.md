# 글로벌 채권 월간 정리 — 파이프라인

**대부분의 실행은 아무것도 하지 않고 끝나야 한다.** 달 경계를 놓치지 않으려 여러 날
뜨므로, STEP 0에서 롤오버가 아님을 확인하면 즉시 종료한다(토큰 낭비 금지).

## STEP 0 — 롤오버 판정

원장 마지막 행의 달과 직전 발행된 월간의 달을 비교한다. 같으면 종료.

## STEP 1 — 집계

```
python3 scripts/build_bond_period.py --span monthly
```

산출은 `bond/monthly/<키>.html` 과 집계 파일 `bond/data/period_monthly_<키>.json` 이다. 집계는 원장의 양 끝을 맞댄 값이라
중간 경로는 담기지 않는다 — 경로는 일간 리포트에 있다.

```

산출은 `bond/monthly/<YYYY-MM>.html` 과 집계 파일
`bond/data/period_monthly_<YYYY-MM>.json` 이다.

주간 행을 롤업하므로 **같은 기간을 두 번 세지 않는다.**

## STEP 2 — 작성·발행

주간과 같되 시계가 한 달이다. 월간에서만 할 수 있는 이야기를 쓴다 —
커브 모양이 한 달 사이 어떻게 바뀌었는가, 크레딧 백분위가 어디서 어디로 갔는가,
뷰 3축이 몇 번 움직였고 그중 몇 번이 되돌려졌는가.

## STEP 3 — 게이트·발행

```
python3 scripts/apply_readability.py        bond/monthly/<YYYY-MM>.html
python3 scripts/check_bond_period.py --html bond/monthly/<YYYY-MM>.html
python3 scripts/check_readability.py --html bond/monthly/<YYYY-MM>.html
python3 scripts/check_style.py              bond/monthly/<YYYY-MM>.html
```

기간 게이트는 일간과 **다른 것**을 본다 — 인용 가능한 수치가 집계 파일과 그 기간
발행본 둘뿐이고, 커버 기간·실제 세션 경계를 반드시 밝혀야 하며, 구간을 다 못 덮으면
그 사실을 고지해야 한다. 월간은 달 첫날·마지막날이 주말이면 구간이 안 덮이는 것이
정상이므로, 「덮인 구간만 말한다」는 문장이 본문에 남아야 한다.

통과하면 `bond/monthly.json`에 등록하고 sitemap 갱신 후 push.
