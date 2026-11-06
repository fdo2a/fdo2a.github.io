# 경제지표 원문 수집 계약 (2026-11-06 구현, 11-07 첫 적용)

사용자 지시(2026-11-06): 「원문 수집이 일부 깨져 있는 것도 수정해」, 검증 실패 원문은 「작성자에게 주지 않음」.
설계 검토: codex 4회(REVISE 16·8·6·5건 → 확정), 표는 프로젝트 루트 `plan.md` 2026-11-06 절.

## 무엇이 깨져 있었나 (11/06 실측)

- `pce`·`gdp` URL 이 BEA 상시 랜딩 페이지였다. `pce.txt` 3,259B 가 전부 메뉴 글자인데 「HTTP 200·3,000B 초과」
  규칙을 넘겨 `ok:true` 로 작성자에게 갔다. `gdp.txt` 는 요약 한 문단.
- `existing-home-sales` 의 `nar.realtor/newsroom/existing-home-sales` 는 404 — 그래서 txt 가 한 번도 없었다.
- 미시간은 홈 발췌(약 3KB). FRED 가 한 달 늦어 홈의 월과 자주 어긋난다.
- 실패해도 이전 날의 `<key>.txt` 가 지워지지 않았고, 무발표 날에는 index 도 갱신되지 않았다.
- 작성 지시 「원문 도달 실패면 블록을 뺀다」는 게이트(`_check_releases`: 새 발표마다 블록 필수)와 모순이었다.
- 수집 담당의 `ok:false` 시 WebFetch·WebSearch 폴백은 검증 없는 원문 경로였다.

## 계약

1. **이 실행의 디렉터리만.** `fetch_releases.py` 는 시작하자마자 `data/releases/*.txt` 를 지우고
   `index.json = {report_date, run_id, status: "running", releases: []}` 를 쓴다. 끝나야 `complete`.
   다음 단계 `--sanitize`(`if: always()`, fetch 뒤·commit 전)가 index 가 없거나 `run_id` 가 이 실행이 아니거나
   `complete` 가 아니면 다시 비우고 `status: "aborted"`. 워크플로는 `git add -A data/releases`(삭제까지).
2. **검증한 본문만 저장.** `us/release_verify.py` — 발표마다 기관의 첫 문단 서술문 하나(정체성 문장)를 정규식으로
   찾고, 거기서 기간을 읽어 그 지표의 FRED `ref_period` 와, 값이 있으면 actual 과(단위 배율·반올림 허용) 대조한다.
   표는 해석하지 않는다(당월·전월·수정치가 한 행에 있다). 못 찾으면 실패. 검증은 `to_text(trim=False, max_chars=None)`
   전문에서. 실패 본문은 어디에도 쓰지 않는다(index `note` 에 사유 코드만).
   `checks.primary_checked` = 대표 지표 자신의 값까지 문장에서 확인했는가(4주 평균처럼 서술문이 없는 지표는 False —
   회차 확인이 목적이고 대표 값은 FRED 로 게이트가 본다. codex 4차 지적 하나를 이 이유로 기각).
3. **회차 문서 찾기.** `us/release_resolve.py` — pce·gdp 는 BEA RSS(`apps.bea.gov/rss/rss.xml`) 제목 접두 +
   pubDate 10일 안의 최신 항목, 회차 HTML 다음 PDF. existing-home-sales 는 NAR 통계 페이지의
   「Read the full news release」 링크. 나머지는 고정 「현재 회차」 URL + 검증. 리디렉션은 같은 등록 도메인만.
4. **링크 승인.** index 행 `url` = 실제로 읽고 검증한 최종 문서, `landing_url` = 출발점. `check_sources.py` 는
   `status: complete` index 의 `ok:true` 행 `url` 만 승인. `status` 없는 옛 index 는 `--legacy-releases`
   (과거 판을 그 커밋 데이터로 다시 검사할 때, `review/style_pass.py`)에서만.
5. **원문 없는 날의 해부 블록.** `macro_gate._check_releases` — 블록·대표 실제값·기관명 필수는 그대로.
   대표 지표 행이 없으면 위반(전에는 조용히 건너뛰었다). 원문이 없으면(`raw_release_available` 거짓 —
   index 가 새 스키마인데 complete 아님·행 없음·ok:false, 또는 check_macro 가 본 index 날짜가 세션과 다름)
   구성 항목 규칙 대신 `structured_figures`(대표 actual, 다르면 previous, 대표와 같은 달 components — 소수 1자리에서
   서로 다른 값) 중 `min(3, 개수)` 개가 **숫자 경계를 지켜 서로 다른 자리에** 인용돼야 한다(`_cited_distinct`).
   옛 index·index 없음은 옛 엄격 규칙 — 과거 판 재검사 결과가 바뀌지 않는다.
6. **작성 계약.** 수집 담당은 index 가 오늘·complete·그 행 ok 일 때만 원문을 읽고, 아니면 ⑧절에 「원문 없음」만.
   웹 폴백 없음. 작성자는 원문 없는 날에도 블록을 쓰되 구조 수치만, 원문에서만 나오는 세부는 쓰지 않는다.

## 알려진 한계

- 정체성 정규식은 기관이 첫 문단 문형을 바꾸면 실패한다(그날 원문 없음 — 발행은 계속). 실패 사유가 index `note` 에
  `identity_not_found` 로 남으니 그때 패턴을 고친다.
- 미시간은 FRED 가 한 달 늦은 날 `period_mismatch` 로 원문 없음이 된다(의도).
- BEA 외 발표의 발표일은 따로 보지 않는다 — 기간 일치가 회차를 가른다(같은 분기 GDP 추계 2·3차는 RSS 최신 항목으로).
