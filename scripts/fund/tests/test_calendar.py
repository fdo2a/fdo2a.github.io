from fund import calendar as cal

HOL = {'valid_from': '2026-09-01', 'valid_through': '2026-12-31', 'dates': ['2026-09-07']}


def test_weekdays_minus_holidays():
    s = cal.us_sessions('2026-09-03', '2026-09-09', HOL)
    assert s == ['2026-09-03', '2026-09-04', '2026-09-08', '2026-09-09']


def test_outside_coverage_is_none():
    assert cal.us_sessions('2026-08-28', '2026-09-09', HOL) is None
    assert cal.us_sessions('2026-09-03', '2027-01-04', HOL) is None
    assert cal.us_sessions('2026-09-03', '2026-09-09', None) is None


def test_load_reads_us_block(tmp_path):
    p = tmp_path / 'h.json'
    p.write_text('{"us": {"valid_from": "2026-01-01", "valid_through": "2026-12-31", "dates": []}}')
    assert cal.load(str(p))['valid_from'] == '2026-01-01'
    assert cal.load(str(tmp_path / 'missing.json')) is None


def test_repo_holiday_file_covers_three_years():
    import os
    here = os.path.dirname(__file__)
    h = cal.load(os.path.join(here, '..', '..', '..', 'data', 'market_holidays.json'))
    assert h['valid_from'] <= '2023-10-06'
    assert '2025-01-09' in h['dates']
