"""채권 조기 폐장일(SIFMA 2:00 p.m. ET)은 14:00 에 끊는다 — 16:00 에는 시세가 없다(2026-11-23)."""
import datetime as dt

from us import yield_cut as Y


def pts(day, hhmm_vals):
    return {t: [(day, h, v) for h, v in hhmm_vals] for t in Y.TENORS}


def test_target_for_early_close_and_normal_day():
    assert Y.target_for('2026-11-27') == '14:00'
    assert Y.target_for('2026-11-25') == '16:00'


def test_early_close_day_picks_the_1400_point_and_ledger_accepts_it():
    naver = pts('2026-11-27', [('13:58', 4.1), ('14:01', 4.2)])
    led = {}
    changed = Y.update(led, '2026-11-27', set(), naver, now_et=dt.datetime(2026, 11, 27, 16, 50))
    assert changed == ['2026-11-27']
    assert led['2026-11-27']['target'] == '14:00'
    assert led['2026-11-27']['tenors']['10Y'] == {'value': 4.2, 'stamp': '14:01'}
    assert Y._entry_problem('2026-11-27', led['2026-11-27']) is None


def test_normal_day_still_rejects_a_1400_stamp():
    e = {'source': 'naver', 'target': '14:00',
         'tenors': {t: {'value': 4.0, 'stamp': '14:00'} for t in Y.TENORS}}
    assert Y._entry_problem('2026-11-25', e)


def test_early_close_window_closes_at_1415():
    assert not Y.window_closed('2026-11-27', dt.datetime(2026, 11, 27, 14, 10))
    assert Y.window_closed('2026-11-27', dt.datetime(2026, 11, 27, 14, 15))


def test_caption_names_each_days_cut_time():
    closed = {'2026-11-26'}
    normal = Y.caption('2026-11-20', closed)
    assert normal.startswith('국채 금리는 뉴욕 16:00 ET 무렵 장중 값(전 거래일·1주 전도 같은 시각)')
    assert '뉴욕 14:00 ET 무렵 값이다(전 거래일 16:00, 1주 전 16:00' in Y.caption('2026-11-27', closed)
    # 11/30 — 당일 16:00, 전 거래일 11/27 은 조기 폐장 14:00 (codex 구현 검토 1회차 #4)
    assert '뉴욕 16:00 ET 무렵 값이다(전 거래일 14:00, 1주 전 16:00' in Y.caption('2026-11-30', closed)
    # 12/4 — 1주 전(5세션 전)이 11/27
    assert '(전 거래일 16:00, 1주 전 14:00' in Y.caption('2026-12-04', closed)
