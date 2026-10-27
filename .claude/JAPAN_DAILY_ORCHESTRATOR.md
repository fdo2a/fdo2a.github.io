# 일본 시장 일간 마감브리프 — 오케스트레이터 (도쿄 거래일 · KR 브리프 직후)

도쿄 거래일 저녁마다 한 편을 `/japan/daily/<세션>.html` 로 발행한다. 본 루틴은 18:20 KST 에 깨어 KR 브리프 발행을 기다렸다가 시작, 재시도 21:00 KST. 일본 주간(`JAPAN_ORCHESTRATOR.md`)과 데이터·발행이 분리돼 있다. **웹 검색은 하지 않는다** — 숫자는 전부 수집 스냅샷에서, 뉴스는 일간 뉴스 파일에서만. 설계: `docs/superpowers/specs/2026-10-27-japan-daily-design.md`(§13 우선).

## STEP 0 — 세션 고정, 판정, 잠금 (다른 파일을 읽기 전에)

```bash
python3 scripts/ci/routine_due.py jp_daily      # DONE | BUSY | DUE <이유>
read -r S P < <(python3 scripts/ci/routine_due.py jp-session)   # 세션, 직전 세션
KEY=$(bash scripts/ci/run_lock.sh key jp_daily)                 # jpd-<S>
```

`DONE`·`BUSY`·`SKIP` 면 그 한 줄만 보고하고 끝낸다(`SKIP` = 오늘 발행할 세션이 아니다 — 휴장일·주말, 보충 발행 없음).

**KR 브리프가 올라온 뒤에 시작한다**(사용자 지시 2026-10-27 — 본 회차는 18:20 KST 에 깨어 기다린다). `DUE` 면 잠금 전에 `bash scripts/ci/wait_for_kr.sh` (Bash timeout 600000) — exit 0(`DONE` — KR 발행 완료, 한국 휴장일도 즉시 `DONE`)이면 진행, exit 2 면 같은 명령을 다시. **최대 8번(약 72분)** 까지 기다리고, 그래도 KR 이 없으면 기다리지 않고 진행한다(일본 일간을 KR 실패에 묶지 않는다). 재시도 회차(21:00)는 기다리지 않는다. 기다린 뒤에는 `routine_due.py jp_daily` 를 한 번 더 — 그사이 다른 런이 발행했으면 `DONE` 으로 끝난다.

**세션 `S` 는 여기서 한 번 정하고 끝까지 그대로 쓴다** — 자정을 넘긴 재시도가 날짜 산술로 다시 만들면 다른 세션이 된다. `bash scripts/ci/run_lock.sh acquire "$KEY" 120` — exit 3 이면 「locked by another run」만 보고하고 끝낸다(exit 4 도 진행하지 않는다). 수집 전후, 작성자를 부르기 직전과 돌아온 직후, 커밋 직전에 `bash scripts/ci/run_lock.sh renew "$KEY"` — exit 3 이면 잠금을 잃었으니 커밋하지 않고 끝낸다. **쓰지 않고 끝나는 모든 경로**에서 `bash scripts/ci/run_lock.sh release "$KEY"` 로 푼다. release 가 exit 4·5 면 그 출력을 붙여 PushNotification 으로 보고한다.

## STEP 1 — 수집 (Actions 에서만)

루틴 환경은 일경·Yahoo·MOF·BOJ 에 닿지 못한다. 수집은 `collect-japan-daily.yml` 이 하고 `japan/data/daily/candidate/<S>.json`(스냅샷)과 `japan/data/news/daily/<S>.json`(16:30 JST 컷 뉴스)을 커밋한다. **예약 실행은 2~5시간 밀리므로 직접 띄운다**(AGENTS.md 규칙 10②):

1. `git pull -q` 후 `japan/data/daily/candidate/<S>.json` 이 있고 `complete: true` 면 3 으로.
2. `N=jpd-$(date +%s)-$RANDOM` → `gh workflow run collect-japan-daily.yml --ref main -f session=$S -f nonce=$N` → `/bin/sleep 15` → `RUN=$(gh run list --workflow=collect-japan-daily.yml --limit 20 --json databaseId,displayTitle --jq "[.[] | select(.displayTitle | endswith(\" $N\"))][0].databaseId")` — **nonce 로 집는다**. 비면 15초 뒤 한 번 더. 기다림은 `bash scripts/ci/wait_run.sh "$RUN"` 한 번(Bash timeout 600000) — exit 2 면 같은 명령을 한 번 더. `gh` 가 없으면 `mcp__github__actions_run_trigger`·`actions_list` 로 같은 입력·nonce.
3. `git pull -q` 하고 **그다음에** 가드: `git cat-file -e origin/main:japan/daily/<S>.html` 이 있으면 다른 런이 발행했으니 잠금을 풀고 끝낸다.
4. `python3 scripts/build_japan_daily.py diag --session $S` — exit 1(`complete` 거짓 — 닛케이 공식 종가 미확인)이면 발행하지 않는다. 잠금을 풀고, **최종 회차(`[[ "$(TZ=Asia/Seoul date +%F%H)" > "${S}20" ]]` — 세션 날 21시 KST 이후, 자정을 넘긴 재시도 포함)면 「<S> 일본 일간 미발행 — 보충 발행 없음」과 diag 출력을 PushNotification 으로 보낸다.** 본 회차면 알리지 않고 끝낸다(재시도가 이어받는다). 보충 발행은 하지 않는다.

