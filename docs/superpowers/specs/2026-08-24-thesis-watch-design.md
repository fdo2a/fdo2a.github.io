# 종목 thesis 감시 파이프라인 설계

작성 2026-08-24 · 상태: 구현

## 문제

US·KR 브리프는 **시장 전체**를 매일 정리한다. 개별 종목을 계속 들고 갈 때 필요한 건 다른 물건이다 —
"오늘 시장이 어땠나"가 아니라 **"내가 이 종목을 처음 본 이유가 아직 유효한가"**다.

뉴스는 매일 나온다. 대부분은 thesis와 무관하다. 무관한 뉴스를 요약해서 보내면 신호가 죽고,
중요한 뉴스를 놓치면 감시가 무의미하다. 그래서 이 파이프라인이 하는 일은 요약이 아니라 **분류**다:
들어온 사건이 thesis를 **강화하는지 · 약화하는지 · 깨는지**를 판정하고, **판정이 바뀔 때만** 말한다.

첫 대상은 메모리 3사 — 삼성전자(005930.KS) · SK하이닉스(000660.KS) · Micron(MU).

## 기존 두 파이프라인과 결정적으로 다른 점

US·KR 브리프는 **매일 반드시 발행**한다. 이 루틴은 **대부분의 날에 아무것도 하지 않아야 한다.**

이건 에이전트에게 어려운 요구다. "매일 실행하되 보통은 아무것도 하지 마"라고 시키면
뭐라도 만들어내려는 경향이 생긴다. US 브리프 §8이 정확히 이 실패를 겪었다 — 매일 그날 표에서
국면을 새로 그리다가 «승계되는 판단»으로 바꿔야 했다.

따라서 이 설계의 중심은 예쁜 페이지가 아니라 **침묵을 강제하는 문지기**다.
프롬프트로만 규칙을 두면 언젠가 무너진다. 상태 파일과 게이트로 기계화한다.

## 구조

```
Actions 17:40 KST  →  thesis/data/{watch.json, history.jsonl}  (결정론적 수치)
                                    ↓
클라우드 루틴 18:00 KST  ─ 수치 트리거 판정 (watch ↔ state 대조, 기계적)
                        └ 사건 트리거 탐색 (WebSearch, 1차 출처 확인)
                                    ↓
                        트리거 없음 → 종료. 파일 무수정, 알림 없음.
                        트리거 있음 → 페이지 부분 갱신 + state 승계 + 게이트 + push + 알림
```

실행 시각 18:00 KST(09:00 UTC)를 고른 이유: 이 시점이면 삼성·하이닉스의 **당일** 종가·뉴스와
Micron의 **전 거래일** 종가·뉴스가 모두 확보된다. Actions는 그 20분 전(08:40 UTC) —
KR 수집(08:00/08:30 UTC) 이후, 루틴 이전.

클라우드 루틴 환경은 금융 호스트(Yahoo/FRED)를 403 차단하므로 시세 수집은 Actions로 이관한다
(2026-07-15 US 브리프, 2026-07-22 KR 브리프와 같은 이유).

## 데이터 계약

### `thesis/data/watch.json` — 오늘의 결정론적 수치

```json
{
  "as_of": "2026-08-24", "complete": true, "missing": [],
  "tickers": {
    "005930.KS": {
      "name": "삼성전자", "currency": "KRW",
      "price": 281500, "price_date": "2026-08-21",
      "chg_20d_pct": -8.4, "pct_from_52w_high": -24.8, "market_cap": 1848487620640768,
      "eps_fy0": 48526.38, "eps_fy1": 67312.55,
      "eps_fy1_low": 24323.0, "eps_fy1_high": 93462.0, "eps_fy1_analysts": 35,
      "pe_fy1": 4.18, "pb": 3.41, "bvps": 82300.0,
      "next_earnings_date": "2026-10-28"
    }
  }
}
```

`complete:false`면 루틴은 수치 트리거를 건너뛰고 사건 트리거만 본다. 없는 수치로 판정하지 않는다.

### `thesis/data/history.jsonl` — 매일 한 줄 append

**이 파일이 설계의 핵심이다.** 감시의 1순위 지표는 *컨센서스 FY1 EPS가 어느 쪽으로 좁혀지는가*인데,
yfinance는 30일 전 컨센을 주지 않는다. 우리가 직접 쌓아야 `eps_fy1_30d_change_pct`와
추정치 분산(high/low 비율)의 변화를 잴 수 있다. 하루 빠지면 그만큼 눈이 먼다.

