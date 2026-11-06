"""US 일간 브리프 수치 전수 대조 (2026-11-07). CLI: `scripts/check_numbers.py`.

「이 숫자가 데이터 어딘가에 있나」는 검사가 아니다 — 11/05 글의 허용 집합 22,187 값에서
맞은 수치의 끝자리를 +1 해도 64% 가 통과했다. 그래서 숫자마다 **자리**(표 칸, 문장 속 자산·필드)를
정하고 그 자리의 값과만 맞춘다.

세 층:
  1. 표 칸 — 시장 표 6종(오늘의 장·주식 지수·섹터·채권·FX·원자재)의 행 라벨 → 데이터 키,
     열(th 와 data-label 이 같은 열을 가리켜야 한다) → 필드 또는 공식. 차단.
  2. 문장 — 자산·단위로 필드가 하나로 정해지는 수치만 판정(방향어로 부호 복원). 후보가 둘 이상,
     자산 사전 밖, 시점·구간 단서가 있는 수치는 「미검증」으로 센다. `prose` 가 warn 이면 경고.
  3. 위임 — 섹터 기간 표(check_sector_perf), 트렌드 유닛 점검(check_fund), 매크로 표의 표식 행
     Actual·Previous·추세(macro_table_gate). 종료 코드가 아니라 **같은 입력으로 그 검사 함수를 불러**
     위반 0 일 때만 위임으로 센다. 아니면 그 자리 수치는 미검증.
  `details`(접힌 계산 근거)는 제외로 센다. 숨긴 요소 속 수치·태그로 쪼갠 수치는 차단.

모든 수치는 표 칸 / 판정 / 미검증 / 위임 / 제외 중 정확히 한 곳에 들어간다(`tokens_seen`).

When changing this: read `docs/superpowers/specs/2026-11-07-number-audit.md` first.
"""

import re
from dataclasses import dataclass, field

from common.numbers import numbers_split_by_tags
from fund.gate import _Doc

EFFECTIVE = '2026-10-01'


class InputError(Exception):
    """입력으로 판정할 수 없다 — 통과가 아니다(CLI exit 2)."""


# ── 토크나이저 ───────────────────────────────────────────────────────────

_MASKS = (re.compile(r'\d{4}-\d{2}-\d{2}'), re.compile(r'\d{4}년'),
          re.compile(r'\d{1,2}월\s?\d{1,2}일'), re.compile(r'\d{1,2}월'),
          re.compile(r'(?<!\d)\d{1,2}:\d{2}(?!\d)'))
