from thesis import triggers as T


FV = {'bull': 1751, 'base': 808, 'bear': 299, 'weighted': 964, 'band1': 771, 'band2': 655}


def snap(**kw):
    base = {'price': 966.78, 'eps_fy1': 155.0, 'eps_fy1_low': 106.89,
            'eps_fy1_high': 221.27}
    base.update(kw)
    return base


def yesterday(**kw):
    """A history row: yesterday's numbers *and* the lines they were judged against."""
    base = {'price': 966.78, 'eps_fy1': 155.0, 'eps_fy1_low': 106.89,
            'eps_fy1_high': 221.27, 'price_date': '2026-08-24',
            'band1': FV['band1'], 'band2': FV['band2'], 'bear': FV['bear']}
    base.update(kw)
    return base


def fire(today, past=None, fv=FV, depth=True, prev=None, prior=None):
    return {t['key'] for t in T.evaluate(today, past, fv, has_depth=depth, prev=prev,
                                         prior=prior)}


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


# ── 하단 수렴 — 넘어선 날에만, 그리고 평균이 실제로 내려왔을 때만 ──

def test_consensus_floor_fires_on_the_day_it_crosses_in():
    today = snap(eps_fy1=115.0, eps_fy1_low=106.89)      # headroom 7.6%
    assert 'consensus_floor' in fire(today, prev=yesterday(eps_fy1=155.0))


def test_consensus_floor_is_silent_the_next_day_in_the_same_place():
    """The condition holding is not news. Yesterday's report was the news."""
    today = snap(eps_fy1=114.0, eps_fy1_low=106.89)
    prev = yesterday(eps_fy1=115.0, eps_fy1_low=106.89)  # 이미 안에 있었다
    assert 'consensus_floor' not in fire(today, prev=prev)


def test_consensus_floor_ignores_an_approach_made_by_the_low_estimate_rising():
    """Headroom shrank because the bears gave up, not because the average fell. That is
    consensus converging *upward* — the opposite of what this trigger means."""
    today = snap(eps_fy1=118.0, eps_fy1_low=112.0)       # headroom 5.4%
    prev = yesterday(eps_fy1=115.0, eps_fy1_low=90.0)    # headroom 27.8%
    assert 'consensus_floor' not in fire(today, prev=prev)


def test_consensus_floor_at_exactly_the_threshold_counts_as_crossed_in():
    today = snap(eps_fy1=122.92, eps_fy1_low=106.89)     # headroom 정확히 15.0%
    assert 'consensus_floor' in fire(today, prev=yesterday(eps_fy1=155.0))


def test_consensus_floor_does_not_refire_when_yesterday_was_already_at_the_line():
    today = snap(eps_fy1=120.0, eps_fy1_low=106.89)
    prev = yesterday(eps_fy1=122.92, eps_fy1_low=106.89)  # 어제 정확히 15.0% — 이미 안
    assert 'consensus_floor' not in fire(today, prev=prev)


def test_consensus_floor_needs_the_average_to_have_actually_moved():
    same = snap(eps_fy1=115.0, eps_fy1_low=106.89)
    assert 'consensus_floor' not in fire(same, prev=yesterday(eps_fy1=115.0,
                                                             eps_fy1_low=90.0))


def test_consensus_floor_survives_missing_or_zero_estimates():
    for today in (snap(eps_fy1=None), snap(eps_fy1_low=0), snap(eps_fy1_low=None)):
        assert 'consensus_floor' not in fire(today, prev=yesterday(eps_fy1=155.0))


def test_consensus_floor_silent_when_avg_is_mid_range():
    assert 'consensus_floor' not in fire(snap(eps_fy1=155.0), prev=yesterday())


def test_consensus_floor_needs_a_yesterday_to_compare_with():
    assert 'consensus_floor' not in fire(snap(eps_fy1=115.0, eps_fy1_low=106.89))


# ── 밴드 진입은 더 이상 트리거가 아니다 ──

def test_band_entry_is_not_a_trigger():
    """주가가 관심가 아래에 있는 것은 thesis가 흔들린 것이 아니다. 상태값으로 페이지에
    상시 표시되며(position.in_band1), 매일 울리는 종이 되어서는 안 된다."""
    assert 'band_entry' not in T.TRIGGER_KEYS
    for price in (760.0, 600.0, 300.0):
        assert fire(snap(price=price), prev=yesterday()) - {'bear_proximity'} == set()


