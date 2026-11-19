# 일본 시장 일간 마감브리프 — 오케스트레이터 (도쿄 거래일 · KR 브리프 직후)

도쿄 거래일 저녁마다 한 편을 `/japan/daily/<세션>.html` 로 발행한다. 본 루틴은 18:20 KST 에 깨어 KR 브리프 발행을 기다렸다가 시작, 재시도는 Actions 재시도 관문이 21:17 KST 쯤 판정해 `DUE` 일 때만 깨우고, 05:30 KST 안전망이 한 번 더 있다(2026-11-19). 일본 주간(`JAPAN_ORCHESTRATOR.md`)과 데이터·발행이 분리돼 있다. **웹 검색은 하지 않는다** — 숫자는 전부 수집 스냅샷에서, 뉴스는 일간 뉴스 파일에서만. 설계: `docs/superpowers/specs/2026-10-27-japan-daily-design.md`(§13 우선). 실행 격리(`run_id`·실행 폴더·시작 가드·검증 기록·manifest 스테이징, 2026-11-19): 일본 일간 v2 설계 20판 §6.

## STEP 0 — 세션 고정, 판정, 잠금 (다른 파일을 읽기 전에)

```bash
python3 scripts/ci/routine_due.py jp_daily      # DONE | BUSY | DUE <이유>
read -r S P < <(python3 scripts/ci/routine_due.py jp-session)   # 세션, 직전 세션
KEY=$(bash scripts/ci/run_lock.sh key jp_daily)                 # jpd-<S>
```

`DONE`·`BUSY`·`SKIP` 면 그 한 줄만 보고하고 끝낸다(`SKIP` = 오늘 발행할 세션이 아니다 — 휴장일·주말, 보충 발행 없음).

**KR 브리프가 올라온 뒤에 시작한다**(사용자 지시 2026-10-27 — 본 회차는 18:20 KST 에 깨어 기다린다). `DUE` 면 잠금 전에 `bash scripts/ci/wait_for_kr.sh` (Bash timeout 600000) — exit 0(`DONE` — KR 발행 완료, 한국 휴장일도 즉시 `DONE`)이면 진행, exit 2 면 같은 명령을 다시. **최대 8번(약 72분)** 까지 기다리고, 그래도 KR 이 없으면 기다리지 않고 진행한다(일본 일간을 KR 실패에 묶지 않는다). 재시도 회차(21:00)는 기다리지 않는다. 기다린 뒤에는 `routine_due.py jp_daily` 를 한 번 더 — 그사이 다른 런이 발행했으면 `DONE` 으로 끝난다.

**세션 `S` 는 여기서 한 번 정하고 끝까지 그대로 쓴다** — 자정을 넘긴 재시도가 날짜 산술로 다시 만들면 다른 세션이 된다. `bash scripts/ci/run_lock.sh acquire "$KEY" 120` — exit 3 이면 「locked by another run」만 보고하고 끝낸다(exit 4 도 진행하지 않는다).

**잠금을 얻은 직후 — `run_id`·실행 폴더·시작 가드(2026-11-19).**

```bash
RUN_ID="jpd-$S-$(date -u +%s)-$RANDOM"      # 이 실행의 이름 — 끝까지 바꾸지 않는다
D="_workspace/jpd/$RUN_ID"                   # 이 실행의 본문·meta·조립본·게이트 결과가 놓이는 유일한 자리(.gitignore)
python3 scripts/ci/jpd_clean_start.py --key "$KEY" --session "$S"
```

