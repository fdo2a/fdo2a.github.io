---
name: review-gate
description: 발행 후 codex 미검토 발행본을 검토·정정하는 절차. 세션 시작 훅이 「codex 미검토 발행본 N건」을 알렸을 때, 또는 사용자가 검토 게이트·review_gate·미검토 발행본·발행본 검토를 언급할 때 사용한다. codex 는 읽기 전용으로만 돌리고, 지적 검증 → main 수정 → 게이트 재실행 → 원장 기록 → 커밋 순서를 따른다. 조판만 바뀐 건과 「판정 불가」 처리도 포함.
user-invocable: true
---

# 발행 후 codex 검토 게이트

세션 시작 훅이 「codex 미검토 발행본 N건」을 알리면 이 문서대로 한다.

**진행 여부를 묻지 않는다** (사용자 지시 2026-09-10). codex 가 지적하고 내가 근거
파일로 확인해 사실 오류로 판정한 것은 **정정·검사·`mark`·커밋·푸시까지 끝내고 결과만
보고한다.** 중간 승인 게이트는 없다. 다만 무관한 작업을 하러 연 세션이면 그 일을 먼저
하고, 검토는 그 뒤에 한다 — 훅은 알리기만 한다.

설계: `docs/superpowers/specs/2026-08-24-post-publish-review-gate-design.md`

## US·KR 무인 정정 (사용자 지시 2026-09-10)

**Claude 작성·최초 발행 → 로컬 러너의 Codex 읽기 전용 검토 → Claude 근거 검증·정정 → 검사·원장·커밋 → 러너 push** 순서다.
`python3 scripts/review_gate.py run --correct`가 기존 SHA 일치 초안과 새 초안을 모두 처리한다.
Claude 세션을 사람이 열 필요는 없다. launchd는 매시 실행하며 맥이 잠들면 깨어난 뒤 이어진다.
기본 `run`은 여전히 초안만 만든다. Codex와 Claude 호출 한도는 각각 US·KR 하루 2회다.

자동 정정의 Claude는 **원격 main의 임시 clone**에서만 작업한다. 사용자 작업 폴더는
pull하거나 수정하지 않는다. 아래 수동 절차의 main 수정·push 대신, Claude는 그 clone에서
검증·국소 정정·게이트·`mark`·커밋까지 하고 **Python 러너가 범위와 원장을 검증한 뒤 push**한다.
근거와 게이트 입력은 현재 날짜 데이터가 아니라 **대상 SHA의 발행 커밋 스냅샷**을 쓴다.
Codex 초안 존재만으로 완료 처리하지 않는다. 지적 없음도 Claude가 확인한 뒤 기록한다.

실패·시간 초과·원격 변경은 정정 완료가 아니다. 초안을 보존하고 다음 tick에서 한도 내
재시도한다. 이미 준비된 초안은 대기 중 날짜가 지나도 정정 대상에 남는다. `reviews/runner.json` 오류와 `reviews/pending/*.claude.txt`에 결과를 남긴다.
전체 수정 범위는 아래 3단계와 같다. 검증된 사실 오류만 정정하고 기각·보류 이유도 남긴다.
재게시 여부는 push 결과와 GitHub Pages 배포 상태를 구분해 보고한다.

## 대원칙 — codex는 읽기만 한다

**검토 경로에서 codex에 쓰기 권한을 주지 않는다.** `--write`를 붙이지 않으면
codex-companion이 `sandbox: "read-only"`로 실행해 프로세스가 물리적으로 파일을 못 고친다.
수정하는 손은 언제나 하나여야 코드가 안 엉킨다.

막힌 문제를 codex에 **위임**할 때만 예외이고, 그때는 워크트리로 폴더와 브랜치를 가른다
(맨 아래 「위임」 절).

## 1. 최신 상태로 맞춘다

```
cd site && git pull --rebase
python3 scripts/review_gate.py pending
```

