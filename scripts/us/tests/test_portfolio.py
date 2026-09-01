"""모의 포트폴리오 — 비중 산출·굴리기·성과 집계.

이 모듈이 지켜야 할 것은 세 가지다. ① 비중은 등급에서만 나온다(창작 금지)
② 레버리지를 쓰지 않는다 ③ 원장을 다시 굴려도 과거가 바뀌지 않는다.
"""
import pytest

from us import portfolio as P


NEUTRAL = {k: 0 for k in ('equities', 'bonds', 'fx', 'energy', 'metals',
                          'memory', 'ai_infra')}


def g(**kw):
    d = dict(NEUTRAL)
    d.update(kw)
    return d


# ── 비중 ────────────────────────────────────────────────────────────────
def test_neutral_book_sums_to_100():
    w = P.sleeve_weights(NEUTRAL)
    assert sum(w.values()) == pytest.approx(100.0)


def test_neutral_book_holds_cash_not_leverage():
    w = P.sleeve_weights(NEUTRAL)
    assert w['cash'] > 0
    assert all(v >= 0 for v in w.values())


def test_equity_grade_moves_the_equity_family():
    up = P.sleeve_weights(g(equities=1))
    flat = P.sleeve_weights(NEUTRAL)
    assert up['equity_core'] > flat['equity_core']
    # 메모리·AI 인프라는 주식 등급이 아니라 제 등급으로만 움직인다
    assert up['memory'] == flat['memory']


def test_memory_overweight_is_funded_from_the_equity_core():
    """상대비중이라는 §10의 정의를 비중에서도 지킨다 — 패밀리 합계가 고정."""
    flat, ow = P.sleeve_weights(NEUTRAL), P.sleeve_weights(g(memory=2))
    fam = lambda w: w['equity_core'] + w['memory'] + w['ai_infra']
    assert fam(ow) == pytest.approx(fam(flat))
    assert ow['memory'] > flat['memory']
    assert ow['equity_core'] < flat['equity_core']


def test_memory_underweight_is_implementable():
    """중립 비중이 0이면 UW와 중립이 같은 책이 된다 — 구분돼야 한다."""
    flat, uw = P.sleeve_weights(NEUTRAL), P.sleeve_weights(g(memory=-2))
    assert uw['memory'] < flat['memory']
    assert uw['memory'] >= 0


def test_bond_grade_is_duration_not_allocation():
    short = P.sleeve_weights(g(bonds=-1))
    long_ = P.sleeve_weights(g(bonds=2))
    fi = lambda w: w['bonds_long'] + w['bonds_short']
    assert fi(short) == pytest.approx(fi(long_))
    assert short['bonds_long'] < long_['bonds_long']


def test_dollar_grade_picks_the_side():
    short = P.sleeve_weights(g(fx=-1))
    long_ = P.sleeve_weights(g(fx=1))
    assert short['fx_short'] > 0 and short['fx_long'] == 0
    assert long_['fx_long'] > 0 and long_['fx_short'] == 0
    assert P.sleeve_weights(NEUTRAL)['fx_short'] == 0


def test_no_leverage_when_tilts_overspend():
    w = P.sleeve_weights(g(equities=2, metals=2, energy=2, fx=2, memory=2, ai_infra=2))
    assert sum(w.values()) == pytest.approx(100.0)
    assert w['cash'] == pytest.approx(0.0)
    assert all(v >= 0 for v in w.values())


def test_grades_are_clamped_to_the_controlled_range():
    assert P.sleeve_weights(g(equities=7)) == P.sleeve_weights(g(equities=2))
    assert P.sleeve_weights(g(metals=-9)) == P.sleeve_weights(g(metals=-2))


def test_missing_grade_reads_as_neutral():
    assert P.sleeve_weights({}) == P.sleeve_weights(NEUTRAL)


