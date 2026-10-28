# Jev 국내/해외 뉴스 필터 — 일본·US·KR (2026-10-27/28)

## 무엇을 하나
정규식이 그 시장의 **국내 갈래**로 남긴 뉴스 후보 가운데, TypeSafe Jev(`jev-1.14.0` 고정)가 `foreign` 을
confidence ≥ 0.9 로 답한 것만 **선정 전에 뺀다**. 되살리지 않는다. `foreign_impact`(제목이 그 나라 영향을 명시)는 남긴다.
그날 파일에 이미 있는 기사는 빼지 않는다. 실패(키 없음·인증·HTTP·전송·형식·다른 모델·마감)는 그 행만 정규식,
예상 못 한 예외는 전체 정규식.

| 시장 | 훅 | 대상 갈래 | 위치 | 마감 |
|---|---|---|---|---|
| 일본 일간 | `fetch_japan_news.collect_daily` | macro·policy·industry·market (retag 뒤) | preselect 전 | 60초 |
| US | `fetch_news.main` | economy·macro·politics | categorize 뒤, **dedupe 전** | 30초 |
| KR | `fetch_kr_news.main` | macro·policy·market·industry (주요뉴스 행만) | **dedupe 전** | 30초 |

코드: `scripts/common/region_filter.py`(필터), `region_labels.py`(라벨 정의·Jev 요청·응답 검증), `jev_client.py`(전송).
감사: 각 payload 최상위 `region_filter` — `dropped`, `candidates`(대상 후보 전부의 guid·제목·갈래·라벨·conf·exempt),
`asked`·`answered`·`late`·`stopped`·`errors`·`seconds`. 게이트·검토 러너는 `items` 만 읽는다.
- `asked` = 마감 전에 **보낼 차례를 잡은** 제목 수(전송 시작과 같지 않다 — 전송은 자물쇠 밖이라 마감 직후에 시작될 수 있다),
  `answered` = 마감 전에 기록된 판정, `late` = 마감 뒤에 와서 버린 답.
- `candidates[].status`: `judged` · `http:…`/`net:…`/`schema:…`(그 행 실패) · `model:mismatch` · `no_answer`(차례를 잡았으나 마감까지
  답이 기록되지 않음) · `unasked`(마감 전에 차례가 오지 않음) · `exempt` · `no_key` · `rolled_back`.

## 근거
- 일본: 10/22-10/27 Yahoo 목록 고유 제목 1,220 → 층화 359, 정답 = Claude·codex 블라인드 합의 347. 정규식이 국내로 남긴
  199건 중 해외 21건 → 이 규칙으로 6건, 잘못 뺀 국내 0건. 0.8·0.7 로 낮추면 국내 1건을 잘못 뺀다. 파일
  `report/_workspace/region_eval_2026-10-27/`, 실행 `region-shadow.yml -f datadir=japan/data/eval`.
- **US·KR 은 평가 없이 켰다**(사용자 2026-10-28 「지금 바꾸고 나중에 측정」). 나중 측정은 `candidates` 에서 표본을 뽑아 일본과
  같은 절차(블라인드 정답)로 한다. Jev 문서: CJK 는 영어보다 정확도가 낮다.

## 결정
- US 는 경제·매크로·정치만 — AI·산업은 해외 기업(TSMC·삼성)이 미국 투자자에게 필요한 기사다(사용자 선택).
- 독자 범위(설계 검토 #6): US 정의는 미국의 대외 정책(관세·제재)을 국내로, 미국을 말하지 않는 해외 중앙은행·정부는 해외로 —
  「Bank of Canada hikes rates」 는 US 매크로에서 빠지고, 글로벌 갈래는 지역·정책 조건이 따로라 그것을 되살리지 않는다.
  KR 정의는 한국 투자자의 해외 투자(서학개미)를 국내로 친다.
- 일본 정의·질문 문자열은 섀도·평가와 바이트 동일 — `japan/tests/test_region_shadow.py` 가 설정 지문·요청 해시를 고정값으로 지킨다.
- **마감은 행 단위 실패다**: 마감 **전에 기록된** 판정만 적용하고 나머지는 정규식(감사 `no_answer`·`unasked`, 늦은 답은 `late`). 마감에 전체를
  되돌리면 가장 느린 날 맞게 뺀 것까지 버린다 — 그래서 「마감이면 오늘과 완전히 같다」는 보장은 하지 않는다(US·KR 구현 검토 #2).
- US·KR 마감 30초: 수집 실측 US 55-470초, KR 306-1062초, 루틴 대기 `timeout 900`. 최신 순으로 물어 못 물은 행은 순위가 낮은 쪽.

## 검토 이력
codex 설계 검토(일본 REVISE 6·3, US·KR REVISE 심각 3·높음 1·중간 2), 구현 검토·재검토 여러 차례 — 표는 `report/plan.md`
2026-10-27·28 절.
