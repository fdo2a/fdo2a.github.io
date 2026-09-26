"""US 주간 인사이트 — 요약이 아니라 진단. 계산·표·조립은 코드가, 해석은 작성자가.

W38 까지 주간은 그 주 일간 5편을 다시 묶은 글이었다. 서사를 발행본에서만 뽑으니 일간이
놓친 것을 주간도 놓쳤다 — W38 은 원·달러 +3.35%·엔·달러 +2.15% 를 표에만 싣고 본문에서
한 번도 설명하지 않았다. 여기서는 그 주의 움직임을 **자기 변동성으로 나눠(z)** 이례적인
것을 코드가 먼저 고르고, 게이트가 「이건 설명하라」고 강제한다.

입력: 집계(`data/weekly/<KEY>.json` — 표 끝값의 정본, 불변식 그대로), 스냅샷
(`data/weekly_ext/<KEY>.json` — 변동성 기준선·포지션·연준 선물), 일정(`data/calendar.json`),
FOMC 일정. 순수 — 파일 I/O 는 `scripts/build_weekly_insight.py`.

작성자 계약: 본문은 `data-section` 절 여섯 개를 이 순서로 쓰고, 표 자리에 `<!--T:이름-->`
을 둔다. 조립이 표를 채운다(작성자는 표 숫자를 손으로 옮기지 않는다).
"""
import html as _html
import math
import re
from datetime import date, timedelta

from scripts.common import post_shell as S
from scripts.common import signcolor
from scripts.common.datelabel import range_ko

Z_FLAG = 2.0          # 이 이상이면 본문에서 반드시 다룬다
LOOKBACK = 52         # 변동성 기준선 주 수
MIN_WEEKS = 26        # 이보다 짧으면 z 를 매기지 않는다 — 표본 몇 개로 이례를 판정하지 않는다
CORR_WINDOW = 20

SECTIONS = ('question', 'diag', 'positioning', 'review', 'next', 'appendix')
PLACEHOLDERS = {'diag': ('anomalies', 'regime'), 'positioning': ('positioning', 'fed'),
                'next': ('next',), 'appendix': ('performance', 'daily')}

LABEL = {
    'S&P 500': 'S&P 500', 'Nasdaq': '나스닥', 'Dow': '다우', 'Russell 2000': '러셀 2000',
    'S&P 500 Growth': 'S&P 성장주', 'S&P 500 Value': 'S&P 가치주',
    # 「S&P 500 성장주」라 쓰면 기간 게이트가 「S&P 500」 별칭에 성장주 등락률을 붙여 읽는다.
    'DXY': '달러지수', 'USD/KRW': '원·달러', 'USD/JPY': '엔·달러', 'EUR/USD': '유로·달러',
    'WTI': 'WTI', 'Brent': '브렌트', 'Natural Gas': '천연가스', 'Gold': '금',
    'Technology': '기술', 'Energy': '에너지', 'Communication Services': '커뮤니케이션',
    'Consumer Discretionary': '경기소비재', 'Utilities': '유틸리티',
    'Consumer Staples': '필수소비재', 'Health Care': '헬스케어', 'Industrials': '산업재',
    'Financials': '금융', 'Materials': '소재', 'Real Estate': '부동산',
    '2Y': '2년물', '5Y': '5년물', '10Y': '10년물', '30Y': '30년물',
}
# 본문이 그 자산을 불렀다고 볼 이름들. 「금」은 「금리」「금융」에 걸리므로 조사를 붙인다.
ALIASES = {
    'S&P 500': ('S&P 500', 'S&P500', 'S&amp;P'), 'Nasdaq': ('나스닥',), 'Dow': ('다우',),
    'Russell 2000': ('러셀',), 'S&P 500 Growth': ('성장주',), 'S&P 500 Value': ('가치주',),
    'DXY': ('달러지수', '달러 지수', 'DXY'), 'USD/KRW': ('원·달러', '원달러', '원화'),
    'USD/JPY': ('엔·달러', '엔달러', '달러·엔', '엔화'), 'EUR/USD': ('유로',),
    'WTI': ('WTI', '유가'), 'Brent': ('브렌트', '유가'), 'Natural Gas': ('천연가스',),
    'Gold': ('금값', '금 가격', '금 선물', '금은', '금이', '금도', '금을', '금과'),
    'Technology': ('기술',), 'Energy': ('에너지',), 'Communication Services': ('커뮤니케이션',),
    'Consumer Discretionary': ('경기소비재', '임의소비재'), 'Utilities': ('유틸리티',),
    'Consumer Staples': ('필수소비재',), 'Health Care': ('헬스케어',), 'Industrials': ('산업재',),
    'Financials': ('금융',), 'Materials': ('소재',), 'Real Estate': ('부동산', '리츠'),
    '2Y': ('2년물',), '5Y': ('5년물',), '10Y': ('10년물',), '30Y': ('30년물',),
}
_FRED_YIELD = {'2Y': 'DGS2', '5Y': 'DGS5', '10Y': 'DGS10', '30Y': 'DGS30'}
_PRICE_GROUPS = ('indices', 'sectors', 'fx', 'commodities')


