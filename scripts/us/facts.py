"""US 칸 풀이기 — `data-ref="별칭:경로"` 를 자료 파일의 값·단위·관측일·상태로 (2026-11-20, 숫자 출처 검사).

**스키마 표에 없는 경로는 칸이 아니다**(U 「칸 없음」). 원본 JSON 잎은 숫자일 뿐이라 단위·부호·관측일·상태를 알 수 없다 —
경로 꼴마다 이 표가 정한다. 상태(설계 §3.1)는 값 대조 **전에** 정한다: 하나라도 어기면 invalid, 상태 자리가 없는 파일
(`ei`·`id`·`mv`, 이력 파일)은 받지 않는다 — 셋 다 U 「칸 무효」. 값으로 칸을 찾아 주는 함수는 두지 않는다(막을 것 12).

계산값(`dv:`)은 닫힌 연산만, 피연산자는 기본 칸만(깊이 1). 두 칸 연산은 같은 묶음 두 자산의 같은 필드이거나 한 자산의
두 날짜(last↔prev, level↔week_ago)여야 한다 — 칸 이름 글자가 아니라 이 표의 묶음·자산·필드로 판정한다.
① 재측정(11/12-18 다섯 편, 문장 수치 927): 자료 잎 그대로 874, 계산 20 남짓(WTI−브렌트 차, 성장−가치 차가 대부분),
어디에도 없음 16(보도된 확률·기간 상대수익 차 — 깊이 2) → 연산은 설계 그대로 두고 이력 연산은 상태 칸이 없어 늘 U.
설계: docs/superpowers/specs/2026-11-20-number-sources.md §3
"""
import json
import os
import re
from dataclasses import dataclass, field

ALIASES = {'md': 'market_data.json', 'id': 'intraday.json', 'ei': 'econ_indicators.json', 'mm': 'macro_metrics.json',
           'mv': 'movers.json', 'fb': 'fund_board.json', 'au': 'auctions.json', 'lq': 'liquidity/liquidity.json',
           'cal': 'calendar.json'}
NO_STATUS = frozenset({'id', 'ei', 'mv'})       # 상태 칸이 없는 파일 — 늘 U(설계 §3.1)
OPS2 = ('diff', 'sum', 'ratio', 'pctchg')
OPS_HIST = ('ret', 'chgbp', 'streak')
DATE_PAIRS = {frozenset({'last', 'prev'}), frozenset({'level', 'week_ago'})}

# 인쇄 단위 집합
PCT, PP, BP = frozenset({'%'}), frozenset({'%p'}), frozenset({'bp'})
IDX = frozenset({'', 'p'})
USD, KRW, JPY = frozenset({'', '달러'}), frozenset({'', '원'}), frozenset({'', '엔'})
NUM = frozenset({''})
RATIO = frozenset({'', '배'})
COUNT = frozenset({'', '건', '명', '개', '곳', '종'})
CUR = {'Micron': USD, 'Western Digital': USD, 'Seagate': USD, 'Nvidia': USD, 'Samsung Elec': KRW, 'SK hynix': KRW,
       'Samsung E-M': KRW, 'Murata': JPY, 'Taiyo Yuden': JPY, 'Yageo': NUM, 'Walsin': NUM, 'Holy Stone': NUM,
       'Sanhuan': frozenset({'', '위안'}), 'Fenghua': frozenset({'', '위안'})}
FX_UNITS = {'DXY': NUM, 'USD/KRW': KRW, 'USD/JPY': JPY, 'EUR/USD': USD}


@dataclass
class Fact:
    value: float
    units: frozenset
    signed: bool
    date: object
    status: str                      # current | stale | invalid
    why: str = ''
    alias: str = ''
    group: tuple = ()                # (별칭, 묶음, 필드) — 두 칸 연산의 관계 판정
    asset: str = ''
    fld: str = ''
    scale: float = 1.0               # 값 × scale = 인쇄 절대값(배율 포함)
    conv: dict = field(default_factory=dict)   # 다른 인쇄 단위 → 곱(예: %p 칸을 bp 로 ×100)


class Miss(Exception):
    """칸으로 풀지 못함 — kind: '칸 없음' | '칸 무효'."""

    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind, self.msg = kind, msg


def _key(s):
    return re.sub(r'[\s&]', '', str(s)).casefold()


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float('inf')


