# 발행 후 codex 검토 게이트

세션 시작 훅이 「codex 미검토 발행본 N건」을 알리면 이 문서대로 한다. 사용자에게 먼저
보고하고, 진행 여부를 확인한 뒤 시작한다 — 무관한 작업을 하러 연 세션까지 검토가
선행되면 안 된다.

설계: `docs/superpowers/specs/2026-08-24-post-publish-review-gate-design.md`

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

**codex 지적을 그대로 받아쓰지 않는다.** 근거 파일을 직접 열어 확인한 뒤 채택·기각을
가른다. 기각한 것도 사용자에게 이유와 함께 보고한다. 판단이 갈리는 해석 문제는 고치지
말고 사용자에게 넘긴다 — 사실 오류만 정정 대상이다.

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

## 6. 커밋한다

```
git add -A && git commit && git push
```

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
