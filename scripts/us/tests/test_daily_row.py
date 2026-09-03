"""일별 종가 행 — 24시간 거래 종목이 다음 날짜 봉으로 새는 것을 막는다.

2026-09-02 발행본 실측: report_date 는 2026-09-02 인데 fx 의 USD/KRW·USD/JPY·EUR/USD
가 `date: 2026-09-03` 을 달고 나갔다. DXY(지수)는 09-02 그대로였다 — 통화쌍은 24시간
거래라 야후 마지막 봉이 다음 날짜로 넘어가는데 지수는 안 넘어가서, 같은 FX 표 안에서
기준일이 갈렸다. 2s10s 와 같은 부류인데 이쪽은 별표도 각주도 없이 조용히 섞였다.
"""
import pytest

from scripts.us import daily_row as dr


def test_row_uses_the_last_bar_when_no_anchor_is_given():
    row = dr.row_from_closes(['2026-09-01', '2026-09-02'], [4.796, 4.794])
    assert row['date'] == '2026-09-02'
    assert row['last'] == 4.794
    assert row['chg'] == pytest.approx(-0.002)


def test_row_ignores_bars_after_the_anchor():
    # EUR/USD 가 09-03 봉을 이미 열었어도 report_date 가 09-02 면 09-02 를 써야 한다.
    row = dr.row_from_closes(['2026-09-01', '2026-09-02', '2026-09-03'],
                             [1.1618, 1.1596, 1.1640], as_of='2026-09-02')
    assert row['date'] == '2026-09-02'
    assert row['last'] == 1.1596


def test_pct_is_measured_against_the_session_before_the_anchor():
    row = dr.row_from_closes(['2026-09-01', '2026-09-02', '2026-09-03'],
                             [100.0, 110.0, 200.0], as_of='2026-09-02')
    assert row['pct'] == pytest.approx(10.0)


def test_row_is_none_without_two_sessions_at_or_before_the_anchor():
    assert dr.row_from_closes(['2026-09-02'], [1.0], as_of='2026-09-02') is None


def test_row_is_none_when_every_bar_is_after_the_anchor():
    assert dr.row_from_closes(['2026-09-03'], [1.0], as_of='2026-09-01') is None


def test_anchor_date_comes_from_the_reference_ticker():
    series = {'^GSPC': ['2026-09-01', '2026-09-02'], 'EURUSD=X': ['2026-09-02', '2026-09-03']}
    assert dr.anchor_date(series, '^GSPC') == '2026-09-02'


def test_anchor_date_is_none_when_the_reference_ticker_is_missing():
    assert dr.anchor_date({'EURUSD=X': ['2026-09-03']}, '^GSPC') is None


# --- codex 검토 반영 (2026-09-04) --------------------------------------------

def test_clip_series_drops_sessions_after_the_anchor():
    """스탠스 트리거·가격 위치 판정이 다음날 봉을 보면 안 된다.

    표(fx)만 앵커로 자르고 이력을 안 자르면, 같은 발행본에서 표는 09-02 인데
    stance_metrics·price_context 는 09-03 값으로 계산된다 (codex 검토).
    """
    dates = ['2026-09-01', '2026-09-02', '2026-09-03']
    closes = [1.1618, 1.1596, 1.1640]
    assert dr.clip_series(closes, dates, '2026-09-02') == ([1.1618, 1.1596],
                                                           ['2026-09-01', '2026-09-02'])


def test_clip_series_without_an_anchor_is_a_passthrough():
    dates, closes = ['2026-09-01', '2026-09-02'], [1.0, 2.0]
    assert dr.clip_series(closes, dates, None) == (closes, dates)


def test_clip_series_tolerates_an_empty_series():
    assert dr.clip_series(None, None, '2026-09-02') == (None, None)