# ── Bear 근접 — 들어선 날에만 ──

def test_bear_proximity_fires_on_the_day_it_enters():
    assert 'bear_proximity' in fire(snap(price=310.0), prev=yesterday(price=966.78))


def test_bear_proximity_is_silent_the_next_day_in_the_same_zone():
    assert 'bear_proximity' not in fire(snap(price=305.0), prev=yesterday(price=310.0))


def test_bear_proximity_fires_when_the_price_gaps_clean_through_the_zone():
    """±10% 안에서 종가가 잡히지 않았다고 조용하면 더 심한 날을 놓친다."""
    hits = {t['key']: t for t in T.evaluate(snap(price=200.0), None, FV, True,
                                            prev=yesterday(price=966.78))}
    assert 'bear_proximity' in hits and hits['bear_proximity']['level'] == 'through'


def test_bear_proximity_fires_when_the_bear_line_rose_to_meet_a_flat_price():
    """추정치가 무너져 bear 가치가 주가까지 올라온 것도 상태 변화다 — 오히려 더 나쁘다."""
    hits = {t['key']: t for t in T.evaluate(
        snap(price=310.0), None, dict(FV, bear=299), True,
        prev=yesterday(price=310.0, bear=200))}
    assert 'bear_proximity' in hits
    assert '기준선' in hits['bear_proximity']['message']


def test_bear_zone_transitions_run_in_the_right_direction():
    """악화만 경고다. 아래에서 띠 안으로 «올라온» 날을 진입 경고로 부르면 회복을
    악재로 읽는 것이다."""
    def keys(today_price, prev_price):
        return {t['key']: t for t in T.evaluate(
            snap(price=today_price), None, FV, True, prev=yesterday(price=prev_price))}

    assert keys(310.0, 966.78)['bear_proximity']['level'] == 'in'    # above → in
    assert keys(200.0, 966.78)['bear_proximity']['level'] == 'through'  # above → below
    assert keys(200.0, 310.0)['bear_proximity']['level'] == 'below'  # in → below
    assert 'bear_exit' in keys(310.0, 200.0)                         # below → in
    assert 'bear_proximity' not in keys(310.0, 200.0)
    assert 'bear_exit' in keys(966.78, 310.0)                        # in → above
    assert keys(966.78, 900.0) == {}                                 # above → above


def test_a_recovery_out_of_the_bear_zone_is_reported_so_a_grade_can_come_back():
    """state.propose()는 트리거 없이 등급을 못 움직인다. 나아진 날에 침묵하면 내려간
    등급이 영영 못 올라온다."""
    hits = {t['key']: t for t in T.evaluate(snap(price=966.78), None, FV, True,
                                            prev=yesterday(price=310.0))}
    assert hits['bear_exit']['severity'] == 'info'


def test_the_cause_is_read_from_the_line_that_actually_moved():
    """어제 선을 그대로 두고 오늘 주가만 넣어 본다. 그래도 상태가 달라지면 주가가 움직인
    것이다 — 단순 가격 일치 비교는 「주가는 올랐는데 선이 더 빨리 올라온」 날을 놓친다."""
    by_line = {t['key']: t for t in T.evaluate(
        snap(price=320.0), None, dict(FV, bear=299), True,
        prev=yesterday(price=310.0, bear=200))}
    assert '기준선이 이동' in by_line['bear_proximity']['message']

    by_price = {t['key']: t for t in T.evaluate(
        snap(price=310.0), None, FV, True, prev=yesterday(price=966.78))}
    assert '주가 이동' in by_price['bear_proximity']['message']


def test_a_nonpositive_bear_value_disables_the_zone_instead_of_inverting_it():
    """적자 구간에서 정규화이익법이 음수 가치를 내면 ±10% 띠의 위아래가 뒤집힌다."""
    for bear in (0, -100):
        assert T.evaluate(snap(price=310.0), None, dict(FV, bear=bear), True,
                          prev=yesterday(price=966.78, bear=bear)) == []


def test_the_zone_edge_is_inclusive_on_both_sides():
    """경계를 코드와 같은 식으로 만들어 확인한다 — bear*1.10처럼 다른 순서로 계산하면
    부동소수점 오차 한 자리 때문에 테스트가 경계가 아닌 곳을 재게 된다."""
    bear = FV['bear']
    edge = bear * T.BEAR_PROXIMITY_PCT / 100
    assert T._bear_zone(bear + edge, bear) == 'in'
    assert T._bear_zone(bear - edge, bear) == 'in'
    assert T._bear_zone(bear + edge * 1.01, bear) == 'above'
    assert T._bear_zone(bear - edge * 1.01, bear) == 'below'


