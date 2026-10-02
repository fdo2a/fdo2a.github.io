# 일본 시장 주간 — 오케스트레이터 (일요일)

일요일 10:00 KST 에 한 편을 발행한다(2026-10-02 루틴 등록, 첫 호 W40). 한도로 죽으면 같은 날 13·16·19·22시 KST 재시도 루틴이 `scripts/ci/routine_due.py japan` 으로 판정해 이어받는다. 재무성 증권투자(목)와 CFTC(금 공개, 화요일 기준)가 모두 들어온 뒤다. US·KR 주간 루틴(토)과 5시간 한도 창을 나누지 않으려고 날을 뗐다. 웹 검색은 하지 않는다.

## STEP 0 — 기간 키와 오늘

```bash
TZ=Asia/Seoul date +%F > /tmp/japan-today && cat /tmp/japan-today
python3 -c "import datetime as d;t=d.date.fromisoformat(open('/tmp/japan-today').read().strip());y,w,_=(t-d.timedelta(days=2)).isocalendar();print(f'{y}-W{w:02d}')"
```

두 번째 값이 `<KEY>`(그 주 금요일이 속한 ISO 주)다. `japan/posts/<KEY>.html` 이 이미 있으면 끝낸다 — **이 가드는 수집 뒤에 둔다**(STEP 1 이 끝난 다음 다시 확인).

**선점 잠금 — 다른 파일을 읽기 전에.** `bash scripts/ci/run_lock.sh acquire japan-<KEY> 240` — exit 3 이면 다른 런이 작성 중이니 「locked by another run」만 보고하고 끝낸다(exit 4 도 진행하지 않는다). STEP 2 작성자를 부르기 직전과 돌아온 직후, STEP 4 커밋 직전에 `bash scripts/ci/run_lock.sh renew japan-<KEY>` — exit 3 이면 잠금을 잃었으니 커밋하지 않고 끝낸다. 쓰지 않고 끝나는 경로(가드·수집 실패)에서는 `bash scripts/ci/run_lock.sh release japan-<KEY>` 로 풀고 끝낸다.

## STEP 1 — 스냅샷과 진단

**스냅샷은 루틴 안에서 받지 않는다**(2026-10-02 — 루틴 환경은 Yahoo·MOF·CFTC·FRED 모두 연결 실패, yfinance 없음). `collect-weekly-data.yml`(Actions)이 받아 `data/weekly_ext/<KEY>.json` 을 커밋하고, **그 파일의 주인은 그 워크플로 하나다** — 루틴은 읽기만 하고 발행 커밋에 넣지 않는다.

1. `python3 scripts/ci/snapshot_ready.py japan --key <KEY> --end <그 주 금요일>` — `READY` 면 2·3 을 건너뛴다.
2. `STALE` 이면 워크플로를 띄운다: `N=wk-$(date +%s)-$RANDOM` → `gh workflow run collect-weekly-data.yml -f key=<KEY> -f end=<그 주 금요일> -f nonce=$N` → `/bin/sleep 15` → `RUN=$(gh run list --workflow=collect-weekly-data.yml --limit 20 --json databaseId,displayTitle --jq "[.[] | select(.displayTitle | endswith(\" $N\"))][0].databaseId")` — **nonce 로 집는다**(맨 `--limit 1` 은 다른 실행을 집을 수 있다). 비어 있으면 15초 뒤 한 번 더 찾는다. `gh` 가 없으면 KR_ORCHESTRATOR STEP 0 처럼 `mcp__github__actions_run_trigger`(같은 입력과 nonce)·`actions_list` 로 같은 일을 한다. 기다림은 `bash scripts/ci/wait_run.sh "$RUN"` 한 번(Bash 도구 timeout 600000) — exit 2(아직 도는 중)면 같은 명령을 한 번 더, 0·1·3 이면 그대로 3 으로 간다.
3. `git pull` 하고 1 을 다시 한다. 여전히 `STALE` 이면 발행하지 않고 그 이유를 PushNotification 으로 알린 뒤 잠금을 풀고 끝낸다.

`japan` 판정은 일본이 쓰는 소스만 보고, **도쿄 금요일분**(JGB 10년·닛케이)이 있어야 `READY` 다 — 토요일 새벽 스냅샷은 그것이 비어 있다(2026-09-26 실측). US 주간이 토요일에 받은 스냅샷이면 대개 `STALE` 이 나와 일요일에 다시 받는다. 그다음 진단(커밋된 파일만 읽는다):

```bash
python3 scripts/build_japan_weekly.py diag --key <KEY>
```

## STEP 2 — 작성과 조립

`japan-report-writer` 를 **동기**로 부른다. 넘기는 것은 경로뿐이다(`japan/data/<KEY>.json`, `<KEY>.news.json`) — 오케스트레이터가 데이터·지시문을 다시 읽지 않는다.

```bash
python3 scripts/build_japan_weekly.py assemble --key <KEY> \
  --body japan_<KEY>.body.html --meta japan_<KEY>.meta.json --out japan_<KEY>.html
```

## STEP 3 — 게이트 (순서대로, 전부 exit 0)

```bash
python3 scripts/apply_readability.py $(pwd)/japan_<KEY>.html
python3 scripts/check_japan.py --html japan_<KEY>.html --key <KEY>
python3 scripts/check_readability.py --strict $(pwd)/japan_<KEY>.html
python3 scripts/check_style.py $(pwd)/japan_<KEY>.html
```

위반은 목록 그대로 writer 에게 돌려준다. 윤문은 루틴에서 하지 않는다(2026-10-01) — 발행 뒤 로컬 러너가 codex 로 고치고, 위 셋(`check_japan` 은 발행 커밋의 `japan/data`)을 다시 통과할 때만 공개판을 바꾼다. US 주간 STEP 4-b 참고.

## STEP 4 — 발행

커밋 직전에는 작업 중 변경이 있으니 `pull` 하지 않고 `git fetch -q origin main` 을 먼저 하고 — **실패하면 확인할 수 없으니 커밋하지 않고 끝낸다** — 성공했을 때만 `git cat-file -e origin/main:japan/posts/<KEY>.html` 로 본다. 있으면 다른 런이 발행한 것이니 커밋하지 않고 끝낸다. 아니면 `japan/posts/<KEY>.html` 로 옮기고 `japan/posts.json` 맨 앞에 `{key, title, headline, start_date, end_date}` 를 넣는다. 진단·뉴스 파일과 함께 **한 커밋**으로(스냅샷은 Actions 가 커밋했다 — 넣지 않는다) `bash scripts/ci/push_with_retry.sh`. PushNotification 으로 URL 을 보낸다.
