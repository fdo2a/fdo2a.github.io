"""check_sources.py and the 2026-11-06 releases contract."""
import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(__file__), '..', '..', 'check_sources.py')
URL = 'https://www.bls.gov/news.release/cpi.nr0.htm'
POST = (f'<html><body><section><div data-release="cpi"><p>BLS <a href="{URL}">원문</a></p>'
        '</div></section></body></html>')


def run(tmp_path, index, *extra):
    d = tmp_path / 'data'
    (d / 'releases').mkdir(parents=True)
    (d / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-05'}))
    (d / 'releases' / 'index.json').write_text(json.dumps(index))
    (d / 'fed').mkdir()
    (d / 'fed' / 'events.json').write_text(json.dumps({'report_date': '2026-11-05', 'events': []}))
    post = tmp_path / 'p.html'
    post.write_text(POST)
    return subprocess.run([sys.executable, SCRIPT, '--html', str(post), '--datadir', str(d), *extra],
                          capture_output=True, text=True)


ROW = {'key': 'cpi', 'ok': True, 'url': URL}


def test_a_complete_index_authorises_its_verified_url(tmp_path):
    r = run(tmp_path, {'report_date': '2026-11-05', 'run_id': 'r', 'status': 'complete', 'releases': [ROW]})
    assert r.returncode == 0, r.stdout + r.stderr


def test_an_unfinished_index_is_incomplete(tmp_path):
    # 2026-11-17: 끝나지 않은 index 는 「아무것도 인가하지 않음」이 아니라 미완료(재수집)
    for status in ('running', 'aborted'):
        r = run(tmp_path / status, {'report_date': '2026-11-05', 'status': status, 'releases': [ROW]})
        assert r.returncode == 2 and '미완료' in r.stderr
        r = run(tmp_path / (status + '-legacy'), {'report_date': '2026-11-05', 'status': status, 'releases': [ROW]},
                '--legacy-releases')
        assert r.returncode == 1                     # 지난 글 재검사는 옛 판정(인가하지 않음)


def test_missing_books_are_incomplete_when_publishing(tmp_path):
    for gone in ('releases/index.json', 'fed/events.json'):
        d = tmp_path / gone.split('/')[0]
        r = run(d, {'report_date': '2026-11-05', 'status': 'complete', 'releases': [ROW]})
        os.unlink(d / 'data' / gone)
        r = subprocess.run([sys.executable, SCRIPT, '--html', str(d / 'p.html'), '--datadir', str(d / 'data')],
                           capture_output=True, text=True)
        assert r.returncode == 2, gone
    r = run(tmp_path / 'stale', {'report_date': '2026-11-04', 'status': 'complete', 'releases': [ROW]})
    assert r.returncode == 2


def test_an_old_schema_index_needs_the_legacy_flag(tmp_path):
    old = {'report_date': '2026-11-05', 'releases': [ROW]}
    assert run(tmp_path / 'a', old).returncode == 2            # 지금 발행하는 글에는 미완료
    assert run(tmp_path / 'b', old, '--legacy-releases').returncode == 0


def test_the_landing_url_is_not_authorised(tmp_path):
    row = {'key': 'cpi', 'ok': True, 'url': 'https://www.bls.gov/x.pdf', 'landing_url': URL}
    r = run(tmp_path, {'report_date': '2026-11-05', 'status': 'complete', 'releases': [row]})
    assert r.returncode == 1
