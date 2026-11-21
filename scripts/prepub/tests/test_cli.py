import json

import prepub_review as cli
from prepub import submit


def status(tmp_path, **kw):
    d = dict(state='submitted', request_id='us-2026-11-07-0123456789ab', draft_sha='a' * 40,
             section='us', date='2026-11-07', deadline=1000.0)
    d.update(kw)
    if d['state'] == 'facts_done' and 'facts_sha256' not in d:
        import hashlib
        final = tmp_path / 'final.html'
        if not final.exists():
            final.write_text('<p>판정을 마친 판</p>', encoding='utf-8')
        d['facts_sha256'] = hashlib.sha256(final.read_bytes()).hexdigest()
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
    status(tmp_path, state='facts_done', facts_applied=0, facts_rejected=0)
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == 0
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text())
    assert rec['state'] == 'reviewed' and rec['facts_applied'] == 0 and rec['facts_done'] is True


# ── 막기(2026-11-22) — 검토를 끝내지 못한 글은 발행 기록을 만들 수 없다 ─────────────────────

def test_record_refuses_anything_short_of_facts_done(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    for st in ('submitted', 'reviewed', 'timeout', 'limit', 'submit_failed', 'stale_html', 'eyJ'):
        status(tmp_path, state=st)
        assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == cli.FALLBACK
        assert not (tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').exists()
    (tmp_path / 'status.json').unlink()
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == cli.FALLBACK


def test_facts_done_needs_a_review_and_seals_the_file(tmp_path):
    (tmp_path / 'h.html').write_text('<p>x</p>', encoding='utf-8')
    status(tmp_path, state='timeout')
    assert cli.main(['facts-done', '--dir', str(tmp_path), '--html', str(tmp_path / 'h.html')]) == cli.FALLBACK
    status(tmp_path, state='reviewed')
    assert cli.main(['facts-done', '--dir', str(tmp_path), '--html', str(tmp_path / 'h.html'),
                     '--applied', '2', '--rejected', '1']) == 0
    st = json.loads((tmp_path / 'status.json').read_text())
    import hashlib
    assert st['state'] == 'facts_done' and st['facts_sha256'] == hashlib.sha256(b'<p>x</p>').hexdigest()
    assert (st['facts_applied'], st['facts_rejected']) == (2, 1)


def _hold(tmp_path, monkeypatch, capsys, *extra, **st):
    if st:
        status(tmp_path, **st)
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07', *extra]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    raw = (tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8')
    return out, json.loads(raw), raw


def test_a_review_that_never_ran_holds_and_lets_the_retry_start_over(tmp_path, monkeypatch, capsys):
    for st in ('submit_failed', 'timeout', 'limit', 'failed', 'mismatch', 'not_reviewed', 'auth_missing'):
        out, rec, _ = _hold(tmp_path, monkeypatch, capsys, state=st, reason='x')
        assert out.endswith('lock=release') and rec['state'] == st and rec['hold'] is True


def test_a_stale_draft_or_failed_mark_also_starts_over(tmp_path, monkeypatch, capsys):
    for st in ('stale_html', 'mark_failed'):
        out, rec, _ = _hold(tmp_path, monkeypatch, capsys, '--state', st, state='reviewed')
        assert out.endswith('lock=release') and rec['state'] == st


def test_once_judging_began_the_hold_waits_for_a_person(tmp_path, monkeypatch, capsys):
    out, rec, _ = _hold(tmp_path, monkeypatch, capsys, '--state', 'recovery_needed', state='reviewed')
    assert out.endswith('lock=hold:recovery_needed') and rec['state'] == 'recovery_needed'
    out, rec, _ = _hold(tmp_path, monkeypatch, capsys, '--state', 'style_abort', state='facts_done')
    assert out.endswith('lock=hold:style_abort')
    # 판정을 시작한 뒤 이유를 안 붙이면 — 모르는 것은 막는 쪽
    out, rec, _ = _hold(tmp_path, monkeypatch, capsys, state='reviewed')
    assert out.endswith('lock=hold:recovery_needed')
    out, rec, _ = _hold(tmp_path, monkeypatch, capsys, state='eyJhbGciOi')
    assert out.endswith('lock=hold:recovery_needed') and rec['state'] == 'recovery_needed'


def test_the_hold_record_carries_only_closed_fields(tmp_path, monkeypatch, capsys):
    status(tmp_path, state='not_reviewed', reason='eyJ' + 'A' * 50 + ' 자료를 읽을 수 없었다')
    (tmp_path / 'split.json').write_text(json.dumps({'clarity': CLARITY, 'style_findings': [{'kind': '번역투', 'quote': 'q'}]}))
    (tmp_path / 'original.html').write_text(DRAFT, encoding='utf-8')
    _, rec, raw = _hold(tmp_path, monkeypatch, capsys)
    assert set(rec) == {'section', 'date', 'request_id', 'state', 'reason', 'hold', 'recorded_at'}
    assert rec['reason'] == 'codex 가 검토하지 못했다'
    assert 'eyJ' not in raw and '노출 축소' not in raw and '번역투' not in raw


def test_the_hold_record_has_no_leak_scan_fixed_strings(tmp_path, monkeypatch, capsys):
    from close import leak
    _, _, raw = _hold(tmp_path, monkeypatch, capsys, '--state', 'recovery_needed', state='reviewed')
    assert not [k for k in leak.FINGER_KEYS if k in raw]


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
    (tmp_path / 'final.html').write_text('<p>금리는 앞단 재가격으로 본다.</p>', encoding='utf-8')
    status(tmp_path, state='facts_done')
    (tmp_path / 'split.json').write_text(json.dumps({'accuracy': [], 'unplaced': [], 'excluded': [], 'candidates': 1,
                                                     'style_findings': [{'kind': '번역투', 'quote': '앞단 재가격', 'note': '풀어 쓴다'}]}))
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07', '--style-applied', '1'])
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
    status(tmp_path, state='facts_done', reason='eyJ' + 'A' * 50 + ' 자료를 읽을 수 없었다')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07'])
    raw = (tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text()
    assert json.loads(raw)['reason'] == '' and 'eyJ' not in raw


# ── 명료성 분류의 공개 기록(2026-11-18) — 닫힌 값과 글에 있는 인용만 ─────────────────────

CLARITY = [{'kind': '용어', 'quote': '이분 사건을 앞둔 노출 축소', 'note': '(가) eyJhbGciOiJIUzI1NiJ9 무엇인지 모른다 / 풀어 쓴다',
            'cannot_tell': '가', 'route': 'style_path', 'placed': 'candidate'},
           {'kind': '지시 대상 불명확', 'quote': '이 차이가 이미 가격에', 'note': '(다) 대상 불명확',
            'cannot_tell': '다', 'route': 'record_only', 'placed': ''}]
DRAFT = '<p>금은 이분 사건을 앞둔 노출 축소 흐름에 올랐다. 이 차이가 이미 가격에 들어 있는지는 모른다.</p>'


def _record(tmp_path, monkeypatch, split=None, **st):
    (tmp_path / 'final.html').write_text(DRAFT, encoding='utf-8')      # 인용은 올릴 판과 대조한다
    status(tmp_path, state='facts_done', **st)
    if split is not None:
        (tmp_path / 'split.json').write_text(json.dumps(split, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == 0
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


def test_a_published_record_keeps_todays_fields_plus_the_seal(tmp_path, monkeypatch):
    """발행 기록은 옛 칸을 그대로 두고 `facts_done` 하나만 더한다(주간 묶음·러너가 읽는 칸)."""
    status(tmp_path, state='facts_done', facts_applied=1, facts_rejected=2)
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == 0
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))
    assert list(rec) == ['section', 'date', 'request_id', 'draft_sha', 'state', 'reason', 'auth_saved',
                         'accuracy_findings', 'style_candidates', 'style_excluded', 'style_unplaced', 'style_dropped',
                         'facts_applied', 'facts_rejected', 'style_applied', 'style_rejected', 'skeleton_rejected',
                         'checker_rejected', 'style_findings', 'recorded_at', 'facts_done', 'final_sha256']
    assert (rec['facts_applied'], rec['facts_rejected']) == (1, 2)


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


def test_a_clarity_quote_is_matched_the_way_the_reader_sees_the_post(tmp_path, monkeypatch):
    """인라인 태그·엔티티를 낀 인용도 독자가 보는 글자로 대조한다 — 주간 묶음이 발행본과 견줄 때도 같은 방식이다."""
    (tmp_path / 'final.html').write_text(
        '<p>S&amp;P <b>500</b>은 원판정으로 내렸다. 문단 끝과</p><p>다음 문단이다.</p>', encoding='utf-8')
    status(tmp_path, state='facts_done')
    (tmp_path / 'split.json').write_text(json.dumps({'clarity': [
        {'kind': '용어', 'quote': 'S&P 500은 원판정으로', 'cannot_tell': '가', 'route': 'style_path', 'placed': 'candidate'},
        {'kind': '용어', 'quote': '문단 끝과 다음 문단', 'cannot_tell': '가', 'route': 'style_path', 'placed': ''}]},
        ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07'])
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))
    assert [c['quote'] for c in rec['clarity']] == ['S&P 500은 원판정으로', '']   # 두 문단에 걸친 글자는 인용이 아니다


def test_a_person_gets_the_materials_only_in_the_private_repo(tmp_path, monkeypatch, capsys):
    sent = {}
    status(tmp_path, state='reviewed', request_id='us-2026-11-07-0123456789ab')
    (tmp_path / 'review.md').write_text('codex 의 답', encoding='utf-8')
    (tmp_path / 'h.html').write_text('<p>고치던 판</p>', encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda files, branch, msg, *a, **k: sent.update(files=files, branch=branch))
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07',
                     '--state', 'recovery_needed', '--html', str(tmp_path / 'h.html')]) == 0
    assert capsys.readouterr().out.strip().endswith('materials=private pushed=skipped lock=hold:recovery_needed')
    assert sent['branch'] == 'holds'
    assert set(sent['files']) == {f'holds/us/2026-11-07/us-2026-11-07-0123456789ab/{n}'
                                  for n in ('status.json', 'review.md', 'current.html')}
    raw = (tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8')
    assert 'codex 의 답' not in raw and '고치던 판' not in raw


def test_a_failed_upload_still_holds(tmp_path, monkeypatch, capsys):
    status(tmp_path, state='reviewed')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))

    def boom(*a, **k):
        raise submit.SubmitError('down')
    monkeypatch.setattr(submit, 'upload', boom)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07',
                     '--state', 'recovery_needed']) == 0
    assert capsys.readouterr().out.strip().endswith('materials=failed pushed=skipped lock=hold:recovery_needed')