def test_a_price_just_inside_the_zone_fires_and_just_outside_does_not():
    assert 'bear_proximity' in fire(snap(price=FV['bear'] * 1.05),
                                    prev=yesterday(price=966.78))
    assert fire(snap(price=FV['bear'] * 1.2), prev=yesterday(price=966.78)) == set()


def test_bear_proximity_silent_far_above():
    assert 'bear_proximity' not in fire(snap(price=966.78), prev=yesterday())


def test_bear_proximity_needs_a_yesterday_to_compare_with():
    assert 'bear_proximity' not in fire(snap(price=310.0))


def test_a_holiday_repeat_of_the_same_numbers_fires_nothing():
    """휴장일에 같은 종가가 다시 들어와도 상태가 그대로라 아무것도 안 울린다."""
    same = yesterday(price=310.0, eps_fy1=115.0)
    today = snap(price=310.0, eps_fy1=115.0)
    assert fire(today, prev=same) == set()


# ── 재장전 (같은 국면에서 매일 다시 울리지 않게) ──

def test_a_swing_that_stays_beyond_the_line_only_speaks_once():
    """30일 변화가 20%를 넘은 채로 머무는 동안은 매일이 같은 사건이다. 어제 이미 울렸으면
    오늘은 말할 것이 없다."""
    today, past = snap(eps_fy1=200.0), snap(eps_fy1=155.0)   # +29%
    assert 'consensus_swing' in fire(today, past, prior={'consensus_swing': [5.0]})
    assert 'consensus_swing' not in fire(today, past, prior={'consensus_swing': [29.0]})


def test_a_swing_rearms_after_the_move_settles_back_down():
    today, past = snap(eps_fy1=200.0), snap(eps_fy1=155.0)
    calmed = {'consensus_swing': [29.0, 25.0, 12.0]}          # 12%까지 진정됐다
    assert 'consensus_swing' in fire(today, past, prior=calmed)


def test_a_swing_hovering_between_the_two_lines_does_not_rearm():
    """20%를 넘었다 18%로 내려온 것은 진정된 게 아니라 같은 국면이다. 15% 아래로 와야
    다시 장전된다 — 안 그러면 임계선 근처에서 오르내릴 때마다 다시 울린다."""
    today, past = snap(eps_fy1=200.0), snap(eps_fy1=155.0)
    hovering = {'consensus_swing': [29.0, 18.0, 17.0]}
    assert 'consensus_swing' not in fire(today, past, prior=hovering)


def test_a_swing_the_other_way_is_a_new_event_even_while_still_beyond_the_line():
    """상향이 이어지다 하향으로 뒤집힌 것은 같은 국면이 아니다."""
    today, past = snap(eps_fy1=110.0), snap(eps_fy1=155.0)    # -29%
    assert 'consensus_swing' in fire(today, past, prior={'consensus_swing': [29.0]})


def test_no_prior_record_means_armed():
    """기록이 짧으면 장전된 것으로 본다. 처음 넘어선 날을 놓치는 것이 더 나쁘다."""
    today, past = snap(eps_fy1=200.0), snap(eps_fy1=155.0)
    assert 'consensus_swing' in fire(today, past, prior=None)
    assert 'consensus_swing' in fire(today, past, prior={'consensus_swing': []})


def test_dispersion_also_speaks_once_per_episode():
    today = snap(eps_fy1_low=80.0, eps_fy1_high=260.0)
    past = snap(eps_fy1_low=110.0, eps_fy1_high=220.0)
    assert 'dispersion_widening' in fire(today, past,
                                         prior={'dispersion_widening': [5.0]})
    assert 'dispersion_widening' not in fire(today, past,
                                             prior={'dispersion_widening': [40.0]})


def test_dispersion_rearms_below_its_own_lower_line():
    today = snap(eps_fy1_low=80.0, eps_fy1_high=260.0)
    past = snap(eps_fy1_low=110.0, eps_fy1_high=220.0)
    assert 'dispersion_widening' in fire(today, past,
                                         prior={'dispersion_widening': [40.0, 15.0]})
    assert 'dispersion_widening' not in fire(today, past,
                                             prior={'dispersion_widening': [40.0, 25.0]})


