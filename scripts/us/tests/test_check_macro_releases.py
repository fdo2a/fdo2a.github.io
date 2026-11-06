"""check_macro.py: a missing releases index means "no release text" now, the old
strict reading only when re-checking a past post (--legacy-releases)."""
import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(__file__), '..', '..', 'check_macro.py')


def run(tmp_path, *extra):
    from us.tests.test_macro_gate import (DATED, build_html, eval_file, macro_file,
                                          next_file)
    d = tmp_path / 'data'
    d.mkdir()
    ev = eval_file()
    ev['headline_releases'] = [DATED]
    (d / 'macro.json').write_text(json.dumps(macro_file()))
    (d / 'macro_eval.json').write_text(json.dumps(ev))
    (d / 'macro_next.json').write_text(json.dumps(next_file()))
    (d / 'market_data.json').write_text(json.dumps({'report_date': ev.get('report_date')}))
    block = ('<div data-release="cpi"><p>7월 CPI는 3.54%로 전월 3.73%에서 내려왔다. '
             '에너지는 -1.5%였다. 출처 BLS.</p></div>')
    post = tmp_path / 'p.html'
    post.write_text(build_html(anatomy=block))
    return subprocess.run([sys.executable, SCRIPT, '--html', str(post), '--datadir', str(d), *extra],
                          capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), '..', '..'))


def test_missing_index_now_means_no_release_text(tmp_path):
    r = run(tmp_path)
    assert '구성 항목' not in r.stdout, r.stdout


def test_missing_index_in_legacy_mode_keeps_the_strict_rule(tmp_path):
    r = run(tmp_path, '--legacy-releases')
    assert r.returncode == 1 and '구성 항목' in r.stdout


def test_an_old_schema_index_now_means_no_release_text(tmp_path):
    d = tmp_path / 'x'
    d.mkdir()
    r0 = run(d)          # builds data/ under d
    (d / 'data' / 'releases').mkdir()
    (d / 'data' / 'releases' / 'index.json').write_text(json.dumps({'releases': [{'key': 'cpi', 'ok': True}]}))
    post = d / 'p.html'
    r = subprocess.run([sys.executable, SCRIPT, '--html', str(post), '--datadir', str(d / 'data')],
                       capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), '..', '..'))
    assert '구성 항목' not in r.stdout, r.stdout
    r = subprocess.run([sys.executable, SCRIPT, '--html', str(post), '--datadir', str(d / 'data'), '--legacy-releases'],
                       capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), '..', '..'))
    assert '구성 항목' in r.stdout
