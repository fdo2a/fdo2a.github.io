"""일본 주간 — 코어 6 지표·신호 계산."""
from datetime import date, timedelta

from japan import core as C


def _days(start, n, f):
    d0 = date.fromisoformat(start)
    out = []
    i = 0
    while len(out) < n:
        d = d0 + timedelta(days=i)
        if d.weekday() < 5:
            out.append((d.isoformat(), f(len(out))))
        i += 1
    return out


def _snap():
    days = _days('2025-09-01', 280, lambda i: i)
    jgb = [{'date': d, '1Y': 1.0 + i * 0.002, '2Y': 1.2 + i * 0.004, '10Y': 2.5 + i * 0.002,
            '30Y': 3.5 + i * 0.003} for d, i in days]
    usd = [[d, 150 - i * 0.02] for d, i in days]
    fred = {'DGS2': [[d, 4.5] for d, _ in days], 'DGS10': [[d, 5.0] for d, _ in days],
            'DTB3': [[d, 4.0] for d, _ in days]}
    flows = [{'week_start': '2026-08-23', 'week_end': '2026-08-29', 'res_foreign_ltdebt_net': -100,
              'nonres_jp_equity_net': 100},
             {'week_start': '2026-08-30', 'week_end': '2026-09-05', 'res_foreign_ltdebt_net': -200,
              'nonres_jp_equity_net': -200},
             {'week_start': '2026-09-06', 'week_end': '2026-09-12', 'res_foreign_ltdebt_net': 1000,
              'nonres_jp_equity_net': -1500},
             {'week_start': '2026-09-13', 'week_end': '2026-09-19', 'res_foreign_ltdebt_net': -200,
              'nonres_jp_equity_net': 50}]
    cftc = {'097741': {'label': '엔 선물', 'rows': [
        {'date': '2026-09-08', 'lev_long': 10, 'lev_short': 20, 'nc_long': 5, 'nc_short': 1},
        {'date': '2026-09-15', 'lev_long': 30, 'lev_short': 20, 'nc_long': 9, 'nc_short': 1}]}}
    return {'jgb': jgb, 'fred': fred, 'mof_flows': flows, 'cftc': cftc,
            'prices': {'USD/JPY': {'daily': usd, 'weekly': usd}}, 'fetch_status': {}}


def test_week_bounds_come_from_the_iso_key():
    assert C.week_bounds('2026-W39') == ('2026-09-21', '2026-09-25')


def test_level_and_changes_use_only_dates_inside_the_windows():
    rows = [('2026-08-28', 1.0), ('2026-09-18', 1.5), ('2026-09-24', 1.6), ('2026-09-30', 9.9)]
    got = C.level_changes(rows, '2026-09-21', '2026-09-25')
    assert got['value'] == 1.6 and got['asof'] == '2026-09-24'
    assert got['chg_1w'] == 0.1 and got['chg_4w'] == 0.6


def test_flows_report_the_latest_week_and_the_four_week_sum_with_sign_words():
    f = C.flows(_snap(), '2026-09-25')
    assert f['week_end'] == '2026-09-19' and f['res_foreign_ltdebt_net'] == -200
    assert f['res_foreign_ltdebt_4w'] == 500 and f['res_foreign_ltdebt_4w_word'] == '순매수'
    assert f['res_foreign_ltdebt_word'] == '순매도'
    assert f['net_selling_weeks_of_4'] == 3


def test_flows_do_not_use_a_week_that_ends_after_the_report():
    snap = _snap()
    snap['mof_flows'].append({'week_start': '2026-09-27', 'week_end': '2026-10-03',
                              'res_foreign_ltdebt_net': 9999, 'nonres_jp_equity_net': 0})
    assert C.flows(snap, '2026-09-25')['week_end'] == '2026-09-19'


def test_hedged_treasury_is_labelled_an_approximation():
    h = C.hedged_ust(_snap(), '2026-09-25')
    # 헤지 비용 근사 = 미 3개월 - JGB 1년
    assert h['approx'] is True and h['hedge_cost'] == round(4.0 - h['jgb_1y'], 3)
    assert h['hedged_ust10'] == round(5.0 - h['hedge_cost'], 3)
    assert h['gap_vs_jgb10'] == round(h['hedged_ust10'] - h['jgb_10y'], 3)


def test_signals_tally_the_two_scenarios():
    d = C.build(_snap(), {'events': []}, '2026-W39')
    s = d['signals']
    assert set(s['tally']) == {'A', 'B', '중립'}
    assert sum(s['tally'].values()) == len(s['items'])
    jgb = next(i for i in s['items'] if i['key'] == 'jgb2y_4w')
    assert jgb['side'] == 'A'          # 2년물이 4주에 +bp → 인상 지속 쪽


def test_positioning_uses_the_last_report_on_or_before_the_week():
    p = C.yen_positioning(_snap(), '2026-09-25')
    assert p['date'] == '2026-09-15' and p['lev_net'] == 10 and p['lev_net_chg'] == 20
    assert p['nc_net'] == 8


def test_spread_uses_each_legs_latest_value_not_the_date_intersection():
    # 일본 연휴(9/21-23)로 이번 주 공통 날짜가 없으면 교집합 계산은 「변화 0」을 만든다.
    us = [('2026-09-18', 4.60), ('2026-09-23', 4.70)]
    jp = [('2026-09-18', 1.85), ('2026-09-24', 1.91)]
    got = C.leg_spread(us, jp, '2026-09-21', '2026-09-25', '미·일 2년 금리차')
    assert got['value'] == 2.79 and got['asof_us'] == '2026-09-23' and got['asof_jp'] == '2026-09-24'
    assert got['chg_1w_bp'] == 4.0


def test_us_legs_take_the_published_close_when_fred_lags():
    rows = [('2026-09-18', 5.0), ('2026-09-23', 5.05)]
    agg = {'end_date': '2026-09-25', 'yields': {'10Y': {'end': 5.12}}}
    assert C.with_published_close(rows, agg, '10Y')[-1] == ('2026-09-25', 5.12)
    assert C.with_published_close(rows, None, '10Y') == rows