_TOK = re.compile(
    # 앞 경계는 ASCII 만 — 한글 바로 뒤 수치(「약9B」「매출9.5%」)도 센다(codex 10차 #3). 「러셀2000」은 단위 없는 정수라 빠진다
    # 「4.5」의 5 는 따로 세지 않는다(숫자+마침표 뒤). 「했다.5%」의 5% 는 센다(한글+마침표 뒤 — codex 12차 #2).
    # 앞 0 생략 소수(.5)는 공백·괄호·부호·문두 뒤에서만.
    r'(?<![A-Za-z0-9_])(?<!\d\.)(?<!\d,)([+\-−－–]?)(\$?)'
    r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|(?:(?<=[\s(\[~+\-−－–$])|^)\.\d+)'
    r'(?!\d|,\d)'
    r'(\s?)(%포인트|%p|%|bp|배|건|억|조|달러|원|엔|포인트|p(?![A-Za-z])|[KMB](?![A-Za-z]))?')
_UNIT_ALIAS = {'%포인트': '%p', '포인트': 'p'}


@dataclass
class Tok:
    start: int
    end: int
    raw: str
    value: float
    sign: str
    decimals: int
    unit: str


# 전각 숫자·기호를 반각으로 — 글자 수가 같아 위치가 그대로다(「９９．９９％」「1，234%」, codex 11차 #2)
_WIDE = str.maketrans({**{chr(0xFF10 + i): str(i) for i in range(10)},
                       '．': '.', '，': ',', '％': '%', '＋': '+', '－': '-', '＄': '$'})


def _mask(text):
    out = text.translate(_WIDE)
    for rx in _MASKS:
        out = rx.sub(lambda m: ' ' * len(m.group(0)), out)
    return out


def tokens(text):
    """위치·원문 단위를 보존한 수치 목록. 단위·소수점·천 단위 구분자 중 하나가 있어야 수치다."""
    out = []
    masked = _mask(text or '')
    for m in _TOK.finditer(masked):
        sign, dollar, num, _, unit = m.groups()
        unit = _UNIT_ALIAS.get(unit, unit) or ''
        if not unit and dollar:
            unit = '$'
        if not unit and '.' not in num and ',' not in num:
            continue
        # 「3M」(종목·만기)도 수치로 센다 — 「9B」(금액)와 글자로 가를 수 없고, 빠뜨린 수치가 드문 오탐보다
        # 나쁘다(codex 8차 지적을 9차 지적으로 되돌렸다). 숨김·SVG 안 「3M」은 막히지만 26편에 그런 표기는 없다
        end = m.end() if unit and unit != '$' else m.start(3) + len(num)
        sign = '-' if sign and sign != '+' else ('+' if sign == '+' else '')
        v = float(num.replace(',', ''))
        if sign == '-':
            v = -v
        dec = len(num.split('.')[1]) if '.' in num else 0
        out.append(Tok(m.start(), end, masked[m.start():end], v, sign, dec, unit))
    return out


def close_enough(printed, decimals, expected, double=False):
    """인쇄 값이 근거 원값을 그 자릿수로 반올림한 값인가. .5 경계는 양쪽 다 받는다.

    `double` 은 문장만 — 표가 157.805 로 싣고 문장이 그것을 157.81 로 줄이면 원값 157.80499… 의
    정직한 반올림(157.80)과 갈린다. 한 자리 더 둔 값에서 줄인 것까지 받는다. **표 칸에는 쓰지 않는다**:
    0.5849 가 0.585 를 거쳐 0.58·0.59 둘 다 통과해 끝자리 오타를 놓친다(소급 변형 시험에서 5건).
    """
    if expected is None:
        return False
    tol = 0.5 * 10 ** -decimals + 1e-9
    if abs(printed - expected) <= tol:
        return True
    return double and abs(printed - round(expected, decimals + 1)) <= tol


def _fmt(x):
    return f'{x:,.4f}'.rstrip('0').rstrip('.') if isinstance(x, (int, float)) else str(x)


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _md(iso):
    m = re.match(r'\d{4}-(\d{2})-(\d{2})$', iso or '')
    return f'{int(m.group(1))}월 {int(m.group(2))}일' if m else None


# ── 데이터 접근 ─────────────────────────────────────────────────────────

def _global_rows(market):
    out = {}
    gc = ((market.get('session') or {}).get('global_close') or {})
    for region in ('asia', 'europe'):
        for r in (gc.get(region) or {}).get('rows') or []:
            if isinstance(r, dict) and r.get('name'):
                out[r['name']] = r
    return out


def _vix(market):
    pc = market.get('price_context') or {}
    lv = ((pc.get('levels') or {}).get('VIX') or {})
    mv = ((pc.get('moves') or {}).get('VIX') or {})
    # 2026-10-23 부터 VIX 등락은 포인트(`unit: pt`), 그 전 자료는 % 였다 — 단위는 자료가 정한다
    return {'close': _num(lv.get('value')), 'chg': _num(mv.get('change')),
            'date': market.get('report_date'), 'chg_unit': 'p' if mv.get('unit') == 'pt' else '%'}


def _asset(market, group, key):
    """(group, key) → {필드: 값}. 표와 문장이 같은 사전을 쓴다."""
    if group == 'global':
        if key == 'VIX':
            return _vix(market)
        r = _global_rows(market).get(key)
        return None if r is None else {'close': _num(r.get('close')), 'chg': _num(r.get('pct')),
                                       'date': r.get('date')}
    if group == 'yields':
        r = (market.get('yields') or {}).get(key)
        if not isinstance(r, dict):
            return None
        lv, wk = _num(r.get('level')), _num(r.get('week_ago'))
        return {'close': lv, 'd1': _num(r.get('bp')), 'wk': wk,
                'w1': None if lv is None or wk is None else (lv - wk) * 100,
                'date': r.get('date'), 'wk_date': r.get('week_ago_date')}
    if group == 'spread':
        return {'close': _num(market.get(key))}
    r = (market.get(group) or {}).get(key)
    if not isinstance(r, dict):
        return None
    return {'close': _num(r.get('last')), 'chg': _num(r.get('pct')), 'date': r.get('date')}


# ── 층 1: 표 지도 ────────────────────────────────────────────────────────

GLOBAL_ROWS = {'닛케이225': 'Nikkei', '항셍': '항셍', '상해종합': '상해종합', 'DAX': 'DAX',
               'FTSE100': 'FTSE100', '유로스톡스50': '유로스톡스50', 'VIX': 'VIX'}
_GLOBAL_NAME = {'Nikkei': '닛케이'}
INDEX_ROWS = {'나스닥': 'Nasdaq', 'S&P500': 'S&P 500', '다우존스': 'Dow', '러셀2000': 'Russell 2000',
              'S&P500 성장주': 'S&P 500 Growth', 'S&P500 가치주': 'S&P 500 Value'}
SECTOR_ROWS = {'기술': 'Technology', '에너지': 'Energy', '커뮤니케이션서비스': 'Communication Services',
               '경기소비재': 'Consumer Discretionary', '유틸리티': 'Utilities', '필수소비재': 'Consumer Staples',
               '헬스케어': 'Health Care', '산업재': 'Industrials', '금융': 'Financials', '소재': 'Materials',
               '부동산': 'Real Estate'}
YIELD_ROWS = {'2Y': '2Y', '5Y': '5Y', '10Y': '10Y', '30Y': '30Y'}
FX_ROWS = {'DXY': 'DXY', 'USD/KRW': 'USD/KRW', 'USD/JPY': 'USD/JPY', 'EUR/USD': 'EUR/USD'}
COMMODITY_ROWS = {'WTI': 'WTI', 'Brent': 'Brent', '천연가스': 'Natural Gas', '금': 'Gold'}

# 열 이름 → 열 키. th 와 data-label 을 따로 정규화하고 둘이 같은 열을 가리켜야 한다.
COLUMNS = {'종가': 'close', '등락': 'chg', '등락률': 'chg', '기준일': 'date', '전일比': 'd1',
           '전일 변화': 'd1', '1주 전': 'wk', '주간 변화': 'w1'}
# 열 키 → 허용 단위
UNITS = {'close': {'', '$', '%'}, 'chg': {'%'}, 'd1': {'', 'bp'}, 'w1': {'', 'bp'},
         'wk': {'%'}}


@dataclass
class TableSpec:
    section: str
    first: str          # 첫 th
    rows: dict
    group: str
    cols: tuple         # 필수 열 키(첫 열 제외)
    optional: tuple = ()


TABLES = (
    TableSpec('오늘의 장', '지수', GLOBAL_ROWS, 'global', ('close', 'chg'), ('date',)),
    TableSpec('주식', '지수', INDEX_ROWS, 'indices', ('close', 'chg')),
    TableSpec('주식', '섹터', SECTOR_ROWS, 'sectors', ('chg',)),
    TableSpec('채권', '만기', YIELD_ROWS, 'yields', ('close', 'd1', 'wk', 'w1')),
    TableSpec('FX', '통화쌍', FX_ROWS, 'fx', ('close', 'chg'), ('date',)),
    TableSpec('원자재', '품목', COMMODITY_ROWS, 'commodities', ('close', 'chg')),
)


def _norm_label(s):
    s = re.sub(r'\s+', ' ', (s or '').replace('&amp;', '&')).strip()
    return re.sub(r'\s*\([^)]*\)\s*$', '', s)


def _paren(s):
    m = re.search(r'\(([^)]*)\)\s*$', s or '')
    return m.group(1).strip() if m else None


# ── 층 2: 자산 사전 ──────────────────────────────────────────────────────

def _alias_table():
    a = []

    def add(pattern, target):
        a.append((re.compile(pattern), target))
    # 막는 이름(다른 자산) — 긴 것부터 먼저 잡혀 아래 짧은 이름을 가린다
    for p in (r'나스닥\s?100', r'S&P\s?(500\s?)?(동일가중|성장주|가치주|선물)', r'동일가중', r'성장주|가치주',
              r'(나스닥|S&P|러셀|다우)\s?선물', r'필라델피아', r'반도체\s?지수', r'SOX', r'QQQ', r'SPY',
              # 같은 만기의 다른 지표 — 「10년물 기대인플레가 2.36%」는 10년물 금리가 아니다
              r'기대\s?인플레|실질\s?금리|명목\s?금리|브레이크이븐|BEI|기간\s?프리미엄|하이일드|'
              r'회사채|모기지|정책\s?금리|기준\s?금리',
              # 다른 나라 — 「프랑스 10년물 4.914%」
              r'프랑스|독일|영국|이탈리아|일본|중국|캐나다|호주|유럽|한국|국내'):
        add(p, None)
    add(r'S&P\s?500|S&P', ('indices', 'S&P 500'))
    add(r'나스닥(?!\s?100)', ('indices', 'Nasdaq'))
    add(r'다우(존스)?', ('indices', 'Dow'))
    add(r'러셀\s?2000|러셀', ('indices', 'Russell 2000'))
    for ko, key in SECTOR_ROWS.items():
        add(re.escape(ko) + r'\s?업종', ('sectors', key))
    for n, key in (('2', '2Y'), ('5', '5Y'), ('10', '10Y'), ('30', '30Y')):
        add(rf'(?<!\d){n}(년물|년 국채|Y)(?![\w])', ('yields', key))
    add(r'2s10s', ('spread', 'spread_2s10s_bp'))
    add(r'5s30s', ('spread', 'spread_5s30s_bp'))
    add(r'달러지수|DXY', ('fx', 'DXY'))
    add(r'원/달러|달러/원|원·달러|원달러|USD/KRW', ('fx', 'USD/KRW'))
    add(r'엔/달러|달러/엔|엔·달러|USD/JPY', ('fx', 'USD/JPY'))
    add(r'유로/달러|EUR/USD', ('fx', 'EUR/USD'))
    add(r'WTI', ('commodities', 'WTI'))
    add(r'브렌트|Brent', ('commodities', 'Brent'))
    add(r'천연가스', ('commodities', 'Natural Gas'))
    add(r'(?<![가-힣])금(?=값|\s?가격|[은는이가도을\s(]|$)', ('commodities', 'Gold'))
    add(r'닛케이', ('global', '닛케이'))
    add(r'항셍', ('global', '항셍'))
    add(r'상해종합|상하이종합', ('global', '상해종합'))
    add(r'DAX', ('global', 'DAX'))
    add(r'FTSE\s?100|FTSE', ('global', 'FTSE100'))
    add(r'유로스톡스\s?50|유로스톡스', ('global', '유로스톡스50'))
    add(r'VIX', ('global', 'VIX'))
    return a


ALIASES = _alias_table()

# 시점·구간·파생 단서 — 그날 종가 수치가 아닐 수 있으므로 판정하지 않는다
_CUES = re.compile(r'전날|전일|지난주|지난달|1주|한 주|닷새|거래일|사이|동안|만에|기간|같은 날|그날|'
                   r'주간|누적|장중|선물|고점|저점|개장|시가|초반|막판|열어|열렸|열린|시작|'
                   r'갭|현물|자정|새벽|아침|저녁|밤|오전|오후|무렵|\(ET\)|ET\b|~|'
                   r'따르면|집계|차이|격차|보다|몫|(?<![가-힣])약\s|'
                   r'최근|연초|월초|구간|평균|이후|대비|직전|기준|약화|강화|조건|목표|손절|트리거|'
                   r'전망|예상|가이던스|보도|발표|컨센|추정|만약|라면|이면|\d{1,2}월|\d{1,2}일')
# 수치 바로 뒤에만 보는 단서 — 어림·문턱 표현(「7,800선」「103달러 부근」「3%대」「5% 이상」)
_TAIL_CUES = re.compile(r'^[^\d]{0,3}?(선(?=[에을이위아도,\s·]|$)|대(?=로|에|를|\s|$)|부근|안팎|이상|이하|넘게|'
                        r'넘는|넘어|가까이|아래|위로|쪽|안에|남짓|까지|부터|되찾|돌파|회복|가운데|비싸|싸|'
                        r'넓어|좁아|가팔라|벌어|확대|축소|정산|결제|'
                        # 과거형·가능성(「5.0%였다」「5.0%가 될 수 있다」)은 오늘 값이라고 단정하지 않는다(codex 3차 #2)
                        r'였|이었|일 수|될 수|갈 수|수 있|가능|라면|면\s|일지|인지)')
# 남의 말·다른 기준가를 옮긴 문장 — 문장 전체를 판정하지 않는다(「…92.87달러에 정산했다고 전했다」)
_REPORTED = re.compile(r'정산|결제가|했다고|이라고|라고\s|에 따르면|전했다|밝혔다|보도했|집계했')

_DOWN = re.compile(r'^\s*(?:[가-힣]{0,2}\s)?(내려|내린|내렸|하락|떨어|밀려|밀린|밀렸|빠졌|빠진|빠져|'
                   r'급락|약세|줄어|줄었|낮아|낮은)')
_UP = re.compile(r'^\s*(?:[가-힣]{0,2}\s)?(올라|오른|올랐|상승|뛰|급등|강세|늘어|늘었|반등|높아|높은)')

# 단위 → 그 자산 그룹에서 맞출 필드
_FIELDS = {
    # 필드는 하나로 정해져야 판정한다 — 1주 전 값·주간 변화는 「1주」「주간」 단서가 붙어 미검증이 된다
    # (둘 중 하나라도 맞으면 통과시키면 「10Y 5.0%」가 1주 전 값으로 통과한다 — codex 구현 검토 #5)
    'yields': {'%': ('close',), 'bp': ('d1',)},
    'spread': {'bp': ('close',)},
    'global': {'%': ('chg',), '': ('close',), 'p': ('chg',)},
}
_DEFAULT_FIELDS = {'%': ('chg',), '': ('close',), '$': ('close',), '달러': ('close',),
                   '원': ('close',), '엔': ('close',)}
_CHANGE = {'chg', 'd1', 'w1'}
_LEVEL_UNITS = {'', '$', '달러', '원', '엔'}


def _fields(group, key, unit, a=None):
    if group == 'global' and key == 'VIX':
        return {'': ('close',), (a or {}).get('chg_unit', 'p'): ('chg',)}.get(unit, ())
    return _FIELDS.get(group, _DEFAULT_FIELDS).get(unit, ())


# ── 결과 ─────────────────────────────────────────────────────────────────

@dataclass
class Result:
    violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    table_cells: int = 0
    prose_judged: int = 0
    unverified: int = 0
    delegated: int = 0
    excluded: int = 0
    tokens_seen: int = 0
    delegated_by: dict = field(default_factory=dict)
    unverified_by: dict = field(default_factory=dict)
    skipped: bool = False
    independent: int = 0

    def summary(self):
        why = ', '.join(f'{k} {v}' for k, v in sorted(self.unverified_by.items(),
                                                      key=lambda x: -x[1]))
        dele = ', '.join(f'{k} {v}' for k, v in sorted(self.delegated_by.items()))
        return (f'number audit: 수치 {self.tokens_seen} — 표 칸 {self.table_cells} 대조 · '
                f'문장 판정 {self.prose_judged} · 미검증 {self.unverified}({why or "—"}) · '
                f'위임 {self.delegated}({dele or "—"}) · 제외(접힌 계산 근거) {self.excluded}')


# ── 문서 ─────────────────────────────────────────────────────────────────

_BLOCKS = {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'caption', 'figcaption', 'td', 'th', 'dt',
           'dd', 'blockquote', 'summary', 'div', 'section', 'table', 'tr', 'ul', 'ol', 'br', 'details',
           'article', 'header', 'footer', 'nav', 'main', 'aside', 'figure', 'pre'}
_SKIP_TAGS = {'script', 'style', 'title', 'head', 'svg', 'math'}
_META_DESC = {'description', 'og:description', 'twitter:description', 'og:title', 'twitter:title'}
_HIDE_STYLE = re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.I)


