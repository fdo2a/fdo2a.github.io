# STEP 2.6 — 문체 마감 (US·KR 일간 공통 절차)

**`python3 scripts/close_guard.py enabled` 가 `close: off`(exit 1)면 이 파일을 읽지 말고 STEP 2.6 을 건너뛴다.** 끄는 것은 `config/style_close.json` 의 `enabled` 하나다. 번역투 점검(STEP 2.5)은 켜고 끄는 것과 상관없이 그대로 돈다.

자리: STEP 2 게이트·STEP 2.5 를 다 지난 뒤, KR STEP 2.9(원장 승계)·STEP 3(발행) 앞. 설계 근거: `docs/superpowers/specs/2026-11-06-style-close.md`. 위협 모델은 비적대적(사고 방지)이다.

**이 절차의 모든 `$G verify`·`$G staged-scan`·`$G leak-compare` 는 exit 0 만 성공이다** — 1(불일치·발견)도 2(검증 불가: 파일 없음·깨진 JSON·`git show` 실패)도 실패로 다룬다.

변수: `H` = 발행할 html(워크스페이스의 `morning_brief_[DATE].html` / `kr_brief_[DATE].html`), `M` = `us`|`kr`, `D` = 보고 날짜, `KEY` = 잠금 키 파일의 값, `G="python3 scripts/close_guard.py"`. 명령은 레포 클론 루트에서 돈다.

## A. 마감 (STEP 3 전)

1. `bash scripts/ci/run_lock.sh renew "$KEY"` — exit 3 이면 잠금을 잃었다. 커밋하지 않고 끝낸다.
2. `export CLOSE_DIR=$(mktemp -d /tmp/close.XXXXXX)` → `$G snapshot --repo . --out $CLOSE_DIR/tree_before.json`
3. `cp "$H" $CLOSE_DIR/pre.html` → `shasum -a 256 "$H" $CLOSE_DIR/pre.html`. 두 값이 다르거나 크기 0 이면 **발행 중단**. 같으면 그 값을 `PRE_SHA` 로 **이 대화에 적어 둔다**(파일에만 두지 않는다).
4. `python3 scripts/scan_translationese.py --flow $CLOSE_DIR/pre.html --out $CLOSE_DIR/candidates.json --market $M --date $D` — exit 2 이거나 `flow: candidates 0` 이면 → **Z(편집 0)** 로. 아니면 `shasum -a 256 $CLOSE_DIR/candidates.json` 을 `CAND_SHA` 로 적는다.
5. `$G writer-prompt $CLOSE_DIR/candidates.json --out $CLOSE_DIR/writer_input.txt` → `cat` 한 내용 **그대로**를 프롬프트로 작성자(같은 `brief-report-writer`/`kr-report-writer`, `model: "opus"`, 동기)를 부른다. 파일 경로는 주지 않는다. 답의 JSON 을 heredoc 으로 `$CLOSE_DIR/edits.json` 에 쓴다. 작성자가 실패·한도·JSON 아님 → **Z**.
6. `shasum -a 256 $CLOSE_DIR/pre.html $CLOSE_DIR/candidates.json` 이 `PRE_SHA`·`CAND_SHA` 와 같은지 본다. pre 가 다르면 **발행 중단**, candidates 만 다르면 **Z**.
7. `$G check $CLOSE_DIR/pre.html $CLOSE_DIR/candidates.json $CLOSE_DIR/edits.json --out $CLOSE_DIR/pairs.json --market $M --date $D --expect-pre $PRE_SHA --expect-cand $CAND_SHA` — exit 3 → 발행 중단, exit 2 또는 `bundles 0` → **Z**.
8. `cat $CLOSE_DIR/checker_input.txt` 내용 그대로로 `close-meaning-checker`(`model: "opus"`, 동기)를 부른다. 답 JSON 을 `$CLOSE_DIR/verdicts.json` 에 쓴다. 실패·JSON 아님 → **Z**. 6 의 해시 확인을 다시 한다.
9. `$G apply $CLOSE_DIR/pre.html $CLOSE_DIR/candidates.json $CLOSE_DIR/edits.json $CLOSE_DIR/pairs.json $CLOSE_DIR/verdicts.json --out $CLOSE_DIR/approved.html --audit $CLOSE_DIR/audit.json --market $M --date $D --expect-pre $PRE_SHA --expect-cand $CAND_SHA` 의 마지막 줄:
   - `close: recheck exclude=C03,…` → 7 을 `--exclude C03,… --out $CLOSE_DIR/pairs2.json` 으로, 8 을 `verdicts2.json` 으로 한 번 더, 9 를 `pairs2.json verdicts2.json --round 2 --exclude C03,…` 로. **검사자 호출은 글당 최대 2회.**
   - `close: applied N` / `close: zero (…)` → approved.html 이 있다. exit 3 → `cp $CLOSE_DIR/pre.html "$H"` 후 sha256 이 `PRE_SHA` 인지 확인, 같으면 **Z** 로 진행, 아니면 발행 중단.
