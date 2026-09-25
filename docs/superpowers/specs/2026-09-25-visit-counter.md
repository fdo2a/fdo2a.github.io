# 방문 통계 — GoatCounter 로더 (2026-09-25)

## 요구

사용자: 「조회수나 방문횟수 등을 볼 수 있는 기능을 추가하자」. 결정 두 개는 사용자에게 받았다 —
**보는 사람은 운영자만(대시보드)**, **서비스는 GoatCounter**. 발행본 화면에는 아무것도 띄우지 않는다.

## 왜 외부 비콘인가

GitHub Pages 는 정적 파일만 내주고 접근 로그를 넘겨주지 않는다. 세는 방법은 페이지가 스스로 알리는 것뿐이다.
GoatCounter 는 쿠키가 없고 스크립트가 3.5 KB 이며, `localhost`·`file://` 페이지는 스크립트가 스스로 건너뛴다
(Playwright 실측: `file://` 로 연 발행본은 `count.js` 만 받고 `/count` 요청을 보내지 않는다).
대시보드: https://fdo2a.goatcounter.com

## 결정

- **규칙 하나**: `scripts/common/analytics.py` — `inject()` 는 첫 `</head>` 바로 앞에 `SNIPPET` 을 넣는다.
  `<head>` 래퍼가 없는 2026-07 초기 글 셋은 광고 로더 바로 뒤. 둘 다 없으면(조각) 손대지 않는다. 멱등(표식
  `<!-- goatcounter -->`).
- **넣는 자리 셋**:
  - `post_shell.render` (US·KR 일간) 와 `build_thesis_pages.py` 는 head 를 직접 쓰므로 같은 자리에 `SNIPPET`
    을 둔다 — 그 결과에 `inject()` 를 걸면 바뀌지 않는다(테스트).
  - `apply_readability.py` CLI — 주간·월간·중국 작성자는 문서 전체를 손으로 쓴다. 모든 발행 흐름이 이 단계를
    지나므로 여기서 넣으면 빠뜨림이 없다. `enhance_html()` 안이 아니라 **뒤에** 둔다 — 검토 게이트는 조판
    변환을 `enhance_html` 순서대로 재연하므로 둘을 섞으면 재연이 어긋난다.
- **소급**: `scripts/inject_analytics.py` (git 추적 방문자 페이지 104편). `--check` 는 빠진 페이지를 나열하고 exit 1.
- **검토 게이트**: 소급은 검토를 마친 판의 SHA 를 전부 움직인다. `review.prose.typography` 가 옛 판에 `inject()` 를
  **재연**해 새 판과 바이트가 같으면(또는 재연한 판을 옛 판 삼아 조판·자산 변환으로 설명되면) 조판으로 받는다.
  방향은 기존 원칙 그대로 — 새 판을 정규화하지 않는다. 로더를 다른 자리에 넣었거나 코드를 바꾼 판, 로더와 함께
  문장을 고친 판은 통과하지 못한다(`scripts/review/tests/test_typography_analytics.py`).
- **개인정보처리방침** §3 을 실제 수집 항목으로 고쳤다(쿠키 없음, 페이지 주소·유입 경로·브라우저·화면 크기·국가,
  IP 미저장 — GoatCounter 공식 문서 대조).

## 막는 것

- `scripts/common/tests/test_analytics.py::test_every_tracked_visitor_page_has_it` — git 이 추적하는 방문자 페이지가
  로더를 정확히 한 번 갖는지. 새 페이지 생성기가 빠뜨리면 여기서 걸린다. 고치는 법: 생성기에 `SNIPPET` 을 넣고
  `python3 scripts/inject_analytics.py`.
- 로더에는 숫자·보이는 글자가 없어 `verify_post.py` 의 수치·태그 대조가 움직이지 않는다(테스트).

## 운영

- 운영자 본인 방문 제외: 사이트에서 한 번 `https://fdo2a.github.io/#toggle-goatcounter` 를 열면 그 브라우저는
  세지 않는다.
- 사이트 코드를 바꾸려면 `analytics.CODE` 한 줄 + `inject_analytics.py` 는 **표식이 이미 있으면 건너뛰므로**
  발행본의 옛 코드를 바꾸지 못한다 — 그때는 치환 스크립트가 따로 필요하고, 검토 게이트 재연도 옛 코드로는
  맞지 않는다.

## 남은 것

- codex 설계·구현 검토 — 이 시점 codex 한도(9/26 22:34 초기화)라 Claude 가 대신 검토했다.