def test_todays_own_value_never_counts_as_a_past_firing():
    """오늘 값이 과거 목록에 섞이면 처음 넘어선 날조차 「이미 울렸다」로 읽혀서 트리거가
    스스로를 죽인다. 수집기가 오늘 행을 먼저 기록하므로 실제로 일어나는 일이다."""
    rows = [
        {'date': '2026-07-01', 'tickers': {'MU': {'eps_fy1': 100.0, 'eps_fy1_low': 80.0,
                                                  'eps_fy1_high': 120.0}}},
        {'date': '2026-08-24', 'tickers': {'MU': {'eps_fy1': 100.0, 'eps_fy1_low': 80.0,
                                                  'eps_fy1_high': 120.0}}},
        {'date': '2026-08-25', 'tickers': {'MU': {'eps_fy1': 140.0, 'eps_fy1_low': 80.0,
                                                  'eps_fy1_high': 120.0}}},
    ]
    prior = T.prior_metrics(rows, 'MU', before='2026-08-25')
    assert prior['consensus_swing'][-1] is None or abs(prior['consensus_swing'][-1]) < 20
    today = snap(eps_fy1=140.0, eps_fy1_low=80.0, eps_fy1_high=120.0)
    past = snap(eps_fy1=100.0, eps_fy1_low=80.0, eps_fy1_high=120.0)
    assert 'consensus_swing' in fire(today, past, prior=prior)


def test_dispersion_rearms_when_the_spread_actually_narrowed():
    """분산은 방향이 있는 지표다. -25%는 「25% 좁혀졌다」는 뜻이라 재장전선을 한참
    지났는데, 절댓값으로 재면 20~30 사이로 읽혀 억제된다."""
    today = snap(eps_fy1_low=80.0, eps_fy1_high=260.0)
    past = snap(eps_fy1_low=110.0, eps_fy1_high=220.0)
    assert 'dispersion_widening' in fire(today, past,
                                         prior={'dispersion_widening': [40.0, -25.0]})


def test_a_record_that_never_leaves_the_middle_stays_armed():
    today, past = snap(eps_fy1=200.0), snap(eps_fy1=155.0)
    assert 'consensus_swing' in fire(today, past, prior={'consensus_swing': [17.0, 18.0]})


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
    assert fire(snap(), snap(), prev=yesterday()) == set()


def test_a_new_ticker_with_no_history_fires_nothing():
    """첫날은 비교할 어제가 없다. 위치는 페이지가 보여주고, 종은 울리지 않는다."""
    assert fire(snap(price=200.0, eps_fy1=110.0, eps_fy1_low=106.89), None) == set()


def test_each_trigger_carries_a_korean_sentence_and_severity():
    hits = T.evaluate(snap(price=310.0, eps_fy1=110.0), snap(eps_fy1=155.0), FV, True,
                      prev=yesterday(price=966.78, eps_fy1=155.0))
    assert hits
    for t in hits:
        assert t['message'] and t['severity'] in T.SEVERITIES
        assert t['key'] in T.TRIGGER_KEYS


def test_missing_fair_value_disables_price_triggers_only():
    hits = fire(snap(eps_fy1=110.0), snap(eps_fy1=155.0), fv=None, prev=yesterday())
    assert 'consensus_swing' in hits
    assert 'bear_proximity' not in hits


def test_missing_price_is_survivable():
    assert T.evaluate(snap(price=None), None, FV, True, prev=yesterday()) is not None


def test_a_yesterday_row_missing_its_lines_stays_quiet_rather_than_guessing():
    """옛 history 행에는 band·bear가 없다. 기록을 넓히기 전 행이 어제인 하루 동안은 가격
    교차를 판정할 수 없고, 그때는 추측 대신 침묵한다."""
    old = {'price': 966.78, 'eps_fy1': 155.0, 'eps_fy1_low': 106.89}
    assert 'bear_proximity' not in fire(snap(price=310.0), prev=old)
    assert 'bear_exit' not in fire(snap(price=966.78), prev=old)


def test_a_missing_price_fires_no_price_trigger():
    hits = fire(snap(price=None), prev=yesterday(price=310.0))
    assert 'bear_proximity' not in hits and 'bear_exit' not in hits
