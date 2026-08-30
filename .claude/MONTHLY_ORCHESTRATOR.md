# 월간 정리 파이프라인 (월 롤오버 다음날)

US·KR 월간 정리 2편을 발행한다. **그 달 발행본의 총정리**이지 새 취재가 아니다 — 웹 검색도 시세 재수집도 하지 않는다.

## STEP 0 — 월이 넘어갔는가 (먼저 확인하고, 아니면 즉시 끝낸다)

이 트리거는 달 경계를 놓치지 않으려고 여러 날에 걸쳐 뜬다. **대부분의 실행은 아무것도 하지 않고 끝나야 한다.**

`report_date`가 속한 달이 아니라 **직전 달 M이 닫혔는가**를 본다. 세 조건이 모두 참일 때만 진행한다.

1. `data/market_data.json`의 `report_date`가 **M보다 뒤의 달**에 있다 — 즉 달이 넘어갔다
2. `data/monthly/<M>.json`이 있고 `complete: true`다
3. `monthly/<M>.html`이 아직 없다

하나라도 어긋나면 「월 롤오버 아님 — 종료」를 남기고 **즉시 끝낸다.** 리서치도 파일 읽기도 더 하지 않는다 — 토큰 낭비다.

**「집계 파일이 있다」만으로 판단하지 않는다** — 수집기는 당월 집계를 매일 갱신하므로 새 달 이틀째에도 1세션짜리 당월 파일이 존재한다. 그걸 롤오버로 읽으면 한 달을 이틀로 정리해 발행한다(2026-08-30 codex 검토).

## STEP 0-b — 준비와 기간 키

레포(`fdo2a/fdo2a.github.io`)를 클론하고 워크스페이스로 삼는다.

```bash
python3 -c "import sys,json;sys.path.insert(0,'scripts');from us.period import month_key;print(month_key(json.load(open('data/market_data.json'))['report_date']))"
```

이 값이 `<KEY>`(예: `2026-08`)다. **날짜 산술로 도출하지 않는다** — 2026-07-13 중복 생성 직전까지 갔던 버그와 같은 부류다.

## STEP 1 — 집계 파일 확인

`data/monthly/<KEY>.json`과 `kr/data/monthly/<KEY>.json`이 있고 `complete: true`인지 본다.

없거나 `complete: false`면 **PushNotification으로 알리고 중단한다.** 완성본만 발행한다 — 반쪽 집계로 낸 총정리는 다음 달에 정정할 방법이 없다.

이 집계는 시세를 다시 받지 않는다. 일별 스냅샷 원장(`data/history/market.jsonl`·`kr/data/history/kr_market.jsonl`)을 굴린 것이라 **끝값이 그 기간 마지막 발행본의 종가와 같아야 한다.** 다르면 원장이 어긋난 것이니 발행하지 말고 알린다 — 2026-08-30에 시세를 다시 받던 집계가 10년물·금·원달러를 발행본과 다르게 실어 주간본을 회수했다.

## STEP 2 — 발행본 회수

```bash
python3 scripts/build_recap_source.py --posts-dir posts --listing posts.json \
  --start <START> --end <END> --span monthly --key <KEY> --out recap_us.json
python3 scripts/build_recap_source.py --posts-dir kr/posts --listing kr/posts.json \
  --start <START> --end <END> --span monthly --key <KEY> --out recap_kr.json
```

`<START>`·`<END>`는 집계 파일의 `start_date`·`end_date`다. **발행본이 0편이면 중단한다** — 총정리할 원본이 없다. 스크립트가 exit 1로 알린다.

`missing`에 남은 날이 있으면 그대로 진행하되 **그 사실을 본문에 밝힌다.**

## STEP 3 — 스코어카드

```bash
python3 scripts/build_scorecard.py --agg data/monthly/<KEY>.json --datadir data \
  --spans 3,12 --no-append --out data/period_scorecard.json
```

**`--no-append`가 붙는 이유**: 월간은 주간 행을 롤업하므로 같은 기간을 이력에 두 번 세면 안 된다. 첫 몇 회차는 `rollup`이 `insufficient: true`로 나오는 것이 정상이다.

## STEP 4 — US 주간 정리

`period-report-writer` 서브에이전트를 `market=us, span=monthly`로 부른다. 입력은 `recap_us.json`·`data/monthly/<KEY>.json`·`data/period_scorecard.json`·`data/history/*.jsonl`. 산출은 `monthly_<KEY>.html`.

**발행 게이트:**

```bash
python3 scripts/check_period.py --html monthly_<KEY>.html --agg data/monthly/<KEY>.json \
  --recap recap_us.json --scorecard data/period_scorecard.json --span monthly
```

위반이 나오면 **목록을 그대로 writer에게 돌려주고 다시 돌린다.** 게이트를 우회하지 않는다.

이어서 조판·문체 게이트를 일간과 동일하게 돌린다.

```bash
python3 scripts/apply_readability.py $(pwd)/monthly_<KEY>.html
python3 scripts/check_readability.py --strict $(pwd)/monthly_<KEY>.html
python3 scripts/check_style.py $(pwd)/monthly_<KEY>.html
```

**`check_weight.py`는 돌리지 않는다.** 그 게이트는 일간의 섹션 제목(「주식」·「채권」·「매크로 논리」)과 무게중심 비율을 검사하는데, 총정리는 5섹션 구조라 그 잣대가 맞지 않는다. 기간용 무게중심 판정은 아직 없다(2026-08-30 codex 검토에서 확인).

**STEP 4-b — AI 티 제거.** 일간과 같은 관문을 지난다. 원본은 손대지 않고 사본에서 윤문한다.

```bash
python3 scripts/humanize_prose.py extract monthly_<KEY>.html --out prose_in.txt
# humanize-korean 스킬 또는 수동 윤문 → prose_out.txt
python3 scripts/humanize_prose.py finalize monthly_<KEY>.html --payload prose_out.txt \
  --gate "python3 scripts/check_style.py {f}" \
  --gate "python3 scripts/check_readability.py --strict {f}" \
  --gate "python3 scripts/check_period.py --html {f} --agg <AGG> --recap <RECAP> --scorecard data/period_scorecard.json --span monthly"
```

전부 통과했을 때만 원본이 바뀐다. 실패하면 사본을 버리고 원본은 미수정으로 남는다.

통과하면 `monthly/<KEY>.html`로 옮긴다.

## STEP 5 — KR 주간 정리

STEP 4와 같되 `market=kr`, 입력 `recap_kr.json`·`kr/data/monthly/<KEY>.json`, 산출 `kr_monthly_<KEY>.html` → `kr/monthly/<KEY>.html`. 게이트도 같은 인자로 돈다.

## STEP 6 — 목록·sitemap·커밋

```bash
python3 scripts/update_archives.py --kind monthly --key <KEY> --title "<제목>" --headline "<헤드라인>"
python3 scripts/update_archives.py --kind kr-monthly --key <KEY> --title "<제목>" --headline "<헤드라인>"
```

`git add` → commit → push. push가 403이면 Claude GitHub App이 **Installed** 상태인지 확인한다(Authorized만으로는 안 된다).

## STEP 7 — 알림

PushNotification으로 2편의 URL을 보낸다.

---

**이 파이프라인이 하지 않는 것**: 웹 검색, 시세 수집, 에디터 노트, Notion 발행.
