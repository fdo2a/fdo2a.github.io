# 발행 전 검사 — 검토를 끝내지 못한 글은 세운다 (US 일간, 2026-11-22)

## 지시
- 11/20 사용자: 「글을 먼저 내보내고 나중에 틀린 데를 찾아 고치면 안되고 발행 전에 제대로 검사하고 다 끝난 다음에 올려야지」, 「실패하면 세워 두기」.
- 11/21-22: 모든 알림 텔레그램, 한도가 풀리면 바로 재시작, 모든 보고서로 넓힘 — 이 문서는 그 첫 묶음(「막기 최소 묶음 M」)만 다룬다. 전체 설계·codex 설계 검토 3회(상한)·남은 지적: 로컬 `plans/attachments/2026-11-17-prepub-all/us_interim_hold_design_v1.md` §10-11, 일 기록 `plans/2026-11-17-발행-전-검토를-모든-글에-한-번-제대로.md`.

## 무엇이 바뀌었나
1. **발행하는 길은 하나**: 검토 도착 → 정확성 지적 전부 판정·반영·게이트 재통과 → `prepub_review.py facts-done` → `record`(표시가 없으면 exit 10, 기록을 쓰지 않는다). 그 밖의 모든 실패는 `PREPUB_REVIEW.md` §5 로 세운다. 원래 판으로 되돌려 발행하는 길은 지웠다(`test_hold_docs.py` 가 지킨다).
2. **세우기(`prepub_review.py hold`)**: 닫힌 칸만 든 보류 기록(섹션·날짜·요청 id·상태·우리가 만든 이유·`hold`·시각)을 커밋하고, 잠금을 어떻게 놓을지 알린다.
   - 검토가 아예 돌지 않음(`NOT_RUN` — 제출 실패·한도·마감·결과 못 읽음·`stale_html`·`mark_failed`) → `release`. 받아들인 것이 없으니 재시도가 처음부터 써도 잃는 것이 없다.
   - 판정을 시작함(`recovery_needed`·`style_abort`·`facts_unmarked`, 모르는 값) → `run_lock.sh hold`. 재료(제출 판·검토 답·고치던 판)는 비공개 `review-runner` 의 `holds` 가지에만.
3. **판정 중 표시는 잠금 ref 에**: `facts.md` 를 읽기 전에 `run_lock.sh renew <키> judging`(수정 전 `fixing`). 표시는 뒤의 renew 가 이어 달고, 브리프 push 직후 `renew … clear` 로 뗀다. 세션이 판정·수정 중에 죽으면 stale 이어도 acquire 가 exit 6 — 재시도가 처음부터 다시 쓰지 않는다. `held`·죽은 표시는 `routine_due.py` 가 `HOLD`(재시도 관문은 쏘지 않는다). 사람만 `run_lock.sh unhold`.
   - 왜 main 의 기록 파일이 아니라 잠금 ref 인가: 런 중간에 main 에 push 하면 발행 커밋의 `git add -A`·`pull --rebase` 와 같은 경로에서 부딪친다. 잠금 ref 는 이미 런마다 쓰는 자리이고, acquire·routine_due 가 이미 읽는다.
   - 판정 표시는 첫 글(브리프)이 없을 때만 HOLD 로 읽는다 — 브리프가 나간 뒤 남은 표시가 뉴스 이어 쓰기를 막지 않게.
4. **초안은 비공개로**: `submit.py` 가 공개 `review-drafts` 대신 비공개 `review-runner` 의 `drafts` 가지에 Git Data API(`gh api`)로 올린다. 막기 모드에서는 세운 초안이 공개 가지에 남아 「검토 안 된 판의 공개」가 되기 때문이다. 비공개 워크플로는 자기 레포에서 먼저 읽고, 11/22 전 제출분만 공개 가지에서 읽는다.

