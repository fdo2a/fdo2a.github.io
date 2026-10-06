from fund import regime as r


def test_classify_four_states():
    # close, sma50, sma200, sma200 20 sessions ago, 3m return, drawdown
    assert r.classify(90, 95, 100, 101, -8, -15) == '장기 약세'
    assert r.classify(104, 106, 100, 99, 1, -6) == '단기 약세'
    assert r.classify(110, 105, 100, 99, 4, -1) == '강세'
    # above both averages but 3m flat -> residual
    assert r.classify(110, 105, 100, 99, -0.5, -2) == '횡보'
    # below 200d but the 200d is still rising -> residual, not a long bear
    assert r.classify(98, 101, 100, 99, -3, -4) == '횡보'


def test_classify_none_on_missing_input():
    assert r.classify(100, None, 100, 99, 1, -1) is None


def test_initialises_on_first_valid_three_run_not_first_value():
    seq = ['강세', '횡보', '강세', '횡보', '횡보', '횡보', '강세']
    # the alternating head never confirms anything; 횡보 x3 does
    assert r.confirm(seq, 3) == [None, None, None, None, None, '횡보', '횡보']


def test_result_does_not_depend_on_alternating_prefix():
    a = ['강세', '횡보'] * 5 + ['강세'] * 3
    b = ['횡보', '강세'] * 5 + ['강세'] * 3
    assert r.confirm(a, 3)[-1] == r.confirm(b, 3)[-1] == '강세'


def test_hysteresis_needs_consecutive_sessions():
    seq = ['강세'] * 10 + ['횡보', '횡보', '강세'] + ['횡보'] * 2
    assert r.confirm(seq, 3)[-1] == '강세'
    assert r.confirm(seq + ['횡보'], 3)[-1] == '횡보'


def test_none_breaks_a_run():
    seq = ['강세'] * 4 + ['횡보', None, '횡보', '횡보']
    assert r.confirm(seq, 3)[-1] == '강세'


def test_state_since_prev_pending():
    seq = ['강세'] * 5 + ['횡보'] * 4 + ['단기 약세'] * 2
    dates = [f'd{i:02d}' for i in range(len(seq))]
    st = r.state(seq, dates, 3)
    assert st['name'] == '횡보'
    assert st['since'] == 'd05'
    assert st['since_exact'] is True
    assert st['prev'] == '강세'
    assert st['pending_name'] == '단기 약세'
    assert st['pending_sessions'] == 2
    assert st['sessions_held'] == 6


def test_since_not_exact_when_state_is_the_initial_one():
    seq = ['강세'] * 8
    dates = [f'd{i}' for i in range(8)]
    st = r.state(seq, dates, 3)
    assert st['name'] == '강세'
    assert st['since'] == 'd0'
    assert st['since_exact'] is False
    assert st['prev'] is None
    assert st['pending_name'] is None


def _closes_up_then_down():
    up = [100 * 1.002 ** i for i in range(520)]
    top = up[-1]
    down = [top * 0.995 ** i for i in range(1, 121)]
    return up + down


def test_compute_long_bear_after_steady_decline():
    closes = _closes_up_then_down()
    dates = [f'd{i:04d}' for i in range(len(closes))]
    out = r.compute(closes, dates)
    assert out['name'] == '장기 약세'
    assert out['raw_today'] == '장기 약세'
    assert out['since_exact'] is True
    assert out['history_start'] == dates[len(closes) - r.LOOKBACK]
    assert set(out['inputs']) >= {'close', 'sma50', 'sma200', 'sma200_prev',
                                  'ret_3m', 'drawdown', 'as_of'}
    assert out['basis'].startswith('가격 기준')
    assert '잔여' in out['residual_note']


def test_compute_none_without_enough_history():
    closes = [100.0] * (r.MIN_CLOSES - 1)
    assert r.compute(closes, [str(i) for i in range(len(closes))]) is None


def test_a_session_spy_lacks_breaks_the_confirming_run():
    # long rise, then turn flat-ish so the raw call changes near the end
    closes = _closes_up_then_down()
    dates = [f'd{i:04d}' for i in range(len(closes))]
    full = r.compute(closes, dates, cal=dates)
    # drop SPY's close on a session inside the window: the calendar still has it
    k = len(closes) - 5
    gap_c = closes[:k] + closes[k + 1:]
    gap_d = dates[:k] + dates[k + 1:]
    out = r.compute(gap_c, gap_d, cal=dates)
    assert out['history_start'] == full['history_start']
    assert out['missing_sessions'] == [dates[k]]


def test_seq_marks_missing_session_as_none():
    seq = r.raw_series([100.0] * 599, [f'd{i:04d}' for i in range(600) if i != 590],
                       [f'd{i:04d}' for i in range(600)])
    assert seq[1][-10] is None
