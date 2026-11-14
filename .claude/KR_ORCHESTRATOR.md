# KR Evening Brief — Orchestrator Runbook

**적용 시점:** 2026-09-21 KST 이후 새로 작성하는 보고서는 `.claude/DESK_REPORT.md`와 `.claude/RESEARCH_WORKFLOW.md`를 적용한다. 이미 발행된 파일은 이 전환을 이유로 다시 쓰지 않는다.

한국 시장 **저녁 마감브리프**의 오케스트레이터. 평일 18:00 KST 실행. US 모닝브리프(`ORCHESTRATOR.md`)와 데이터·발행이 완전 분리되며, 공유 규칙(디자인·문체·검증)은 US 문서를 참조한다.

**Report trading date**: `kr/data/kr_market_data.json`의 `report_date`(코스피 실제 종가일)를 신뢰한다. KST 요일 산술은 폴백일 뿐. 저녁 발행이라 당일 세션이 마감된 상태여야 한다 — 장중(15:30 이전) 실행 시 당일치는 미완이므로 데이터 워크플로(17:00·17:30 KST cron)가 마감 후 확정한 데이터를 쓴다.

## STEP 0 — 커밋된 KR 데이터 확인 (먼저)

`.github/workflows/collect-kr-data.yml`가 마감 후 Naver+yfinance로 `kr/data/*`를 커밋한다(수급·**장중 수급 궤적**·**프로그램 매매**·거래대금·업종·테마·섹터·지수·장중·**기술적 지표**). **루틴 환경은 금융 호스트가 막힐 수 있으니 직접 fetch 금지 — 커밋된 파일을 읽는다.** 장중 수급은 `kr_flows_intraday.json`(누적 순매수 30분 앵커·극값·방향 전환, 억원)·차트 `kr/assets/kr_flows_intraday_[DATE].png`, 프로그램 매매는 `kr_program.json`(차익·비차익·전체 순매수, 억원), 기술적 지표는 `kr_technical.json`(4종 이평·볼린저·일목)·오버레이 `kr/assets/kr_charts_[DATE].png`(있는 것은 `kr/data/kr_charts_manifest.json` 이 정본) — 전부 비-코어(없어도 발행 게이트 통과, 해당 블록만 생략). **2026-09-17 네이버 SPA 개편으로 장중 수급·프로그램 매매는 소스가 폐지됐다 — 상시 결측이니 §5·§6 의 해당 서브블록을 빼고 쓰고, 수집을 다시 돌려도 안 돌아온다.**

0. **선점 잠금과 멱등 가드 — 다른 파일을 읽기 전에**(2026-09-27, 한도 뒤 재시도 루틴이 생기면서 같은 날 여러 번 뜬다):

   ```bash
   bash scripts/ci/run_lock.sh key kr > /tmp/kr-lock-key && cat /tmp/kr-lock-key
   bash scripts/ci/run_lock.sh acquire "$(cat /tmp/kr-lock-key)" 120
   ```

   exit 3 이면 다른 런이 작성 중이다 — 아무것도 읽거나 쓰지 말고 「locked by another run」만 보고하고 끝낸다. exit 4 도 진행하지 않는다. STEP 2 작성 시작 전과 STEP 3 커밋 직전에 `bash scripts/ci/run_lock.sh renew "$(cat /tmp/kr-lock-key)"` — exit 3 이면 잠금을 잃었으니 커밋하지 않고 끝낸다. **쓰지 않고 끝나는 모든 경로**(아래 가드·수집 뒤 데이터 부족)에서는 `bash scripts/ci/run_lock.sh release "$(cat /tmp/kr-lock-key)"` 로 풀고 끝낸다. **release 는 ref 를 지우지 않고 `released` 표시 커밋으로 바꾼다**(클라우드는 ref 삭제 push 를 거부한다 — 2026-10-20). release 가 **exit 4·5 면 잠금이 남아 재시도 루틴이 stale 까지 BUSY 로 막힌다** — 이 가드가 평소 알리지 않고 끝나는 경로라도 release 출력을 붙여 PushNotification 으로 보고한다. exit 0 은 풀렸거나 이미 남의 것이다.

   아래 1·2 로 `report_date` 가 예상 세션과 맞고 `kr/posts/<report_date>.html` 이 이미 커밋돼 있으면 **「already published」만 보고하고 끝낸다**(잠금을 풀고, 알림 없이). **단 2026-11-06 부터는 뉴스 글도 본다** — 브리프가 있고 `kr/news/<report_date>.html` 이 origin 에 없으면 `python3 scripts/ci/routine_due.py kr-news-input <report_date> <워크스페이스 루트>/kr_news_data` 를 돌린다. `expected` 면(브리프 발행 뒤 한도로 죽은 런) STEP 1~3 을 건너뛰고 **STEP 3.5 만** 한다. `none` 이면 「already published」다. `error …` 면 판정할 수 없으니 쓰지 않고 잠금을 풀고 그 줄을 붙여 PushNotification 으로 보고한다(재시도 루틴이 다음 회차에 다시 본다). 이 명령은 잠금을 보지 않으므로 잠금을 쥔 채 돌려도 된다(`routine_due.py kr` 은 자기 잠금에 BUSY 를 낸다 — 이 판단에 쓰지 않는다). 잠금은 잡은 그대로다. 데이터가 예상 세션보다 이르면 이 가드로 멈추지 말고 3번 재수집으로 내려간다 — 어제 글이 있는 건 당연하다.