5. **codex 구현 검토 1회차(IMPL NO) 반영**:
   - 보류 기록 push 는 `hold --push` 가 origin/main 위에 **그 파일 하나만** 바뀐 커밋을 따로 짓는다 — 문체 마감 B 의 `git add -A` 나 이미 만든 발행 커밋이 섞이지 않는다(시험: 스테이징·로컬 커밋 뒤 push 한 나무 = 원래 + 기록).
   - `record --html posts/D.html` 은 올릴 파일이 `facts-done` 판이나 봉인한 판(`seal --why style|note` — guard 를 지난 문체 편집·에디터 노트)과 바이트가 같을 때만 받는다. 작성자가 다시 쓴 판은 루틴이 받아들인 지적을 다시 대조하고 `facts-done` 을 다시 찍어야 한다(앞 봉인은 무효).
   - 판정 표시가 달린 클론의 `release` 는 풀지 않고 `held … reason=recovery_needed` 로 바꾼다 — 지시문의 어느 중단 경로가 release 를 불러도 재시도가 처음부터 쓰지 않는다.
   - 브리프 push 와 `clear` 사이에 죽은 흔적은 `acquire … brief-out`(부른 쪽이 origin/main 의 브리프를 확인) 으로만 넘겨받는다. 세움(`held`)은 그래도 열리지 않는다.

6. **codex 구현 검토 2회차(IMPL NO) 반영**:
   - (2·3회차 #1) 판정 표시를 로컬 파일에 따로 적지 않는다. `renew`·`release` 는 **lease 를 거는 바로 그 잠금 커밋(소유 SHA)의 제목**에서 표시를 읽는다 — push 는 원격 끝이 그 커밋일 때만 통과하므로, 통과한 새 커밋의 표시는 언제나 직전 원격 커밋의 표시에서 나온다. 같은 클론의 renew 가 겹쳐도 파일과 원격이 어긋날 자리가 없다(2회차는 「성공 뒤 표시 기록」의 틈, 3회차는 그 틈을 막느라 넣은 「실패 뒤 표시 되돌리기」의 틈을 짚었다 — 두 번 같은 갈래라 파일을 없앴다). 소유 SHA 가 가리키는 커밋을 못 읽으면 renew 는 exit 3, release 는 exit 4(잠금을 움직이지 않는다).
   - `record` 의 공개 인용(`style_findings`·`clarity`)은 제출 초안이 아니라 **`--html` 로 받은 올릴 판**(해시를 잰 바로 그 바이트)과 대조한다 — 고치면서 지운 글자는 빈 인용이 된다. 따라 오는 것: 반영된 문체 수정의 인용은 늘 비고, 주간 묶음(`style_digest`)은 빈 인용을 「인용이 빈 지적 N건」·잔존 「알 수 없음」으로 읽는다(분류 집계는 그대로).
   - STEP 0 의 exit 6 갈래는 설정하지 않은 `KEY` 대신 `/tmp/us-lock-key` 에서 날짜를 읽는다(`cut -d- -f2-`). 같은 파일의 국채 종가 대기 줄에 남아 있던 `renew "$KEY"`(이 변경 전부터 있던 것)도 같은 꼴로 고쳤다.
   - 발행 전 검토의 문체 후보가 0 인 날 STEP 2.6(기본 꺼짐)이 켜져 글을 고치면 ORCHESTRATOR STEP 2.6 이 그 판을 `seal --why style` 로 봉인한다 — 없으면 `record` 가 exit 10 으로 멀쩡한 글을 세운다. KR 은 `PREPUB_DIR` 이 없어 공용 `STYLE_CLOSE.md` 가 아니라 US 지시문에 둔다.

## 남는 것(이 묶음 밖)
즉시 텔레그램(지금은 폰 알림 + 12:10 KST `missing`), 한도 풀리면 15분 안 재시작, 옛 세션 이어 내기, 독립 감시, 다른 보고서. 사람이 재료로 잇는 절차는 아직 손이다.
- 첫 실제 실행에서 확인할 것: 루틴의 `gh api` 가 비공개 레포에 blob·ref 를 쓸 수 있는지(11/19 P 시험은 git push 로 확인), 비공개 워크플로가 새 자리에서 읽는지.
