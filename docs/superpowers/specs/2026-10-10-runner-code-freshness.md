# 러너 코드 신선도 가드 (2026-10-10)

## 왜
launchd 러너(`scripts/review_gate.py run --correct`)는 WorkingDirectory=site/ 의 코드를 그대로 import 한다. 2026-10-03 site/ 에 staged 로만 남은 미완성 작업(연방기금 선물 경로, 13파일)이 upstream 과 3파일 겹쳐 pull 이 막혔고, 러너는 10/10 까지 **81커밋 뒤(10/02 코드)**로 공개판을 고쳐 푸시했다. 그 코드의 문체 단계에는 `check_fund` 게이트와 `NEVER_TOLERATE` 가 없었다. 아무 경보도 없었다. (10/10 WIP 는 `wip/fed-path-2026-10-02` 로 옮기고 main 을 ff 했다.)

## 불변식
러너는 **origin/main 과 같은 코드로만** 공개판을 읽고 고친다.
- **뒤처지기만 했고 추적 파일이 하나도 안 바뀌었으면** fast-forward 하고 그 tick 은 쉰다(훅·autoStash·무시 파일 덮어쓰기 끔, 직전 브랜치 재확인). 이미 import 한 코드는 옛 판이라 새 코드로 도는 것은 다음 tick 이다 — 재실행(execv)은 하지 않는다.
- 그 밖에 다르면(다른 브랜치·분리 HEAD·앞선 커밋·코드 변경·scripts 미추적 파일·손댄 파일이 있는 뒤처짐) 그 tick 은 아무것도 하지 않고(codex·정정 모두) `errors['러너-코드']`(사람검토)를 남긴다. 훅이 그대로 보여 준다.

## 검사 지점 (`scripts/review/freshness.py`, stdlib 만)
| 지점 | 검사 |
|---|---|
| 프로세스 시작(레포 모듈 import 전) `boot()` | `run` 이면 HEAD 의 코드 tree 를 적는다 — import 와 첫 검사 사이 pull 을 잡는다 |
| tick 시작(fetch 뒤) `status()` | main 브랜치·`CODE_PATHS` 변경·scripts 미추적 없음, HEAD == origin/main 이면 OK, 뒤처지기만 했으면 BEHIND(→ `catch_up`). OK 면 `pin()` — 지금 HEAD 가 `BOOT` 와 다르면 그 tick 은 쉰다 |
| 문체 수정 clone 직후·rebase 뒤 `moved()` | clone 한 판의 `CODE_PATHS` tree == 고정 tree. 글·데이터만 바뀐 커밋은 통과 |
| 정정 clone 직후 `moved()` | 같다. 푸시 직전은 기존 「origin/main == base」 검사가 이미 막는다. 실패는 `DRIFT` 표지로 회차를 세지 않고 예약을 되돌린다 |
| 정정 게이트·절차 문서 | 사람 폴더가 아니라 검증한 base 의 `git archive` 사본에서 실행·읽기 — 검사 뒤 로컬 변조가 독립 검사에 못 닿는다 |
| 레포 모듈 import 실패 | `review_gate._import_failed` — 훅에 한 줄, tick 은 러너 잠금을 잡고 runner.json 에 경보(경합이면 건드리지 않는다). 스크립트로 실행되면 표준 모듈 import 전에 scripts/ 를 sys.path 에서 뺀다(옆의 json.py 가림) |
| 큐 조사 실패 | 훅이 「확인 실패」 뒤에 러너 상태를 그대로 붙인다 |

`CODE_PATHS = scripts, .claude/skills/review-gate, .claude/REVIEW_GATE.md` — 정정 프롬프트가 REVIEW_GATE.md 를 로컬에서 읽는다. STYLE_EXEMPLARS 는 origin/main 에서 직접 꺼내므로 빠진다. HUMANIZE_RULES 는 레포 밖이다.

경보는 **맞았음을 확인했을 때만** 지운다. fetch 실패 tick 은 경보를 유지한다. 멈춘 tick 은 `last_ok` 를 갱신하지 않는다(`progressed=False`, 반환 1).

## 자동 pull 의 범위
처음 설계는 「main·scripts 깨끗함·뒤처짐만이면 ff + 재실행」이었다. codex 설계 검토(10건)가 막았다:
- 공유 폴더에서는 확인과 ff 사이에 사람이 브랜치를 바꿀 수 있다 — 그러면 `merge --ff-only` 가 사람의 브랜치를 당긴다. RunnerLock 은 러너끼리만 막는다(#2).
- `merge.autoStash`·ignored 파일 덮어쓰기·post-merge 훅 — 「겹치면 git 이 거부한다」에 조건이 빠져 있다(#5).
- 재실행(os.execv) 계약은 실제 subprocess 로만 검증된다(#9).
그래서 한때 「멈추고 알리기만」으로 바꿨다. 그런데 그러면 다른 세션이 origin 에 코드를 푸시할 때마다(거의 매일) 누가 site/ 를 pull 할 때까지 러너가 선다. 절충: **추적 파일이 하나도 안 바뀐 main** 에서만 ff 하고(사람이 손대는 중이 아니다), 재실행 없이 다음 tick 에 맡긴다(#9 가 사라진다). #5 의 조건은 `-c core.hooksPath=/dev/null --no-autostash --no-overwrite-ignore` 로 막는다. #2 의 경합(브랜치 확인과 merge 사이의 브랜치 전환)은 직전 재확인으로 창을 줄일 뿐 없애지는 못한다 — 남은 위험으로 둔다.

## 남은 위험(수용)
- 브랜치 재확인과 merge 사이(수 ms)에 사람이 브랜치를 바꾸면 그 브랜치가 ff 될 수 있다.
- 무시 목록에 걸린 `scripts/` 아래 파일은 `git status` 에 안 보인다.
- 사람이 site/ 에서 자주 작업하면 러너가 그동안 멈춘다. 잦아지면 러너 전용 checkout 으로 옮긴다(훅·원장 경로 이동이 따라온다).