_SEG = re.compile(r'([^.\[\]]+)|\[([^\]]+)\]')


def _walk(obj, path):
    """경로 → (실제 열쇠들, 잎, 잎의 부모 사전, 지나온 사전들). 키는 공백·& 를 빼고 대소문자 없이. 둘 이상 맞으면 Miss."""
    keys, parents, cur = [], [], obj
    for m in _SEG.finditer(path):
        name, sel = m.group(1), m.group(2)
        if name is not None:
            if not isinstance(cur, dict):
                raise Miss('칸 없음', f'「{name}」 앞이 사전이 아니다')
            hit = [k for k in cur if _key(k) == _key(name)]
            if len(hit) != 1:
                raise Miss('칸 없음', f'열쇠 「{name}」 이 {len(hit)}개 맞는다')
            parents.append(cur)
            keys.append(hit[0])
            cur = cur[hit[0]]
        else:
            if not isinstance(cur, list):
                raise Miss('칸 없음', f'[{sel}] 앞이 목록이 아니다')
            hit = [it for it in cur if isinstance(it, dict) and any(
                _key(it.get(f)) == _key(sel) for f in ('id', 'key', 'name', 'label_ko', 'fred_id', 'term')
                if isinstance(it.get(f), str))]
            if len(hit) != 1:
                raise Miss('칸 없음', f'목록 항목 [{sel}] 이 {len(hit)}개 맞는다')
            parents.append(hit[0])
            keys.append('[]')
            cur = hit[0]
    return keys, cur, parents