루틴이 매일 커밋하므로 로컬은 거의 항상 뒤처져 있다. rebase 먼저. 게이트는 뒤처진
상태에서도 발행본을 보지만(`origin/main`과 작업 폴더를 둘 다 본다), 고치려면 최신 판이
손에 있어야 한다.

출력에 「지금 본 판이 최신이 아닐 수 있다」가 붙어 있으면 fetch가 실패한 것이다. 그때의
「미검토 없음」은 믿을 수 없다.

### 조판만 바뀐 것은 큐에 안 뜬다

`apply_readability.py`가 조판 사양을 고쳐 발행본 60여 편의 SHA를 한꺼번에 움직여도, 게이트는
**검토된 판을 조판 변환으로 밀어 새 판이 바이트 그대로 나오는지**를 보고 조용히 넘긴다.
통과하는 새 판은 하나뿐이라 그 사이에 다른 편집이 끼어들 수 없다. 아래에 「조판만 바뀐 N건」이
뜨면 원장을 정리한다.

```
python3 scripts/review_gate.py refresh              # dry-run — 무엇을 승인할지만 보여준다
python3 scripts/review_gate.py refresh --apply
```

`refresh`는 **「읽었다」고 기록하지 않는다.** `sha`·`at`·`findings`는 사람이 실제로 읽은 판을
가리킨 채로 두고 `accepted` 목록에 판을 하나 더한다. 신규 발행본과 「판정 불가」는 손대지 않는다.

**「판정 불가」는 「같다」가 아니다.** 셋 중 하나다 — ① 새 판의 조판 블록이
`scripts/review/known_blocks.py`에 등록되지 않았다 ② 마커가 없거나 둘 이상이다 ③ 기준이 될 옛
blob을 이 저장소에서 못 찾았다(force-push 뒤 gc, 얕은 클론). ①은 조판 도구가 새 CSS를 내기
시작했다는 뜻이므로 **그 블록을 눈으로 확인하고 등록**한다 — 자동으로 늘어나면 그 파일은
아무것도 막지 못한다. ③은 스스로 낫지 않으므로 그 글을 읽고 `mark`해서 끊는다.

**원장과 코드는 한 커밋으로 나간다.** 옛 코드는 `accepted`를 모르므로, 옛 판을 체크아웃하면
정리해 둔 51건이 다시 미검토로 뜬다. 손상은 아니고 소음이지만, 옛 판에서 `mark`를 돌리면 그
경로의 `accepted`가 지워진다.


## 2. codex에 읽기 전용 검토를 시킨다

### 먼저 초안이 있는지 본다

로컬 러너(`review_gate.py run`, launchd)가 us·kr 발행본의 초안을 미리 만들어 둔다.

```
ls reviews/pending/          # <날짜>-<섹션>-<sha7>.md
```

**파일명의 sha7이 현재 큐의 SHA와 같을 때만 그 초안을 쓴다** (`review_gate.py pending`
이 `경로 @ sha7 — 사유`로 판을 함께 낸다). 다르면 그 사이 글이
바뀐 것이므로 **버리고** 아래대로 직접 돌린다. us·kr 밖(thesis·weekly·monthly·china)은
언제나 직접 돌린다 — 러너가 읽지 않는다.

**초안은 검토 완료가 아니다.** codex가 읽었다는 것뿐이고, 3단계(지적 검증)를 건너뛰거나
초안이 있다는 이유로 `mark`하면 원장의 「읽었다」가 거짓이 된다. 원장은 **검증 담당 Claude가 근거와 함께 확인한**
판을 가리켜야 한다.

러너가 죽으면 초안이 안 늘어난다. 세션 시작 훅이 「미검토 N건 / 초안 준비됨 M건 / 러너
마지막 성공 …」을 한 줄로 내므로, 큐만 길어지는 것이 보이면 러너를 본다:
`launchctl list | grep fdo2a`, `~/Library/Logs/fdo2a-review-runner.log`.

