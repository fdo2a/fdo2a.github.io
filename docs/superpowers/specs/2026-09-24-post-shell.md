# 발행본 셸 — 작성자는 본문만 쓴다 (2026-09-24)

## 문제

일간 브리프(US·KR)는 작성 에이전트가 문서 전체를 손으로 썼다 — `<head>`, SEO 메타, JSON-LD, 애드센스
로더, 약 6 KB 의 CSS, 상단 바. 발행 단계(STEP 3)에서는 오케스트레이터가 nav 블록과 SEO 메타를 다시 손으로
주입했다. 대가는 셋이었다.

- **토큰**: US 작성 지시문 약 140줄이 CSS 명세였고(발행본마다 CSS 5.6~8.8 KB 를 출력 토큰으로 냈다),
  KR 작성자는 CSS 를 베끼려고 직전 발행본(35 KB)을 읽었다 — KR CSS 는 9/4 이후 바이트까지 같다.
- **결함**: 2026-09-23 US 발행본은 description·canonical·og 태그가 두 벌이었다(작성자 한 벌 + STEP 3 한 벌).
  어떤 게이트도 head 를 보지 않았다.
- **표류**: US CSS 는 20편에 선택자 125종, 최신 발행본에 없는 선택자 67종(`.topbar-inner`·`.topdate`·
  `.topbar .date` 가 번갈아 나왔다).

## 결정

- `scripts/common/post_shell.py`(순수) + CLI `scripts/render_post.py`. 입력은 둘이다 —
  `meta.json` `{"title", "summary"}` 과 `<div class="doc">` 안에 들어갈 본문 조각.
- 나머지는 유도한다: og:title 은 날짜에서(「미국 증시 모닝브리프 — YYYY년 M월 D일 (요일)」), meta description
  은 `<h1>` 에서(「[h1]. [DATE] 미국 증시 모닝브리프.」 — STEP 3 이 손으로 만들던 형식 그대로), canonical·og:url
  은 시장·날짜에서, JSON-LD 는 그 값들로, CSS 는 `scripts/common/post_css/<market>.css` 에서.
- CSS 템플릿: US 는 2026-09-23 발행본의 기본 블록 + 작성 지시문이 요구하던 컴포넌트 규칙(`.stance-tbl`,
  `.fed-quote`·`.fed-idea`). KR 은 2026-09-23 기본 블록 그대로. `apply_readability.py`·`apply_colors.py`
  가 표식을 달고 주입하는 블록은 템플릿에 넣지 않는다 — 지금처럼 그 스크립트들이 넣는다.
- 검증(`validate`): 본문에 `<html>/<head>/<body>/<!DOCTYPE>`·`<div class="doc">` 금지, `<h1>` 정확히 하나,
  본문 `<style>` 이 템플릿 선택자를 다시 정의하면 거부(섹터 막대처럼 데이터가 싣고 오는 위젯 스타일은 통과),
  SEO 제목 형식(「미국 증시 마감 시황 — … | DATE」 / 「코스피 마감 시황 — … | DATE」), summary 비어 있지 않음.
- STEP 3 의 nav·SEO 메타 수동 주입을 없앤다. 셸이 한 번만 넣는다.
- 렌더는 한 번이다. 이후 수정·윤문·게이트는 지금처럼 완성본 HTML 에서 한다.

## 검증

- `scripts/common/tests/test_post_shell.py` — 실제 2026-09-23 US·KR 발행본을 본문·메타로 쪼갰다가 다시
  렌더: head 태그가 각 한 번, JSON-LD 파싱·headline=og:title, 본문 불변, description 이 h1 에서 나옴.
  계약 위반 다섯 종, 위젯 스타일 허용, 제목 형식, JSON-LD 안의 `</script>` 무력화.
- 수동(2026-09-24): 재렌더 → `apply_readability`·`apply_colors` → `check_readability --strict`·`check_style`
  통과, `verify_post --before 원본` 은 head 태그 순서와 제거된 중복 태그 5개만 보고(수치 변화 없음).
  Playwright 390·1280px 에서 원본과 재렌더의 scrollWidth·scrollHeight 가 네 경우 모두 같다.

## 남은 것

