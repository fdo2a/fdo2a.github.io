"""오프라인 시험 하니스 — 운영 경로·집계 규칙(codex 구현 검토 #5·#7·#9)."""

import json
import os

import pytest

from close import offline_trial as ot

P1 = '유가가 2% 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'
EDIT = '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'


def _key(tmp_path, n_real=2):
    key = [{'id': 'Q%03d' % i, 'src': 'real_applied', 'post': 'p', 'A_is': 'after'} for i in range(n_real)]
    key.append({'id': 'Q900', 'src': 'artificial', 'post': 'p', 'A_is': 'before', 'meta': {'blocked': True}})
    (tmp_path / 'key.json').write_text(json.dumps(key))
    return key


def _score(tmp_path, answers):
    (tmp_path / 'answers.json').write_text(json.dumps(answers))
    ot.main(['score', '--out', str(tmp_path), '--answers', str(tmp_path / 'answers.json')])
    return json.loads((tmp_path / 'score.json').read_text())


def test_score_incomplete_is_not_pass(tmp_path):
    _key(tmp_path)
    res = _score(tmp_path, {'Q000': {'read': 'A'}, 'Q900': {'meaning': 'changed'}})
    assert res['real_applied']['pass'] is None and 'incomplete' in res['real_applied']['verdict']
    assert res['real_applied']['n'] == 0


def test_score_small_sample_is_not_pass(tmp_path):
    _key(tmp_path)
    res = _score(tmp_path, {'Q000': {'meaning': 'same', 'read': 'A'}, 'Q001': {'meaning': 'same', 'read': 'A'},
                            'Q900': {'meaning': 'changed'}})
    assert res['real_applied']['pass'] is None and 'insufficient' in res['real_applied']['verdict']
    assert res['real_applied']['better_rate'] == 1.0


def test_score_full_sample_can_pass(tmp_path):
    _key(tmp_path, n_real=40)
    ans = {'Q%03d' % i: {'meaning': 'same', 'read': 'A' if i < 30 else 'none'} for i in range(40)}
    ans['Q900'] = {'meaning': 'changed'}
    res = _score(tmp_path, ans)
    ra = res['real_applied']
    assert ra['pass'] is True and ra['better_rate'] == 0.75 and ra['unneeded_rate'] == 0.25
    ans['Q005'] = {'meaning': 'changed', 'read': 'A'}
    assert _score(tmp_path, ans)['real_applied']['pass'] is False


@pytest.mark.parametrize('cmd', ['report', 'sheets'])
def test_outputs_inside_repo_refused(cmd):
    from close import paths
    with pytest.raises(paths.PathError):
        ot.main([cmd, '--out', os.path.join(paths.REPO, 'reviews')])


def test_run_uses_the_real_guard_cli(tmp_path, monkeypatch):
    """작성자·검사자는 가짜, check/apply 는 close_guard.py 그대로 — 반영 판이 approved.html 로 나온다."""
    post = tmp_path / 'site' / 'posts'
    post.mkdir(parents=True)
    html = '<html><body><h2>시장</h2><div class="card"><p>%s</p></div></body></html>' % P1
    (post / '2026-10-01.html').write_text(html, encoding='utf-8')
    monkeypatch.setattr(ot, 'REPO', str(tmp_path / 'site'))

    def fake(system_file, prompt, tools, cwd, **kw):
        if 'proposed_sha256:' in prompt:
            sha = prompt.split('proposed_sha256: ', 1)[1].split()[0]
            text = json.dumps({'proposed_sha256': sha, 'verdicts': {'B01': {'verdict': 'same', 'why': 'x'}}})
        else:
            text = json.dumps({'C01': EDIT}, ensure_ascii=False)
        return {'text': text, 'usage': {'input_tokens': 10, 'output_tokens': 5}, 'cost': 0.01, 'ms': 1, 'ok': True,
                'error': None, 'turns': 1}
    monkeypatch.setattr(ot, 'claude', fake)
    monkeypatch.setattr(ot, 'AGENTS', os.path.join(os.path.dirname(ot.HERE), '..', '.claude', 'agents'))
    out = tmp_path / 'out'
    out.mkdir()
    sandbox = tmp_path / 'sb'
    sandbox.mkdir()
    rec = ot.run_post('posts/2026-10-01.html', str(out), str(sandbox))
    assert rec['outcome'] == 'applied', rec
    approved = (out / 'runs' / 'us_2026-10-01' / 'approved.html').read_text()
    assert '올랐고' in approved
    calls = [json.loads(l) for l in open(out / 'calls.jsonl')]
    assert [c['role'] for c in calls] == ['writer', 'checker']


def _args(tmp_path, *extra):
    out = tmp_path / 'trial'
    out.mkdir(exist_ok=True)
    return out, ['run', '--out', str(out), '--posts', 'posts/x.html', *extra]


def test_default_mode_mirrors_production_editor(tmp_path, monkeypatch):
    """운영은 A5 를 narrow-editor 로 부른다 — 시험이 옛 작성자를 재면 다른 프롬프트를 잰다."""
    seen = []
    monkeypatch.setattr(ot, 'run_post', lambda p, out, sb, mode: seen.append(mode) or
                        {'post': p, 'outcome': 'no_candidates', 'candidates': 0})
    out, argv = _args(tmp_path)
    assert ot.main(argv) == 0
    assert seen == ['narrow-editor']
    assert json.loads((out / 'mode.json').read_text())['mode'] == 'narrow-editor'
    assert ot.editor_file('narrow-editor', 'us') == 'narrow-editor.md'
    assert ot.editor_file('full-writer', 'kr') == 'kr-report-writer.md'


def test_one_directory_one_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(ot, 'run_post', lambda p, out, sb, mode: {'post': p, 'outcome': 'x', 'candidates': 0})
    out, argv = _args(tmp_path)
    assert ot.main(argv) == 0
    assert ot.main(argv + ['--full-writer']) == 2          # 같은 폴더에 다른 편집자 결과를 섞지 않는다
    assert ot.main(argv + ['--lean']) == 2
    assert ot.main(argv) == 0


def test_legacy_directory_without_mode_is_not_resumed(tmp_path, monkeypatch):
    monkeypatch.setattr(ot, 'run_post', lambda p, out, sb, mode: {'post': p, 'outcome': 'x', 'candidates': 0})
    out, argv = _args(tmp_path)
    (out / 'calls.jsonl').write_text('{}\n')
    assert ot.main(argv) == 2 and not (out / 'mode.json').exists()
    assert ot.recorded_mode(str(out)) == 'unknown (pre-mode.json)'


def test_lean_and_full_writer_are_exclusive(tmp_path):
    out, argv = _args(tmp_path)
    with pytest.raises(SystemExit):
        ot.main(argv + ['--lean', '--full-writer'])
