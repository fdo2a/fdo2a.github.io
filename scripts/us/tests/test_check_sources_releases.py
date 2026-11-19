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
    post = tmp_path / 'p.html'
    post.write_text(POST)
    return subprocess.run([sys.executable, SCRIPT, '--html', str(post), '--datadir', str(d), *extra],
                          capture_output=True, text=True)


ROW = {'key': 'cpi', 'ok': True, 'url': URL}


def test_a_complete_index_authorises_its_verified_url(tmp_path):
    r = run(tmp_path, {'report_date': '2026-11-05', 'run_id': 'r', 'status': 'complete', 'releases': [ROW]})
    assert r.returncode == 0, r.stdout + r.stderr


def test_an_unfinished_index_authorises_nothing(tmp_path):
    for status in ('running', 'aborted'):
        r = run(tmp_path / status, {'report_date': '2026-11-05', 'status': status, 'releases': [ROW]})
        assert r.returncode == 1


def test_an_old_schema_index_needs_the_legacy_flag(tmp_path):
    old = {'report_date': '2026-11-05', 'releases': [ROW]}
    assert run(tmp_path / 'a', old).returncode == 1
    assert run(tmp_path / 'b', old, '--legacy-releases').returncode == 0


def test_the_landing_url_is_not_authorised(tmp_path):
    row = {'key': 'cpi', 'ok': True, 'url': 'https://www.bls.gov/x.pdf', 'landing_url': URL}
    r = run(tmp_path, {'report_date': '2026-11-05', 'status': 'complete', 'releases': [row]})
    assert r.returncode == 1