- 실행 폴더 `$D` 는 STEP 1 의 입력 고정이 만든다. **다른 `run_id` 폴더는 읽지 않는다** — 실패한 실행의 초안·조립본·`gates.json` 을 이어 쓰지 않는다. 레포 루트에 `jpd_<S>.*` 를 만들지 않는다.
- 가드 exit 0 = 이 사본이 `origin/main` 과 같은 커밋에서 시작한다(뒤처졌으면 ff 로 맞췄고, 이 세션의 잠금을 쥔 채 실패한 발행 산출물만 남았으면 되돌렸다). **exit 3 = 거부, 아무것도 건드리지 않았다** — 발행 산출물 밖의 변경·미추적 파일, 잠금 없는 사본의 잔재, 다른 제목·경로의 앞선 커밋, 진행 중인 rebase, fetch 실패. 잠금을 풀고 가드 출력을 PushNotification 으로 보내고 끝낸다. 가드를 건너뛰거나 손으로 `reset`·`clean` 하지 않는다.
- 가드가 되돌릴 수 있는 것은 발행 산출물 7경로(`japan/daily/<S>.html`·`japan/data/daily/<S>.json`·`japan/data/daily/runs/<S>.json`·`japan/data/telegram/published/<S>.json`·`japan/data/history/jp_daily.jsonl`·`japan/daily.json`·`sitemap.xml`)뿐이다.

수집 전후, 작성자를 부르기 직전과 돌아온 직후, 커밋 직전에 `bash scripts/ci/run_lock.sh renew "$KEY"` — exit 3 이면 잠금을 잃었으니 커밋하지 않고 끝낸다. **쓰지 않고 끝나는 모든 경로**에서 `bash scripts/ci/run_lock.sh release "$KEY"` 로 푼다. **발행기(STEP 4-1)가 파일을 쓴 뒤 push 없이 끝나는 경로(「중단 경로」)는 잠금을 풀기 전에 시작 가드를 한 번 더 돌려** 발행 산출물을 `origin/main` 으로 되돌린다 — 가드는 잠금을 쥔 사본에서만 되돌리므로 순서가 바뀌면 거부된다. 실행 폴더는 남겨도 된다(다음 실행은 새 `run_id` 라 읽지 않는다). release 가 exit 4·5 면 그 출력을 붙여 PushNotification 으로 보고한다.

## STEP 1 — 수집 (Actions 에서만)

루틴 환경은 일경·Yahoo·MOF·BOJ 에 닿지 못한다. 수집은 `collect-japan-daily.yml` 이 하고 `japan/data/daily/candidate/<S>.json`(스냅샷)과 `japan/data/news/daily/<S>.json`(16:30 JST 컷 뉴스)을 커밋한다. **예약 실행은 2~5시간 밀리므로 직접 띄운다**(AGENTS.md 규칙 10②):

1. `git pull -q` 후 `japan/data/daily/candidate/<S>.json` 이 있고 `complete: true` 이며 `jgb_recollect` 가 **`false`** 이고 **`schema` 가 `2`** 면 3 으로. 하나라도 아니면(16:30 예약 실행처럼 네이버 JGB 마감 호가가 보이기 전 17:45 JST 이전에 받은 후보, 옛 형식, 2판이 아닌 후보) 2 로 다시 수집한다. 다시 수집할 때 `wait_run` 이 exit 1·3 이면(exit 2 는 한 번 더 기다린 뒤에도 성공을 확인하지 못하면) **그 자리에서 잠금을 풀고 끝낸다** — 재시도 회차가 이어받는다. 성공했어도 후보가 그대로면 5 의 `diag` 가 1 로 끝나 발행하지 않는다.
2. `N=jpd-$(date +%s)-$RANDOM` → `gh workflow run collect-japan-daily.yml --ref main -f session=$S -f nonce=$N` → `/bin/sleep 15` → `RUN=$(gh run list --workflow=collect-japan-daily.yml --limit 20 --json databaseId,displayTitle --jq "[.[] | select(.displayTitle | endswith(\" $N\"))][0].databaseId")` — **nonce 로 집는다**. 비면 15초 뒤 한 번 더. 기다림은 `bash scripts/ci/wait_run.sh "$RUN"` 한 번(Bash timeout 600000) — exit 2 면 같은 명령을 한 번 더. `gh` 가 없으면 `mcp__github__actions_run_trigger`·`actions_list` 로 같은 입력·nonce.
3. `git pull -q` 하고 **그다음에** 가드: `git cat-file -e origin/main:japan/daily/<S>.html` 이 있으면 다른 런이 발행했으니 잠금을 풀고 끝낸다.
4. **입력을 커밋에서 한 번 고정한다**: `python3 scripts/jp_daily_gates.py --pin --run-dir $D --session $S` — `HEAD`(= 방금 pull 한 `origin/main`)에 들어 있는 수집 후보·뉴스·견해 파일의 바이트를 `$D/root/` 아래 같은 상대 경로로 꺼내고 해시를 `$D/inputs.json` 에 적는다. 작업 폴더의 파일이 아니다 — 로컬에서 고쳐진 후보는 입력이 될 수 없다. `HEAD` 에 없는 파일은 이 실행에서 「없음」이다. exit 0 이 아니면(폴더가 이미 있음 등) 잠금을 풀고 끝낸다. **이 뒤로 진단·조립·게이트는 전부 `--root $D/root` 만 읽는다.**
5. `python3 scripts/build_japan_daily.py diag --session $S --root $D/root` — exit 1(`complete` 거짓 — 닛케이 공식 종가 미확인)이면 발행하지 않는다. 잠금을 풀고, **최종 회차(`[[ "$(TZ=Asia/Seoul date +%F%H)" > "${S}20" ]]` — 세션 날 21시 KST 이후, 자정을 넘긴 재시도 포함)면 「<S> 일본 일간 미발행 — 보충 발행 없음」과 diag 출력을 PushNotification 으로 보낸다.** 본 회차면 알리지 않고 끝낸다(재시도가 이어받는다). 보충 발행은 하지 않는다.

