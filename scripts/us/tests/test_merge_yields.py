"""발행용 커브 우선순위 — 네이버는 «전부 아니면 전무»로 쓴다.

일부 만기만 네이버로 채우면 남은 만기가 야후·FRED 날짜를 달고 들어와, 2026-09-04에
고치려던 기준일 어긋남이 그대로 재현된다. 그래서 네 만기가 다 차야 네이버를 쓴다.
"""
import importlib

cmd = importlib.import_module('collect_market_data')


def _row(level, date, source, bp=1.0):
    return {'level': level, 'date': date, 'source': source, 'bp': bp}


FRED = {t: _row(4.0, '2026-09-01', 'FRED') for t in ('2Y', '5Y', '10Y', '30Y')}
YAHOO = {t: _row(4.5, '2026-09-02', 'Yahoo') for t in ('5Y', '10Y', '30Y')}
NAVER = {t: _row(4.7, '2026-09-02', 'Naver') for t in ('2Y', '5Y', '10Y', '30Y')}


def test_complete_naver_curve_wins_every_tenor():
    out = cmd.merge_yields(FRED, YAHOO, NAVER)
    assert {t: r['source'] for t, r in out.items()} == {t: 'Naver' for t in NAVER}
    assert len({r['date'] for r in out.values()}) == 1


def test_partial_naver_curve_is_discarded_whole():
    partial = {t: v for t, v in NAVER.items() if t != '2Y'}
    out = cmd.merge_yields(FRED, YAHOO, partial)
    assert out['10Y']['source'] == 'Yahoo'
    assert out['2Y']['source'] == 'FRED'


def test_naver_row_without_a_level_counts_as_missing():
    holed = dict(NAVER, **{'2Y': _row(None, '2026-09-02', 'Naver')})
    assert cmd.merge_yields(FRED, YAHOO, holed)['10Y']['source'] == 'Yahoo'


def test_falls_back_to_the_old_chain_when_naver_is_absent():
    out = cmd.merge_yields(FRED, YAHOO, None)
    assert out['10Y']['source'] == 'Yahoo'
    assert out['2Y']['source'] == 'FRED'


def test_a_curve_without_a_previous_session_is_discarded_whole():
    """전일比를 못 만드는 커브는 통째로 버리고 야후·FRED 로 넘긴다.

    비교 구간이 늘어난 날 bp 가 비는데, 그 상태로 실으면 표의 「전일比」 칸이 통째로
    빈다. 폴백 사슬은 그날도 정상적인 전일 대비를 갖고 있다.
    """
    no_bp = {t: dict(v, bp=None) for t, v in NAVER.items()}
    assert cmd.merge_yields(FRED, YAHOO, no_bp)['10Y']['source'] == 'Yahoo'
