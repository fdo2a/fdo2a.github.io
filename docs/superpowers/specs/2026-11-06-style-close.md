# 문체 마감 STEP 2.6 — 발행 전 독립 검사를 통과한 흐름 편집만 (C안 v4.6, 2026-11-06)

사용자 결정(2026-11-05) 「Design option C」 → 「Pre-publish independent check」 → 「비적대적 위협 모델」. 발행 뒤 codex 문체 수정안 507건 중 판단을 바꾼 것이 10건(2.0%)이었고, 그중 8건이 「연결어미로 먼저 잇기」「판정어로 고치기」 지시에서 나왔다. 그래서 문체 수정은 발행 **전에** 근거를 가진 쪽(Claude 작성자)이 하고, 의미가 같은지는 **다른 호출**(검사자)이 보고, codex 는 발행 뒤 **지적만** 한다. 설계 검토는 codex 8회(9→7→8→7→5→4→4→OK). 라운드별 판정표는 레포 밖 `plan.md` 「C안」 항목, 설계 원문은 레포 밖 `option-c-style-closing-design-v4-2026-11-05.md`(v4.1-v4.6 이 앞을 대체).

**기본은 꺼져 있다** — `config/style_close.json {"enabled": false}`. 켜는 조건은 아래 「오프라인 시험」의 세 문턱을 모두 넘고 사용자가 동의할 때다.

## 구성

| 조각 | 자리 | 계약 |
|---|---|---|
| 후보 | `scripts/close/flow.py`, `scan_translationese.py --flow` | `prose_swap._eligible` 문단 중 40자 미만 문장 2개 연속. 번역투 보호 구간·문단 안 보호 요소·판단 구역 Z·잠금 V/L/T 문장·따옴표(디코드 뒤 하나라도) 제외. 구간 = UTF-8 바이트 + inner sha1. 예외·잘못된 인자·레포 안 출력 = 종료 2 |
| 잠금 규칙 | `scripts/close/locks.py` | B안 Z·V·L·T·D·C. L 은 그날까지의 `research/<m>/ledger.jsonl` 가설 기록 |
| guard | `scripts/close/guard.py`, `scripts/close_guard.py` | 편집마다 `_check_one`·`_check_strict` + 관계 표지 Counter·D·C·V/L/T·생 `<` `>`·새 엔티티·새 따옴표. 통과 편집만 바이트 구간에 끼우고(뒤에서부터) 구간 밖 바이트·태그/속성 순서 단언 → 쓰기 단계(apply_readability, US apply_colors) → 본문 텍스트 불변 단언 → `proposed_sha256`. 인접 편집은 한 묶음, 문맥은 제안 판 기준 |
| 검사자 | `.claude/agents/close-meaning-checker.md` | opus, `tools:` 비움(로컬 CLI 2.1.314 에서 도구 0 확인, 클라우드 미확인). 기준 ⓪-⑦, `same` 만 반영, 모르면 기각. 검사 판 해시에 묶인다 |
| apply | `close_guard.py apply` | pairs.json 을 믿지 않고 pre·candidates·edits 로 다시 만든다. 해시 다름·모르는 id·깨진 응답 → 편집 0. 묶음 하나라도 same 아님 → 그 묶음을 빼고 재검사 1회, 그래도면 편집 0 |
| verify | `close_guard.py verify` | approved ↔ 대상: 같거나, approved 에 `apply_note` 노트 블록 하나만 더한 판. 작업 파일·HEAD blob·origin/main blob 세 곳 |
| 누출 | `scripts/close/leak.py` | 인덱스 항목 + 인덱스와 다른 추적 파일의 **작업 트리 바이트 sha256** + 미추적 sha256 을 STEP 2.6 전후 비교(이미 수정된 바이너리의 재변경도 잡는다 — 최종 검토 minor). 커밋 직전 staged 더해진 줄에서 감사 지문 검색 |
| 작성자 지시 | `STYLE_EXEMPLARS.md` §13 + 작성자 파일 한 문단 | 원문이 말한 관계만 잇는다, 지시어를 명사로 바꾸지 않는다, 나아지지 않으면 그대로. §13 은 실행 때 `writer-prompt` 가 뽑아 프롬프트에 넣는다(복제 없음) |
| 절차 | `.claude/STYLE_CLOSE.md`, 두 오케스트레이터 STEP 2.6 | 꺼져 있으면 읽지 않는다. 감사 기록은 비공개 `fdo2a/report-close-edits` 에만 |
| 발행 뒤 | `review_gate.STYLE_REWRITE=False` | codex 는 읽기 전용, 문체 지적 최대 5건 → `reviews/style_findings/`(git 제외), `style_log` 새 행 {ts, path, sha, findings, by_kind}, 주간 `scripts/review/style_digest.py`. 옛 고쳐 쓰기 코드는 남긴다 |

## 위협 모델과 남는 위험

막는 것: 사고 — 중간 파일·마감 전 문장·감사 기록이 공개 레포에 들어가는 것, 마감 편집이 사실·주장·귀속·판단을 바꾸는 것, 검증이 실패했는데 수정 문장이 발행되는 것. 막는다고 하지 않는 것: 서브에이전트의 **의도적** 우회, 외부 자료를 통한 프롬프트 인젝션. 검사자도 Claude 라 작성자와 오류가 겹칠 수 있다 — 크기는 오프라인 시험이 잰다. **「guard·검사자를 통과했다」는 「의미가 같다」의 보증이 아니다.**

## 오프라인 시험 (`scripts/close/offline_trial.py`, 로컬 전용)

성공 = 셋 다: 비용(루틴 하루 토큰 +15% 이하), 의미(사람 선분류 기준 반영 편집의 의미 변경 0), 가독성(반영 편집 눈가림 3택 「확실히 낫다」 ≥ 60%, 「원문이 낫다」 ≤ 10%, 「차이 없음」+「원문이 낫다」 > 40% 면 실패). 하나라도 못 미치면 꺼 둔 채 번역투 점검만 유지한다. 결과 숫자는 레포 밖 시험 보고서와 `plan.md` 에 둔다(마감 전 문장이 들어 있어 공개 레포에 넣지 않는다).

이 설계를 바꿀 때: 이 파일과 `scripts/close/tests/` 를 먼저 읽는다.
