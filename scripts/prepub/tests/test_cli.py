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


# ── 명료성 분류의 공개 기록(2026-11-18) — 닫힌 값과 글에 있는 인용만 ─────────────────────

CLARITY = [{'kind': '용어', 'quote': '이분 사건을 앞둔 노출 축소', 'note': '(가) eyJhbGciOiJIUzI1NiJ9 무엇인지 모른다 / 풀어 쓴다',
            'cannot_tell': '가', 'route': 'style_path', 'placed': 'candidate'},
           {'kind': '지시 대상 불명확', 'quote': '이 차이가 이미 가격에', 'note': '(다) 대상 불명확',
            'cannot_tell': '다', 'route': 'record_only', 'placed': ''}]
DRAFT = '<p>금은 이분 사건을 앞둔 노출 축소 흐름에 올랐다. 이 차이가 이미 가격에 들어 있는지는 모른다.</p>'


def _record(tmp_path, monkeypatch, split=None, **st):
    status(tmp_path, state='reviewed', **st)
    if split is not None:
        (tmp_path / 'split.json').write_text(json.dumps(split, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'original.html').write_text(DRAFT, encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']) == 0
    path = tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json'
    return json.loads(path.read_text(encoding='utf-8')), path.read_text(encoding='utf-8')


def test_the_public_record_carries_clarity_findings_as_closed_values(tmp_path, monkeypatch):
    rec, raw = _record(tmp_path, monkeypatch, {
        'accuracy': [], 'unplaced': [], 'excluded': [], 'dropped': [], 'candidates': 1, 'style_findings': [],
        'clarity': CLARITY, 'clarity_meta': {'marker': True, 'lines_skipped': 0, 'over_cap': 0}})
    assert rec['clarity'] == [
        {'kind': '용어', 'quote': '이분 사건을 앞둔 노출 축소', 'cannot_tell': '가', 'route': 'style_path', 'placed': 'candidate'},
        {'kind': '지시 대상 불명확', 'quote': '이 차이가 이미 가격에', 'cannot_tell': '다', 'route': 'record_only', 'placed': ''}]
    assert rec['clarity_meta'] == {'marker': True, 'lines_skipped': 0, 'over_cap': 0}
    assert 'eyJ' not in raw and '무엇인지 모른다' not in raw and '풀어 쓴다' not in raw   # 검토자의 글은 실리지 않는다


def test_values_outside_the_closed_sets_never_reach_the_public_record(tmp_path, monkeypatch):
    bad = [{'kind': '용어', 'quote': '글에 없는 인용 eyJhbGci', 'cannot_tell': 'eyJhbGci', 'route': 'eyJ', 'placed': 'eyJ'},
           {'kind': 'eyJhbGciOi', 'quote': '이 차이가 이미 가격에', 'cannot_tell': '다', 'route': 'record_only', 'placed': ''},
           'not a dict']
    rec, raw = _record(tmp_path, monkeypatch, {'clarity': bad, 'clarity_meta': {'marker': 'eyJhbGci', 'lines_skipped': 'x'}})
    assert rec['clarity'] == [{'kind': '용어', 'quote': '', 'cannot_tell': '', 'route': 'style_path', 'placed': ''}]
    assert rec['clarity_meta'] == {'marker': False, 'lines_skipped': 0, 'over_cap': 0}
    assert 'eyJ' not in raw


def test_the_new_fields_do_not_trip_the_leak_scan_fixed_strings(tmp_path, monkeypatch):
    """공개 기록은 발행 직전 유출 검사의 대상이다 — 칸 이름이 그 고정 문자열과 같으면 발행이 중단된다."""
    from close import leak
    _, raw = _record(tmp_path, monkeypatch, {'clarity': CLARITY, 'clarity_meta': {'marker': True}})
    assert not [k for k in leak.FINGER_KEYS if k in raw]


def test_a_broken_clarity_block_falls_back_to_todays_record(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('x')
    monkeypatch.setattr(cli, '_public_clarity', boom)
    rec, _ = _record(tmp_path, monkeypatch, {'accuracy': [{'kind': '판단 세기 흐림'}], 'clarity': CLARITY})
    assert 'clarity' not in rec and 'clarity_meta' not in rec
    assert rec['state'] == 'reviewed' and rec['accuracy_findings'] == 1


OLD_KEYS = ['section', 'date', 'request_id', 'draft_sha', 'state', 'reason', 'auth_saved', 'accuracy_findings',
            'style_candidates', 'style_excluded', 'style_unplaced', 'style_dropped', 'facts_applied',
            'facts_rejected', 'style_applied', 'style_rejected', 'skeleton_rejected', 'checker_rejected',
            'style_findings', 'recorded_at']


def test_a_run_without_a_review_writes_the_record_it_writes_today(tmp_path, monkeypatch):
    """검토가 없거나 실패한 날(split.json 없음)의 기록은 칸 하나도 늘지 않는다."""
    status(tmp_path, state='submit_failed', reason='HTTP 502')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']) == 0
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))
    assert list(rec) == OLD_KEYS and rec['state'] == 'submit_failed'


def test_split_keeps_the_tokens_the_routine_reads(tmp_path, capsys):
    import hashlib
    html = tmp_path / 'h.html'
    html.write_text('<html><body data-register="da"><div class="doc"><h2>장</h2>'
                    '<p>금은 이분 사건을 앞둔 노출 축소 흐름에 올랐다. 이 차이가 이미 가격에 들어 있는지는 모른다.</p>'
                    '</div></body></html>', encoding='utf-8')
    status(tmp_path, state='reviewed', source_html_sha256=hashlib.sha256(html.read_bytes()).hexdigest())
    (tmp_path / 'review.md').write_text('=== 문체 지적 ===\n- [지시 대상 불명확] 「이 차이가 이미 가격에」 — (다) 대상 불명확 / x\n',
                                        encoding='utf-8')
    assert cli.main(['split', '--review', str(tmp_path / 'review.md'), '--html', str(html), '--section', 'us',
                     '--date', '2026-11-07', '--out', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert 'prepub: accuracy 0 · style candidates 0 ·' in out and 'recorded 1' in out
    got = json.loads((tmp_path / 'split.json').read_text(encoding='utf-8'))
    assert got['candidates'] == 0 and [f['kind'] for f in got['clarity']] == ['지시 대상 불명확']
    assert got['clarity_meta']['marker'] is True


def test_a_clarity_quote_is_matched_the_way_the_reader_sees_the_draft(tmp_path, monkeypatch):
    """인라인 태그·엔티티를 낀 인용도 독자가 보는 글자로 대조한다 — 주간 묶음이 발행본과 견줄 때도 같은 방식이다."""
    status(tmp_path, state='reviewed')
    (tmp_path / 'split.json').write_text(json.dumps({'clarity': [
        {'kind': '용어', 'quote': 'S&P 500은 원판정으로', 'cannot_tell': '가', 'route': 'style_path', 'placed': 'candidate'},
        {'kind': '용어', 'quote': '문단 끝과 다음 문단', 'cannot_tell': '가', 'route': 'style_path', 'placed': ''}]},
        ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'original.html').write_text(
        '<p>S&amp;P <b>500</b>은 원판정으로 내렸다. 문단 끝과</p><p>다음 문단이다.</p>', encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    cli.main(['record', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07'])
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))
    assert [c['quote'] for c in rec['clarity']] == ['S&P 500은 원판정으로', '']   # 두 문단에 걸친 글자는 인용이 아니다
