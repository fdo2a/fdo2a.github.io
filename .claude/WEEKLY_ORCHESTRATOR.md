# 주간 정리 파이프라인 (토요일 15:00 KST)

> 2026-09-26: 12:00 → 15:00. US 일간(08:30)이 5시간 한도를 태운 날 같은 창에서 0초 만에 죽었다 — 창을 뗐다.

US·KR 주간 2편을 발행한다. 웹 검색은 하지 않는다. **KR 은 그 주 발행본의 총정리**, **US 는 인사이트 형식**(2026-09-26 — 발행본 + 주간 스냅샷으로 계산한 진단, STEP 4). 시세는 다시 받지 않는다 — 표 끝값은 집계, 진단은 스냅샷에서 온다.

**편집 계약:** 준비 단계에서 `.claude/DESK_REPORT.md`를 읽고 writer에게 경로를 전달한다. 기간 시황과 성과표를 유지하면서 현재 판단의 함의·기대와 결과의 차이·다음 확인 조건을 연결한다. 주간은 중요한 질문의 심화, 월간은 판단 방법의 복기다. 작성 전후 그 문서의 Editorial acceptance를 적용하고 기존 연구·수치·문체 검사를 모두 수행한다.

## STEP 0 — 준비와 기간 키

레포(`fdo2a/fdo2a.github.io`)를 클론하고 워크스페이스로 삼는다.

```bash
python3 -c "import sys,json;sys.path.insert(0,'scripts');from us.period import week_key;print(week_key(json.load(open('data/market_data.json'))['report_date']))"
```

이 값이 `<KEY>`(예: `2026-W35`)다. **날짜 산술로 도출하지 않는다** — 2026-07-13 중복 생성 직전까지 갔던 버그와 같은 부류다.

**선점 잠금과 부분 발행 이어받기**(2026-09-27 — 한도 뒤 재시도 루틴이 토요일 저녁부터 3시간마다 뜬다). `bash scripts/ci/run_lock.sh acquire weekly-<KEY> 240` — exit 3 이면 다른 런이 작성 중이니 「locked by another run」만 보고하고 끝낸다(exit 4 도 진행하지 않는다). **STEP 4·5 의 작성자를 부르기 직전과 돌아온 직후, STEP 6 커밋 직전에 `bash scripts/ci/run_lock.sh renew weekly-<KEY>`** 를 한다 — exit 3 이면 잠금을 잃은 것이니(갱신 없이 240분이 지나 재시도가 넘겨받았다) 커밋하지 않고 끝낸다. 쓰지 않고 끝나는 경로에서는 `release weekly-<KEY>` 로 풀고 끝낸다.

**먼저 데이터가 밀렸는지 본다** — 금요일 수집이 실패해 `report_date` 가 지난주에 머물면 지난주 키가 나와 아래 가드가 「already published」로 끝낸다. 그러니 가드보다 먼저 `python3 scripts/ci/routine_due.py week-key`(휴장일 달력으로 정한 이번 주 키)를 `<KEY>` 와 맞대고, **다르면** 발행하지 않고 그 사실을 PushNotification 으로 알린 뒤(잠금을 풀고) 끝낸다. 이번 주 집계가 아예 없어도 이것으로 잡힌다. 재시도 판정(`routine_due.py weekly`)은 달력으로 이번 주 키를 정하므로 계속 미발행으로 본다.

그다음:

- `weekly/<KEY>.html` 과 `kr/weekly/<KEY>.html` 이 **둘 다** 원격에 있으면 「already published」만 보고하고 끝낸다.
- **하나만 있으면 있는 쪽은 다시 만들지 않는다** — US 가 있으면 STEP 4 를, KR 이 있으면 STEP 5 를 건너뛰고, STEP 1·2·3 과 STEP 6 도 **남은 시장만** 본다(이미 나간 쪽 집계는 확인하지 않는다).
- STEP 6 커밋 직전에는 작업 중인 변경이 있으니 `pull` 하지 않고 `git fetch -q origin main` 을 먼저 하고 — **실패하면 확인할 수 없으니 커밋하지 않고 끝낸다** — 성공했을 때만 `git cat-file -e origin/main:<그 글 경로>` 로 확인한다. 그 사이 생긴 쪽은 커밋에서 뺀다. push 가 거절되면 `git pull --rebase` 하고, `weekly.json`·`kr/weekly.json`·`sitemap.xml` 충돌은 원격 판을 받은 뒤 STEP 6 의 `update_archives.py` 를 이 키로 다시 돌려 `git rebase --continue` 한다. 글 파일 자체가 충돌하면 다른 런이 발행한 것이니 `git rebase --abort` 하고 끝낸다.


## STEP 1 — 집계 파일 확인

`data/weekly/<KEY>.json`과 `kr/data/weekly/<KEY>.json`이 있고 `complete: true`인지 본다(STEP 0 에서 한 시장이 이미 발행됐으면 남은 시장의 집계만).

없거나 `complete: false`면 **PushNotification으로 알리고 중단한다.** 완성본만 발행한다 — 반쪽 집계로 낸 총정리는 나중에 정정할 방법이 없다.

