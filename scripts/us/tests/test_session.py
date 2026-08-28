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


def test_overnight_window_spans_the_et_calendar_boundary():
    bars = [
        {'t': '2026-08-26T15:30:00-04:00', 'high': 9, 'low': 9},    # 정규장 — 제외
        {'t': '2026-08-26T18:30:00-04:00', 'high': 7741.25, 'low': 7700.0},
        {'t': '2026-08-27T04:30:00-04:00', 'high': 7730.0, 'low': 7690.25},
        {'t': '2026-08-27T10:00:00-04:00', 'high': 9, 'low': 9},    # 개장 후 — 제외
    ]
    w = session.overnight(bars, '2026-08-27')
    assert w['high'] == 7741.25 and w['high_t'] == '18:30'
    assert w['low'] == 7690.25 and w['low_t'] == '04:30'
    assert w['bars'] == 2


def test_overnight_ignores_bars_from_last_week():
    bars = [{'t': '2026-08-18T18:30:00-04:00', 'high': 1, 'low': 1},
            {'t': '2026-08-27T04:30:00-04:00', 'high': 2, 'low': 2}]
    assert session.overnight(bars, '2026-08-27')['bars'] == 1


def test_overnight_returns_none_without_bars_in_the_window():
    assert session.overnight([{'t': '2026-08-27T10:00:00-04:00',
                               'high': 1, 'low': 1}], '2026-08-27') is None
    assert session.overnight(None, '2026-08-27') is None


def test_gap_is_computed_on_the_cash_index_not_the_future():
    market = {'indices': {'S&P 500': {'last': 7730.99, 'chg': 55.0}}}
    intraday = {'S&P 500': {'open': 7710.34}}
    g = session.gap(market, intraday, 'S&P 500')
    assert g == 0.45
    assert session.gap_direction(g) == '상승 출발'
    assert session.gap_direction(0.05) == '보합 출발'
    assert session.gap_direction(-0.9) == '하락 출발'
    assert session.gap_direction(None) is None


def test_gap_is_none_when_a_leg_is_missing():
    assert session.gap({'indices': {}}, {'S&P 500': {'open': 1}}, 'S&P 500') is None
    assert session.gap({'indices': {'S&P 500': {'last': 1, 'chg': 0.1}}},
                       {}, 'S&P 500') is None


def _two(spy, rsp, d=('2026-08-26', '2026-08-27')):
    return ({'SPY': [100.0, 100 + spy], 'RSP': [100.0, 100 + rsp]},
            {'SPY': list(d), 'RSP': list(d)})


def test_participation_labels_a_narrow_rally():
    p = session.participation(*_two(0.66, -0.29))     # 2026-08-27 실측 근사
    assert p['band'] == '소수가 끌어올림'
    assert p['gap_pp'] == -0.95
    assert p['date'] == '2026-08-27'


def test_participation_labels_a_broad_rally():
    assert session.participation(*_two(0.5, 1.2))['band'] == '고르게 오름'


def test_participation_labels_declines_on_both_sides():
    assert session.participation(*_two(-0.5, -1.2))['band'] == '고르게 내림'
    assert session.participation(*_two(-0.5, 0.2))['band'] == '소수가 끌어내림'


def test_participation_is_neutral_inside_the_threshold():
    assert session.participation(*_two(0.5, 0.7))['band'] == '중립'


def test_participation_requires_a_shared_session_date():
    closes = {'SPY': [100.0, 100.5], 'RSP': [100.0, 101.0]}
    dates = {'SPY': ['2026-08-26', '2026-08-27'], 'RSP': ['2026-08-24', '2026-08-25']}
    assert session.participation(closes, dates) is None
    assert session.participation({'SPY': None, 'RSP': None}, {}) is None


def test_tape_positions_the_close_inside_the_day_range():
    t = session.tape({'Nasdaq': {'open': 26365.29, 'close': 26539.56,
                                 'low': 26273.87, 'high': 26553.27}})
    assert t['Nasdaq']['close_position'] == 95
    assert t['Nasdaq']['band'] == '고점권 마감'


def test_tape_is_null_when_the_range_is_degenerate():
    assert session.tape({'Nasdaq': {'close': 1, 'low': 1, 'high': 1}})['Nasdaq'] is None
    assert session.tape({}) == {}


