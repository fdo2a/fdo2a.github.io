# 제목 줄바꿈 — readability v6 (2026-11-05)

## 사용자 규칙
1. 제목은 네모 칸에 최대한 한 줄로 쓴다.
2. 한 줄에 다 안 들어가 둘째 줄이 문장 중간에서 끊길 것 같으면, 그 문장을 둘째 줄 처음부터 쓴다.

## 원인
셸 `us.css` 와 readability-v5 가 1024px 이상에서 `h1 { max-width: 30em }`(750px)을 걸었고, 그 아래 리드는
카드 폭(약 1070px)을 다 썼다. 11/03 US 제목이 「…오르며 / 커브 가팔라져」로 갈렸다(8/26 부터 있던 상한).

## 구현
- `readability.py` v6: v5 와 바이트 같되 h1 데스크톱 상한을 `none`, `h1 tl-s { display: inline-block }`,
  `.headline-card h1 { text-wrap: wrap }`(11/04-05 셸이 실었던 balance 를 덮는다).
- `split_title_sentences()` 가 첫 실제 h1 의 문장(말줄임표, 한글 뒤·공백 앞 `.?!`)마다 `<tl-s>` 를 씌운다.
  inline-block 이라 남은 줄에 들어가는 문장은 이어 쓰고, 안 들어가면 통째로 다음 줄로 간다.
  `span` 이 아닌 사용자 정의 원소인 것은 발행본 CSS 의 span 규칙이 닿지 못하게 하려는 것이다.
- v5→v6 이주는 v5 블록 글자만 정확히 바꾼다(뒤따르는 signcolor 보존). 아카이브 196편 이주.
  `posts/2026-09-23.html` 은 블록 뒤에 자체 CSS 가 붙어 게이트가 설명하지 못해 제외했다.

## 검토 게이트
`prose.transformed()` 가 제목 변환을 재연한다. 변환이 실제로 일어난 판에서는 `_title_css_risky()` 가
`<tl-s>` 에 닿을 수 있는 CSS(전칭 주어·원소 이름·`:has` 등 인자, 허용 목록 밖 선언), 제목 자신의
flex/grid 배치, `::first-letter/line`, 모르는 stylesheet·외부 script, 셸 `_FOOT_JS`·ld+json 밖의 인라인
script, `on*=`, `noscript` 가 있으면 판정 불가로 보낸다. codex 다섯 차례 검토의 재현 입력이 전부
`scripts/review/tests/test_prose_title.py` 에 있다. 이것은 보안 경계가 아니라 사고 방지용 가드다.

교훈: `transformed()` 의 `except Exception` 은 예외를 판정 불가로 삼킨다. 게이트는 `scripts/` 만 경로에
두므로 `scripts.` 접두 import 를 하는 모듈(post_shell)을 부르면 조용히 21편이 판정 불가가 됐다.
