# US 모닝브리프 — 멀티에셋 스탠스 지속성 설계

작성일: 2026-08-17
대상 섹션: US 모닝브리프 §8 «멀티에셋 매니저 전략»

## 문제

§8의 자산군별 «판단»이 매일 실질적으로 뒤집힌다. 7/24~8/14 발행본에서 주식 판단은
`비중축소·선별 → 선별적 비중조정 → 비중축소 → 선별적 리스크온 → 리스크온 유지 → 대형
성장주 비중 축소`로 오갔고, 채권은 `단기물 숏 듀레이션 → 단기 중립 → 벨리~단기 중심 →
숏~중립 → 벨리 중심 중립`을 반복했다. 7/29 「비중축소」에서 7/30 「선별적 리스크온」으로의
전환은 마이크론 하루 +18% 급등에 책 전체가 뒤집힌 사례다.

원인은 둘이다.

1. **파이프라인에 전일 기억이 없다.** `brief-report-writer`는 `market_data.json` /
   `intraday.json` / `research_notes.md`만 읽는다. 전일 리포트를 참조하는 경로가 없어
   매일 그날 등락에서 전략을 처음부터 재도출한다.
2. **판단 라벨이 자유 텍스트다.** 통제 어휘가 없어 같은 스탠스가 매일 다른 문구로 나오고,
   독자는 스탠스가 바뀐 것인지 표현만 바뀐 것인지 구분할 수 없다.

## 목표

- 스탠스가 **포지션**으로 읽힐 것 — 하루 등락이 아니라 사전 선언한 트리거가 충족될 때만 이동
- 전일 대비 변화가 **한눈에 보일 것** — 고정 어휘와 유지 일수
- 과거 판단이 **검증될 것** — 어제 건 트리거의 오늘 판정 결과를 본문에 노출

비목표: 수익률 백테스트, KR 마감브리프 반영(추후 별도 회차).

## 스탠스 시계

**2~6주 스윙.** 모든 등급은 이 시계의 포지셔닝이며, 논거도 이 시계에서 서술한다.
당일 가격은 논거의 보조일 뿐 근거의 본체가 될 수 없다.

## 자산군 축과 통제 어휘

등급은 정수이며 `label`은 아래 표에서만 고른다. 즉흥 문구 금지.

| 키 | 자산군 | 축 | −2 | −1 | 0 | +1 | +2 |
|---|---|---|---|---|---|---|---|
| `equities` | 주식 | 절대비중 | 비중축소 | 소폭축소 | 중립 | 소폭확대 | 비중확대 |
| `bonds` | 채권 | 듀레이션 | 숏 듀레이션 | 숏 바이어스 | 중립 듀레이션 | 롱 바이어스 | 롱 듀레이션 |
| `fx` | FX | 달러 방향 | 달러 숏 | 달러 소폭 숏 | 달러 중립 | 달러 소폭 롱 | 달러 롱 |
| `energy` | 원자재·에너지 | 절대비중 | 비중축소 | 소폭축소 | 중립 | 소폭확대 | 비중확대 |
| `metals` | 원자재·귀금속 | 절대비중 | (동일) | | | | |
| `memory` | 메모리 | **주식 대비 상대비중** | — | UW | 중립 | OW | — |
| `ai_infra` | AI 인프라 | **주식 대비 상대비중** | — | UW | 중립 | OW | — |

부가 필드(등급과 별개, 자유 서술 허용):

- `bonds.curve` — `플래트너` / `커브 중립` / `스티프너` / `벨리 OW` 중 하나 (역시 통제 어휘)
- `fx.pair_note` — 주목 페어 한 줄
- `tilt` — 모든 자산군 공통. 「대형 성장주 축소, 에너지·소형주 확대」 같은 섹터 틸트를
  자유 서술로 담는다. 등급은 통제하되 뉘앙스는 살리기 위한 칸이다.

표는 6행을 유지한다 — 원자재는 `energy`/`metals` 두 서브등급을 한 칸에 병기한다
(관측상 유가와 금이 반대로 가는 날이 잦아 단일 등급으로는 담기지 않는다).

## 이동 규율

방향은 **0(중립) 기준**으로 정의한다. 자산군마다 리스크 방향이 다르다는 문제를 이 정의가
없앤다 — 중립은 베팅이 없는 상태이므로, 중립에서 멀어지는 것이 곧 베팅 확대다.

- **증대** (`|grade|` 증가): 사전 선언한 `increase` 트리거가 MET일 때만 가능
- **축소** (`|grade|` 감소, 중립 방향): 트리거 없이도 항상 허용 — 단 사유를 본문에 명시
- **1일 1단계**: 등급은 하루에 한 칸만 이동한다. 부호 전환은 반드시 0을 경유하므로
  −1 → +1 같은 하루 뒤집기가 구조적으로 불가능해진다
- **증대 잠금 3영업일**: 같은 자산군에서 마지막 등급 변경 후 3영업일이 지나야 증대할 수 있다.
  축소에는 잠금이 걸리지 않는다

