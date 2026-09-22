"""매크로 전달경로 방향을 채점하는 성적표 (2026-09-19 스탠스 삭제로 입력을 옮겼다)."""
from us.history import macro_record
from us.scorecard import direction_changes
from us.period_scorecard import realized, score


def row(date, **directions):
    return {'report_date': date,
            'transmission': {k: {'direction': v, 'since': date}
                             for k, v in directions.items()}}


# ── 이력에 방향이 쌓인다 ───────────────────────────────────────────────────
def test_macro_history_now_carries_the_per_asset_direction():
    rec = macro_record({'report_date': '2026-09-19', 'horizon': '3-6개월',
                        'regime': {'growth': '둔화'},
                        'policy_path': {'stance': '인상'},
                        'transmission': {'bonds': {'direction': 1,
                                                   'since': '2026-08-17',
                                                   'channel': '긴 산문 ' * 50,
                                                   'confirm': '조건'}}})
    assert rec['transmission']['bonds']['direction'] == 1
    assert rec['transmission']['bonds']['since'] == '2026-08-17'


def test_the_long_channel_prose_is_not_copied_into_every_history_row():
    rec = macro_record({'report_date': '2026-09-19',
                        'transmission': {'bonds': {'direction': 1, 'since': 'x',
                                                   'channel': '긴 산문 ' * 50}}})
    assert 'channel' not in rec['transmission']['bonds']


def test_a_macro_without_transmission_still_records():
    rec = macro_record({'report_date': '2026-09-19', 'regime': {}})
    assert rec['transmission'] == {}


# ── 이력에서 방향 전환을 뽑는다 ────────────────────────────────────────────
def test_a_direction_flip_becomes_a_scorable_change():
    rows = [row('2026-09-01', bonds=0), row('2026-09-02', bonds=1)]
    assert direction_changes(rows) == [
        {'date': '2026-09-02', 'asset': 'bonds', 'from': 0, 'to': 1}]


def test_holding_the_same_direction_is_not_a_change():
    rows = [row('2026-09-01', bonds=1), row('2026-09-02', bonds=1)]
    assert direction_changes(rows) == []


def test_the_first_row_is_not_a_change_there_is_nothing_before_it():
    assert direction_changes([row('2026-09-01', bonds=1)]) == []


def test_rows_are_read_in_date_order_whatever_order_they_arrive():
    rows = [row('2026-09-02', bonds=1), row('2026-09-01', bonds=0)]
    assert [c['date'] for c in direction_changes(rows)] == ['2026-09-02']


def test_an_asset_that_appears_later_is_not_a_change_from_nothing():
    rows = [row('2026-09-01', bonds=1), row('2026-09-02', bonds=1, fx=-1)]
    assert direction_changes(rows) == []


def test_every_asset_flip_in_one_day_is_reported():
    rows = [row('2026-09-01', bonds=0, fx=0), row('2026-09-02', bonds=1, fx=-1)]
    assert {c['asset'] for c in direction_changes(rows)} == {'bonds', 'fx'}


# ── 기간 성적표가 같은 자리에서 읽는다 ─────────────────────────────────────
def test_period_score_reads_the_transmission_direction():
    agg = {'start_date': '2026-09-01', 'end_date': '2026-09-30',
           'indices': {'S&P 500': {'pct': 2.0}},
           'yields': {'10Y': {'chg_bp': -10.0}}}
    out = score([row('2026-09-01', equities=1, bonds=1)], agg)
    assert out['assets']['equities']['grade'] == 1
    assert out['assets']['equities']['verdict'] == '적중'
    assert out['assets']['bonds']['grade'] == 1


def test_the_bond_sign_convention_survives_the_move():
    # 롱 듀레이션(+1) 은 금리가 내려야 맞은 것이다
    agg = {'start_date': '2026-09-01', 'end_date': '2026-09-30',
           'yields': {'10Y': {'chg_bp': -10.0}}}
    assert realized(agg)['bonds'] == 10.0