1. `git -C <repo> pull` 후 `kr/data/kr_market_data.json` Read.
2. `report_date`가 예상 세션과 맞고 `"complete": true`(코어 4종: indices = 코스피·코스닥 두 지수 모두 종가·검증된 등락률, flows = 코스피·코스닥 두 시장 모두, top_value·sectors. 2026-11-12 부터 못 읽은 값은 0 이 아니라 결측이라 등락률을 못 읽거나 검증하지 못한 날은 `indices` 결측이다 — 계산값으로 채워 발행하지 않는다)면 그대로 사용. `missing`에 `econ`·`themes`·`flows_intraday`만 있으면 발행 가능(전부 비-코어 — `flows_intraday` 결측 시 §6 장중 수급 서브블록만 생략). `econ`은 ECOS 금리 일부/전량 결측 — writer가 결측 행을 빼고 §9를 재구성한다(2026-07-29 ECOS 연동, 인증키는 레포 시크릿 `ECOS_API_KEY`). `themes`는 2026-07-29 테마 섹션 폐지로 강등.
3. 없거나 stale/`complete:false`면 **수집 워크플로를 직접 돌린다**. 이게 1순위다: 2026-08-27 이래 GitHub 예약 실행이 2~5시간씩 밀려(cron 08:00·08:30 UTC 가 실제로는 12:40·12:57 UTC) **수집이 이 루틴보다 늦게 도착하는 날이 정상이 됐다**. 수동 dispatch 는 밀리지 않고 즉시 뜬다.

   ```
   gh workflow run collect-kr-data.yml -f force=true
   sleep 15
   RUN=$(gh run list --workflow=collect-kr-data.yml --event=workflow_dispatch \
           --limit 1 --json databaseId --jq '.[0].databaseId')
   timeout 900 gh run watch "$RUN" --exit-status
   git pull
   ```

   **`gh` 가 없으면**(클라우드 샌드박스, 실측 exit 127) `mcp__github__actions_run_trigger`(`method: run_workflow`)로 걸고 `mcp__github__actions_list`(`method: list_workflow_runs`)로 run id 를 받은 뒤 **`bash scripts/ci/wait_run.sh "$RUN"` 한 번으로** 기다린다(Bash 도구 timeout 을 600000 으로 올린다 — 도구가 먼저 끊으면 같은 명령을 다시 부른다). exit 0 만 성공이다. **Monitor·ScheduleWakeup·짧은 폴링 반복으로 기다리지 않는다** — 깨어날 때마다 전체 컨텍스트가 다시 실린다(2026-09-21 China 실행이 「아직 진행 중」을 확인하느라 수십 턴을 썼다).

   **실행 ID 를 집고 `--exit-status` 를 붙인다** — 맨 `gh run watch` 는 엉뚱한 예약 실행을 기다리거나 대화형 선택으로 빠지고, `--exit-status` 가 없으면 실패한 수집도 「기다렸다」로 통과해 낡은 데이터로 발행된다. 워크플로를 못 돌리는 환경이면 `python scripts/collect_kr_data.py --outdir kr/data`를 직접 실행한다(네트워크 열린 환경에서만).

   **폴백이 끝나면 다시 확인한다** — `report_date`가 여전히 예상 세션보다 이르거나 `complete:false`면 **발행하지 않고 중단한다**. 뒤의 completeness 게이트는 필드가 있는지만 보고 날짜는 보지 않으므로, 여기서 막지 않으면 전 거래일 자료로 오늘 글이 나간다. 한국 휴장일이면 예상 세션 자체가 전 거래일이라는 점에 주의 — 요일 산술이 아니라 `report_date`가 정본이다.

**수급 신선도**: `flows_date`·`flows_provisional`을 STEP 2에 그대로 넘긴다. 당일 확정치가 없으면 writer가 "당일 잠정"/"전 거래일 기준"으로 라벨링한다 — 오케스트레이터가 수급을 창작하지 않는다.

## STEP 1 — 리서치 (research_notes.md)

**운용자 대상 시황·리서치:** STEP 1 시작 전에 `.claude/DESK_REPORT.md`를 읽고 그 문서의 Handoff를 수행한다. 기존 시황·수급·뉴스 자료를 유지하면서 `research_notes.md`에 `운용 판단 브리핑`을 추가한다. 작성자에게 이 절과 해당 문서 경로를 반드시 넘긴다. STEP 2 초안 뒤에 그 문서의 Editorial acceptance를 수행한다. 실제 보유·운용제약이 주어지지 않았으면 자산별 조건부 판단으로 쓰며, 새 거래 아이디어가 없는 날도 정상 발행한다.

**리서치 인계:** `.claude/TRADER_LEARNING.md`를 반드시 읽고 Research handoff를 수행한다. 수집·작성 담당에게 해당 문서 경로, 직전 발행본 경로(없으면 bootstrap), `research_notes.md`의 `학습·복기` 절을 전달한다. STEP 2 초안 뒤에 그 문서의 Editorial check를 수행하고, 위반 문단을 수정한 뒤 기존 발행 게이트를 통과시킨다.

**앞으로 작성하는 보고서:** `.claude/RESEARCH_WORKFLOW.md`를 읽고 증거 → 가설·복기 기록 → 당일 cycle 순서로 진행한다. 원장은 `research/kr`, 원장·증거 파일을 새 발행본과 함께 커밋한다. 기존 발행본은 이 변경의 대상이 아니다. 작성자에게 cycle ID와 모든 미해결 가설을 전달하고, 초안이 아래 검사를 통과해야 한다. 새 자료가 추가되면 cycle도 다시 기록한다.

