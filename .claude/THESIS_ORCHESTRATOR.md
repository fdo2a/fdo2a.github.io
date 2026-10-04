# 종목 thesis 감시 파이프라인

평일 18:00 KST. 삼성전자(005930.KS) · SK하이닉스(000660.KS) · Micron(MU).

**이 루틴의 기본 동작은 «아무것도 하지 않는 것»이다.** (수집 워크플로는 별개다 —
그쪽은 매일 시세를 받아 페이지를 다시 렌더하고 커밋한다. 판단은 이 루틴만 바꾼다.) US·KR 브리프는 매일 발행하지만
이것은 다르다. 공식 발표로 기존 논거에 새로운 사실이 확인되면 등급이 그대로여도 기록한다.
새로운 사실이나 판단의 진전이 없으면 파일·커밋·알림 없이 끝낸다.
대부분의 날이 그런 날이다. 그게 정상이고, 그게 이 루틴의 가치다.

뭐라도 써야 할 것 같은 압박이 들면 그것이 바로 실패 신호다. 게이트가 막는다.

## 가장 먼저 — 조용한 날 확인 (다른 파일을 읽기 전에)

```bash
git pull && python3 scripts/thesis_quiet.py
```

`THESIS_QUIET` 가 나오면 **여기서 끝낸다.** 이 문서의 나머지도, `DESK_REPORT.md` 도 읽지
않는다. 웹 검색·파일 수정·커밋·알림 없이 최종 메시지 한 줄(「변화 없음 — THESIS_QUIET」)로
마친다. 커밋된 수치·DART 공시·삼성/하이닉스 뉴스룸 피드·실적 발표 창에 신규 신호가
없다는 뜻이다. Micron과 고객사 공식 발표의 전체 범위는 금요일 점검으로 확인한다.

`THESIS_CHECK` 가 나오거나 명령이 실패하면 아래 전체 절차를 그대로 밟는다. 출력된 사유가
STEP 2 에서 먼저 볼 자리다. 금요일은 늘 `THESIS_CHECK` 다 — 고객사(NVIDIA·AMD) 발표와
Micron 은 피드로 기계화되지 않아 주 1회 전체 점검으로 메운다.

편집 역할: 먼저 `.claude/DESK_REPORT.md`의 공통 원칙과 메모리 thesis 분기를 읽는다.
독자는 보유 여부를 밝히지 않은 헤지펀드 운용자다. 메모리 산업 시황과 기업별 투자 논거를 연결하되,
고객 주문·딜러 재고·포지셔닝을 관측한 것처럼 쓰지 않는다. 일간 브리프의 발행 빈도와 별도 연구 원장을
여기로 옮기지 않는다. 기존 `history.jsonl`·`thesis_state.json`·`changelog`가 판단 이력의 정본이다.

설계: `docs/superpowers/specs/2026-08-24-thesis-watch-design.md`

---

## STEP 0 — 상태 읽기

1. 레포를 클론하고 `git pull`.
2. `thesis/data/watch.json` — 오늘의 결정론적 수치. **직접 시세를 fetch하지 마라.**
   클라우드 환경은 금융 호스트가 403이고, 그래서 Actions가 17:40 KST에 미리 받아 커밋해 둔다.
3. `thesis/data/thesis_state.json` — 어제까지의 판단. 등급·`last_seen`·`open_questions`.
4. `thesis/data/history.jsonl` — 30일 전 값 조회용.

평일에 수집 자료가 늦으면 루트 `AGENTS.md`의 예약 수집 지연 절차를 따라 Actions 수집을
실행하고, 해당 실행 ID의 완료를 확인한 뒤 main을 동기화해 자료를 다시 읽는다. 주말에는
전 거래일 자료를 오늘 자료로 바꾸기 위해 수집을 강제하지 않는다.

`watch.json`의 `as_of`가 오늘이 아니면 오늘의 수치 판정 자료가 없는 것이다. 주말에는 평일
수집이 멈추므로 전 거래일 자료가 남는 것이 정상이다. **수치 트리거는 건너뛰고 사건 트리거만
보되, 최종 보고에는 «수치 판정 보류 · 사건 변화 확인/미확인»을 적는다.** 판정하지 못한
수치를 빈 트리거로 취급해 전체 변화 없음으로 보고하지 않는다. 낡은 수치로 판정하지 않는다.

