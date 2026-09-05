"""헤드라인 지표 manifest — 이 파이프라인의 수치 게이트가 딛고 서는 바닥.

## 왜 파싱하는가

US 브리프는 릴리스를 **파싱하지 않는다**. 기여도 귀속·수정폭 같은 질적 정보를 읽으려고
받아 둘 뿐이고, 숫자에는 FRED·market_data.json 이라는 정형 소스가 따로 있다. 중국에는
그 집이 없다 — FRED 의 중국 월간 계열은 CPI 가 2025-04 에서 끊겼고 GDP 는 2023-07 이다
(2026-09-05 실측). 그러니 「파싱하지 않는다」를 그대로 옮기면 US 설계를 따르는 게 아니라
**토대만 빼내는 것**이고, 수치 게이트가 사라진다.

게다가 이건 학습 리포트라 오귀속의 대가가 크다. 틀린 숫자는 `claims` 에 박혀 되짚기로
재인용되고 다음 강의의 전제가 된다 — **틀린 것을 누적해서 배운다.**

## 무엇을 파싱하는가

**헤드라인만.** 릴리스당 5~15개, 전부 합쳐 서른 남짓. 나머지 숫자(세부 항목·기여도)는
원문 덤프에 그대로 남아 `data-cite` 문단 안에서 약한 집합 대조를 받는다. 리포트의 척추는
기계가 지키고 곁가지는 사람이 본다 — 완전하지 않지만 어디가 약한지가 분명하다.

## fail-closed

**못 뽑으면 없는 것이고, 없으면 인용이 금지된다.** 파서가 실패했는데 조용히 넘어가면
수집 장애가 「그 주엔 발표가 없었다」로 위장된다(codex C5). 그래서 `extract()` 는 못 찾은
지표를 만들어 내지 않고, 알 수 없는 kind 는 빈 결과가 아니라 KeyError 를 던진다 —
오타난 kind 가 무발표로 읽히면 같은 위장이 다시 열린다.

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

import re
from dataclasses import dataclass

# 방향어 → 부호. 원문이 「decreased by 1.5%」라고 쓴 것을 -1.5 로 실어 둬야 게이트가
# 부호까지 본다. 숫자만 뽑으면 「식품이 1.5% 올랐다」는 창작이 통과한다.
_UP = (r'increased by|rose by|up by|grew by|climbed by|gained by'
       r'|increased|rose|climbed|gained|上涨|上升|增长|提高')
_DOWN = (r'decreased by|fell by|down by|declined by|dropped by|slid by|eased by'
         r'|decreased|fell|declined|dropped|slid|eased|下降|下跌|回落|降低')
_FLAT = r'remained flat|was unchanged|持平'

_DIR = f'(?P<dir>{_UP}|{_DOWN}|{_FLAT})'
_VAL = r'(?P<val>\d+(?:\.\d+)?)'

# 「a year-on-year decrease of 19.2%」 — 방향어가 명사로 오는 두 번째 구문. NBS 는
# 투자·재정 릴리스에서 이쪽을 쓴다.
_UP_N = r'increase|rise|growth'
_DOWN_N = r'decrease|decline|fall|drop|reduction'
_YOY_OF = rf'a year-on-year\s+(?P<dir>{_UP_N}|{_DOWN_N})\s+of\s+{_VAL}\s*%'

# 지표 이름과 값 사이에 **다른 백분율이 끼지 못하게** 한다. FAI 헤드라인(-6.7%)을 찾다가
# 뒤쪽 「내자기업 -6.4%」를 집어 온 오귀속이 여기서 났다(2026-09-05 실측).
_GAP = r'[^%]{0,140}?'
# 값이 없는 방향어(「remained flat」·「持平」)도 뽑아야 한다 — 0 을 «결측» 으로 흘리면
# 「변화 없음」이 발표되지 않은 것처럼 보인다. 그래서 수치를 선택항으로 두고, 방향이
# flat 이 아닌데 수치가 없으면 그 패턴은 못 맞은 것으로 친다.
_SIGNED = rf'{_DIR}\s*(?:by\s*)?(?:{_VAL}\s*%)?'


def _sign(word):
    if re.fullmatch(f'{_UP}|{_UP_N}', word):
        return 1
    if re.fullmatch(f'{_DOWN}|{_DOWN_N}', word):
        return -1
    return 0


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    kind: str            # 어느 릴리스에서 나오는가
    label_ko: str
    unit: str            # '%' | '%p' | 'level' 단위 표기
    value_kind: str      # 'change' (부호 있는 변화) | 'level' (수준)
    patterns: tuple      # 앞에서부터 먼저 맞는 것을 쓴다
    scope: str = ''      # 'yoy' 면 전월비 서술이 시작되기 전까지만 본다


def _spec(mid, kind, label, patterns, unit='%', value_kind='change', scope=''):
    return MetricSpec(mid, kind, label, unit, value_kind, tuple(patterns), scope)


# 전년비 서술이 끝나고 전월비 서술이 시작되는 자리. 같은 문구가 양쪽에 다 나오는
# 지표(식품·비식품)를 가르는 경계다.
_MOM_MARKER = re.compile(r'month on month|环比')


def _scoped(text, scope):
    if scope != 'yoy':
        return text
    m = _MOM_MARKER.search(text)
    if not m:
        return text
    # 전월비 문장의 앞 절까지는 남긴다 — 리드 문장이 「… year on year and decreased
    # by 0.7% month on month」처럼 한 문장인 릴리스가 있다.
    cut = text.rfind('.', 0, m.start())
    return text[:cut + 1] if cut > 0 else text[:m.start()]


# ── CPI (NBS, 매월 ~10일) ──
_CPI = [
    # 리드 문장(「In July 2026, …」)에 고정한다. 앵커가 느슨하면 문구가 조금만 바뀌어도
    # 뒤쪽 누계 문장(「From January to July … increased by 0.9%」)을 물어 온다.
    _spec('cpi_yoy', 'nbs-cpi', '소비자물가 전년 대비', [
        rf"In \w+ \d{{4}},{_GAP}Consumer Price Index \(CPI\)\s*{_SIGNED}\s*year on year",
        rf"In \w+ \d{{4}},{_GAP}CPI\s*{_SIGNED}\s*year on year",
        rf"居民消费价格同比{_DIR}{_VAL}%",
    ], scope='yoy'),
    _spec('cpi_mom', 'nbs-cpi', '소비자물가 전월 대비', [
        rf"CPI\s*{_SIGNED}\s*month on month",
        rf"居民消费价格环比{_DIR}{_VAL}%",
    ]),
    # 전월비 문단에도 같은 문구가 있다 — 전년비 구간으로 범위를 좁혀서 찾는다.
    _spec('cpi_food_yoy', 'nbs-cpi', '식품 물가 전년 대비', [
        rf"price index for food\s*{_SIGNED}",
        rf"食品价格{_DIR}{_VAL}%",
    ], scope='yoy'),
    _spec('cpi_nonfood_yoy', 'nbs-cpi', '비식품 물가 전년 대비', [
        rf"for non-food\s*{_SIGNED}",
        rf"非食品价格{_DIR}{_VAL}%",
    ], scope='yoy'),
    _spec('cpi_cum_yoy', 'nbs-cpi', '소비자물가 누계 전년 대비', [
        rf"on average, China's CPI\s*{_SIGNED}\s*year on year",
        rf"累计.{{0,6}}居民消费价格.{{0,4}}{_DIR}{_VAL}%",
    ]),
]

# ── PPI (NBS, CPI 와 같은 날) ──
_PPI = [
    _spec('ppi_yoy', 'nbs-ppi', '생산자물가 전년 대비', [
        rf"price index for industrial products \(PPI\)\s*{_SIGNED}\s*year on year",
        rf"工业生产者出厂价格同比{_DIR}{_VAL}%",
    ]),
    # 한 문장이 전년비와 전월비를 함께 싣는다 — 「… and decreased by 0.7% month on
    # month」. 값은 「month on month」 바로 앞에 붙으므로 인접으로 묶으면 안전하다.
    _spec('ppi_mom', 'nbs-ppi', '생산자물가 전월 대비', [
        rf"\(PPI\)[\s\S]{{0,140}}?{_SIGNED}\s*month on month",
        rf"工业生产者出厂价格环比{_DIR}{_VAL}%",
    ]),
]

# ── 월간 덤프 (NBS, ~15~19일) ──
_ACTIVITY = [
    # 「In July, …」 로 시작하는 월간 헤드라인에 고정한다. 누계 문장이 먼저 나오므로
    # 앞에서부터 찾으면 월간 자리에 누계 값이 들어간다.
    _spec('ip_yoy', 'nbs-ip', '산업생산 전년 대비', [
        rf"In \w+,{_GAP}total value added of industrial enterprises above the "
        rf"designated size\s*{_SIGNED}\s*year on year",
        rf"规模以上工业增加值同比实际?{_DIR}{_VAL}%",
    ]),
    _spec('retail_yoy', 'nbs-retail', '소매판매 전년 대비', [
        rf"In \w+, the total retail sales of consumer goods{_GAP}{_SIGNED}\s*year on year",
        rf"社会消费品零售总额同比{_DIR}{_VAL}%",
    ]),
    _spec('retail_cum_yoy', 'nbs-retail', '소매판매 누계 전년 대비', [
        rf"From January to \w+[^%]{{0,20}}, the total retail sales of consumer goods"
        rf"{_GAP}{_SIGNED}\s*year on year",
    ]),
    # 「national investment in fixed assets」 — 하위 항목 문장은 「the investment in
    # fixed assets of domestic-invested enterprises」 라 이 수식어로 갈린다.
    _spec('fai_cum_yoy', 'nbs-fai', '고정자산투자 누계 전년 대비', [
        rf"national investment in fixed assets{_GAP}{_YOY_OF}",
        rf"national investment in fixed assets{_GAP}{_SIGNED}\s*year on year",
        rf"固定资产投资.{{0,12}}同比{_DIR}{_VAL}%",
    ]),
    _spec('property_inv_cum_yoy', 'nbs-property', '부동산개발투자 누계 전년 대비', [
        rf"investment in real estate development was{_GAP}{_YOY_OF}",
        rf"investment in real estate development{_GAP}{_SIGNED}\s*year on year",
        rf"房地产开发投资.{{0,12}}同比{_DIR}{_VAL}%",
    ]),
]

# ── PMI (NBS, 전월 말일) — 레벨이라 부호가 없다 ──
_PMI = [
    _spec('pmi_mfg', 'nbs-pmi', '제조업 PMI',
          [r"\(PMI\) of China's manufacturing industry was\s*(?P<val>\d+(?:\.\d+)?)\s*%",
           r"manufacturing sector was\s*(?P<val>\d+(?:\.\d+)?)\s*%",
           r"制造业采购经理指数为(?P<val>\d+(?:\.\d+)?)%"],
          unit='%', value_kind='level'),
    _spec('pmi_nonmfg', 'nbs-pmi', '비제조업 PMI',
          [r"non-manufacturing business activity index was\s*(?P<val>\d+(?:\.\d+)?)\s*%",
           r"非制造业商务活动指数为(?P<val>\d+(?:\.\d+)?)%"],
          unit='%', value_kind='level'),
    _spec('pmi_composite', 'nbs-pmi', '종합 PMI 산출지수',
          [r"composite PMI output index was\s*(?P<val>\d+(?:\.\d+)?)\s*%",
           r"综合PMI产出指数为(?P<val>\d+(?:\.\d+)?)%"],
          unit='%', value_kind='level'),
]

# ── 금융통계 (PBoC, ~13~15일) ──
_CREDIT = [
    _spec('tsf_stock_yoy', 'pboc-afre', '총사회융자 잔액 증가율', [
        rf"[Aa]ggregate [Ff]inancing to the [Rr]eal [Ee]conomy[^.]{{0,90}}?{_SIGNED}\s*year on year",
        rf"社会融资规模存量.{{0,20}}同比{_DIR}{_VAL}%",
    ]),
    _spec('m2_yoy', 'pboc-afre', 'M2 증가율', [
        rf"M2\s*{_SIGNED}\s*year on year",
        rf"广义货币\(M2\)余额.{{0,20}}同比{_DIR}{_VAL}%",
    ]),
]

# ── LPR (PBoC, 매월 20일) — 레벨 ──
_LPR = [
    _spec('lpr_1y', 'pboc-lpr', '1년 만기 LPR',
          [r"1年期LPR为(?P<val>\d+(?:\.\d+)?)%",
           r"one-year LPR (?:was|at)\s*(?P<val>\d+(?:\.\d+)?)\s*%"],
          value_kind='level'),
    _spec('lpr_5y', 'pboc-lpr', '5년 초과 LPR',
          [r"5年期以上LPR为(?P<val>\d+(?:\.\d+)?)%",
           r"over-five-year LPR (?:was|at)\s*(?P<val>\d+(?:\.\d+)?)\s*%"],
          value_kind='level'),
]

# ── 무역 (해관총서, 공표 시간표에 따름) ──
_TRADE = [
    _spec('exports_yoy', 'customs-trade', '수출 전년 대비', [
        rf"[Ee]xports\s*{_SIGNED}\s*year on year",
        rf"出口.{{0,10}}同比{_DIR}{_VAL}%",
    ]),
    _spec('imports_yoy', 'customs-trade', '수입 전년 대비', [
        rf"[Ii]mports\s*{_SIGNED}\s*year on year",
        rf"进口.{{0,10}}同比{_DIR}{_VAL}%",
    ]),
]

# ── 재정 (재정부, 월별) — codex F19. A02·A03 이 이것 없이는 성립하지 않는다 ──
_FISCAL = [
    _spec('land_sales_cum_yoy', 'mof-fiscal', '국유토지사용권 출양수입 누계 전년 대비', [
        rf"国有土地使用权出让收入.{{0,20}}同比{_DIR}{_VAL}%",
    ]),
    _spec('fiscal_revenue_cum_yoy', 'mof-fiscal', '일반공공예산수입 누계 전년 대비', [
        rf"一般公共预算收入.{{0,20}}同比{_DIR}{_VAL}%",
    ]),
]

METRICS = {s.metric_id: s for s in
           _CPI + _PPI + _ACTIVITY + _PMI + _CREDIT + _LPR + _TRADE + _FISCAL}

KINDS = sorted({s.kind for s in METRICS.values()})


# 원문은 조판 따옴표·줄표를 쓴다(`China\u2019s`). 곧은 문자로만 맞추면 조용히 놓치고,
# 그 결과는 「그 지표는 발표되지 않았다」와 구분되지 않는다.
_NORMALIZE = str.maketrans({'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
                            '\u2013': '-', '\u2014': '-', '\u2212': '-',
                            '\xa0': ' ', '\u3000': ' '})


def extract(kind, text, *, period, source_key=None):
    """한 릴리스 원문에서 그 kind 의 헤드라인 지표를 뽑는다.

    못 찾은 지표는 **만들지 않는다**(fail-closed). 알 수 없는 kind 는 빈 결과가 아니라
    KeyError — 오타가 「발표 없음」으로 읽히면 수집 장애 위장이 다시 열린다.
    """
    if kind not in KINDS:
        raise KeyError(f'알 수 없는 릴리스 kind: {kind!r} (아는 것: {KINDS})')

    text = text.translate(_NORMALIZE)
    facts = []
    for spec in METRICS.values():
        if spec.kind != kind:
            continue
        haystack = _scoped(text, spec.scope)
        for pat in spec.patterns:
            m = re.search(pat, haystack, re.S)
            if not m:
                continue
            groups = m.groupdict()
            if spec.value_kind == 'level':
                value = float(groups['val'])
            else:
                sign = _sign(groups['dir'])
                if sign == 0:
                    value = 0.0
                elif groups.get('val') is None:
                    continue        # 방향만 있고 수치가 없다 — 이 패턴은 못 맞은 것
                else:
                    value = sign * float(groups['val'])
            facts.append({
                'metric_id': spec.metric_id,
                'label_ko': spec.label_ko,
                'period': period,
                'value': value,
                'unit': spec.unit,
                'kind': spec.value_kind,
                'source_key': source_key,
            })
            break
    return facts


def build(releases):
    """[{key, kind, period, text}] → {metric_id: {period: fact}}."""
    out = {}
    for rel in releases:
        for fact in extract(rel['kind'], rel['text'], period=rel['period'],
                            source_key=rel['key']):
            out.setdefault(fact['metric_id'], {})[fact['period']] = fact
    return out


def _canon(v):
    f = float(v)
    return str(int(f)) if f == int(f) else f'{f:.10g}'


def allowed_values(man, metric_id, period=None):
    """그 지표로 인쇄해도 되는 수치 문자열.

    `period` 를 주면 **그 달 값만** 허용한다. 지표별로만 좁히면 같은 지표의 다른 달
    값을 그 달 것처럼 인쇄하는 창작이 통과한다 — 「7월 CPI 는 0.2%」(실제로는 6월 값).
    부호를 뒤집은 변형은 넣지 않는다.
    """
    out = set()
    facts = man.get(metric_id, {})
    facts = {period: facts[period]} if period is not None and period in facts else (
        {} if period is not None else facts)
    for fact in facts.values():
        v = fact['value']
        out.add(_canon(v))
        # 원문이 「49.0%」라고 쓴 것을 발행본도 그렇게 쓴다. `_canon` 은 뒷자리 0 을
        # 지우므로 고정소수 표기를 함께 넣지 않으면 정상 인용이 창작으로 걸린다.
        out.add(f'{v:.1f}')
        out.add(f'{v:.2f}')
        for nd in (1, 2):
            r = round(v, nd)
            # 값을 0 으로 지우는 반올림은 넣지 않는다(period_gate 와 같은 이유).
            if r == 0 and v != 0:
                continue
            out.add(_canon(r))
        # 음수는 절댓값도 함께 허용한다 — 「1.5% 하락했다」처럼 방향을 말로 쓰는 것이
        # 정상 표기다. 방향어와의 정합은 게이트가 따로 본다.
        if v < 0:
            out.add(_canon(abs(v)))
    return out
