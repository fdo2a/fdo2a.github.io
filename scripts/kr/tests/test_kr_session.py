from scripts.kr import session as ks


def test_us_prev_carries_its_own_as_of_and_session_lag():
    md = {'report_date': '2026-08-26',
          'indices': {'S&P 500': {'pct': 0.720325672650235}, 'Nasdaq': {'pct': 1.57},
                      'Dow': {'pct': 0.31}}}
    out = ks.us_prev(md, report_date='2026-08-28')
    assert out['as_of'] == '2026-08-26'
    assert out['lag_sessions'] == 2
    assert out['rows']['S&P 500'] == 0.72        # 원시 부동소수를 그대로 싣지 않는다


def test_us_prev_is_none_without_usable_input():
    assert ks.us_prev(None, report_date='2026-08-28') is None
    assert ks.us_prev({'indices': {}}, report_date='2026-08-28') is None


def test_kr_hours_window_converts_from_et_before_slicing():
    # 09:00~15:30 KST = 전날 20:00~당일 02:30 ET
    bars = [
        {'t': '2026-08-26T19:30:00-04:00', 'close': 100.0},   # 08:30 KST — 제외
        {'t': '2026-08-26T20:00:00-04:00', 'close': 101.0},   # 09:00 KST — 시작
        {'t': '2026-08-27T01:00:00-04:00', 'close': 103.0},   # 14:00 KST
        {'t': '2026-08-27T02:00:00-04:00', 'close': 102.0},   # 15:00 KST — 끝
        {'t': '2026-08-27T03:00:00-04:00', 'close': 999.0},   # 16:00 KST — 제외
    ]
    w = ks.kr_hours_window(bars, '2026-08-27')
    assert w['pct'] == 0.99          # 101.0 → 102.0
    assert w['bars'] == 3
    assert w['first_t'] == '09:00' and w['last_t'] == '15:00'


def test_kr_hours_window_needs_two_bars():
    assert ks.kr_hours_window([{'t': '2026-08-26T20:00:00-04:00', 'close': 1}],
                              '2026-08-27') is None
    assert ks.kr_hours_window(None, '2026-08-27') is None


def test_asia_peers_reports_kospi_relative_strength():
    peers = ks.asia_peers({'닛케이': -0.2, '항셍': -0.34}, kospi_pct=0.9)
    assert peers['avg_pct'] == -0.27
    assert peers['relative_pp'] == 1.17


def test_asia_peers_is_none_without_data():
    assert ks.asia_peers({}, kospi_pct=0.9) is None
    assert ks.asia_peers({'닛케이': -0.2}, kospi_pct=None) is None


def test_usdkrw_window_reports_the_regular_session():
    bars = [
        {'t': '2026-08-27T00:00:00+01:00', 'high': 1, 'low': 1, 'close': 1},   # 08:00 KST
        {'t': '2026-08-27T01:00:00+01:00', 'high': 1378.0, 'low': 1372.0, 'close': 1374.0},
        {'t': '2026-08-27T06:00:00+01:00', 'high': 1376.0, 'low': 1370.0, 'close': 1371.0},
    ]
    w = ks.usdkrw_window(bars, '2026-08-27')
    assert w['high'] == 1378.0 and w['high_t'] == '09:00'
    assert w['low'] == 1370.0 and w['low_t'] == '14:00'
    assert w['close'] == 1371.0


def test_asia_peers_keep_their_session_dates():
    peers = ks.asia_peers({'닛케이': (-0.2, '2026-08-27')}, kospi_pct=0.9)
    assert peers['dates']['닛케이'] == '2026-08-27'
    assert peers['rows']['닛케이'] == -0.2