## STEP 1 — 수치 트리거 (기계적)

```bash
python3 - <<'PY'
import json, sys; sys.path.insert(0, 'scripts')
from thesis import triggers as T, history as H
watch = json.load(open('thesis/data/watch.json'))
rows = H.load('thesis/data/history.jsonl')
deep = H.has_depth(rows, T.MIN_HISTORY_ROWS)
back = H.days_ago(watch['as_of'], T.LOOKBACK_DAYS)
out = {}
for sym, row in watch['tickers'].items():
    past = {k: H.value_on(rows, back, sym, k)
            for k in ('eps_fy1', 'eps_fy1_low', 'eps_fy1_high', 'price')}
    past = past if any(v is not None for v in past.values()) else None
    prev = H.previous(rows, watch['as_of'], sym)
    prior = T.prior_metrics(rows, sym, before=watch['as_of'])
    out[sym] = T.evaluate(row, past, row.get('fair_value'), has_depth=deep,
                          prev=prev, prior=prior)
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```

이 결과가 «오늘 숫자가 실제로 움직였는가»의 답이다. 재해석하지 마라 — 산술이다.

**전부 «오늘 넘어섰는가»를 묻는다.** 조건이 유지되는 동안은 조용하다. 30일 변화처럼
창이 굴러가는 지표는 한 번 울리면 충분히 진정될 때까지(20%→15%, 30%→20%) 다시 울리지
않는다 — 임계선 근처에서 오르내리는 것은 새 사건이 아니다. 어제도 오늘도
bear 가치권 안이면 트리거는 비어 있고, 그것이 아무 일도 없었다는 뜻으로 맞다. 그러니
「트리거가 없는데 페이지에는 관심선 아래라고 쓰여 있다」는 모순이 아니다 — 위치는
상태값(`position.in_band1`·`in_band2`)이고 페이지가 상시 보여준다. **주가가 관심선
아래로 내려간 것 자체는 트리거가 아니다.** 논거가 흔들린 것이 아니라 싸진 것이다.

## STEP 2 — 사건 트리거 (리서치)

각 종목에 대해 **마지막 실행 이후** 나온 것을 찾는다. `thesis_state.json`의 `updated`가 기준선이다.
이전 누락을 발견하면 기존 이력과 출처를 대조해 중복을 확인하고, 발표일과 발견일을 구별해
보완한다. 과거 사건을 오늘 새로 발생한 사건처럼 쓰거나 과거 판단을 소급해 고치지 않는다.

### 기록 조건과 등급 변경 조건

**기록 기준은 등급 변경 기준보다 넓다.** 공식 출처가 새로운 사실을 확인하고, 그 사실이
기존 thesis나 `open_questions`에 무엇을 더해 주는지 `delta`로 설명할 수 있으면 기록한다.
확정 주문이나 당장 발생한 매출이 없어도 다음 사건은 대상이다:

- 신규 고객·계약, 매출 가이던스, 마진·현금흐름 변화와 실적의 논거 이탈
- 투자 집행·투자 결정·전략적 지분 취득, 희석·주주환원, 경영 책임·거버넌스 변화
- 제품 샘플 공급·고객 평가·인증·양산 계획·증설·공정 적용의 구체적인 새 이정표
- 열린 질문의 답 또는 부분적인 진전, 공식적으로 확인된 장애·지연·위험

제품 발표에는 기존 계획 대비 바뀐 기술·고객 평가 단계·생산 일정 등 구체적인 새 정보가
있어야 한다. 공식 발표라는 이유만으로 홍보를 사건으로 올리지 않는다. 발표에 주문·인증 완료·
투자액·매출·수익 효과가 없으면 그 범위를 명시하고, 충분한 방향 근거가 없으면 `Neutral`로
기록한다. **등급 유지도 업데이트다.** 등급 이동은 STEP 3의 기존 규율로 별도 판단한다.

기록하지 않는 것 — 이미 기록한 내용의 반복, thesis와 무관한 홍보·행사 참석, 새로운
이정표가 없는 기술 소개, 단순 주가 변동, 소셜미디어 루머. 확인되지 않은 보도는 다음 조사
단서이며 확정 사건이나 등급 이동 근거로 사용하지 않는다.

### 1차 출처 규칙 (타협 없음)

