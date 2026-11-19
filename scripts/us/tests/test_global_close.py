"""세계 지수 종가 판정 — 네이버의 날짜 붙은 종가를 야후와 맞춰 본 것만 싣고, 아니면 「없음」.

수치는 2026-11-17~19 실측이다(네이버 세계 지수·야후 일봉과 시세).
"""
import datetime as dt
import threading
import time
import zoneinfo

import pytest

from scripts.us import global_close as gc
from scripts.us import session

RD = '2026-11-18'


def ep(tz, y, mo, d, h, mi, s=0):
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=zoneinfo.ZoneInfo(tz)).timestamp()


def nrow(stamp, close):
    return {'localTradedAt': stamp, 'closePrice': close}


def naver(*rows):
    return gc.parse_naver_rows([nrow(s, c) for s, c in rows])


def live(status, stamp):
    return gc.parse_naver_live({'marketStatus': status, 'localTradedAt': stamp})


# 18:20 ET = 00:20 CET — 유럽 자정 뒤 재수집. 야후 11-18 일봉이 비어 있다.
NOW = ep('America/New_York', 2026, 11, 18, 18, 20)
DAX_N = naver(('2026-11-18T17:35:00+01:00', '25,736.24'), ('2026-11-17T17:35:00+01:00', '26,045.37'),
              ('2026-11-16T17:35:00+01:00', '26,598.64'))
DAX_LIVE = live('CLOSE', '2026-11-18T17:35:00+01:00')
DAX_BLANK = [('2026-11-16', 26598.64), ('2026-11-17', 26045.37), ('2026-11-18', None)]
DAX_Q = {'price': 25736.24, 'date': '2026-11-18'}


def dax(n=DAX_N, lv=DAX_LIVE, bars=DAX_BLANK, q=DAX_Q, rd=RD, now=NOW, ticker='^GDAXI'):
    return gc.settle_close(ticker, n, lv, bars, q, rd, now)


def test_blank_yahoo_bar_no_longer_reverts_to_the_prior_session():
    r = dax()
    assert r['status'] == 'ok'
    assert (r['date'], r['close'], r['prev_close'], r['basis']) == (
        '2026-11-18', 25736.24, 26045.37, 'naver_close')
    assert r['xcheck'] == {'yahoo_close': 25736.24, 'yahoo_source': 'quote', 'yahoo_prev': 26045.37,
                           'prev_date': '2026-11-17'}
    assert gc.pct_of(r) == -1.19


def test_refilled_bar_is_the_cross_check():
    r = dax(bars=DAX_BLANK[:-1] + [('2026-11-18', 25736.24)], q=None)
    assert r['status'] == 'ok' and r['xcheck']['yahoo_source'] == 'bar'


def test_ftse_bar_rounded_to_one_decimal_still_matches():
    n = naver(('2026-11-18T16:35:00+00:00', '10,551.17'), ('2026-11-17T16:35:00+00:00', '10,689.87'))
    bars = [('2026-11-17', 10689.9), ('2026-11-18', 10551.2)]
    r = gc.settle_close('^FTSE', n, live('CLOSE', '2026-11-18T16:35:00+00:00'), bars, None, RD, NOW)
    assert r['status'] == 'ok' and r['close'] == 10551.17


def reason(r):
    assert r['status'] == 'missing'
    return r['reason']


def test_naver_behind_yahoo_is_missing_not_the_prior_session():
    # 네이버가 아직 11-18 을 안 올렸다. 야후의 빈 행이 「그 세션이 있었다」고 말한다.
    r = dax(n=naver(*[(x['date'] + 'T17:35:00+01:00', str(x['close'])) for x in DAX_N[1:]]),
            lv=live('CLOSE', '2026-11-17T17:35:00+01:00'))
    assert reason(r) == 'latest_session_disagree' and r['date'] == '2026-11-17'


def test_yahoo_quote_date_alone_proves_a_later_session():
    r = dax(n=naver(('2026-11-17T17:35:00+01:00', '26,045.37'), ('2026-11-16T17:35:00+01:00', '26,598.64')),
            lv=live('CLOSE', '2026-11-17T17:35:00+01:00'), bars=DAX_BLANK[:-1])   # 야후가 빈 행을 버렸다
    assert reason(r) == 'latest_session_disagree'


def test_yahoo_behind_naver_is_missing():
    assert reason(dax(bars=DAX_BLANK[:-1], q={'price': 26045.37, 'date': '2026-11-17'})) == \
        'latest_session_disagree'


