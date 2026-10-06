import datetime
import json

import pytest

from fund import core, render, universe


def series(n, daily, start=100.0):
    return [start * (1 + daily) ** i for i in range(n)]


def iso_days(n):
    d0 = datetime.date(2024, 1, 1)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


LAST = iso_days(600)[-1]


def histories(n=600):
    dates = iso_days(n)
    closes = {t: series(n, 0.0005) for t in universe.tickers()}
    closes['SMH'] = series(n, 0.002)
    return closes, {t: list(dates) for t in closes}


MARKET = {
    'report_date': LAST,
    'price_context': {'levels': {'VIX': {'value': 16.4, 'percentile': 35.7, 'sessions': 504}}},
    'yield_drivers': {'rows': {'hy_spread': {'level': 3.12, 'date': '2026-09-30', 'chg_5d_bp': 39.0},
                               'real_10y': {'level': 2.93, 'date': '2026-09-30', 'chg_5d_bp': 17.0}}},
}
FRED = {
    'WALCL': [('2026-09-02', 6_770_000), ('2026-09-09', 6_760_000), ('2026-09-16', 6_750_000),
              ('2026-09-23', 6_740_000), ('2026-09-30', 6_730_000)],
    'WDTGAL': [('2026-09-02', 815_000), ('2026-09-09', 820_000), ('2026-09-16', 825_000),
               ('2026-09-23', 830_000), ('2026-09-30', 835_000)],
    'RRPONTSYD': [('2026-09-02', 10.0), ('2026-09-30', 1.0)],
    'NFCI': [('2026-08-28', -0.47), ('2026-09-04', -0.46), ('2026-09-11', -0.45),
             ('2026-09-18', -0.44), ('2026-09-25', -0.43)],
}


def build(**over):
    closes, dates = histories()
    kw = dict(closes=closes, dates=dates, market=MARKET, fred=FRED,
              report_date=LAST, generated_at='2026-10-06 09:00 KST')
    kw.update(over)
    return core.build(**kw)


def test_contract_fields_and_ok_status():
    d = build()
    for k in ('schema_version', 'calculation_version', 'universe_version', 'report_date',
              'generated_at', 'status', 'missing', 'source_dates', 'market_regime',
              'liquidity', 'risk', 'units', 'rank_basis', 'var_meta'):
        assert k in d
    # no holiday file: the weaker majority calendar is used and the day says so
    assert d['status'] == 'partial'
    assert d['missing'] and d['missing'][0].startswith('calendar:')
    assert d['source_dates']['prices'] == LAST
    assert d['var_meta'] == {'lookback_sessions': 60, 'holding_sessions': 1,
                             'method': 'historical', 'quantile': 'linear'}
    json.dumps(d, allow_nan=False)


def test_unavailable_when_spy_missing_or_date_mismatch():
    closes, dates = histories()
    closes.pop('SPY')
    d = build(closes=closes, dates=dates)
    assert d['status'] == 'unavailable'
    assert d['missing']
    d2 = build(report_date='2099-01-01')
    assert d2['status'] == 'unavailable'
    assert any('report_date' in x for x in d2['missing'])


def test_partial_when_liquidity_missing():
    d = build(fred={})
    assert d['status'] == 'partial'
    assert any('liquidity' in x for x in d['missing'])


def test_nan_becomes_null():
    closes, dates = histories()
    closes['IGV'][-30] = float('nan')
    d = build(closes=closes, dates=dates)
    json.dumps(d, allow_nan=False)


def test_render_is_deterministic_and_carries_hash():
    d = build()
    a, b = render.board_html(d), render.board_html(json.loads(json.dumps(d)))
    assert a == b
    assert a.count('data-fund-board=') == 1
    assert f'data-fund-board="{core.digest(d)}"' in a
    assert f'data-report-date="{LAST}"' in a
    # four tables: risk-on, defensive, region, benchmark
    assert a.count('<table') == 4
    assert '방어 스타일' in a and '가격 기준(이익 수정 미반영)' in a
    assert '최근 60거래일 표본의 1일 VaR' in a