```bash
python3 scripts/check_research.py check --span daily --html <새 초안> --root research/kr --market kr --date <DATE> --cycle <CYCLE_ID>
```

발행 뒤 codex 문체 수정도 글에 박힌 cycle 로 이 검사를 다시 돌린다(`scripts/review/style_pass.py`).

수치가 아닌 **뉴스·정책 촉매·해석**만 웹 리서치한다(수치는 kr/data가 확정). 최소 포함:
- 그날 코스피·코스닥·수급을 움직인 뉴스(외국인 매매 배경, 대장주 이슈)
- **정책·정치 촉매 — 리서치 비중 최우선 (2026-07-29 사용자 지시로 섹션 확대)**: 밸류업·기업지배구조(상법·자사주)·금투세·대주주 양도세·배당 분리과세·한은 금통위·반도체/2차전지/바이오 보조금·통상(대미 관세·수출규제)·환율당국·국민연금·부동산 규제·지정학·국회 일정 중 그날 해당분. writer가 블록당 **사실 → 전달 경로(수급/이익/멀티플) → 수혜·피해 업종 → 다음 일정·확인 트리거** 4요소를 쓸 수 있도록 각 재료마다 이 네 가지를 채워서 넘긴다. 신규 재료가 없으면 중요한 계류 정책의 변화 여부를 확인하고, 변화가 없다는 사실만 짧게 쓴다. 분량을 채우기 위한 재서술은 하지 않는다.
- **움직인 종목의 「왜」 (§9 특징주용, 2026-09-24)** — `kr/data/kr_movers.json` 의 `groups`(최대 5묶음: 지수 기여 상·하위 2 + |등락| ≥ 5%, 업종·방향으로 묶음)마다 **원인 검색 1회**(「대표 종목명 + 날짜 + 특징주/급등/급락」, 묶음이면 업종명도). `research_notes.md` 의 「움직인 종목의 이유」 절에 묶음 id(`g1`…)별로 **원인 한 줄 + 출처 매체**를 적는다. 출처 있는 원인을 못 찾으면 「확인된 재료 없음」 — 추측으로 채우지 않는다. 종목 등락률은 검색 결과가 아니라 파일 값이 정본이다(장중 기사 숫자는 종가와 다르다).
- 출처 귀속 필수. 복수 출처 교차 확인(단일 검색 수치 불신 — US 전례).
- **오늘의 뉴스는 리서치 대상이 아니다** — 수집 잡이 만든 `kr/data/news/<DATE>.json`(네이버증권 주요뉴스·네이버 뉴스 정치·세계 섹션 + `summary_ko`)이 유일한 재료다. 그 요약은 촉매 리서치의 출발점으로 읽어도 되지만, 웹에서 찾은 기사를 뉴스 칸에 넣지 않는다(`check_news.py` 가 막는다). **2026-11-06 부터 오늘의 뉴스는 마감브리프가 아니라 뉴스 글(STEP 3.5)에 싣는다.**

**테마 리서치는 폐지** (2026-07-29 사용자 지시로 테마 섹션 삭제). `kr_theme.json`은 리서치·작성 어디서도 쓰지 않는다.

## STEP 2 — 리포트 작성 (subagent: kr-report-writer)

**텔레그램(2026-11-06)** — 작성자를 부르기 직전에 한 번, 어느 경로로 왔든 같은 방법으로: `W=<워크스페이스 루트>; rm -f $W/kr_telegram.json; C=$(git -C <repo> rev-parse --verify HEAD) && [ -n "$C" ] && git -C <repo> show "$C:kr/data/kr_market_data.json" | cmp -s - <repo>/kr/data/kr_market_data.json && { git -C <repo> show "$C:kr/data/telegram/<DATE>.json" > $W/kr_telegram.json 2>/dev/null || rm -f $W/kr_telegram.json; }`. 작성자가 읽는 `kr/data/kr_market_data.json` 이 그 커밋의 것과 **바이트까지 같을 때만** 쓴다(로컬 `collect_kr_data.py` 폴백이면 텔레그램 없음). `report_date` 가 `<DATE>` 가 아니면 지운다(다른 날짜로 대체 금지). 이 스냅샷 경로를 작성자 프롬프트에 **명시**하고 게이트도 같은 파일을 쓴다. `stats` 한 줄을 최종 보고에 옮긴다. 규칙: `.claude/agents/kr-report-writer.md` 「텔레그램 견해·의견」.

Agent 도구로 `kr-report-writer` 동기 실행. 프롬프트: report_date, kr/data 입력 목록(**kr_flows_intraday.json/.png·kr_program.json·kr_technical.json 포함**), research_notes.md, 산출 파일명 `kr_brief_[YYYY-MM-DD].html`(작성자는 `.body.html`·`.meta.json` 만 쓰고 `scripts/render_post.py --market kr` 로 합친다 — head·CSS·상단 바·nav 는 셸이 만든다), 그리고 **writer 스펙의 섹션 순서를 그대로 따르라**는 지시(전략 코멘트는 헤드라인 바로 다음, 테마 섹션 없음, 장중 수급·프로그램 매매는 수급 서브블록, 기술적 분석은 일봉 차트 바로 아래). Agent 미지원 시 general-purpose 에이전트에게 `.claude/agents/kr-report-writer.md` 를 먼저 Read 하라고 경로를 주어 위임하거나 직접 수행(폴백).