- 주간·월간·China 작성자는 아직 문서 전체를 쓴다. 같은 셸로 옮길 수 있다.
- 새 컴포넌트가 필요하면 템플릿 CSS 에 규칙을 더하고 작성 지시문의 클래스 표에 한 줄 더한다.
- codex 설계·구현 검토 — 이 변경 시점에 codex 가 한도(9/26 22:34 초기화)라 Claude 가 대신 검토했다.

## 부록 — 대체된 작성 지시문 원문 (근거와 이력 보존)

셸 도입 전 `brief-report-writer.md` 의 HTML 절과 CSS 조각, KR 의 제목 규칙이다. 폭·글자 크기·줄간격·라벨·
모바일 규칙의 **이유와 사고 이력**이 여기에 있다. 템플릿 CSS 를 고칠 때 먼저 읽는다.

### US — 추세 칸 규칙 (구조 절)

- `<style>` 에 `td[data-trend] { min-width: 13em; white-space: normal; }` 를 넣는다 — 없으면 390px 에서 추세 칸이 좁게 접혀 행 높이가 세 배가 된다(실측 102px → 37px)

### US — §10 연준 이벤트 CSS

**CSS** (`<style>` 에 함께 넣는다):

```css
.fed-quote { border-left: 3px solid #0064FF; background: #F7F9FC; border-radius: 0 12px 12px 0;
             padding: 14px 16px; margin: 14px 0; }
.fed-quote blockquote { margin: 0 0 8px; font-size: 14px; line-height: 1.65; color: #333D4B;
                        font-style: normal; }
.fed-quote .fed-trans { margin: 0 0 6px; font-weight: 600; color: #191F28; }
.fed-quote .caption { margin: 0; }
.fed-idea { border: 1px solid #E5E8EB; border-radius: 12px; padding: 14px 16px; margin: 12px 0; }
.fed-idea [data-invalidation] { margin-bottom: 0; color: #6B7684; }
```


### US — HTML / 디자인 사양 절 전체

## HTML / 디자인 사양 (Toss 시스템) — 고정 템플릿, 임의 리디자인 금지

**폭 (2026-07-21 사용자 지시 — PC는 넓게, 모바일은 화면폭에 맞게)**: 보고서 본문 컨테이너는 `max-width: 1120px; margin: 0 auto`로 한다(고정 픽셀 폭이 아니라 max-width이므로 데스크톱에선 1120px까지 넓게 퍼지고, 좁은 화면에선 자동으로 화면폭에 맞춰진다). STEP 3에서 주입되는 상단 네비게이션 바도 `max-width:1120px`이므로 이 값과 반드시 일치시킨다. 매일 CSS를 새로 설계하지 말고 이 값을 그대로 쓴다 — 과거 한 호가 임의로 1180px·3열 그리드로 재설계해 **모바일 브레이크포인트 없이** 폰에서 글자가 깨진 사고가 있었다. 넓게 하되 아래 모바일 반응형 블록을 반드시 함께 넣는 것이 핵심이다.

- font-family: 'Toss Product Sans', Pretendard, 'Noto Sans CJK KR', -apple-system, sans-serif; letter-spacing -0.01em; 페이지 배경 #F2F4F6; 콘텐츠는 흰색 카드 위
- **폰트 크기 (2026-07-21 사용자 지시 — 약 12pt로 확대)**: 본문 읽는 문단(`.card p`, 일반 `<p>`)은 **16px(=12pt)**. 표는 14.5~15px, 헤드라인 카드 16~17px, h1 22px, h2 18.5~19px, h3 16px, 캡션·note·출처 12~13px, 섹터 막대 라벨 12.5px. 이전의 12.5px 본문은 너무 작다는 지적이 있었으니 다시 줄이지 말 것.
- 색상: primary/accent #0064FF (Toss Blue), 본문 #191F28, 보조 #4E5968, muted #8B95A1, 보더 #E5E8EB/#F2F4F6, 상승 #00A85A on #E8F8EE, 하락 #FF4040 on #FFE8E8, 정보 #0064FF on #E8F2FF
- 카드: 흰 배경, border-radius 14px, 1px solid #F2F4F6, 플랫. 필 태그(border-radius 9999px)
- 본문 문단 **들여쓰기 없음** (text-indent 금지, 2026-07-22 사용자 지시). 대신 `body { word-break: keep-all; }`를 반드시 넣어 한글이 줄바꿈에서 어절(단어) 중간에 쪼개지지 않게 한다 — 한글 기본값은 아무 글자에서나 줄바꿈되므로 keep-all이 없으면 '디스인플레이션' 같은 단어가 '디스인플레\n이션'으로 끊긴다.
- **문단 조판 (2026-08-24 사용자 지시 — 가독성)**: 카드는 1120px까지 넓게 쓰되 **읽는 문단은 그 폭을 다 쓰지 않는다.** 2026-08-24 실측에서 데스크톱 한 줄이 한글 66자였다(눈이 편한 범위는 35~45자). 아래 네 줄을 CSS에 반드시 넣는다 — 표·차트는 그대로 전체 폭을 쓰고 산문만 좁아진다.