이 집계는 시세를 다시 받지 않는다. 일별 스냅샷 원장(`data/history/market.jsonl`·`kr/data/history/kr_market.jsonl`)을 굴린 것이라 **끝값이 그 기간 마지막 발행본의 종가와 같아야 한다.** 다르면 원장이 어긋난 것이니 발행하지 말고 알린다 — 2026-08-30에 시세를 다시 받던 집계가 10년물·금·원달러를 발행본과 다르게 실어 주간본을 회수했다.

## STEP 1-b — 주간 스냅샷 (작업 트리를 바꾸기 전에)

**US 글이 이미 원격에 있으면(STEP 0 의 부분 발행) 이 단계를 건너뛴다** — 스냅샷은 US 진단에만 쓰이고, KR 만 남은 재시도를 US 스냅샷이 막으면 안 된다.

**스냅샷은 루틴 안에서 받지 않는다**(2026-10-02 — 루틴 환경은 Yahoo·MOF·CFTC·FRED 모두 연결 실패, yfinance 없음). `collect-weekly-data.yml`(Actions)이 받아 `data/weekly_ext/<KEY>.json` 을 커밋하고, **그 파일의 주인은 그 워크플로 하나다** — 루틴은 읽기만 하고 발행 커밋에 넣지 않는다.

1. `python3 scripts/ci/snapshot_ready.py us --key <KEY> --end <END>` — `READY` 면 2·3 을 건너뛴다.
2. `STALE` 이면 워크플로를 띄운다: `N=wk-$(date +%s)-$RANDOM` → `gh workflow run collect-weekly-data.yml -f key=<KEY> -f end=<END> -f nonce=$N` → `/bin/sleep 15` → `RUN=$(gh run list --workflow=collect-weekly-data.yml --limit 20 --json databaseId,displayTitle --jq "[.[] | select(.displayTitle | endswith(\" $N\"))][0].databaseId")` — **nonce 로 집는다**(맨 `--limit 1` 은 다른 실행을 집을 수 있다). 비어 있으면 15초 뒤 한 번 더 찾는다. `gh` 가 없으면 KR_ORCHESTRATOR STEP 0 처럼 `mcp__github__actions_run_trigger`(같은 입력과 nonce)·`actions_list` 로 같은 일을 한다. 기다림은 `bash scripts/ci/wait_run.sh "$RUN"` 한 번(Bash 도구 timeout 600000) — exit 2(아직 도는 중)면 같은 명령을 한 번 더, 0·1·3 이면 그대로 3 으로 간다.
3. `git pull` 하고 1 을 다시 한다. 여전히 `STALE` 이면 발행하지 않고 그 이유(판정 출력)를 PushNotification 으로 알린 뒤 잠금을 풀고 끝낸다. `<END>` 는 집계의 `end_date` 다.

이 단계를 STEP 2·3 **앞에** 두는 이유: STEP 3 이 이력·스코어카드를 고친 뒤에는 `git pull` 이 작업 중 변경과 부딪친다.

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

## 연구 복기 준비 — 작성자 호출 전

`.claude/RESEARCH_WORKFLOW.md`의 기간 복기를 수행한다. 시장별 `research/us`·`research/kr` 원장과 저장 증거만 사용한다. 집계의 START·END와 실제 검토 시각 AS_OF를 고정하고 `check_research.py render`로 요약을 만든다. 작성자는 생성된 section을 그대로 삽입하고, 주간에는 가설 변화와 반증, 월간에는 반복된 설명의 한계와 다음 검증 조건을 서술한다. 초기 원장이 비어 있으면 축적 전이라고 밝힌다.

아래 US 명령의 `<AS_OF>`는 같은 고정 시각이다. KR 실행에서는 모든 입력 경로와 `--research-root research/kr --market kr`를 함께 바꾼다. 발행 전 `check_research.py check`도 workflow대로 수행한다(윤문은 발행 뒤 codex 가 하고, 그때 연구 요약은 원본과 바이트 대조한다).

## STEP 4 — US 주간 인사이트

**4-0. 진단.** 요약이 아니라 진단을 쓰는 형식이라(2026-09-26) STEP 1-b 의 스냅샷을 쓴다. 진단은 커밋된 파일만 읽는다(네트워크 없음).

```bash
python3 scripts/build_weekly_insight.py diag --key <KEY>
```

진단(`data/weekly_ext/<KEY>.insight.json`)은 발행 커밋에 넣는다(게이트 재현용). 스냅샷은 Actions 가 이미 커밋했다 — 넣지 않는다.

`period-report-writer` 서브에이전트를 `market=us, span=weekly`로 부른다(지시문 끝 「US 주간 인사이트」 절). 입력은 `recap_us.json`·`data/weekly/<KEY>.json`·`data/weekly_ext/<KEY>.insight.json`·`data/period_scorecard.json`·`data/history/*.jsonl`. 산출은 `weekly_<KEY>.body.html`·`weekly_<KEY>.meta.json`. 이어서 조립한다:

```bash
python3 scripts/build_weekly_insight.py assemble --key <KEY> \
  --body weekly_<KEY>.body.html --meta weekly_<KEY>.meta.json --out weekly_<KEY>.html
```

