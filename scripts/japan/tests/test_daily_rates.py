"""일본 일간 금리 — MOF JGB(T+1)·BOJ API (codex 설계 검토 #4)."""
import pytest

from japan import daily_rates as R

ROWS = [
    {'date': '2026-10-21', '2Y': 1.60, '5Y': 1.85, '10Y': 2.30, '30Y': 3.90},
    {'date': '2026-10-22', '2Y': 1.63, '5Y': 1.86, '10Y': 2.31, '30Y': 3.92},
    {'date': '2026-10-23', '2Y': 1.642, '5Y': 1.872, '10Y': 2.325, '30Y': 3.904},
]

# 2026-10-27 00:04 KST 에 받은 FM01/STRDCLUCON 응답(일부).
CALL = {'STATUS': 200, 'RESULTSET': [{
    'SERIES_CODE': 'STRDCLUCON', 'NAME_OF_TIME_SERIES': 'Call Rate, Uncollateralized Overnight, Average (Daily)',
    'UNIT': 'percent per annum', 'FREQUENCY': 'DAILY', 'LAST_UPDATE': 20261026,
    'VALUES': {'SURVEY_DATES': [20261019, 20261020, 20261021, 20261022, 20261024],
               'VALUES': [1.227, 1.228, 1.227, 1.227, None]}}]}


def test_jgb_uses_prev_session_row():
    got = R.jgb_block(ROWS, '2026-10-23')
    assert got['10Y']['value'] == 2.325 and got['10Y']['period'] == '2026-10-23'
    assert got['10Y']['prev_period'] == '2026-10-22'


def test_jgb_bp_against_previous_bond_day():
    got = R.jgb_block(ROWS, '2026-10-23')
    assert got['10Y']['chg_bp'] == 1.5 and got['2Y']['chg_bp'] == 1.2


def test_jgb_ignores_rows_after_prev_session():
    got = R.jgb_block(ROWS, '2026-10-22')
    assert got['10Y']['period'] == '2026-10-22'


def test_jgb_stale_returns_none():
    got = R.jgb_block(ROWS[:2], '2026-10-23')
    assert got['10Y'] is None and 'why' in got


def test_jgb_missing_tenor_is_none():
    rows = [dict(r) for r in ROWS]
    del rows[-1]['30Y']
    assert R.jgb_block(rows, '2026-10-23')['30Y'] is None


def test_boj_values_drop_null():
    got = R.boj_values(CALL)
    assert len(got) == 1
    s = got[0]
    assert s['code'] == 'STRDCLUCON' and s['freq'] == 'DAILY'
    assert s['points'][-1] == ['2026-10-22', 1.227] and len(s['points']) == 4


def test_boj_period_formats():
    assert R.period('MONTHLY', 202609) == '2026-09'
    assert R.period('QUARTERLY', 202602) == '2026Q2'
    assert R.period('DAILY', 20261022) == '2026-10-22'


def test_call_rate_lag_ok():
    got = R.call_rate(CALL, '2026-10-26')
    assert got['value'] == 1.227 and got['period'] == '2026-10-22'


def test_call_rate_too_old():
    assert R.call_rate(CALL, '2026-10-30') is None


def test_resolve_series():
    meta = {'RESULTSET': [{'SERIES_CODE': 'A', 'NAME_OF_TIME_SERIES': 'Corporate Goods Price Index, All commodities'},
                          {'SERIES_CODE': 'B', 'NAME_OF_TIME_SERIES': 'Export Price Index'}]}
    assert R.resolve_series(meta, r'^Corporate Goods Price Index, All commodities$') == 'A'
    assert R.resolve_series(meta, r'^Nothing$') is None


def test_resolve_series_ambiguous_raises():
    meta = {'RESULTSET': [{'SERIES_CODE': 'A', 'NAME_OF_TIME_SERIES': 'X index'},
                          {'SERIES_CODE': 'B', 'NAME_OF_TIME_SERIES': 'X index (yen basis)'}]}
    with pytest.raises(ValueError):
        R.resolve_series(meta, r'^X index')


# --- 네이버 당일 JGB (2026-10-29) ---------------------------------------------------------
S, P = '2026-10-28', '2026-10-27'
LEVELS = {'2Y': (1.880, 1.898), '5Y': (2.236, 2.269), '10Y': (2.788, 2.825), '30Y': (3.820, 3.879)}
READY = (S, '18:30')


def _payload(prev, now, stamp='15:25:40', extra=()):
    rows = [{'localTradedAt': f'{S}T{stamp}+09:00', 'closePrice': f'{now:.4f}', 'fluctuations': f'{now - prev:.4f}'},
            {'localTradedAt': f'{P}T15:28:53+09:00', 'closePrice': f'{prev:.4f}'},
            {'localTradedAt': '2026-10-26T15:29:58+09:00', 'closePrice': f'{prev - 0.01:.4f}'}]
    return {'result': list(extra) + rows}


def _payloads(**over):
    return {t: over.get(t) or _payload(*LEVELS[t]) for t in R.TENORS}


MOF = [{'date': P, '2Y': 1.888, '5Y': 2.246, '10Y': 2.829, '30Y': 3.895}]


def test_naver_same_day_block():
    got, why, check = R.jgb_naver(_payloads(), S, P, READY, MOF)
    assert why is None and check == 'ok'
    assert got['10Y'] == {'value': 2.825, 'period': S, 'prev_period': P, 'chg_bp': 3.7,
                          'unit': '%', 'source': 'naver'}


def test_naver_rejected_before_close_is_visible():
    # 2시간 지연 — 16:30 예약 실행은 장중 행을 받는다(codex 설계 검토 #2)
    got, why, _ = R.jgb_naver(_payloads(), S, P, (S, '16:30'), MOF)
    assert got is None and '확정' in why
    assert R.naver_ready(S, ('2026-10-29', '00:10'))


