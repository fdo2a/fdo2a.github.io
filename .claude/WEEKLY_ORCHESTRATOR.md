# 주간 정리 파이프라인 (토요일)

US·KR 주간 정리 2편을 발행한다. **그 주 발행본의 총정리**이지 새 취재가 아니다 — 웹 검색도 시세 재수집도 하지 않는다.

## STEP 0 — 준비와 기간 키

레포(`fdo2a/fdo2a.github.io`)를 클론하고 워크스페이스로 삼는다.

```bash
python3 -c "import sys,json;sys.path.insert(0,'scripts');from us.period import week_key;print(week_key(json.load(open('data/market_data.json'))['report_date']))"
```

이 값이 `<KEY>`(예: `2026-W35`)다. **날짜 산술로 도출하지 않는다** — 2026-07-13 중복 생성 직전까지 갔던 버그와 같은 부류다.

## STEP 1 — 집계 파일 확인

`data/weekly/<KEY>.json`과 `kr/data/weekly/<KEY>.json`이 있고 `complete: true`인지 본다.

없거나 `complete: false`면 **PushNotification으로 알리고 중단한다.** 완성본만 발행한다 — 반쪽 집계로 낸 총정리는 다음 주에 정정할 방법이 없다.

## STEP 2 — 발행본 회수

```bash
python3 scripts/build_recap_source.py --posts-dir posts --listing posts.json \
  --start <START> --end <END> --span weekly --key <KEY> --out recap_us.json
python3 scripts/build_recap_source.py --posts-dir kr/posts --listing kr/posts.json \
  --start <START> --end <END> --span weekly --key <KEY> --out recap_kr.json
```

`<START>`·`<END>`는 집계 파일의 `start_date`·`end_date`다. **발행본이 0편이면 중단한다** — 총정리할 원본이 없다. 스크립트가 exit 1로 알린다.

`missing`에 남은 날이 있으면 그대로 진행하되 **그 사실을 본문에 밝힌다.**

## STEP 3 — 스코어카드

```bash
python3 scripts/build_scorecard.py --agg data/weekly/<KEY>.json --datadir data \
  --spans 4,12 --out data/period_scorecard.json
```

이력에 한 행이 append된다(`data/history/period_scorecard.jsonl`). 첫 몇 회차는 `rollup`이 `insufficient: true`로 나오는 것이 정상이다.

## STEP 4 — US 주간 정리

`period-report-writer` 서브에이전트를 `market=us, span=weekly`로 부른다. 입력은 `recap_us.json`·`data/weekly/<KEY>.json`·`data/period_scorecard.json`·`data/history/*.jsonl`. 산출은 `weekly_<KEY>.html`.

**발행 게이트:**

```bash
python3 scripts/check_period.py --html weekly_<KEY>.html --agg data/weekly/<KEY>.json \
  --recap recap_us.json --scorecard data/period_scorecard.json --span weekly
```

위반이 나오면 **목록을 그대로 writer에게 돌려주고 다시 돌린다.** 게이트를 우회하지 않는다.

이어서 조판·문체 게이트를 일간과 동일하게 돌린다.

```bash
python3 scripts/apply_readability.py $(pwd)/weekly_<KEY>.html
python3 scripts/check_readability.py --strict $(pwd)/weekly_<KEY>.html
python3 scripts/check_style.py $(pwd)/weekly_<KEY>.html
```

통과하면 `weekly/<KEY>.html`로 옮긴다.

## STEP 5 — KR 주간 정리

STEP 4와 같되 `market=kr`, 입력 `recap_kr.json`·`kr/data/weekly/<KEY>.json`, 산출 `kr_weekly_<KEY>.html` → `kr/weekly/<KEY>.html`. 게이트도 같은 인자로 돈다.

## STEP 6 — 목록·sitemap·커밋

```bash
python3 scripts/update_archives.py --kind weekly --key <KEY> --title "<제목>" --headline "<헤드라인>"
python3 scripts/update_archives.py --kind kr-weekly --key <KEY> --title "<제목>" --headline "<헤드라인>"
```

`git add` → commit → push. push가 403이면 Claude GitHub App이 **Installed** 상태인지 확인한다(Authorized만으로는 안 된다).

## STEP 7 — 알림

PushNotification으로 2편의 URL을 보낸다.

---

**이 파이프라인이 하지 않는 것**: 웹 검색, 시세 수집, 에디터 노트, Notion 발행.