사건이 등급을 움직이려면 **공시·IR·실적자료·고객사 공식 발표**로 확인돼야 한다.
언론 단독·익명 소식통·"업계에 따르면"은 **추론**으로만 분류하고, 그것만으로는 등급이 안 움직인다.
확인되면 `confirmed: true`, 아니면 `false`로 표시한다.

시장 기대는 관측 자료로만 설명한다. FY1 EPS 컨센서스의 기준일·범위·변화는 이익 기대의 대용치이며,
주가가 그 기대를 얼마나 반영했는지나 시장 포지셔닝의 직접 증거가 아니다. 자료가 없으면
기대 대비 차이는 미확인으로 남긴다. 공시 시각·수집 시각과 가격 반응의 거래 세션을 구별한다.

각 종목의 `open_questions`를 우선 확인한다 — 이미 열어둔 질문에 답이 나왔는지가
새 뉴스를 찾는 것보다 중요하다.

## STEP 3 — 판정

STEP 1·2가 **둘 다 비었으면 → STEP 6으로 건너뛴다. 아무것도 하지 않는다.**

하나라도 있으면 기존 논거에 더해진 사실을 기록하고 종목별 등급을 제안한다. 등급이 그대로여도
STEP 4로 진행한다. 등급 변경 제안은 규율에 통과시킨다:

```bash
python3 - <<'PY'
import json, sys; sys.path.insert(0, 'scripts')
from thesis import state as S
book = json.load(open('thesis/data/thesis_state.json'))['tickers']['MU']
r = S.propose(book, '주의', today='YYYY-MM-DD',
              triggers=['consensus_swing'], kill_evidence=('price',))
print(r.grade, r.allowed, r.reasons)
PY
```

규율 — 하루 한 단계 · 대각선 금지 · **kill은 가격 축과 계약/점유율 축이 함께 깨질 때만** ·
악화는 즉시, 회복은 3영업일 잠금 · 트리거 없으면 이동 불가.
`propose()`가 깎아낸 결과가 최종이다. 우회하지 마라.

**리서치 판단** — 트리거가 생긴 종목만 기존 논거를 유지·수정·폐기하는 이유를 작성한다.
확인된 사실, 해석, 가장 설득력 있는 대안 설명, 다음 촉매와 반증 조건을 연결한다.
촉매의 예정 시점과 관찰 기간은 출처가 있을 때 적고 모르면 미정으로 둔다. 일정 위험·원가·수요 등
일반 리스크와 논거 자체를 깨는 반증을 구별한다. 등급 유지도 정당한 결론이다.

**투자 활용** — 현물·상대가치·환헤지 등 표현 방법은 근거와 실행 여건을 확인한 경우에만 조건부로
설명한다. 세 회사의 회계기간·통화·제품 구성을 맞추지 않은 배수 비교로 우열을 정하지 않는다.
차입·스프레드·거래비용·유동성·투자 기간이 미확인이면 거래안 확정이나 수량·비중 제시를 하지 않는다.
밸류에이션의 확률·정규화율·배수는 내부 가정이며 시장에서 측정한 확률이 아니다.

**교차 반영** — 세 종목은 같은 사이클을 공유한다. 한 종목의 계약·가격 뉴스는
나머지 둘의 판단에도 반영한다. 특히 Micron의 RPO와 총이익률은 셋 공통의 계기판이다.

## STEP 4 — 기록

1. `thesis/data/thesis_state.json` 갱신 — `grade`·`grade_since`·`conviction`·
   `last_seen`(오늘 watch.json 값으로)·`open_questions`, 그리고 `changelog` 맨 앞에 새 항목:

```json
{"date": "YYYY-MM-DD", "signal": "주의", "stance": "Bearish",
 "title": "이벤트 제목",
 "fact": "확정 사실. <cite>출처</cite>",
 "inference": "추론: …",
 "delta": "기존 thesis 대비 무엇이 바뀌었는지",
 "next": "다음에 확인해야 할 것"}
```

`signal`은 통제 어휘 4개(`홀딩 강화`·`주의`·`비중 조절 검토`·`kill condition`),
`stance`는 `Bullish`·`Bearish`·`Neutral`. **`fact`에는 `<cite>` 출처가 반드시 있어야 한다** —
없으면 게이트가 막는다. 추론은 `inference`에만 쓰고 `fact`에 섞지 않는다.
`delta`에는 이전 판단과 비교해 유지·수정·폐기한 부분 및 놓친 가정을 기록하고, `next`에는
무엇을 언제 확인하면 판단이 달라지는지 쓴다. 결과를 보고 당시 확신이나 수익률을 재구성하지 않는다.
`open_questions`에는 아직 답하지 못한 질문을 승계한다. 이전 기록은 삭제하거나 사후에 고치지 않는다.