`diag` 가 절 순서(이벤트일이면 매크로가 둘째), 기준일이 다른 값(JGB 직전 세션, 콜 BOJ 최신 관측일), 뉴스 후보 수, 실패한 비-코어 원천을 알려 준다. 그대로 작성자에게 넘긴다.

## STEP 2 — 작성과 조립

`japan-daily-writer` 를 **동기**로, Agent 호출에 `model: "sonnet"` 을 적어 부른다. 넘기는 것: 세션 `S`, `diag` 출력 전문, 스냅샷·뉴스 파일 경로, 직전 일간 경로(있으면). 오케스트레이터는 데이터·지시문을 다시 읽지 않는다. 작성자 마감의 점검(번역투 포함)은 작성자가 한다 — 오케스트레이터는 대신 고치지 않는다.

```bash
python3 scripts/build_japan_daily.py assemble --session $S \
  --body jpd_$S.body.html --meta jpd_$S.meta.json --out jpd_$S.html
```

실패 목록이 나오면 그대로 작성자에게 돌려준다.

**작성자 호출 예산과 막힘 승격(2026-10-27)** — 조립 실패와 STEP 3 게이트 위반이 **같은 예산**을 쓴다: 첫 작성 1번 + 되돌려 고치기 최대 3번, 합계 4번. 첫 작성과 첫 고치기는 `model: "sonnet"`, **두 번째 고치기부터는 `model: "opus"`** 로 부르고 그 세션 안에서는 Sonnet 으로 돌아가지 않는다. 위반 문구가 바뀌어도 예산은 다시 세지 않는다. 승격하지 않고 바로 STEP 3 의 미발행 처리로 가는 경우: 원천 데이터 부족(`diag` 의 코어 결측), 파일 경로·도구 실패, 잠금. 설계: `docs/superpowers/specs/2026-10-27-model-routing.md`.

## STEP 3 — 게이트 (순서대로, 전부 exit 0)

```bash
python3 scripts/apply_readability.py $(pwd)/jpd_$S.html
python3 scripts/check_japan_daily.py --session $S --html jpd_$S.html
python3 scripts/check_news.py --html jpd_$S.html --datadir japan/data --market jp-daily --date $S
python3 scripts/check_readability.py --strict $(pwd)/jpd_$S.html
python3 scripts/check_style.py $(pwd)/jpd_$S.html
```

위반은 목록 그대로 작성자에게 돌려준다(STEP 2 의 예산 — 조립 실패와 합쳐 최대 세 번, 두 번째부터 Opus). 그래도 남으면 발행하지 않고 잠금을 풀고 위반 목록을 PushNotification 으로 보낸다. 윤문은 하지 않는다 — 게이트를 통과한 판이 최종본이다.

## STEP 4 — 발행

1. `mkdir -p japan/daily && mv jpd_$S.html japan/daily/$S.html`
2. `python3 scripts/publish_japan_daily.py --session $S --title "<meta.title>" --headline "<meta.summary>"` — 수집 후보를 발행 스냅샷 `japan/data/daily/<S>.json` 으로 고정하고 이력·`japan/daily.json`·sitemap 을 갱신한다. exit 2 면 이미 발행된 세션이니 커밋하지 않고 끝낸다.
3. 커밋 직전 가드: `git fetch -q origin main` — **실패하면 커밋하지 않고 끝낸다** — 성공하면 `git cat-file -e origin/main:japan/daily/$S.html` 이 없을 때만 진행. `git add japan/daily japan/data/daily japan/data/history japan/daily.json sitemap.xml && git commit -m "Add JP daily [$S]" && git push`.
4. push 가 거절되면 `git pull --rebase`. `japan/daily.json`·`sitemap.xml` 에서 충돌하면 **원격 판을 받고(`git checkout --ours <파일>` — rebase 중에는 `--ours` 가 upstream, `--theirs` 는 재적용 중인 로컬 커밋이다)** `python3 scripts/update_archives.py --kind jp-daily --key $S --title "<title>" --headline "<summary>"` 로 이 세션 항목만 다시 넣은 뒤 `git add` → `git rebase --continue` → 3 의 가드를 다시 하고 push. 글 파일 자체가 충돌하면 다른 런이 발행한 것이니 `git rebase --abort` 하고 끝낸다.
5. 잠금 release, PushNotification 으로 `https://fdo2a.github.io/japan/daily/<S>.html`.

## 규칙

- 수집 후보·뉴스 파일의 주인은 수집 워크플로다 — 루틴은 고치지 않는다. 발행 스냅샷은 발행 단계만 만든다.
- 발행 뒤 사실 오류는 review-gate(수동)로 고친다. 이 루틴은 발행된 세션을 다시 쓰지 않는다.
- 일본은행 API 크레디트는 조립이 꼬리에 넣는다 — 지우지 않는다.
