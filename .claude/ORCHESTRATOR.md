# US Morning Brief — Orchestrator Runbook

You are the orchestrator for the daily US morning market brief. Follow this runbook start to finish.

**Report trading date**: the most recent completed US trading day. **Authoritative source is the committed data file** (STEP 0 below) — trust `report_date` in `data/market_data.json`, which is the S&P 500's actual last-close date. Do NOT compute it from the KST run day; the old weekday-arithmetic rule caused a duplicate-report bug (2026-07-15). Only if no data file exists, fall back to arithmetic: previous US weekday relative to the KST run day (Tuesday KST → Monday US session, … Saturday KST → Friday), stepping back over US market holidays.

The repository fdo2a/fdo2a.github.io is cloned into your workspace as a source (locate with ls / find; if missing, clone https://github.com/fdo2a/fdo2a.github.io). Its .claude/agents/ directory contains the two subagent definitions used in STEP 1 and STEP 2.

## STEP 0 — 커밋된 데이터 파일 확인 (먼저)

A GitHub Actions workflow (.github/workflows/collect-market-data.yml) collects canonical yfinance/FRED data in a network-open runner and commits `data/market_data.json`, `data/intraday.json`, `data/econ_indicators.json`, `data/sector_performance.html`, `data/yield_curve.png` before this routine fires. **This is the primary data path** — the routine's own environment blocks finance hosts (Yahoo/FRED/exchanges all 403), so do NOT try to fetch them here.

1. `git -C <repo> pull` (or re-clone) to get the latest committed data, then Read `data/market_data.json`.
2. If it exists, `report_date` matches today's expected US session (most recent US weekday; if it looks stale by >1 trading day, note it), and `"complete": true` — **copy the five data files to the workspace root** (`market_data.json`, `intraday.json`, `econ_indicators.json`, `sector_performance.html`, `yield_curve.png`) and skip STEP 1's market-data collection entirely. Proceed to STEP 1 for research_notes.md only (the web-research half).
   Also copy the two inherited books if present — they are **non-core**: their absence never blocks publication, and never fails the completeness gate.
   - §8 매크로 논리: `data/macro.json` (yesterday's regime / policy path / transmission), `data/macro_eval.json` (today's verdict — what may move), `data/macro_metrics.json` (axis scores and the new-release list), and **`data/releases/`** — the primary press releases behind today's promoted indicators, already fetched and committed (`index.json` says which succeeded). Copy the whole `releases/` directory. Missing → the writer opens the book in bootstrap mode.
   - §9 멀티에셋 스탠스: `data/stance.json`, `data/stance_eval.json`, `data/stance_metrics.json`. Missing → the writer freezes every grade, or bootstraps.
3. If `data/market_data.json` is missing, stale, or `"complete": false`, note exactly which fields `missing` lists and run the full STEP 1 collector to fill the whole set (or just the gaps). The Actions run may have partially failed; treat its output as a starting point, not gospel.

**토큰 규율**: 이 데이터 파일들이 있으면 그 안의 수치를 웹서치로 재확인하지 않는다. 웹 리서치(STEP 1의 리서치 절반)는 뉴스·해석·컨센서스처럼 파일에 없는 것에만 쓴다. 경제지표 Actual/Previous는 econ_indicators.json이 이미 확정했다.

## STEP 1 — 데이터 수집·검증 (subagent: brief-data-collector)

If STEP 0 already produced a complete market_data.json/intraday.json/yield_curve.png, you still need **research_notes.md** — launch the collector subagent (or fallback) for the web-research portion only (STEP 2 of the agent file: 시황 동인·채권 맥락·메모리·AI 인프라·경제지표 4축). Otherwise run it in full.

Launch the Agent tool with subagent_type "brief-data-collector", run synchronously (run_in_background: false). Prompt: the report trading date [YYYY-MM-DD], whether market data is already present (and its path), and the instruction to produce any missing artifacts in the workspace root: market_data.json, intraday.json, yield_curve.png (may be skipped if week-ago yields are missing), research_notes.md.

Fallbacks: if the subagent type is not available, Read .claude/agents/brief-data-collector.md in the repo and launch a general-purpose agent with that file's body (below the frontmatter) plus the report date as the prompt. If the Agent tool itself is unavailable, execute that file's instructions yourself, in full, before continuing.

Gate before proceeding: market_data.json parses as JSON with non-null indices/sectors/yields; intraday.json parses; research_notes.md exists and contains the 4-axis macro indicator table. If `data/macro_metrics.json` lists `headline_releases`, research_notes.md must also carry section ⑧ (신규 발표 해부) with an entry per release — or an explicit note that the primary release could not be reached. If the gate fails, relaunch the subagent once with the specific error details; if it fails again, fix the gaps yourself using the agent file's instructions.

**Completeness gate (사용자 지시 2026-07-14 — 완성본만 발행)**: the canonical dataset must be COMPLETE before STEP 2 — indices 6종(3대 지수+러셀+Growth/Value), sectors 11종 전부(XLRE 포함) + sector_performance 5기간, yields 2Y/5Y/10Y/30Y + curve chart, FX 4종, commodities 4종, memory 6종, AI infra 5종. "미확인이라 표에서 제외" 처리는 발행 사유가 아니라 발행 중단 사유다. Yields are Yahoo spot (^FVX/^TNX/^TYX) for 5Y/10Y/30Y and FRED DGS2 for 2Y (2026-07-28 사용자 지시) — **tenors carrying different as-of dates is expected, not a gate failure**; the gate only requires a non-null level + week_ago per tenor. If primary sources (yfinance/FRED) are blocked, retry via alternative canonical routes (FRED DGS5/DGS10/DGS30 as the yield fallback, FRED CSV via curl, exchange sites) until complete. If the dataset still cannot be completed, DO NOT publish a partial report to any channel — send a PushNotification listing exactly which fields are missing and why, and stop.

## STEP 2 — 리포트 작성 (subagent: brief-report-writer)

Launch the Agent tool with subagent_type "brief-report-writer", run synchronously. Prompt: the report trading date, the list of input files from STEP 1 (**including macro.json / macro_eval.json / macro_metrics.json and stance.json / stance_eval.json / stance_metrics.json if present**), and the required outputs in the workspace root — morning_brief_[YYYY-MM-DD].html **plus macro_next.json and stance_next.json** (the updated books; the input macro.json / stance.json must be left untouched). Same fallbacks as STEP 1 (agent file: .claude/agents/brief-report-writer.md).

Gate before proceeding (발행 게이트): (a) `grep -c '확인필요' <html>` — must be 0; (b) spot-check 5+ numbers by grepping the HTML for specific values from market_data.json / intraday.json / econ_indicators.json (e.g. `grep -o '4\.62' <html>`), NOT by reading the whole ~34K-token HTML into context. If either check fails, relaunch the writer subagent with the specific violations; repeat until clean. 수치 창작 절대 금지 — 미확인 항목은 삭제·재구성이 원칙.

**매크로 게이트 (§8)** — run `python scripts/check_macro.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: the regime label is outside the 3×3 controlled vocabulary; the regime sits outside `allowed_regimes` (the writer moved it on a day with no new release, inside the 5-business-day lock, or against what the axis scores imply); the axis scores or the FedWatch probability are not quoted in the section; a newly released indicator listed in `headline_releases` has no `data-release` anatomy block, or that block stops at the headline number (no primary source named, fewer than three figures); a transmission direction is outside its `allowed_directions`; the policy path was re-timed without either a new release or a 15%p probability move; a transmission direction conflicts with the §9 stance grade and no `data-reconcile` paragraph explains it; or macro_next.json is missing / not dated today / disagrees with the §8 markers. Relaunch the writer with the exact violations.

**가격 맥락 게이트 (§3·§5·§6·§7)** — run `python scripts/check_price_context.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: a cross-asset relationship whose sign flipped against the prior 60 sessions is not written about (needs a `data-relation="KEY"` paragraph — same discipline as §8's reconciliation, disagreement allowed, silence not); a `data-attribution` block prints the sector split without the residual it cannot explain, or prints one at all on a day the sector weights barely fit the index; or internal machinery (주성분·고유값·필드명) reached the page. Non-core: an older dataset with no `price_context` block passes untouched. Relaunch the writer with the exact violations.

**시황 게이트 (「오늘의 장」)** — run `python3 scripts/check_session.py --html morning_brief_[DATE].html --datadir <workspace> --market us` from the repo clone. It fails the run when: a `data-session` paragraph is missing or empty; a region whose average direction diverged from the S&P 500 is not written about (silence is the failure, disagreement is fine); the participation reading is narrated on a neutral day or omitted on a day it fired; a global close printed in the table disagrees with the collected value, or a close older than three sessions carries no as-of date; the reading is called 「상승 종목 비율」·「등락 종목 수」·「시장 폭」; internal field names or a 「§N」 notation reached the page. Non-core: a dataset with no `session` block passes untouched.

**스탠스 게이트 (§9)** — run `python scripts/check_stance.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: a §9 grade label is outside the controlled vocabulary; a grade sits outside that asset's `allowed_grades` from stance_eval.json; a moved row lacks the MET trigger's actual value (or, for an event trigger, a research_notes.md attribution) in the surrounding text; a row is missing its 유지 일수 or 다음 분기점; or the writer's new stance.json is not dated today / omits a history entry for a moved row. Relaunch the writer with the exact violations. This gate is what keeps §9 a position rather than a restatement of the day's tape — do not waive it. Neither gate is waivable: between them they are the only thing standing between «승계되는 판단» and a daily rewrite wearing the same headings.

**가독성 게이트 = 초안 수리 루프 (실패로 루틴 종료 금지)**

1. `python3 scripts/apply_readability.py <morning_brief 절대경로>`로 v5 조판(데스크톱 본문 17px·**폭 제한 없음** — 문장이 카드를 다 채운다, 라벨은 제 줄에, 캡션 특정도 교정)·빠른 이동·긴 문단 분리를 적용하고, `python3 scripts/check_readability.py --strict <morning_brief 절대경로>`와 **`python3 scripts/check_style.py <morning_brief 절대경로>`**의 전체 출력을 저장한다. 문체 검사는 **쉬운 말 검사를 겸한다(2026-08-26)** — 풀어 쓸 수 있는 음차어, 풀이 없이 처음 나온 전문어, 한 문장에 겹친 낯선 말을 잡는다. 나머지 문체 항목은 「말하듯이 쓴다」 기준에서 셀 수 있는 부분(비인칭 피동·번역투 연결·서술어 없는 명사형 머리말·「~한 상태다」 종결·같은 문단 머리말 반복·「~다」 연속)을 본다. **STEP 2.5의 윤문과 별개로 여기서 항상 돈다** — 윤문은 건너뛸 수 있어도 문체 기준은 건너뛰지 않는다.
2. 실패하면 출력에 찍힌 위반을 원인별로 고친다. 문체 위반은 「말하듯이 쓴다」 절의 해당 항목대로 문장을 다시 쓴다: 헤드라인은 방향·촉매·행동만 남기고, 120자 초과는 시간·주제가 바뀌는 곳에서 문장을 나누며, 수치 5개 이상은 정확한 값은 표에 두고 산문에는 관계만 남긴다. 과잉 정밀도는 산문만 반올림하고 정확한 값은 표에서 보존한다. 반복 수치는 첫 설명과 정본 표 한 곳만 남긴다.
3. writer를 **전체 보고서를 유지한 채 위반 문단만 수정하라**는 지시와 검사 원문으로 다시 실행한다. 수정 뒤 데이터 정본과 표를 재대조하고 apply → strict check를 반복한다.
4. writer 재실행이 두 번 연속 같은 위반을 남기면 오케스트레이터가 해당 문단을 직접 국소 수정한다. 긴 문장 분리 → 중복 수치 삭제 → 산문 반올림 순서로 고치고 다시 검사한다. **통과할 때까지 이 수리 루프를 계속한다.**

가독성 실패는 현재 초안을 반려할 뿐, “오늘 레포트 미발행” 사유가 아니다. 가독성 때문에 중단 알림을 보내지 않는다. 데이터 정본이 끝내 완성되지 않는 경우만 기존 completeness gate에 따라 중단할 수 있다.

## STEP 2.5 — AI 티 제거 (발행 전 마지막 손질)

2026-08-25 사용자 지시. 리포트를 **말하듯이** 쓰라는 문체 기준(`.claude/agents/brief-report-writer.md`의 「말하듯이 쓴다」 절)을 writer가 지켰더라도, 매일 같은 틀로 생성된 글에는 사람이 안 쓰는 리듬이 남는다. 발행 직전에 한 번 걸러낸다.

**1. 원본은 건드리지 않는다. 사본에서 작업한다.**

```bash
cp morning_brief_[DATE].html morning_brief_[DATE].humanizing.html
```

윤문도 검증도 전부 이 사본에서 한다. 원본이 바뀌는 순간은 4번의 finalize 하나뿐이다. 그래서 스킬이 예외로 죽든, 시간이 초과되든, 문단을 반만 쓰고 멈추든, 사본을 지우면 그것으로 끝이다 — 원본은 애초에 한 번도 수정되지 않았다. **원본을 먼저 고치고 나중에 되돌리는 방식은 쓰지 않는다.** 되돌리기가 실패하는 분기가 남기 때문이다.

**2. 산문을 꺼낸다.**

```bash
python3 scripts/humanize_prose.py extract morning_brief_[DATE].humanizing.html
```

`prose_in.txt`(손댈 문단만, 이름표 `[[P001]]`이 붙어 있다)와 `prose_map.json`(사이드카)이 나온다. 표 안 문단·캡션·에디터 노트는 애초에 뽑히지 않는다 — **넘기지 않은 것은 훼손될 수 없다.** 인라인 태그(`<strong>` 등)는 `⟦0⟧` 자리표로 바뀌어 나가고, 되꽂을 때 하나라도 없으면 거부된다.

**3. `prose_in.txt`의 문장을 고친다. 이름표 줄(`[[P001]]`)은 건드리지 않는다.**

`humanize-korean` 스킬은 레포 `.claude/settings.json`이 마켓플레이스(`epoko77-ai/im-not-ai`)째 등록해 둔다 — 이 레포를 클론한 세션은 시작할 때 설치를 시도한다. **그래도 쓸 수 있다고 가정하지 않는다.** 트리거의 `allowed_tools`에 `Skill`이 빠져 있으면 설치돼도 부를 수 없고(스킬이 서브에이전트를 띄우므로 `Agent`도 있어야 한다), 샌드박스가 마켓플레이스를 못 받아오는 경우도 있다.

**목록에 보이는 것과 부를 수 있는 것은 다르다.** `allowed_tools`는 사전 승인 목록이라 이름이 보여도 호출이 거부될 수 있다. 그러니 판정은 호출해 보고 한다 — 거부·오류·산출물 없음 중 하나라도 나오면 **반쯤 나온 결과는 버리고** 직접 고친다. **어느 쪽이든 이 단계를 건너뛰지는 않는다.**

- **스킬로 할 때**: `prose_in.txt`를 입력으로 준다. 스킬은 텍스트를 받아 `_workspace/{run_id}/final.md`(마크다운)를 내놓는다 — **HTML을 고쳐 주지 않으므로 HTML을 통째로 넘기는 사용법은 없다.** 이름표를 그대로 두고 문장만 고치라고, **강도는 「보수」**로 명시한다 — 스킬이 절을 갈아끼우기 시작하면 4번에서 통째로 거부된다.
- **직접 할 때**: `prose_in.txt`를 그 자리에서 고치고, 그 파일을 그대로 4번의 `--payload`로 쓴다. `python3 scripts/check_style.py <html>`의 출력이 작업 목록이다. 검사가 짚은 항목부터 고치고, 검사가 못 보는 아래 셋도 함께 훑는다.
  - **주어를 되살린다.** 앞 문장에서 이어받아 생략한 주어를 다시 넣는다. 「이후 반등해…」 → 「나스닥은 이후 반등해…」.
  - **한 문장에 한 관계만 남긴다.** 「A했다가 B했고 이후 C해서 D로 마감했다」는 문장이 아니라 표다. 시각이 셋 이상이면 나눈다.
  - **판단을 능동으로 쓴다.** 「~로 읽힌다/판정된다」를 「~라고 볼 수 있습니다」나 「A가 B를 끌어내렸습니다」로 바꾼다.

**두 경로 모두 문장만 만진다.** 숫자·자리표·이름표는 그대로 둔다. 4번이 그것을 강제한다.

**4. 되꽂고, 검사하고, 통과했을 때만 원본을 교체한다. 한 명령으로 한다.**

```bash
python3 scripts/humanize_prose.py finalize morning_brief_[DATE].humanizing.html \
  --original morning_brief_[DATE].html --payload <고친 prose_in.txt 또는 _workspace/{run_id}/final.md> \
  --gate "python3 scripts/check_style.py {f}" \
  --gate "python3 scripts/check_readability.py --strict {f}" \
  --gate "python3 scripts/verify_post.py {f} --before morning_brief_[DATE].html --skip-layout" \
  --gate "python scripts/check_macro.py --html {f} --datadir <workspace>" \
  --gate "python scripts/check_stance.py --html {f} --datadir <workspace>" \
  --gate "python scripts/check_price_context.py --html {f} --datadir <workspace>" \
  --gate "python3 scripts/check_session.py --html {f} --datadir <workspace> --market us"
```

되꽂기 → 바뀐 문단 출력 → 게이트 순서로 돌고, **전부 통과했을 때만** `os.replace`로 원본을 교체한다. 하나라도 실패하면 사본을 지우고 exit 1로 끝난다 — 원본은 처음부터 수정되지 않았다. **맨손 `mv`는 쓰지 않는다.** 검사를 건너뛰고 교체할 자리를 남기지 않는 것이 이 명령의 존재 이유다.

되꽂기가 거부하는 것 — **문단마다** 이것들이 원문과 같아야 한다:

- 숫자 (**부호 포함** — `+1.2%`와 `-1.2%`는 다른 값이다)
- 영문 이름·티커 (AAPL과 TSLA를 문단끼리 맞바꾸면 각자 제 원문과는 여전히 닮아 유사도로는 안 잡힌다)
- **판단 어휘** — 개선·악화·보합, 둔화·가속·재가속, 뚜렷·완만·미미, 레짐 이름 9종, 확대·축소·중립. 「완만한 개선」을 「뚜렷한 악화」로 바꾸면 3-gram 유사도는 0.8이 넘는다. 말투는 바꿔도 이 낱말들은 그대로 둔다
- 링크가 감싼 말 (`<a>`가 「연준 보고서」에서 「노동부 자료」로 옮겨 붙으면 멀쩡한 링크가 엉뚱한 출처를 가리킨다)
- 인라인 자리표의 개수와 순서, 문단 길이(0.5~2.0배)
- 그리고 **몸통이 제 원문보다 다른 문단에 더 닮지 않을 것**

**이 단계가 허락하는 것은 문법과 말투까지다.** 종결어미를 바꾸고, 주어를 되살리고, 긴 문장을 나누는 것 — 거기까지다. 절을 갈아끼우는 재작성은 문턱(닮은 정도 0.80)에서 걸린다. 원문에 없던 인과를 넣거나 조건절을 떼어 단정으로 만드는 의미 변화는 어떤 사실 검사로도 못 잡으니, **애초에 그만큼 못 바꾸게 막는 편이 낫다.** 08-21 발행본 58문단 실측에서 말투 편집은 최저 0.95, 절을 갈아끼운 재작성은 중앙 0.62로 두 무리가 갈렸다.

닮은 정도 비교는 총체적 뒤바뀜도 함께 잡는다. 이름표는 자리만 정하지 몸통이 제 자리 것인지는 보증하지 않는다 — 숫자가 없는 문단끼리 내용을 통째로 맞바꾸면 수치 검사도 `verify_post`도 전부 통과한다(2026-08-25 codex 검토에서 실제로 뚫린 뒤 들어간 검사다).

`finalize`는 게이트가 **하나도 없으면 시작하지 않고**, 사본과 원본 경로가 같아도 시작하지 않는다(검사 실패 시 원본을 지우게 된다). 게이트는 셸을 거치지 않고 인자 배열로 실행된다.

`check_macro`·`check_stance`·`check_price_context`가 여기 다시 들어가는 이유가 있다. STEP 2의 게이트들은 **윤문 전 원고를 보고 통과시킨 것이다.** 윤문은 문장을 합치거나 나누므로 문장 길이·수치 밀도가 깨질 수 있고, 통제 어휘나 `data-*` 표식을 건드리면 §8·§9가 검사받지 않은 채로 나간다.

**5. 명령이 찍어 준 「바뀐 문단」을 읽는다.**

허용 범위를 문법·말투로 좁혔으니 남는 것은 그 안에서의 미세한 뉘앙스뿐이다. 그래도 **사람이 한 번 읽는다** — finalize가 바뀐 문단만 전/후로 찍어 주므로 그 출력을 그 자리에서 읽는다.

**이 읽기는 교체를 막지 못한다** — finalize는 이미 원본을 바꾼 뒤다. 그래서 여기서 이상한 것을 발견하면 발행 후 검토 게이트(`.claude/REVIEW_GATE.md`)로 넘긴다. 그쪽이 발행본을 다시 읽고 정정하는 자리다. 윤문이 만든 의미 변화도 그 절차가 잡는 대상에 포함된다.

**윤문이 거부돼도 발행은 계속한다.** 말투는 있으면 좋은 것이고, 게이트는 필수다.

사본(`*.humanizing.html`)·`prose_in.txt`·`prose_map.json`과 스킬 작업 폴더(`_workspace/`)는 `.gitignore`에 걸려 있다. STEP 3의 `git add -A`가 쓸어 담지 않는다.

## STEP 3 — Publish to the blog (GitHub Pages 루트 사이트)

Site base URL: https://fdo2a.github.io/

1. Copy the report HTML into the repo as posts/[YYYY-MM-DD].html, then make two injections:
   (a) Immediately BEFORE `<div class="doc">`, this navigation block:
```html
<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;display:flex;align-items:center;gap:10px;">
  <a href="../index.html" style="text-decoration:none;background:#fff;border:1px solid #E5E8EB;border-radius:9999px;padding:6px 14px;font-size:12px;font-weight:700;color:#191F28;">‹ 전체 보고서</a>
  <a href="../index.html" style="text-decoration:none;font-size:14px;font-weight:800;color:#0064FF;letter-spacing:-0.02em;">US Market Brief</a>
</div>
```
   (b) Immediately BEFORE `<title>`, SEO meta tags:
```html
<meta name="description" content="[헤드라인 한 줄 요약]. [YYYY-MM-DD] 미국 증시 모닝브리프.">
<link rel="canonical" href="https://fdo2a.github.io/posts/[YYYY-MM-DD].html">
<meta property="og:type" content="article">
<meta property="og:title" content="미국 증시 모닝브리프 — [YYYY년 M월 D일 (요일)]">
<meta property="og:url" content="https://fdo2a.github.io/posts/[YYYY-MM-DD].html">
```
2. Copy yield_curve.png into the repo as assets/yield_curve_[YYYY-MM-DD].png, then promote **both** of the writer's books:
   - `macro_next.json` → `data/macro.json`
   - `stance_next.json` → `data/stance.json`
   Tomorrow's Actions run judges today's regime and triggers against these files. Publishing without promoting them leaves both books frozen — and because macro.json also carries `last_seen`, a missed promotion makes every indicator read as newly released tomorrow, which would hand the writer a free regime change.
3. **에디터 노트 (있는 날만)** — if `notes/[YYYY-MM-DD].md` exists in the repo clone, run `python3 scripts/apply_note.py posts/[YYYY-MM-DD].html` from the repo root. That file is the publisher's own view, written by hand before the run; the script drops it in verbatim after §2 전략 코멘트. **Never write, edit, polish, or fact-check that text, and never author the section yourself** — a note the publisher did not write is worse than no note. The script is a no-op (exit 1, page untouched) when the file is missing, empty, or still the unedited template, so it is safe to run unconditionally. Most days there is no note and no section.
4. Update posts.json in the repo root: add {"date", "title", "headline"}. Same-date entry → REPLACE, never duplicate. Keep valid JSON.
5. Regenerate sitemap.xml from posts.json: one <url> for https://fdo2a.github.io/ (lastmod=today, changefreq daily) plus one <url> per post (https://fdo2a.github.io/posts/DATE.html, lastmod). Keep valid XML.
6. Commit and push to main:
   git add -A && git commit -m "Add [YYYY-MM-DD] brief" && git push
   If the push fails, continue with remaining steps and report the failure clearly in your final message and PushNotification.

## STEP 4 — Notify

Send a PushNotification with the headline and the blog post URL (mention any failures).

**발행 채널은 블로그 하나뿐이다 (2026-08-18 사용자 지시로 Notion 발행 중지).** Do NOT publish to Notion, do NOT generate a PDF, do NOT use SendUserFile, and do NOT send email. If a Notion connector is available in the session, leave it alone — its presence is not an instruction to use it.

## RULES
- All prices/% changes in the published report MUST come from market_data.json / intraday.json; macro indicator values from research_notes.md. 수치 창작 절대 금지.
- **완성본만 발행 (2026-07-14 사용자 지시)**: 핵심 표(지수·섹터·채권·FX·원자재·메모리·AI 인프라)에 누락 항목이 있는 채로 발행 금지. 완성 불가 시 발행하지 말고 PushNotification으로 누락 내역을 보고할 것. 웹 리서치로 대체 수집한 시세는 발행 전 반드시 복수 출처 교차 확인 — 단일 검색 결과 수치는 신뢰하지 않는다 (7/13호에서 FX 방향·유가 등락률 오류 발생 전례).
- **발행본에 [확인필요] 금지 (STEP 2 게이트).** 미확인 항목은 끝까지 확인하거나 삭제·재구성.
- Web findings attributed to sources. Professional strategy-desk tone (기관 전략 리포트 톤).
- **「buy-side」 금지 (2026-08-22 사용자 지시)** — 발행본 어디에도 쓰지 않는다. §2 헤더는 「전략 코멘트」, 해석 박스는 「전략 해석」. `scripts/check_macro.py` 게이트가 차단한다.
- Final message: blog (GitHub Pages) delivery status, which subagents ran (or which fallback was used), and any failures.