class Book:
    """한 글의 자료 — datadir 의 파일들 + 글 날짜 + 이번 cycle 이 참조한 연구 원장 기록."""

    def __init__(self, datadir, date, ledger=None, cycle=None):
        self.datadir, self.date, self.cycle = datadir, date, cycle
        self._files = {}
        self._ledger = ledger           # [기록] | None(못 읽음)
        self.dv_used = []

    def file(self, alias):
        if alias not in self._files:
            try:
                with open(os.path.join(self.datadir, ALIASES[alias]), encoding='utf-8') as fh:
                    self._files[alias] = json.load(fh)
            except (OSError, ValueError):
                self._files[alias] = None
        return self._files[alias]

    # ── 기본 칸 ──
    def resolve(self, name):
        alias, _, path = name.partition(':')
        if alias == 'dv':
            return self._dv(path)
        if alias == 'rl':
            return self._rl(path)
        if alias not in ALIASES:
            raise Miss('칸 없음', f'모르는 별칭 「{alias}」')
        data = self.file(alias)
        if data is None:
            raise Miss('칸 무효', f'{ALIASES[alias]} 를 읽지 못했다')
        keys, leaf, parents = _walk(data, path)
        if not _num(leaf):
            raise Miss('칸 없음', '값이 숫자가 아니다')
        spec = SCHEMA[alias](keys, parents, data)
        if spec is None:
            raise Miss('칸 없음', '스키마 표에 없는 경로')
        if alias in NO_STATUS:
            raise Miss('칸 무효', f'{ALIASES[alias]} 에는 상태 칸이 없다')
        units, signed, group, asset, fld, scale, conv, date_of = spec
        bad = STATUS[alias](keys, parents, data, self.date)
        d = date_of if date_of else data.get('report_date')
        if bad:
            st = 'invalid'
        elif not isinstance(d, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d[:10]):
            st, bad = 'invalid', '관측일을 읽지 못했다'
        else:
            st = 'current' if d[:10] == self.date else 'stale'
        return Fact(float(leaf), units, signed, d, st, bad or '', alias, group, asset, fld, scale, conv)

    # ── 연구 원장 ──
    def _rl(self, path):
        if self._ledger is None:
            raise Miss('칸 무효', '연구 원장을 읽지 못했다')
        rid, _, rest = path.partition('.')
        by = {r.get('id'): r for r in self._ledger if isinstance(r, dict)}
        cyc = by.get(self.cycle)
        if cyc is None:
            raise Miss('칸 무효', '이번 cycle 기록이 원장에 없다')
        allowed = {self.cycle} | set(cyc.get('candidate_ids') or []) | set(cyc.get('reviewed_ids') or [])
        rec = by.get(rid)
        if rec is None or rid not in allowed:
            raise Miss('칸 무효', '이번 cycle 이 참조한 기록이 아니다')
        keys, leaf, parents = _walk(rec, rest)
        if not _num(leaf):
            raise Miss('칸 없음', '값이 숫자가 아니다')
        unit = parents[-1].get('unit') if parents and isinstance(parents[-1], dict) else None
        units = {'%': PCT, 'pct': PCT, 'bp': BP, '%p': PP, 'pp': PP, 'USD': USD, '$': USD}.get(unit, NUM)
        return Fact(float(leaf), units, True, rec.get('report_date'), 'current', '', 'rl', ('rl', rid, keys[-1]),
                    rid, keys[-1])

    # ── 계산값 ──
    def _dv(self, expr):
        m = re.fullmatch(r'([a-z]+)\((.*)\)', expr.strip())
        if not m:
            raise Miss('칸 없음', '계산값 꼴이 아니다 — dv:연산(인자,…)')
        op, args = m.group(1), [a.strip() for a in m.group(2).split(',')]
        if op in OPS_HIST:
            # 이력 파일(data/history/market.jsonl) 행에는 상태 칸이 없다 — 설계 §3.1 그대로 받지 않는다
            raise Miss('칸 무효', '이력 파일에는 상태 칸이 없다')
        if any(a.startswith('dv:') for a in args):
            raise Miss('칸 없음', '계산값의 피연산자는 기본 칸만(깊이 1)')
        if op in OPS2 or op == 'gap':
            if len(args) != 2:
                raise Miss('칸 없음', f'{op} 은 칸 둘')
            a, b = self.resolve(args[0]), self.resolve(args[1])
            st = _worse(a, b)
            if op == 'gap':
                if b.alias != 'rl':
                    raise Miss('칸 없음', 'gap 의 문턱은 rl: 칸이어야 한다')
                v, units, signed = a.value - b.value, (PP if a.units == PCT else a.units), True
            else:
                same_field = a.group == b.group and a.asset != b.asset
                two_dates = (a.alias, a.group[:2], a.asset) == (b.alias, b.group[:2], b.asset) and \
                    frozenset({a.fld, b.fld}) in DATE_PAIRS
                if not (same_field or two_dates):
                    raise Miss('칸 없음', '두 칸이 같은 묶음 같은 필드도, 한 자산의 두 날짜도 아니다')
                if op == 'diff':
                    v = a.value - b.value
                elif op == 'sum':
                    v = a.value + b.value
                elif op == 'ratio':
                    if b.value == 0:
                        raise Miss('칸 없음', '0 으로 나눈다')
                    v = a.value / b.value
                else:
                    if b.value == 0:
                        raise Miss('칸 없음', '0 으로 나눈다')
                    v = (a.value / b.value - 1) * 100
                units, signed = (a.units, True)
                conv = {}
                if op in ('diff', 'sum') and a.units == PCT:
                    # 수준이 % 인 칸(금리)의 차는 %p, bp 로도 쓴다. 등락률(%)의 차는 %p
                    units, conv = PP, {'bp': 100.0}
                if op == 'ratio':
                    units, conv = RATIO, {'%': 100.0}
                if op == 'pctchg':
                    units = PCT
                self.dv_used.append(f'{op}({args[0]},{args[1]})')
                return Fact(v, units, signed, a.date, st, '', 'dv', ('dv', op), '', op, a.scale if op in ('diff', 'sum') else 1.0, conv)
            self.dv_used.append(f'{op}({args[0]},{args[1]})')
            return Fact(v, units, signed, a.date, st, '', 'dv', ('dv', op), '', op, a.scale, {'bp': 100.0} if units == PP else {})
        if op == 'rank':
            if len(args) != 3:
                raise Miss('칸 없음', 'rank 는 (묶음, 필드, 키)')
            grp, fld, key = args
            alias, _, g = grp.partition(':')
            if alias != 'md':
                raise Miss('칸 없음', 'rank 는 md 묶음만')
            data = self.file('md')
            rows = (data or {}).get(g)
            if not isinstance(rows, dict):
                raise Miss('칸 없음', '묶음이 없다')
            vals = []
            for k in rows:
                f = self.resolve(f'md:{g}.{k}.{fld}')
                if f.status == 'invalid':
                    raise Miss('칸 무효', f'{k} 칸이 무효다')
                vals.append((k, f.value))
            target = [k for k, _ in vals if _key(k) == _key(key)]
            if len(target) != 1:
                raise Miss('칸 없음', '순위 키가 묶음에 없다')
            order = sorted(vals, key=lambda kv: -kv[1])
            rank = 1 + next(i for i, (k, _) in enumerate(order) if k == target[0])
            self.dv_used.append(f'rank({grp},{fld},{key})')
            return Fact(float(rank), frozenset({'위'}), False, data.get('report_date'), 'current'
                        if data.get('report_date') == self.date else 'stale', '', 'dv', ('dv', 'rank'), '', 'rank')
        raise Miss('칸 없음', f'모르는 연산 「{op}」')


