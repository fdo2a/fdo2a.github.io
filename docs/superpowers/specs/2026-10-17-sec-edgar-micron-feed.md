# thesis 감시 — SEC EDGAR 공시 피드(Micron) (2026-10-17)

대상 `scripts/thesis/edgar.py`, `scripts/collect_thesis_data.py`, `scripts/thesis/quiet.py`,
`.github/workflows/collect-thesis-data.yml`.

## 왜

`quiet.py` 는 KR 두 종목의 공시를 `disclosures.json`(OpenDART)으로 매일 확인했지만 Micron 은
피드가 없어 금요일 전체 점검만이 Micron 사건을 잡았다. 2026-09-24 spec 은 「Micron IR 피드와 SEC
submissions API 는 이 클라이언트를 403 으로 막았다」고 기록했다.

## 실측 (2026-10-17)

GitHub-hosted 러너에서 임시 브랜치의 push 워크플로로 1회 측정(브랜치는 삭제).

| 호스트 | 선언형 UA (`fdo2a-report thesis-watch`) | 이메일 형태 UA | urllib 기본 UA |
|---|---|---|---|
| `data.sec.gov/submissions` | 200 | 200 | **403** |
| `efts.sec.gov` 전문 검색 | 200 | 200 | 403 |
| `www.sec.gov` (Archives·browse-edgar) | **403** | 200 | 403 |

로컬에서는 UA 에 `github`·`users.noreply.github.com`·URL 이 들어가면 403 이었다(SEC WAF 휴리스틱).
**9/24 의 403 은 UA 를 밝히지 않은 탓일 가능성이 높다.** `investors.micron.com` 은 어떤 경로·UA 로도
여전히 403(WAF)이다.

## 결정

1. **data.sec.gov submissions JSON 하나만 쓴다.** 종목당 하루 1회 요청 — SEC 한도(초당 10회)와 무관하다.
   403 은 재시도하지 않는다(WAF 차단은 일시적이지 않다). 5xx·429·네트워크 오류만 3회.
2. **UA**: 환경변수 `SEC_USER_AGENT`(워크플로가 저장소 *변수* `vars.SEC_USER_AGENT` 를 넘긴다 — 연락처가
   공개 레포에 남지 않는다), 비어 있으면 `fdo2a-report thesis-watch`. SEC 정책은 연락처 이메일을
   요구하므로 기본값은 동작은 하지만 정책상 완전하지 않다 — 사용자가 변수를 설정하면 그쪽을 쓴다.
3. **창은 SEC `filingDate`(미 동부 영업일)로, 직전 수집일 전날부터 오늘까지**다 — DART 와 같은 하루 겹침.
   처음 설계는 접수 시각 커서였으나 설계 검토(Claude, codex 는 사용자 지시로 생략)에서 둘 다 깨졌다.
   - `acceptanceDateTime` 의 `Z` 는 UTC 가 아니다. EDGAR 색인 페이지와 대조하면 **ET 벽시계 + 오프셋×2**다:
     2026-09-30 실적 8-K 는 JSON `2026-10-01T00:02:22Z` ↔ 색인 16:02:22 EDT(+8h), 2025-12-17 실적 8-K 는
     `2025-12-18T02:03:26Z` ↔ 16:03:26 EST(+10h). UTC 로 읽으면 장 마감 뒤 공시가 다음 세션으로 넘어간다.
     `accepted_et()` 가 되돌려 `accepted_et`(ET 문자열)로 남긴다.
   - 커서는 루틴이 한 번 읽기 전에 수집이 두 번 돌면(수동 실행, 10/14·10/15 실측) 첫 실행이 본 공시를
     덮어써 잃는다. 날짜 창의 하루 겹침은 같은 공시를 이틀 보고하는 대신 잃지 않는다.