def test_no_yahoo_value_for_the_session_is_missing():
    assert reason(dax(q=None)) == 'yahoo_no_value'
    assert reason(dax(q={'price': 26045.37, 'date': '2026-11-17'})) == 'yahoo_no_value'
    assert reason(dax(q={'price': None, 'date': '2026-11-18'})) == 'yahoo_no_value'


def test_values_that_differ_by_two_basis_points_are_missing():
    assert reason(dax(q={'price': 25736.24 * 1.0002, 'date': '2026-11-18'})) == 'value_disagree'
    assert dax(q={'price': 25736.24 * 1.00005, 'date': '2026-11-18'})['status'] == 'ok'


@pytest.mark.parametrize('bars', [
    [('2026-11-16', 26598.64), ('2026-11-17', None), ('2026-11-18', None)],        # 직전 일봉도 비었다
    [('2026-11-16', 26598.64), ('2026-11-18', None)],                              # 직전 행이 없다
    [('2026-11-16', 26598.64), ('2026-11-17', 26100.0), ('2026-11-18', None)],     # 값이 다르다
])
def test_previous_session_must_agree_in_both_sources(bars):
    assert reason(dax(bars=bars)) == 'previous_disagree'


def test_a_yahoo_session_between_p_and_s_means_the_change_would_span_two_sessions():
    n = naver(('2026-11-18T17:35:00+01:00', '25,736.24'), ('2026-11-16T17:35:00+01:00', '26,598.64'))
    assert reason(dax(n=n)) == 'previous_disagree'


def test_open_session_in_the_daily_list_is_not_a_close():
    assert reason(dax(lv=live('OPEN', '2026-11-18T15:00:00+01:00'))) == 'naver_session_open'
    assert reason(dax(lv=None)) == 'naver_session_open'
    assert reason(dax(lv=live('CLOSE', '2026-11-17T17:35:00+01:00'))) == 'naver_session_open'
    assert dax(lv=live('OPEN', '2026-11-19T09:05:00+01:00'))['status'] == 'ok'     # 다음 세션이 열렸다


def test_pre_auction_stamp_is_rejected_even_when_everything_else_agrees():
    n = naver(('2026-11-18T17:29:00+01:00', '25,736.24'), ('2026-11-17T17:35:00+01:00', '26,045.37'))
    assert reason(dax(n=n, lv=live('OPEN', '2026-11-19T09:05:00+01:00'))) == 'naver_stamp_before_close'


def test_stamp_after_now_is_rejected():
    assert reason(dax(now=ep('Europe/Berlin', 2026, 11, 18, 17, 34))) == 'naver_stamp_future'


def test_hang_seng_close_print_is_1608():
    def hsi(stamp):
        n = naver((f'2026-11-18T{stamp}+08:00', '23,294.75'), ('2026-11-17T16:08:36+08:00', '23,508.17'))
        bars = [('2026-11-17', 23508.17), ('2026-11-18', None)]
        return gc.settle_close('^HSI', n, live('CLOSE', '2026-11-18T16:08:28+08:00'), bars,
                               {'price': 23294.75, 'date': '2026-11-18'}, RD, NOW)
    assert hsi('16:08:28')['status'] == 'ok'
    assert reason(hsi('16:07:59')) == 'naver_stamp_before_close'


def test_unreadable_price_is_kept_and_makes_the_index_missing():
    # 최신 행의 값을 못 읽었다고 그 행을 버리면 뒤의 11-17 이 최신처럼 읽힌다.
    n = naver(('2026-11-18T17:35:00+01:00', 'N/A'), ('2026-11-17T17:35:00+01:00', '26,045.37'),
              ('2026-11-16T17:35:00+01:00', '26,598.64'))
    assert [r['date'] for r in n] == ['2026-11-18', '2026-11-17', '2026-11-16'] and n[0]['close'] is None
    r = dax(n=n, bars=DAX_BLANK[:-1], q={'price': 26045.37, 'date': '2026-11-17'})
    assert reason(r) == 'naver_unparseable' and r['date'] == '2026-11-18'
    # S 와 P 사이 세션의 값을 못 읽은 경우 — P 는 응답에서 S 바로 다음 행이라 건너뛸 수 없다.
    n = naver(('2026-11-18T17:35:00+01:00', '25,736.24'), ('2026-11-17T17:35:00+01:00', ''),
              ('2026-11-16T17:35:00+01:00', '26,598.64'))
    assert reason(dax(n=n, bars=[('2026-11-16', 26598.64), ('2026-11-18', None)])) == 'naver_unparseable'


