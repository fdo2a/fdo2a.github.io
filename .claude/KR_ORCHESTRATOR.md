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

   exit 3 이면 다른 런이 작성 중이다 — 아무것도 읽거나 쓰지 말고 「locked by another run」만 보고하고 끝낸다. exit 4 도 진행하지 않는다. STEP 2 작성 시작 전과 STEP 3 커밋 직전에 `bash scripts/ci/run_lock.sh renew "$(cat /tmp/kr-lock-key)"` — exit 3 이면 잠금을 잃었으니 커밋하지 않고 끝낸다. **쓰지 않고 끝나는 모든 경로**(아래 가드·수집 뒤 데이터 부족)에서는 `bash scripts/ci/run_lock.sh release "$(cat /tmp/kr-lock-key)"` 로 풀고 끝낸다.

   아래 1·2 로 `report_date` 가 예상 세션과 맞고 `kr/posts/<report_date>.html` 이 이미 커밋돼 있으면 **「already published」만 보고하고 끝낸다**(잠금을 풀고, 알림 없이). 데이터가 예상 세션보다 이르면 이 가드로 멈추지 말고 3번 재수집으로 내려간다 — 어제 글이 있는 건 당연하다.

1. `git -C <repo> pull` 후 `kr/data/kr_market_data.json` Read.
2. `report_date`가 예상 세션과 맞고 `"complete": true`(코어 4종: indices·flows·top_value·sectors)면 그대로 사용. `missing`에 `econ`·`themes`·`flows_intraday`만 있으면 발행 가능(전부 비-코어 — `flows_intraday` 결측 시 §6 장중 수급 서브블록만 생략). `econ`은 ECOS 금리 일부/전량 결측 — writer가 결측 행을 빼고 §9를 재구성한다(2026-07-29 ECOS 연동, 인증키는 레포 시크릿 `ECOS_API_KEY`). `themes`는 2026-07-29 테마 섹션 폐지로 강등.
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
- **§12 오늘의 뉴스는 리서치 대상이 아니다** — 수집 잡이 만든 `kr/data/news/<DATE>.json`(네이버증권 주요뉴스 + `summary_ko`)이 유일한 재료다. 그 요약은 촉매 리서치의 출발점으로 읽어도 되지만, 웹에서 찾은 기사를 §12 에 넣지 않는다(`check_news.py --market kr` 가 막는다).

**테마 리서치는 폐지** (2026-07-29 사용자 지시로 테마 섹션 삭제). `kr_theme.json`은 리서치·작성 어디서도 쓰지 않는다.

## STEP 2 — 리포트 작성 (subagent: kr-report-writer)

Agent 도구로 `kr-report-writer` 동기 실행. 프롬프트: report_date, kr/data 입력 목록(**kr_flows_intraday.json/.png·kr_program.json·kr_technical.json 포함**), research_notes.md, 산출 파일명 `kr_brief_[YYYY-MM-DD].html`(작성자는 `.body.html`·`.meta.json` 만 쓰고 `scripts/render_post.py --market kr` 로 합친다 — head·CSS·상단 바·nav 는 셸이 만든다), 그리고 **writer 스펙의 섹션 순서를 그대로 따르라**는 지시(전략 코멘트는 헤드라인 바로 다음, 테마 섹션 없음, 장중 수급·프로그램 매매는 수급 서브블록, 기술적 분석은 일봉 차트 바로 아래). Agent 미지원 시 general-purpose 에이전트에게 `.claude/agents/kr-report-writer.md` 를 먼저 Read 하라고 경로를 주어 위임하거나 직접 수행(폴백).

**위임한 것은 다시 읽지 않는다.** 서브에이전트는 **동기**(`run_in_background: false`)로 부르고, 기다리는 동안 아무것도 열지 않는다. 에이전트 정의 파일(`.claude/agents/*.md`), 그 에이전트가 읽을 데이터 파일, 직전 발행본은 오케스트레이터가 읽지 않는다 — **경로만 넘기고**, 돌아온 산출물과 게이트 출력만 본다. (2026-09-22 KR 실행이 에이전트를 백그라운드로 띄워 두고 지시문 35 KB·데이터 12개·직전 발행본을 다시 읽다가 5시간 한도로 죽었다.)