조립이 exit 1 이면 목록을 writer 에게 그대로 돌려준다. 아래 US 게이트 명령에는 모두 `--insight data/weekly_ext/<KEY>.insight.json` 을 붙인다.

**위임한 것은 다시 읽지 않는다.** 서브에이전트는 **동기**(`run_in_background: false`)로 부르고, 기다리는 동안 아무것도 열지 않는다. 에이전트 정의 파일(`.claude/agents/*.md`), 그 에이전트가 읽을 데이터 파일, 직전 발행본은 오케스트레이터가 읽지 않는다 — **경로만 넘기고**, 돌아온 산출물과 게이트 출력만 본다. 폴백으로 general-purpose 에이전트를 쓸 때도 정의 파일 본문을 붙여 넣지 말고 「이 파일을 먼저 Read 하라」고 경로를 준다. (2026-09-22 KR 실행이 에이전트를 백그라운드로 띄워 두고 지시문 35 KB·데이터 12개·직전 발행본을 다시 읽다가 5시간 한도로 죽었다.)

**발행 게이트:**

```bash
python3 scripts/check_period.py --html weekly_<KEY>.html --agg data/weekly/<KEY>.json \
  --recap recap_us.json --scorecard data/period_scorecard.json --span weekly --research-root research/us --research-as-of <AS_OF> --market us \
  --insight data/weekly_ext/<KEY>.insight.json
```

위반이 나오면 **목록을 그대로 writer에게 돌려주고 다시 돌린다.** 게이트를 우회하지 않는다.

이어서 조판·문체 게이트를 일간과 동일하게 돌린다.

```bash
python3 scripts/apply_readability.py $(pwd)/weekly_<KEY>.html
python3 scripts/check_readability.py --strict $(pwd)/weekly_<KEY>.html
python3 scripts/check_style.py $(pwd)/weekly_<KEY>.html
```

**`check_weight.py`는 돌리지 않는다.** (US 인사이트의 무게중심은 `--insight` 가 대신 본다 — 이례적 움직임 언급.) 그 게이트는 일간의 섹션 제목(「주식」·「채권」·「매크로」)을 검사하는데, 총정리는 5섹션 구조라 그 잣대가 맞지 않는다. 기간용 무게중심 판정은 아직 없다(2026-08-30 codex 검토에서 확인).

**STEP 4-b — 윤문은 루틴에서 하지 않는다 (2026-10-01).** 위 게이트를 통과한 판이 곧 발행본이다. 말투 손질은 **발행 뒤** 로컬 러너(`scripts/review_gate.py run --correct`, 매시)가 codex 로 한다 — `prose_in.txt` 만 고치고, 문단별 되꽂기와 이 단계의 게이트(`check_period` 는 발행 커밋의 집계·recap·스코어카드로, 연구 요약은 원본과 바이트 대조)를 통과해야 공개판을 바꾼다. 거부되면 원본이 그대로 남는다. Claude 윤문(humanize-korean)은 부르지 않는다 — 사용자 지시 「주간, 월간, 일본 보고서도 codex가 검토하도록 해」. 설계 `docs/superpowers/specs/2026-10-01-period-codex-style-pass.md`.

통과하면 `weekly/<KEY>.html`로 옮긴다.

## STEP 5 — KR 주간 정리

STEP 4와 같되 `market=kr`, 입력 `recap_kr.json`·`kr/data/weekly/<KEY>.json`, 산출 `kr_weekly_<KEY>.html` → `kr/weekly/<KEY>.html`. 게이트도 같은 인자로 돈다.

## STEP 6 — 목록·sitemap·커밋

**목록에는 주 키(2026-W39)가 아니라 날짜를 보인다**(`--label`, 2026-09-26 사용자 지시 — 「W39 라고 하면 언제인지 알 수 없다」). 제목(`<title>`)에도 주 키 대신 「2026년 9월 21일~25일」 꼴을 쓴다.


```bash
LABEL=$(python3 -c "import sys;sys.path.insert(0,'.');from scripts.common.datelabel import range_ko;import json;a=json.load(open('data/weekly/<KEY>.json'));print(range_ko(a['start_date'],a['end_date']))")
python3 scripts/update_archives.py --kind weekly --key <KEY> --title "<제목>" --headline "<헤드라인>" --label "$LABEL"
KLABEL=$(python3 -c "import sys;sys.path.insert(0,'.');from scripts.common.datelabel import range_ko;import json;a=json.load(open('kr/data/weekly/<KEY>.json'));print(range_ko(a['start_date'],a['end_date']))")
python3 scripts/update_archives.py --kind kr-weekly --key <KEY> --title "<제목>" --headline "<헤드라인>" --label "$KLABEL"
```

`git add` → commit → push. push가 403이면 Claude GitHub App이 **Installed** 상태인지 확인한다(Authorized만으로는 안 된다).

## STEP 7 — 알림

PushNotification으로 2편의 URL을 보낸다.

---

**이 파이프라인이 하지 않는 것**: 웹 검색, 시세 수집, 에디터 노트, Notion 발행.
