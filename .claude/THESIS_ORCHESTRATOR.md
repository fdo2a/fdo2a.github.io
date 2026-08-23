# 종목 thesis 감시 파이프라인

평일 18:00 KST. 삼성전자(005930.KS) · SK하이닉스(000660.KS) · Micron(MU).

**이 루틴의 기본 동작은 «아무것도 하지 않는 것»이다.** US·KR 브리프는 매일 발행하지만
이것은 다르다. 변화가 없으면 파일을 건드리지 않고, 커밋하지 않고, 알림도 보내지 않고 끝낸다.
대부분의 날이 그런 날이다. 그게 정상이고, 그게 이 루틴의 가치다.

뭐라도 써야 할 것 같은 압박이 들면 그것이 바로 실패 신호다. 게이트가 막는다.

설계: `docs/superpowers/specs/2026-08-24-thesis-watch-design.md`

---

## STEP 0 — 상태 읽기

1. 레포를 클론하고 `git pull`.
2. `thesis/data/watch.json` — 오늘의 결정론적 수치. **직접 시세를 fetch하지 마라.**
   클라우드 환경은 금융 호스트가 403이고, 그래서 Actions가 17:40 KST에 미리 받아 커밋해 둔다.
3. `thesis/data/thesis_state.json` — 어제까지의 판단. 등급·`last_seen`·`open_questions`.
4. `thesis/data/history.jsonl` — 30일 전 값 조회용.

`watch.json`의 `as_of`가 오늘이 아니면 Actions가 실패한 것이다. **수치 트리거는 건너뛰고
사건 트리거만 보되, 최종 보고에 그 사실을 반드시 적는다.** 낡은 수치로 판정하지 않는다.

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
    out[sym] = T.evaluate(row, past, row.get('fair_value'), has_depth=deep)
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```

이 결과가 «오늘 숫자가 실제로 움직였는가»의 답이다. 재해석하지 마라 — 산술이다.

## STEP 2 — 사건 트리거 (리서치)

각 종목에 대해 **마지막 실행 이후** 나온 것만 찾는다. `thesis_state.json`의 `updated`가 기준선.

찾는 것 — 신규 고객명 · 대형 주문/production order · 양산 일정 변경 · 매출 가이던스 상하향 ·
마진 개선/악화 · 현금흐름 악화 · 유상증자/전환사채/워런트 등 희석 · 파트너십의 실제 매출 전환 ·
경영진·거버넌스·자본배분 · 실적에서 thesis 이탈 · 밸류 재계산이 필요한 수주 변화.

**찾지 않는 것** — 단순 주가 변동 · 컨퍼런스 참석 · 홍보성 뉴스 · 소셜미디어 루머 ·
이미 알려진 테마성 코멘트 · 고객명·주문·매출·양산·가이던스 변화가 없는 보도자료.

### 1차 출처 규칙 (타협 없음)

사건이 등급을 움직이려면 **공시·IR·실적자료·고객사 공식 발표**로 확인돼야 한다.
언론 단독·익명 소식통·"업계에 따르면"은 **추론**으로만 분류하고, 그것만으로는 등급이 안 움직인다.
확인되면 `confirmed: true`, 아니면 `false`로 표시한다.

각 종목의 `open_questions`를 우선 확인한다 — 이미 열어둔 질문에 답이 나왔는지가
새 뉴스를 찾는 것보다 중요하다.

## STEP 3 — 판정

STEP 1·2가 **둘 다 비었으면 → STEP 6으로 건너뛴다. 아무것도 하지 않는다.**

하나라도 있으면 종목별로 등급을 제안하고, 규율에 통과시킨다:

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
- **좋아 보이는 뉴스라도 실제 주문·고객명·매출·양산·가이던스·마진·현금흐름 변화가 없으면
  과대평가하지 않는다.** 기술 발표와 수주는 다른 사건이다.
- **단기 주가가 내려도 지표가 유지되면 단순 변동성**으로 분류한다. 그건 알림 대상이 아니다.
- 「buy-side」 금지. `[확인필요]`·TODO 잔존 금지. 게이트가 둘 다 막는다.
- 매수·매도 지시를 하지 않는다. 판단 보조용 정리다.
- 최종 메시지에 적을 것: 트리거 유무, 등급 변화 유무, push 성공/실패, Actions 데이터 신선도.
