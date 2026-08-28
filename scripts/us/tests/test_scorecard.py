from us.scorecard import MIN_SAMPLE, BENCHMARKS, build, score_change


def _dts(n, start='2026-01-01'):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _rising(n=120, step=1.0, start=100.0):
    return [start + step * i for i in range(n)]


def _world(n=120, gspc_step=1.0, tnx_step=0.01):
    dates = _dts(n)
    closes = {'^GSPC': _rising(n, gspc_step), '^TNX': _rising(n, tnx_step, 4.0),
              'CL=F': _rising(n, 0.2, 80.0), 'GC=F': _rising(n, 1.0, 4000.0),
              'DX-Y.NYB': _rising(n, 0.05, 99.0)}
    return closes, {t: dates for t in closes}


def test_a_long_position_before_a_rise_scores_positive():
    closes, dates = _world()
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'equities', 'from': 0, 'to': 1},
                       closes, dates, horizon=20)
    assert got['score'] > 0


def test_a_long_position_before_a_fall_scores_negative():
    closes, dates = _world(gspc_step=-1.0)
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'equities', 'from': 0, 'to': 1},
                       closes, dates, horizon=20)
    assert got['score'] < 0


def test_a_bond_overweight_scores_on_falling_yields_not_rising_ones():
    """채권 비중 확대는 금리가 내려야 맞은 것이다 — 부호 규약이 뒤집혀 있다."""
    closes, dates = _world(tnx_step=0.01)          # yields rising
    got = score_change({'date': dates['^TNX'][10], 'asset': 'bonds', 'from': 0, 'to': 1},
                       closes, dates, horizon=20)
    assert got['score'] < 0


def test_a_short_position_scores_positive_when_the_market_falls():
    closes, dates = _world(gspc_step=-1.0)
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'equities', 'from': 0, 'to': -1},
                       closes, dates, horizon=20)
    assert got['score'] > 0


def test_a_move_to_neutral_carries_no_position_to_score():
    closes, dates = _world()
    assert score_change({'date': dates['^GSPC'][10], 'asset': 'equities', 'from': 1, 'to': 0},
                        closes, dates, horizon=20) is None


def test_the_bootstrap_entry_is_not_a_decision():
    closes, dates = _world()
    assert score_change({'date': dates['^GSPC'][10], 'asset': '*', 'from': None, 'to': None},
                        closes, dates, horizon=20) is None


def test_a_change_too_recent_to_have_a_forward_window_is_skipped():
    closes, dates = _world()
    assert score_change({'date': dates['^GSPC'][-2], 'asset': 'equities', 'from': 0, 'to': 1},
                        closes, dates, horizon=20) is None


def test_every_scored_asset_has_a_declared_benchmark_and_sign():
    for key, ticker, sign in BENCHMARKS:
        assert sign in (1, -1), key


def test_build_refuses_to_report_on_too_few_decisions():
    closes, dates = _world()
    history = [{'date': dates['^GSPC'][10], 'asset': 'equities', 'from': 0, 'to': 1}]
    got = build(history, closes, dates)
    assert got['sufficient'] is False
    assert got['scored'] == 1


def test_build_reports_once_there_are_enough_decisions():
    closes, dates = _world(n=400)
    history = [{'date': dates['^GSPC'][i], 'asset': 'equities', 'from': 0, 'to': 1}
               for i in range(10, 10 + MIN_SAMPLE)]
    got = build(history, closes, dates)
    assert got['sufficient'] is True
    assert got['scored'] == MIN_SAMPLE


def test_build_counts_how_often_the_position_was_right():
    closes, dates = _world(n=400)
    history = [{'date': dates['^GSPC'][i], 'asset': 'equities', 'from': 0, 'to': 1}
               for i in range(10, 10 + MIN_SAMPLE)]
    got = build(history, closes, dates)
    assert got['hit_rate'] == 100.0


def test_build_breaks_the_record_out_by_asset():
    closes, dates = _world(n=400)
    history = [{'date': dates['^GSPC'][i], 'asset': 'equities', 'from': 0, 'to': 1}
               for i in range(10, 10 + MIN_SAMPLE)]
    got = build(history, closes, dates)
    assert got['by_asset']['equities']['scored'] == MIN_SAMPLE


def test_build_on_an_empty_history_is_not_an_error():
    closes, dates = _world()
    got = build([], closes, dates)
    assert got['sufficient'] is False and got['scored'] == 0


# ── 상대 비중 자산 (메모리·AI 인프라) ──────────────────────────────────────

from us.scorecard import RELATIVE  # noqa: E402


def _relative_world(n=400, basket_step=2.0, mkt_step=1.0):
    dates = _dts(n)
    closes = {'^GSPC': _rising(n, mkt_step)}
    for _key, tickers, _bench, _sign in RELATIVE:
        for t in tickers:
            closes[t] = _rising(n, basket_step)
    return closes, {t: dates for t in closes}


def test_a_memory_overweight_scores_on_beating_the_market_not_on_rising():
    """메모리 등급은 주식 대비 상대 비중이다 — 같이 올랐으면 맞은 게 아니다."""
    closes, dates = _relative_world(basket_step=1.0, mkt_step=1.0)   # 딱 시장만큼
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'memory', 'from': 0, 'to': 1},
                       closes, dates, horizon=20)
    assert got is not None and abs(got['score']) < 0.5


def test_a_memory_overweight_that_beat_the_market_scores_positive():
    closes, dates = _relative_world(basket_step=3.0, mkt_step=1.0)
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'memory', 'from': 0, 'to': 1},
                       closes, dates, horizon=20)
    assert got['score'] > 0


def test_a_memory_underweight_scores_positive_when_the_basket_lags():
    closes, dates = _relative_world(basket_step=0.2, mkt_step=1.0)
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'memory', 'from': 0, 'to': -1},
                       closes, dates, horizon=20)
    assert got['score'] > 0


def test_every_asset_in_the_stance_book_can_be_scored():
    """책에 7개 자산이 있는데 5개만 채점하면 나머지는 조용히 빠진다."""
    import json
    book = set(json.load(open('data/stance.json'))['assets'])
    covered = {k for k, _t, _s in BENCHMARKS} | {k for k, _t, _b, _s in RELATIVE}
    assert book <= covered, book - covered


def test_a_leg_starting_late_is_aligned_rather_than_inventing_excess():
    """2026-08-28 codex 실측에서 한 다리가 하루 늦게 시작한 것만으로 90%짜리
    초과수익이 만들어졌다. 공통 거래일 위에서 재면 그런 일이 없다."""
    closes, dates = _relative_world(basket_step=1.0, mkt_step=1.0)
    closes['MU'] = closes['MU'][1:]
    dates['MU'] = dates['MU'][1:]
    got = score_change({'date': dates['^GSPC'][10], 'asset': 'memory', 'from': 0, 'to': 1},
                       closes, dates, horizon=20)
    assert got is not None and abs(got['score']) < 0.5, got


def test_a_relative_basket_missing_a_name_is_refused():
    """받아오지 못한 종목을 조용히 빼면 바스켓이 말없이 줄어든다."""
    closes, dates = _relative_world()
    del closes['STX']; del dates['STX']
    assert score_change({'date': dates['^GSPC'][10], 'asset': 'memory', 'from': 0, 'to': 1},
                        closes, dates, horizon=20) is None
