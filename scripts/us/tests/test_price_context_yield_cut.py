"""국채 당일 변화는 표의 16:00 ET 컷 bp 로 — 야후 15:00 일봉 변화가 표와 어긋나지 않게."""
from us import price_context as PC


def _closes(n=70):
    # 하루 ±0.04pp 로 오가는 계열 — 평소 하루 변화의 표준편차가 약 0.04
    return {'^TNX': [4.0 + (0.02 if i % 2 else -0.02) for i in range(n)]}


def test_move_uses_cut_bp_when_row_is_cut():
    moves = {'10Y': {'change': -0.05, 'unit': 'pp'}}
    md = {'yields': {'10Y': {'basis': 'cut_1600_et', 'bp': 3.0}}}
    PC.align_yield_moves(moves, _closes(), md)
    m = moves['10Y']
    assert m['change'] == 0.03 and m['basis'] == 'cut_1600_et'
    assert m['multiple'] is not None and m['band'] == PC.move_band(m['multiple'])


def test_untouched_without_cut_or_bp():
    moves = {'10Y': {'change': -0.05}, '30Y': {'change': 0.01}}
    md = {'yields': {'10Y': {'bp': 3.0}, '30Y': {'basis': 'cut_1600_et', 'bp': None}}}
    PC.align_yield_moves(moves, {}, md)
    assert moves == {'10Y': {'change': -0.05}, '30Y': {'change': 0.01}}


def test_bond_holiday_row_is_not_todays_move():
    moves = {'10Y': {'change': 0.01}}
    md = {'report_date': '2026-11-11',
          'yields': {'10Y': {'basis': 'cut_1600_et', 'bp': 5.0, 'date': '2026-11-10'}}}
    PC.align_yield_moves(moves, _closes(), md)
    assert moves['10Y'] is None


def test_level_position_uses_the_cut_value_not_yahoo_last():
    closes = {'^TNX': [4.0 + 0.01 * i for i in range(60)] + [4.30]}   # 야후 마지막(15:00) 4.30 = 최고
    levels = {'10Y': {'value': 4.30, 'percentile': 100.0}}
    md = {'report_date': '2026-11-06',
          'yields': {'10Y': {'basis': 'cut_1600_et', 'level': 4.20, 'date': '2026-11-06'}}}
    PC.align_yield_levels(levels, closes, md)
    lv = levels['10Y']
    assert lv['value'] == 4.20 and lv['basis'] == 'cut_1600_et'
    assert lv['percentile'] < 100.0                                  # 16:00 값은 최고가 아니다


def test_level_cleared_on_bond_holiday():
    # 휴장일 표는 직전 세션 16:00 컷(4.20), 야후 마지막은 15:00(4.30) — 어긋난 위치를 남기지 않는다
    levels = {'10Y': {'value': 4.3}}
    md = {'report_date': '2026-11-11',
          'yields': {'10Y': {'basis': 'cut_1600_et', 'level': 4.2, 'date': '2026-11-10'}}}
    PC.align_yield_levels(levels, {'^TNX': [4.0] * 61}, md)
    assert levels['10Y'] is None


def test_level_keeps_the_last_bar_when_it_is_not_today():
    # 야후 봉이 하루 늦으면(마지막 봉 = 전일) 그 봉은 지난 이력이다 — 빼지 않는다
    seq = [4.0] * 59 + [4.5]
    dates = {'^TNX': [f'd{i}' for i in range(59)] + ['2026-11-05']}
    md = {'report_date': '2026-11-06',
          'yields': {'10Y': {'basis': 'cut_1600_et', 'level': 4.4, 'date': '2026-11-06'}}}
    levels = {}
    PC.align_yield_levels(levels, {'^TNX': seq}, md, dates=dates)
    assert levels['10Y']['sessions'] == 60 and levels['10Y']['percentile'] < 100.0
