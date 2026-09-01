"""일일 굴리기 CLI의 경계 — 「확인할 수 없으면 굴리지 않는다」.

단위 테스트가 통과해도 이 경계들이 열려 있었다(2026-09-01 codex 검토). 여기서만
잡히는 것들이라 CLI 를 그대로 실행해 본다.
"""
import json
import os
import subprocess
import sys

import pytest

from us import portfolio as P

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, 'build_portfolio.py')

PX = {t: 100.0 for t in P.TICKERS}
CALENDAR = ['2026-08-26', '2026-08-27', '2026-08-28', '2026-08-31', '2026-09-01']
GRADES = {'equities': 1, 'bonds': -1, 'fx': -1, 'energy': 0, 'metals': 2,
          'memory': 0, 'ai_infra': 0}


def _write(d, name, blob):
    path = os.path.join(d, name)
    os.makedirs(os.path.dirname(path) or d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(blob, fh, ensure_ascii=False)


def _workspace(tmp_path, report_date, stance_date, prices=True, state=None):
    d = str(tmp_path)
    os.makedirs(os.path.join(d, 'history'), exist_ok=True)
    _write(d, 'market_data.json', {'report_date': report_date})
    _write(d, 'stance.json', {'report_date': stance_date,
                              'assets': {k: {'grade': v} for k, v in GRADES.items()}})
    if prices:
        _write(d, 'portfolio_prices.json',
               {'report_date': report_date, 'as_of': report_date, 'closes': PX,
                'recent': {t: {'2026-08-31': v} for t, v in PX.items()},
                'sessions': CALENDAR, 'missing': []})
    else:
        _write(d, 'portfolio_prices.json', {})
    if state:
        _write(d, 'portfolio_state.json', state)
    return d


def _run(d):
    return subprocess.run([sys.executable, BUILD, '--datadir', d],
                          capture_output=True, text=True)


def _state(date='2026-08-31'):
    from us import portfolio_io as IO
    st = P.open_state(date, PX, GRADES)
    return IO.state_blob(st, grades_from='2026-08-28')


def test_an_unreadable_price_file_stops_the_book(tmp_path):
    d = _workspace(tmp_path, '2026-09-01', '2026-08-31', prices=False)
    r = _run(d)
    assert r.returncode == 1
    assert not os.path.exists(os.path.join(d, 'portfolio.json'))


def test_an_unreadable_price_file_stops_it_even_with_a_standing_book(tmp_path):
    d = _workspace(tmp_path, '2026-09-01', '2026-08-31', prices=False,
                   state=_state())
    assert _run(d).returncode == 1


def test_a_future_dated_book_is_never_applied_even_on_the_first_run(tmp_path):
    """마감 뒤에 정한 등급을 그날 종가에 담는 것이 룩어헤드다."""
    d = _workspace(tmp_path, '2026-08-31', '2026-09-05')
    r = _run(d)
    assert r.returncode == 1
    assert '룩어헤드' in r.stderr


def test_the_opening_session_may_use_its_own_book(tmp_path):
    """첫 손익은 다음 세션부터라 앞을 보지 않는다."""
    d = _workspace(tmp_path, '2026-08-31', '2026-08-31')
    assert _run(d).returncode == 0
    book = json.load(open(os.path.join(d, 'portfolio.json'), encoding='utf-8'))
    assert book['grades_from'] == '2026-08-31'
    assert book['stance_frozen'] is False


def test_a_same_day_book_is_refused_once_a_position_exists(tmp_path):
    d = _workspace(tmp_path, '2026-09-01', '2026-09-01', state=_state())
    r = _run(d)
    assert r.returncode == 0 and '룩어헤드' in r.stderr
    book = json.load(open(os.path.join(d, 'portfolio.json'), encoding='utf-8'))
    assert book['stance_frozen'] is True
    assert book['grades_from'] == '2026-08-28'      # 동결은 출처까지 승계한다


def test_a_missed_session_is_read_off_the_calendar(tmp_path):
    d = _workspace(tmp_path, '2026-09-01', '2026-08-31',
                   state=_state('2026-08-27'))
    assert _run(d).returncode == 0
    book = json.load(open(os.path.join(d, 'portfolio.json'), encoding='utf-8'))
    assert '2026-08-28' in book['gaps'] and '2026-08-31' in book['gaps']
    assert book['performance']['returns']['1d'] is None


@pytest.mark.parametrize('broken', [{}, {'assets': {'equities': {'grade': 1}}}])
def test_a_book_it_cannot_read_freezes_rather_than_neutralises(tmp_path, broken):
    d = _workspace(tmp_path, '2026-09-01', '2026-08-31', state=_state())
    _write(d, 'stance.json', dict(broken, report_date='2026-08-31'))
    assert _run(d).returncode == 0
    book = json.load(open(os.path.join(d, 'portfolio.json'), encoding='utf-8'))
    assert book['stance_frozen'] is True
    metals = next(w for w in book['performance']['weights'] if w['sleeve'] == 'metals')
    assert metals['weight_pct'] == pytest.approx(
        P.sleeve_weights(GRADES)['metals'])       # 중립(6%)으로 내려가지 않는다


@pytest.mark.parametrize('bad', ['09/05/2026', '2026-010-01', '내일', ''])
def test_a_book_whose_date_is_not_a_date_is_not_applied(tmp_path, bad):
    """문자열로 견주면 「09/05/2026」이 「2026-08-31」보다 작다 — 미래 책이 적용된다."""
    d = _workspace(tmp_path, '2026-09-01', '2026-08-31', state=_state())
    _write(d, 'stance.json', {'report_date': bad,
                              'assets': {k: {'grade': v} for k, v in GRADES.items()}})
    r = _run(d)
    assert r.returncode == 0
    book = json.load(open(os.path.join(d, 'portfolio.json'), encoding='utf-8'))
    assert book['stance_frozen'] is True
    assert book['grades_from'] == '2026-08-28'
