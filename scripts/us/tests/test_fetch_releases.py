"""fetch_releases contract (2026-11-06): this run's directory only, verified text only."""
import datetime
import json
import os

import fetch_releases as FR

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'releases')
TODAY = datetime.date(2026, 10, 30)


def _fx(name):
    with open(os.path.join(FX, name), encoding='utf-8') as fh:
        return fh.read()


class Resp:
    def __init__(self, text, url, ctype='text/html'):
        self.text, self.url = text, url
        self.content = text.encode()
        self.headers = {'content-type': ctype}


def pages(mapping):
    def get(url):
        if url in mapping:
            v = mapping[url]
            return (Resp(v, url), 'ok') if isinstance(v, str) else (v, 'ok')
        return None, 'HTTP 404'
    return get


def setup(tmp_path, releases, report_date='2026-10-29', stale=None):
    d = tmp_path / 'data'
    (d / 'releases').mkdir(parents=True)
    (d / 'market_data.json').write_text(json.dumps({'report_date': report_date}))
    (d / 'macro_metrics.json').write_text(json.dumps({'report_date': report_date, 'headline_releases': releases}))
    for name, body in (stale or {}).items():
        (d / 'releases' / name).write_text(body)
    return d


def index(d):
    return json.loads((d / 'releases' / 'index.json').read_text())


PCE = {'key': 'pce', 'label': 'PCE', 'agency': 'BEA', 'primary': 'PCE Price Index YoY',
       'url': 'https://www.bea.gov/data/personal-consumption-expenditures-price-index',
       'indicators': [{'name': 'PCE Price Index YoY', 'actual': 3.65, 'ref_period': '2026-09-01'}]}
PIO = 'https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026'
CPI = {'key': 'cpi', 'label': 'CPI', 'agency': 'BLS', 'primary': 'CPI MoM',
       'url': 'https://www.bls.gov/news.release/cpi.nr0.htm',
       'indicators': [{'name': 'CPI MoM', 'actual': 0.6, 'ref_period': '2026-09-01'}]}


def test_bea_release_is_resolved_through_the_feed_and_verified(tmp_path):
    d = setup(tmp_path, [PCE])
    get = pages({FR.rr.BEA_RSS: _fx('bea_rss.xml'), PIO: _fx('pce-full.txt')})
    FR.run(str(d), 'r1', get=get, today=TODAY)
    row = index(d)['releases'][0]
    assert row['ok'] and row['url'] == PIO and row['resolver'] == 'bea_rss'
    assert row['landing_url'] == PCE['url'] and row['checks']['primary_checked']
    assert (d / 'releases' / 'pce.txt').exists()
    assert index(d)['status'] == 'complete' and index(d)['run_id'] == 'r1'


def test_landing_navigation_is_never_written(tmp_path):
    # The old behaviour: evergreen page, 3 KB of menu, ok:true. Now the feed is down and
    # the landing page is not even tried.
    d = setup(tmp_path, [PCE])
    FR.run(str(d), 'r1', get=pages({PCE['url']: _fx('pce.txt')}), today=TODAY)
    row = index(d)['releases'][0]
    assert not row['ok'] and 'rss' in row['note']
    assert not (d / 'releases' / 'pce.txt').exists()


def test_a_failed_verification_leaves_no_text_anywhere(tmp_path):
    d = setup(tmp_path, [dict(CPI, indicators=[{'name': 'CPI MoM', 'actual': 0.6, 'ref_period': '2026-10-01'}])])
    FR.run(str(d), 'r1', get=pages({CPI['url']: _fx('cpi.txt')}), today=TODAY)
    assert 'period_mismatch' in index(d)['releases'][0]['note']
    assert list((d / 'releases').glob('*.txt')) == []
    assert not (d / 'releases' / 'rejected').exists()


def test_yesterdays_files_are_gone_even_on_a_quiet_day(tmp_path):
    d = setup(tmp_path, [], stale={'claims.txt': 'old', 'index.json': json.dumps(
        {'report_date': '2026-10-28', 'releases': [{'key': 'claims', 'ok': True, 'url': 'x'}]})})
    FR.run(str(d), 'r2', get=pages({}), today=TODAY)
    assert list((d / 'releases').glob('*.txt')) == []
    assert index(d) == {'report_date': '2026-10-29', 'run_id': 'r2', 'status': 'complete', 'releases': []}


def test_off_site_redirect_is_refused(tmp_path):
    d = setup(tmp_path, [CPI])
    get = pages({CPI['url']: Resp(_fx('cpi.txt'), 'https://evil.example/cpi')})
    FR.run(str(d), 'r1', get=get, today=TODAY)
    assert 'off-site' in index(d)['releases'][0]['note']


def test_same_site_redirect_records_the_final_url(tmp_path):
    d = setup(tmp_path, [CPI])
    get = pages({CPI['url']: Resp(_fx('cpi.txt'), 'https://www.bls.gov/news.release/archives/cpi.htm')})
    FR.run(str(d), 'r1', get=get, today=TODAY)
    assert index(d)['releases'][0]['url'] == 'https://www.bls.gov/news.release/archives/cpi.htm'


def test_a_crash_mid_run_is_wiped_by_sanitize(tmp_path):
    d = setup(tmp_path, [CPI])

    def boom(url):
        raise RuntimeError('killed')
    try:
        FR.run(str(d), 'r1', get=boom, today=TODAY)
    except RuntimeError:
        pass
    assert index(d)['status'] == 'running'
    assert FR.sanitize(str(d), 'r1') is False
    assert index(d)['status'] == 'aborted' and list((d / 'releases').glob('*.txt')) == []


def test_sanitize_drops_a_complete_index_from_another_run(tmp_path):
    # Same-day forced re-collection: the earlier run's complete index must not survive
    # a run whose own fetch step never got to write.
    d = setup(tmp_path, [CPI])
    FR.run(str(d), 'r1', get=pages({CPI['url']: _fx('cpi.txt')}), today=TODAY)
    assert FR.sanitize(str(d), 'r2') is False
    assert list((d / 'releases').glob('*.txt')) == []


def test_sanitize_keeps_this_runs_complete_directory(tmp_path):
    d = setup(tmp_path, [CPI])
    FR.run(str(d), 'r1', get=pages({CPI['url']: _fx('cpi.txt')}), today=TODAY)
    assert FR.sanitize(str(d), 'r1') is True
    assert (d / 'releases' / 'cpi.txt').exists()


def test_sanitize_without_any_index(tmp_path):
    d = setup(tmp_path, [], stale={'cpi.txt': 'old'})
    assert FR.sanitize(str(d), 'r1') is False
    assert index(d)['status'] == 'aborted'


def test_yesterdays_metrics_name_no_release_today(tmp_path):
    # codex 구현 검토 #1: a failed step leaves yesterday's macro_metrics behind.
    d = setup(tmp_path, [CPI])
    (d / 'macro_metrics.json').write_text(json.dumps({'report_date': '2026-10-28', 'headline_releases': [CPI]}))
    FR.run(str(d), 'r1', get=pages({CPI['url']: _fx('cpi.txt')}), today=TODAY)
    assert index(d)['releases'] == [] and index(d)['metrics'] == 'stale'
    assert list((d / 'releases').glob('*.txt')) == []