2. 페이지를 다시 만든다. **HTML을 직접 편집하지 마라** — 수치는 watch.json에서 렌더된다:

```bash
python3 scripts/build_thesis_pages.py
```

thesis 자체(9항목 기준표)가 바뀌어야 하는 사건이면 `scripts/thesis/content.py`를 고친 뒤 다시 빌드한다.
이건 드문 일이고, 반드시 changelog 항목이 따라붙어야 한다.

3. `sitemap.xml`의 `/thesis/` 항목 `lastmod`를 오늘로.

## STEP 5 — 게이트와 발행

```bash
cat > /tmp/run.json <<'JSON'
{"triggers": {"MU": [...]}, "events": {"MU": [...]},
 "kill_evidence": {"MU": ["price", "contract"]}}
JSON
python3 scripts/check_thesis.py --triggers /tmp/run.json
```

**실패하면 발행하지 않는다.** 특히 `silence` 실패는 "트리거 없이 페이지를 고쳤다"는 뜻이므로,
고친 것을 되돌려야지 트리거를 만들어내면 안 된다.

통과하면:
```bash
git add -A && git commit -m "thesis: [종목] [한 줄 요약] YYYY-MM-DD" && git pull --rebase && git push
```

## STEP 6 — 알림

**변화가 없으면 PushNotification을 보내지 않는다.** 조용히 끝낸다.

변화가 있으면 종목별로 7단계 형식:

```
1. [티커] / [이벤트 제목]
2. 확정 사실: … (출처)
3. 추론: … ← 사실과 분리
4. Bullish / Bearish / Neutral
5. 기존 thesis 대비 바뀐 것
6. 홀딩 강화 / 주의 / 비중 조절 검토 / kill condition
7. 다음에 확인할 것
```
페이지 URL(https://fdo2a.github.io/thesis/[slug].html)을 붙인다.

## RULES

- **발행 채널은 블로그 하나뿐이다.** Notion·PDF·이메일 금지. 커넥터가 붙어 있어도 쓰지 않는다.
- **수치 창작 절대 금지.** 페이지의 모든 숫자는 `watch.json`에서 렌더된다. 손으로 타이핑하지 않는다.
- **P/B의 기준일을 바꾸지 마라.** 최근 분기 실적이 발표됐어도 데이터 소스에 반영되기 전이면
  자본 증가가 안 잡혀 P/B가 높게 보인다. 이건 페이지에 이미 명시돼 있다.
  창작한 숫자보다 기준일이 밝혀진 낡은 숫자가 낫다.
- **기록 여부는 STEP 2의 기준으로 판단한다.** 공식 투자·제품·고객 평가·생산 진척은
  기존 논거에 새 정보를 주면 기록한다. 기술 이정표를 확정 주문이나 실현 매출로 해석하지 않는다.
- **단기 주가가 내려도 지표가 유지되면 단순 변동성**으로 분류한다. 그건 알림 대상이 아니다.
- 「buy-side」 금지. `[확인필요]`·TODO 잔존 금지. 게이트가 둘 다 막는다.
- 매수·매도 지시를 하지 않는다. 판단 보조용 정리다.
- 최종 메시지에 적을 것: 수치 트리거 판정 여부, 사건 기록 유무, 등급 변화 유무, push 성공/실패,
  Actions 데이터 신선도. 수치 판정 보류와 변화 없음은 구별한다.

## 템플릿 배포와 첫 적용

생성기 변경은 기존 발행 HTML을 일괄 다시 쓰는 권한이 아니다. 다음 정상 수집이 새 생성기를 사용한다.
수집 전 `--check --allow-template-transition`은 `scripts/thesis/template_transition.json`에 기록된
검증된 이전 페이지와 데이터가 모두 정확히 일치할 때만 템플릿 전환을 허용한다. 손편집이나
다른 데이터 조합이면 실패하며, 전환 뒤에는 새 렌더 결과와의 일반 대조가 적용된다.
이 예외를 늘리거나 해시를 갱신하려면 이전 생성기로 원본 일치 여부부터 검증한다.