# ── 계산 ─────────────────────────────────────────────────────────────────────

def _stdev(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _week_last(rows):
    """[[date, v]] -> ISO 주의 마지막 관측만."""
    by = {}
    for d, v in rows:
        y, w, _ = date.fromisoformat(d).isocalendar()
        by[(y, w)] = (d, v)
    return [by[k] for k in sorted(by)]


def _baseline(rows, before, bp=False):
    """`before`(그 주 시작일) 이전 주간 변화들. 이번 주는 섞지 않는다."""
    wk = [(d, v) for d, v in _week_last(rows) if d < before]
    ch = []
    for (_, a), (_, b) in zip(wk, wk[1:]):
        if bp:
            ch.append((b - a) * 100)
        elif a:
            ch.append((b / a - 1) * 100)
    return ch[-LOOKBACK:]


def anomalies(agg, snap):
    """그 주 움직임 ÷ 직전 52주 주간 변동성. |z| 내림차순."""
    out = []
    start = agg['start_date']
    for group in _PRICE_GROUPS:
        for name, row in (agg.get(group) or {}).items():
            if not isinstance(row, dict) or row.get('pct') is None:
                continue
            series = ((snap.get('prices') or {}).get(name) or {}).get('weekly') or []
            ch = _baseline(series, start)
            sd = _stdev(ch) if len(ch) >= MIN_WEEKS else None
            if not sd:
                continue
            out.append(_anom(name, group, row['pct'], '%', sd))
    for tenor, sid in _FRED_YIELD.items():
        row = (agg.get('yields') or {}).get(tenor)
        rows = (snap.get('fred') or {}).get(sid) or []
        if not row or row.get('chg_bp') is None:
            continue
        ch = _baseline(rows, start, bp=True)
        sd = _stdev(ch) if len(ch) >= MIN_WEEKS else None
        if sd:
            out.append(_anom(tenor, 'yields', row['chg_bp'], 'bp', sd))
    out.sort(key=lambda r: -abs(r['z']))
    return out


def _anom(name, group, move, unit, sd):
    z = round(move / sd, 1)
    return {'name': name, 'label': LABEL.get(name, name), 'group': group,
            'move': round(move, 2 if unit == '%' else 1), 'unit': unit,
            'vol': round(sd, 2 if unit == '%' else 1), 'z': z, 'flagged': abs(z) >= Z_FLAG}


def curve_regime(d2, d10, flat=3.0):
    if abs(d2) < flat and abs(d10) < flat:
        return '보합'
    if d2 > 0 and d10 > 0:
        return '베어 플래트닝' if d2 > d10 else '베어 스티프닝'
    if d2 < 0 and d10 < 0:
        return '불 스티프닝' if d2 < d10 else '불 플래트닝'
    return '트위스트 플래트닝' if d2 > d10 else '트위스트 스티프닝'


def _corr(xs, ys):
    if len(xs) < 5:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 2)


