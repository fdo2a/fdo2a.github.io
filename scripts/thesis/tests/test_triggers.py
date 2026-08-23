from thesis import triggers as T


FV = {'bull': 1751, 'base': 808, 'bear': 299, 'weighted': 964, 'band1': 771, 'band2': 655}


def snap(**kw):
    base = {'price': 966.78, 'eps_fy1': 155.0, 'eps_fy1_low': 106.89,
            'eps_fy1_high': 221.27}
    base.update(kw)
    return base


def fire(today, past=None, fv=FV, depth=True):
    return {t['key'] for t in T.evaluate(today, past, fv, has_depth=depth)}


# ── 컨센 급변 ──

def test_consensus_swing_up_fires():
    assert 'consensus_swing' in fire(snap(eps_fy1=200.0), snap(eps_fy1=155.0))


def test_consensus_swing_down_fires():
    assert 'consensus_swing' in fire(snap(eps_fy1=110.0), snap(eps_fy1=155.0))


def test_small_consensus_drift_is_silent():
    assert 'consensus_swing' not in fire(snap(eps_fy1=160.0), snap(eps_fy1=155.0))


def test_consensus_swing_needs_history():
    assert 'consensus_swing' not in fire(snap(eps_fy1=200.0), snap(eps_fy1=155.0), depth=False)


def test_consensus_swing_without_past_is_silent():
    assert 'consensus_swing' not in fire(snap(eps_fy1=200.0), None)


# ── 하단 수렴 ──

def test_consensus_floor_fires_when_avg_approaches_low():
    assert 'consensus_floor' in fire(snap(eps_fy1=115.0, eps_fy1_low=106.89))


def test_consensus_floor_silent_when_avg_is_mid_range():
    assert 'consensus_floor' not in fire(snap(eps_fy1=155.0, eps_fy1_low=106.89))


# ── 밴드 진입 ──

def test_band1_entry_fires():
    assert 'band_entry' in fire(snap(price=760.0))


def test_band2_entry_is_reported_at_deeper_level():
    hits = {t['key']: t for t in T.evaluate(snap(price=600.0), None, FV, has_depth=True)}
    assert hits['band_entry']['level'] == 'band2'


def test_no_band_entry_above_band1():
    assert 'band_entry' not in fire(snap(price=966.78))


# ── Bear 근접 ──

def test_bear_proximity_fires_near_bear_value():
    assert 'bear_proximity' in fire(snap(price=310.0))


def test_bear_proximity_silent_far_above():
    assert 'bear_proximity' not in fire(snap(price=966.78))


# ── 분산 확대 ──

def test_dispersion_widening_fires():
    today = snap(eps_fy1_low=80.0, eps_fy1_high=260.0)   # ratio 3.25
    past = snap(eps_fy1_low=110.0, eps_fy1_high=220.0)   # ratio 2.00
    assert 'dispersion_widening' in fire(today, past)


def test_dispersion_narrowing_is_silent():
    today = snap(eps_fy1_low=120.0, eps_fy1_high=200.0)
    past = snap(eps_fy1_low=80.0, eps_fy1_high=260.0)
    assert 'dispersion_widening' not in fire(today, past)


# ── 형태 ──

def test_quiet_day_fires_nothing():
    assert fire(snap(), snap()) == set()


def test_each_trigger_carries_a_korean_sentence_and_severity():
    for t in T.evaluate(snap(price=310.0, eps_fy1=110.0), snap(eps_fy1=155.0), FV, has_depth=True):
        assert t['message'] and t['severity'] in T.SEVERITIES
        assert t['key'] in T.TRIGGER_KEYS


def test_missing_fair_value_disables_price_triggers_only():
    hits = fire(snap(eps_fy1=110.0), snap(eps_fy1=155.0), fv=None)
    assert 'consensus_swing' in hits
    assert 'band_entry' not in hits and 'bear_proximity' not in hits


def test_missing_price_is_survivable():
    assert T.evaluate(snap(price=None), None, FV, has_depth=True) is not None