class _Stream(_Doc):
    """fund.gate 의 브라우저식 트리 + 보이는 텍스트를 블록 경계와 조상 목록과 함께 흘린다."""

    def __init__(self, html):
        self.stream = []
        self.hidden_text = []
        self.svg_text = []
        self.raw_tokens = 0      # 분류와 무관하게 본문의 모든 글 조각에서 센 수치(script·style 만 뺀다)
        self.extra = []          # (출처, 글) — 제목·meta 설명·대체 문구. 속성 순서와 무관하게 파서로 읽는다
        self._title = None
        super().__init__(html, '\x00no-block')

    def handle_starttag(self, tag, attrs):
        a = {k: (v or '') for k, v in attrs}
        if tag == 'meta' and (a.get('name') or a.get('property') or '').lower() in _META_DESC:
            self.extra.append(('meta', a.get('content', '')))
        if tag == 'img' and a.get('alt'):
            self.extra.append(('alt', a['alt']))
        if tag == 'title':
            self._title = []
        if tag in _BLOCKS:
            self.stream.append(None)
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'title' and self._title is not None:
            self.extra.append(('title', ''.join(self._title)))
            self._title = None
        if tag in _BLOCKS:
            self.stream.append(None)
        super().handle_endtag(tag)

    def handle_data(self, data):
        super().handle_data(data)
        if self._title is not None:
            self._title.append(data)
        stack = list(self.stack)
        in_body = any(n.tag == 'body' for n in stack)
        if in_body and not any(n.tag in ('script', 'style') for n in stack):
            self.raw_tokens += len(tokens(data))
        if any(n.tag in _SKIP_TAGS - {'svg', 'math'} for n in stack):
            return
        if any(n.tag in ('svg', 'math') for n in stack):
            if in_body:
                self.svg_text.append(data)
            return
        # 숨김을 접힘보다 먼저 본다 — <details hidden> 안 수치는 제외가 아니라 숨김이다(codex 재검토 #4)
        if any(_hidden_attr(n) for n in stack):
            if in_body:
                self.hidden_text.append(data)
            return
        # 접힌 details 는 모든 접힌 조상에 대해 그 직속 <summary> 안일 때만 보인다(중첩 포함)
        for i, n in enumerate(stack):
            if n.tag == 'details' and 'open' not in n.attrs and not (
                    len(stack) > i + 1 and stack[i + 1].tag == 'summary'):
                self.stream.append((data, stack, 'details'))
                return
        self.stream.append((data, stack, None))