비대칭이 의도적이다. 실제 운용에서도 손절은 즉시, 재진입은 신중하다.

## 데이터 흐름

```
[GitHub Actions 21:30 UTC]
  collect_market_data.py
    ├─ market_data.json (기존)
    └─ stance_metrics.json (신규)      ← 트리거 판정용 지표 사전 계산
  eval_stance_triggers.py
    stance.json (전일, 레포에 커밋돼 있음) + stance_metrics.json
    └─ stance_eval.json (신규)          ← 트리거별 MET / NOT_MET / UNKNOWN / MANUAL

[클라우드 루틴 23:00 UTC]
  brief-report-writer
    읽기: market_data.json, intraday.json, research_notes.md,
          stance.json, stance_eval.json
    쓰기: morning_brief_[date].html
          stance.json (갱신 — 다음날 입력)
```

전일 루틴이 남긴 `stance.json`은 다음날 Actions가 도는 시점에 이미 레포에 있다. 순서는
현재 스케줄로 이미 맞다.

## `data/stance.json` 스키마

```json
{
  "report_date": "2026-08-14",
  "horizon": "2-6주",
  "assets": {
    "equities": {
      "grade": 0,
      "label": "중립",
      "tilt": "대형 성장주 축소, 에너지·소형주·가치주 선별 확대",
      "since": "2026-08-14",
      "thesis": "AI 파이낸싱 우려로 대형 기술주 심리가 흔들리는 사이 소형주·가치주로 자금 이동",
      "triggers": {
        "increase": [
          {"kind": "metric", "metric": "spx_vs_20dma_pct", "op": ">", "value": 2.0,
           "desc": "S&P 500이 20DMA를 2% 이상 상회"}
        ],
        "decrease": [
          {"kind": "metric", "metric": "vix_close", "op": ">", "value": 22,
           "desc": "VIX 22 상회"},
          {"kind": "event", "desc": "이란 협상 결렬 공식화"}
        ]
      }
    }
  },
  "history": [
    {"date": "2026-08-14", "asset": "equities", "from": 1, "to": 0,
     "reason": "브로드컴발 AI 파이낸싱 우려로 대형주 심리 훼손"}
  ]
}
```

- `since` — 현재 등급에 진입한 날짜. 유지 일수는 `since`부터의 영업일 수로 파생한다
  (저장하지 않는다 — 파생 가능한 값을 이중 보관하면 어긋난다)
- `history` — 전체 자산군 공통 이동 로그, 최근 30건만 유지
- 지원 연산자: `>`, `>=`, `<`, `<=`

## `data/stance_metrics.json` — 트리거 판정용 지표

`collect_market_data.py`가 이미 받는 가격 히스토리로 계산한다. 신규 티커는 `^VIX` 하나.

| 그룹 | 지표 |
|---|---|
| 주식 | `spx_vs_20dma_pct`, `spx_vs_50dma_pct`, `ndx_vs_20dma_pct`, `rut_vs_20dma_pct`, `spx_pct_5d`, `spx_pct_20d`, `growth_value_spread_5d`, `vix_close`, `vix_chg_5d` |
| breadth | `sectors_up_1d`, `sectors_up_1m` (11종 중 상승 개수) |
| 채권 | `ust2y`, `ust5y`, `ust10y`, `ust30y`, `spread_2s10s_bp`, `spread_5s30s_bp`, 각 만기 `_chg_5d_bp` |
| FX | `dxy_close`, `dxy_pct_5d`, `dxy_pct_20d`, `usdjpy_close`, `usdjpy_pct_5d`, `usdkrw_close`, `usdkrw_pct_5d`, `eurusd_pct_5d` |
| 원자재 | `wti_close`, `wti_pct_5d`, `wti_pct_20d`, `brent_close`, `gold_close`, `gold_pct_5d`, `gold_pct_20d` |
| 테마 | `memory_rel_5d`, `memory_rel_20d`, `ai_infra_rel_5d`, `ai_infra_rel_20d` — 미국 상장 동일가중 바스켓의 S&P 500 대비 초과수익(%p). 메모리 = MU·WDC·STX, AI 인프라 = MRVL·COHR·LITE·GEV·VRT. 삼성전자·SK하이닉스는 세션·통화가 달라 제외 |

## `data/stance_eval.json` — 판정 결과

```json
{
  "report_date": "2026-08-17",
  "stance_date": "2026-08-14",
  "stale": false,
  "bootstrap": false,
  "assets": {
    "equities": {
      "grade": 0, "label": "중립", "days_held": 1,
      "increase": [{"metric": "spx_vs_20dma_pct", "op": ">", "value": 2.0,
                    "actual": 1.24, "status": "NOT_MET", "desc": "..."}],
      "decrease": [{"kind": "event", "status": "MANUAL", "desc": "이란 협상 결렬 공식화"}],
      "can_increase": false,
      "increase_block": "no_trigger_met",
      "can_decrease": true,
      "allowed_grades": [-1, 0]
    }
  }
}
```