### 초안이 없으면 직접 돌린다

한 번에 한 편. `/codex:rescue`로 아래 뼈대를 채워 보낸다. **읽기 전용임을 프롬프트에
명시**한다.

> 읽기 전용으로 검토만 해 줘. 파일을 고치지 말고 지적만 목록으로 돌려줘.
>
> 대상: `site/posts/2026-08-22.html` (한국어 미국 증시 모닝브리프 발행본)
> 근거 데이터: `site/data/market_data.json`, `site/data/econ_indicators.json`,
> `site/data/macro_metrics.json`, `site/data/stance.json`, `site/data/releases/*.txt`
>
> 세 가지만 본다.
> 1. **데이터 ↔ 본문 정합** — 본문의 수치·방향·날짜가 근거 데이터와 어긋나는 곳.
>    특히 지표의 증감을 좋다/나쁘다로 옮길 때 부호가 뒤집힌 곳(실업수당 청구 감소는
>    개선이다).
> 2. **논리 비약** — 근거가 지지하지 않는 단정, 앞뒤 절이 모순되는 곳.
> 3. **문장** — 한 문단에 주제가 둘 이상인 곳, 피동 종결 반복, 기계적 나열.
>
> 레이아웃·HTML·CSS는 보지 마. 별도 스크립트가 검사한다.
> 지적마다 «위치(§번호나 첫 문장) / 무엇이 틀렸나 / 무엇이 맞나(근거 파일과 값)»으로.

KR 브리프면 근거를 `site/kr/data/*`로, thesis 페이지면 `site/thesis/data/watch.json`과
`history.jsonl`로 바꾼다.

## 3. 지적을 검증한다

**근거는 그 글의 발행 커밋에서 꺼낸다.** 최신 `pull` 뒤의 작업 폴더 데이터를 열면 안 된다 —
`data/*.json`·`kr/data/*.json` 은 날짜별이 아니라 한 자리를 덮어쓰므로, 어제 본문을 오늘
데이터와 맞대면 **정상인 글이 사실 오류로 판정된다.** 러너는 이미 발행 커밋에서 읽으므로
사람 검증도 같은 판을 봐야 한다. 자동 정정에서는 이게 유일한 게이트라 여기서 틀리면
잘못된 정정이 그대로 나간다.

```
python3 - <<'EOF'
import sys, os; sys.path.insert(0, 'scripts')
import review_gate as g
root = os.getcwd()
path, sha = 'posts/2026-09-08.html', '<pending 이 찍은 40자리 sha>'
c = g.publish_commit(root, path, sha)
g.snapshot(root, c, (path, 'data'), '/tmp/snap')   # kr 이면 'kr/data'
print(c)
EOF
```

**본문 기준일과 근거 기준일이 다르면 그것은 정정 근거가 아니다.**

**codex 지적을 그대로 받아쓰지 않는다.** 근거 파일을 직접 열어 확인한 뒤 채택·기각을
가른다. **이 확인이 유일한 게이트다** — 승인을 받는 자리가 아니라, 둘(codex 의 지적과
근거 파일)이 같은 말을 하는지 내가 보는 자리다. 여기서 갈린 결과는 이렇게 처리한다.

| 판정 | 처리 |
|---|---|
| 사실 오류 (근거 파일이 본문과 어긋난다) | **바로 정정하고 끝까지 밀어 커밋·푸시** |
| 오인용 (codex 가 본문을 잘못 읽었다) | 고치지 않는다. 이유와 함께 **사후 보고** |
| 해석·문장 문제 (판단이 갈린다) | 고치지 않는다. **사후 보고** — 고칠지는 사용자가 정한다 |

사실 오류만 정정 대상이라는 규칙은 그대로다. 바뀐 것은 **정정 전에 묻지 않는다**는 것뿐이고,
기각분과 보류분은 마지막 보고에 반드시 함께 낸다.

## 4. main에서 고친다