`diag` 가 절 순서(이벤트일이면 매크로가 둘째), 기준일이 다른 값(JGB 는 네이버 당일 또는 MOF 폴백 직전 세션, 콜 BOJ 최신 관측일), 뉴스 후보 수, 실패한 비-코어 원천을 알려 준다. 그대로 작성자에게 넘긴다. `--root $D/root` 에는 발행본이 없어 `diag` 의 「직전 일간」 은 늘 「없음」 으로 찍힌다 — 직전 일간 경로는 레포의 `japan/daily/$P.html` 이 있으면 그것을 직접 넘긴다(읽기만 한다).

**견해·의견 후보(2026-11-15)** — 같은 워크플로가 수집 끝에 `japan/data/telegram/<S>.json` 을 만든다(비차단, 실패해도 일간은 그대로 간다). `diag` 의 `견해·의견 후보 N건` 줄이 **N ≥ 1 일 때만** 그 줄의 파일 경로(`$D/root/…`)를 작성자에게 넘긴다. `견해·의견: 없음(…)` 이거나 0건이면 넘기지 않고, 그날 글에는 그 절이 없다. 이 파일 때문에 수집을 다시 띄우지 않는다. **입력 고정 뒤로는 발행 커밋을 만들 때까지 `git pull` 하지 않는다** — 게이트와 발행 단계는 고정한 사본(또는 없음)만 읽고, 발행기는 그 해시가 검증 기록과 같을 때만 쓴다. 그사이 레포의 후보가 다시 수집돼도 이 실행은 고정한 사본으로 발행한다. 설계: `docs/superpowers/specs/2026-11-15-telegram-japan-daily.md`.

## STEP 2 — 작성과 조립

`japan-daily-writer` 를 **동기**로, Agent 호출에 `model: "sonnet"` 을 적어 부른다. 넘기는 것: 세션 `S`, `diag` 출력 전문, 스냅샷·뉴스 파일 경로(`$D/root/…` 사본), 직전 일간 경로(있으면), **본문·meta 를 쓸 경로 `$D/jpd_$S.body.html`·`$D/jpd_$S.meta.json`**. 오케스트레이터는 데이터·지시문을 다시 읽지 않는다. 작성자 마감의 점검(번역투 포함)은 작성자가 한다 — 오케스트레이터는 대신 고치지 않는다.

```bash
python3 scripts/build_japan_daily.py assemble --session $S --root $D/root \
  --body $D/jpd_$S.body.html --meta $D/jpd_$S.meta.json --out $D/jpd_$S.html
```