def test_instrument_weights_split_baskets_equally():
    w = P.instrument_weights(g(memory=2))
    mem = P.sleeve_weights(g(memory=2))['memory']
    for t in ('MU', 'WDC', 'STX'):
        assert w[t] == pytest.approx(mem / 3)
    assert sum(w.values()) == pytest.approx(100.0)


def test_zero_weight_sleeves_are_not_held():
    w = P.instrument_weights(NEUTRAL)
    assert 'UDN' not in w and 'UUP' not in w


# ── 굴리기 ──────────────────────────────────────────────────────────────
PX0 = {t: 100.0 for t in P.TICKERS}


def test_open_book_invests_the_whole_nav():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    assert b['nav'] == pytest.approx(P.BASE_NAV)
    assert sum(u * PX0[t] for t, u in b['units'].items()) == pytest.approx(P.BASE_NAV)


def test_flat_prices_leave_nav_unchanged():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    b2, row = P.advance(b, '2026-08-17', PX0, NEUTRAL)
    assert b2['nav'] == pytest.approx(P.BASE_NAV)
    assert row['ret_pct'] == pytest.approx(0.0)


def test_contributions_sum_to_the_daily_return():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    px = dict(PX0, SPY=110.0, GLD=90.0)
    _, row = P.advance(b, '2026-08-17', px, NEUTRAL)
    assert sum(row['contrib'].values()) == pytest.approx(row['ret_pct'])


def test_no_rebalance_while_the_grades_stand():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    b2, row = P.advance(b, '2026-08-17', dict(PX0, SPY=120.0), NEUTRAL)
    assert row['rebalanced'] is False
    assert b2['units'] == b['units']          # 비중은 가격을 따라 표류한다
    assert b2['weights']['equity_core'] > b['weights']['equity_core']


def test_a_grade_change_rebalances_at_that_close():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    b2, row = P.advance(b, '2026-08-17', PX0, g(metals=2))
    assert row['rebalanced'] is True
    assert b2['weights']['metals'] == pytest.approx(
        P.sleeve_weights(g(metals=2))['metals'])


def test_rebalance_conserves_nav():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    px = dict(PX0, SPY=130.0, GLD=80.0)
    b2, row = P.advance(b, '2026-08-17', px, g(equities=2))
    assert sum(u * px[t] for t, u in b2['units'].items()) == pytest.approx(b2['nav'])
    assert b2['nav'] == pytest.approx(P.BASE_NAV * (1 + row['ret_pct'] / 100))


def test_a_missing_price_refuses_to_roll():
    """값이 없는 날 앞의 값으로 메우면 원장이 조용히 틀려진다."""
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    px = {t: v for t, v in PX0.items() if t != 'SPY'}
    with pytest.raises(ValueError):
        P.advance(b, '2026-08-17', px, NEUTRAL)


# ── 두 책(액티브·중립) ──────────────────────────────────────────────────
def test_step_runs_the_benchmark_alongside():
    st = P.open_state('2026-08-14', PX0, g(metals=2))
    st2, row = P.step(st, '2026-08-17', dict(PX0, GLD=110.0), g(metals=2))
    assert row['nav'] > row['bench_nav']          # 금 비중이 더 크니 더 벌어야 한다
    assert row['active_pct'] == pytest.approx(row['ret_pct'] - row['bench_ret_pct'])


def test_benchmark_holds_the_neutral_book_whatever_the_grades():
    st = P.open_state('2026-08-14', PX0, g(equities=2, metals=2))
    assert st['bench']['weights'] == P.sleeve_weights(P.NEUTRAL_GRADES)


def test_benchmark_resets_on_the_active_rebalance_dates():
    """표류 차이가 섞이면 초과수익이 틸트만의 것이 아니게 된다."""
    st = P.open_state('2026-08-14', PX0, NEUTRAL)
    st, _ = P.step(st, '2026-08-17', dict(PX0, SPY=150.0), NEUTRAL)
    drifted = st['bench']['weights']['equity_core']
    st, row = P.step(st, '2026-08-18', dict(PX0, SPY=150.0), g(metals=1))
    assert row['rebalanced'] is True
    assert drifted != pytest.approx(st['bench']['weights']['equity_core'])
    assert st['bench']['weights'] == pytest.approx(
        P.sleeve_weights(P.NEUTRAL_GRADES))