def stock_bond_corr(snap, end):
    """S&P 500 일간 수익률 vs 10년물 일간 변화(bp). 최근 20일과 그 앞 20일."""
    spx = {d: v for d, v in ((snap.get('prices') or {}).get('S&P 500') or {}).get('daily') or []}
    ten = {d: v for d, v in (snap.get('fred') or {}).get('DGS10') or []}
    days = sorted(d for d in spx if d in ten and d <= end)
    pairs = []
    for a, b in zip(days, days[1:]):
        pairs.append(((spx[b] / spx[a] - 1) * 100, (ten[b] - ten[a]) * 100))
    now, prev = pairs[-CORR_WINDOW:], pairs[-2 * CORR_WINDOW:-CORR_WINDOW]
    return {'now': _corr(*zip(*now)) if now else None,
            'prev': _corr(*zip(*prev)) if prev else None, 'window': CORR_WINDOW}


def _jgb2y_change(snap, start, end):
    rows = [(r['date'], r.get('2Y')) for r in snap.get('jgb') or [] if r.get('2Y') is not None]
    before = [v for d, v in rows if d < start]
    upto = [v for d, v in rows if d <= end]
    if not before or not upto:
        return None
    return round((upto[-1] - before[-1]) * 100, 1)


def regime(agg, snap):
    y = agg.get('yields') or {}
    d2 = (y.get('2Y') or {}).get('chg_bp')
    d10 = (y.get('10Y') or {}).get('chg_bp')
    idx = agg.get('indices') or {}
    fx = agg.get('fx') or {}

    def pct(g, n):
        return (g.get(n) or {}).get('pct')

    out = {'curve': curve_regime(d2, d10) if d2 is not None and d10 is not None else None,
           'd2y_bp': d2, 'd10y_bp': d10,
           'corr': stock_bond_corr(snap, agg['end_date'])}
    g, v = pct(idx, 'S&P 500 Growth'), pct(idx, 'S&P 500 Value')
    out['growth_minus_value'] = round(g - v, 2) if g is not None and v is not None else None
    n, r = pct(idx, 'Nasdaq'), pct(idx, 'Russell 2000')
    out['nasdaq_minus_russell'] = round(n - r, 2) if n is not None and r is not None else None
    sec = [(k, s['pct']) for k, s in (agg.get('sectors') or {}).items()
           if isinstance(s, dict) and s.get('pct') is not None]
    if sec:
        best, worst = max(sec, key=lambda t: t[1]), min(sec, key=lambda t: t[1])
        out['sector_best'] = {'name': LABEL.get(best[0], best[0]), 'pct': round(best[1], 2)}
        out['sector_worst'] = {'name': LABEL.get(worst[0], worst[0]), 'pct': round(worst[1], 2)}
        out['sector_spread'] = round(best[1] - worst[1], 2)
    jgb = _jgb2y_change(snap, agg['start_date'], agg['end_date'])
    if jgb is not None and d2 is not None:
        out['jgb2y_bp'] = jgb
        out['usjp_2y_spread_chg_bp'] = round(d2 - jgb, 1)
    out['dxy_pct'] = pct(fx, 'DXY')
    out['usdjpy_pct'] = pct(fx, 'USD/JPY')
    return out


def _pct_rank(values, x):
    if not values:
        return None
    return round(100 * sum(1 for v in values if v <= x) / len(values))


def positioning(snap, end):
    out = []
    for code, c in (snap.get('cftc') or {}).items():
        rows = [r for r in c.get('rows') or [] if r['date'] <= end
                and r.get('lev_long') is not None and r.get('lev_short') is not None]
        if not rows:
            continue
        nets = [r['lev_long'] - r['lev_short'] for r in rows][-156:]
        last = rows[-1]
        row = {'code': code, 'label': c.get('label', code), 'date': last['date'],
               'lev_net': nets[-1], 'lev_net_chg': nets[-1] - nets[-2] if len(nets) > 1 else None,
               'pct_3y': _pct_rank(nets, nets[-1])}
        if last.get('nc_long') is not None and last.get('nc_short') is not None:
            row['nc_net'] = last['nc_long'] - last['nc_short']
        out.append(row)
    return out