def _worse(a, b):
    for st in ('invalid', 'stale'):
        if st in (a.status, b.status):
            return st
    return 'current'


# ── 스키마 표 ─────────────────────────────────────────────────────────────
# 함수마다 (열쇠들, 부모들, 파일) → (인쇄 단위, 부호 있음, 묶음, 자산, 필드, 배율, 변환, 관측일) | None

def _row_date(parents, data, *names):
    for p in reversed(parents):
        if isinstance(p, dict):
            for n in names or ('date', 'as_of'):
                if isinstance(p.get(n), str):
                    return p[n]
    return data.get('report_date')


def _md(keys, parents, data):
    k = tuple(keys)
    row = parents[-1] if parents else {}
    d = _row_date(parents[-1:], data)
    if len(k) == 3 and k[0] in ('indices', 'sectors', 'memory', 'ai_infra', 'mlcc'):
        g, asset, f = k
        lvl = IDX if g == 'indices' else (USD if g in ('sectors', 'ai_infra') else CUR.get(asset, NUM))
        if f == 'pct':
            return PCT, True, ('md', g, f), asset, f, 1.0, {}, d
        if f in ('last', 'chg'):
            return lvl, f == 'chg', ('md', g, f), asset, f, 1.0, {}, d
        return None
    if len(k) == 3 and k[0] in ('fx', 'commodities'):
        g, asset, f = k
        lvl = FX_UNITS.get(asset, NUM) if g == 'fx' else USD
        if f == 'pct':
            return PCT, True, ('md', g, f), asset, f, 1.0, {}, d
        if f in ('last', 'prev', 'chg'):
            dd = row.get('prev_date') if f == 'prev' else d
            return lvl, f == 'chg', ('md', g, f), asset, f, 1.0, {}, dd
        return None
    if len(k) == 3 and k[0] in ('yields', 'yields_fred'):
        g, asset, f = k
        if f in ('level', 'week_ago'):
            dd = row.get('week_ago_date') if f == 'week_ago' else d
            return PCT, False, ('md', g, f), asset, f, 1.0, {}, dd
        if f == 'bp':
            return BP, True, ('md', g, f), asset, f, 1.0, {}, d
        return None
    if len(k) == 3 and k[0] == 'sector_performance' and k[2] in ('1D', '1W', '1M', '6M', '1Y'):
        return PCT, True, ('md', k[0], k[2]), k[1], k[2], 1.0, {}, d
    if k in (('spread_2s10s_bp',), ('spread_5s30s_bp',), ('spread_2s10s_fred_bp',)):
        return BP, True, ('md', 'spread', k[0]), k[0], k[0], 1.0, {}, data.get('report_date')
    if len(k) == 4 and k[:2] == ('price_context', 'levels'):
        if k[3] == 'value':
            return (PCT if k[2] in ('10Y', '30Y', '2Y', '5Y') else (FX_UNITS.get(k[2]) or IDX | USD)), False, \
                ('md', 'levels', 'value'), k[2], 'value', 1.0, {}, data.get('report_date')
        if k[3] == 'percentile':
            return PCT, False, ('md', 'levels', 'percentile'), k[2], 'percentile', 1.0, {}, data.get('report_date')
        return None
    if len(k) == 4 and k[:2] == ('price_context', 'moves'):
        if k[3] == 'change':
            u = {'%': PCT, 'pp': PP, 'pt': IDX}.get(row.get('unit'))
            if u is None:
                return None
            return u, True, ('md', 'moves', 'change'), k[2], 'change', 1.0, ({'bp': 100.0} if u == PP else {}), \
                data.get('report_date')
        if k[3] == 'multiple':
            return RATIO, True, ('md', 'moves', 'multiple'), k[2], 'multiple', 1.0, {}, data.get('report_date')
        return None
    if k[:2] == ('price_context', 'cohesion') and len(k) == 3 and k[2] in ('top1_pct', 'top3_pct', 'percentile'):
        return PCT, False, ('md', 'cohesion', k[2]), '', k[2], 1.0, {}, data.get('report_date')
    if k[:2] == ('price_context', 'drivers') and len(k) == 4 and k[3] in ('share_pct', 'gap_pct', 'ratio_pct'):
        return PCT, False, ('md', 'drivers', k[3]), k[2], k[3], 1.0, {}, data.get('report_date')
    if k[:2] == ('price_context', 'sector_contribution') and k[-1] in ('index_change', 'residual') and len(k) == 3:
        return PCT if k[2] == 'index_change' else PP, True, ('md', 'contrib', k[2]), '', k[2], 1.0, {}, \
            data.get('report_date')
    if k[:3] == ('session', 'global_close', 'asia') or k[:3] == ('session', 'global_close', 'europe'):
        if len(k) == 6 and k[3] == 'rows' and k[5] in ('close', 'pct'):
            name = row.get('name', '')
            return (PCT if k[5] == 'pct' else IDX), k[5] == 'pct', ('md', 'global', k[5]), name, k[5], 1.0, {}, d
        return None
    if k[:2] == ('session', 'participation') and len(k) == 3 and k[2] in ('gap_pp', 'spy_pct'):
        return (PP if k[2] == 'gap_pp' else PCT), True, ('md', 'participation', k[2]), '', k[2], 1.0, {}, d
    if k[:3] == ('session', 'futures', 'gap') and len(k) == 4:
        return PCT, True, ('md', 'futures_gap', 'pct'), k[3], 'pct', 1.0, {}, data.get('report_date')
    if k[:2] == ('yield_drivers', 'rows') and len(k) == 4:
        if k[3] == 'level':
            return PCT, False, ('md', 'yd', 'level'), k[2], 'level', 1.0, {}, d
        if k[3] in ('chg_1d_bp', 'chg_5d_bp'):
            return BP, True, ('md', 'yd', k[3]), k[2], k[3], 1.0, {}, d
        return None
    if k[:2] == ('yield_drivers', 'decomposition') and len(k) == 4 and k[3].endswith('_bp'):
        return BP, True, ('md', 'decomp', k[3]), k[2], k[3], 1.0, {}, _row_date(parents[-1:], data, 'as_of')
    return None


