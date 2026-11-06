import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import build_liquidity as B  # noqa: E402
from us import liquidity as L  # noqa: E402

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'liquidity')


def fx(name):
    with open(os.path.join(FX, name), encoding='utf-8') as fh:
        return fh.read()


PAGES = {
    L.H41_BASE + 'current/': 'h41_20261105.html',
    L.H41_BASE + '20261105/': 'h41_20261105.html',
    L.H41_BASE + '20261029/': 'h41_20261029.html',
    L.QRA_LANDING: 'qra_landing_2026q4.html',
    L.H41_DATES: 'h41_release_dates.json',
    'https://home.treasury.gov/news/press-releases/sb0675': 'qra_borrowing_2026q4.html',
    'https://home.treasury.gov/news/press-releases/sb0678': 'qra_refunding_2026q4.html',
    'https://home.treasury.gov/news/press-releases/sb0679': 'qra_tbac_2026q4.html',
}


def fake_get(missing=()):
    calls = []

    def get(url):
        calls.append(url)
        if url in PAGES and url not in missing:
            return 200, fx(PAGES[url])
        return 404, ''
    get.calls = calls
    return get


def et(y, m, d, hh=17, mm=30):
    return dt.datetime(y, m, d, hh, mm, tzinfo=L.ET)


def test_fetch_h41_recovers_missed_week_from_archive():
    get = fake_get()
    hist, pending, checked = B.fetch_h41([], et(2026, 10, 30), et(2026, 11, 6), get, [])
    assert [r['release_date'] for r in hist] == ['2026-10-29', '2026-11-05']
    assert pending == [] and checked


def test_fetch_h41_missing_week_is_pending_then_found_later():
    get = fake_get(missing={L.H41_BASE + '20261029/'})
    hist, pending, _ = B.fetch_h41([], et(2026, 10, 30), et(2026, 11, 6), get, [])
    assert pending == ['2026-10-29'] and [r['release_date'] for r in hist] == ['2026-11-05']
    hist2, pending2, _ = B.fetch_h41(hist, et(2026, 10, 30), et(2026, 11, 9), fake_get(), [])
    assert pending2 == [] and len(hist2) == 2


def test_fetch_h41_does_not_probe_future():
    get = fake_get()
    B.fetch_h41([], et(2026, 11, 4), et(2026, 11, 5, 12, 0), get, [])
    assert not any(u.endswith('20261105/') for u in get.calls)


def test_fetch_qra_writes_verified_text_only(tmp_path):
    rounds, rnd, nexts = B.fetch_qra({}, et(2026, 11, 6), fake_get(), str(tmp_path), [])
    assert nexts == {'borrowing': '2027-02-01', 'refunding': '2027-02-03'}
    assert rnd == '2026Q4'
    docs = rounds['2026Q4']['docs']
    assert all(docs[k]['ok'] for k in ('borrowing', 'refunding', 'tbac'))
    assert sorted(os.listdir(tmp_path)) == ['2026Q4_borrowing.txt', '2026Q4_refunding.txt', '2026Q4_tbac.txt']
    assert rounds['2026Q4']['guidance'].endswith('for the next several quarters.')


def test_fetch_qra_before_statement_time_takes_only_estimates(tmp_path):
    rounds, _, _ = B.fetch_qra({}, et(2026, 11, 3), fake_get(), str(tmp_path), [])
    assert set(rounds['2026Q4']['docs']) == {'borrowing'}


def test_fetch_qra_failed_doc_writes_nothing(tmp_path):
    get = fake_get(missing={'https://home.treasury.gov/news/press-releases/sb0678'})
    rounds, _, _ = B.fetch_qra({}, et(2026, 11, 6), get, str(tmp_path), [])
    d = rounds['2026Q4']['docs']['refunding']
    assert (d['ok'], d['note']) == (False, 'http_404')
    assert '2026Q4_refunding.txt' not in os.listdir(tmp_path)


# ── 실행 전체 ──────────────────────────────────────────────────────────

