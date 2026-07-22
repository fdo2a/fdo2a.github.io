# KR Evening Brief — Orchestrator Runbook

한국 시장 **저녁 마감브리프**의 오케스트레이터. 평일 18:00 KST 실행. US 모닝브리프(`ORCHESTRATOR.md`)와 데이터·발행이 완전 분리되며, 공유 규칙(디자인·문체·검증)은 US 문서를 참조한다.

**Report trading date**: `kr/data/kr_market_data.json`의 `report_date`(코스피 실제 종가일)를 신뢰한다. KST 요일 산술은 폴백일 뿐. 저녁 발행이라 당일 세션이 마감된 상태여야 한다 — 장중(15:30 이전) 실행 시 당일치는 미완이므로 데이터 워크플로(17:00·17:30 KST cron)가 마감 후 확정한 데이터를 쓴다.

## STEP 0 — 커밋된 KR 데이터 확인 (먼저)

`.github/workflows/collect-kr-data.yml`가 마감 후 Naver+yfinance로 `kr/data/*`를 커밋한다(수급·거래대금·업종·테마·섹터·지수·장중). **루틴 환경은 금융 호스트가 막힐 수 있으니 직접 fetch 금지 — 커밋된 파일을 읽는다.**

1. `git -C <repo> pull` 후 `kr/data/kr_market_data.json` Read.
2. `report_date`가 예상 세션과 맞고 `"complete": true`(코어 5종: indices·flows·top_value·sectors·themes)면 그대로 사용. `missing`에 `econ`만 있으면 정상(ECOS 미구현, §10).
3. 없거나 stale/`complete:false`면 `python scripts/collect_kr_data.py --outdir kr/data`를 실행해 채운다(네트워크 열린 환경에서만).

**수급 신선도**: `flows_date`·`flows_provisional`을 STEP 2에 그대로 넘긴다. 당일 확정치가 없으면 writer가 "당일 잠정"/"전 거래일 기준"으로 라벨링한다 — 오케스트레이터가 수급을 창작하지 않는다.

## STEP 1 — 리서치 (research_notes.md)

수치가 아닌 **뉴스·정책·테마 촉매·해석**만 웹 리서치한다(수치는 kr/data가 확정). 최소 포함:
- 그날 코스피·코스닥·수급을 움직인 뉴스(외국인 매매 배경, 대장주 이슈)
- **정책·정치 촉매**(spec §4.4): 밸류업·금투세·대주주·상법·한은 금리·반도체/2차전지 보조금·통상(관세)·환율당국·부동산·지정학 — 회고+전망
- 상위 테마(`kr_theme.json`)의 재료·주도주
- 출처 귀속 필수. 복수 출처 교차 확인(단일 검색 수치 불신 — US 전례).

## STEP 2 — 리포트 작성 (subagent: kr-report-writer)

Agent 도구로 `kr-report-writer` 동기 실행. 프롬프트: report_date, kr/data 입력 목록, research_notes.md, 산출 파일명 `kr_brief_[YYYY-MM-DD].html`. Agent 미지원 시 `.claude/agents/kr-report-writer.md` 본문을 읽어 general-purpose에 위임하거나 직접 수행(폴백).

**발행 게이트**: (a) `grep -c '확인필요'` = 0; (b) 수급 서술 기준일이 `flows_date`와 일치하고 provisional/stale 라벨이 있는지; (c) 표 수치 5개+ 를 kr/data/* 원본과 대조. 실패 시 재작성. **완성본만 발행 — 코어 표에 구멍 있으면 발행 중단, PushNotification으로 누락 보고.**

## STEP 3 — 블로그 발행 (/kr/)

1. 리포트 HTML을 `kr/posts/[YYYY-MM-DD].html`로 복사, 두 주입:
   (a) `<div class="doc">` 바로 앞 네비게이션(폭 1120px 일치):
```html
<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;display:flex;align-items:center;gap:10px;">
  <a href="../index.html" style="text-decoration:none;background:#fff;border:1px solid #E5E8EB;border-radius:9999px;padding:6px 14px;font-size:12px;font-weight:700;color:#191F28;">‹ 전체 보고서</a>
  <a href="../index.html" style="text-decoration:none;font-size:14px;font-weight:800;color:#0064FF;letter-spacing:-0.02em;">KR Market Brief</a>
  <a href="../../index.html" style="text-decoration:none;font-size:12px;font-weight:700;color:#8B95A1;margin-left:auto;">🇺🇸 미국 시장 →</a>
</div>
```
   (b) `<title>` 바로 앞 SEO 메타:
```html
<meta name="description" content="[헤드라인 한 줄]. [YYYY-MM-DD] 한국 증시 마감브리프.">
<link rel="canonical" href="https://fdo2a.github.io/kr/posts/[YYYY-MM-DD].html">
<meta property="og:type" content="article">
<meta property="og:title" content="한국 증시 마감브리프 — [YYYY년 M월 D일 (요일)]">
<meta property="og:url" content="https://fdo2a.github.io/kr/posts/[YYYY-MM-DD].html">
```
2. `kr/posts.json`에 `{date,title,headline}` 추가(같은 날짜는 REPLACE, 중복 금지). 유효 JSON 유지.
3. `sitemap.xml`에 `https://fdo2a.github.io/kr/posts/DATE.html` url 추가(전체 재생성, US 항목 보존).
4. main에 커밋·푸시: `git add -A && git commit -m "Add KR brief [YYYY-MM-DD]" && git push`. 푸시 실패 시 나머지 진행 후 최종 메시지·푸시알림에 명확히 보고(클라우드 푸시는 GitHub App Installed 권한 필요).

## STEP 4 — Notion 발행

Notion MCP(`notion-create-pages`)로 DB "KR Market Brief" data_source_id **`d1dcda42-2e15-4080-93a2-b77622e46f3d`**에 페이지 1개 생성(같은 날짜 중복 금지 — 새로 만들지 말고 이 DB 사용). properties: 제목·`date:날짜:start`·헤드라인·웹 링크(https://fdo2a.github.io/kr/posts/YYYY-MM-DD.html), icon 📉. content는 Notion 마크다운(헤드라인 인용 + 링크 + 섹션 헤딩·표 + 면책).

## STEP 5 — 알림
PushNotification으로 헤드라인 + `https://fdo2a.github.io/kr/posts/YYYY-MM-DD.html`. PDF·이메일 없음.

## RULES
- 모든 수치는 kr/data/*에서만. 수치 창작 절대 금지.
- **수급 신선도 라벨 필수** — 당일 확정 없으면 잠정/전거래일 명시.
- **완성본만 발행** — 코어 표 구멍 시 중단·보고.
- 발행본 [확인필요] 금지. 출처 귀속. buy-side 톤.