def test_unreadable_stamp_voids_the_whole_list():
    assert gc.parse_naver_rows([nrow('2026-11-18T17:35:00+01:00', '1'), nrow('garbage', '2')]) == gc.UNPARSEABLE
    assert gc.parse_naver_rows([nrow('2026-11-18T17:35:00', '1')]) == gc.UNPARSEABLE     # 오프셋 없음
    assert reason(dax(n=gc.UNPARSEABLE)) == 'naver_unparseable'
    assert gc.parse_naver_rows({'error': 1}) is None and gc.parse_naver_rows([]) is None


def test_fetch_failures_and_shape_problems_are_missing():
    assert reason(dax(n=None)) == 'naver_fetch_failed'
    assert reason(dax(bars=None)) == 'yahoo_fetch_failed'
    assert reason(dax(n=DAX_N[:1])) == 'naver_no_previous'
    assert reason(dax(n=list(reversed(DAX_N)))) == 'naver_unordered'
    assert reason(dax(ticker='^UNKNOWN')) == 'unknown_index'
    dup = DAX_BLANK[:-1] + [('2026-11-18', 25736.24), ('2026-11-18', 25000.0)]
    assert reason(dax(bars=dup)) == 'yahoo_fetch_failed'


def test_exchange_holiday_keeps_the_older_session_with_its_own_date():
    # 11-18 이 그 거래소 휴장이면 두 원천 모두 11-17 을 최신으로 말한다.
    n = naver(('2026-11-17T17:35:00+01:00', '26,045.37'), ('2026-11-16T17:35:00+01:00', '26,598.64'))
    r = dax(n=n, lv=live('CLOSE', '2026-11-17T17:35:00+01:00'), bars=DAX_BLANK[:-1],
            q={'price': 26045.37, 'date': '2026-11-17'})
    assert (r['status'], r['date']) == ('ok', '2026-11-17')


def test_asia_at_us_collection_time_uses_the_report_date_session():
    # 17:34 ET = 도쿄 다음 날 07:34. 네이버 맨 앞은 11-18(장중인 11-19 는 목록에 없다).
    n = naver(('2026-11-18T15:45:03+09:00', '59,024.28'), ('2026-11-17T15:45:03+09:00', '58,860.43'))
    bars = [('2026-11-17', 58860.43), ('2026-11-18', None)]
    r = gc.settle_close('^N225', n, live('CLOSE', '2026-11-18T15:45:03+09:00'), bars,
                        {'price': 59024.28, 'date': '2026-11-18'}, RD,
                        ep('America/New_York', 2026, 11, 18, 17, 34))
    assert (r['status'], r['date'], gc.pct_of(r)) == ('ok', '2026-11-18', 0.28)


def test_asia_with_the_next_session_open_is_missing_until_yahoo_refills():
    # 19:30 ET = 도쿄 09:30. 야후 시세는 이미 11-19, 11-18 일봉은 아직 비었다 → 대조할 값이 없다.
    n = naver(('2026-11-18T15:45:03+09:00', '59,024.28'), ('2026-11-17T15:45:03+09:00', '58,860.43'))
    lv = live('OPEN', '2026-11-19T09:30:00+09:00')
    now = ep('Asia/Tokyo', 2026, 11, 19, 9, 31)
    bars = [('2026-11-17', 58860.43), ('2026-11-18', None), ('2026-11-19', 58895.82)]
    r = gc.settle_close('^N225', n, lv, bars, {'price': 58895.82, 'date': '2026-11-19'}, RD, now)
    assert reason(r) == 'yahoo_no_value'
    bars[1] = ('2026-11-18', 59024.28)                                              # 03:25 CET 무렵 채워진 뒤
    r = gc.settle_close('^N225', n, lv, bars, {'price': 58895.82, 'date': '2026-11-19'}, RD, now)
    assert (r['status'], r['date']) == ('ok', '2026-11-18')


def test_naver_rows_after_report_date_are_skipped_not_used():
    # 늦은 수집: 네이버가 이미 11-19 종가를 갖고 있어도 report_date(11-18) 세션을 싣는다.
    n = naver(('2026-11-19T15:45:03+09:00', '59,444.21'), ('2026-11-18T15:45:03+09:00', '59,024.28'),
              ('2026-11-17T15:45:03+09:00', '58,860.43'))
    bars = [('2026-11-17', 58860.43), ('2026-11-18', 59024.28), ('2026-11-19', 59444.21)]
    r = gc.settle_close('^N225', n, live('CLOSE', '2026-11-19T15:45:03+09:00'), bars,
                        {'price': 59444.21, 'date': '2026-11-19'}, RD,
                        ep('Asia/Tokyo', 2026, 11, 19, 18, 0))
    assert (r['status'], r['date'], r['close']) == ('ok', '2026-11-18', 59024.28)


