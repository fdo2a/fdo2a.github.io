"""하루 시차 — 마감 뒤에 결정한 등급을 그날 종가에 담으면 룩어헤드다."""
from us import portfolio_io as IO


ROWS = [
    {'report_date': '2026-08-14', 'assets': {'equities': {'grade': 0},
                                             'metals': {'grade': 1}}},
    {'report_date': '2026-08-17', 'assets': {'equities': {'grade': 1},
                                             'metals': {'grade': 1}}},
    {'report_date': '2026-08-18', 'assets': {'equities': {'grade': 1},
                                             'metals': {'grade': 2}}},
]


def test_a_session_uses_the_book_published_before_it():
    lookup = IO.grades_lookup(ROWS)
    assert lookup('2026-08-18')['metals'] == 1     # 08-18 책(2)이 아니라 08-17 책
    assert lookup('2026-08-19')['metals'] == 2


def test_the_inception_session_uses_its_own_book():
    """첫 손익은 다음 세션부터라 앞을 보는 것이 아니다."""
    assert IO.grades_lookup(ROWS)('2026-08-14')['metals'] == 1


def test_a_session_before_any_book_reads_as_neutral():
    lookup = IO.grades_lookup(ROWS)
    assert lookup('2026-08-13') == IO.grades_of(None)


def test_unlisted_assets_read_as_neutral_not_as_missing():
    g = IO.grades_of({'assets': {'equities': {'grade': 2}}})
    assert g['equities'] == 2 and g['bonds'] == 0


def test_a_broken_grade_does_not_take_the_book_down():
    assert IO.grades_of({'assets': {'equities': {'grade': 'x'}}})['equities'] == 0


def test_out_of_order_history_is_sorted_before_it_is_read():
    lookup = IO.grades_lookup(list(reversed(ROWS)))
    assert lookup('2026-08-19')['metals'] == 2


def test_the_applied_book_is_named_by_its_own_date():
    """비중을 만든 책이 어느 날 것인지 — 발행본이 그 날짜를 밝힌다."""
    assert IO.book_lookup(ROWS)('2026-08-19')['report_date'] == '2026-08-18'
    assert IO.book_lookup(ROWS)('2026-08-14')['report_date'] == '2026-08-14'


# ── 원장과 책이 갈리면 만들지 않는다 (2026-09-01 codex 지적) ────────────
import pytest  # noqa: E402

from us import portfolio as P  # noqa: E402

_PX = {t: 100.0 for t in P.TICKERS}
_NEUTRAL = dict(P.NEUTRAL_GRADES)


def _state_and_rows():
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    st, row = P.step(st, '2026-08-17', dict(_PX, SPY=110.0), _NEUTRAL)
    return st, [row]


def test_a_publishable_book_matches_its_ledger():
    st, rows = _state_and_rows()
    book = IO.publishable(st, rows, '2026-08-17', [], '2026-08-14')
    assert book['performance']['report_date'] == book['as_of']


def test_a_ledger_that_stops_short_refuses_to_publish():
    st, rows = _state_and_rows()
    rows[-1] = dict(rows[-1], report_date='2026-08-14')
    with pytest.raises(ValueError):
        IO.publishable(st, rows, '2026-08-17', [], '2026-08-14')


def test_a_ledger_whose_value_disagrees_refuses_to_publish():
    st, rows = _state_and_rows()
    rows[-1] = dict(rows[-1], nav=rows[-1]['nav'] + 5)
    with pytest.raises(ValueError):
        IO.publishable(st, rows, '2026-08-17', [], '2026-08-14')


def test_a_corrupt_ledger_line_is_fatal_not_skipped(tmp_path):
    """성과 원장에서 한 줄이 조용히 빠지면 수익률이 조용히 달라진다."""
    path = tmp_path / 'portfolio.jsonl'
    path.write_text('{"report_date": "2026-08-17", "nav": 1000}\n{ broken\n',
                    encoding='utf-8')
    with pytest.raises(ValueError):
        IO.read_ledger(str(path))


def _recent(date='2026-08-14', **overrides):
    out = {t: {date: _PX[t]} for t in P.TICKERS}
    for t, px in overrides.items():
        out[t] = {date: px}
    return out


def test_re_basing_only_reads_the_books_own_session():
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    recent = _recent()
    recent['SPY'] = {'2026-08-13': 50.0, '2026-08-14': _PX['SPY']}
    assert IO.rebase(st, recent)[1] == []


def test_re_basing_reports_what_moved():
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    st2, moved = IO.rebase(st, _recent(SPY=50.0))
    assert moved == ['SPY']
    assert st2['active']['nav'] == pytest.approx(st['active']['nav'])
    assert st2['bench']['units']['SPY'] == pytest.approx(
        st['bench']['units']['SPY'] * 2)


def test_re_basing_covers_a_holding_only_the_benchmark_has():
    """BIL 은 중립 책만 담는다 — 액티브 기준으로만 훑으면 벤치마크가 조용히 틀어진다."""
    st = P.open_state('2026-08-14', _PX, {'equities': 2, 'metals': 2, 'energy': 2,
                                          'fx': 2, 'memory': 2, 'ai_infra': 2,
                                          'bonds': 0})
    assert 'BIL' not in st['active']['units'] and 'BIL' in st['bench']['units']
    st2, moved = IO.rebase(st, _recent(BIL=50.0))
    assert moved == ['BIL']
    assert st2['bench']['nav'] == pytest.approx(st['bench']['nav'])


def test_re_basing_survives_a_skipped_session():
    """한 세션을 건너뛴 뒤에도 이 책의 기준일 값으로 비교한다."""
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    recent = _recent()
    recent['SPY'] = {'2026-08-14': 50.0, '2026-08-17': 51.0}
    assert IO.rebase(st, recent)[1] == ['SPY']


def test_a_half_broken_stance_refuses_to_read_as_neutral():
    with pytest.raises(ValueError):
        IO.grades_of({'assets': {'equities': {'grade': 1}}}, strict=True)


def test_the_applied_book_is_remembered_in_the_state():
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    blob = IO.state_blob(st, grades_from='2026-08-13', stance_frozen=True)
    assert blob['grades_from'] == '2026-08-13' and blob['stance_frozen'] is True


# ── 2026-09-01 codex 3차: 확인할 수 없으면 굴리지 않는다 ────────────────
def test_re_basing_refuses_when_it_cannot_see_the_books_own_session():
    """상태 기준일이 넘겨받은 창 밖이면 분할이 있었는지 알 방법이 없다."""
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    far = {t: {'2026-09-10': 100.0} for t in st['active']['prices']}
    with pytest.raises(ValueError):
        IO.rebase(st, far)


def test_re_basing_refuses_when_nothing_was_handed_over():
    st = P.open_state('2026-08-14', _PX, _NEUTRAL)
    with pytest.raises(ValueError):
        IO.rebase(st, {})


def test_missing_sessions_are_read_off_the_market_calendar():
    calendar = ['2026-08-25', '2026-08-26', '2026-08-27', '2026-08-28', '2026-08-31']
    assert IO.missing_sessions(calendar, '2026-08-26', '2026-08-31',
                               {'2026-08-27'}) == ['2026-08-28']


def test_an_unverifiable_calendar_is_not_an_empty_one():
    with pytest.raises(ValueError):
        IO.missing_sessions([], '2026-08-26', '2026-08-31', set())
    with pytest.raises(ValueError):
        IO.missing_sessions(['2026-08-31'], '2026-08-26', '2026-08-31', set())