채택한 지적만 `site/`에서 직접 수정한다. 발행본은 이미 공개된 글이므로 **정정 범위를
최소로** 한다. 문장을 다시 쓰고 싶은 충동은 기각한다.

## 5. 검사하고 기록한다

```
python3 scripts/verify_post.py posts/2026-08-22.html
python3 scripts/check_session.py --html posts/2026-08-22.html --datadir data --market us
python3 scripts/review_gate.py mark posts/2026-08-22.html --findings 3
```

KR 발행본이면 `--datadir kr/data --market kr`로 바꾼다.

**시황 게이트를 여기서 다시 도는 이유**: 루틴이 발행할 때 이미 한 번 돌지만, 그때는
그날 데이터로 돌았다. 여기서는 **커밋된 데이터와 공개된 글**을 맞대 본다 — 발행 후에
데이터가 다시 커밋됐거나(수집 재실행), 4단계에서 손으로 고치며 「오늘의 장」 문단의
수치·표식을 건드렸을 때 그것이 드러나는 자리다. 「오늘의 장」이 실린 첫 발행본은
이 검사를 반드시 통과시킨 뒤 `mark`한다.

`verify_post.py`가 「수치가 움직였다」고 잡는 것은 **정상이다.** 틀린 숫자를 고쳤으니
움직이는 게 맞다. 출력에 나온 사라진 값·생긴 값이 의도한 정정과 일치하는지 눈으로
대조하고 넘어간다. 의도하지 않은 값이 섞여 있으면 거기서 멈춘다.

`mark`가 원장에 남기는 SHA는 **정정 후** 내용이다. codex가 읽은 것은 정정 전 판이므로
**정정하면서 새로 넣은 오류는 아무도 다시 안 본다.** 그래서 4단계의 「최소 범위」가
규칙이고, 반영한 지적은 하나씩 눈으로 확인한 뒤 넘어간다.

## 6. 커밋·푸시한다

```
git add posts/<날짜>.html kr/posts/<날짜>.html reviews/index.json
git diff --cached --stat        # 이 목록이 정정 범위와 같은지 눈으로 본다
git commit && git push
```

**`git add -A` 를 쓰지 않는다.** 승인 게이트가 없어졌으므로, 앞선 무관한 작업의 변경이나
이미 staged 된 파일이 검토 없이 공개 레포로 나갈 수 있다. 정정한 발행본과 원장만 담는다.

**여기까지가 한 묶음이다.** 정정해 놓고 푸시를 미루면 공개된 글은 틀린 채로 남는다.

메시지 본문에 **무엇을 왜 고쳤는지** 남긴다. 지적 상세를 따로 파일로 남기지 않으므로
커밋 메시지가 유일한 기록이다.

지적이 0건이어도 `mark`는 한다. 「읽었고 문제가 없었다」와 「아직 안 읽었다」는 다르다.

---

## 위임 — 막힌 문제를 codex에 넘길 때

같은 문제에 2~3회 시도가 실패하면 넘긴다. 이때만 codex가 쓰기를 한다.

```
git worktree add .claude/worktrees/fix-<topic> -b fix/<topic>
```

`/codex:rescue`에 작업 폴더를 `site/.claude/worktrees/fix-<topic>`으로 지정하고 수정을
맡긴다. 브랜치가 갈려 있으므로 그동안 나는 main에서 다른 일을 해도 안전하고, 루틴이
main에 푸시해도 부딪히지 않는다.

끝나면 diff를 읽고 판단한 뒤 main으로 가져온다.

```
git -C .claude/worktrees/fix-<topic> log --oneline main..
git diff main..fix/<topic>
git merge fix/<topic>        # 또는 필요한 부분만 cherry-pick
git worktree remove .claude/worktrees/fix-<topic>
git branch -d fix/<topic>
```

`.claude/worktrees/`는 gitignore 대상이라 루틴의 `git add -A`에 딸려가지 않는다.
