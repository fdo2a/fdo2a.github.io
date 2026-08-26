# KR Evening Brief — Orchestrator Runbook

한국 시장 **저녁 마감브리프**의 오케스트레이터. 평일 18:00 KST 실행. US 모닝브리프(`ORCHESTRATOR.md`)와 데이터·발행이 완전 분리되며, 공유 규칙(디자인·문체·검증)은 US 문서를 참조한다.

**Report trading date**: `kr/data/kr_market_data.json`의 `report_date`(코스피 실제 종가일)를 신뢰한다. KST 요일 산술은 폴백일 뿐. 저녁 발행이라 당일 세션이 마감된 상태여야 한다 — 장중(15:30 이전) 실행 시 당일치는 미완이므로 데이터 워크플로(17:00·17:30 KST cron)가 마감 후 확정한 데이터를 쓴다.

## STEP 0 — 커밋된 KR 데이터 확인 (먼저)

`.github/workflows/collect-kr-data.yml`가 마감 후 Naver+yfinance로 `kr/data/*`를 커밋한다(수급·**장중 수급 궤적**·**프로그램 매매**·거래대금·업종·테마·섹터·지수·장중·**기술적 지표**). **루틴 환경은 금융 호스트가 막힐 수 있으니 직접 fetch 금지 — 커밋된 파일을 읽는다.** 장중 수급은 `kr_flows_intraday.json`(누적 순매수 30분 앵커·극값·방향 전환, 억원)·차트 `kr_flows_intraday.png`, 프로그램 매매는 `kr_program.json`(차익·비차익·전체 순매수, 억원), 기술적 지표는 `kr_technical.json`(4종 이평·볼린저·일목)·오버레이 `kr_charts.png` — 전부 비-코어(없어도 발행 게이트 통과, 해당 블록만 생략).

1. `git -C <repo> pull` 후 `kr/data/kr_market_data.json` Read.
2. `report_date`가 예상 세션과 맞고 `"complete": true`(코어 4종: indices·flows·top_value·sectors)면 그대로 사용. `missing`에 `econ`·`themes`·`flows_intraday`만 있으면 발행 가능(전부 비-코어 — `flows_intraday` 결측 시 §5 장중 수급 서브블록만 생략). `econ`은 ECOS 금리 일부/전량 결측 — writer가 결측 행을 빼고 §9를 재구성한다(2026-07-29 ECOS 연동, 인증키는 레포 시크릿 `ECOS_API_KEY`). `themes`는 2026-07-29 테마 섹션 폐지로 강등.
3. 없거나 stale/`complete:false`면 `python scripts/collect_kr_data.py --outdir kr/data`를 실행해 채운다(네트워크 열린 환경에서만).

**수급 신선도**: `flows_date`·`flows_provisional`을 STEP 2에 그대로 넘긴다. 당일 확정치가 없으면 writer가 "당일 잠정"/"전 거래일 기준"으로 라벨링한다 — 오케스트레이터가 수급을 창작하지 않는다.

## STEP 1 — 리서치 (research_notes.md)

수치가 아닌 **뉴스·정책 촉매·해석**만 웹 리서치한다(수치는 kr/data가 확정). 최소 포함:
- 그날 코스피·코스닥·수급을 움직인 뉴스(외국인 매매 배경, 대장주 이슈)
- **정책·정치 촉매 — 리서치 비중 최우선 (2026-07-29 사용자 지시로 섹션 확대)**: 밸류업·기업지배구조(상법·자사주)·금투세·대주주 양도세·배당 분리과세·한은 금통위·반도체/2차전지/바이오 보조금·통상(대미 관세·수출규제)·환율당국·국민연금·부동산 규제·지정학·국회 일정 중 그날 해당분. writer가 블록당 **사실 → 전달 경로(수급/이익/멀티플) → 수혜·피해 업종 → 다음 일정·확인 트리거** 4요소를 쓸 수 있도록 각 재료마다 이 네 가지를 채워서 넘긴다. 그날 신규 재료가 없으면 **계류 중인 정책의 진행 상황**을 조사해 채운다(검색 2~4회 배정).
- 거래대금 상위·업종 주도에서 드러난 종목의 개별 재료(§8 특징주용)
- 출처 귀속 필수. 복수 출처 교차 확인(단일 검색 수치 불신 — US 전례).

**테마 리서치는 폐지** (2026-07-29 사용자 지시로 테마 섹션 삭제). `kr_theme.json`은 리서치·작성 어디서도 쓰지 않는다.

## STEP 2 — 리포트 작성 (subagent: kr-report-writer)