`allowed_grades`가 계약의 핵심이다 — writer는 이 목록 밖의 등급을 쓸 수 없다.

판정 상태:

- `MET` / `NOT_MET` — 수치형 트리거를 지표와 대조한 결과
- `UNKNOWN` — 지표가 결측이라 판정 불가. **증대 근거로 쓸 수 없다**(안전한 기본값은 유지)
- `MANUAL` — 이벤트형. writer가 `research_notes.md`의 구체적 인용을 근거로 판정한다.
  이벤트형은 `increase` 쪽에도 놓을 수 있으나, 인용 없이 충족 선언하면 발행 게이트가 잡는다

`increase_block` 값: `no_trigger_met` / `lock_3bd` / `at_max` / `null`

## 이상 상황 처리

| 상황 | 처리 |
|---|---|
| `stance.json` 없음 | `bootstrap: true`. writer가 초기 스탠스를 설정하고 유지 1일차로 기록. 이날은 이동 규율 미적용 |
| `stance.json.report_date`가 직전 거래일이 아님 | `stale: true`. 등급은 그대로 승계하되 본문에 공백 기간을 밝히고, 그날은 1단계 이동 제한을 유지한 채 잠금은 해제 |
| 지표 결측 | 해당 트리거 `UNKNOWN`. 증대 불가, 축소는 가능 |
| `stance_eval.json` 없음(수집 실패) | writer가 `stance.json`만 읽어 **전 자산군 등급 동결**. 새 트리거만 갱신 |

## §8 섹션 재구성

1. **전일 스탠스 리뷰** — 어제 건 트리거와 오늘 판정 결과를 실제 수치와 함께 노출하고,
   그래서 유지인지 이동인지 밝힌다. 2~3문단
2. **스탠스 표** — `자산군 | 등급 | 유지 | 전일대비 | 논거 | 다음 분기점`
   - 등급: 통제 어휘 라벨 (+ `tilt`를 작은 글씨로 병기)
   - 유지: `N영업일`
   - 전일대비: `유지` / `▲1단계` / `▼1단계`
   - 논거: 2~6주 시계에서 왜 이 포지션인가. 당일 등락 나열 금지
   - 다음 분기점: 다음날 판정할 트리거를 수치로. 「추이 확인 필요」 같은 무판정 문구 금지
3. **리스크 시나리오 2~3개** (기존 유지)

## 발행 게이트 추가 항목

1. §8 등급 라벨 6행이 모두 통제 어휘표에 있는가
2. 각 행 등급이 `stance_eval.json`의 `allowed_grades`에 드는가
3. 등급이 이동한 행마다 MET 트리거의 실제 수치 인용 또는(이벤트형이면) `research_notes.md`
   출처 인용이 본문에 있는가
4. 6행 모두 유지 일수와 다음 분기점이 채워졌는가
5. `stance.json`이 오늘 `report_date`로 새로 쓰였고, 이동한 행이 `history`에 기록됐는가

## 신규·변경 파일

| 파일 | 성격 |
|---|---|
| `scripts/us/__init__.py` | 신규 |
| `scripts/us/stance.py` | 신규 — 통제 어휘, 이동 규율, 트리거 판정(순수 함수) |
| `scripts/us/stance_metrics.py` | 신규 — 지표 계산 |
| `scripts/us/tests/test_stance.py` | 신규 — TDD |
| `scripts/eval_stance_triggers.py` | 신규 — CLI 진입점 |
| `scripts/collect_market_data.py` | 변경 — `^VIX` 추가, `stance_metrics.json` 산출 |
| `.github/workflows/collect-market-data.yml` | 변경 — eval 스텝, 커밋 대상 확장 |
| `.claude/agents/brief-report-writer.md` | 변경 — §8 재정의, 어휘표, 이동 규율 |
| `.claude/ORCHESTRATOR.md` | 변경 — 게이트 5항, `stance.json` 커밋 |
| `data/stance.json` | 신규 — 8/14 발행본 기준 수동 부트스트랩 |

## 테스트

`scripts/us/tests/test_stance.py` (pytest, 네트워크 불필요):

- 통제 어휘 — 정의된 등급↔라벨 왕복, 범위 밖 등급 거부
- 이동 규율 — 1단계 초과 거부, 부호 전환 직행 거부, 증대 시 트리거 필요,
  축소는 트리거 없이 허용, 3영업일 잠금이 증대만 막고 축소는 통과
- 트리거 판정 — 4개 연산자, 결측 지표 `UNKNOWN`, 이벤트형 `MANUAL`
- `allowed_grades` — 잠금·최대등급·트리거 미충족 조합에서 정확한 목록
- 영업일 계산 — 주말 건너뛰기
- 회귀 케이스 — 7/29 −1 → 7/30 +1 입력이 규율상 거부되는지
