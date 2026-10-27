# 일본 시장 주간 — 오케스트레이터 (MOF 게시일)

**재무성(MOF)이 금요일 JGB 커브를 올리는 날** — 금요일 다음 도쿄 영업일, 보통 월요일이고 월요일이 휴장이면 그 뒤 — 에 한 편을 발행한다(2026-10-04 일요일에서 옮김: MOF 커브는 다음 영업일 공표라 주말엔 금요일분이 없다). 본 루틴은 월~금 13:00 KST, 재시도는 16·19·22시 KST 에 뜨고, 둘 다 먼저 `scripts/ci/routine_due.py japan` 을 본다 — 게시일 전이면 `WAIT`, 발행했으면 `DONE` 으로 곧바로 끝난다. 재무성 증권투자(목)와 CFTC(금 공개, 화요일 기준)가 모두 들어온 뒤다. 웹 검색은 하지 않는다.

## STEP 0 — 기간 키와 오늘

```bash
python3 scripts/ci/routine_due.py japan-key    # → <KEY> <그 주 금요일> <게시일>
```

첫 값이 `<KEY>`(오늘보다 앞선 마지막 금요일이 속한 ISO 주), 둘째가 스냅샷 종료일인 그 금요일, 셋째가 MOF 게시일이다. 날짜 산술로 다시 만들지 않는다. `japan/posts/<KEY>.html` 이 이미 있으면 끝낸다 — **이 가드는 수집 뒤에 둔다**(STEP 1 이 끝난 다음 다시 확인).

**선점 잠금 — 다른 파일을 읽기 전에.** `bash scripts/ci/run_lock.sh acquire japan-<KEY> 240` — exit 3 이면 다른 런이 작성 중이니 「locked by another run」만 보고하고 끝낸다(exit 4 도 진행하지 않는다). STEP 2 작성자를 부르기 직전과 돌아온 직후, STEP 4 커밋 직전에 `bash scripts/ci/run_lock.sh renew japan-<KEY>` — exit 3 이면 잠금을 잃었으니 커밋하지 않고 끝낸다. 쓰지 않고 끝나는 경로(가드·수집 실패)에서는 `bash scripts/ci/run_lock.sh release japan-<KEY>` 로 풀고 끝낸다. **release 는 ref 를 지우지 않고 `released` 표시 커밋으로 바꾼다**(클라우드는 ref 삭제 push 를 거부한다 — 2026-10-20). release 가 **exit 4·5 면 잠금이 남아 재시도 루틴이 stale 까지 BUSY 로 막힌다** — 이 가드가 평소 알리지 않고 끝나는 경로라도 release 출력을 붙여 PushNotification 으로 보고한다. exit 0 은 풀렸거나 이미 남의 것이다.

## STEP 1 — 스냅샷과 진단

**스냅샷은 루틴 안에서 받지 않는다**(2026-10-02 — 루틴 환경은 Yahoo·MOF·CFTC·FRED 모두 연결 실패, yfinance 없음). `collect-weekly-data.yml`(Actions)이 받아 `data/weekly_ext/<KEY>.json` 을 커밋하고, **그 파일의 주인은 그 워크플로 하나다** — 루틴은 읽기만 하고 발행 커밋에 넣지 않는다.

1. `python3 scripts/ci/snapshot_ready.py japan --key <KEY> --end <그 주 금요일>` — `READY` 면 2·3 을 건너뛴다.
2. `STALE` 이면 워크플로를 띄운다: `N=wk-$(date +%s)-$RANDOM` → `gh workflow run collect-weekly-data.yml --ref main -f key=<KEY> -f end=<그 주 금요일> -f nonce=$N` → `/bin/sleep 15` → `RUN=$(gh run list --workflow=collect-weekly-data.yml --limit 20 --json databaseId,displayTitle --jq "[.[] | select(.displayTitle | endswith(\" $N\"))][0].databaseId")` — **nonce 로 집는다**(맨 `--limit 1` 은 다른 실행을 집을 수 있다). 비어 있으면 15초 뒤 한 번 더 찾는다. `gh` 가 없으면 KR_ORCHESTRATOR STEP 0 처럼 `mcp__github__actions_run_trigger`(같은 입력과 nonce)·`actions_list` 로 같은 일을 한다. 기다림은 `bash scripts/ci/wait_run.sh "$RUN"` 한 번(Bash 도구 timeout 600000) — exit 2(아직 도는 중)면 같은 명령을 한 번 더, 0·1·3 이면 그대로 3 으로 간다.
3. `git pull` 하고 1 을 다시 한다. 여전히 `STALE` 이면 발행하지 않고 잠금을 풀고 끝낸다. MOF 게시 시각은 실측이 없으니 게시일 낮에는 아직일 수 있다 — PushNotification 은 그날 마지막 재시도(`TZ=Asia/Seoul date +%H` 가 21 이상)이거나 서울 날짜가 게시일보다 뒤일 때만 그 이유와 함께 보낸다. 그 전 시각에는 알리지 않고 끝낸다 — 다음 재시도가 이어받는다.