```css
.card p, .doc p, p { line-height: 1.78; margin: 0 0 15px; max-width: 42em; }
.card p:last-child, .doc p:last-child, p:last-child { margin-bottom: 0; }
table { font-variant-numeric: tabular-nums; }
@media (max-width: 560px) { .card p, .doc p, p { line-height: 1.72; margin-bottom: 13px; } }
```

  `max-width: 42em`가 한 줄 42자를 만든다. 줄간격 1.78·문단 간격 15px은 이전 1.58·9px을 대체한다 — 한글 장문에서 1.6 이하 줄간격과 반 줄도 안 되는 문단 간격은 문단 경계를 지워 글을 벽으로 만든다. 모바일에서는 `max-width`가 저절로 무력해지므로 브레이크포인트를 따로 손댈 필요가 없다.

- **데스크톱 폭 (2026-08-26 지시 → 2026-08-28 지시로 갱신)**: 위 42em은 **모바일·태블릿 기준**이다. 그대로 두면 뷰포트가 1440px이든 768px이든 문단 폭이 똑같이 672px이라, 카드는 1080px인데 글은 672px만 쓰고 오른쪽 408px이 늘 빈다. 2026-08-26에는 이것을 50em(약 850px)으로 넓혔는데, **2026-08-28 사용자 지시(「문장 끝이 네모 전체에 차게 작성해. 중간에 줄바꿈 하지 말고」)로 데스크톱에서는 폭 제한을 아예 걷어낸다** — 50em도 1080px 카드에서 오른쪽 230px을 비웠다. 1024px 이상에서 본문은 17px이고 폭은 카드가 정한다(실측 1034px). **줄 끝에서 단어가 잘리지 않는 것은 `word-break: keep-all`이 보장한다** — 폭을 넓힌다고 이 속성을 빼면 안 된다. 이 블록은 `scripts/apply_readability.py`(v5)가 자동으로 넣으므로 손으로 쓸 필요는 없지만, **직접 쓴 CSS가 이것과 싸우지 않게** 한다.

```css
@media (min-width: 1024px) {
  .card p, .doc p, .panel p, p,
  .caption, .sub, .footer-note, .note, .lead, li { max-width: none; }
  .card p:not([class]), .doc p:not([class]), .panel p:not([class]), p:not([class]),
  .doc li { font-size: 17px; line-height: 1.8; }
  h1 { font-size: 25px; max-width: 30em; }
  h2 { font-size: 20px; }
  h3 { font-size: 17px; }
}
```