def _mm(keys, parents, data):
    k = tuple(keys)
    rd = data.get('report_date')
    if k in (('growth_score',), ('inflation_score',), ('growth_diffusion',), ('inflation_diffusion',)):
        return NUM, True, ('mm', 'score', k[0]), '', k[0], 1.0, {}, rd
    if len(k) == 2 and k[0] == 'axis_scores':
        return NUM, True, ('mm', 'axis', 'score'), k[1], 'score', 1.0, {}, rd
    if len(k) == 3 and k[0] == 'axis_summary' and k[2] in ('score', 'support', 'improving', 'total'):
        return (NUM if k[2] == 'score' else COUNT), k[2] == 'score', ('mm', 'axis', k[2]), k[1], k[2], 1.0, {}, rd
    if len(k) >= 2 and k[0] == 'indicators' and k[1] == '[]':
        ind = parents[1] if len(parents) > 1 else {}
        f = k[-1]
        units = ind.get('units')
        base = {'%': (PCT, 1.0), 'K': (COUNT, 1e3), '': (COUNT, 1.0), '$B': (USD, 1e9)}.get(units)
        if base is None:
            return None
        u, sc = base
        if len(k) == 3 and f in ('actual', 'previous'):
            return u, True, ('mm', 'ind', f), ind.get('name', ''), f, sc, {}, rd
        if len(k) == 4 and k[2] == 'trend' and f in ('prior_avg', 'recent_avg'):
            return u, True, ('mm', 'ind', f), ind.get('name', ''), f, sc, {}, rd
        if len(k) == 3 and f in ('momentum_z', 'signed_z'):
            return NUM, True, ('mm', 'ind', f), ind.get('name', ''), f, 1.0, {}, rd
    return None