def test_naver_intraday_stamp_rejected():
    got, why, _ = R.jgb_naver(_payloads(**{'30Y': _payload(3.82, 3.879, stamp='14:30:00')}), S, P, READY, MOF)
    assert got is None and '마감 전' in why


def test_naver_missing_prev_day_in_all_tenors_rejected():
    # 네 만기 모두 직전 세션이 빠지면 build_curve 의 공백 검사는 못 본다(codex 설계 검토 #1)
    drop = {t: {'result': [r for r in _payload(*LEVELS[t])['result'] if not r['localTradedAt'].startswith(P)]}
            for t in R.TENORS}
    got, why, _ = R.jgb_naver(drop, S, P, READY, MOF)
    assert got is None and P in why


def test_naver_nan_and_duplicate_rows_rejected():
    nan = _payload(2.788, 2.825)
    nan['result'][0]['closePrice'] = 'nan'
    assert R.jgb_naver(_payloads(**{'10Y': nan}), S, P, READY, MOF)[0] is None
    dup = _payload(2.788, 2.825, extra=[{'localTradedAt': f'{S}T15:29:00+09:00', 'closePrice': '2.9000'}])
    assert R.jgb_naver(_payloads(**{'10Y': dup}), S, P, READY, MOF)[0] is None


def test_naver_mof_mismatch_falls_back():
    bad = [dict(MOF[0], **{'30Y': 3.60})]       # 22bp — 만기 매핑 오류로 본다
    got, why, check = R.jgb_naver(_payloads(), S, P, READY, bad)
    assert got is None and check.startswith('mismatch') and '30Y' in why


def test_naver_mof_check_skip_is_recorded():
    got, _, check = R.jgb_naver(_payloads(), S, P, READY, None)
    assert got and check.startswith('skip')
    got, _, check = R.jgb_naver(_payloads(), S, P, READY, [dict(MOF[0], **{'30Y': None})])
    assert got and '30Y' in check


def test_naver_codes_fixed_to_tenors():
    assert R.NAVER_CODES == {'2Y': 'JP2YT=RR', '5Y': 'JP5YT=RR', '10Y': 'JP10YT=RR', '30Y': 'JP30YT=RR'}


def test_mof_fallback_needs_exact_previous_bond_day():
    rows = [ROWS[0], ROWS[2]]                       # 10/22 이 빠졌다
    got = R.jgb_block(rows, '2026-10-23', holidays=())
    assert got['10Y']['chg_bp'] is None and got['10Y']['source'] == 'mof'
    assert R.jgb_block(rows, '2026-10-23')['10Y']['chg_bp'] == 2.5   # holidays 없으면 예전 동작


def test_prev_business_skips_weekend_and_holiday():
    assert R.prev_business('2026-10-26') == '2026-10-23'
    assert R.prev_business('2026-10-13', ('2026-10-12',)) == '2026-10-09'


def test_naver_stamp_parsed_to_jst():
    # 다른 오프셋의 직전 행은 JST 날짜로 옮겨야 한다 — 23:25 -04:00 은 JST 다음 날 12:25(구현 검토 #5)
    moved = {t: _payload(*LEVELS[t]) for t in R.TENORS}
    moved['10Y']['result'][1]['localTradedAt'] = '2026-10-27T23:25:00-04:00'
    assert R.jgb_naver(moved, S, P, READY, MOF)[0] is None
    bad = {t: _payload(*LEVELS[t]) for t in R.TENORS}
    bad['2Y']['result'][0]['localTradedAt'] = f'{S}T99:99:00+09:00'
    got, why, _ = R.jgb_naver(bad, S, P, READY, MOF)
    assert got is None and '2Y' in why


def test_naver_intraday_prev_row_rejected():
    p = _payload(2.788, 2.825)
    p['result'][1]['localTradedAt'] = f'{P}T10:00:00+09:00'
    got, why, _ = R.jgb_naver(_payloads(**{'10Y': p}), S, P, READY, None)
    assert got is None and P in why and '마감 전' in why


def test_naver_chain_break_rejected():
    # 지표물 교체일 — 네이버 등락이 직전 행 종가와 이어지지 않는다(재검토 7차 #1)
    p = _payload(2.788, 2.825)
    p['result'][0]['fluctuations'] = '0.0070'
    got, why, _ = R.jgb_naver(_payloads(**{'10Y': p}), S, P, READY, MOF)
    assert got is None and '사슬' in why


def test_naver_1505_rows_rejected():
    for idx in (0, 1):
        p = _payload(2.788, 2.825)
        p['result'][idx]['localTradedAt'] = p['result'][idx]['localTradedAt'][:11] + '15:05:00+09:00'
        got, why, _ = R.jgb_naver(_payloads(**{'10Y': p}), S, P, READY, None)
        assert got is None and '마감 전' in why


def test_mof_check_compares_finite_tenors_despite_one_missing():
    bad = [dict(MOF[0], **{'2Y': 1.0, '30Y': None})]   # 2년 90bp 차이 + 30년 결측(재검토 7차 #2)
    got, _, check = R.jgb_naver(_payloads(), S, P, READY, bad)
    assert got is None and check.startswith('mismatch') and '2Y' in check


def test_naver_chain_tolerance_boundary():
    for fluct, ok in (('0.0995', True), ('0.1005', True), ('0.0994', False), ('0.1006', False)):
        p = _payload(1.900, 2.000)
        p['result'][0]['fluctuations'] = fluct
        got = R.jgb_naver(_payloads(**{'10Y': p}), S, P, READY, None)[0]
        assert (got is not None) == ok, fluct