**2026-11-06 부터 아래 쟁점 분석 문단과 게이트 목록의 `check_news.py`·`check_contested.py` 는 마감브리프에 돌리지 않는다** — 둘 다 STEP 3.5 뉴스 글로 옮겼다. 작성자에게도 §12·12-b 를 쓰지 말라고 넘긴다(writer 스펙). 브리프에 뉴스·쟁점 표식이 남으면 `check_kr_stance.py` 가 막는다. 2026-11-05 까지의 글(정정)은 아래 그대로다.

**쟁점 분석(2026-10-21, 2026-11-05 까지)** — 작성자를 부르기 전에 `python3 scripts/contested_ready.py --market kr --date <DATE> --out <워크스페이스 루트>/contested.json` 을 돌리고 마지막 줄 `contested: …` 를 최종 보고에 옮긴다. 결과는 Mac 의 로컬 러너가 만들어 푸시한다 — **루틴은 기다리지도 수집하지도 않는다.** 작성자는 표식 `<!--CONTESTED-->` 한 줄만 둔다(writer 스펙 12-b). `render_post.py` 로 합친 직후 `python3 scripts/render_contested.py --html <kr_brief> --json <워크스페이스 루트>/contested.json --market kr --date <DATE>` — `ok` 면 섹션, 확정된 none 이면 지움, 아직 없거나 재시도 중이면 자리표시(`<!--contested-pending-->`, 러너가 발행 뒤 채운다). 「쟁점 자리가 0개」면 표식을 `<div class="footer-note">` 바로 앞에 넣고 다시 돌린다. **이 섹션은 고치지 않는다** — 이 섹션 때문에 `check_readability`·`check_style` 이 막히면 `render_contested.py … --omit gate_failed` 로 빼고 게이트를 다시 돌린 뒤 보고에 적는다.

**작성자 모델(2026-10-27)** — 작성자(`kr-report-writer`)를 부르는 모든 Agent 호출 — 첫 작성, 게이트·조립 실패로 되돌려 고치기, general-purpose 폴백 — 에 `model: "opus"` 를 적는다. 에이전트 머리말에도 같은 값이 있지만 폴백에서는 머리말이 빠진다. 수집 담당 등 다른 서브에이전트는 모델을 적지 않는다(본체 모델 상속). **본체가 직접 쓰거나 고치는 모든 단계는 이 루틴의 모델이 Opus 일 때만 한다** — Agent 도구가 없을 때의 폴백, 작성자 타입이 없을 때의 직접 작성, 「같은 위반 두 번 → 오케스트레이터가 직접 고친다」. 본체가 Opus 가 아니면: 작성자 타입이 없으면 general-purpose 를 `model: "opus"` 로 부르고, 직접 고치는 대신 작성자를 `model: "opus"` 로 한 번 더 부르며, Agent 도구가 없거나 그래도 남으면 잠금을 풀고 중단을 보고한다 — 이 중단은 「중단은 completeness 실패뿐」의 예외다. 설계: `docs/superpowers/specs/2026-10-27-model-routing.md`.

**위임한 것은 다시 읽지 않는다.** 서브에이전트는 **동기**(`run_in_background: false`)로 부르고, 기다리는 동안 아무것도 열지 않는다. 에이전트 정의 파일(`.claude/agents/*.md`), 그 에이전트가 읽을 데이터 파일, 직전 발행본은 오케스트레이터가 읽지 않는다 — **경로만 넘기고**, 돌아온 산출물과 게이트 출력만 본다. (2026-09-22 KR 실행이 에이전트를 백그라운드로 띄워 두고 지시문 35 KB·데이터 12개·직전 발행본을 다시 읽다가 5시간 한도로 죽었다.)