def _fb(keys, parents, data):
    k = tuple(keys)
    rd = data.get('report_date')
    if len(k) == 3 and k[0] == 'units' and k[1] == '[]':
        u = parents[1] if len(parents) > 1 else {}
        f = k[2]
        if f in ('ret_1m', 'ret_3m', 'ret_6m', 'ret_12m', 'rel_3m', 'mom_12_1', 'drawdown_52w', 'rel_3m_5d'):
            return PCT, True, ('fb', 'units', f), u.get('id', ''), f, 1.0, {}, u.get('as_of') or rd
        if f in ('vol_60', 'var_1d_90', 'var_1d_95'):
            return PCT, False, ('fb', 'units', f), u.get('id', ''), f, 1.0, {}, u.get('as_of') or rd
        if f == 'rel_3m_chg_pp':
            return PP, True, ('fb', 'units', f), u.get('id', ''), f, 1.0, {}, u.get('as_of') or rd
        if f in ('rank', 'rank_5d'):
            return frozenset({'위', ''}), False, ('fb', 'units', f), u.get('id', ''), f, 1.0, {}, u.get('as_of') or rd
        if f == 'beta_60':
            return NUM, False, ('fb', 'units', f), u.get('id', ''), f, 1.0, {}, u.get('as_of') or rd
        return None
    if k[:2] == ('market_regime', 'inputs') and len(k) == 3:
        if k[2] in ('ret_3m', 'drawdown'):
            return PCT, True, ('fb', 'regime', k[2]), '', k[2], 1.0, {}, parents[-1].get('as_of') or rd
        if k[2] in ('close', 'sma50', 'sma200', 'sma200_prev'):
            return USD, False, ('fb', 'regime', 'price'), k[2], 'price', 1.0, {}, parents[-1].get('as_of') or rd
        return None
    if k == ('market_regime', 'sessions_held'):
        return frozenset({'', '거래일', '일'}), False, ('fb', 'regime', 'held'), '', 'held', 1.0, {}, rd
    if k[:2] == ('liquidity', 'net') and len(k) == 3 and k[2] in ('level_bn', 'chg_4w_bn'):
        return USD, k[2] == 'chg_4w_bn', ('fb', 'liq', k[2]), '', k[2], 1e9, {}, parents[-1].get('date')
    if k[:2] == ('liquidity', 'nfci') and len(k) == 3 and k[2] in ('level', 'chg_4w'):
        return NUM, True, ('fb', 'nfci', k[2]), '', k[2], 1.0, {}, parents[-1].get('date')
    if k[0] == 'risk' and len(k) == 3:
        row = parents[-1]
        if k[1] == 'vix' and k[2] == 'level':
            return IDX, False, ('fb', 'risk', 'level'), 'vix', 'level', 1.0, {}, rd
        if k[1] == 'vix' and k[2] == 'percentile_2y':
            return PCT, False, ('fb', 'risk', 'pctile'), 'vix', 'pctile', 1.0, {}, rd
        if k[1] in ('hy_spread', 'real_10y') and k[2] == 'level':
            return PCT, False, ('fb', 'risk', 'level'), k[1], 'level', 1.0, {'bp': 100.0}, row.get('date')
        if k[1] in ('hy_spread', 'real_10y') and k[2] == 'chg_5d_bp':
            return BP, True, ('fb', 'risk', 'chg_5d_bp'), k[1], 'chg_5d_bp', 1.0, {}, row.get('date')
    return None


def _au(keys, parents, data):
    k = tuple(keys)
    if len(k) == 3 and k[0] in ('today', 'recent') and k[1] == '[]':
        row = parents[1]
        f = k[2]
        if f == 'bid_to_cover':
            return RATIO, False, ('au', k[0], f), row.get('key', ''), f, 1.0, {}, row.get('date')
        if f in ('indirect_pct', 'direct_pct', 'dealer_pct', 'high_yield'):
            return PCT, False, ('au', k[0], f), row.get('key', ''), f, 1.0, {}, row.get('date')
        if f in ('offering_amt', 'prev_offering_amt'):
            return USD, False, ('au', k[0], 'offering_amt'), row.get('key', ''), f, 1.0, {}, row.get('date')
        if f in ('dealer_vs_avg_pp', 'indirect_vs_avg_pp'):
            return PP, True, ('au', k[0], f), row.get('key', ''), f, 1.0, {}, row.get('date')
    if len(k) == 4 and k[0] in ('today', 'recent') and k[2] == 'avg6':
        row = parents[1]
        u = RATIO if k[3] == 'bid_to_cover' else PCT
        return u, False, ('au', 'avg6', k[3]), row.get('key', ''), k[3], 1.0, {}, row.get('date')
    if len(k) == 3 and k[0] == 'next' and k[2] == 'offering_amt':
        row = parents[1]
        return USD, False, ('au', 'next', 'offering_amt'), row.get('key', ''), 'offering_amt', 1.0, {}, \
            data.get('report_date')
    return None