# ── 성과 집계 ───────────────────────────────────────────────────────────
def _rows(n, daily=0.5, bench_daily=0.25):
    rows, nav, bench = [], P.BASE_NAV, P.BASE_NAV
    for i in range(n):
        nav *= 1 + daily / 100
        bench *= 1 + bench_daily / 100
        rows.append({'report_date': f'2026-06-{i + 1:02d}', 'nav': nav,
                     'ret_pct': daily, 'bench_nav': bench,
                     'bench_ret_pct': bench_daily,
                     'active_pct': daily - bench_daily,
                     'contrib': {'equity_core': daily}, 'rebalanced': False,
                     'weights': P.sleeve_weights(NEUTRAL), 'grades': dict(NEUTRAL)})
    return rows


def test_summary_reports_inception_and_period_returns():
    s = P.summarize(_rows(25))
    assert s['sessions'] == 25
    assert s['inception'] == '2026-06-01'
    assert s['returns']['itd']['portfolio'] == pytest.approx((1.005 ** 25 - 1) * 100)
    assert s['returns']['1w']['portfolio'] == pytest.approx((1.005 ** 5 - 1) * 100)
    assert s['returns']['1d']['active'] == pytest.approx(0.25)


def test_periods_longer_than_the_record_are_omitted_not_guessed():
    s = P.summarize(_rows(3))
    assert s['returns']['1w'] is None
    assert s['returns']['itd'] is not None


def test_short_record_forbids_annualised_statistics():
    assert P.summarize(_rows(10))['insufficient'] is True
    assert P.summarize(_rows(P.MIN_SESSIONS))['insufficient'] is False


def test_contribution_is_reported_with_its_compounding_residual():
    s = P.summarize(_rows(25))
    total = sum(c['itd'] for c in s['contrib'].values())
    assert s['residual_pct'] == pytest.approx(
        s['returns']['itd']['portfolio'] - total)


def test_drawdown_is_measured_from_the_running_peak():
    rows = _rows(5)
    rows[3]['nav'] = rows[2]['nav'] * 0.9
    rows[4]['nav'] = rows[2]['nav'] * 0.95
    s = P.summarize(rows)
    assert s['max_drawdown_pct'] == pytest.approx(-10.0, abs=1e-6)


def test_summary_of_an_empty_ledger_says_nothing():
    s = P.summarize([])
    assert s['sessions'] == 0 and s['insufficient'] is True
    assert s['returns']['itd'] is None


def test_rebalance_history_names_what_moved():
    rows = _rows(3)
    rows[2]['rebalanced'] = True
    rows[2]['grades'] = g(metals=2)
    s = P.summarize(rows)
    assert s['rebalances'][-1]['report_date'] == rows[2]['report_date']
    assert s['rebalances'][-1]['changed'] == {'metals': {'from': 0, 'to': 2}}


def test_current_weights_are_reported_against_neutral():
    s = P.summarize(_rows(3))
    row = next(r for r in s['weights'] if r['sleeve'] == 'cash')
    assert row['neutral_pct'] == pytest.approx(
        P.sleeve_weights(P.NEUTRAL_GRADES)['cash'])
    assert row['diff_pct'] == pytest.approx(row['weight_pct'] - row['neutral_pct'])


# ── 이어 굴리기 ─────────────────────────────────────────────────────────
def test_replay_opens_on_the_first_session_and_rolls_the_rest():
    px = {d: dict(PX0) for d in ('2026-08-14', '2026-08-17', '2026-08-18')}
    px['2026-08-17']['SPY'] = 110.0
    state, rows, gaps = P.replay(sorted(px), px, lambda d: NEUTRAL)
    assert state['inception'] == '2026-08-14'
    assert [r['report_date'] for r in rows] == ['2026-08-17', '2026-08-18']
    assert gaps == []