실패 목록이 나오면 그대로 작성자에게 돌려준다. 조립은 시작할 때 이 실행의 앞 판 통과 기록(`$D/gates.json`)과 조립본을 지우고, 실패하면 그 목록을 `$D/gates.log` 에 남긴다 — 앞 판이 게이트를 통과했어도 새 판을 조립한 뒤에는 래퍼를 다시 통과해야 발행할 수 있다.

**작성자 호출 예산과 막힘 승격(2026-10-27)** — 조립 실패와 STEP 3 게이트 위반이 **같은 예산**을 쓴다: 첫 작성 1번 + 되돌려 고치기 최대 3번, 합계 4번. **4번째 판도 조립이나 게이트를 넘지 못하면 발행하지 않는다** — `gates.json` 이 없으니 발행기도 쓰지 않는다(exit 4). 잠금을 풀고 「<S> 일본 일간 미발행 — 작성자 4회 실패」와 마지막 위반 목록(`$D/gates.log`)을 PushNotification 으로 보낸다. 오케스트레이터가 문단·문장을 지우거나 고쳐 써서 내보내는 길은 없다. 첫 작성과 첫 고치기는 `model: "sonnet"`, **두 번째 고치기부터는 `model: "opus"`** 로 부르고 그 세션 안에서는 Sonnet 으로 돌아가지 않는다. 위반 문구가 바뀌어도 예산은 다시 세지 않는다. 승격하지 않고 바로 STEP 3 의 미발행 처리로 가는 경우: 원천 데이터 부족(`diag` 의 코어 결측), 파일 경로·도구 실패, 잠금. 설계: `docs/superpowers/specs/2026-10-27-model-routing.md`.

## STEP 3 — 게이트 (순서대로, 전부 exit 0)

```bash
python3 scripts/jp_daily_gates.py --run-dir $D --session $S
```

이 래퍼가 `$D/jpd_$S.html` 에 다섯 게이트를 순서대로 돌린다 — `apply_readability.py`(조판, 글을 고쳐 쓴다) → `check_japan_daily.py --root $D/root` → `check_news.py --datadir $D/root/japan/data --market jp-daily` → `check_readability.py --strict` → `check_style.py`. **전부 exit 0 일 때만** `$D/gates.json`(run_id·세션·조립본과 입력 사본의 해시·`<title>`·요약·게이트별 exit·`verdict: pass`)을 한 번에 쓴다. 하나라도 실패하면 exit 1, `gates.json` 은 없고(있던 것도 지운다) 위반은 출력과 `$D/gates.log` 에 남는다. 게이트를 하나씩 손으로 돌려 통과시킨 판은 발행할 수 없다 — 발행기는 이 기록만 본다. 견해 파일이 있어도 `usable: true` 가 아니면 `telegram_sha256` 은 `null` 이고 그날은 고정 파일을 만들지 않는다.

**「증권사 견해·시장 의견」 절은 일간을 붙잡지 않는다(2026-11-15).** 위반 문구가 `data-tg`·그 절·「텔레그램 요약과 겹친다」를 가리키면: **첫 되돌림에 한해** 그 회차의 다른 위반과 함께 작성자에게 돌려준다. 그 뒤에도 남았거나 나중 회차에 새로 나오면 작성자를 부르지 않고 `python3 scripts/tg_news.py strip --html $D/jpd_$S.html` 로 **절 전체**만 뺀 뒤 래퍼를 처음부터 다시 돌린다(조립이 그 절 때문에 실패하면 같은 명령을 `$D/jpd_$S.body.html` 에 쓰고 다시 조립). strip 으로 사라지지 않는 것(절 밖에 남은 `data-tg`, 작성자 산문 속 채널 이름·요약과 겹치는 문장)은 보통의 산문 위반이다 — 아래 예산으로 돌려준다. 게이트를 다 통과하면 `check_japan_daily.py` 가 찍은 「문단 / 요약」 짝(래퍼 출력)을 읽는다 — 뜻이 요약과 다르거나 요약에 없는 평가·전망을 덧붙인 문단이 있으면 **지우지 않고** 그 짝을 작성자 예산 안에서 돌려준다(예산이 남지 않았으면 절 전체 strip 뒤 래퍼를 다시). 문단 하나를 골라 지우는 자동 삭제는 하지 않는다(2026-11-19).

