# 월간 정리 파이프라인 (월 롤오버 다음날)

US·KR 월간 정리 2편을 발행한다. **그 달 발행본의 총정리**이지 새 취재가 아니다 — 웹 검색도 시세 재수집도 하지 않는다.

**편집 계약:** 준비 단계에서 `.claude/DESK_REPORT.md`를 읽고 writer에게 경로를 전달한다. 기간 시황과 성과표를 유지하면서 현재 판단의 함의·기대와 결과의 차이·다음 확인 조건을 연결한다. 주간은 중요한 질문의 심화, 월간은 판단 방법의 복기다. 작성 전후 그 문서의 Editorial acceptance를 적용하고 기존 연구·수치·문체 검사를 모두 수행한다.

## STEP 0 — 준비와 월 롤오버 판정 (먼저 확인하고, 아니면 즉시 끝낸다)

이 트리거는 달 경계를 놓치지 않으려고 여러 날에 걸쳐 뜬다. **대부분의 실행은 아무것도 하지 않고 끝나야 한다.** 운영 전제: **매월 1-7일 매일 같은 시각**에 뜬다 — 1일이 주말이면 1·2일에는 US 데이터가 아직 지난달이라 WAIT 로 끝나고, 그 뒤 실행이 없으면 그 달 월간이 안 나온다(2026-10-27 codex 설계 검토 #2).

레포(`fdo2a/fdo2a.github.io`)를 클론하고 워크스페이스로 삼는다. 판정 전에 `git pull -q origin main` 으로 작업 트리를 원격과 맞춘다 — **실패하면 판정하지 않고 PushNotification 으로 알린 뒤 끝낸다.** 판정 스크립트는 fetch 하지 않고 이렇게 맞춘 `HEAD` 를 읽는다 — 판정과 작성이 같은 커밋을 봐야 한다(codex 설계 검토 #4·구현 검토 #3). 판정 뒤에는 STEP 6 직전까지 pull 하지 않는다.

```bash
python3 scripts/ci/routine_due.py monthly
```

한 줄이 나온다: `<판정> <KEY> <남은 시장 또는 이유>`.

- `DONE` — `monthly/<KEY>.html` 과 `kr/monthly/<KEY>.html` 이 **둘 다** 있다. 그 줄만 남기고 끝낸다.
- `WAIT` — 남은 시장의 `report_date` 가 아직 `<KEY>` 달을 넘지 않았다(월 롤오버 아님). 그 줄만 남기고 끝낸다. 리서치도 파일 읽기도 더 하지 않는다 — 토큰 낭비다.
- `BLOCKED` — 남은 시장의 집계가 없거나 불완전하거나, `end_date` 가 그 달 마지막 거래일이 아니거나, `sessions` 가 그 달 거래일 수(휴장 달력)와 다르다, 또는 git 실패. KR 만 남아도 **US 집계는 검사한다** — STEP 3 스코어카드가 US 집계로 만들어진다. **발행하지 않고 그 줄을 PushNotification 으로 알린 뒤 끝낸다.** 집계는 수집기가 현재 `report_date` 의 달만 갱신하므로 월말 수집이 실패한 달은 다시 돌려도 고쳐지지 않는다.
- `DUE` — 둘째 토큰이 `<KEY>`(예: `2026-10`), 셋째가 남은 시장(`us,kr` · `us` · `kr`).

**`<KEY>` 는 이 출력의 값을 끝까지 쓴다. 다시 계산하지 않는다.** KEY 는 서울 달력의 직전 달이고(`scripts/us/period.py` `prev_month_key`), `report_date` 로 다시 만들면 새 달 키가 된다 — report_date 2026-11-02 는 `2026-11` 을 낸다(2026-10-27 codex 검토). **날짜 산술로 직접 도출하지도 않는다** — 2026-07-13 중복 생성 직전까지 갔던 버그와 같은 부류다.

**「집계 파일이 있다」·`complete: true` 만으로 판정하지 않는다** — `complete` 는 「본 세션 사이에 빈 날이 없다」일 뿐이다. 수집기는 당월 집계를 매일 갱신하므로 새 달 이틀째에도 1세션짜리 당월 파일이 `complete: true` 로 존재한다. 그걸 롤오버로 읽으면 한 달을 이틀로 정리해 발행한다(2026-08-30 codex 검토). 판정 스크립트가 시장별 `report_date`·`end_date`·거래일 수를 따로 본다.

**부분 발행 이어받기** (US 만 나가고 KR 이 실패한 달을 다음 실행이 이어받는다 — 예전 STEP 0 은 US 글만 보고 영구히 끝냈다):

- **남은 시장만 만든다** — US 가 이미 있으면 STEP 4 를, KR 이 이미 있으면 STEP 5 를 건너뛰고, STEP 1·2 와 STEP 6 도 **남은 시장만** 본다. **STEP 3 은 남은 시장과 무관하게 항상 돈다** — KR 게이트도 `data/period_scorecard.json` 을 받으므로, 건너뛰면 다른 기간의 스코어카드가 그 자리에 남는다(codex #3). 그래서 US 가 이미 나갔어도 US 집계는 필요하고, STEP 0 판정이 그것까지 확인한다.
- STEP 6 커밋 직전에는 작업 중인 변경이 있으니 `pull` 하지 않고 `git fetch -q origin main` 을 먼저 하고 — **실패하면 확인할 수 없으니 커밋하지 않고 끝낸다** — 성공했을 때만 `git cat-file -e origin/main:<그 글 경로>` 로 확인한다. 그 사이 생긴 쪽은 글·목록 갱신 모두 커밋에서 뺀다. push 가 거절되면 `git pull --rebase` 하고, `monthly.json`·`kr/monthly.json`·`sitemap.xml` 충돌은 원격 판을 받은 뒤 STEP 6 의 `update_archives.py` 를 이 키로 다시 돌려 `git rebase --continue` 한다. 글 파일 자체가 충돌하면 다른 런이 발행한 것이니 `git rebase --abort` 하고 끝낸다.

## STEP 1 — 집계 파일 확인

`data/monthly/<KEY>.json`과 `kr/data/monthly/<KEY>.json`이 있고 `complete: true`인지 본다(STEP 0 에서 한 시장이 이미 발행됐으면 남은 시장의 집계만). STEP 0 판정이 같은 커밋으로 이미 확인했으니 여기서 어긋나면 작업 트리가 판정 뒤에 바뀐 것이다.

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

## 연구 복기 준비 — 작성자 호출 전

`.claude/RESEARCH_WORKFLOW.md`의 기간 복기를 수행한다. 시장별 `research/us`·`research/kr` 원장과 저장 증거만 사용한다. 집계의 START·END와 실제 검토 시각 AS_OF를 고정하고 `check_research.py render`로 요약을 만든다. 작성자는 생성된 section을 그대로 삽입하고, 주간에는 가설 변화와 반증, 월간에는 반복된 설명의 한계와 다음 검증 조건을 서술한다. 초기 원장이 비어 있으면 축적 전이라고 밝힌다.

아래 US 명령의 `<AS_OF>`는 같은 고정 시각이다. KR 실행에서는 모든 입력 경로와 `--research-root research/kr --market kr`를 함께 바꾼다. 발행 전 `check_research.py check`도 workflow대로 수행한다.

## STEP 4 — US 주간 정리

`period-report-writer` 서브에이전트를 `market=us, span=monthly`로 부른다. 입력은 `recap_us.json`·`data/monthly/<KEY>.json`·`data/period_scorecard.json`·`data/history/*.jsonl`. 산출은 `monthly_<KEY>.html`.

**작성자 모델(2026-10-27)** — 작성자(`period-report-writer`)를 부르는 모든 Agent 호출 — 첫 작성, 게이트·조립 실패로 되돌려 고치기, general-purpose 폴백 — 에 `model: "opus"` 를 적는다. 에이전트 머리말에도 같은 값이 있지만 폴백에서는 머리말이 빠진다. 수집 담당 등 다른 서브에이전트는 모델을 적지 않는다(본체 모델 상속). **본체가 직접 쓰거나 고치는 모든 단계는 이 루틴의 모델이 Opus 일 때만 한다** — Agent 도구가 없을 때의 폴백, 작성자 타입이 없을 때의 직접 작성, 「같은 위반 두 번 → 오케스트레이터가 직접 고친다」. 본체가 Opus 가 아니면: 작성자 타입이 없으면 general-purpose 를 `model: "opus"` 로 부르고, 직접 고치는 대신 작성자를 `model: "opus"` 로 한 번 더 부르며, Agent 도구가 없거나 그래도 남으면 잠금을 풀고 중단을 보고한다 — 이 중단은 「중단은 completeness 실패뿐」의 예외다. 설계: `docs/superpowers/specs/2026-10-27-model-routing.md`.

**위임한 것은 다시 읽지 않는다.** 서브에이전트는 **동기**(`run_in_background: false`)로 부르고, 기다리는 동안 아무것도 열지 않는다. 에이전트 정의 파일(`.claude/agents/*.md`), 그 에이전트가 읽을 데이터 파일, 직전 발행본은 오케스트레이터가 읽지 않는다 — **경로만 넘기고**, 돌아온 산출물과 게이트 출력만 본다. 폴백으로 general-purpose 에이전트를 쓸 때도 정의 파일 본문을 붙여 넣지 말고 「이 파일을 먼저 Read 하라」고 경로를 준다. (2026-09-22 KR 실행이 에이전트를 백그라운드로 띄워 두고 지시문 35 KB·데이터 12개·직전 발행본을 다시 읽다가 5시간 한도로 죽었다.)

**발행 게이트:**

```bash
python3 scripts/check_period.py --html monthly_<KEY>.html --agg data/monthly/<KEY>.json \
  --recap recap_us.json --scorecard data/period_scorecard.json --span monthly --research-root research/us --research-as-of <AS_OF> --market us
```

위반이 나오면 **목록을 그대로 writer에게 돌려주고 다시 돌린다.** 게이트를 우회하지 않는다.

이어서 조판·문체 게이트를 일간과 동일하게 돌린다.

```bash
python3 scripts/apply_readability.py $(pwd)/monthly_<KEY>.html
python3 scripts/check_readability.py --strict $(pwd)/monthly_<KEY>.html
python3 scripts/check_style.py $(pwd)/monthly_<KEY>.html
```

**`check_weight.py`는 돌리지 않는다.** 그 게이트는 일간의 섹션 제목(「주식」·「채권」·「매크로」)을 검사하는데, 총정리는 5섹션 구조라 그 잣대가 맞지 않는다. 기간용 무게중심 판정은 아직 없다(2026-08-30 codex 검토에서 확인).

**STEP 4-b — 윤문은 루틴에서 하지 않는다 (2026-10-01).** 위 게이트를 통과한 판이 곧 최종본이다. Claude 윤문(humanize-korean)은 부르지 않는다. 발행 뒤 로컬 러너의 codex 문체 수정은 **2026-10-13 부터 수정안만 기록하고 공개판을 바꾸지 않는다**(`style_pass.APPLY`) — 문체는 작성 단계가 책임진다. 러너 동작은 `docs/superpowers/specs/2026-10-01-period-codex-style-pass.md`.

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
