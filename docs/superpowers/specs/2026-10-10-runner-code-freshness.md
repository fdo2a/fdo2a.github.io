# 러너 코드 신선도 — origin/main 사본으로 돈다 (2026-10-10)

## 왜
launchd 러너(`review_gate.py run --correct`, WorkingDirectory=site/)는 site/ 의 코드를 그대로 import 했다. 2026-10-03 site/ 에 staged 로만 남은 미완성 작업(연방기금 선물 경로, 13파일)이 upstream 과 3파일 겹쳐 pull 이 막혔고, 러너는 10/10 까지 **81커밋 뒤(10/02 코드)**로 공개판을 고쳐 푸시했다. 그 코드의 문체 단계에는 `check_fund` 게이트와 `NEVER_TOLERATE` 가 없었다. 경보는 없었다. (10/10 WIP 는 `wip/fed-path-2026-10-02` 로 옮기고 main 을 ff 했다.)

## 불변식
러너는 **origin/main 과 같은 코드로만** 공개판을 읽고 고친다. 사람의 폴더는 읽지도 움직이지도 않는다.

## 구조
| 자리 | 하는 일 |
|---|---|
| `scripts/runner_launch.py` (launchd 가 부른다, **stdlib 만**) | fetch → origin/main 커밋 트리 전체를 **그 tick 전용 임시 폴더(0700)**에 `git archive` 로 풀고 → 그 사본의 `review_gate.py` 를 cwd=site/, `REVIEW_RUNNER_CODE=<oid>` 로 자식 프로세스 실행 → 끝나면 사본 삭제. 실패하면 러너 잠금을 잡고 `errors['러너-코드']` 경보. 여러 tick 이 나눠 쓰는 캐시는 두지 않는다(변조·반쯤 만든 사본·쓰는 중 삭제, codex 3차 #1-#3). 레포 모듈을 import 하지 않는다(3차 #4) |
| `review_gate.cmd_run` | 자동 tick(`--correct` 또는 사본)은 공개판 원장의 큐만 본다 — 사람 폴더의 편집 중인 원장을 조사하지 않는다(3차 #5). `REVIEW_RUNNER_CODE` 가 있으면 그 커밋의 코드 tree 를 기준으로 고정(`pin_code`). 없으면(손으로 site/ 에서 부를 때) site/ 가 main·HEAD == origin/main·코드 경로 변경 없음·scripts 미추적 없음, import 뒤 HEAD 불변(`boot`/`pin`)일 때만 돈다 — 아니면 경보 |
| 문체 수정 clone 직후·rebase 뒤, 정정 clone 직후 `freshness.moved()` | clone 한 판의 코드 tree 가 기준과 다르면 그 글을 멈춘다(tick 도중 origin 에 게이트 커밋). 정정의 이 실패(`DRIFT`)는 회차로 세지 않고 예약을 되돌린다 |
| 정정 게이트·절차 문서 | 검증한 base 의 `git archive` 사본에서 실행·읽기 |
| import 실패·큐 조사 실패 | 훅에 한 줄 / tick 은 러너 잠금을 잡고 runner.json 경보(`note_alarm`, 경합이면 건드리지 않는다). 스크립트로 실행되면 표준 모듈 import 전에 scripts/ 를 sys.path 에서 뺀다 |

`CODE_PATHS = scripts, .claude/skills/review-gate, .claude/REVIEW_GATE.md`. 경보는 맞았음을 확인했을 때만 지운다. 멈춘 tick 은 `last_ok` 를 갱신하지 않는다.

## 종료 처리
- 런처: 처리기는 **첫 신호를 기록하고 자식에게 넘기기만** 한다(예외를 던지지 않는다 — 던지면 임시 폴더 생성 직후·정리 진입·경보 기록 중 어디서든 흐름이 끊겼다, codex 5·6차). git 과 자식은 0.2초마다 끊어 기다리며 기록을 확인하고 스스로 멈춘다. 자식에게는 `GRACE`(20초)까지 정리 시간을 준 뒤 사본을 지운다. 신호를 받았으면 언제 왔든 128+N 으로 끝낸다.
- 러너(`review_gate run`): CLI 진입에서 SIGTERM 을 SystemExit 로 바꾼다(두 번째 신호는 무시) — 잠금·고정 해제가 돈다.
- 정정기 `_status`: 별도 세션으로 띄운 Claude·게이트는 부모와 함께 죽지 않으므로, 취소(SystemExit·Ctrl-C)에도 프로세스 그룹을 SIGKILL 하고 회수한다.
- plist `ExitTimeOut` 30(GRACE 20 보다 길게). SIGKILL·전원 차단에서는 임시 사본이 남는다 — 시스템 임시 폴더 정리에 맡긴다.

## launchd 전환 절차
1. 기존 job 을 먼저 내린다(`launchctl bootout gui/$UID/com.fdo2a.review-runner`) — 진행 중 tick·정정기 하위 프로세스가 끝났는지 `pgrep -f review_gate` 로 확인.
2. 검토된 커밋을 **origin/main** 에 반영(런처는 브랜치가 아니라 origin/main 을 고른다). site/ 는 fetch·ff 만, 실패해도 reset·clean 하지 않는다.
3. plist 백업 → ProgramArguments 의 스크립트를 `scripts/runner_launch.py` 로, `ExitTimeOut` 30 → `plutil -lint`.
4. `launchctl bootstrap` → `launchctl print` 로 **로드된 인자** 확인 → `launchctl kickstart` 로 첫 tick 을 돌려 사본 OID·경보·종료 코드·임시 폴더 정리를 확인.

## 거쳐 온 설계
1. **site/ 를 검사하고 뒤처지면 ff + 재실행** — codex 설계 검토(10건)가 막았다: 확인과 ff 사이 사람의 브랜치 전환(#2), autoStash·무시 파일·post-merge 훅(#5), execv 검증(#9).
2. **검사하고 다르면 멈추고 알리기만** — 다른 세션의 코드 푸시마다(거의 매일) 누가 pull 할 때까지 러너가 선다.
3. **추적 파일이 안 바뀐 main 이면 ff 하고 그 tick 은 쉰다** — codex 구현 재검토: 러너 본체를 읽은 뒤 boot 전 pull(#1), 정정기 지연 import 가 사람 폴더를 읽는다(#2), 데이터 커밋마다 한 tick 미룸(#7), 브랜치 전환 경합(#8). 공유 폴더를 검사하는 한 「읽는 순간」과 「검사하는 순간」 사이 틈은 줄어들 뿐 없어지지 않는다.
4. **지금: 코드는 origin/main 사본에서** (3차 검토 뒤 캐시를 tick 전용 임시 사본으로) — 틈이 생기는 자리(공유 폴더에서 코드를 읽는 것) 자체를 없앴다. site/ 동기화는 러너와 무관해졌다.

## 남은 위험(수용)
- 런처 파일 자체는 site/ 에서 읽는다. 런처가 낡아도 그것이 고르는 코드는 origin/main 이다. 런처를 바꾸면 site/ 를 pull 해야 반영된다.
- 사본은 tick 시작의 origin/main 이다. tick 도중 origin 에 게이트 커밋이 오르면 `moved()` 가 그 글을 멈추고 다음 tick 이 새 사본으로 한다.
- 손으로 site/ 에서 `run` 을 부르는 경로는 여전히 공유 폴더 검사(설계 3 의 틈)를 쓴다.