위반은 목록 그대로 작성자에게 돌려준다(STEP 2 의 예산 — 조립 실패와 합쳐 최대 세 번, 두 번째부터 Opus). **래퍼를 통과한 판을 어떤 이유로든(견해 문단 의미 대조 포함) 작성자에게 되돌릴 때는 먼저** `python3 scripts/jp_daily_gates.py --invalidate "<되돌린 이유>" --run-dir $D --session $S` — 그 판의 발행 자격을 지우고 이유를 로그에 남긴다. 고친 판은 `$D` 안에서 다시 조립하고 래퍼를 처음부터 다시 돌린다. 그래도 남으면 발행하지 않고 잠금을 풀고 위반 목록을 PushNotification 으로 보낸다. 윤문은 하지 않는다 — 게이트를 통과한 판이 최종본이다. **`gates.json` 을 쓴 뒤에는 `$D/jpd_$S.html` 을 건드리지 않는다** — 1바이트라도 바뀌면 발행기가 거부한다. 번역투는 작성자가 마감에서 고친다(2026-10-22) — 게이트를 다 통과한 판으로 `python3 scripts/scan_translationese.py $D/jpd_$S.html | tail -1` 을 돌려 남은 개수를 최종 보고에 옮긴다(읽기만, 발행을 막지 않는다).

## STEP 4 — 발행

**발행기는 완료된 검증에만 묶이고, 커밋에는 발행기가 적은 경로만 들어간다(2026-11-19).** 이 STEP 에서 어느 줄이든 실패해 push 없이 끝나면 「중단 경로」다: `python3 scripts/ci/jpd_clean_start.py --key "$KEY" --session "$S"`(잠금을 쥔 채 발행 산출물만 `origin/main` 으로 되돌린다) → 잠금 release → 출력을 PushNotification. 최종 회차(STEP 1-5 의 조건)면 「<S> 일본 일간 미발행」 경보로 보낸다. 가드가 exit 3 이면 되돌리지 못한 것이니 그 출력도 함께 붙인다.

1. `python3 scripts/publish_japan_daily.py --run-dir $D --run-id $RUN_ID` — **제목·요약 인자는 없다.** 쓰기 전에 `$D/gates.json` 이 이 `run_id` 의 통과 기록인지, `$D` 의 조립본과 `$D/root` 의 후보·뉴스·견해 사본 해시가 기록과 같은지, 조립본의 `<title>`·description 이 기록과 같은지 본다. 통과하면 그 바이트를 옮긴다: 글 `japan/daily/<S>.html`, 발행 스냅샷 `japan/data/daily/<S>.json`(후보 사본 + `published`), 발행 기록 `japan/data/daily/runs/<S>.json`, (`telegram_sha256` 이 있을 때만) 견해 고정 파일 `japan/data/telegram/published/<S>.json`, 이력, `japan/daily.json`(검증된 제목·요약), sitemap. 실제로 바뀐 경로는 `$D/manifest.txt`, 옮긴 것의 해시는 `$D/publish.json`.
   - exit 2 = 이미 발행된 세션이거나 후보가 발행할 수 없는 상태(2판 아님·`complete` 거짓) — 아무것도 쓰지 않았다. 잠금을 풀고 끝낸다.
   - **exit 4 = 검증 기록이 없거나 어긋났다** — 아무것도 쓰지 않았다. 잠금을 풀고 출력을 PushNotification 으로 보낸다. 다시 게이트를 돌려 같은 실행에서 이어 붙이지 않는다(재시도 회차가 새 `run_id` 로 처음부터).
