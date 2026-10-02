# 주간·월간·일본도 발행 뒤 codex 문체 수정 (2026-10-01)

## 지시

사용자: 「주간, 월간, 일본 보고서도 codex가 검토하도록 해」. 일간(2026-09-27 설계
`2026-09-27-post-publish-codex-style-pass.md`, 9/30 가동)과 같은 경로를 넓힌다. 루틴의 Claude 윤문
(주간·월간 STEP 4-b, 일본 STEP 3)은 뺀다.

## 종류 표 — `scripts/review/kinds.py`

| 섹션 | 시장·주기 | 발행일(키에서) | 신선도 | 근거(발행 커밋) |
|---|---|---|---|---|
| `weekly` | us·weekly | 그 주 토요일 | 3일 | `data/weekly/KEY.json`, `data/weekly_ext/KEY.insight.json`, `recap_us.json`, `data/period_scorecard.json` |
| `kr/weekly` | kr·weekly | 토요일 | 3일 | `kr/data/weekly/KEY.json`, `recap_kr.json`, `data/period_scorecard.json` |
| `monthly`·`kr/monthly` | ·monthly | 다음 달 1일 | 7일 | `…/monthly/KEY.json`, recap, 스코어카드 |
| `japan/posts` | jp·weekly | 일요일 | 3일 | `japan/data/KEY.json`, `KEY.news.json` |

섹션마다 하루 2회(DAILY_CAP). 키 형식이 아닌 기간 페이지는 자동 대상이 아니다.

## 게이트

`check_style`, `check_readability --strict`, `verify_post --before 원본`, 그리고
- 기간: `check_period --agg/--recap/--scorecard`(발행 커밋 근거) `--span --market --research-frozen 원본`
  (+US 주간 `--insight`).
- 일본: `check_japan --key --datadir <근거>/japan/data`.

**연구 요약**: as-of 가 발행본에 남지 않아 다시 렌더할 수 없다. `--research-frozen` 은 요약 블록이 원본과
바이트까지 같은지만 보고 떼어낸 뒤 나머지 검사를 전부 돈다. 이 옵션 없이는 요약 오류에서 바로 돌아가
수치 창작 검사까지 건너뛰었고, 「원본과 같은 실패」 허용이 게이트 전체를 껐다(설계 검토 2, 재현).
`prose_swap.extract` 는 중첩된 요약 section 도 뺀다(설계 검토 1, KR W39 에서 요약 문단이 넘어갔다).

**근거가 하나라도 없으면 반영하지 않는다.** 게이트가 원본·수정본 모두 같은 FATAL 로 죽으면 동일 실패로
봐줘서 꺼진 채 통과한다.

## 범위 밖

- **사실 정정(Claude 자동)은 일간만**이다(`corrector` 가 `(kr/)?posts/DATE.html` 만 받는다). 기간·일본
  초안은 `reviews/pending/<발행일>-<섹션>-<sha7>.md` 로 남고 수동 review-gate 로 처리한다.
- 일본은 아직 발행본이 없어 실제 글로는 확인하지 못했다.

## codex 설계 검토 (2026-10-01) — DESIGN OK AFTER CHANGES

1. 중첩 연구 요약 누출 → 수용(Elements 균형 매칭).
2. as-of 없는 check_period 가 원본부터 실패 → 부분 수용: as-of 보존 대신 `--research-frozen`.
3. 일본은 일요일 발행 → 수용.
4. 월간 1일은 확정 발행일이 아니다 → 부분 수용: 커밋 시각 대신 신선도 7일(`eligible` 은 git 없는 순수 함수).
5. `_correct_ready` 가 기간 초안을 받게 된다 → 수용: 일간만.