_NONDISPLAY_BODY = {'textarea', 'xmp', 'select', 'option', 'optgroup', 'datalist', 'noscript', 'iframe',
                    'noembed', 'noframes', 'plaintext', 'object', 'template'}


def _hidden_attr(n):
    """접힌 details 말고 숨기는 것 — hidden 속성, 인라인 display:none·visibility:hidden, 표시하지 않는 요소."""
    return ('hidden' in n.attrs or bool(_HIDE_STYLE.search(n.attrs.get('style', '')))
            or n.tag in _NONDISPLAY_BODY)


def _children(doc):
    kids = {}
    for n in doc.nodes:
        if n.parent is not None:
            kids.setdefault(id(n.parent), []).append(n)
    return kids


def _sections(doc):
    """최상위 <section> 과 그 h2 제목. 섹션 안 h2 가 둘 이상이면 None(경계 위조)."""
    out = []
    for n in doc.nodes:
        if n.tag != 'section' or any(a.tag == 'section' for a in list(n.ancestors())[1:]):
            continue
        heads = [h for h in doc.nodes if h.tag == 'h2' and any(a is n for a in h.ancestors())]
        titles = [re.sub(r'\s+', ' ', ''.join(h.raw)).strip() for h in heads]
        out.append((n, titles[0] if titles else None, titles))
    return out


def _inside(node, anc):
    return any(a is anc for a in node.ancestors())


# ── 층 1 ─────────────────────────────────────────────────────────────────

def _cells(tr, kids):
    return [c for c in kids.get(id(tr), []) if c.tag in ('td', 'th')]