def setup_dirs(tmp_path, report_date='2026-11-05', effective='2026-11-02', posts=None):
    repo = tmp_path / 'repo'
    (repo / 'config').mkdir(parents=True)
    (repo / 'data').mkdir()
    (repo / 'posts').mkdir()
    (repo / 'config' / 'liquidity.json').write_text(json.dumps({
        'effective_session': effective,
        'qra_bootstrap': [{'round': '2026Q3', 'round_name': '2026 - 3rd Quarter',
                           'guidance': 'Treasury anticipates maintaining nominal coupon and FRN auction sizes '
                                       'for at least the next several quarters.', 'url': 'x'}]}))
    (repo / 'data' / 'market_holidays.json').write_text(json.dumps({'us': {'dates': []}}))
    for name, body in (posts or {}).items():
        (repo / 'posts' / name).write_text(body)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'market_data.json').write_text(json.dumps({'report_date': report_date}))
    return repo, data


ANNOUNCED = [{'securityTerm': '3-Year', 'datedDate': '2026-11-15T00:00:00', 'type': 'Note', 'offeringAmount': '58000000000'},
             {'securityTerm': '10-Year', 'datedDate': '2026-11-15T00:00:00', 'type': 'Note', 'offeringAmount': '42000000000'}]


def run(monkeypatch, repo, data, *extra, get=None, announced=None):
    monkeypatch.setattr(B, 'http_get', get or fake_get())
    monkeypatch.setattr(B, 'announced_rows', announced or (lambda: ANNOUNCED))
    monkeypatch.setattr(sys, 'argv', ['build_liquidity.py', '--datadir', str(data), '--repo', str(repo), *extra])
    B.main()
    return json.loads((data / 'liquidity' / 'liquidity.json').read_text())


def test_main_qra_and_h41_same_session(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path, posts={'2026-11-02.html': '<p data-qra-doc="2026Q4:borrowing"></p>'})
    book = run(monkeypatch, repo, data, '--date', '2026-11-05')
    assert book['status'] == 'complete' and book['today'] is True
    assert [c['release_date'] for c in book['h41']['candidates']] == ['2026-11-05']
    # 월요일 차입 추정은 11/2 글에 실렸다 → 이번엔 성명·TBAC 만, 수요일 발표라 11/5 세션엔 「지난 발표분」
    assert set(book['qra']['candidates']) == {'refunding', 'tbac'}
    assert book['qra']['guidance']['change'] == 'changed'
    assert book['qra']['guidance']['words'] == ['at', 'least']
    html = (data / 'liquidity' / 'table.html').read_text()
    assert 'data-h41-release="2026-11-05"' in html and 'data-qra-table="2026Q4"' in html
    st = json.loads((data / 'liquidity' / 'state.json').read_text())
    assert st['generation'] == 1 and '2026Q3' in st['qra_rounds']


