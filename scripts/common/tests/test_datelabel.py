from scripts.common.datelabel import range_ko


def test_same_month():
    assert range_ko('2026-09-21', '2026-09-25') == '2026년 9월 21일~25일'


def test_month_boundary():
    assert range_ko('2026-09-28', '2026-10-02') == '2026년 9월 28일~10월 2일'


def test_year_boundary():
    assert range_ko('2026-12-28', '2027-01-01') == '2026년 12월 28일~2027년 1월 1일'