`japan` 판정은 일본이 쓰는 소스만 보고, **도쿄 금요일분**(JGB 10년·닛케이)이 있어야 `READY` 다 — 주말 스냅샷은 JGB 금요일분이 비어 있다(2026-10-04 실측: 토 15시~일 22시 6개가 전부 목요일에서 끝났다). US 주간이 토요일에 받은 스냅샷이면 `STALE` 이 나와 게시일에 다시 받는다. 그다음 진단(커밋된 파일만 읽는다):

```bash
python3 scripts/build_japan_weekly.py diag --key <KEY>
```

## STEP 2 — 작성과 조립

**작성자 모델(2026-10-27)** — 작성자(`japan-report-writer`)를 부르는 모든 Agent 호출 — 첫 작성, 게이트·조립 실패로 되돌려 고치기, general-purpose 폴백 — 에 `model: "opus"` 를 적는다. 에이전트 머리말에도 같은 값이 있지만 폴백에서는 머리말이 빠진다. 수집 담당 등 다른 서브에이전트는 모델을 적지 않는다(본체 모델 상속). **본체가 직접 쓰거나 고치는 모든 단계는 이 루틴의 모델이 Opus 일 때만 한다** — Agent 도구가 없을 때의 폴백, 작성자 타입이 없을 때의 직접 작성, 「같은 위반 두 번 → 오케스트레이터가 직접 고친다」. 본체가 Opus 가 아니면: 작성자 타입이 없으면 general-purpose 를 `model: "opus"` 로 부르고, 직접 고치는 대신 작성자를 `model: "opus"` 로 한 번 더 부르며, Agent 도구가 없거나 그래도 남으면 잠금을 풀고 중단을 보고한다 — 이 중단은 「중단은 completeness 실패뿐」의 예외다. 설계: `docs/superpowers/specs/2026-10-27-model-routing.md`.

`japan-report-writer` 를 **동기**로 부른다. 넘기는 것은 경로뿐이다(`japan/data/<KEY>.json`, `<KEY>.news.json`) — 오케스트레이터가 데이터·지시문을 다시 읽지 않는다. 일본 뉴스(`japan/data/news/<date>.json`)는 `collect-japan-news.yml`(Actions, 화-토·월 07:00 JST)이 받아 커밋한다 — 루틴은 받지 않고, 비어 있으면 `diag` 의 「이번 주 뉴스 후보 0」 이 그대로 면제다. 조립이 `<!--NEWS:-->` 자리표시를 요약으로 채우고, 채우지 못하면 실패 목록을 작성자에게 돌려준다.

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

위반은 목록 그대로 writer 에게 돌려준다. 윤문은 루틴에서 하지 않는다(2026-10-01). 발행 뒤 codex 문체 수정은 2026-10-13 부터 수정안만 기록하고 공개판을 바꾸지 않는다(`style_pass.APPLY`) — 위 셋을 통과한 판이 곧 최종본이다. US 주간 STEP 4-b 참고.

## STEP 4 — 발행

커밋 직전에는 작업 중 변경이 있으니 `pull` 하지 않고 `git fetch -q origin main` 을 먼저 하고 — **실패하면 확인할 수 없으니 커밋하지 않고 끝낸다** — 성공했을 때만 `git cat-file -e origin/main:japan/posts/<KEY>.html` 로 본다. 있으면 다른 런이 발행한 것이니 커밋하지 않고 끝낸다. 아니면 `japan/posts/<KEY>.html` 로 옮기고 `japan/posts.json` 맨 앞에 `{key, title, headline, start_date, end_date}` 를 넣는다. 진단·뉴스 파일과 함께 **한 커밋**으로(스냅샷은 Actions 가 커밋했다 — 넣지 않는다) `bash scripts/ci/push_with_retry.sh`. PushNotification 으로 URL 을 보낸다.
