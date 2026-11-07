import json

import prepub_review as cli
from prepub import submit


def status(tmp_path, **kw):
    d = dict(state='submitted', request_id='us-2026-11-07-0123456789ab', draft_sha='a' * 40,
             section='us', date='2026-11-07', deadline=1000.0)
    d.update(kw)
    (tmp_path / 'status.json').write_text(json.dumps(d))


def test_waiting_inside_the_deadline_asks_to_be_called_again(tmp_path, monkeypatch):
    status(tmp_path)
    monkeypatch.setattr(cli, '_now', lambda: 0.0)
    monkeypatch.setattr(submit, 'wait', lambda *a, **k: ('timeout', None))
    assert cli.main(['wait', '--dir', str(tmp_path), '--minutes', '1']) == cli.WAITING


def test_the_deadline_turns_waiting_into_fallback(tmp_path, monkeypatch):
    status(tmp_path)
    monkeypatch.setattr(cli, '_now', lambda: 2000.0)
    assert cli.main(['wait', '--dir', str(tmp_path)]) == cli.FALLBACK
    assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'timeout'


def test_a_review_is_written_once_it_arrives(tmp_path, monkeypatch):
    status(tmp_path)
    monkeypatch.setattr(cli, '_now', lambda: 0.0)
    monkeypatch.setattr(submit, 'wait', lambda *a, **k: (
        'reviewed', {'request_id': 'x', 'draft_sha': 'y', 'review': '지적 없음', 'auth_saved': True}))
    assert cli.main(['wait', '--dir', str(tmp_path)]) == 0
    assert (tmp_path / 'review.md').read_text() == '지적 없음'
    assert cli.main(['wait', '--dir', str(tmp_path)]) == 0   # 다시 불러도 같은 답


def test_a_limit_is_a_fallback_with_its_reason(tmp_path, monkeypatch):
    status(tmp_path)
    monkeypatch.setattr(cli, '_now', lambda: 0.0)
    monkeypatch.setattr(submit, 'wait', lambda *a, **k: ('limit', {'error': 'usage limit'}))
    assert cli.main(['wait', '--dir', str(tmp_path)]) == cli.FALLBACK
    assert json.loads((tmp_path / 'status.json').read_text())['reason'] == 'usage limit'


def test_record_writes_one_file_per_post(tmp_path, monkeypatch):
    status(tmp_path, state='timeout', reason='deadline')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']) == 0
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text())
    assert rec['state'] == 'timeout' and rec['facts_applied'] == 0


PAIRS = {'proposed_sha256': 'p', 'bundles': [{'id': 'B01', 'judgment': True}, {'id': 'B02', 'judgment': False}]}


def v(**kw):
    return {'proposed_sha256': 'p', 'verdicts': {k: {'verdict': x} for k, x in kw.items()}}


def test_a_judgment_bundle_needs_two_sames():
    m = cli.merge_verdicts(PAIRS, v(B01='same', B02='same'), v(B01='unsure', B02='changed'))
    assert m['verdicts']['B01']['verdict'] == 'unsure'
    assert m['verdicts']['B02']['verdict'] == 'same'          # 판단 문장 아닌 묶음은 첫 검사
    m = cli.merge_verdicts(PAIRS, v(B01='same'), v(B01='same'))
    assert m['verdicts']['B01']['verdict'] == 'same'
    m = cli.merge_verdicts(PAIRS, v(B01='changed'), v(B01='same'))
    assert m['verdicts']['B01']['verdict'] == 'changed'


def test_verdicts_for_another_version_are_refused():
    import pytest
    with pytest.raises(ValueError):
        cli.merge_verdicts(PAIRS, v(B01='same'), {'proposed_sha256': 'other', 'verdicts': {}})


def test_style_findings_reach_the_weekly_digest(tmp_path, monkeypatch):
    from review import style_digest
    status(tmp_path, state='reviewed')
    (tmp_path / 'split.json').write_text(json.dumps({'accuracy': [], 'unplaced': [], 'excluded': [], 'candidates': 1,
                                                     'style_findings': [{'kind': '번역투', 'quote': '앞단 재가격', 'note': '풀어 쓴다'}]}))
    (tmp_path / 'original.html').write_text('<p>금리는 앞단 재가격으로 본다.</p>', encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    cli.main(['record', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07', '--style-applied', '1'])
    from datetime import datetime, timedelta, timezone
    rows = style_digest.collect(str(tmp_path / 'repo'), datetime.now(timezone.utc) - timedelta(days=7))
    assert [r['kind'] for r in rows] == ['번역투'] and '발행 전' in rows[0]['path']


def test_a_changed_draft_is_not_split_against_an_old_review(tmp_path):
    import hashlib
    html = tmp_path / 'h.html'
    html.write_text('<html><body><p>지수가 올랐다.</p></body></html>', encoding='utf-8')
    status(tmp_path, state='reviewed', source_html_sha256=hashlib.sha256(b'other').hexdigest())
    (tmp_path / 'review.md').write_text('지적 없음', encoding='utf-8')
    args = ['split', '--review', str(tmp_path / 'review.md'), '--html', str(html), '--section', 'us',
            '--date', '2026-11-07', '--out', str(tmp_path)]
    assert cli.main(args) == cli.FALLBACK
    assert cli.main(args + ['--after-fixes']) == 0


def test_a_result_that_arrives_after_the_deadline_is_dropped():
    t = [0]

    def gh(cmd, **kw):
        t[0] += 100       # 호출 하나가 마감을 넘겼다
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'request_id': 'r', 'draft_sha': 's',
                                                               'status': 'reviewed'}), '')
    state, _ = submit.wait('r', 's', 60, run=gh, sleep=lambda s: None, clock=lambda: t[0])
    assert state == 'timeout'


def test_the_public_record_keeps_only_kinds_and_quotes_found_in_the_post():
    got = cli._public_findings([{'kind': '번역투', 'quote': '앞단 재가격', 'note': '풀어 쓴다'},
                                {'kind': '기타', 'quote': 'eyJAbc123 Def456', 'note': 'eyJ' + 'A' * 60}],
                               post_text='금리는 앞단 재가격으로 본다.')
    assert got == [{'kind': '번역투', 'quote': '앞단 재가격'}, {'kind': '기타', 'quote': ''}]


def test_submit_keeps_the_original_even_when_bundling_fails(tmp_path, monkeypatch):
    html = tmp_path / 'h.html'
    html.write_text('<p>x</p>')
    from prepub import bundle as b

    def boom(*a, **k):
        raise b.BundleError('no')
    monkeypatch.setattr(b, 'build', boom)
    out = tmp_path / 'out'
    assert cli.main(['submit', '--section', 'us', '--date', '2026-11-07', '--html', str(html),
                     '--notes', str(tmp_path / 'missing.md'), '--out', str(out)]) == cli.FALLBACK
    assert (out / 'original.html').read_text() == '<p>x</p>'


def test_the_public_reason_never_carries_runner_text(tmp_path, monkeypatch):
    status(tmp_path, state='not_reviewed', reason='eyJ' + 'A' * 50 + ' 자료를 읽을 수 없었다')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    cli.main(['record', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07'])
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text())
    assert rec['reason'] == 'codex 가 검토하지 못했다'