def test_a_review_that_never_ran_uploads_nothing(tmp_path, monkeypatch, capsys):
    called = []
    status(tmp_path, state='limit')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: called.append(1))
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']) == 0
    assert not called and capsys.readouterr().out.strip().endswith('materials=none pushed=skipped lock=release')


# ── 판정을 마친 판 = 올릴 판 (codex 구현 1회차 #2) ─────────────────────────────────────

def _done(tmp_path):
    h = tmp_path / 'h.html'
    h.write_text('<p>수정 반영판</p>', encoding='utf-8')
    status(tmp_path, state='reviewed')
    assert cli.main(['facts-done', '--dir', str(tmp_path), '--html', str(h), '--applied', '1']) == 0
    return h


def test_a_rewrite_after_facts_done_cannot_be_recorded_until_restamped(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    h = _done(tmp_path)
    post = tmp_path / 'post.html'
    post.write_text('<p>작성자가 다시 쓴 판</p>', encoding='utf-8')     # 받아들인 수정이 빠졌을 수 있다
    rec = ['record', '--dir', str(tmp_path), '--html', str(post), '--section', 'us', '--date', '2026-11-07']
    assert cli.main(rec) == cli.FALLBACK
    assert not (tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').exists()
    # 루틴이 그 판에서 받아들인 지적을 다시 대조하고 다시 찍으면 된다
    assert cli.main(['facts-done', '--dir', str(tmp_path), '--html', str(post), '--applied', '1']) == 0
    assert cli.main(rec) == 0


def test_style_and_note_changes_pass_only_when_sealed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    h = _done(tmp_path)
    h.write_text('<p>수정 반영판 — 문체 편집</p>', encoding='utf-8')
    rec = ['record', '--dir', str(tmp_path), '--html', str(h), '--section', 'us', '--date', '2026-11-07']
    assert cli.main(rec) == cli.FALLBACK
    assert cli.main(['seal', '--dir', str(tmp_path), '--html', str(h), '--why', 'style']) == 0
    assert cli.main(rec) == 0
    # 다시 찍으면 앞선 봉인은 사라진다
    other = tmp_path / 'o.html'
    other.write_text('<p>또 다른 판</p>', encoding='utf-8')
    assert cli.main(['facts-done', '--dir', str(tmp_path), '--html', str(other)]) == 0
    assert cli.main(rec) == cli.FALLBACK


def test_seal_needs_a_finished_judgment(tmp_path):
    h = tmp_path / 'h.html'
    h.write_text('x', encoding='utf-8')
    status(tmp_path, state='reviewed')
    assert cli.main(['seal', '--dir', str(tmp_path), '--html', str(h), '--why', 'note']) == cli.FALLBACK


# ── 보류 기록 push 는 그 파일 하나뿐 (codex 구현 1회차 #1) ──────────────────────────────

def _git(cwd, *a):
    import subprocess
    return subprocess.run(['git', '-C', str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


def test_the_hold_push_never_carries_staged_or_committed_posts(tmp_path, monkeypatch, capsys):
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(origin))
    work = tmp_path / 'work'
    _git(tmp_path, 'clone', '-q', str(origin), str(work))
    (work / 'README').write_text('x')
    _git(work, 'add', '-A')
    _git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'base')
    _git(work, 'push', '-q', 'origin', 'HEAD:main')
    # 발행 커밋을 이미 로컬에 만들었고(STEP 3), 다른 글도 스테이징돼 있다(문체 마감 B 의 git add -A)
    (work / 'posts').mkdir()
    (work / 'posts/2026-11-07.html').write_text('<p>세운 글</p>')
    _git(work, 'add', '-A')
    _git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'Add brief')
    (work / 'news').mkdir()
    (work / 'news/2026-11-07.html').write_text('<p>뉴스</p>')
    _git(work, 'add', '-A')
    status(tmp_path, state='limit')
    monkeypatch.setattr(cli, 'ROOT', str(work))
    monkeypatch.setenv('GIT_AUTHOR_NAME', 't'); monkeypatch.setenv('GIT_AUTHOR_EMAIL', 't@t')
    monkeypatch.setenv('GIT_COMMITTER_NAME', 't'); monkeypatch.setenv('GIT_COMMITTER_EMAIL', 't@t')
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07', '--push']) == 0
    assert 'pushed=ok' in capsys.readouterr().out
    names = _git(origin, 'ls-tree', '-r', '--name-only', 'main').split()
    assert names == ['README', 'reviews/prepublish/us/2026-11-07.json']


def test_a_phrase_removed_by_the_fixes_never_reaches_the_public_record(tmp_path, monkeypatch):
    """제출 초안에는 있고 올릴 판에는 없는 인용은 두 칸 모두 빈 값이다 — 중간판 글자가 공개 기록에 남지 않는다
    (codex 구현 2회차 #2)."""
    (tmp_path / 'original.html').write_text('<p>금리는 앞단 재가격으로 본다. 남는 문장은 그대로다.</p>', encoding='utf-8')
    (tmp_path / 'final.html').write_text('<p>금리는 단기 구간의 가격 조정으로 본다. 남는 문장은 그대로다.</p>', encoding='utf-8')
    status(tmp_path, state='facts_done')
    (tmp_path / 'split.json').write_text(json.dumps({
        'style_findings': [{'kind': '번역투', 'quote': '앞단 재가격'}, {'kind': '번역투', 'quote': '남는 문장은 그대로다'}],
        'clarity': [{'kind': '용어', 'quote': '앞단 재가격', 'cannot_tell': '가', 'route': 'style_path', 'placed': 'candidate'},
                    {'kind': '용어', 'quote': '남는 문장은 그대로다', 'cannot_tell': '가', 'route': 'style_path', 'placed': ''}]},
        ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == 0
    raw = (tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8')
    rec = json.loads(raw)
    assert [f['quote'] for f in rec['style_findings']] == ['', '남는 문장은 그대로다']
    assert [c['quote'] for c in rec['clarity']] == ['', '남는 문장은 그대로다']
    assert '앞단 재가격' not in raw


def test_the_weekly_digest_reads_a_record_whose_quotes_are_blank(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from review import style_digest
    (tmp_path / 'final.html').write_text('<p>고친 뒤의 글.</p>', encoding='utf-8')
    status(tmp_path, state='facts_done')
    (tmp_path / 'split.json').write_text(json.dumps({'style_findings': [{'kind': '번역투', 'quote': '지워진 글자'}]},
                                                    ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(tmp_path / 'final.html'), '--section', 'us', '--date', '2026-11-07']) == 0
    rows = style_digest.collect(str(tmp_path / 'repo'), datetime.now(timezone.utc) - timedelta(days=7))
    assert [(r['kind'], r.get('quote', '')) for r in rows] == [('번역투', '')]