- **라벨은 본문 위에 선다 (2026-08-28 사용자 지시 — 「제목 바로 옆에 내용을 이어서 적지 말고 제목 밑에 줄바꿈을 해」)**: `<span class="box-label">장중 흐름.</span> 나스닥은…`처럼 라벨 옆에 본문이 이어 붙지 않는다. `.box-label`은 `display:block; width:fit-content`로 알약 모양을 지킨 채 제 줄을 차지하고, 문단 첫머리 `<strong>` 라벨은 `class="p-label"`을 달아 블록이 된다. **라벨과 강조된 첫 문장은 마침표 위치로 갈린다** — `<strong>오늘의 행동.</strong>`처럼 안에 있으면 라벨, `<strong>…지배했습니다</strong>.`처럼 밖에 있으면 그냥 문장이라 그대로 이어 쓴다. 종결어미(…다./…요.)로 끝나면 짧아도 문장이다. `apply_readability.py`가 자동으로 판정해 붙인다.
- **본문 크기는 맨 `p`에만 얹는다 (2026-08-26 실측 사고)**: `.card p, p { font-size:16px }`처럼 쓰지 말고 **`p { font-size:16px }`**로 쓴다. `.card p`는 특정도 (0,1,1)이라 `.caption`(0,1,0)을 이기고, 그러면 12.5px이어야 할 캡션·각주가 본문 크기 16px로 인쇄된다. 실제로 KR 발행본 5편과 US 1편이 이 선택자를 썼고 그 글들만 캡션이 커져 있었다. `.card p`에는 폭·줄간격·여백만 얹고 **font-size는 절대 얹지 않는다.** `scripts/apply_readability.py`가 이 선택자를 발견하면 한정 부분을 떼어내지만, 애초에 만들지 않는 것이 맞다.
- h2: bold #191F28 + 6px 라운드 Toss Blue 바 프리픽스(::before). 표: 헤더 행 배경 #F2F4F6 + 2px Toss Blue 하단 보더, 라운드 컨테이너
- 상단 바: 'US Market Brief' Toss Blue bold + 작성일. 헤드라인은 #E8F2FF 카드
- **`<title>` 태그 (SEO 최우선, 2026-07-23)**: 검색 결과에 뜨는 문구다. 반드시 `미국 증시 마감 시황 — [그날 핵심구] | [YYYY-MM-DD]` 형식으로 쓴다. 핵심구는 그날 헤드라인에서 뽑은 **검색될 키워드**(주도 종목·지수·촉매)를 25자 이내로 압축 — 예: `미국 증시 마감 시황 — 메모리주 폭등에 나스닥 반등 | 2026-07-21`. **금지: `US Market Brief — 날짜`처럼 영어 브랜드+날짜만 쓴 제목**(검색어가 없어 유입이 0이 된다). `og:title`은 기존대로 `미국 증시 모닝브리프 — YYYY년 M월 D일 (요일)` 유지.
- **H1 (필수, SEO)**: 본문 최상단 헤드라인 카드의 그날 한 줄 요약을 `<h1>`으로 감싼다(페이지당 정확히 1개). CSS에 `h1 22px`가 이미 정의돼 있다. 상단 바의 'US Market Brief'는 `<span class="brand">`로 두고 h1은 그날 헤드라인에만 쓴다 — h2로 바로 시작하지 말 것.
- **NewsArticle 구조화 데이터 (필수, SEO)**: `<head>`에 아래 JSON-LD를 넣는다(뉴스/리치결과 노출 자격). `headline`=og:title, `description`=meta description, `datePublished`/`dateModified`=보고서 날짜, `author`·`publisher`=`{"@type":"Organization","name":"US Market Brief","url":"https://fdo2a.github.io/"}`, `mainEntityOfPage`=canonical URL, `inLanguage`="ko". 형식: `<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle",...}</script>`
- 최상단에 `<meta charset="utf-8">`와 `<meta name="viewport" content="width=device-width, initial-scale=1">` 포함
- **구글 애드센스 로더**: `<head>` 안(권장: `</head>` 직전)에 아래 스크립트 한 줄을 반드시 포함한다 — 매 발행 글에 광고가 실린다.
  `<!-- adsense-loader --><script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9240461016907498" crossorigin="anonymous"></script>`
- 채권 섹션: 수익률 표 아래 카드에 커브 차트를 **외부 참조**로 넣는다 — `<img src="../assets/yield_curve_[YYYY-MM-DD].png" alt="미국 국채 수익률 커브" style="width:100%">`. **base64 data URI 를 쓰지 않는다** — 발행 단계가 같은 PNG 를 `assets/yield_curve_[DATE].png` 로 커밋하므로 임베드하면 같은 그림이 레포에 두 벌 들어가고 발행본이 3배가 된다(2026-09-03 실측 165,239 B 중 99,310 B 가 base64, 참조로 바꾸면 65,965 B). 파일명이 날짜별이라 과거 발행본도 제 차트를 가리킨다 + 주간 변화 캡션 + 출처·기준일 각주(위 '섹션 5. 채권 — 상세 사양')