def test_tape_bands_cover_the_middle_and_the_bottom():
    t = session.tape({'S&P 500': {'close': 50, 'low': 0, 'high': 100},
                      'Nasdaq': {'close': 10, 'low': 0, 'high': 100}})
    assert t['S&P 500']['band'] == '중단 마감'
    assert t['Nasdaq']['band'] == '저점권 마감'


def test_compute_assembles_every_block_and_survives_missing_pieces():
    closes = {'^N225': [100.0, 99.8], 'SPY': [100.0, 100.66], 'RSP': [100.0, 99.71]}
    dates = {t: ['2026-08-26', '2026-08-27'] for t in closes}
    market = {'indices': {'S&P 500': {'last': 7730.99, 'chg': 55.0, 'pct': 0.72}}}
    intraday = {'S&P 500': {'open': 7710.34, 'close': 7730.11,
                            'low': 7689.89, 'high': 7741.27}}
    out = session.compute(closes, dates, market, intraday, {}, '2026-08-27')
    assert out['report_date'] == '2026-08-27'
    assert out['global_close']['asia']['rows'][0]['name'] == '닛케이'
    assert out['global_close']['asia']['alignment'] is None      # 살아남은 지수 1종
    assert out['global_close']['europe']['rows'] == []
    assert out['participation']['band'] == '소수가 끌어올림'
    assert out['futures']['contracts'] == {}
    assert out['futures']['gap']['S&P 500'] == 0.45
    assert out['futures']['direction'] == '상승 출발'
    assert out['tape']['S&P 500']['band'] == '고점권 마감'


def test_overnight_takes_only_the_most_recent_evening():
    """4일치 저녁을 한 창에 담으면 저점이 그날 밤 값이 아니게 된다
    (2026-08-27 실전 수집에서 ES 봉이 33개가 아니라 61개로 나왔다)."""
    bars = [
        {'t': '2026-08-25T20:00:00-04:00', 'high': 100, 'low': 1},     # 이틀 전 저녁
        {'t': '2026-08-26T18:30:00-04:00', 'high': 7741.25, 'low': 7700.0},
        {'t': '2026-08-27T04:30:00-04:00', 'high': 7730.0, 'low': 7690.25},
    ]
    w = session.overnight(bars, '2026-08-27')
    assert w['bars'] == 2
    assert w['low'] == 7690.25          # 이틀 전의 1이 아니다
    assert w['high'] == 7741.25


def test_participation_refuses_to_span_a_hole():
    """한쪽 종가가 비면 그 세션을 건너뛰어 이틀치가 하루치로 둔갑한다."""
    closes = {'SPY': [100.0, float('nan'), 100.5], 'RSP': [100.0, 99.0, 101.0]}
    dates = {t: ['2026-08-25', '2026-08-26', '2026-08-27'] for t in closes}
    assert session.participation(closes, dates) is None


def test_participation_still_spans_a_weekend():
    """주말은 구멍이 아니다 — 어느 쪽에도 그 세션이 없다."""
    closes = {'SPY': [100.0, 100.5], 'RSP': [100.0, 101.0]}
    dates = {t: ['2026-08-21', '2026-08-24'] for t in closes}   # 금 → 월
    assert session.participation(closes, dates)['band'] == '고르게 오름'


def test_participation_refuses_a_stale_reading():
    closes = {'SPY': [100.0, 100.5], 'RSP': [100.0, 99.0]}
    dates = {t: ['2026-08-25', '2026-08-26'] for t in closes}
    assert session.participation(closes, dates, report_date='2026-08-27') is None
    assert session.participation(closes, dates, report_date='2026-08-26') is not None


def test_tape_classifies_before_rounding():
    """74.6을 75로 반올림한 뒤 「고점권」이라 부르지 않는다."""
    t = session.tape({'S&P 500': {'close': 74.6, 'low': 0, 'high': 100},
                      'Nasdaq': {'close': 25.4, 'low': 0, 'high': 100}})
    assert t['S&P 500']['band'] == '중단 마감' and t['S&P 500']['close_position'] == 75
    assert t['Nasdaq']['band'] == '중단 마감' and t['Nasdaq']['close_position'] == 25


def test_futures_carry_their_overnight_range():
    bars = [{'t': '2026-08-26T18:30:00-04:00', 'high': 110.0, 'low': 100.0},
            {'t': '2026-08-27T04:30:00-04:00', 'high': 105.0, 'low': 102.0}]
    assert session.overnight(bars, '2026-08-27')['range_pct'] == 10.0