def _rows(table, kids):
    out = []
    stack = [table]
    while stack:
        n = stack.pop(0)
        for c in kids.get(id(n), []):
            if c.tag == 'tr':
                out.append(c)
            elif c.tag in ('thead', 'tbody', 'tfoot'):
                stack.append(c)
    return out


def _audit_table(spec, table, kids, market, res, owned):
    v = res.violations
    rows = _rows(table, kids)
    head = [r for r in rows if _cells(r, kids) and all(c.tag == 'th' for c in _cells(r, kids))]
    body = [r for r in rows if r not in head]
    if len(head) != 1:
        v.append(f'[{spec.section}] 표 머리 행이 {len(head)}개다 — 정확히 1개여야 한다')
        return
    for r in rows:
        for c in _cells(r, kids):
            if c.attrs.get('colspan', '1') not in ('', '1') or c.attrs.get('rowspan', '1') not in ('', '1'):
                v.append(f'[{spec.section}] 표에 colspan·rowspan 이 있다 — 화면 열과 검사 열이 갈린다')
                return
    ths = [c.plain() for c in _cells(head[0], kids)]
    keys = []
    for i, th in enumerate(ths[1:], 1):
        k = COLUMNS.get(_norm_label(th))
        if k is None:
            v.append(f'[{spec.section}] 표에 알 수 없는 열 「{th}」 — 지도에 없는 열은 싣지 않는다')
        keys.append(k)
    for k in spec.cols:
        if k not in keys:
            v.append(f'[{spec.section}] 표에 필수 열({k})이 없다')
    # 머리 괄호는 단위(bp) 또는 날짜(「11월 5일」)만 — 그 밖의 괄호는 날짜 검사를 피해 간다(codex #3)
    head_dates = {}
    for k, th in zip(keys, ths[1:]):
        par = _paren(th)
        if par is None or not k:
            continue
        if re.fullmatch(r'\d{1,2}월 \d{1,2}일', par):
            head_dates[k] = par
        elif par != 'bp':
            v.append(f'[{spec.section}] 열 머리 「{th}」 의 괄호는 단위(bp)나 날짜(「11월 5일」)만 쓴다')
    seen = {}
    for tr in body:
        cells = _cells(tr, kids)
        if not cells:
            continue
        label_raw = cells[0].plain()
        label = _norm_label(label_raw)
        key = spec.rows.get(label)
        if key is None:
            v.append(f'[{spec.section}] 표에 알 수 없는 행 「{label_raw}」')
            continue
        if key in seen:
            v.append(f'[{spec.section}] 표에 「{label}」 행이 두 번 있다')
            continue
        seen[key] = True
        akey = _GLOBAL_NAME.get(key, key)
        a = _asset(market, spec.group, akey)
        if len(cells) - 1 != len(keys):
            v.append(f'[{spec.section}] 「{label}」 행의 칸 수({len(cells) - 1})가 열 수({len(keys)})와 다르다')
        for col, cell in zip(keys, cells[1:]):
            dl = cell.attrs.get('data-label')
            if dl is not None and COLUMNS.get(_norm_label(dl)) != col:
                v.append(f'[{spec.section}] 「{label}」 행의 칸 data-label 「{dl}」 이 열 '
                         f'「{ths[keys.index(col) + 1] if col in keys else col}」 과 다른 열을 가리킨다')
            if col is None:
                continue          # 소유하지 않는다 — 그 칸 수치는 문장 층에서 미검증으로 센다(codex #9)
            owned.add(id(cell))
            _audit_cell(spec, label, col, cell, a, head_dates, res)
    for label, key in spec.rows.items():
        a = _asset(market, spec.group, _GLOBAL_NAME.get(key, key)) or {}
        if key not in seen and any(_num(a.get(c)) is not None for c in spec.cols):
            v.append(f'[{spec.section}] 표에 「{label}」 행이 없다(데이터에는 있다)')


def _audit_cell(spec, label, col, cell, a, head_dates, res):
    v = res.violations
    text = cell.plain()
    where = f'[{spec.section}] 「{label}」 {col_name(col)} 칸'
    if a is None:
        v.append(f'{where}: 데이터에 이 행이 없다')
        return
    if col == 'date':
        want = _md(a.get('date'))
        if text != want:
            v.append(f'{where} 「{text}」 — 데이터 기준일은 {want}')
        return
    want = a.get(col)
    if spec.group == 'global' and label == 'VIX' and col == 'chg':
        unit_ok = {a.get('chg_unit', 'p')}
    else:
        unit_ok = UNITS.get(col, {''})
    toks = tokens(text)
    if not toks and not re.search(r'\d', text):
        # 비운 칸·설명(「월물 교체로 비교 불가」)은 틀린 숫자가 아니다 — 지우기가 창작보다 낫다(규칙 3)
        if want is not None:
            res.warnings.append(f'경고(표): {where}을 비웠다(「{text}」) — 데이터 값 {_fmt(want)} 이 있다')
        return
    if len(toks) != 1 or toks[0].raw.strip() != text.translate(_WIDE).strip().rstrip('.'):
        v.append(f'{where} 「{text}」 — 칸에는 수치 하나만 쓴다')
        res.table_cells += len(toks)
        return
    t = toks[0]
    res.table_cells += 1
    if t.unit not in unit_ok:
        v.append(f'{where} 「{text}」 — 단위 「{t.unit or "없음"}」 는 이 열의 단위가 아니다')
        return
    if want is None:
        v.append(f'{where} 「{text}」 — 데이터에 값이 없다')
        return
    if not close_enough(t.value, t.decimals, want):
        v.append(f'{where} 「{text}」 — 데이터 {_fmt(want)}')
    hd = head_dates.get(col)
    if hd is not None:
        src = a.get('wk_date') if col == 'wk' else a.get('date')
        if _md(src) != hd:
            v.append(f'[{spec.section}] 열 머리 날짜 「{hd}」 가 「{label}」 기준일 {_md(src)} 과 다르다')


def col_name(col):
    return {'close': '종가', 'chg': '등락', 'date': '기준일', 'd1': '전일 변화', 'wk': '1주 전',
            'w1': '주간 변화'}.get(col, col)


# ── 층 3: 위임 증명 ─────────────────────────────────────────────────────

