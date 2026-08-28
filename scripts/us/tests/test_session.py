import datetime as dt

from scripts.us import session


def _dates(n, start='2026-08-20'):
    d0 = dt.date.fromisoformat(start)
    return [str(d0 + dt.timedelta(days=i)) for i in range(n)]


def test_region_rows_uses_last_session_on_or_before_report_date():
    closes = {'^N225': [100.0, 101.0, 99.0]}
    dates = {'^N225': _dates(3)}          # 08-20, 08-21, 08-22
    rows = session.region_rows(closes, dates, (('닛케이', '^N225'),), '2026-08-21')
    assert rows == [{'name': '닛케이', 'ticker': '^N225', 'close': 101.0,
                     'pct': 1.0, 'date': '2026-08-21'}]


def test_region_rows_drops_series_without_two_bars():
    closes = {'^N225': [100.0]}
    dates = {'^N225': ['2026-08-21']}
    assert session.region_rows(closes, dates, (('닛케이', '^N225'),), '2026-08-21') == []


def test_region_rows_skips_a_ticker_the_download_missed():
    closes = {'^N225': None, '^HSI': [100.0, 102.0]}
    dates = {'^N225': None, '^HSI': _dates(2)}
    rows = session.region_rows(closes, dates, session.ASIA, '2026-08-21')
    assert [r['ticker'] for r in rows] == ['^HSI']


def test_alignment_divergent_when_region_and_us_disagree():
    rows = [{'pct': +0.31}, {'pct': -0.79}, {'pct': -0.71}]   # 평균 -0.40
    a = session.alignment(rows, us_pct=+0.72)
    assert a['label'] == '엇갈림'
    assert a['mixed'] is True
    assert a['avg_pct'] == -0.4


def test_alignment_continues_when_both_sides_share_a_sign():
    a = session.alignment([{'pct': -0.2}, {'pct': -0.34}], us_pct=-0.5)
    assert a['label'] == '이어감'
    assert a['mixed'] is False


def test_alignment_needs_two_surviving_indices():
    assert session.alignment([{'pct': +1.0}], us_pct=+0.5) is None
    assert session.alignment([], us_pct=+0.5) is None


def test_alignment_flat_when_either_side_is_inside_the_dead_band():
    assert session.alignment([{'pct': 0.05}, {'pct': 0.02}], us_pct=+0.9)['label'] == '보합'
    assert session.alignment([{'pct': 0.9}, {'pct': 0.8}], us_pct=0.03)['label'] == '보합'


def test_history_tickers_cover_both_regions_and_the_participation_legs():
    assert set(session.HISTORY_TICKERS) == {
        '^N225', '^HSI', '000001.SS', '^GDAXI', '^FTSE', '^STOXX50E', 'RSP', 'SPY'}
