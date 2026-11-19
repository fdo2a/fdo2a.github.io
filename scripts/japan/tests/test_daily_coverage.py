"""일본 일간 v2 — 일정표 확인 창(coverage)·미확인 계열 (설계 §7·§11-7)."""
from japan import daily_calendar as C

ALL = [cid for cid, _ in C.REQUIRED]


def cov(cid, lo='2026-11-01', hi='2027-01-31', cadence='irregular', **over):
    return dict({'id': cid, 'name_ko': C.REQUIRED_NAMES[cid], 'cadence': cadence, 'source': 'https://x',
                 'from': lo, 'through': hi, 'checked_at': '2026-11-13'}, **over)


def full(events=(), **over):
    """필수 16개 전부 덮은 일정표(monthly 없음)."""
    c = [over[cid] if cid in over else cov(cid) for cid in ALL]
    return {'coverage': [x for x in c if x is not False], 'events': list(events)}


def test_all_covered_nothing_missing():
    assert C.coverage(full(), '2026-11-18') == {'today_missing': [], 'upcoming_missing': []}


def test_missing_series_named_in_order():
    cal = full(trade=False, gdp=False)
    got = C.coverage(cal, '2026-11-18')
    assert got['today_missing'] == ['GDP', '무역통계'] and got['upcoming_missing'] == ['GDP', '무역통계']


def test_window_not_covering_today_is_missing():
    """다음 달 행만 있고 창이 오늘을 안 덮음 → 미확인."""
    cal = full([{'date': '2026-12-08', 'kind': 'release', 'cov': 'wages'}],
               wages=cov('wages', '2026-12-01', '2027-01-31'))
    assert '매월근로통계' in C.coverage(cal, '2026-11-18')['today_missing']


def test_upcoming_needs_whole_interval():
    """창이 대상일+14일 하루만 덮고 중간이 빔 → upcoming_missing(R10)."""
    cal = full(gdp=cov('gdp', '2026-12-02', '2027-01-31'))
    got = C.coverage(cal, '2026-11-18')
    assert 'GDP' in got['upcoming_missing'] and 'GDP' in got['today_missing']
    cal = full(gdp=cov('gdp', '2026-11-01', '2026-12-01'))
    got = C.coverage(cal, '2026-11-18')
    assert got['today_missing'] == [] and got['upcoming_missing'] == ['GDP']


def test_row_outside_window_bad_checked_at_and_inverted_window():
    out = full([{'date': '2027-03-01', 'kind': 'release', 'cov': 'cgpi'}])
    assert '기업물가' in C.coverage(out, '2026-11-18')['today_missing']
    assert 'GDP' in C.coverage(full(gdp=cov('gdp', checked_at='11월 13일')), '2026-11-18')['today_missing']
    assert 'GDP' in C.coverage(full(gdp=cov('gdp', '2027-01-31', '2026-11-01')), '2026-11-18')['today_missing']
    assert 'GDP' in C.coverage(full(gdp=cov('gdp', source='')), '2026-11-18')['today_missing']


def test_unknown_cov_does_not_cover_anything():
    cal = full([{'date': '2026-11-20', 'kind': 'release', 'cov': 'no_such'}], trade=False)
    assert C.coverage(cal, '2026-11-18')['today_missing'] == ['무역통계']


def test_monthly_needs_release_row_each_full_month():
    rows = [{'date': '2026-11-20', 'kind': 'release', 'cov': 'cpi_national'},
            {'date': '2026-12-18', 'kind': 'release', 'cov': 'cpi_national'}]
    ok = full(rows, cpi_national=cov('cpi_national', '2026-11-01', '2026-12-31', cadence='monthly'))
    assert C.coverage(ok, '2026-11-18')['today_missing'] == []
    meeting_only = [{'date': '2026-11-20', 'kind': 'release', 'cov': 'boj_policy'},
                    {'date': '2026-12-17', 'kind': 'meeting', 'cov': 'boj_policy'}]
    cal = full(meeting_only, boj_policy=cov('boj_policy', '2026-11-01', '2026-12-31', cadence='monthly'))
    assert C.coverage(cal, '2026-11-18')['today_missing'] == ['BOJ 금융정책']
    # 21일 알림도 같은 판정으로 그 계열 이름을 낸다(R14)
    assert C.alert_missing(cal, '2026-11-18') == ['BOJ 금융정책']


def test_duplicate_window_is_unconfirmed():
    cal = full()
    cal['coverage'].append(cov('gdp'))
    assert C.coverage(cal, '2026-11-18')['today_missing'] == ['GDP']


def test_file_without_coverage_everything_missing():
    assert C.coverage({'events': []}, '2026-11-18')['today_missing'] == [n for _, n in C.REQUIRED]


def test_repo_calendar_validates():
    """레포 일정표: 창이 있는 계열은 전부 검증을 통과하고, 창이 없는 계열만 미확인이다."""
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', '..', '..', C.PATH), encoding='utf-8') as fh:
        cal = json.load(fh)
    declared = {c['id'] for c in cal.get('coverage') or []}
    w = C.windows(cal)
    assert {cid for cid, v in w.items() if v} == declared
    for e in cal['events']:
        assert e.get('cov') in declared, e['name_ko']
