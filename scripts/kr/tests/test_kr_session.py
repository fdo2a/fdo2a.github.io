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


# ── 아시아 이웃 지수: 미국 수집기와 같은 판정 (2026-11-19) ────────────────────

def test_settle_peers_uses_the_shared_settle_and_never_a_prior_session():
    """자정 뒤 재수집에서 야후가 그날 일봉을 비워도 전 세션으로 돌아가지 않는다.

    11/18 실측: 첫 수집 닛케이 +0.28%(11-18) → 02:04 KST 재수집이 -1.34%(11-17)를 실었다.
    """
    from us import global_close as gc

    def nv(t, ctx):
        rows = {'^N225': [('2026-11-18T15:45:03+09:00', '59,024.28'), ('2026-11-17T15:45:03+09:00', '58,860.43')],
                '^HSI': [('2026-11-18T16:08:28+08:00', '23,294.75'), ('2026-11-17T16:08:36+08:00', '23,508.17')]}.get(t)
        if not rows:
            return None, None
        return (gc.parse_naver_rows([{'localTradedAt': s, 'closePrice': c} for s, c in rows]),
                gc.parse_naver_live({'marketStatus': 'CLOSE', 'localTradedAt': rows[0][0]}))

    def yh(t):
        if t == '^N225':      # 02:04 KST: 11-18 일봉이 비었고 시세가 그날 종가다
            return [('2026-11-17', 58860.43), ('2026-11-18', None)], {'price': 59024.28, 'date': '2026-11-18'}
        if t == '^HSI':       # 야후 값이 네이버와 다르다 → 싣지 않는다
            return [('2026-11-17', 23508.17), ('2026-11-18', 23000.0)], None
        return None, None

    import datetime as dt
    now = dt.datetime(2026, 11, 19, 2, 4, tzinfo=ks.KST).timestamp()
    peers, missing = ks.settle_peers(
        '2026-11-18', collect=lambda ts, rd: gc.collect(ts, rd, now=now, naver=nv, yahoo=yh))
    assert set(peers) == {'닛케이'}
    pct, date = peers['닛케이']
    assert (round(pct, 2), date) == (0.28, '2026-11-18')
    assert missing['항셍']['reason'] == 'value_disagree' and missing['항셍']['date'] == '2026-11-18'
    assert missing['상해종합']['reason'] == 'naver_fetch_failed'
    assert missing['대만가권']['reason'] == 'naver_fetch_failed'
    assert all(m['note_ko'] for m in missing.values())
    block = ks.asia_peers(peers, kospi_pct=1.0)
    assert block['rows'] == {'닛케이': 0.28} and block['dates'] == {'닛케이': '2026-11-18'}


def test_settle_peers_survives_a_collector_that_raises():
    def boom(ts, rd):
        raise RuntimeError('network down')
    peers, missing = ks.settle_peers('2026-11-18', collect=boom)
    assert peers == {} and set(missing) == {n for n, _ in ks.PEERS}


def test_every_peer_has_a_naver_code_and_a_close_time():
    from us import global_close as gc
    for _, t in ks.PEERS:
        assert t in gc.NAVER_CODES and t in gc.CLOSE_PRINT_LOCAL


def test_kr_collector_no_longer_takes_the_last_two_yahoo_rows():
    import os
    src = open(os.path.join(os.path.dirname(__file__), '..', '..', 'collect_kr_data.py'), encoding='utf-8').read()
    assert 'kr_session.settle_peers(report_date)' in src
    assert 'history(period="10d")["Close"].dropna()' not in src
    assert '"asia_peers_missing": peers_missing' in src
