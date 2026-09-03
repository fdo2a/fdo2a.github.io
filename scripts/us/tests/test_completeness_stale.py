"""마감 전에 뜬 회차는 complete 로 커밋되면 안 된다.

크론은 서머타임을 모르므로 두 슬롯이 연중 다 뜬다. 겨울의 이른 슬롯(21:30 UTC)은
16:30 EST 로 국채 현물 마감 17:05 EST **전**이라 네이버가 아직 전 거래일 종가만
갖고 있다. 그 판을 complete 로 커밋하면 마감 뒤 회차(22:30 UTC = 17:30 EST)가
멱등 가드에 막혀, 그날 커브가 영영 전일치로 남는다 (codex 검토 2026-09-04).
"""
import importlib

cmd = importlib.import_module('collect_market_data')


def _full_data():
    data = {g: {n: {'last': 1.0} for n, _ in pairs} for g, pairs in cmd.GROUPS}
    data['yields'] = {t: {'level': 4.0, 'week_ago': 4.0} for t in ('2Y', '5Y', '10Y', '30Y')}
    data['sector_performance'] = {n: {'1D': 0.1, '1W': 0.1, '1M': 0.1} for n, _ in cmd.SECTORS}
    return data


_INTRADAY = {'Nasdaq': {}, 'S&P 500': {}}


def test_otherwise_complete_dataset_reports_nothing_missing():
    assert cmd.completeness(_full_data(), _INTRADAY) == []


def test_a_pre_close_run_is_marked_incomplete():
    missing = cmd.completeness(_full_data(), _INTRADAY, naver_stale=True)
    assert 'yields/naver_close_not_posted' in missing