def test_replay_skips_a_session_it_cannot_price():
    """건너뛴 날의 수익률은 다음 성공한 날이 그대로 덮는다 — 좌수가 그대로니까."""
    px = {'2026-08-14': dict(PX0),
          '2026-08-17': {t: v for t, v in PX0.items() if t != 'SPY'},
          '2026-08-18': dict(PX0, SPY=110.0)}
    _, rows, gaps = P.replay(sorted(px), px, lambda d: NEUTRAL)
    assert gaps == ['2026-08-17']
    assert [r['report_date'] for r in rows] == ['2026-08-18']
    assert rows[0]['ret_pct'] > 0


def test_summary_takes_the_inception_from_the_book_not_the_first_return_day():
    rows = _rows(3)
    assert P.summarize(rows, inception='2026-05-30')['inception'] == '2026-05-30'


# ── 건너뛴 세션은 「어제 하루」가 아니다 (2026-09-01 codex 지적) ─────────
def _dated(dates, daily=0.5):
    rows, nav, bench = [], P.BASE_NAV, P.BASE_NAV
    for d in dates:
        nav *= 1 + daily / 100
        bench *= 1 + daily / 200
        rows.append({'report_date': d, 'nav': nav, 'ret_pct': daily,
                     'bench_nav': bench, 'bench_ret_pct': daily / 2,
                     'active_pct': daily / 2, 'contrib': {}, 'rebalanced': False,
                     'weights': P.sleeve_weights(NEUTRAL), 'grades': dict(NEUTRAL)})
    return rows


def test_a_gap_before_the_last_row_voids_the_one_day_reading():
    """08-28 을 건너뛴 원장에서 마지막 행의 수익률은 이틀치다 — 하루라 부를 수 없다."""
    rows = _dated(['2026-08-26', '2026-08-27', '2026-08-31'])
    s = P.summarize(rows, gaps=['2026-08-28'])
    assert s['returns']['1d'] is None
    assert s['returns']['itd'] is not None


def test_a_period_says_which_sessions_it_covers():
    rows = _dated(['2026-08-26', '2026-08-27', '2026-08-31'])
    s = P.summarize(rows, gaps=['2026-08-28'])
    assert s['returns']['itd']['to'] == '2026-08-31'
    assert s['returns']['itd']['spans_gap'] is True


def test_a_clean_ledger_keeps_its_one_day_reading():
    rows = _dated(['2026-08-26', '2026-08-27', '2026-08-28'])
    s = P.summarize(rows, gaps=['2026-08-31'])       # 창 밖의 결측은 무관하다
    assert s['returns']['1d'] is not None
    assert s['returns']['1d']['spans_gap'] is False


# ── 소급 조정된 종가 (2026-09-01 codex 지적) ────────────────────────────
def test_a_split_restates_history_and_must_be_re_anchored():
    """auto_adjust 종가는 배당·분할 때 과거가 소급 조정된다. 좌수를 함께 고치지
    않으면 가치가 그대로인데 수익률이 반토막 난다."""
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    fresh_prev = dict(PX0, SPY=50.0)                 # 2:1 분할로 과거가 반값이 됨
    b2 = P.reanchor(b, fresh_prev)
    assert b2['nav'] == pytest.approx(b['nav'])      # 가치는 그대로
    assert b2['units']['SPY'] == pytest.approx(b['units']['SPY'] * 2)
    _, row = P.advance(b2, '2026-08-17', dict(PX0, SPY=50.0), NEUTRAL)
    assert row['ret_pct'] == pytest.approx(0.0)      # 실제로는 아무 일도 없었다


def test_re_anchoring_leaves_an_unchanged_basis_alone():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    assert P.reanchor(b, dict(PX0))['units'] == b['units']


def test_re_anchoring_ignores_prices_it_cannot_check():
    b = P.open_book('2026-08-14', PX0, NEUTRAL)
    assert P.reanchor(b, {'SPY': 0})['units'] == b['units']