def fed_path(snap, end, meetings):
    effr = [v for d, v in (snap.get('fred') or {}).get('EFFR') or [] if d <= end]
    base = effr[-1] if effr else None
    month = end[:7]
    contracts = []
    for c in snap.get('fedfunds') or []:
        if c['month'] <= month or base is None:
            continue
        row = {'month': c['month'], 'implied': round(c['implied'], 3),
               'bp_vs_effr': round((c['implied'] - base) * 100, 1)}
        if c.get('week_ago') is not None:
            row['chg_1w_bp'] = round((c['implied'] - (100 - c['week_ago'])) * 100, 1)
        contracts.append(row)
    nxt = [m for m in sorted(meetings) if m > end]
    return {'effr': base, 'contracts': contracts,
            'next_meeting': nxt[0] if nxt else None,
            'following_meeting': nxt[1] if len(nxt) > 1 else None}


_BILL = re.compile(r'\d+-Week')


def next_week(calendar, end, days=9):
    lo = date.fromisoformat(end)
    hi = (lo + timedelta(days=days)).isoformat()
    out = []
    for e in (calendar or {}).get('events') or []:
        d = e.get('date') or ''
        if not (end < d <= hi):
            continue
        if e.get('kind') == 'auction' and _BILL.search(e.get('name_ko', '')):
            continue
        out.append({k: e.get(k) for k in ('date', 'time_kst', 'kind', 'name_ko', 'watch')})
    return sorted(out, key=lambda e: (e['date'], e.get('time_kst') or ''))


_DAILY_SERIES = (('equities', 'S&P 500', '%'), ('bonds', '10년물', 'bp'),
                 ('fx', '달러지수', '%'), ('energy', 'WTI', '%'))


def daily_record(agg):
    """그 주 날짜별 주요 가격 — 집계의 일별 계열(발행본 종가)에서. 헤드라인을 다시 싣지 않는다
    (발행된 헤드라인의 표현을 고칠 수 없는데 문체 게이트는 표까지 본다)."""
    series = agg.get('series') or {}
    days = {}
    for key, label, unit in _DAILY_SERIES:
        rows = series.get(key) or []
        for (d0, a), (d1, b) in zip(rows, rows[1:]):
            if d1 < agg['start_date'] or d1 > agg['end_date'] or a in (None, 0) or b is None:
                continue
            chg = round((b - a) * 100, 1) if unit == 'bp' else round((b / a - 1) * 100, 2)
            days.setdefault(d1, {'date': d1})[label] = {'level': round(b, 3), 'chg': chg, 'unit': unit}
    return [days[d] for d in sorted(days)]


def build(agg, snap, calendar, meetings):
    return {
        'key': agg.get('key'), 'start_date': agg['start_date'], 'end_date': agg['end_date'],
        'z_flag': Z_FLAG, 'lookback_weeks': LOOKBACK,
        'anomalies': anomalies(agg, snap),
        'regime': regime(agg, snap),
        'positioning': positioning(snap, agg['end_date']),
        'fed': fed_path(snap, agg['end_date'], meetings),
        'next_week': next_week(calendar, agg['end_date']),
        'daily': daily_record(agg),
        'fetch_status': {k: v for k, v in (snap.get('fetch_status') or {}).items() if v != 'ok'},
    }


# ── 표 ───────────────────────────────────────────────────────────────────────

def _e(x):
    return _html.escape(str(x), quote=False)


def _signed(v, unit='', digits=2):
    if v is None:
        return '—'
    return f'{v:+.{digits}f}{unit}'


def _cv(v, text, invert=False):
    """표 칸의 부호 색. + 초록, - 빨강. **금리 계열은 반대**(invert) — 금리가 오르면 채권 가격은
    내린다(2026-09-26 사용자 지시). 0 이거나 값이 없으면 칠하지 않는다. 산문은 칠하지 않는다."""
    if v is None or v == 0:
        return text
    cls = 'pos' if (v > 0) != invert else 'neg'
    return f'<span class="{cls}">{text}</span>'


def _c(v, unit='', digits=2, invert=False):
    if v is None or round(v, digits) == 0:
        return _signed(v, unit, digits)
    return _cv(v, _signed(v, unit, digits), invert)