def _delegations(html, doc, sections, data, market, rd):
    """(노드, 위임처) 목록. 검사 함수가 같은 입력에서 위반 0 을 돌려줄 때만."""
    out = []
    by_title = {t: n for n, t, _ in sections if t}
    # 위임은 그 게이트가 실제로 비교한 자리만 — 섹션 전체가 아니다(codex 구현 검토 #4).
    # 섹터 기간 표: `spf-val` 칸(값을 데이터와 글자째 비교), 트렌드 유닛: `data-fund-board` 블록(다시 그린 것과 바이트 비교).
    sec = by_title.get('섹터 기간별 수익률')
    if sec is not None:
        from us.sector_perf_gate import check as sp_check, STRICT_FROM
        if rd >= STRICT_FROM and not sp_check(html, market):
            out += [(n, 'check_sector_perf') for n in _sector_vals_checked(doc, sec, market)]
    fund = by_title.get('트렌드 유닛 점검')
    board = data.get('fund_board')
    if fund is not None and isinstance(board, dict):
        from fund.gate import check as fund_check, EFFECTIVE as F_EFF
        if rd >= F_EFF and board.get('report_date') == rd and not fund_check(html, board, 'us', rd):
            out += [(n, 'check_fund') for n in doc.nodes
                    if 'data-fund-board' in n.attrs and _inside(n, fund)]
    mac = by_title.get('매크로')
    econ = data.get('econ_indicators')
    if mac is not None and isinstance(econ, dict):
        from us import macro_table_gate as mtg
        from us.macro_gate import section_macro
        part = section_macro(html)       # check_macro 가 자르는 그대로
        rows = (econ.get('indicators') or [])
        if part and rows and rd >= mtg.FIRST_SESSION and 'data-indicator=' in part and \
                not mtg.check_tables(part, rows, data.get('macro_metrics'), rd):
            out.append((mac, 'macro_table_gate'))
    return out


def _cls(n):
    return n.attrs.get('class', '').split()


def _sector_vals_checked(doc, sec, market):
    """섹터 기간 표에서 값을 **여기서 다시 맞춰 본** spf-val 노드 — 클래스만 붙인 문단은 위임하지 않는다
    (codex 재검토 #1). 구조: spf-block > spf-title(「1일 수익률」) + spf-row > spf-name + spf-val."""
    from us import sector_perf_gate as spg
    kids = _children(doc)
    perf = market.get('sector_performance') or {}
    titles = {f'{label} 수익률': key for key, label in spg.HORIZONS}
    out = []
    for blk in doc.nodes:
        if 'spf-block' not in _cls(blk) or not _inside(blk, sec):
            continue
        ch = kids.get(id(blk), [])
        head = [c for c in ch if 'spf-title' in _cls(c)]
        if len(head) != 1 or head[0].plain() not in titles:
            continue
        key = titles[head[0].plain()]
        for row in (c for c in ch if 'spf-row' in _cls(c)):
            rc = kids.get(id(row), [])
            names = [c for c in rc if 'spf-name' in _cls(c)]
            vals = [c for c in rc if 'spf-val' in _cls(c)]
            if len(names) != 1 or len(vals) != 1:
                continue
            sector = spg._LONG.get(names[0].plain(), names[0].plain())
            want = spg._num((perf.get(sector) or {}).get(key))
            if want is not None and vals[0].plain().replace('−', '-') == spg._fmt(want) + '%':
                out.append(vals[0])
    return out


def _macro_delegated_cell(stack, kids, html=''):
    """매크로 표에서 macro_table_gate 가 실제로 칸을 묶어 보는 자리: 표식 행의 Actual·Previous·추세.
    data-label 이 아니라 **열 위치**로 정한다 — 게이트가 머리 위치로 읽기 때문이다(codex 재검토 #2)."""
    td = next((n for n in reversed(stack) if n.tag == 'td'), None)
    tr = next((n for n in reversed(stack) if n.tag == 'tr'), None)
    table = next((n for n in reversed(stack) if n.tag == 'table'), None)
    if td is None or tr is None or table is None or 'data-indicator' not in tr.attrs:
        return False
    cells = _cells(tr, kids)
    if not any(c is td for c in cells):
        return False
    idx = next(i for i, c in enumerate(cells) if c is td)
    # 열 위치는 **게이트 자신의 함수로** 고른다 — 머리 정규화(공백 제거 등)를 따로 흉내 내면 「Act ual」 같은
    # 변형으로 둘이 다른 열을 고른다(codex 3·4차 #1). 같은 이름이 둘이면 게이트처럼 첫 열만.
    from us import macro_table_gate as mtg
    head = mtg._head(html[table.start:table.end or len(html)])
    if idx == mtg._header_index(head, mtg.TREND_HEADER):
        return 'all'          # 추세 칸은 계산 문자열과 통째로 비교한다(_same)
    if idx in {mtg._header_index(head, x) for x in ('Actual', 'Previous')} - {None}:
        # 게이트는 칸의 첫 수치만 읽는다(_printed — 앞 괄호를 건너뛰고 자기 정규식으로). 「첫 수치」를 따로
        # 흉내 내면 <br>·앞 괄호·「7523K」에서 둘이 다른 수를 고른다(codex 5·6차). 그래서 **수치가 정확히
        # 하나이고 게이트가 읽은 값과 같은 칸**만 위임하고, 나머지는 칸째 미검증이다.
        import html as _h
        raw = html[td.start:td.end or len(html)]
        # 태그를 공백으로 — <br> 로 나뉜 두 수치를 한 덩어리로 읽지 않는다
        text = re.sub(r'\s+', ' ', _h.unescape(re.sub(r'<[^>]*>', ' ', raw))).strip()
        toks = tokens(text)
        got = mtg._printed(raw)
        # 칸 글 전체가 그 수치 하나여야 한다 — 「- 7,523K」(부호와 숫자 사이 공백)는 화면에선 음수인데 둘 다
        # 양수로 읽는다(codex 7차 #2). K·M·B 는 수치 단위로 센다(7차 #1 「7,523K / 99K」).
        if len(toks) == 1 and toks[0].raw == text.translate(_WIDE) and got is not None and abs(got[0] - toks[0].value) < 1e-9:
            return 'all'
        return 'mixed'
    return None