**발행 전 가독성 수리 루프**: 먼저 `python3 scripts/apply_readability.py <산출 HTML>`로 조판·빠른 이동·긴 문단 분리를 적용한 뒤, `python3 scripts/check_readability.py --strict <산출 HTML>`을 돌린다. 경고는 현재 초안을 반려하는 수정 지시다. 출력에 찍힌 문장만 고쳐 다시 검사하고, 0건이 될 때까지 반복한 뒤 최종본을 넘긴다. 여러 논점이 겹쳐 이해를 방해하는 문장은 나누고, 수치 과밀은 정확값을 표에 남긴 채 산문을 관계 중심으로 줄이며, 반복 수치는 정본 표와 첫 설명만 남긴다. 이 과정에서 보고서 전체 섹션이나 근거를 삭제해 얇은 대체본으로 만들지 않는다.

**게이트 소스를 읽지 않는다.** `scripts/check_*.py`·`scripts/us/readability.py` 등을 열어 기준을 역산하지 않는다 — 게이트는 걸린 줄마다 한도를 찍고, 가독성 게이트는 무엇을 세는지 「기준」 줄도 찍는다. 출력이 계약의 전부다. 출력만으로 고칠 수 없으면 추측하지 말고 그 출력을 그대로 보고한다.

**다단 그리드는 지수/섹터 표 한 곳(`.grid-2`, 2단)에만 쓴다.** 그 외 서술형 카드(경제지표 대시보드 카드 등)는 위에서 지시한 대로 세로 스택 — 3열 이상 그리드로 텍스트 카드를 배치하지 않는다(모바일에서 읽기 불가능해짐).

**모바일 반응형 (필수, 2026-07-20 사용자 지시)**: 실제 스마트폰(약 375~430px 폭)에서 읽었을 때 어떤 다단 요소도 글자가 뭉개지지 않아야 한다.

**수치 칸의 색은 손으로 칠하지 않는다 (2026-09-12 사용자 지시 「가시성을 높혀」).** 발행 직전에 `scripts/apply_colors.py`가 결정론적으로 칠한다(class 는 `sc-up`·`sc-dn`, 발행본마다 서식이 다른 `pos`·`neg`와 겹치지 않게 따로 둔 이름이다).

- 「전일 대비」·「등락」 — 값 부호 그대로. 오르면 초록
- **채권 섹션**의 「전일 변화」·「주간 변화」 — **수익률 기준으로 반전**. 금리가 떨어지면 초록
- **매크로 섹션**의 「Actual」 — **같은 행 「직전 대비」 칸(`data-vs-prev`)을 그대로 읽는다**(개선·하락 초록 / 악화·상승 빨강 / 보합 무색). 그 칸이 없는 옛 표만 「판정」 어휘를 읽는다(개선·둔화 초록 / 악화·재가속 빨강 / 보합·교착 무색). 판정을 다시 계산하지 않는다 — 원시 부호로 읽으면 실업수당이 **줄어든** 날을 나쁜 방향이라 칠한다(§9가 판정 어휘를 도입한 바로 그 사고). 판정 칸이 없는 옛 「최근 | 이전」 표에만 전기 대비로 대체한다

하루 70칸이라 사람이 칠하면 매일 틀린다. **해야 할 일은 하나뿐이다 — 열 이름을 위 이름 그대로 쓰고 모든 `<td>`에 `data-label`을 단다.** 색 class 를 직접 쓰거나 인라인 `style`로 색을 넣지 말 것.

**모든 `<table>`은 예외 없이 `<div class="tbl-scroll"><table>...</table></div>`로 감싼다.** (표 마크업을 쓸 때마다 이 래퍼를 빠뜨리지 말 것 — `table { display:block; overflow-x:auto }` 같은 트릭은 내부 table 레이아웃과 충돌해 동작하지 않는다. 실제로 동작을 확인한 방식은 래퍼 div뿐이다.) `<style>` 블록에 아래를 반드시 포함한다:
```css
.tbl-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 10px; }
@media (max-width: 560px) {
  .doc, .container { padding-left: 14px; padding-right: 14px; }
  .grid-2 { grid-template-columns: 1fr; }
  table { font-size: 11px; }
  th, td { padding: 5px 7px; white-space: nowrap; }
  th:first-child, td:first-child { white-space: normal; }
  th:last-child, td:last-child { white-space: normal; }
}
```
첫 열(지표명·종목명)과 마지막 열은 줄바꿈을 허용하고 그 사이 숫자·날짜 열만 nowrap로 보호한다 — '전략 근거'처럼 긴 서술이 마지막 열에 오는 표가 모바일에서 한 줄로 늘어나 과도한 가로 스크롤이 생기는 것을 막는다. **서술 칸이 둘 이상인 표에는 이 규칙이 통하지 않는다 — 아래 `.stance-tbl`을 쓴다.** 그래도 6열짜리 경제지표 표처럼 좁은 화면에 다 안 들어가는 표는 `.tbl-scroll` 래퍼 덕에 가로 스크롤이 생긴다 — 열을 줄이거나 글자를 억지로 더 축소하지 않는다. 검증은 스크린샷 눈대중이 아니라 `document.documentElement.scrollWidth`가 뷰포트 폭과 같은지(페이지 레벨 가로 스크롤이 없는지) 확인하는 방식이 정확하다.
`sector_performance.html` 스니펫은 자체 미디어쿼리를 이미 포함하고 있으니 그대로 삽입하면 된다(수정 금지).