2. 커밋 직전 가드: `git fetch -q origin main` — **실패하면 중단 경로** — 성공하면 `git cat-file -e origin/main:japan/daily/$S.html` 이 있으면(다른 런이 발행) 중단 경로. 없을 때만 진행.
3. **아래 다섯 줄을 순서대로, 한 줄씩. 어느 줄이든 exit 0 이 아니면 다음 줄로 가지 않고 중단 경로.**
   - `git add -- $(cat $D/manifest.txt)` — **명시 경로만 스테이징한다. 디렉터리 단위 `git add` 는 쓰지 않는다.** 수집기 파일(`candidate/`·뉴스·`japan/data/telegram/<S>.json`)은 올리지 않는다 — 워크플로 몫이다.
   - `python3 scripts/publish_japan_daily.py check-staged --run-dir $D` — `git diff --cached --name-only` 가 manifest 와 **정확히 같아야** 0. 더 올라갔거나 빠졌으면 exit 4.
   - `git commit -m "Add JP daily [$S]"`
   - `python3 scripts/publish_japan_daily.py verify-head --run-dir $D` — **push 전 확인이다.** `HEAD` 커밋에서 꺼낸 글·발행 스냅샷·발행 기록·견해 고정 파일(검증이 채택하지 않은 날은 「없음」이어야 한다)·이 세션 뉴스 파일(검증 때 없었으면 「없음」)·`japan/daily.json` 의 이 세션 항목·이력 행·sitemap 을 검증 기록과 견주고, `HEAD` 가 `origin/main` 위의 커밋 하나이며 그 변경 경로가 manifest 와 같은지 본다. 하나라도 다르면 exit 4 — push 하지 않는다. 이미 push 한 커밋은 amend 하지 않는다.
   - `git push`
4. push 가 거절되면 `git pull --rebase`. **rebase 가 끝나면 충돌이 있었든 없었든** 2 의 `fetch`·`cat-file` 가드와 `verify-head` 만 다시 돌리고(커밋을 새로 만들지 않는다) push 한다. `japan/daily.json`·`sitemap.xml` 에서 충돌하면 **원격 판을 받고(`git checkout --ours <파일>` — rebase 중에는 `--ours` 가 upstream, `--theirs` 는 재적용 중인 로컬 커밋이다)** `python3 scripts/update_archives.py --kind jp-daily --key $S` 로 이 세션 항목만 다시 넣는다 — **제목·요약 인자는 받지 않는다**, 발행 기록 `japan/data/daily/runs/<S>.json` 의 검증된 값을 읽는다(sitemap 충돌도 같은 명령이 이 세션 URL 을 병합한다). 이 명령은 두 파일을 다 다시 쓰므로 `git add -- japan/daily.json sitemap.xml`(이 두 경로만, 폴더째가 아니다) → `GIT_EDITOR=true git rebase --continue` → 위의 가드·`verify-head` → push. 글 파일 자체가 충돌하거나 다른 파일에서 충돌하면 `git rebase --abort` 하고 중단 경로. rebase 로 이 세션 뉴스 파일이 새로 들어오거나 바뀌었으면 `verify-head` 가 거부한다 — 중단 경로(재시도 회차가 새 `run_id` 로 다시 쓴다).
5. 잠금 release, PushNotification 으로 `https://fdo2a.github.io/japan/daily/<S>.html`.

## 규칙

- 수집 후보·뉴스 파일의 주인은 수집 워크플로다 — 루틴은 고치지 않는다. 발행 스냅샷·발행 기록(`runs/`)은 발행 단계만 만든다.
- 실행 하나 = `run_id` 하나 = 실행 폴더 하나. 실패한 실행의 폴더·`gates.json`·초안은 다음 실행이 읽지 않는다. 손으로 `git add japan/…` 처럼 폴더째 올리지 않는다.
- 발행 뒤 사실 오류는 review-gate(수동)로 고친다. 이 루틴은 발행된 세션을 다시 쓰지 않는다.
- 일본은행 API 크레디트는 조립이 꼬리에 넣는다 — 지우지 않는다.