def _table(head, rows, caption=None):
    th = ''.join(f'<th>{_e(h)}</th>' for h in head)
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    cap = f'<p class="caption">{caption}</p>' if caption else ''
    return (f'<div class="tbl-scroll"><table><thead><tr>{th}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>{cap}')


def _t_anomalies(d):
    rows = []
    for a in d['anomalies'][:8]:
        digits = 2 if a['unit'] == '%' else 1
        bp = a['unit'] == 'bp'
        rows.append([_e(a['label']), _c(a['move'], a['unit'], digits, invert=bp),
                     f"{a['vol']:.{digits}f}{a['unit']}", _cv(a['z'], f"{a['z']:+.1f}", invert=bp),
                     '설명 필요' if a['flagged'] else ''])
    return _table(['자산', '주간 변화', '평소 주간 변동폭', '배수(z)', ''], rows,
                  f'평소 주간 변동폭은 직전 {d["lookback_weeks"]}주 주간 변화의 표준편차. '
                  f'배수 {d["z_flag"]:.1f} 이상은 평소보다 두 배 넘게 움직인 자산이다.')


def _t_regime(d):
    r = d['regime']
    rows = []
    if r.get('curve'):
        rows.append(['미 국채 커브', _e(r['curve']),
                     f"2년물 {_c(r['d2y_bp'], 'bp', 1, invert=True)} · 10년물 {_c(r['d10y_bp'], 'bp', 1, invert=True)}"])
    c = r.get('corr') or {}
    if c.get('now') is not None:
        prev = f" (직전 {c['window']}일 {c['prev']:+.2f})" if c.get('prev') is not None else ''
        rows.append(['주가·금리 상관', f"{c['now']:+.2f}",
                     f"대형주 지수 일간 수익률과 미 국채 장기물 일간 변화, 최근 {c['window']}일{prev}"])
    if r.get('growth_minus_value') is not None:
        rows.append(['성장주 − 가치주', _c(r['growth_minus_value'], '%p'), '대형주 스타일 지수'])
        # 설명 칸에 「S&P 500」을 쓰면 기간 게이트가 다음 행의 %p 를 그 지수 값으로 읽는다.
    if r.get('nasdaq_minus_russell') is not None:
        rows.append(['나스닥 − 러셀 2000', _c(r['nasdaq_minus_russell'], '%p'), '대형 기술주 대 소형주'])
    if r.get('sector_spread') is not None:
        rows.append(['섹터 격차', f"{r['sector_spread']:.2f}%p",
                     f"{_e(r['sector_best']['name'])} {_c(r['sector_best']['pct'], '%')} · "
                     f"{_e(r['sector_worst']['name'])} {_c(r['sector_worst']['pct'], '%')}"])
    if r.get('usjp_2y_spread_chg_bp') is not None:
        rows.append(['미·일 2년 금리차', _c(r['usjp_2y_spread_chg_bp'], 'bp', 1, invert=True),
                     f"JGB 2년 {_c(r['jgb2y_bp'], 'bp', 1, invert=True)} · 엔·달러 {_c(r.get('usdjpy_pct'), '%')}"])
    # 「일본 2년물」이라 쓰면 기간 게이트가 「2년물」을 미 국채로 읽고 값이 다르다며 막는다.
    return _table(['관계', '이번 주', '구성'], rows)


def _t_positioning(d):
    rows = []
    for p in d['positioning']:
        rows.append([_e(p['label']), _cv(p['lev_net'], f"{p['lev_net']:+,}"),
                     _cv(p['lev_net_chg'], f"{p['lev_net_chg']:+,}") if p.get('lev_net_chg') is not None else '—',
                     f"{p['pct_3y']}" if p.get('pct_3y') is not None else '—', _e(p['date'])])
    return _table(['선물', '레버리지 펀드 순포지션(계약)', '전주 대비', '3년 백분위', '기준일'], rows,
                  'CFTC 금융선물 보유 현황. 화요일 기준으로 금요일에 공개된다 — 수요일 이후의 '
                  '가격 움직임은 반영돼 있지 않다. 백분위 100은 3년 중 가장 순매수 쪽이다.')