한 줄 = `{"date": "...", "tickers": {티커: {eps_fy1, eps_fy1_low, eps_fy1_high, price, pb}}}`.
30일 전 조회는 **가장 가까운 과거 영업일**로 폴백하며, 20일치 미만이면 해당 트리거를 비활성화한다.

### `thesis/data/thesis_state.json` — 승계되는 책

`stance.json`과 같은 역할. 어제의 판단이 오늘의 출발점이다.

```json
{
  "updated": "2026-08-24",
  "tickers": {
    "005930.KS": {
      "grade": "홀딩 강화", "grade_since": "2026-08-24",
      "conviction": "base",
      "last_seen": {"eps_fy1": 67312.55, "pb": 3.41, "price": 281500,
                    "hbm4_status": "3Q 3배 가이던스 제시, 미검증",
                    "lta_coverage": "캐파 60~70% 목표, CSP 5곳"},
      "open_questions": ["3Q 실적에서 HBM4 매출 3배 달성 여부"],
      "fair_value": {"bull": 598990, "base": 300462, "bear": 128607,
                     "weighted": 347057, "band1": 277645, "band2": 235999,
                     "computed": "2026-08-24"}
    }
  }
}
```

`last_seen`이 있어야 **"오늘 값이 어제와 같으면 등급이 산술적으로 못 움직인다"**를 기계가 안다.

## 밸류에이션

피크 이익 위에서 P/E는 신호가 아니다. 두 방법을 독립적으로 계산해 평균한다 —
두 방법이 비슷한 값에 닿는지가 신뢰도의 척도다.

- **A 정규화이익법**: FY1 컨센 EPS × 정규화율 × 정규화 P/E
- **B 자산법**: 2년 뒤 예상 BPS × 시나리오별 P/B

| 시나리오 | 확률 | 정규화율 | 근거 |
|---|---|---|---|
| Bull 구조적 재평가 | 30% | FY1의 80% | LTA·take-or-pay가 하방 지지, 2028년까지 타이트 |
| Base 연착륙 | 45% | 48% | 2027 피크 후 2028~29 정상화 |
| Bear 사이클 회귀 | 25% | 25% | 2028 신규 캐파 도착 → 공급과잉 |

배수는 시장별 차등(한국에 지배구조·순환주 디스카운트). 관심 밴드는 확률가중 가치의 −20%(1차)·−32%(2차)로,
Bear 손실 크기(−54~−69%)와 확률(25%)을 감안한 안전마진이다.

**가정이 결과를 지배한다는 사실을 페이지에 명시한다.** Bull 확률을 50%로 올리면 세 종목 모두
현재가가 저평가로 바뀐다. 이건 모델의 결함이 아니라 이 사이클의 실제 불확실성이며, 숨기면 안 된다.

## 트리거

### 수치 트리거 — `scripts/thesis/triggers.py`, 순수 함수

| 키 | 조건 | 산출 |
|---|---|---|
| `consensus_swing` | FY1 EPS 30일 변화 ≥ ±20% | 밸류 재계산 + 알림 |
| `consensus_floor` | FY1 EPS avg가 low 대비 +15% 이내 | kill 후보 |
| `band_entry` | 주가가 band1/band2 하향 돌파 | 정보 알림 |
| `bear_proximity` | 주가가 bear FV ±10% 이내 | 주의 |
| `dispersion_widening` | high/low 비율 30일 대비 +30% | 주의 |

### 사건 트리거 — 루틴이 WebSearch로 탐색

신규 고객명 · 대형 주문/production order · 양산 일정 변경 · 가이던스 상하향 · 마진 개선/악화 ·
현금흐름 악화 · 희석(유증·CB·워런트) · 파트너십의 실제 매출 전환 · 경영진/거버넌스/자본배분 ·
실적에서 thesis 이탈 · 밸류 재계산이 필요한 수주 변화.

## 문지기 규칙

1. 수치 트리거가 하나도 안 걸리고 사건이 «확정 사실»로 확인되지 않으면 → **종료. 파일 무수정, 알림 없음.**
2. 사건은 **1차 출처**(공시·IR·실적자료·고객사 발표)로 확인돼야 등급을 움직인다.
   언론 단독·익명 소식통은 «추론»으로만 분류되고 **단독으로는 등급을 못 바꾼다.**
