import json
import subprocess

import pytest

from prepub import bundle


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'repo'
    (r / 'data').mkdir(parents=True)
    (r / 'data/market_data.json').write_text('{"spx": 1}')
    git(tmp_path, 'init', '-q', str(r))
    git(r, 'add', '-A')
    git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'x')
    return r


def draft(tmp_path, text='<html><body><p>코스피가 올랐다.</p></body></html>'):
    p = tmp_path / 'draft.html'
    p.write_text(text, encoding='utf-8')
    return p


def test_the_bundle_names_the_commit_its_evidence_comes_from(repo, tmp_path):
    man = bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')
    assert man['data_commit'] == git(repo, 'rev-parse', 'HEAD')
    assert man['post_path'] == 'posts/2026-11-07.html'
    assert set(man['files']) == {'post.html', 'prompt.txt'}
    assert json.loads((tmp_path / 'b/manifest.json').read_text())['request_id'] == man['request_id']


def test_the_prompt_is_the_post_publish_prompt_plus_style_findings(repo, tmp_path):
    bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')
    text = (tmp_path / 'b/prompt.txt').read_text(encoding='utf-8')
    assert 'posts/2026-11-07.html' in text and '`data/`' in text
    assert '=== 문체 지적 ===' in text


def test_edited_evidence_is_refused(repo, tmp_path):
    (repo / 'data/market_data.json').write_text('{"spx": 2}')
    with pytest.raises(bundle.BundleError):
        bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')


def test_an_unknown_market_or_date_is_refused(repo, tmp_path):
    for sec, d in (('jp', '2026-11-07'), ('us', '11/07')):
        with pytest.raises(bundle.BundleError):
            bundle.build(str(repo), sec, d, draft(tmp_path), tmp_path / 'b')


def test_request_ids_have_the_shape_the_private_runner_accepts():
    import re
    assert re.fullmatch(r'(us|kr|jp)-\d{4}-\d{2}-\d{2}-[0-9a-f]{12}', bundle.request_id('kr', '2026-11-07'))
