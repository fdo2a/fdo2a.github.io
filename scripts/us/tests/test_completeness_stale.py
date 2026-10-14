"""마감 전에 뜬 회차는 complete 로 커밋되면 안 된다.

크론은 서머타임을 모르므로 두 슬롯이 연중 다 뜬다. 겨울의 이른 슬롯(21:30 UTC)은
16:30 EST 로 국채 현물 마감 17:05 EST **전**이라 네이버가 아직 전 거래일 종가만
갖고 있다. 그 판을 complete 로 커밋하면 마감 뒤 회차(22:30 UTC = 17:30 EST)가
멱등 가드에 막혀, 그날 커브가 영영 전일치로 남는다 (codex 검토 2026-09-04).
"""
import importlib

cmd = importlib.import_module('collect_market_data')
from scripts.us import close_cut  # noqa: E402

_CUT = {'last': 1.0, 'prev': 1.0, 'pct': 0.0, 'date': '2026-09-25',
        'prev_date': '2026-09-24', 'basis': close_cut.BASIS}


def _full_data(day='2026-09-25'):
    cut = dict(_CUT, date=day, prev_date='2026-09-01')
    data = {g: {n: ({**cut} if g in close_cut.CUT_GROUPS else {'last': 1.0}) for n, _ in pairs}
            for g, pairs in cmd.GROUPS}
    data['yields'] = {t: {'level': 4.0, 'week_ago': 4.0} for t in ('2Y', '5Y', '10Y', '30Y')}
    data['sector_performance'] = {n: {'1D': 0.1, '1W': 0.1, '1M': 0.1} for n, _ in cmd.SECTORS}
    return data


_INTRADAY = {'Nasdaq': {}, 'S&P 500': {}}


def test_otherwise_complete_dataset_reports_nothing_missing():
    assert cmd.completeness(_full_data(), _INTRADAY) == []
    assert cmd.completeness(_full_data(), _INTRADAY, report_date='2026-09-25') == []


def test_a_pre_close_run_is_marked_incomplete():
    missing = cmd.completeness(_full_data(), _INTRADAY, naver_stale=True)
    assert 'yields/naver_close_not_posted' in missing


def test_us_listed_rows_dated_before_the_session_are_incomplete():
    # 2026-09-25 판: 섹터가 전부 09-24 날짜인데 complete:true 였다(codex #14).
    data = _full_data()
    for n in data['sectors']:
        data['sectors'][n]['date'] = '2026-09-24'
    missing = cmd.completeness(data, _INTRADAY, report_date='2026-09-25')
    assert 'sectors/Technology/stale:2026-09-24' in missing


def test_foreign_listed_rows_may_carry_another_date():
    data = _full_data()
    data['memory']['SK hynix']['date'] = '2026-09-23'      # 한국 추석 휴장
    assert cmd.completeness(data, _INTRADAY, report_date='2026-09-25') == []


def test_fx_and_commodity_rows_must_be_the_sessions_four_pm_cut():
    # 2026-10-14: 24시간 시장도 이제 그날 16:00 ET 값이어야 한다. 일봉 폴백 행(basis 없음)이나
    # 다른 날짜 행이 complete 로 커밋되면 기준이 다시 섞인다(codex 설계 검토 A9).
    data = _full_data()
    data['fx']['USD/JPY']['date'] = '2026-09-26'
    data['commodities']['WTI'] = {'last': 94.71, 'chg': 0.97, 'pct': 1.03, 'date': '2026-09-25'}
    missing = cmd.completeness(data, _INTRADAY, report_date='2026-09-25')
    assert missing == ['fx/USD/JPY/stale:2026-09-26', 'commodities/WTI/basis']


def test_sector_performance_row_from_an_earlier_session_is_incomplete():
    # 2026-10-12 재수집: XLC·XLRE 일봉이 10-09 에 멈췄는데 1D/1W/1M 이 다 있어 통과했고,
    # 표의 「1일」은 10-09 하루 수익률이었다.
    data = _full_data('2026-10-12')
    for n in data['sector_performance']:
        data['sector_performance'][n]['date'] = '2026-10-12'
    data['sector_performance']['Communication Services']['date'] = '2026-10-09'
    missing = cmd.completeness(data, _INTRADAY, report_date='2026-10-12')
    assert missing == ['sector_performance/Communication Services/stale:2026-10-09']


def test_sector_performance_rows_without_a_date_are_not_judged():
    # 날짜를 남기기 전의 옛 데이터
    assert cmd.completeness(_full_data('2026-10-12'), _INTRADAY, report_date='2026-10-12') == []