**본문 `body`에 `overflow-wrap: break-word`를 함께 건다 (2026-08-20).** `word-break: keep-all`만 걸면 「Western Digital(+5.35%)·Marvell(+5.54%)·Micron(+4.13%)」처럼 공백 없이 가운뎃점으로 이어붙인 종목 나열이 **끊기지 않는 한 덩어리**가 돼 390px에서 페이지 전체가 가로로 밀린다(2026-07-22·08-17 발행본 실측 403px·524px). `break-word`는 한글 단어는 그대로 두고 넘치는 라틴 덩어리만 쪼갠다.

**서술 칸이 둘 이상인 표 = `.stance-tbl` (2026-08-20 사용자 지시, 2026-09-19 부터 매크로 4축 표·MLCC 표에 적용)** — 서술 칸이 `논거`·`다음 분기점` 둘이라 위의 nowrap 규칙으로는 비율이 무너진다(실측: 390px에서 논거 칸이 1,250px 한 줄로 늘어나고 다음 분기점은 85px로 눌려 표 전체가 1,808px). 모바일에서는 표를 좁은 화면에 밀어넣지 말고 **행 하나를 카드 하나로 세로로 쌓는다**. 마크업은 `<table class="stance-tbl">` + **모든 `<td>`에 `data-label="열 이름"`** (라벨이 모바일에서 머리행을 대신한다).
```css
.stance-tbl { table-layout: fixed; }
@media (min-width: 561px) {
.stance-tbl th:nth-child(1), .stance-tbl td:nth-child(1) { width: 8%; }
.stance-tbl th:nth-child(2), .stance-tbl td:nth-child(2) { width: 17%; text-align: left; }
.stance-tbl th:nth-child(3), .stance-tbl td:nth-child(3) { width: 8%; }
.stance-tbl th:nth-child(4), .stance-tbl td:nth-child(4) { width: 9%; }
.stance-tbl th:nth-child(5), .stance-tbl td:nth-child(5) { width: 31%; text-align: left; }
.stance-tbl th:nth-child(6), .stance-tbl td:nth-child(6) { width: 27%; text-align: left; }
}
@media (max-width: 560px) {
  .stance-tbl, .stance-tbl tbody, .stance-tbl tr, .stance-tbl td { display: block; width: auto; }
  .stance-tbl thead { display: none; }
  .stance-tbl { font-size: 14px; }
  .stance-tbl tr { background: #fff; border: 1px solid #E5E8EB; border-radius: 12px;
    padding: 12px 14px; margin-bottom: 10px; }
  .stance-tbl tr:last-child { margin-bottom: 0; }
  .stance-tbl td { padding: 0; border: none; text-align: left; white-space: normal; font-weight: 400; }
  .stance-tbl td::before { content: attr(data-label); display: block; font-size: 11px; font-weight: 800;
    color: #8B95A1; letter-spacing: 0.02em; margin: 10px 0 2px; }
  .stance-tbl td:nth-child(1) { font-size: 15px; font-weight: 800; }
  .stance-tbl td:nth-child(1)::before, .stance-tbl td:nth-child(2)::before { content: none; }
  .stance-tbl td:nth-child(2) { margin-top: 3px; }
  .stance-tbl td:nth-child(3), .stance-tbl td:nth-child(4) { display: inline-block;
    margin: 9px 14px 0 0; font-size: 12.5px; color: #4E5968; }
  .stance-tbl td:nth-child(3)::before, .stance-tbl td:nth-child(4)::before { display: inline;
    margin: 0 5px 0 0; }
}
```
데스크톱 열 너비를 `min-width: 561px` 안에 가두는 것이 핵심이다 — `nth-child` 셀렉터(0,2,1)가 모바일의 `width: auto`(0,1,1)를 이기기 때문에, 밖에 두면 카드로 쌓아도 칸이 27px·103px로 쪼그라든다(실측).