def _t_fed(d):
    f = d['fed']
    rows = [[_e(c['month']), f"{c['implied']:.3f}%", _c(c['bp_vs_effr'], 'bp', 1, invert=True),
             _c(c.get('chg_1w_bp'), 'bp', 1, invert=True)] for c in f['contracts']]
    cap = f"실효 연방기금금리 {f['effr']:.2f}% 대비. 선물 가격에서 역산한 월평균 금리다" \
        if f.get('effr') is not None else '실효 연방기금금리를 받지 못했다'
    if f.get('next_meeting'):
        cap += f" — 다음 FOMC {f['next_meeting']}."
    return _table(['월물', '내재 금리', '실효금리 대비', '1주 변화'], rows, cap)


def _t_next(d):
    rows = [[_e(e['date']), _e((e.get('time_kst') or '')[-5:]), _e(e['name_ko']),
             _e(e.get('watch') or '')] for e in d['next_week']]
    return _table(['날짜', '시각(KST)', '일정', '볼 것'], rows)


_PERF_GROUPS = (('주식 지수', 'indices'), ('섹터', 'sectors'), ('환율', 'fx'), ('원자재', 'commodities'))


def _perf_rows(agg, g):
    items = [(k, v) for k, v in (agg.get(g) or {}).items()
             if isinstance(v, dict) and v.get('pct') is not None]
    if g == 'sectors':
        items.sort(key=lambda kv: kv[1].get('rank') or 99)
    return [[_e(LABEL.get(k, k)),
             f"{v['end']:,.2f}" if isinstance(v.get('end'), (int, float)) else '—',
             _c(v['pct'], '%')] for k, v in items]


def _t_performance(agg):
    """부록 성과표 — 자산군마다 표 하나(2026-09-26 사용자 지시 「자산군별로 구분이 가도록」)."""
    end = agg['end_date']
    out = []
    for title, g in _PERF_GROUPS[:1]:
        out.append((title, _table(['자산', f'종가({end})', '주간 등락'], _perf_rows(agg, g))))
    rows = [[_e(LABEL.get(t, t)), f"{v.get('end'):.3f}%", _c(v.get('chg_bp'), 'bp', 1, invert=True)]
            for t, v in (agg.get('yields') or {}).items()]
    out.append(('미 국채 금리', _table(['만기', f'금리({end})', '주간 변화'], rows)))
    for title, g in _PERF_GROUPS[1:]:
        out.append((title, _table(['자산', f'종가({end})', '주간 등락'], _perf_rows(agg, g))))
    baskets = []
    for key, label in (('memory', '메모리 5종목 바스켓'), ('ai_infra', 'AI 인프라 5종목 바스켓')):
        pct = (agg.get(key) or {}).get('basket_pct')
        if pct is not None:
            baskets.append([_e(label), _c(pct, '%')])
    if baskets:
        out.append(('테마 바스켓', _table(['바스켓', '주간 등락'], baskets)))
    body = ''.join(f'<h3>{t}</h3>{tbl}' for t, tbl in out)
    return body + '<p class="caption">종가와 주간 등락은 그 주 발행본에 실린 종가로 계산했다.</p>'


def _t_daily(diag):
    """일별 기록 — 자산군마다 표 하나."""
    out = []
    groups = (('주식', 'S&P 500'), ('채권', '10년물'), ('환율', '달러지수'), ('원자재', 'WTI'))
    for klass, label in groups:
        unit = next(u for _, lab, u in _DAILY_SERIES if lab == label)
        rows = []
        for r in diag.get('daily') or []:
            c = r.get(label)
            if not c:
                continue
            lvl = f"{c['level']:.3f}%" if unit == 'bp' else f"{c['level']:,.2f}"
            rows.append([_e(r['date']), lvl, _c(c['chg'], unit, 1 if unit == 'bp' else 2, invert=unit == 'bp')])
        if rows:
            out.append(f'<h3>{klass} — {_e(label)}</h3>' + _table(['날짜', '종가', '전일 대비'], rows))
    return ''.join(out) + '<p class="caption">그날 발행본에 실린 종가 기준.</p>'


