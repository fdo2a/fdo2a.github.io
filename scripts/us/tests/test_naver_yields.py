"""네이버 국채 종가 파서 — 만기별 기준일을 하나로 맞추는 것이 존재 이유다.

2026-07-28 이래 발행용 미국 커브는 5Y/10Y/30Y 야후 스팟 + 2Y FRED DGS2(T-1) 였다.
야후에 2년 스팟 지수가 없어서 생긴 우회인데, 그 탓에 2s10s 두 다리의 날짜가 갈렸다
(실측 90영업일 중앙 3.4bp·최대 11.8bp 오차). 네이버는 전 만기를 17:05 ET 종가로
같은 날짜에 준다(실측 120/120 영업일 정렬). 여기 함수들이 그 정렬을 강제한다.
"""
import pytest

from scripts.us import naver_yields as ny


def _payload(rows):
    return {'isSuccess': True, 'result': [
        {'localTradedAt': f'{d}T17:05:00-04:00', 'closePrice': c} for d, c in rows]}


def test_parse_prices_reads_date_and_close():
    got = ny.parse_prices(_payload([('2026-09-02', '4.7940'), ('2026-09-01', '4.7960')]))
    assert got == [('2026-09-01', 4.796), ('2026-09-02', 4.794)]


def test_parse_prices_strips_thousands_separator():
    assert ny.parse_prices(_payload([('2026-09-02', '1,844.00')])) == [('2026-09-02', 1844.0)]


def test_parse_prices_skips_rows_without_a_close():
    payload = {'result': [{'localTradedAt': '2026-09-02T17:05:00-04:00', 'closePrice': None},
                          {'localTradedAt': '2026-09-01T17:05:00-04:00', 'closePrice': '4.79'}]}
    assert ny.parse_prices(payload) == [('2026-09-01', 4.79)]


def test_common_date_is_latest_date_present_in_every_tenor():
    # 10Y 가 하루 앞서 있어도 2Y 가 못 따라오면 그 날짜를 쓰면 안 된다.
    series = {'2Y': [('2026-09-01', 4.39), ('2026-09-02', 4.386)],
              '10Y': [('2026-09-02', 4.794), ('2026-09-03', 4.75)]}
    assert ny.common_date(series) == '2026-09-02'


def test_common_date_is_none_when_no_date_is_shared():
    series = {'2Y': [('2026-09-01', 4.39)], '10Y': [('2026-09-02', 4.794)]}
    assert ny.common_date(series) is None


def test_build_curve_puts_every_tenor_on_one_date():
    series = {'2Y': [('2026-08-31', 4.35), ('2026-09-01', 4.394), ('2026-09-02', 4.386)],
              '10Y': [('2026-08-31', 4.758), ('2026-09-01', 4.796), ('2026-09-02', 4.794)]}
    curve = ny.build_curve(series)
    assert {t: r['date'] for t, r in curve.items()} == {'2Y': '2026-09-02', '10Y': '2026-09-02'}
    assert curve['2Y']['level'] == 4.386
    assert curve['2Y']['source'] == 'Naver'


def test_build_curve_bp_is_change_from_the_previous_session():
    series = {'10Y': [('2026-09-01', 4.796), ('2026-09-02', 4.794)]}
    assert ny.build_curve(series)['10Y']['bp'] == pytest.approx(-0.2)


def test_build_curve_week_ago_shares_one_date_across_tenors():
    days = ['2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27', '2026-08-28',
            '2026-08-31', '2026-09-01', '2026-09-02']
    series = {'2Y': [(d, 4.0 + i / 100) for i, d in enumerate(days)],
              '10Y': [(d, 4.5 + i / 100) for i, d in enumerate(days)]}
    curve = ny.build_curve(series)
    assert curve['2Y']['week_ago_date'] == curve['10Y']['week_ago_date'] == '2026-08-26'


def test_build_curve_returns_none_when_tenors_share_no_date():
    series = {'2Y': [('2026-09-01', 4.39)], '10Y': [('2026-09-02', 4.794)]}
    assert ny.build_curve(series) is None


# --- codex 검토 반영 (2026-09-04) --------------------------------------------

def test_build_curve_rejects_a_curve_that_is_not_the_expected_session():
    """겨울 크론 함정 — 21:30 UTC 는 EST 로 16:30, 국채 마감(17:05) 전이다.

    그때 네이버가 주는 최신 종가는 전 거래일 것이고, 그걸 그대로 실으면 주식 종가는
    당일·커브는 전일인 리포트가 나간다. 게다가 그 회차가 complete 로 커밋되면
    제대로 된 22:30 UTC 회차가 멱등 가드에 막힌다.
    """
    series = {'2Y': [('2026-09-01', 4.39), ('2026-09-02', 4.386)],
              '10Y': [('2026-09-01', 4.796), ('2026-09-02', 4.794)]}
    assert ny.build_curve(series, expected_date='2026-09-02') is not None
    assert ny.build_curve(series, expected_date='2026-09-03') is None


def test_previous_session_is_shared_by_every_tenor():
    """비교일은 전 만기 공통이어야 한다 — 합집합으로 잡으면 한 만기만 bp 가 빈다."""
    days = ['2026-08-31', '2026-09-01', '2026-09-02']
    series = {'2Y': [(d, 4.3 + i / 100) for i, d in enumerate(days)],
              '10Y': [(d, 4.7 + i / 100) for i, d in enumerate(days)]}
    curve = ny.build_curve(series)
    assert curve['2Y']['bp'] == pytest.approx(1.0)
    assert curve['10Y']['bp'] == pytest.approx(1.0)


def test_a_stretched_comparison_window_blanks_bp_instead_of_mislabelling_it():
    """한 만기가 어제를 빠뜨리면 「전일比」를 만들 수 없다 — 지어내지 말고 비운다.

    교집합에서 비교일을 고르면 전 만기가 같은 날을 보긴 하지만, 그 날이 실제
    전 거래일이 아닐 수 있다. 그때 2세션 변화를 「전일比」로 인쇄하면 조용히 틀린다
    (codex 검토 2026-09-04 — 이전 판의 테스트가 그 값을 인정하고 있었다).
    """
    series = {'2Y': [('2026-08-31', 4.35), ('2026-09-02', 4.386)],          # 09-01 결측
              '10Y': [('2026-08-31', 4.758), ('2026-09-01', 4.796), ('2026-09-02', 4.794)]}
    curve = ny.build_curve(series)
    assert curve is not None
    assert curve['2Y']['bp'] is None and curve['10Y']['bp'] is None
    assert curve['2Y']['level'] == 4.386          # 종가 자체는 멀쩡하므로 살린다