def _cal(keys, parents, data):
    return None          # 일정표 숫자는 날짜·시각(X-코드)뿐이다 — 값 칸을 두지 않는다


def _lq(keys, parents, data):
    return None          # 유동성 표·문단은 기존 게이트가 맞춰 본다(T) — 문장용 칸은 아직 두지 않는다


def _none(keys, parents, data):
    return (NUM, True, (), '', '', 1.0, {}, data.get('report_date')) if keys else None


SCHEMA = {'md': _md, 'mm': _mm, 'fb': _fb, 'au': _au, 'cal': _cal, 'lq': _lq, 'id': _none, 'ei': _none, 'mv': _none}


# ── 상태(설계 §3.1) ───────────────────────────────────────────────────────
# (열쇠들, 부모들, 파일, 글 날짜) → 어긴 이유 | ''

def _st_md(keys, parents, data, date):
    if data.get('complete') is not True:
        return 'market_data complete 가 true 가 아니다'
    miss = data.get('missing')
    if not isinstance(miss, list):
        return 'market_data missing 을 읽지 못했다'
    # 수집기 꼴은 「묶음/이름[/문제]」(collect_market_data.py) — 같은 묶음 항목이 하나라도 있으면 그 묶음 칸을 받지 않는다(보수적)
    if any(not isinstance(m, str) or m.split('/')[0] == keys[0] for m in miss):
        return f'missing 에 {keys[0]} 항목이 있다'
    if keys[0] in ('fx', 'commodities'):
        row = parents[-1] if len(parents) > 2 else {}
        if row.get('basis') != 'close_1600_et':
            return '16:00 ET 기준(basis close_1600_et)이 아니다'
    if data.get('report_date') != date:
        return 'market_data 가 글 날짜 판이 아니다'
    return ''


def _st_mm(keys, parents, data, date):
    if data.get('book_state') != 'ok':
        return 'macro_metrics book_state 가 ok 가 아니다'
    if data.get('report_date') != date:
        return 'macro_metrics 가 글 날짜 판이 아니다'
    return ''


def _st_fb(keys, parents, data, date):
    if data.get('status') != 'ok':
        return 'fund_board status 가 ok 가 아니다'
    miss = data.get('missing')
    if not isinstance(miss, list):
        return 'fund_board missing 을 읽지 못했다'
    if keys[0] == 'units':
        u = parents[1] if len(parents) > 1 else {}
        if u.get('status') != 'ok':
            return '유닛 status 가 ok 가 아니다'
        if u.get('id') in miss:
            return 'missing 에 그 유닛이 있다'
    if keys[0] in miss:
        return f'missing 에 {keys[0]} 가 있다'
    return ''


def _st_au(keys, parents, data, date):
    if data.get('ok') is not True or data.get('complete') is not True:
        return 'auctions ok·complete 가 true 가 아니다'
    return ''


def _st_cal(keys, parents, data, date):
    if data.get('complete') is not True:
        return 'calendar complete 가 true 가 아니다'
    row = parents[1] if len(parents) > 1 else {}
    if row.get('status') != 'confirmed':
        return '일정 행이 confirmed 가 아니다'
    return ''


def _st_lq(keys, parents, data, date):
    return '' if data.get('status') == 'complete' else 'liquidity status 가 complete 가 아니다'


def _st_none(keys, parents, data, date):
    return '상태 칸이 없다'


STATUS = {'md': _st_md, 'mm': _st_mm, 'fb': _st_fb, 'au': _st_au, 'cal': _st_cal, 'lq': _st_lq,
          'id': _st_none, 'ei': _st_none, 'mv': _st_none}


def load_ledger(repo):
    """연구 원장 기록들 — 못 읽으면 None(rl: 칸은 「칸 무효」)."""
    try:
        import sys
        sys.path.insert(0, os.path.join(repo, 'scripts'))
        from common import research_ledger as RL
        return RL.read_records(os.path.join(repo, 'research', 'us'))
    except Exception:  # noqa: BLE001
        return None