def render_tables(diag, agg):
    return {'anomalies': _t_anomalies(diag), 'regime': _t_regime(diag),
            'positioning': _t_positioning(diag), 'fed': _t_fed(diag), 'next': _t_next(diag),
            'performance': _t_performance(agg), 'daily': _t_daily(diag)}


# ── 조립 ─────────────────────────────────────────────────────────────────────

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S)
_FORBIDDEN = ('<!doctype', '<html', '<head', '<body')


def sections(body):
    return [(m.group(1), m.group(2)) for m in _SEC.finditer(body)]


def validate_body(body):
    errs = []
    low = body.lower()
    for tag in _FORBIDDEN:
        if tag in low:
            errs.append(f'본문에 {tag}> 가 있다 — 문서 껍데기는 조립이 만든다')
    if len(re.findall(r'<h1\b', body)) != 1:
        errs.append('<h1> 은 머리 카드에 하나만 둔다')
    found = sections(body)
    names = [n for n, _ in found]
    for s in SECTIONS:
        if s not in names:
            errs.append(f'data-section="{s}" 절이 없다')
    present = [n for n in names if n in SECTIONS]
    if present != [s for s in SECTIONS if s in present]:
        errs.append(f'절 순서가 다르다: {" → ".join(present)} (정해진 순서 {" → ".join(SECTIONS)})')
    inner = dict(found)
    for sec, phs in PLACEHOLDERS.items():
        for ph in phs:
            tag = f'<!--T:{ph}-->'
            n = body.count(tag)
            if n != 1:
                errs.append(f'{tag} 가 {n}번 있다 — 한 번, {sec} 절 안에 둔다')
            elif sec in inner and tag not in inner[sec]:
                errs.append(f'{tag} 가 {sec} 절 밖에 있다')
    q = inner.get('question', '')
    for attr in ('data-alt', 'data-watch'):
        if not re.search(rf'<p\b[^>]*\b{attr}\b', q):
            errs.append(f'question 절에 <p {attr}> 문단이 없다')
    return errs


def assemble(body, meta, diag, agg):
    tables = render_tables(diag, agg)
    for name, frag in tables.items():
        body = body.replace(f'<!--T:{name}-->', frag)
    links = []
    n = 0

    def _id(m):
        nonlocal n
        n += 1
        h = _H2.search(m.group(0))
        if h:
            links.append(f'<a href="#read-{n}">{S.plain(h.group(1))}</a>')
        return m.group(0).replace('<section', f'<section id="read-{n}"', 1)

    body = _SEC.sub(_id, body)
    # 「빠른 이동」 목차는 apply_readability.py(reading-map-v1)가 넣는다. 여기서도 만들면 두 번 나온다.
    key, start, end = agg.get('key'), agg['start_date'], agg['end_date']
    url = f'https://fdo2a.github.io/weekly/{key}.html'
    title = S.escape(meta['title'].strip())
    summary = S.escape(meta['summary'].strip())
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{title}</title>\n<meta name="description" content="{summary}">\n'
        f'<link rel="canonical" href="{url}">\n<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="US Market Brief — 주간 인사이트 {range_ko(start, end)}">\n'
        f'<meta property="og:url" content="{url}">\n<meta property="og:description" content="{summary}">\n'
        f'{S.ADSENSE}\n<style>\n{S.css("us")}{signcolor.CSS}\n</style>\n{S.ANALYTICS}\n</head>\n'
        '<body data-layout="prose" data-register="da">\n'
        f'<div class="topbar"><span class="brand">US Market Brief</span>'
        f'<span class="date">주간 인사이트 · {range_ko(start, end)}</span></div>\n'
        f'<div class="container">\n{body}\n'
        '<footer class="disclaimer"><p>이 글은 그 주 발행본의 종가, 공개 시장 데이터(CFTC·연방기금금리 선물·'
        '재무성)와 계산한 진단을 바탕으로 썼다. 투자 판단의 참고 자료이며 투자 권유가 아니다.</p></footer>\n'
        '</div>\n</body>\n</html>\n')