def test_render_unavailable_is_none():
    closes, dates = histories()
    closes.pop('SPY')
    assert render.board_html(build(closes=closes, dates=dates)) is None


def test_digest_changes_with_content():
    d = build()
    d2 = json.loads(json.dumps(d))
    d2['units'][0]['ret_1m'] = 99.0
    assert core.digest(d) != core.digest(d2)


def test_block_has_no_paragraphs_so_readability_does_not_count_it_as_prose():
    assert '<p' not in render.board_html(build())


def test_values_that_round_to_zero_carry_no_sign_or_colour():
    assert render._num(-0.04, 1, True, '%') == '0.0%'
    assert render._signed_cell(-0.04, 1, '%') == '<td>0.0%</td>'
    assert render._signed_cell(0.06, 1, '%') == '<td class="fb-p">+0.1%</td>'


def test_vix_window_label_follows_sessions():
    d = build()
    assert '최근 2년 중' in render.board_html(d)
    short = json.loads(json.dumps(d))
    short['risk']['vix']['sessions'] = 120
    a = render.board_html(short)
    assert '최근 2년' not in a and '최근 120거래일 중' in a


def test_caption_grammar():
    a = render.board_html(build())
    assert '바뀌었나다' not in a and '바뀌었는지를 뜻한다' in a


# --- codex 구현 재검토 재현: 독립 달력 ---

def weekdays(n, end=datetime.date(2026, 10, 5)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


def wk_histories(n=600):
    dates = weekdays(n)
    closes = {t: series(n, 0.0005) for t in universe.tickers()}
    closes['SMH'] = series(n, 0.002)
    return closes, {t: list(dates) for t in closes}


HOLIDAYS = {'valid_from': '2020-01-01', 'valid_through': '2030-12-31', 'dates': []}


def wk_build(closes, dates, **kw):
    return core.build(closes, dates, MARKET, FRED, dates['SPY'][-1], 't', holidays=HOLIDAYS, **kw)


def test_a_session_every_series_lost_is_still_a_session():
    c, d = wk_histories()
    gone = d['SPY'][-20]
    for t in c:
        k = d[t].index(gone)
        del c[t][k]
        d[t] = d[t][:k] + d[t][k + 1:]
    b = wk_build(c, d)
    assert b['status'] == 'partial'
    assert gone in b['market_regime']['missing_sessions']
    semis = next(u for u in b['units'] if u['id'] == 'semis')
    assert semis['vol_60'] is None and semis['ret_1m'] is not None


def test_tickers_outside_the_fund_do_not_vote_on_the_calendar():
    c, d = histories()
    base = build(closes=c, dates=d)
    for i in range(40):
        t = f'ZZ{i}'
        c[t] = series(600, 0.001)
        d[t] = d['SPY'][:-3] + ['2099-01-0%d' % j for j in (1, 2, 3)]
    b = build(closes=c, dates=d)
    assert b['rank_basis']['date'] == base['rank_basis']['date']
    semis = lambda x: next(u for u in x['units'] if u['id'] == 'semis')
    assert semis(b)['ret_3m'] == semis(base)['ret_3m']


def test_duplicate_date_hidden_by_nan_is_still_rejected():
    c, d = histories()
    d['SMH'] = list(d['SMH'])
    d['SMH'][-2] = d['SMH'][-3]
    c['SMH'][-2] = float('nan')
    b = build(closes=c, dates=d)
    assert any('SMH' in m for m in b['missing'])
    assert next(u for u in b['units'] if u['id'] == 'semis')['status'] == 'missing'


def test_fallback_majority_is_strict():
    from fund import board
    d = {'SPY': ['d1', 'd2'], 'SMH': ['d1', 'd2'], 'IGV': ['d1', 'd3'], 'XLI': ['d1', 'd3']}
    assert board.sessions(d) == ['d1']


def test_with_the_holiday_calendar_a_clean_day_is_ok():
    c, d = wk_histories()
    b = wk_build(c, d)
    assert b['status'] == 'ok' and b['missing'] == []
    assert b['rank_basis']['calendar'] == 'NYSE 휴장일 달력'