4. **두 깃발.** `confirmed` 는 kill 축을 공급할 수 있어 DART 축 규율 그대로 좁게(넓어지는 것이 유일한 위험한
   실패 방향 — 2026-09-21 DART spec). `notable` 은 색인만으로는 가를 수 없지만 건너뛰면 안 되는 공시다 —
   `quiet.py` 가 `THESIS_CHECK` 로 리서치를 부르고, 축은 주지 않는다.

   | 공시 | 처리 |
   |---|---|
   | 8-K 2.02(실적) | `confirmed`·`contract` — kill 축. DART 영업(잠정)실적과 같은 자리 |
   | 8-K 2.01·2.03·2.04·3.02·3.03 | `confirmed`·`capital` |
   | 8-K 2.05·2.06·4.01·4.02, 10-K·10-Q | `confirmed`·`financials` |
   | SCHEDULE 13D | `confirmed`·`ownership` |
   | 8-K 1.01·1.02 | `notable` — Micron 의 1.01 은 사채·신용계약이 많다. kill 축을 주면 사채 발행 + 주가 하락이 kill 을 연다 |
   | 8-K 1.05·5.01·5.02 | `notable` — 사이버 사고, 지배권·임원 변동(DART 도 임원 변동은 확정하지 않는다) |
   | 8-K 7.01·8.01 | `notable` — Micron 은 2025-08-11 가이던스 수정, 2023-05-22 중국 CAC 판정, 2024·2025 CHIPS 를 여기 실었다 |
   | 8-K/A, NT 10-K/Q | `notable` — 실적 정정·정기보고서 지연 |

   여러 항목이 실린 8-K 는 가장 센 축(contract > capital > financials > ownership)을 갖는다.
   `/A` 정정은 `confirmed` 가 되지 않는다(DART 기재정정과 같은 이유). Form 3·4·5·144, 13G, S-8, 424B·FWP,
   위임장, 8-K 5.03·5.07·9.01 단독 등은 기록만 한다.
5. **사건 스키마 = DART 사건 키**(`rcept_no`·`date`·`title`·`corp`·`filer`·`url`·`axis`·`kind`·
   `correction`·`confirmed`) + SEC 전용 `notable`·`form`·`items`·`accepted_et`. `rcept_no` 는 접수번호,
   `date` 는 filingDate, `url` 은 EDGAR 원문, `filer` 는 `None`(submissions 가 제출자를 밝히지 않는다).
   종목 행은 `{cik, events, axes, confirmed_count, notable_count}`.
6. **금요일 전체 점검은 남긴다.** 고객사(NVIDIA·AMD) 발표와 공시 밖 Micron 보도자료(제품·고객 발표,
   IR 사이트 403)는 여전히 피드가 없다. 바뀐 것은 Micron **공시**가 매일 잡힌다는 것이다.

## 경계

- `quiet.FILING_TICKERS` 에 있는 종목 행이 `disclosures.json` 에 없으면 조용하지 않다. 목록은 파일이 아니라
  `quiet.py` 상수다 — 행을 빠뜨린 수집기가 스스로를 보증하지 못하게. 테스트가 수집기 상수와 대조한다.
- 비-코어. SEC 실패는 `missing` 에 `MU:…` 로 남고 그날은 `THESIS_CHECK` 가 된다. 수집을 막지 않는다.
- DART 키가 없어(`pending`) DART 가 일찍 돌아와도 SEC 는 수집한다(`edgar.merge`).
- SEC 가 러너 IP 대역을 막기 시작하면 매일이 `THESIS_CHECK` 가 된다 — 사건을 놓치는 쪽이 아니라
  리서치 한 번 비용 쪽으로 실패한다. `missing` 에 `MU:SEC 403` 으로 보인다.

## 검증

- `scripts/thesis/tests/test_edgar.py` — 분류 표(confirmed·notable·기록만), 다중 항목 우선순위, 정정,
  접수 시각 보정(여름·겨울 실측값), 창 경계·하루 두 번 수집, CIK 대조, 깨진 응답, UA, 403 무재시도, 병합.
  `test_quiet.py` — notable 이 조용함을 깨고 Form 4 는 깨지 않음, 종목 행 누락, FILING_TICKERS ↔ 수집기 상수.
- 2026-10-17 실제 MU submissions 로 30일 창: 8-K 2.02(9/30 실적)·10-K(10/9) 2건 confirmed, Form 4·144 는
  기록만.

## 남은 것

- 공시 밖 Micron 보도자료(investors.micron.com 403)·고객사 발표 — 금요일 전체 점검.
- `SEC_USER_AGENT` 저장소 변수(연락처 이메일) 설정은 사용자 몫.
- codex 설계·구현 검토 — 사용자 지시(2026-10-17 「codex 스킵해」)로 생략. Claude 서브에이전트가 설계를 검토했다
  (치명 2·중대 4·경미 8 — 접수 시각·커서·7.01/8.01·1.01 축·행 누락 가드를 반영).