3. 등급 이동은 **하루 한 단계, 대각선 금지**(홀딩 강화 → kill 직행 불가).
4. **kill은 가격 지표 하나 + 계약/점유율 지표 하나가 함께 깨질 때만.** 하나만이면 «비중 조절 검토»까지.
5. **악화는 즉시, 회복은 3영업일 잠금**(stance.json의 비대칭과 동일).
6. 한 티커의 계약·가격 뉴스는 **나머지 둘의 state에도 반영**한다 — 같은 사이클을 공유하므로.

등급 통제 어휘 4개(자유 문구 금지): `홀딩 강화` · `주의` · `비중 조절 검토` · `kill condition`

## 페이지

```
/thesis/                인덱스 — 3종목 카드(등급·현재가·가중가치 대비) + 통합 변경 피드
/thesis/samsung.html    상설 기준표 (덮어쓰기 갱신)
/thesis/skhynix.html
/thesis/micron.html
/thesis/index.json      종목별 메타 (날짜별이 아니라 posts.json과 스키마가 다름)
```

디자인은 **Toss 토큰 유지**(블로그 일관성). 등급 배지의 semantic color만 추가 — 장식이 아니라 정보다.

네비게이션은 US↔KR 2방향 스위치를 **3방향 pill 그룹**으로 교체.
건드리는 파일은 `index.html`·`kr/index.html`·`thesis/index.html` 셋뿐이며 **기존 포스트는 무수정**.

### 기계 주소 마커

루틴이 매일 페이지를 고치므로 블록마다 마커를 심어 **부분 갱신**을 가능하게 한다.
통째로 다시 쓰면 매번 수치가 미세하게 흔들릴 위험이 있다(과거 FX 방향·유가 등락률 오류 전례).

```html
<article data-ticker="005930.KS" data-grade="홀딩 강화" data-since="2026-08-24">
  <ol data-block="changelog"><li data-date="..." data-signal="...">…</li></ol>
  <section data-block="thesis">…</section>
  <section data-block="valuation" data-computed="2026-08-24">…</section>
</article>
```

변경 이력은 페이지 상단에 **누적**된다. 알림 7단계가 그대로 한 항목이 되므로
별도 로그 포스트 없이 "언제 무엇이 왜 바뀌었나"가 한 페이지에서 읽힌다.

## 알림 형식 (7단계)

1. 티커 / 이벤트 제목 · 2. 확정 사실(출처 명시) · 3. 추론(사실과 분리) ·
4. Bullish/Bearish/Neutral · 5. 기존 thesis 대비 변화 · 6. 신호 등급(통제 어휘 4개) ·
7. 다음에 확인할 것

## 발행 게이트 — `scripts/check_thesis.py`

| 검사 | 실패 조건 |
|---|---|
| 등급 어휘 | 통제 어휘 4개 외 문구 |
| 등급 규율 | 하루 2단계 · 대각선 · 회복 잠금 위반 |
| kill 조건 | 지표 하나만 깨졌는데 kill 부여 |
| 알림 형식 | 변경 이력 항목에 7요소 누락 |
| 사실/추론 분리 | 확정 사실에 출처 미표기 |
| 수치 불변 | 안 건드린 블록의 수치 토큰이 HEAD와 불일치 (`post_check.token_diff`) |
| state 정합 | `thesis_state.json` 등급 ↔ 페이지 `data-grade` 불일치 |
| 금칙어 | `[확인필요]`·TODO·TBD, buy-side (`macro_gate.BANNED_LABELS`) |
| **침묵** | **트리거가 없는데 파일이 수정됨** |

마지막 «침묵» 검사가 "변화 없으면 아무것도 하지 마"를 강제하는 최종 장치다.

## 지금 만들지 않는 것 (YAGNI)

- 종목 추가용 일반화 템플릿 엔진 — 4번째 종목이 생길 때 일반화하는 게 싸다
- 알림 히스토리 별도 저장소 — 페이지 변경 이력과 git이 이미 그 역할
- 차트 — 감시에 필요한 건 숫자와 판정이지 그림이 아니다

## 파일

```
.github/workflows/collect-thesis-data.yml
scripts/collect_thesis_data.py          수집 진입점
scripts/check_thesis.py                 게이트 진입점
scripts/thesis/{__init__,watch,history,valuation,triggers,state,gate}.py
scripts/thesis/tests/
.claude/THESIS_ORCHESTRATOR.md          루틴 파이프라인
thesis/{index.html,samsung.html,skhynix.html,micron.html,index.json}
thesis/data/{watch.json,history.jsonl,thesis_state.json}
```

트리거는 평일 09:00 UTC. 부트스트랩만 트리거에 두고 파이프라인은 레포 파일에 둔다(기존 두 개와 동일).