# ── rows / missing ────────────────────────────────────────────────────────

def test_rows_and_missing_carry_reasons_and_never_a_number_for_a_missing_index():
    settle = {'^GDAXI': dax(), '^FTSE': gc._missing('value_disagree', RD)}
    rows, missing = gc.rows_and_missing(settle, session.EUROPE)
    assert [(r['name'], r['close'], r['pct'], r['date'], r['basis']) for r in rows] == [
        ('DAX', 25736.24, -1.19, RD, 'naver_close')]
    assert [(m['name'], m['ticker'], m['date'], m['reason']) for m in missing] == [
        ('FTSE100', '^FTSE', RD, 'value_disagree'), ('유로스톡스50', '^STOXX50E', None, 'naver_fetch_failed')]
    assert all(m['note_ko'] and 'close' not in m and 'pct' not in m for m in missing)


def test_every_reason_has_a_korean_note():
    import inspect
    import re
    src = inspect.getsource(gc)
    used = set(re.findall(r"_missing\('([a-z_]+)'", src))
    assert used and used <= set(gc.NOTE_KO)


def test_compute_uses_settle_and_never_the_history_rows():
    closes = {'^GDAXI': [26598.64, 26045.37], '^FTSE': [10881.6, 10689.9]}
    dates = {'^GDAXI': ['2026-11-16', '2026-11-17'], '^FTSE': ['2026-11-16', '2026-11-17']}
    md = {'indices': {'S&P 500': {'pct': -0.5}}}
    out = session.compute(closes, dates, md, {}, {}, RD, settle={'^GDAXI': dax()})
    eu = out['global_close']['europe']
    assert [r['date'] for r in eu['rows']] == [RD]                 # 이력의 11-17 행이 끼어들지 않는다
    assert [m['name'] for m in eu['missing']] == ['FTSE100', '유로스톡스50']
    assert eu['alignment'] is None                                 # 지수 하나로 지역을 판정하지 않는다
    asia = out['global_close']['asia']
    assert asia['rows'] == [] and len(asia['missing']) == 3


def test_compute_without_settle_keeps_the_history_path_for_old_callers():
    closes = {'^GDAXI': [100.0, 101.0], '^FTSE': [100.0, 102.0]}
    dates = {'^GDAXI': ['2026-11-17', RD], '^FTSE': ['2026-11-17', RD]}
    out = session.compute(closes, dates, {}, {}, {}, RD)
    assert len(out['global_close']['europe']['rows']) == 2
    assert 'missing' not in out['global_close']['europe']


# ── collect: 어떤 실패도 「없음」으로 끝난다 ────────────────────────────────

def test_collect_settles_each_ticker_from_injected_fetchers():
    def nv(t, ctx):
        return (DAX_N, DAX_LIVE) if t == '^GDAXI' else (None, None)

    def yh(t):
        if t == '^FTSE':
            raise RuntimeError('boom')
        return DAX_BLANK, DAX_Q
    out = gc.collect(['^GDAXI', '^FTSE', '^STOXX50E'], RD, now=NOW, naver=nv, yahoo=yh)
    assert out['^GDAXI']['status'] == 'ok'
    assert reason(out['^FTSE']) == 'naver_fetch_failed'
    assert reason(out['^STOXX50E']) == 'naver_fetch_failed'


def test_collect_abandons_a_fetch_that_never_returns():
    gate = threading.Event()
    t0 = time.monotonic()
    out = gc.collect(['^GDAXI', '^N225'], RD, now=NOW, wall_s=0.2,
                     naver=lambda t, ctx: gate.wait(30), yahoo=lambda t: (None, None))
    assert time.monotonic() - t0 < 2.0
    assert {r['reason'] for r in out.values()} == {'fetch_timeout'} and len(out) == 2
    gate.set()


def test_yahoo_frame_keeps_blank_closes():
    bars = gc.yahoo_frame_to_bars([dt.date(2026, 11, 17), dt.date(2026, 11, 18)], [26045.37, float('nan')])
    assert bars == [('2026-11-17', 26045.37), ('2026-11-18', None)]


def test_naver_live_parser():
    assert live('CLOSE', '2026-11-18T17:35:00+01:00') == {'status': 'CLOSE', 'date': '2026-11-18'}
    assert gc.parse_naver_live({'marketStatus': 'CLOSE', 'localTradedAt': 'x'}) is None
    assert gc.parse_naver_live({'localTradedAt': '2026-11-18T17:35:00+01:00'}) is None
    assert gc.parse_naver_live(None) is None