**발행 게이트** — (a) `grep -c '확인필요'` = 0; (b) 수급 **문장**의 기준일이 `flows_date` 와 일치하고 provisional/stale 라벨이 있는지(표 제목 라벨은 (c) 의 게이트가 본다); (c) 표 네 종(지수 & 장중·수급·거래대금 상위·환율·금리)의 숫자는 아래 실행 목록의 `check_numbers`(KR, 2026-11-16 부터)가 칸마다 kr/data/* 와 대조한다 — 수기 대조는 **문장 수치** 5개 이상만 원본과 맞춘다. 실패 시 재작성. **완성본만 발행 — 코어 표에 구멍이 있으면 발행 중단, PushNotification 으로 누락 보고.**

아래 게이트는 실패하면 **출력에 찍힌 위반을 그대로** writer 에게 넘겨 다시 돌린다(게이트 소스를 읽지 않는다).

```bash
python3 scripts/run_gates.py check --market kr --date <DATE> --html <kr_brief 절대경로> --datadir kr/data --repo . \
        --tg <워크스페이스 루트>/kr_telegram.json --stance-next <워크스페이스 루트>/kr_stance_next.json --cycle <CYCLE_ID>
```

**실행 목록은 `config/prepub_gates.json` 하나다**(2026-11-08) — 위 한 줄이 목록의 검사기를 전부 돌리고 검사기마다 `== 이름 [필수|참고] 상태` 와 출력 원문을 찍는다. exit 1 = 필수 검사가 실패했거나 **판정 불가**(통과가 아니다). `check_news`·`check_contested` 는 2026-11-06 부터 목록의 `disabled` 에 있다 — 따로 돌리지 않는다. 표 숫자는 `check_numbers` 결과로 기록되고, 문장 수치 수기 대조((c))는 자동 기록 대상이 아니다.

- `check_weight.py` 의 KR 계약: 필수 섹션 비어 있음 금지, §2 문단 순서(2026-10-20 부터 다섯 — 어제 판단의 판정은 「시장 판단과 복기」 첫 문단, 배치는 `check_kr_stance.py` 가 발행일로 고른다), 가격 섹션의 스탠스 등급 어휘 금지. **절대 글자 수 하한은 2026-10-13 폐지** — 「경고:」 줄(서술형 본문 5,000자 초과, 시황군 < 판단군)은 발행을 막지 않으며, 그것을 맞추려고 초안을 늘리거나 줄이지 않는다(`STYLE_EXEMPLARS.md` §11).
- `check_fund.py` — `kr/data/kr_fund_view.json` 의 `status` 가 `ok`·`partial` 이고 날짜가 오늘이면 「아시아 세션 유닛 관측」 섹션이 있어야 하고, 그 밖에는 없어야 한다. 블록(`kr_fund_view.html`)은 그대로 넣는다.
- `check_kr_stance.py` 는 비-코어가 아니다 — 원장이 틀어지면 다음 회차의 복기가 통째로 거짓이 된다.

**가독성·문체 = 초안 수리 루프 (실패로 루틴을 끝내지 않는다)**

1. `python3 scripts/apply_readability.py <html>` → `python3 scripts/check_readability.py --strict --no-inline-images <html>` 과 `python3 scripts/check_style.py <html>` 의 전체 출력을 저장한다. 문체 검사는 항상 돈다.
2. 실패하면 검사 원문을 writer 에게 넘겨 **전체 보고서를 유지한 채 위반 문단만 수정**하게 하고 apply → check 를 반복한다.
3. 같은 위반이 두 번 연속 남으면 오케스트레이터가 그 문단을 직접 고치고(장중 시각이 셋 이상인 문장은 시간대별로 나누기 → 정확한 레벨은 표에 두고 산문엔 가장 가까운 지지·저항만 → 산문 반올림 → 반복 수치 제거), 수치 정본·표·수급 신선도·정책 블록 수를 다시 확인한다. **통과할 때까지 계속한다.**

가독성 실패는 초안 반려일 뿐 미발행 사유가 아니다. 중단은 데이터 정본의 completeness 실패뿐이다.

## STEP 2.5 — 번역투 점검은 작성자 마감에서 한다 (2026-10-22)

**루틴에 따로 윤문하는 단계는 없다** — Claude 윤문(humanize-korean)은 9/27 에 뺐고, 발행 뒤 로컬 러너의 codex 문체 몫은 2026-11-06 부터 지적만 남긴다(`review_gate.STYLE_REWRITE`). 발행 전 흐름 편집은 STEP 2.6(기본 꺼짐)이다.

2026-10-22 사용자 지시 「발간 직전에 번역투만 점검·수정」은 **작성자 지시문의 「번역투 점검 — 마감의 첫 단계」** 가 맡는다. 작성자가 `scripts/scan_translationese.py` 로 자리를 찾아 자기 문장을 고치고, 그 판이 STEP 2 게이트를 지난다. **오케스트레이터는 대신 고치지 않는다** — 근거와 문맥을 가진 작성자만 「에 대한」을 지워도 뜻이 그대로인지 안다. 게이트를 다 통과한 판으로 `python3 scripts/scan_translationese.py <html> | tail -1` 을 돌려 남은 개수를 최종 보고에 옮긴다(발행을 막지 않는다). 설계와 거절된 세 안: `docs/superpowers/specs/2026-10-22-pre-publish-translationese.md`.

## STEP 2.6 — 문체 마감 (꺼져 있으면 건너뛴다, 2026-11-06)

`python3 scripts/close_guard.py enabled` 가 `close: off` 면 아무것도 읽지 않고 STEP 2.9 로 간다(기본값 — `config/style_close.json`). `close: on` 이면 `.claude/STYLE_CLOSE.md` 의 A 를 `H=kr_brief_[DATE].html`·`M=kr` 로 따르고, STEP 3 에서 같은 파일의 B 를 함께 한다. 마감은 작성자 재호출(edits JSON) → guard → 검사자 `close-meaning-checker` → 게이트 전체 재실행 순이고, 무엇이 실패해도 게이트를 이미 지난 판(pre)으로 발행한다.

## STEP 2.9 — 판단 원장 승계

게이트를 다 통과한 뒤, writer가 낸 `kr_stance_next.json`을 **`kr/data/kr_stance.json`으로 옮긴다.** 이것이 내일 STEP 0의 입력이 되고, 내일 수집기가 여기 적힌 무효화 레벨을 그날 종가로 검산해 `kr_stance_eval.json`을 만든다.

```
cp <워크스페이스 루트>/kr_stance_next.json <repo>/kr/data/kr_stance.json
```

**순서가 중요하다.** 게이트 전에 옮기면 통과 못 한 판단이 원장에 남고, 발행을 접은 날에도 내일이 그 판단을 채점한다. **발행이 확정된 뒤에만 옮긴다.** STEP 3의 `git add -A`가 이 파일을 함께 커밋한다.

## STEP 3 — 블로그 발행 (/kr/)

1. 리포트 HTML을 `kr/posts/[YYYY-MM-DD].html`로 복사한다. **아무것도 주입하지 않는다** — 네비게이션과 SEO 메타(description·canonical·og)는 `scripts/render_post.py` 가 이미 한 번 넣었다. 다시 넣으면 head 태그가 두 벌이 된다(2026-09-23 US 발행본). 파일에 `post-shell-v1` 이 없으면 작성자가 셸을 건너뛴 것이다 — head 를 손으로 고치지 말고 렌더로 돌려보낸다.
2. `kr/posts.json`에 `{date,title,headline}` 추가(같은 날짜는 REPLACE, 중복 금지). 유효 JSON 유지.
3. `sitemap.xml`에 `https://fdo2a.github.io/kr/posts/DATE.html` url 추가(전체 재생성, US 항목 보존).
**STEP 2.6 이 돌았으면**(`close: on`) 아래 커밋 명령을 한 줄로 돌리지 말고 `.claude/STYLE_CLOSE.md` B 의 순서(add → verify → staged-scan → commit → push 전 verify → push → push 뒤 verify)로 나눠 돈다 — 검사가 exit 0 이 아니면 커밋·push 하지 않는다.
4. **커밋 직전에 가드를 한 번 더** — 작업 중인 변경이 있으니 `pull` 하지 않고 `git fetch -q origin main` 을 먼저 하고 — **실패하면 확인할 수 없으니 커밋하지 않고 끝낸다** — 성공했을 때만 `git cat-file -e origin/main:kr/posts/[YYYY-MM-DD].html` 로 본다. 있으면(그 사이 다른 런이 발행) 아무것도 커밋하지 않고 끝낸다. 아니면 5 로 간다.
5. **최종 검증 기록 (2026-11-08)** — 4 의 가드를 통과한 뒤, 커밋 전에 **실제로 올릴 파일**로:
   `python3 scripts/run_gates.py record --market kr --date [YYYY-MM-DD] --html kr/posts/[YYYY-MM-DD].html --datadir kr/data --repo . --tg <워크스페이스 루트>/kr_telegram.json --stance-next <워크스페이스 루트>/kr_stance_next.json --cycle <CYCLE_ID> --out verification/kr/[YYYY-MM-DD].json`
   - exit 0 → 6. **기록한 뒤에는 글을 고치지 않는다** — 고쳤으면 record 를 다시 돈다.
   - exit 1(필수 검사 실패·판정 불가) → 찍힌 위반을 writer 에게 넘겨 고치고 STEP 2 게이트 → STEP 3 1-3 → record, 최대 2회. 그래도 1이면 **커밋하지 않고** 잠금 해제, 알림에 막은 검사기를 적고 중단. `close: on` 이면 고쳐 쓰지 않고 STYLE_CLOSE 의 pre 판(이 발행 건에서 게이트를 지난 판)으로 다시 하고 record — 그 판도 1이면 중단.
   - exit 4(검사는 다 돌았고 발행 가능, **레포 안 기록 저장만** 실패) → 찍힌 `fallback_record=<경로>`(레포 밖 같은 기록)를 적어 두고 발행한다. 아래 verify 에 `--record-file <그 경로>` 를 붙인다 — 기록이 레포에 없어도 글·검사 코드·원장·입력이 바뀌면 막는다. 알림에 「검증 기록 없음 — 저장 실패」(2026-11-22 까지 시험 운영).
   - exit 5(기록 도구 자체 오류, 또는 대체 기록도 못 남김) → 최종 판이 검사됐다는 근거가 없다. **커밋하지 않고** 잠금 해제, 알림에 「검증 도구 오류 — 발행 보류」와 오류 줄을 적고 중단(필수 검사를 못 돌린 것과 같다).
6. **커밋·푸시** — 명령을 `&&` 로 잇지 말고 한 줄씩 돌려 종료 코드를 본다: `git add -A` → `python3 scripts/run_gates.py verify --market kr --date [YYYY-MM-DD] --repo . --index --datadir kr/data --tg <워크스페이스 루트>/kr_telegram.json --stance-next <워크스페이스 루트>/kr_stance_next.json` — exit 0 이면 `git commit -m "Add KR brief [YYYY-MM-DD]"`. exit 1 이면 5 의 record → `git add -A` → verify 다시. **exit 4(기록 없음)는 5 의 record 가 4 였을 때만** 넘어간다 — 그때는 `--record-file <fallback_record 경로>` 를 붙여 0 이어야 commit. **exit 2(git 을 읽지 못함)는 커밋하지 않고 중단**.
   **모든 `git push` 직전**(`pull --rebase`·충돌 해결 뒤 포함) `python3 scripts/run_gates.py verify --market kr --date [YYYY-MM-DD] --repo . --rev HEAD --datadir kr/data --tg <워크스페이스 루트>/kr_telegram.json --stance-next <워크스페이스 루트>/kr_stance_next.json` — exit 0 → `git push`. exit 1 → record → `git add -A` → `git commit --amend --no-edit` → 다시 verify. exit 4 → record 가 4 였을 때만, `--record-file <fallback_record 경로>` 를 붙여 0 이면 push. exit 2 → push 하지 않고 중단.
   push 거절되면 `git pull --rebase` 한다 — `kr/posts.json`·`sitemap.xml` 에서 충돌하면 원격 판을 받고(`git checkout --theirs <파일>`) 이 날짜 항목만 STEP 3 의 2·3번으로 다시 넣은 뒤 `git add` → `git rebase --continue`. 그다음 같은 확인을 하고 다시 push 한다. 글 파일 자체가 충돌하면 다른 런이 발행한 것이니 `git rebase --abort` 하고 끝낸다. 푸시 실패 시 나머지 진행 후 최종 메시지·푸시알림에 명확히 보고(클라우드 푸시는 GitHub App Installed 권한 필요).

## STEP 3.5 — KR 뉴스 글 (subagent: kr-news-writer) — 브리프를 발행한 **뒤에** (2026-11-06 부터)

2026-11-05 사용자 지시 「한국 레포트 칸에도 미국처럼 뉴스탭을 새로 만들어 분리해서 발행하자. 미국처럼 정치, 매크로, 특정 이슈가 있는 산업으로 각각 최소 3개씩」. US STEP 3.5 와 같은 모양이다. **브리프가 먼저다** — 이 단계는 STEP 3 커밋·푸시 다음에 시작하고, 이 글이 게이트를 끝내 못 넘으면 이 글만 빼고 최종 보고·알림에 사유를 적는다. 브리프를 다시 열지 않는다.

0. **멱등 가드·입력** — `kr/news/[DATE].html` 이 이미 커밋돼 있으면 건너뛴다. 아니면 `python3 scripts/ci/routine_due.py kr-news-input [DATE] <workspace>/kr_news_data` 로 **브리프 발행 커밋의** 뉴스 수집분을 `<workspace>/kr_news_data/news/[DATE].json` 에 꺼낸다(발행 뒤 재수집이 `kr/data` 를 바꿔도 이 판이 근거다). 출력이 `expected` 가 아니면 이 글을 만들지 않고, 최종 보고에 그 줄과 수집분의 `summary_note`·`notes` 를 옮긴다(`error …` 는 근거를 못 읽은 것이다 — 재시도 루틴이 다음 회차에 다시 본다)(재시도 판정도 같은 판으로 그날 뉴스 글을 기다리지 않는다). 아래에서 `<NEWSDATA>` = `<workspace>/kr_news_data`.
0-1. **쟁점 분석 결과** — `python3 scripts/contested_ready.py --market kr --date [DATE] --out <workspace>/contested.json`, 마지막 줄 `contested: …` 를 최종 보고에 옮긴다. 루틴은 기다리지도 수집하지도 않는다.
0-2. **텔레그램 입력**(2026-11-12) — `python3 scripts/tg_news.py input --market kr --date [DATE] --repo . --news <NEWSDATA>/news/[DATE].json --out <workspace>/kr_telegram_news.json`. 브리프 **발행 커밋**의 텔레그램 파일에 뉴스 글용 표시(`news_use`)를 달아 꺼낸다 — 같은 런이든 재개든 이 명령 하나다(워크스페이스의 `telegram.json` 을 넘기지 않는다). `--news` 는 **이 단계의 작성자와 `check_news.py` 가 쓰는 바로 그 파일**이다. 마지막 줄 `tg-news: …` 를 최종 보고에 옮긴다. **그 줄이 `tg-news: 쓸 수 있는 …` 일 때만** `<workspace>/kr_telegram_news.json` 경로를 작성자 프롬프트에 적는다. `none`·`error` 면 「텔레그램 없음」이라고 적는다 — 이 글을 막지 않는다. 종료 코드 1(옛 출력 파일을 못 지움)이면 그 파일이 남아 있다: 「텔레그램 없음」으로 하고, 아래 `check_telegram.py` 의 `--tg` 에는 그 파일 대신 없는 경로(`<workspace>/kr_telegram_news.json.none`)를 준다.
1. Agent 도구로 subagent_type `kr-news-writer` 를 `model: "opus"` 로 동기 실행한다(없으면 general-purpose 에 `.claude/agents/kr-news-writer.md` 를 읽으라고 경로를 주어 `model: "opus"` 로). 프롬프트: 기준일, 레포 경로, 뉴스 데이터 폴더 `<NEWSDATA>`(파일은 `<NEWSDATA>/news/[DATE].json`), `kr_telegram_news.json`(0-2 에서 생겼으면 경로, 아니면 「텔레그램 없음」), 산출 `kr_news_[DATE].html`. 합친 직후 `python3 scripts/render_contested.py --html kr_news_[DATE].html --json <workspace>/contested.json --market kr --date [DATE]`.
2. **게이트** — 실패하면 출력을 그대로 넘겨 위반 문단만 고치게 한다(두 번 연속 같은 위반이면 STEP 2 의 「작성자 모델」 규칙대로). 쟁점 섹션은 고치지 않는다 — 그 섹션 때문에 막히면 `render_contested.py … --omit gate_failed` 로 빼고 다시 돌린다.
   ```bash
   python3 scripts/apply_readability.py kr_news_[DATE].html
   python3 scripts/check_news.py --html kr_news_[DATE].html --datadir <NEWSDATA> --market kr-news --date [DATE]
   python3 scripts/check_telegram.py --html kr_news_[DATE].html --tg <workspace>/kr_telegram_news.json --news <NEWSDATA>/news/[DATE].json --date [DATE] --layout news
   python3 scripts/check_contested.py --html kr_news_[DATE].html --json <workspace>/contested.json --market kr --date [DATE]
   python3 scripts/check_readability.py --strict --no-inline-images kr_news_[DATE].html
   python3 scripts/check_style.py kr_news_[DATE].html
   grep -c '확인필요' kr_news_[DATE].html     # 0
   ```
   `--market kr-news` 는 정치·정책·매크로·산업에 **하한 3건**을 건다(그날 실을 수 있는 기사가 3건 이상인 갈래만). 색은 칠하지 않는다(KR). `python3 scripts/scan_translationese.py kr_news_[DATE].html | tail -1` 을 최종 보고에 옮긴다.
2-1. **텔레그램 섹션 — 실패 처리와 다시 읽기**(2026-11-12) — `check_telegram.py … --layout news` 가 실패하면 출력을 작성자에게 넘겨 지목된 표식·잇는 말만 고치게 한다(최대 2회 — 메시지가 고치는 법을 말한다). 그래도 실패하면 `python3 scripts/tg_news.py strip --html kr_news_[DATE].html` 로 「증권사 견해·시장 의견」 섹션만 빼고 **같은 `<workspace>/kr_telegram_news.json` 로 위 게이트를 전부 다시** 돌린다. 섹션을 빼고도 「표식 밖 문장이 텔레그램 요약과 겹친다」가 남으면 그 문장을 작성자가 지운다 — 그래도 안 되면 이 글은 내지 않는다. 섹션을 뺐으면 최종 보고에 적는다.
   **다시 읽기는 발행 직전 마지막 일이다.** 게이트를 전부 통과한 최종판에서 `check_telegram.py` 가 찍은 것을 오케스트레이터가 직접 읽는다(작성자에게 맡기지 않는다). **① 문단**(글 순서 그대로 — `[id]` 뒤가 그 항목의 문장, 나머지가 잇는 말): 문장마다 누구의 말로 읽히는지(이름·「같은 보도는」·「시장에서는」이 어디까지 가리키는지, 앞 문장 안에 다른 화자가 나올 때), 「반면」 같은 관계어가 맞는지, 잇는 말이 요약에 없는 사실·평가·전망을 말하지 않는지. **② 항목별 `문장 / 요약` 쌍**: 뜻이 같은지, 요약에 없는 평가·날짜·기간을 덧붙이지 않았는지(`날짜:` 줄이 찍힌 항목은 표기만 바꾼 것인지 본다). 틀린 것은 고쳐 쓰지 않고 지운다 — 틀린 항목은 그 `<span data-tg>` 와 앞뒤에 붙은 잇는 말을 같이, 틀린 잇는 말은 그것만. 지운 자리 뒤의 표식이 「같은 보도는」「한 연구원은」으로 시작하고 있었으면 게이트가 이름 누락으로 잡는다 — 그 표식에 이름을 직접 단다(이것만은 고쳐 쓴다). 그렇게 해도 문단이 말이 안 되면(관계어만 남는다, 여는 말이 가리킬 것이 없다) 그 `<p>` 를 통째로 지운다. 표식이 하나도 안 남으면 `strip`. 지운 뒤 게이트 전부 → 다시 읽기. 읽은 뒤에는 파일을 건드리지 않고 발행한다. 이 글은 발행 뒤 자동 검토 대상이 아니라 이 읽기가 유일한 뜻 확인이다.
3. **발행 (이 글만의 커밋)** — `kr_news_[DATE].html` 을 `kr/news/[YYYY-MM-DD].html` 로 복사하고(주입 없음, `post-shell-v1` 확인) `python3 scripts/update_archives.py --root . --kind kr-news --key [YYYY-MM-DD] --title "[meta.json 의 title 에서 「 | DATE」 를 뗀 것]" --headline "[그 글의 h1]"`. 커밋 직전 `git fetch -q origin main && ! git cat-file -e origin/main:kr/news/[YYYY-MM-DD].html` 일 때만 `git add kr/news/ kr/news.json sitemap.xml && git commit -m "Add KR news [YYYY-MM-DD]" && git push` — 거절되면 `git pull --rebase` 후 다시 push 한다(`kr/news.json`·`sitemap.xml` 충돌은 STEP 3 의 6번과 같은 방법).

## STEP 4 — 알림
PushNotification으로 헤드라인 + `https://fdo2a.github.io/kr/posts/YYYY-MM-DD.html`, `검증 기록:` 한 줄(record 의 「판정 … · 발행 …」, 없으면 「검증 기록 없음 — 사유」), 그리고 KR 뉴스 글 URL(`https://fdo2a.github.io/kr/news/YYYY-MM-DD.html`) 또는 내지 않은 사유. 쟁점 분석은 `contested: …` 한 줄(실렸으면 주제, 아니면 상태·사유)을 붙인다.

**발행 채널은 블로그 하나뿐이다 (2026-08-18 사용자 지시로 Notion 발행 중지).** Notion·PDF·이메일 모두 없음. 세션에 Notion 커넥터가 붙어 있어도 쓰지 않는다 — 연결돼 있다는 사실이 사용 지시는 아니다.

## STEP 5 — 발행 후 자동 검토·정정

최초 push 성공 뒤 로컬 러너가 Codex 검토와 Claude 정정·재게시를 이어받는다.
절차는 `.claude/REVIEW_GATE.md`의 「US·KR 무인 정정」을 따른다.
클라우드 루틴은 Codex 검토를 완료했다고 보고하지 말고 최초 발행과 사후 검토 대기를 구분한다.
이미 발행된 글의 재작성 금지 가드는 그대로 유지한다. 정정은 로컬 러너가 맡는다.

## RULES
- 모든 수치는 kr/data/*에서만. 수치 창작 절대 금지.
- **수급 신선도 라벨 필수** — 당일 확정 없으면 잠정/전거래일 명시.
- **완성본만 발행** — 코어 표 구멍 시 중단·보고.
- 발행본 [확인필요] 금지. 출처 귀속. 근거와 판단이 분명한 자연스러운 보고서 문체.
- **buy-side 표기 금지 (2026-08-22 사용자 지시)** — 전략·리포트·시황 정리로. 발행 전 `grep -i "buy[- ]\?side" kr_brief_*.html`로 확인.