def test_main_same_session_rerun_is_identical(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    a = run(monkeypatch, repo, data, '--date', '2026-11-05')
    b = run(monkeypatch, repo, data, '--date', '2026-11-05')
    strip = lambda x: {k: v for k, v in x.items() if k not in ('run_id', 'generated', 'checked')}  # noqa: E731
    assert strip(a) == strip(b)                    # 같은 세션 재수집이 발표를 지우지 않는다(1차 #1)


def test_main_disabled_without_effective(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path, effective=None)
    book = run(monkeypatch, repo, data, '--date', '2026-11-05')
    assert book['disabled'] is True and book['today'] is False
    assert not (data / 'liquidity' / 'table.html').exists()


def test_recompute_after_ledger_changes(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    book = run(monkeypatch, repo, data, '--date', '2026-11-05')
    assert [c['release_date'] for c in book['h41']['candidates']] == ['2026-11-05']
    (repo / 'posts' / '2026-11-04.html').write_text('<table data-h41-release="2026-11-05"></table>'
                                                    '<p data-qra-doc="2026Q4:refunding"></p>'
                                                    '<p data-qra-doc="2026Q4:borrowing"></p>')
    new = run(monkeypatch, repo, data, '--date', '2026-11-05', '--recompute', get=fake_get(missing=set(PAGES)))
    assert new['recomputed'] is True and new['h41']['candidates'] == []
    assert new['qra']['candidates'] == {}       # TBAC 단독은 싣지 않는다
    assert new['today'] is False and not (data / 'liquidity' / 'table.html').exists()


def test_sanitize_wipes_unfinished(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    run(monkeypatch, repo, data, '--date', '2026-11-05')
    p = data / 'liquidity' / 'liquidity.json'
    b = json.loads(p.read_text())
    b['status'] = 'running'
    p.write_text(json.dumps(b))
    run(monkeypatch, repo, data, '--sanitize')
    assert json.loads(p.read_text())['status'] == 'aborted'
    assert not (data / 'liquidity' / 'table.html').exists()
    assert not list((data / 'liquidity' / 'qra').glob('*.txt'))
    assert (data / 'liquidity' / 'state.json').exists()       # state 는 남는다


def test_sanitize_keeps_complete_of_this_run(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    monkeypatch.setenv('LIQ_RUN_ID', 'r1')
    run(monkeypatch, repo, data, '--date', '2026-11-05')
    run(monkeypatch, repo, data, '--sanitize')
    assert json.loads((data / 'liquidity' / 'liquidity.json').read_text())['status'] == 'complete'
    monkeypatch.setenv('LIQ_RUN_ID', 'r2')
    run(monkeypatch, repo, data, '--sanitize')
    assert json.loads((data / 'liquidity' / 'liquidity.json').read_text())['status'] == 'aborted'


def test_backfill_from_archive_dir(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    arc = tmp_path / 'arc'
    arc.mkdir()
    for f in ('h41_20261029.html', 'h41_20261105.html'):
        (arc / f).write_text(fx(f))
    (arc / 'junk.html').write_text('<html>Page not found</html>')
    monkeypatch.setattr(sys, 'argv', ['build_liquidity.py', '--datadir', str(data), '--repo', str(repo),
                                      '--backfill', str(arc)])
    B.main()
    st = json.loads((data / 'liquidity' / 'state.json').read_text())
    assert [r['release_date'] for r in st['h41_history']] == ['2026-10-29', '2026-11-05']


def test_workflow_runs_liquidity_on_both_paths():
    wf = open(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.github', 'workflows',
                           'collect-market-data.yml'), encoding='utf-8').read()
    build = wf.split('- name: Fed H.4.1 and Treasury refunding (liquidity)')[1].split('- name:')[0]
    assert 'continue-on-error: true' in build and '\n        if:' not in build   # skipped 여도 돈다
    san = wf.split('- name: Sanitize liquidity')[1].split('- name:')[0]
    assert "if: always()" in san and '--sanitize' in san
    alt = wf.split('- name: Commit liquidity (market data already complete)')[1].split('- name:')[0]
    assert "steps.collect.outputs.skipped == 'true'" in alt and 'git add -A data/liquidity' in alt
    main_commit = wf.split('- name: Commit data')[1].split('- name:')[0]
    assert 'git add -A data/liquidity' in main_commit
    assert wf.index('Sanitize liquidity') < wf.index('- name: Commit data')



# ── codex 구현 검토 1차 재현 ─────────────────────────────────────────────

def test_impl1_landing_failure_publishes_no_old_round(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    run(monkeypatch, repo, data, '--date', '2026-11-05')
    st_path = data / 'liquidity' / 'state.json'
    st = json.loads(st_path.read_text())
    st['schedule']['qra_next'] = {'borrowing': '2026-11-02', 'refunding': '2026-11-04'}   # 발표일이 된 날로
    st_path.write_text(json.dumps(st))
    book = run(monkeypatch, repo, data, '--date', '2026-11-05', get=fake_get(missing={L.QRA_LANDING}))
    assert book['qra']['candidates'] == {} and book['qra']['confirmed'] is None
    assert [c['release_date'] for c in book['h41']['candidates']] == ['2026-11-05']


def test_impl1_ta_ws_size_mismatch_fails_refunding(tmp_path):
    bad = [dict(ANNOUNCED[0], offeringAmount='59000000000')]
    rounds, _, _ = B.fetch_qra({}, et(2026, 11, 6), fake_get(), str(tmp_path), [], announced=lambda: bad)
    assert rounds['2026Q4']['docs']['refunding']['ok'] is False
    assert rounds['2026Q4']['docs']['refunding']['note'] == 'ta_ws_mismatch'
    rounds, _, _ = B.fetch_qra({}, et(2026, 11, 6), fake_get(), str(tmp_path), [], announced=lambda: ANNOUNCED)
    assert rounds['2026Q4']['docs']['refunding']['ta_ws'] == {'3': 'match', '10': 'match', '30': 'unmatched'}


def test_impl1_ledger_reads_committed_head_only(tmp_path):
    import subprocess
    repo = tmp_path / 'r'
    (repo / 'posts').mkdir(parents=True)
    git = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)  # noqa: E731
    git('init', '-q')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    (repo / 'posts' / '2026-11-06.html').write_text('<table data-h41-release="2026-11-05"></table>')
    git('add', '-A')
    git('commit', '-qm', 'x')
    (repo / 'posts' / '2026-11-09.html').write_text('<p data-qra-doc="2026Q4:borrowing"></p>')   # 미추적
    (repo / 'posts' / '2026-11-06.html').write_text('<p>지움</p>')                                 # 작업 트리만
    h, q = L.ledger_from_posts(str(repo), '2026-11-10')
    assert h == {'2026-11-05'} and q == set()



# ── 발표일에만 확인한다(사용자 2026-11-07) ────────────────────────────────

def test_no_requests_on_days_without_scheduled_release(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    run(monkeypatch, repo, data, '--date', '2026-11-05')               # 첫 실행: 일정 파악
    st = json.loads((data / 'liquidity' / 'state.json').read_text())
    assert st['schedule']['qra_next'] == {'borrowing': '2027-02-01', 'refunding': '2027-02-03'}
    assert st['schedule']['h41_next'] == '2026-11-12'
    (data / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-09'}))
    get = fake_get()
    book = run(monkeypatch, repo, data, '--date', '2026-11-09', get=get)
    assert get.calls == []                                             # 월요일 — 아무 페이지도 열지 않는다
    assert book['checked'] == {'h41': False, 'qra': False}
    # 확인하지 않는 날에도 최신 회차 원문은 state 에서 다시 쓴다
    assert sorted(os.listdir(data / 'liquidity' / 'qra')) == ['2026Q4_borrowing.txt', '2026Q4_refunding.txt',
                                                              '2026Q4_tbac.txt']


def test_scheduled_day_checks_and_late_round_retried(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    run(monkeypatch, repo, data, '--date', '2026-11-05')
    (data / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-12'}))
    get = fake_get()
    book = run(monkeypatch, repo, data, '--date', '2026-11-12', get=get)
    assert get.calls[0] == L.H41_BASE + 'current/'                     # 목요일 — H.4.1 만 확인
    assert not any('treasury.gov' in u for u in get.calls)
    assert book['checked'] == {'h41': True, 'qra': False}
    assert book['h41']['pending'] == ['2026-11-12']                    # 픽스처에 11/12 판이 없다
    get2 = fake_get()
    run(monkeypatch, repo, data, '--date', '2026-11-12', get=get2)
    assert get2.calls                                                  # 못 받은 주는 다음 실행이 다시 찾는다


def test_qra_due_on_or_after_next_date():
    times = {'borrowing': et(2026, 11, 2, 15, 0).isoformat(), 'refunding': et(2026, 11, 4, 8, 30).isoformat()}
    rounds = {'2026Q4': {'times': times, 'docs': {'borrowing': {'ok': True}, 'refunding': {'ok': True}}}}
    sch = {'qra_next': {'borrowing': '2027-02-01', 'refunding': '2027-02-03'}}
    assert B.qra_due(rounds, sch, et(2027, 1, 29)) is False
    assert B.qra_due(rounds, sch, et(2027, 2, 1)) is True
    assert B.qra_due({}, sch, et(2027, 1, 29)) is True                  # 회차를 모르면 확인
    failed = {'2026Q4': {'times': times, 'docs': {'borrowing': {'ok': True}, 'refunding': {'ok': False}}}}
    assert B.qra_due(failed, sch, et(2026, 12, 30)) is True             # 검증 실패 문서는 기한 없이 다시


def test_impl_sched1_monday_check_then_wednesday_statement(tmp_path, monkeypatch):
    repo, data = setup_dirs(tmp_path)
    (data / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-03'}))
    book = run(monkeypatch, repo, data, '--date', '2026-11-03')
    assert set(book['qra']['candidates']) == {'borrowing'}
    (data / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-04'}))
    get = fake_get()
    book = run(monkeypatch, repo, data, '--date', '2026-11-04', get=get)
    assert any('sb0678' in u for u in get.calls)                       # 수요일 성명을 다시 확인한다
    assert 'refunding' in book['qra']['candidates']


def test_impl_sched3_long_delay_still_found():
    probes = L.h41_probe_dates(dt.date(2026, 11, 12))
    assert [d.isoformat() for d in probes] == ['2026-11-12', '2026-11-13', '2026-11-16', '2026-11-17', '2026-11-18']
    # 11/12 주 회차가 다음 주 예정일(11/19)을 넘겨 11/20 에 나오고 11/19 주는 11/23 에 나왔다 — 발표 순서로 주에 붙는다
    hist = [{'release_date': '2026-11-05'}, {'release_date': '2026-11-20'}, {'release_date': '2026-11-23'}]
    assert L.h41_due(hist, et(2026, 11, 6), et(2026, 11, 24)) == []


def test_impl_sched4_late_release_after_effective_counts():
    eff = et(2026, 11, 12, 17, 0)           # 그 주 예정 발표(16:30) 뒤에 적용 — 실제 발표가 늦었다면 실어야 한다
    due = L.h41_due([{'release_date': '2026-11-05'}], eff, et(2026, 11, 16))
    assert [th for th, _ in due] == [dt.date(2026, 11, 12)]



def test_impl_sched2_missing_week_found_through_release_dates_list():
    # 10/29 주를 못 받았다 — 발표일 목록에 20261029 가 있으니 그 아카이브만 연다(짐작한 날짜 창을 훑지 않는다)
    hist = [L.parse_h41(fx('h41_20261105.html'))]
    get = fake_get()
    hist, pending, _ = B.fetch_h41(hist, et(2026, 10, 30), et(2026, 11, 6), get, [])
    assert [r['release_date'] for r in hist] == ['2026-10-29', '2026-11-05'] and pending == []
    assert L.H41_DATES in get.calls and get.calls.count(L.H41_BASE + '20261029/') == 1
    assert not any(u.endswith(('20261030/', '20261102/')) for u in get.calls)


def test_impl_sched2_release_dates_unreadable_falls_back_to_window():
    hist = [L.parse_h41(fx('h41_20261105.html'))]
    get = fake_get(missing={L.H41_DATES})
    hist, pending, _ = B.fetch_h41(hist, et(2026, 10, 30), et(2026, 11, 6), get, [])
    assert [r['release_date'] for r in hist] == ['2026-10-29', '2026-11-05']


def test_impl_sched2_partial_qra_schedule_checks():
    rounds = {'2026Q4': {'times': {}, 'docs': {}}}
    assert B.qra_due(rounds, {'qra_next': {'borrowing': None, 'refunding': '2027-02-03'}}, et(2026, 12, 1)) is True
