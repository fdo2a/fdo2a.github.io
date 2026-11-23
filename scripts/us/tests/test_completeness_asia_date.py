"""한국·일본 상장 행이 그 거래소의 기대 세션이 아니면 완결이 아니다(2026-11-23, 수집 16:50 ET)."""
import collect_market_data as C

HOL = {'kr': ['2026-11-20'], 'jp': []}


def test_expected_session_skips_weekend_and_holiday():
    assert C.asia_expected('2026-11-20', set()) == '2026-11-20'
    assert C.asia_expected('2026-11-20', {'2026-11-20'}) == '2026-11-19'
    assert C.asia_expected('2026-11-23', set()) == '2026-11-23'


def _data(samsung_date, murata_date, yageo_date='2026-11-18'):
    return {'memory': {'Samsung Elec': {'last': 1, 'date': samsung_date}},
            'mlcc': {'Murata': {'last': 1, 'date': murata_date},
                     'Yageo': {'last': 1, 'date': yageo_date}}}


def _asia_missing(data, rd, hol):
    # GROUPS 의 다른 행은 없으니 그 결측은 걸러 낸다 — 날짜 검사가 낸 줄만 본다.
    full = {g: {} for g, _ in C.GROUPS}
    full.update(data)
    full['yields'] = {}
    return [m for m in C.completeness(full, {}, report_date=rd, asia_holidays=hol) if '/stale:' in m]


def test_previous_session_rows_are_flagged():
    assert _asia_missing(_data('2026-11-18', '2026-11-18'), '2026-11-19', HOL) == [
        'memory/Samsung Elec/stale:2026-11-18', 'mlcc/Murata/stale:2026-11-18']


def test_kr_holiday_row_from_the_day_before_is_fine_and_taiwan_is_not_checked():
    assert _asia_missing(_data('2026-11-19', '2026-11-20'), '2026-11-20', HOL) == []


def test_no_holiday_file_skips_the_check():
    assert _asia_missing(_data('2026-11-18', '2026-11-18'), '2026-11-19', None) == []