**§8 4축 스트립 CSS (2026-08-18)** — 전달경로 스트립과 같은 골격을 쓴다.
```css
.ax-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 14px; }
.ax-item { display: inline-flex; align-items: baseline; gap: 6px; padding: 7px 11px;
           background: #F9FAFB; border: 1px solid #F2F4F6; border-radius: 9999px;
           font-size: 13.5px; white-space: nowrap; }
.ax-item b { font-weight: 700; color: #191F28; }
.ax-item .sub { font-size: 11.5px; color: #8B95A1; }
.ax-item [data-axis] { padding: 2px 8px; border-radius: 9999px; font-weight: 700;
                       font-size: 12.5px; background: #F2F4F6; color: #4E5968; }
```
방향별 색은 전달경로 배지와 같은 팔레트를 쓴다 — 개선/둔화는 `#00A85A on #E8F8EE`, 악화/재가속은 `#FF4040 on #FFE8E8`, 보합/교착은 기본 회색. **물가축은 「개선」이 아니라 「둔화」가 초록**이다(인플레가 내려가는 것이 우호적).

**§8 방향 스트립 CSS (2026-08-18)** — 표를 쓰지 않으므로 `.tbl-scroll` 규칙이 닿지 않는다. 아래를 `<style>`에 함께 넣는다. `flex-wrap`이 좁은 화면에서 배지를 여러 줄로 흘려보내므로 가로 스크롤이 아예 생기지 않는다.
```css
.mt-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px; }
.mt-item { display: inline-flex; align-items: baseline; gap: 6px; padding: 7px 11px;
           background: #F9FAFB; border: 1px solid #F2F4F6; border-radius: 9999px;
           font-size: 13.5px; white-space: nowrap; }
.mt-item b { font-weight: 700; color: #191F28; }
.mt-item .sub { font-size: 11.5px; color: #8B95A1; }
.mt-item [data-direction="1"]  { color: #00A85A; background: #E8F8EE; }
.mt-item [data-direction="0"]  { color: #4E5968; background: #F2F4F6; }
.mt-item [data-direction="-1"] { color: #FF4040; background: #FFE8E8; }
.mt-item [data-direction] { padding: 2px 8px; border-radius: 9999px; font-weight: 700;
                            font-size: 12.5px; }
[data-macro-group] { margin-bottom: 14px; }
[data-macro-group] h4 { font-size: 15px; font-weight: 700; color: #191F28;
                        margin: 0 0 6px; }
```

**페이지 분할 규칙 (중요):** 각 섹션을 `<section>`으로 감싸고 `section { break-inside: avoid-page; page-break-inside: avoid; }` 적용 — 안 들어가면 통째로 다음 페이지부터. 경제지표 대시보드는 축별 섹션 분리. 표와 카드에도 page-break-inside: avoid.


### KR — 제목·JSON-LD 규칙

**`<title>` 태그 (SEO 최우선, 2026-07-23)**: `코스피 마감 시황 — [그날 핵심구] | [YYYY-MM-DD]` 형식. 핵심구는 그날 헤드라인의 검색될 키워드(지수 등락·수급·주도 업종·주도주)를 25자 이내로 — 예: `코스피 마감 시황 — 외국인 순매수에 코스피·코스닥 동반 급등 | 2026-07-23`. `og:title`은 `한국 증시 마감브리프 — YYYY년 M월 D일 (요일)` 유지. **H1**은 US 스펙과 동일 — 그날 헤드라인을 `<h1>` 1개로. **NewsArticle 구조화 데이터**도 US 스펙과 동일하게 `<head>`에 넣되 `author`·`publisher`의 name은 `"KR Market Brief"`, url은 `"https://fdo2a.github.io/kr/"`로.