# ── 층 2 ─────────────────────────────────────────────────────────────────

_SENT_END = re.compile(r'(?<=[다요음함됨임])\.(?=\s|$)|[。!?](?=\s|$)')


def _sentences(text):
    out, i = [], 0
    for m in _SENT_END.finditer(text):
        out.append(text[i:m.end()])
        i = m.end()
    if text[i:].strip():
        out.append(text[i:])
    return out


def _aliases_in(seg):
    hits = []
    taken = []
    for rx, target in ALIASES:
        for m in rx.finditer(seg):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            hits.append((m.start(), m.end(), target))
    return sorted(hits, key=lambda h: h[0])


_OWN_PARTICLE = re.compile(r'^(은|는|이|가|도|만|의|와|과|를|을)?\s*')
_OTHER_SUBJECT = re.compile(r'[가-힣A-Za-z]+(이|가|은|는|도)(\s|$)')


def _near(seg, end):
    """자산 이름 뒤에서 수치까지가 그 이름의 서술인가 — 짧고, 다른 주어나 괄호가 끼지 않는다."""
    gap = seg[end:]
    if len(gap) > 15:
        return False
    rest = _OWN_PARTICLE.sub('', gap, count=1)
    if '(' in rest and not rest.lstrip().startswith('('):
        return False
    return not _OTHER_SUBJECT.search(rest)


def _audit_sentence(sent, market, res, where, mode):
    toks = tokens(sent)
    if _REPORTED.search(sent):
        res.tokens_seen += len(toks)
        if toks:
            _unverified(res, '보도·인용 문장', len(toks))
        return
    prev_end, prev_bound, prev_reason = 0, None, None
    for t in toks:
        res.tokens_seen += 1
        seg = sent[prev_end:t.start]
        hits = _aliases_in(seg)
        targets = {h[2] for h in hits}
        target, reason = None, None
        if len(targets) == 1:
            target = next(iter(targets))
            if target is None:
                reason = '사전 밖 자산'
            elif not _near(seg, hits[-1][1]):
                target, reason = None, '자산과 수치 사이가 멀다'
        elif len(targets) > 1:
            reason = '자산 후보 둘 이상'
        elif prev_bound is not None and t.unit in _LEVEL_UNITS and prev_bound[1] in _CHANGE:
            target = prev_bound[0]
        else:
            reason = '자산 없음'
        # 「현물은 S&P -0.13%, 나스닥 -0.72%」 — 단서는 나열 전체에 걸린다
        if prev_reason == '시점·구간 단서' and len(re.sub(r'[\s,·및와과]', '', seg)) <= 8:
            reason, target = '시점·구간 단서', None
        after = sent[t.end:t.end + 12]
        nxt = next((u.start for u in toks if u.start > t.start), len(sent))
        tail = sent[t.end:min(nxt, t.end + 15)]
        if target is not None and (_CUES.search(seg) or _CUES.search(tail) or _TAIL_CUES.search(tail)):
            reason, target = '시점·구간 단서', None
        if target is not None and t.decimals == 0 and abs(t.value) >= 100 and abs(t.value) % 50 == 0:
            reason, target = '어림수', None
        prev_reason = reason
        if target is None:
            _unverified(res, reason)
            prev_end, prev_bound = t.end, None
            continue
        group, key = target
        a = _asset(market, group, key)
        fields = _fields(group, key, t.unit, a)
        if not fields or a is None:
            if group == 'global' and key == 'VIX' and t.unit == '%':
                _flag(res, mode, f'[{where}] 「{_clip(sent, t)}」 — VIX 등락은 % 가 아니라 p 로 쓴다')
                res.prose_judged += 1
            else:
                _unverified(res, '단위로 필드를 못 정함' if a is not None else '데이터에 없는 자산')
            prev_end, prev_bound = t.end, None
            continue
        res.prose_judged += 1
        direction = -1 if _DOWN.match(after) else (1 if _UP.match(after) else 0)
        ok, best = False, None
        for f in fields:
            want = a.get(f)
            if want is None:
                continue
            best = (f, want)
            if f in _CHANGE:
                if t.sign:
                    got = t.value
                elif direction:
                    got = direction * abs(t.value)
                else:
                    got, want = abs(t.value), abs(want)
            else:
                got = t.value
            if close_enough(got, t.decimals, want, double=True):
                ok, best = True, (f, want)
                break
        if not ok:
            f, want = best if best else (fields[0], None)
            _flag(res, mode, f'[{where}] 「{_clip(sent, t)}」 — {key} {col_name(f)} 데이터 '
                             f'{_fmt(want) if want is not None else "없음"}')
        prev_end, prev_bound = t.end, (target, fields[0])


def _clip(sent, t):
    a = max(0, t.start - 24)
    return re.sub(r'\s+', ' ', sent[a:t.end + 8]).strip()


def _flag(res, mode, msg):
    (res.violations if mode == 'block' else res.warnings).append(
        ('' if mode == 'block' else '경고(문장): ') + msg)


def _unverified(res, why, n=1):
    res.unverified += n
    res.unverified_by[why] = res.unverified_by.get(why, 0) + n


# ── 본체 ─────────────────────────────────────────────────────────────────