Agent 도구로 `kr-report-writer` 동기 실행. 프롬프트: report_date, kr/data 입력 목록(**kr_flows_intraday.json/.png·kr_program.json·kr_technical.json 포함**), research_notes.md, 산출 파일명 `kr_brief_[YYYY-MM-DD].html`. Agent 미지원 시 `.claude/agents/kr-report-writer.md` 본문을 읽어 general-purpose에 위임하거나 직접 수행(폴백). 장중 수급 전개·프로그램 매매는 수급 서브블록(그 순서대로), 기술적 분석/전략은 일봉 차트 바로 아래 산문 섹션(writer 스펙 §5·§4.5). **구조 변경 반영(2026-07-29)**: 전략 코멘트가 §2로 전진(헤드라인 다음), 테마 섹션 폐지, 정책·정치 촉매(§10) 확대 — writer 스펙의 섹션 순서를 그대로 따르게 프롬프트에 명시한다.

**발행 게이트**: (a) `grep -c '확인필요'` = 0; (b) 수급 서술 기준일이 `flows_date`와 일치하고 provisional/stale 라벨이 있는지; (c) 표 수치 5개+ 를 kr/data/* 원본과 대조. 실패 시 재작성. **완성본만 발행 — 코어 표에 구멍 있으면 발행 중단, PushNotification으로 누락 보고.**

**가독성 게이트 = 초안 수리 루프 (실패로 루틴 종료 금지)**

1. `python3 scripts/apply_readability.py <kr_brief 절대경로>`(v4 조판 — 데스크톱 본문 17px·`max-width:50em`, 캡션 특정도 교정) 뒤 `python3 scripts/check_readability.py --strict <kr_brief 절대경로>`와 **`python3 scripts/check_style.py <kr_brief 절대경로>`**의 전체 출력을 저장한다. 문체 검사는 **쉬운 말 검사를 겸한다(2026-08-26)** — 풀어 쓸 수 있는 음차어, 풀이 없이 처음 나온 전문어, 한 문장에 겹친 낯선 말을 잡는다. 나머지 문체 항목은 STEP 2.5의 윤문과 별개로 여기서 항상 돈다 — 윤문은 건너뛸 수 있어도 문체 기준은 건너뛰지 않는다.
2. 위반 원인별로 처방한다: 헤드라인은 방향·촉매·행동만 남기고, 장중 시각이 셋 이상인 문장은 시간대별로 나눈다. 수치가 다섯 개 이상이면 정확한 레벨은 표에 두고 산문에는 가장 가까운 지지·저항과 관계만 남긴다. 원화·지수 소수점은 산문에서 반올림하고 정밀값은 표·JSON에서 보존한다. 반복 수치는 첫 설명과 정본 표 한 곳만 남긴다.
3. 검사 원문을 writer에게 넘겨 **전체 보고서를 유지한 채 위반 문단만 수정**하게 하고 apply → strict check를 반복한다.
4. writer가 두 번 연속 같은 위반을 남기면 오케스트레이터가 해당 문단을 직접 국소 수정한다. 수치 정본과 표 대조, 수급 신선도, 정책 블록 수는 다시 확인한다. **통과할 때까지 수리 루프를 계속한다.**

가독성 실패는 현재 초안을 반려할 뿐 미발행 사유가 아니다. 데이터 정본의 completeness 실패만 기존 규칙에 따라 중단할 수 있다.

## STEP 2.5 — AI 티 제거 (발행 전 마지막 손질)

2026-08-25 사용자 지시. 리포트를 **말하듯이** 쓰라는 문체 기준(`.claude/agents/brief-report-writer.md`의 「말하듯이 쓴다」 절(KR도 공유))을 writer가 지켰더라도, 매일 같은 틀로 생성된 글에는 사람이 안 쓰는 리듬이 남는다. 발행 직전에 한 번 걸러낸다.

**1. 원본은 건드리지 않는다. 사본에서 작업한다.**

```bash
cp kr_brief_[DATE].html kr_brief_[DATE].humanizing.html
```

윤문도 검증도 전부 이 사본에서 한다. 원본이 바뀌는 순간은 4번의 finalize 하나뿐이다. 그래서 스킬이 예외로 죽든, 시간이 초과되든, 문단을 반만 쓰고 멈추든, 사본을 지우면 그것으로 끝이다 — 원본은 애초에 한 번도 수정되지 않았다. **원본을 먼저 고치고 나중에 되돌리는 방식은 쓰지 않는다.** 되돌리기가 실패하는 분기가 남기 때문이다.

**2. 산문을 꺼낸다.**

```bash
python3 scripts/humanize_prose.py extract kr_brief_[DATE].humanizing.html
```

`prose_in.txt`(손댈 문단만, 이름표 `[[P001]]`이 붙어 있다)와 `prose_map.json`(사이드카)이 나온다. 표 안 문단·캡션·에디터 노트는 애초에 뽑히지 않는다 — **넘기지 않은 것은 훼손될 수 없다.** 인라인 태그(`<strong>` 등)는 `⟦0⟧` 자리표로 바뀌어 나가고, 되꽂을 때 하나라도 없으면 거부된다.

**3. `prose_in.txt`의 문장을 고친다. 이름표 줄(`[[P001]]`)은 건드리지 않는다.**

`humanize-korean` 스킬은 레포 `.claude/settings.json`이 마켓플레이스(`epoko77-ai/im-not-ai`)째 등록해 둔다 — 이 레포를 클론한 세션은 시작할 때 설치를 시도한다. **그래도 쓸 수 있다고 가정하지 않는다.** 트리거의 `allowed_tools`에 `Skill`이 빠져 있으면 설치돼도 부를 수 없고(스킬이 서브에이전트를 띄우므로 `Agent`도 있어야 한다), 샌드박스가 마켓플레이스를 못 받아오는 경우도 있다.

**목록에 보이는 것과 부를 수 있는 것은 다르다.** `allowed_tools`는 사전 승인 목록이라 이름이 보여도 호출이 거부될 수 있다. 그러니 판정은 호출해 보고 한다 — 거부·오류·산출물 없음 중 하나라도 나오면 **반쯤 나온 결과는 버리고** 직접 고친다. **어느 쪽이든 이 단계를 건너뛰지는 않는다.**

- **스킬로 할 때**: `prose_in.txt`를 입력으로 준다. 스킬은 텍스트를 받아 `_workspace/{run_id}/final.md`(마크다운)를 내놓는다 — **HTML을 고쳐 주지 않으므로 HTML을 통째로 넘기는 사용법은 없다.** 이름표를 그대로 두고 문장만 고치라고, **강도는 「보수」**로 명시한다 — 스킬이 절을 갈아끼우기 시작하면 4번에서 통째로 거부된다.
- **직접 할 때**: `prose_in.txt`를 그 자리에서 고치고, 그 파일을 그대로 4번의 `--payload`로 쓴다. `python3 scripts/check_style.py <html>`의 출력이 작업 목록이다. 검사가 짚은 항목부터 고치고, 검사가 못 보는 아래 셋도 함께 훑는다.
  - **주어를 되살린다.** 앞 문장에서 이어받아 생략한 주어를 다시 넣는다. 「이후 반등해…」 → 「코스피는 이후 반등해…」.
  - **한 문장에 한 관계만 남긴다.** 「A했다가 B했고 이후 C해서 D로 마감했다」는 문장이 아니라 표다. 시각이 셋 이상이면 나눈다.
  - **판단을 능동으로 쓴다.** 「~로 읽힌다/판정된다」를 「~라고 볼 수 있습니다」나 「A가 B를 끌어내렸습니다」로 바꾼다.

**두 경로 모두 문장만 만진다.** 숫자·자리표·이름표는 그대로 둔다. 4번이 그것을 강제한다.

**4. 되꽂고, 검사하고, 통과했을 때만 원본을 교체한다. 한 명령으로 한다.**

```bash
python3 scripts/humanize_prose.py finalize kr_brief_[DATE].humanizing.html \
  --original kr_brief_[DATE].html --payload <고친 prose_in.txt 또는 _workspace/{run_id}/final.md> \
  --gate "python3 scripts/check_style.py {f}" \
  --gate "python3 scripts/check_readability.py --strict {f}" \
  --gate "python3 scripts/verify_post.py {f} --before kr_brief_[DATE].html --skip-layout"
```

되꽂기 → 바뀐 문단 출력 → 게이트 순서로 돌고, **전부 통과했을 때만** `os.replace`로 원본을 교체한다. 하나라도 실패하면 사본을 지우고 exit 1로 끝난다 — 원본은 처음부터 수정되지 않았다. **맨손 `mv`는 쓰지 않는다.** 검사를 건너뛰고 교체할 자리를 남기지 않는 것이 이 명령의 존재 이유다.

되꽂기가 거부하는 것 — **문단마다** 이것들이 원문과 같아야 한다:

- 숫자 (**부호 포함** — `+1.2%`와 `-1.2%`는 다른 값이다)
- 영문 이름·티커 (AAPL과 TSLA를 문단끼리 맞바꾸면 각자 제 원문과는 여전히 닮아 유사도로는 안 잡힌다)
- **판단 어휘** — 개선·악화·보합, 둔화·가속·재가속, 뚜렷·완만·미미, 레짐 이름 9종, 확대·축소·중립. 「완만한 개선」을 「뚜렷한 악화」로 바꾸면 3-gram 유사도는 0.8이 넘는다. 말투는 바꿔도 이 낱말들은 그대로 둔다
- 링크가 감싼 말 (`<a>`가 「연준 보고서」에서 「노동부 자료」로 옮겨 붙으면 멀쩡한 링크가 엉뚱한 출처를 가리킨다)
- 인라인 자리표의 개수와 순서, 문단 길이(0.5~2.0배)
- 그리고 **몸통이 제 원문보다 다른 문단에 더 닮지 않을 것**

**이 단계가 허락하는 것은 문법과 말투까지다.** 종결어미를 바꾸고, 주어를 되살리고, 긴 문장을 나누는 것 — 거기까지다. 절을 갈아끼우는 재작성은 문턱(닮은 정도 0.80)에서 걸린다. 원문에 없던 인과를 넣거나 조건절을 떼어 단정으로 만드는 의미 변화는 어떤 사실 검사로도 못 잡으니, **애초에 그만큼 못 바꾸게 막는 편이 낫다.** 08-21 발행본 58문단 실측에서 말투 편집은 최저 0.95, 절을 갈아끼운 재작성은 중앙 0.62로 두 무리가 갈렸다.

닮은 정도 비교는 총체적 뒤바뀜도 함께 잡는다. 이름표는 자리만 정하지 몸통이 제 자리 것인지는 보증하지 않는다 — 숫자가 없는 문단끼리 내용을 통째로 맞바꾸면 수치 검사도 `verify_post`도 전부 통과한다(2026-08-25 codex 검토에서 실제로 뚫린 뒤 들어간 검사다).

`finalize`는 게이트가 **하나도 없으면 시작하지 않고**, 사본과 원본 경로가 같아도 시작하지 않는다(검사 실패 시 원본을 지우게 된다). 게이트는 셸을 거치지 않고 인자 배열로 실행된다.

게이트를 다시 돌리는 이유가 있다. STEP 2의 게이트들은 **윤문 전 원고를 보고 통과시킨 것이다.** 문장을 다시 쓴 뒤에도 그 판정이 유효하다고 가정하면 안 된다. 통과한 뒤 §2 전략 코멘트의 수치가 아래 표와 여전히 1:1로 맞는지, 수급 신선도 라벨(당일 잠정/전 거래일 기준)이 그대로인지도 확인한다 — 윤문이 라벨을 문장에 녹이다 지울 수 있다.

**5. 명령이 찍어 준 「바뀐 문단」을 읽는다.**

허용 범위를 문법·말투로 좁혔으니 남는 것은 그 안에서의 미세한 뉘앙스뿐이다. 그래도 **사람이 한 번 읽는다** — finalize가 바뀐 문단만 전/후로 찍어 주므로 그 출력을 그 자리에서 읽는다.

**이 읽기는 교체를 막지 못한다** — finalize는 이미 원본을 바꾼 뒤다. 그래서 여기서 이상한 것을 발견하면 발행 후 검토 게이트(`.claude/REVIEW_GATE.md`)로 넘긴다. 그쪽이 발행본을 다시 읽고 정정하는 자리다. 윤문이 만든 의미 변화도 그 절차가 잡는 대상에 포함된다.

**윤문이 거부돼도 발행은 계속한다.** 말투는 있으면 좋은 것이고, 게이트는 필수다.

사본(`*.humanizing.html`)·`prose_in.txt`·`prose_map.json`과 스킬 작업 폴더(`_workspace/`)는 `.gitignore`에 걸려 있다. STEP 3의 `git add -A`가 쓸어 담지 않는다.

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

## STEP 4 — 알림
PushNotification으로 헤드라인 + `https://fdo2a.github.io/kr/posts/YYYY-MM-DD.html`.

**발행 채널은 블로그 하나뿐이다 (2026-08-18 사용자 지시로 Notion 발행 중지).** Notion·PDF·이메일 모두 없음. 세션에 Notion 커넥터가 붙어 있어도 쓰지 않는다 — 연결돼 있다는 사실이 사용 지시는 아니다.

## RULES
- 모든 수치는 kr/data/*에서만. 수치 창작 절대 금지.
- **수급 신선도 라벨 필수** — 당일 확정 없으면 잠정/전거래일 명시.
- **완성본만 발행** — 코어 표 구멍 시 중단·보고.
- 발행본 [확인필요] 금지. 출처 귀속. 기관 전략 리포트 톤.
- **buy-side 표기 금지 (2026-08-22 사용자 지시)** — 전략·리포트·시황 정리로. 발행 전 `grep -i "buy[- ]\?side" kr_brief_*.html`로 확인.