10. `cp $CLOSE_DIR/approved.html "$H"` → sha256 이 approved.html 과 같은지 확인.
11. **필수 게이트 전체를 다시** — STEP 2 의 발행 게이트와 가독성·문체 체인(apply_readability → US apply_colors → 파이프라인 게이트 → check_readability --strict → check_style, KR 은 `check_kr_stance.py --next` 포함). 쓰기 단계 뒤 `shasum -a 256 "$H"` 가 approved.html 과 같아야 한다(멱등). 하나라도 실패하거나 바뀌면 `cp $CLOSE_DIR/pre.html "$H"` → `$G note --audit $CLOSE_DIR/audit.json outcome=gate_restored` → 게이트 전체 다시 → `shasum -a 256 "$H"` 가 `PRE_SHA` 와 같은지 확인(다르면 발행 중단 — 쓰기 단계가 통과 판을 바꿨다) → `cp "$H" $CLOSE_DIR/approved.html`. **게이트가 그래도 실패하면 발행 중단**(잠금 release + PushNotification) — pre 는 이미 통과한 판이라 환경 이상이다. 수리 루프(재작성)는 하지 않는다.
12. `$G snapshot --repo . --out $CLOSE_DIR/tree_after.json` → `$G leak-compare $CLOSE_DIR/tree_before.json $CLOSE_DIR/tree_after.json` 이 exit 1 이면 **아무것도 지우거나 되돌리지 말고 발행 중단**(경로 목록만 PushNotification).
13. 감사 기록 ①: `fdo2a/report-close-edits` 를 `$CLOSE_DIR/audit-repo` 에 clone 해 `audit/$M/$D-<audit.json 의 uuid>.json` 으로 `audit.json` 을 커밋·푸시(같은 경로가 있으면 실패 — 덮어쓰지 않는다). 3회 실패하면 **롤아웃 첫 주에는** `cp $CLOSE_DIR/pre.html "$H"` → 11 의 게이트 전체 → `$G zero $CLOSE_DIR/pre.html --out $CLOSE_DIR/approved.html --audit $CLOSE_DIR/audit.json --outcome audit_upload_failed --market $M --date $D`. 롤아웃 뒤에는 발행을 막지 않는다.

**Z(편집 0)**: `$G zero $CLOSE_DIR/pre.html --out $CLOSE_DIR/approved.html --audit $CLOSE_DIR/audit.json --outcome <no_candidates|writer_failed|checker_failed|guard_input> --market $M --date $D --expect-pre $PRE_SHA` → `cp $CLOSE_DIR/approved.html "$H"` → sha256 이 `PRE_SHA` 인지 확인 → 12·13 은 똑같이 한다. 후보 0 처럼 `audit.json` 이 아직 없을 때도 이 명령이 만든다.

## B. 발행 (STEP 3 안에서 더하는 것)

- STEP 3 의 커밋 명령(`git add -A && git commit … && git push`)을 **나눠서 이 순서로** 한다: 에디터 노트(`apply_note`) → `git add -A` → `$G verify $CLOSE_DIR/approved.html posts/[DATE].html`(KR `kr/posts/[DATE].html`) → `$G staged-scan --repo . --audit $CLOSE_DIR/audit.json` → `git commit` → 아래 push 전 verify → `git push`. verify·staged-scan 이 exit 0 이 아니면 **발행 중단**(커밋하지 않는다, staged-scan 은 경로만 보고). 검사 뒤에 다시 `git add` 하지 않는다 — 했다면 두 검사를 다시 돈다.
- pull·rebase 뒤와 매 push 직전: `$G verify $CLOSE_DIR/approved.html --git HEAD:<글 경로>` — exit 0 이 아니면 push 하지 않고 중단. rebase 충돌을 풀며 `git add` 했으면 `staged-scan` 도 다시.
- push 성공 뒤: `git fetch -q origin main` → `$G verify $CLOSE_DIR/approved.html --git origin/main:<글 경로>`. exit 0 이 아니면 이미 공개됐으니 되돌리지 않고 `outcome=published_mismatch`(exit 2 는 `published_unverified`) 로 남기고 PushNotification — 그날은 평가 미완료.
- 감사 기록 ②: 같은 비공개 레포에 `audit/$M/$D-<uuid>.published.json` = `{"commit": <공개 커밋 SHA>, "blob": "$(git rev-parse origin/main:<글 경로>)", "verify": "ok|mismatch"}` 를 푸시(덮어쓰기 금지, 3회 재시도). 실패해도 발행은 그대로 — 최종 보고에 한 줄.
- 최종 보고: `문체 마감 — 후보 n · 작성자 편집 n · guard 기각 n · 검사자 기각 n · 반영 n · 게이트 복원 여부 · 감사 ①② 여부`.

`$CLOSE_DIR` 는 레포 밖이고 공개 레포에는 아무 흔적도 남기지 않는다(HTML 주석도 없다). guard·스캐너는 레포 안 출력 경로를 받으면 exit 2 다.
