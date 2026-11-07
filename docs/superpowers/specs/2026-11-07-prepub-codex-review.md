# 발행 전 codex 검토 — 비공개 레포 Actions + 구독 로그인 (2026-11-07)

## 사용자 결정

- 「발행 되기 직전에 codex 검토를 돌리고, 그 값을 보고 판단 및 수정까지 다 한 뒤 올리면 안되는거야?」
- 「문체 오류를 수정하는걸 메인으로 하고 싶은데」
- 「비공개 레포 Actions + 구독 로그인 방식으로 해보자」, 「검토 전 초안이 공개 레포의 기록에 남아도 괜찮아」

## 왜 이 구조인가

- 클라우드 루틴에는 codex 가 없다. 맥 codex 는 ChatGPT 구독 로그인(`auth.json`)으로 돈다. API 키는 별도 과금이라 쓰지 않는다.
- OpenAI CI/CD 인증 안내(<https://learn.chatgpt.com/docs/auth/ci-cd-auth.md>): 구독 로그인을 CI 에 넣는 것은
  「an advanced workflow for enterprise and other trusted private automation」, 「Do not use this workflow for public or
  open-source repositories」. 보고서 레포는 공개라 **검토는 비공개 레포 `fdo2a/review-runner` 에서** 돈다.
  비공개 레포가 공개 레포의 글을 읽는 것이 안내의 허용 범위인지는 우리가 확인할 수 없다 — 남은 정책 위험(사용자에게 고지).
- 맥 로그인 파일을 복사하지 않는다(여러 기기가 한 파일을 나눠 쓰면 안 된다). 클라우드 전용 기기 인증 로그인을 따로 만들었다.

## 흐름

1. 루틴(STEP 2.7, `.claude/PREPUB_REVIEW.md`)이 게이트를 지난 초안으로 묶음을 만든다 — `post.html`·`prompt.txt`·
   `manifest.json`(요청 ID·`data_commit`·파일 해시). 근거 데이터는 넣지 않는다 — 이미 main 에 커밋돼 있어 비공개 쪽이
   `data_commit` 에서 꺼낸다(발행 뒤 검토가 발행 커밋에서 꺼내는 것과 같다). 작업 폴더의 근거가 HEAD 와 다르면 묶지 않는다.
2. 묶음을 공개 레포 `review-drafts` 브랜치 `drafts/<요청 ID>/` 에 올린다(임시 인덱스로 커밋 — 작업 폴더를 건드리지 않는다).
   Pages 는 main 루트만 내보내므로 사이트에 뜨지 않는다.
3. 루틴이 비공개 레포 `prepub-review` 워크플로를 REST 로 띄운다. 루틴 세션은 설정에 넣은 레포에만 닿으므로 **공개 레포에
   dispatch 키를 두지 않는다**(실측 — 「sessions are bound to their configured repositories」). `gh workflow run` 은 루틴에서
   GraphQL 이 막혀 실패한다.
4. 워크플로: 입력 형식 검증 → 묶음·`data_commit` 을 데이터로만 꺼내 검토 폴더를 짓는다(공개 레포 코드는 실행하지 않는다) →
   고정한 codex(0.166.0, gpt-6.1-terra high)로 `--sandbox read-only` → 출력에서 로그인 토큰 문자열 제거 → **갱신된 로그인을
   결과보다 먼저 비밀값에 저장**(3회, 실패하면 `auth_saved: false`) → `results/<요청 ID>.json`. 동시 실행은 `codex-auth` 한 줄.
5. 루틴이 결과를 기다린다(9분씩 나눠, 마감 25분). **요청 ID·초안 커밋이 정확히 같을 때만** 받는다.
6. 판정·수정은 루틴이 한다 — 사실 오류와 근거 없는 원인·주체 단정은 정확성 오류로(근거 파일을 직접 열어), 문체 지적은
   STEP 2.6 의 안전장치(작성자 편집 → guard → 의미 검사자 → `same` 만 반영)로. 확신도 지적(「판단 세기 흐림」「원문에 없는
   관계」)은 문체 경로에 넣지 않는다 — 의미 검사자가 세기 변화를 `changed` 로 막는다.
7. 실패·한도·마감은 발행을 막지 않는다. `reviews/prepublish/<시장>/<날짜>.json` 에 남기고, 맥 러너가 발행 뒤에 본다
   (시범 동안은 검토된 글도 맥 러너가 다시 본다 — 원장 연결은 다음 단계).

## 실측(2026-11-07)

- 루틴 토큰은 프록시 토큰, 설정한 레포에만 닿는다. main 밖 브랜치 push·워크플로 파일 push·push 이벤트 기동 모두 됐다.
- 비공개 레포를 소스로 넣자 admin 으로 닿았고, REST 기동·결과 읽기가 됐다.
- 첫 시험 루틴은 지시문이 「push 하지 마라」와 기동을 함께 말해 자동 모드 분류기가 막았다 — 기동이 목적이라고 적는다.
- 첫 왕복(US 11/06): GitHub Ubuntu 러너가 bubblewrap 을 막아 codex 가 파일을 못 읽고도 exit 0 으로 「검토하지 못했다」고
  답했다 → 러너에서 `kernel.apparmor_restrict_unprivileged_userns=0` 으로 샌드박스만 연다(끄지 않는다), 출력에 `bwrap:` 이
  보이면 `sandbox_failed`.

## 문체에 무게 (사용자 「번역투나 문체수정에 더 무게를 두고 싶으면?」→「그렇게 진행해봐」)

첫 왕복에서 문체 지적 4건이 전부 판단 구역·판단 문장 문단이라 STEP 2.6 의 후보 제외에 걸려 반영 0 이었다.

- 판단 문단도 후보로 받는다. 판단 문장은 guard 의 `locks.locked` 비교가 글자 그대로 지킨다.
- 「번역투」만 판단 문장의 낱말까지 고친다 — `locks.judgment_skeleton`(판단 어휘·기간·원장 앵커·판단의 주인 표지의
  순서·개수)과 문장 수가 같아야 하고, 그 묶음은 의미 검사를 두 번 받아 둘 다 same 일 때만 실린다.
- 시험이 잡은 구멍: 주체 맞바꾸기(10/13 「언론은 … 우리는 …」), 판단 문장 쪼개기(판단 어휘 없는 단정문이 생긴다).
- 실제 글 시뮬레이션: 「굳어지는 신호」→「자리 잡았다는 신호」(진행→완료)는 guard 를 통과했지만 의미 검사 두 번이 모두
  `changed` 로 막았다 — 마지막 방어선이 모델이라는 점은 그대로다.
- 문체 지적 상한 5→8, 발행 전 지적도 주간 묶음(`style_digest.py`)에 들어간다.

## 다음 단계로 미룬 것

- KR·일본 일간(일본은 근거 폴더가 다르다), 원장 `prepublish` 연결(검토된 최종판을 맥 러너 중복 검토에서 빼기 — codex 설계 #3 조건).
- 로그인 갱신 유지용 주간 실행(8일 기준) — 매일 발행이 돌면 그 실행이 갱신한다.

When changing this: read this spec before touching `scripts/prepub/` or the private `fdo2a/review-runner` workflow.