def audit(html, data, prose='warn', tables=True):
    market = data.get('market_data')
    if not isinstance(market, dict):
        raise InputError('market_data.json 이 없거나 객체가 아니다')
    rd = market.get('report_date')
    if not isinstance(rd, str) or not re.match(r'\d{4}-\d{2}-\d{2}$', rd):
        raise InputError(f'market_data.json 의 report_date 가 없거나 날짜가 아니다({rd!r})')
    res = Result()
    if rd < EFFECTIVE:
        res.skipped = True
        return res
    if prose not in ('warn', 'block'):
        raise InputError(f'prose 는 warn 또는 block 이다({prose!r})')

    doc = _Stream(html)
    kids = _children(doc)
    sections = _sections(doc)

    # 쪼갠 수치·숨긴 수치
    body_at = html.find('<body')
    split = numbers_split_by_tags(html[body_at:] if body_at >= 0 else html)
    for s in split:
        res.violations.append(f'수치가 태그·보이지 않는 문자로 쪼개져 있다({s[:30]!r}) — 화면과 검사가 '
                              f'다른 숫자를 읽는다')
    hidden = [t for d in doc.hidden_text for t in tokens(d)]
    for t in hidden:
        res.violations.append(f'숨긴 요소 안에 수치 「{t.raw}」 — 독자에게 안 보이는 수치는 싣지 않는다')
    svg = [t for d in doc.svg_text for t in tokens(d)]
    for t in svg:
        res.violations.append(f'SVG 안에 수치 「{t.raw}」 — 그림 속 글자는 대조할 수 없다(차트는 PNG 로 싣는다)')

    # 층 1 — 시장 섹션은 정확히 하나씩, 제목 h2 하나씩, 표는 지도에 있는 것만(codex 구현 검토 #1·#2).
    # 제목을 「채권 동향」으로 바꾸거나 h2 를 하나 더 넣어 표를 검사 밖으로 빼는 길을 막는다.
    owned = set()
    if tables:
        market_names = {spec.section for spec in TABLES}
        for n, title, titles in sections:
            for t in titles[1:]:
                if t in market_names:
                    res.violations.append(f'시장 섹션 제목 「{t}」 이 다른 섹션({title}) 안 소제목으로 있다 — '
                                          f'섹션 경계를 정할 수 없다')
        by_title = {}
        for n, title, nh in sections:
            if title:
                by_title.setdefault(title, []).append(n)
        market_secs = set()
        for name in dict.fromkeys(spec.section for spec in TABLES):
            secs = by_title.get(name, [])
            if len(secs) != 1:
                res.violations.append(f'「{name}」 섹션이 {len(secs)}개다 — 정확히 1개여야 한다'
                                      f'(제목은 「{name}」 그대로)')
                continue
            market_secs.add(id(secs[0]))
            mapped = []
            for spec in (x for x in TABLES if x.section == name):
                found = []
                for n in doc.nodes:
                    if n.tag == 'table' and _inside(n, secs[0]):
                        head = [c for r in _rows(n, kids) for c in _cells(r, kids) if c.tag == 'th']
                        if head and _norm_label(head[0].plain()) == spec.first:
                            found.append(n)
                if len(found) != 1:
                    res.violations.append(f'[{spec.section}] 「{spec.first}」 표가 {len(found)}개다 — '
                                          f'정확히 1개여야 한다')
                    continue
                mapped.append(found[0])
                _audit_table(spec, found[0], kids, market, res, owned)
            for n in doc.nodes:
                if n.tag == 'table' and _inside(n, secs[0]) and not any(n is m for m in mapped):
                    res.violations.append(f'[{name}] 지도에 없는 표가 있다 — 시장 섹션의 표는 정해진 표만 싣는다')

    # 층 3
    deleg = _delegations(html, doc, sections, data, market, rd)

    # 층 2 — 블록마다 텍스트를 모아 문장으로
    def where_of(stack):
        for n, title, _ in sections:
            if any(s is n for s in stack):
                return title or '제목 없는 섹션'
        return '섹션 밖'

    block, ctx = [], None

    def flush():
        nonlocal block, ctx
        if not block:
            return
        text = ''.join(block)
        stack, kind = ctx
        if kind == 'owned':
            pass
        elif kind == 'details':
            res.excluded += len(tokens(text))
            res.tokens_seen += len(tokens(text))
        elif kind and kind.startswith('deleg:'):
            n = len(tokens(text))
            res.delegated += n
            res.tokens_seen += n
            res.delegated_by[kind[6:]] = res.delegated_by.get(kind[6:], 0) + n
        elif kind and kind.startswith('unv:'):
            n = len(tokens(text))
            res.tokens_seen += n
            _unverified(res, kind[4:], n)
        else:
            w = where_of(stack)
            for s in _sentences(text):
                _audit_sentence(s, market, res, w, prose)
        block, ctx = [], None

    for item in doc.stream:
        if item is None:
            flush()
            continue
        data_, stack, kind = item
        if kind is None:
            if any(id(n) in owned for n in stack):
                kind = 'owned'
            else:
                for node, who in deleg:
                    if any(s is node for s in stack):
                        if who == 'macro_table_gate':
                            how = _macro_delegated_cell(stack, kids, html)
                            if how == 'all':
                                kind = 'deleg:' + who
                            elif how == 'mixed':
                                kind = 'unv:매크로 칸(수치 둘 이상·형식 불일치)'
                        else:
                            kind = 'deleg:' + who
                        break
                if kind is None and any(n.tag == 'table' for n in stack) and \
                        where_of(stack) == '매크로':
                    kind = 'unv:매크로 표(예상치·표식 없는 행)'
                if kind is None and any('data-research-summary' in n.attrs
                                        or 'data-learning' in n.attrs for n in stack):
                    kind = 'unv:연구 원장'
                if kind is None and any('data-release' in n.attrs for n in stack):
                    kind = 'unv:지표 해부'
        if ctx is not None and (ctx[1] != kind):
            flush()
        if ctx is None:
            ctx = (stack, kind)
        block.append(data_)
    flush()

    # 표 칸 토큰 합계(소유 칸은 위 스트림에서 건너뛰었다)
    res.tokens_seen += res.table_cells

    # 제목·meta 설명·대체 문구 — 파서가 속성으로 읽었다(속성 순서·따옴표와 무관)
    for where, text in doc.extra:
        for s in _sentences(text):
            _audit_sentence(s, market, res, where, prose)

    # 독립 집계(codex #9, 재검토 #3): 분류 스트림이 아니라 파서가 본 **모든 글 조각**(숨김·SVG·접힘 포함,
    # script·style 만 뺀다)에서 다시 센 수와, 분류된 수 + 숨김 + SVG 가 같아야 한다
    indep = doc.raw_tokens + sum(len(tokens(s)) for _, text in doc.extra for s in _sentences(text))
    res.independent = indep
    classified = res.tokens_seen + len(hidden) + len(svg)
    if indep != classified:
        res.violations.append(f'수치 집계가 맞지 않는다(분류 {classified} · 원문 {indep}) — 검사기 결함이거나 '
                              f'블록 경계를 넘어 붙은 수치다')
    return res