**발행 게이트** — (a) `grep -c '확인필요'` = 0; (b) 수급 서술 기준일이 `flows_date` 와 일치하고 provisional/stale 라벨이 있는지; (c) 표 수치 5개 이상을 kr/data/* 원본과 대조. 실패 시 재작성. **완성본만 발행 — 코어 표에 구멍이 있으면 발행 중단, PushNotification 으로 누락 보고.**

아래 게이트는 실패하면 **출력에 찍힌 위반을 그대로** writer 에게 넘겨 다시 돌린다(게이트 소스를 읽지 않는다).

```bash
python3 scripts/check_session.py  --html <kr_brief 절대경로> --datadir kr/data --market kr
python3 scripts/check_weight.py   --html <kr_brief 절대경로> --datadir kr/data --market kr
python3 scripts/check_kr_stance.py --html <kr_brief 절대경로> --datadir kr/data --next <워크스페이스 루트>/kr_stance_next.json
python3 scripts/check_news.py    --html <kr_brief 절대경로> --datadir kr/data --market kr --date <DATE>
python3 scripts/check_movers.py  --html <kr_brief 절대경로> --datadir kr/data --market kr
python3 scripts/check_fund.py    --html <kr_brief 절대경로> --datadir kr/data --market kr
```

- `check_weight.py` 의 KR 계약: 시황·가격군 하한 2,200자, **판단군(전략 코멘트·기술적 분석) 하한 1,800자**, 가격 섹션의 `data-standing`, 가격 섹션의 스탠스 등급 어휘 금지.
- `check_fund.py` — `kr/data/kr_fund_view.json` 의 `status` 가 `ok`·`partial` 이고 날짜가 오늘이면 「아시아 세션 유닛 관측」 섹션이 있어야 하고, 그 밖에는 없어야 한다. 블록(`kr_fund_view.html`)은 그대로 넣는다.
- `check_kr_stance.py` 는 비-코어가 아니다 — 원장이 틀어지면 다음 회차의 복기가 통째로 거짓이 된다.

**가독성·문체 = 초안 수리 루프 (실패로 루틴을 끝내지 않는다)**

1. `python3 scripts/apply_readability.py <html>` → `python3 scripts/check_readability.py --strict --no-inline-images <html>` 과 `python3 scripts/check_style.py <html>` 의 전체 출력을 저장한다. 문체 검사는 항상 돈다.
2. 실패하면 검사 원문을 writer 에게 넘겨 **전체 보고서를 유지한 채 위반 문단만 수정**하게 하고 apply → check 를 반복한다.
3. 같은 위반이 두 번 연속 남으면 오케스트레이터가 그 문단을 직접 고치고(장중 시각이 셋 이상인 문장은 시간대별로 나누기 → 정확한 레벨은 표에 두고 산문엔 가장 가까운 지지·저항만 → 산문 반올림 → 반복 수치 제거), 수치 정본·표·수급 신선도·정책 블록 수를 다시 확인한다. **통과할 때까지 계속한다.**

가독성 실패는 초안 반려일 뿐 미발행 사유가 아니다. 중단은 데이터 정본의 completeness 실패뿐이다.

## STEP 2.5 — 윤문은 루틴에서 하지 않는다 (2026-09-27)

**루틴은 STEP 2 게이트를 통과하면 바로 STEP 3 으로 간다.** `humanize-korean` 윤문을 부르지 않는다 — Claude 주간 한도를 아끼려고 사용자가 뺐다.

말투 손질은 **발행 뒤** 로컬 러너(`scripts/review_gate.py run --correct`, 매시)가 codex 로 한다. codex 는 발행 커밋 스냅샷에서 `prose_in.txt`(이 단계가 쓰던 `humanize_prose.py extract` 산출물)만 고치고, Python 이 `prose_swap.reinsert`(문단마다 숫자·영문 이름·판단 어휘·링크·닮은 정도)와 이 단계가 쓰던 게이트 목록 전체를 발행 커밋의 데이터로 다시 돌린 뒤에만 공개판을 교체한다. 거부되면 원본이 그대로 공개돼 있을 뿐이다. 모듈 `scripts/review/style_pass.py`, 설계 `docs/superpowers/specs/2026-09-27-post-publish-codex-style-pass.md`.

**그래서 초고가 곧 발행본이다.** writer 지시문의 「말하듯이 쓴다」와 STEP 2 의 `check_style` 이 첫 판의 문체를 책임진다.

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
4. **커밋 직전에 가드를 한 번 더** — 작업 중인 변경이 있으니 `pull` 하지 않고 `git fetch -q origin main` 을 먼저 하고 — **실패하면 확인할 수 없으니 커밋하지 않고 끝낸다** — 성공했을 때만 `git cat-file -e origin/main:kr/posts/[YYYY-MM-DD].html` 로 본다. 있으면(그 사이 다른 런이 발행) 아무것도 커밋하지 않고 끝낸다. 아니면 main에 커밋·푸시: `git add -A && git commit -m "Add KR brief [YYYY-MM-DD]" && git push`. 거절되면 `git pull --rebase` 한다 — `kr/posts.json`·`sitemap.xml` 에서 충돌하면 원격 판을 받고(`git checkout --theirs <파일>`) 이 날짜 항목만 STEP 3 의 2·3번으로 다시 넣은 뒤 `git add` → `git rebase --continue`. 그다음 같은 확인을 하고 다시 push 한다. 글 파일 자체가 충돌하면 다른 런이 발행한 것이니 `git rebase --abort` 하고 끝낸다. 푸시 실패 시 나머지 진행 후 최종 메시지·푸시알림에 명확히 보고(클라우드 푸시는 GitHub App Installed 권한 필요).

## STEP 4 — 알림
PushNotification으로 헤드라인 + `https://fdo2a.github.io/kr/posts/YYYY-MM-DD.html`.

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
