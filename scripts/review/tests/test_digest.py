"""매일 검증 알림(`review.digest`, CLI `scripts/verify_digest.py`) — 2026-11-08.

알림이 거짓말을 하는 자리를 막는다: 경고를 「이상 없음」으로 읽기, 늦게 끝난 검토 놓치기,
원장에 이름만 있는 글을 「검토 끝」으로 세기, 같은 내용 매일 반복, 4,000자 넘김.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime

import pytest

from review import digest as D

KST = D.KST


def at(y, m, d, h=9, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=KST)


# ── 어떤 글을 따라가나 ─────────────────────────────────────────────────────

def test_post_day_by_section():
    assert D.post_day('posts/2026-11-06.html') == date(2026, 11, 6)
    assert D.post_day('kr/posts/2026-11-06.html') == date(2026, 11, 6)
    assert D.post_day('news/2026-11-06.html') == date(2026, 11, 6)
    assert D.post_day('kr/news/2026-11-06.html') == date(2026, 11, 6)
    assert D.post_day('weekly/2026-W45.html') == date(2026, 11, 7)      # 토요일
    assert D.post_day('japan/daily/2026-11-05.html') == date(2026, 11, 5)
    assert D.post_day('about.html') is None
    assert D.post_day('china/posts/2026-09-01.html') is None             # 따라가지 않는 섹션


def test_tracked_posts_keeps_window_only():
    tree = {'posts/2026-11-06.html': 'a', 'posts/2026-10-20.html': 'b',
            'kr/news/2026-11-05.html': 'c', 'index.html': 'd', 'posts/2026-11-09.html': 'e'}
    got = D.tracked_posts(tree, date(2026, 11, 8))
    assert [p for p, _, _ in got] == ['kr/news/2026-11-05.html', 'posts/2026-11-06.html']


def test_window_is_seven_dates():
    # codex 구현 검토 #7 — 오늘 포함 7개 날짜
    tree = {f'posts/2026-11-0{i}.html': 'a' for i in range(1, 9)}
    got = [p for p, _, _ in D.tracked_posts(tree, date(2026, 11, 8))]
    assert got[0] == 'posts/2026-11-02.html' and len(got) == 7


def test_kept_posts_ninety_dates():
    tree = {'posts/2026-08-12.html': 'a', 'posts/2026-08-11.html': 'b', 'posts/2026-11-09.html': 'c',
            'posts/2026-11-10.html': 'd'}
    got = [p for p, _, _ in D.kept_posts(tree, date(2026, 11, 9))]
    assert got == ['posts/2026-08-12.html', 'posts/2026-11-09.html']     # 오늘 포함 90개 날짜


def _p(path, state='완료', sha='s1', findings=0):
    return post(path, state=state, findings=findings, sha=sha)


def test_reconcile_first_run_baselines_only_finished_old_posts():
    # 3차 #3 — 첫 알림에 창 밖 미해결 글은 보이고, 끝난 글만 기준판으로 적는다
    today = date(2026, 11, 9)
    done_old, open_old, new = _p('posts/2026-10-01.html'), _p('posts/2026-10-02.html', '대기'), _p('posts/2026-11-06.html')
    lines, notes, tracked = D.reconcile([done_old, open_old, new], {}, {x['path']: 's1' for x in (done_old, open_old, new)}, today)
    assert set(lines) == {'posts/2026-10-01.html'}
    text, _ = D.render([done_old, open_old, new], lines, at(2026, 11, 9))
    assert 'US 일간 10/02' in text and 'US 일간 11/06' in text and '■ US 일간 10/01' not in text
    assert tracked == {x['path']: 's1' for x in (done_old, open_old, new)}


def test_reconcile_reports_removed_posts_once():
    # 3차 #2 — 공개판에서 사라진 글은 알리고 기록에서 뺀다(되살아나면 새 글로 다시 나온다)
    state = {'last_sent': 'x', 'lines': {'posts/2026-11-05.html': {'sha': 'a', 'text': 't'}},
             'open': ['kr/posts/2026-11-05.html'], 'tracked': {'news/2026-11-05.html': 'n'}}
    lines, notes, _ = D.reconcile([], state, {}, date(2026, 11, 9))
    # 4차 #2 — 전달 전에 지운 끝난 글(추적 목록에만 있던 것)도 알린다
    assert lines == {} and '공개판에서 사라진 글 3건' in notes[0] and 'US 뉴스 11/05' in notes[0]


def test_reconcile_reports_aged_undelivered_or_open():
    # 3차 #1 — 90일이 지나 빠지는 글 중 안 끝났거나 못 보낸 글은 알린다
    old_done, old_cut, old_open = 'posts/2026-08-01.html', 'posts/2026-08-02.html', 'posts/2026-08-03.html'
    old_changed = 'posts/2026-08-04.html'
    state = {'last_sent': 'x', 'lines': {old_done: {'sha': 'a', 'text': 't'},
                                         old_changed: {'sha': 'A', 'text': 't'}},
             'open': [old_open], 'tracked': {old_done: 'a', old_cut: 'b', old_open: 'c', old_changed: 'B'}}
    tree = {old_done: 'a', old_cut: 'b', old_open: 'c', old_changed: 'B'}
    lines, notes, tracked = D.reconcile([], state, tree, date(2026, 11, 9))
    # 4차 #1 — 전달한 A판 뒤 못 보낸 B판도 알린다
    assert '추적을 멈춘 글 3건' in notes[0] and 'US 일간 8/02' in notes[0] and 'US 일간 8/04' in notes[0]
    assert 'US 일간 8/01' not in notes[0]
    assert lines == {} and tracked == {}


def test_reconcile_reports_late_old_posts():
    # 4차 #3 — 90일보다 오래된 날짜의 글이 새로 올라오면 알린다(첫 알림의 기존 글은 제외)
    state = {'last_sent': 'x', 'lines': {}, 'tracked': {}, 'all': ['posts/2026-11-01.html']}
    tree = {'posts/2026-11-01.html': 'a', 'posts/2026-07-01.html': 'b'}
    _, notes, _ = D.reconcile([], state, tree, date(2026, 11, 9))
    assert '90일보다 오래된 날짜의 글이 새로 올라왔어요' in notes[0] and 'US 일간 7/01' in notes[0]
    _, notes, _ = D.reconcile([], {}, tree, date(2026, 11, 9))
    assert notes == []


def test_notes_name_every_post():
    # 4차 #5 — 건수만 있고 이름이 빠진 글이 없게
    tracked = {f'posts/2026-08-0{d}.html': 's' for d in range(1, 8)}
    state = {'last_sent': 'x', 'lines': {}, 'open': list(tracked), 'tracked': tracked}
    _, notes, _ = D.reconcile([], state, {}, date(2026, 11, 9))
    assert all(f'8/0{d}' in notes[0] for d in range(1, 8))


def test_checker_version_changes_with_checker_files(tmp_path):
    a = tmp_path / 'a.py'
    a.write_text('x')
    v1 = D.checker_version([str(a)], base=str(tmp_path))
    a.write_text('y')
    assert D.checker_version([str(a)], base=str(tmp_path)) != v1 and len(v1) == 12


def test_checker_version_ignores_checkout_location(tmp_path):
    # 5차 #4 — 예약 실행은 매번 다른 임시 사본이다. 위치가 아니라 내용으로 키를 만든다
    for d in ('one', 'two'):
        (tmp_path / d / 'us').mkdir(parents=True)
        (tmp_path / d / 'us' / 'a.py').write_text('same')
    v = [D.checker_version([str(tmp_path / d / 'us' / 'a.py')], base=str(tmp_path / d)) for d in ('one', 'two')]
    assert v[0] == v[1]


def test_status_change_of_old_finished_post_is_reported():
    # 3차 #4 — 창 밖 글이라도 상태가 바뀌면(같은 blob) 알린다
    a = _p('posts/2026-10-01.html', findings=1)
    lines = {a['path']: {'sha': 's1', 'text': D.block(_p('posts/2026-10-01.html', state='대기'))}}
    text, _ = D.render([a], lines, at(2026, 11, 9))
    assert '■ US 일간 10/01 — 검토 끝' in text


# ── 검토 상태 ────────────────────────────────────────────────────────────

def test_review_state_buckets_beat_ledger():
    reviewed = {'posts/2026-11-06.html': {'sha': 'old', 'findings': 3}}
    # 원장에 이름이 있어도 지금 판이 큐에 있으면 검토 안 된 것이다(codex 설계 #5)
    assert D.review_state('posts/2026-11-06.html', 'new', reviewed,
                          {'posts/2026-11-06.html': 'pending'}) == ('대기', None)
    assert D.review_state('posts/2026-11-06.html', 'new', reviewed,
                          {'posts/2026-11-06.html': 'expired'}) == ('만료', None)
    assert D.review_state('posts/2026-11-06.html', 'new', reviewed,
                          {'posts/2026-11-06.html': 'unavailable'}) == ('판정 불가', None)


def test_review_state_ledger_and_baseline():
    reviewed = {'posts/a.html': {'sha': 's', 'findings': 4},
                'posts/b.html': {'sha': 's', 'findings': 0, 'baseline': True}}
    assert D.review_state('posts/a.html', 's', reviewed, {}) == ('완료', 4)
    assert D.review_state('posts/b.html', 's', reviewed, {}) == ('읽지 않음', None)
    assert D.review_state('posts/c.html', 's', reviewed, {}) == ('기록 없음', None)
    # 조판만 바뀐 판은 검토된 판과 같다 — 원장의 지적 수를 그대로
    assert D.review_state('posts/a.html', 't', reviewed, {'posts/a.html': 'typography'}) == ('완료', 4)


def test_auto_review_flag():
    assert D.auto_reviewed('posts/2026-11-06.html')
    assert D.auto_reviewed('weekly/2026-W45.html')
    assert not D.auto_reviewed('news/2026-11-06.html')
    assert not D.auto_reviewed('kr/news/2026-11-06.html')


# ── 숫자 재검사 결과 읽기 ───────────────────────────────────────────────────

COUNTS = {'tokens_seen': 120, 'table_cells': 69, 'prose_judged': 22, 'unverified': 15,
          'delegated': 10, 'excluded': 4}


def _out(warnings=(), violations=(), skipped=False):
    if skipped:
        return json.dumps({'skipped': True})
    return json.dumps({'skipped': False, 'warnings': list(warnings), 'violations': list(violations),
                       'summary': 'number audit: …', 'counts': COUNTS}, ensure_ascii=False)


def test_number_result_ok():
    r = D.number_result(0, _out(), '', False)
    assert r['kind'] == 'ok' and r['counts']['table_cells'] == 69


def test_number_result_warning_is_not_ok():
    # 문장 층은 경고만 내고 exit 0 — 이걸 「일치」로 읽으면 안 된다(codex 설계 #1)
    r = D.number_result(0, _out(warnings=['경고(문장): S&P 4.37%']), '', False)
    assert r['kind'] == 'warn' and r['warnings'] == 1


def test_number_result_violation():
    r = D.number_result(1, _out(violations=['[채권] 2Y 4.478% ≠ 4.477%']), '', False)
    assert r['kind'] == 'violation' and r['violations'] == 1 and '2Y' in r['lines'][0]


def test_number_result_errors_are_unknown_not_ok():
    assert D.number_result(2, '', 'FATAL: 데이터 report_date 가 다르다', False)['kind'] == 'error'
    assert '다르다' in D.number_result(2, '', 'FATAL: 데이터 report_date 가 다르다', False)['reason']
    assert D.number_result(None, '', '', True)['kind'] == 'error'
    assert D.number_result(0, 'not json', '', False)['kind'] == 'error'
    assert D.number_result(1, _out(), '', False)['kind'] == 'error'     # 위반 없이 1 — 모순
    assert D.number_result(-9, '', '', False)['kind'] == 'error'


def test_number_result_skipped():
    assert D.number_result(0, _out(skipped=True), '', False)['kind'] == 'skipped'


def test_number_result_rejects_broken_contract():
    # codex 구현 검토 #6 — 계약이 깨진 응답은 정상이 아니다
    assert D.number_result(0, '{}', '', False)['kind'] == 'error'
    assert D.number_result(1, _out(skipped=True), '', False)['kind'] == 'error'
    bad = json.dumps({'skipped': False, 'warnings': 'x', 'violations': [], 'counts': COUNTS})
    assert D.number_result(0, bad, '', False)['kind'] == 'error'
    # 2차 #4 — 필수 수가 빠졌거나 항목 형식이 틀리면 정상이 아니다
    empty = json.dumps({'skipped': False, 'warnings': [], 'violations': [], 'counts': {}})
    assert D.number_result(0, empty, '', False)['kind'] == 'error'
    odd = json.dumps({'skipped': False, 'warnings': [1], 'violations': [], 'counts': COUNTS})
    assert D.number_result(0, odd, '', False)['kind'] == 'error'
    flag = dict(COUNTS, table_cells=True)
    assert D.number_result(0, json.dumps({'skipped': False, 'warnings': [], 'violations': [],
                                          'counts': flag}), '', False)['kind'] == 'error'


# ── 판단 한 줄 ────────────────────────────────────────────────────────────

def post(path='posts/2026-11-06.html', state='완료', findings=2, number=None, sha='s1'):
    return {'path': path, 'state': state, 'findings': findings, 'number': number,
            'auto': D.auto_reviewed(path), 'sha': sha}


def seen_line(p):
    return {'sha': p['sha'], 'text': D.block(p)}


def test_verdict_priority():
    ok = {'kind': 'ok', 'counts': COUNTS}
    assert D.verdict(post(number=ok)) == '검토 끝'
    assert D.verdict(post(number={'kind': 'warn', 'warnings': 1, 'counts': COUNTS})) == '확인 필요'
    assert D.verdict(post(number={'kind': 'error', 'reason': 'x'})) == '확인 필요'
    assert D.verdict(post(state='만료', number=ok)) == '확인 필요'
    assert D.verdict(post(state='판정 불가')) == '확인 필요'
    # 범위에만 넣고 읽지 않은 글(게이트 도입 전)은 정책상 검토하지 않는다 — 미해결로 쌓지 않고 따로 센다
    assert D.verdict(post(state='읽지 않음')) == '검토 안 함(범위 편입)'
    assert D.resolved(post(state='읽지 않음'))
    assert D.verdict(post(state='대기', number=ok)) == '검토 대기'
    assert D.verdict(post('news/2026-11-06.html', state='대기', findings=None)) == '사람이 읽어야 함'
    assert D.verdict(post('news/2026-11-06.html', state='완료', findings=1)) == '검토 끝'


def test_resolved():
    assert D.resolved(post())
    assert not D.resolved(post(state='대기'))
    assert not D.resolved(post(number={'kind': 'violation', 'violations': 1, 'counts': COUNTS}))


# ── 메시지 ───────────────────────────────────────────────────────────────

def test_block_text_is_plain_and_honest():
    text = D.block(post(number={'kind': 'warn', 'warnings': 2, 'violations': 0, 'counts': COUNTS,
                                 'lines': ['경고(문장): …']}))
    assert text.startswith('■ US 일간 11/06 — 확인 필요')
    assert '발행 뒤 재검사' in text and '경고 2' in text and '미검증 15' in text
    assert '지적 2건' in text
    assert '*' not in text and '_' not in text           # 마크다운 해석 없이 보낸다


def test_block_for_unchecked_section():
    text = D.block(post('kr/posts/2026-11-06.html', state='대기', findings=None))
    assert '숫자: 자동 검사 없음' in text and '검토 대기' in text


def test_render_reports_only_new_or_changed_and_counts_rest():
    a = post('posts/2026-11-06.html')
    b = post('kr/posts/2026-11-06.html', state='대기', findings=None)
    c = post('kr/posts/2026-11-05.html', state='만료', findings=None)
    prev = {c['path']: seen_line(c)}
    text, lines = D.render([a, b, c], prev, at(2026, 11, 9))
    assert 'US 일간 11/06' in text and 'KR 일간 11/06' in text
    assert '■ KR 일간 11/05' not in text                # 바뀌지 않았다
    assert '아직 안 끝난 글 2건' in text and 'KR 일간 11/05' in text
    assert set(lines) == {a['path'], b['path'], c['path']}
    assert D.CAVEAT in text


def test_render_without_changes_still_says_so():
    a = post()
    text, _ = D.render([a], {a['path']: seen_line(a)}, at(2026, 11, 9))
    assert '새로 나온 글이나 바뀐 상태가 없어요' in text


def test_render_reports_content_change_with_same_status():
    # codex 구현 검토 #2 — 상태 문장이 같아도 공개판 내용이 바뀌면 알린다
    a = post(sha='s1')
    b = post(sha='s2')
    text, lines = D.render([b], {a['path']: seen_line(a)}, at(2026, 11, 9))
    assert '(글 내용이 바뀜)' in text and lines[b['path']]['sha'] == 's2'


def test_render_keeps_lines_of_untracked_posts():
    # 따라가지 않는 글의 전달 기록을 지우면 다음 날 「처음 보는 글」로 되살아난다
    a = post()
    old = {'posts/2026-10-01.html': {'sha': 'z', 'text': None}}
    _, lines = D.render([a], old, at(2026, 11, 9))
    assert lines['posts/2026-10-01.html'] == {'sha': 'z', 'text': None}


def test_render_cut_posts_are_not_recorded():
    many = [post(f'posts/2026-11-0{d}.html', state='대기', findings=None,
                 number={'kind': 'violation', 'violations': 3, 'warnings': 0, 'counts': COUNTS,
                         'lines': ['가' * 300, '나' * 300]}) for d in range(1, 9)]
    many += [post(f'kr/posts/2026-11-0{d}.html', state='대기', findings=None,
                  number={'kind': 'violation', 'violations': 3, 'warnings': 0, 'counts': COUNTS,
                          'lines': ['가' * 300, '나' * 300]}) for d in range(1, 9)]
    text, lines = D.render(many, {}, at(2026, 11, 9))
    assert '외' in text and 0 < len(lines) < len(many)


def test_totals_count_only_the_window():
    # 2차 #5 — 「최근 7일」 합계에 창 밖의 미해결 글을 섞지 않는다
    old = post('posts/2026-10-01.html', number={'kind': 'violation', 'violations': 5, 'warnings': 0,
                                                 'counts': COUNTS})
    text, _ = D.render([post(), old], {}, at(2026, 11, 9))
    assert '최근 7일: 글 1편 · 숫자 위반 0' in text


def test_render_accepts_legacy_string_lines():
    a = post()
    text, _ = D.render([a], {a['path']: D.block(a)}, at(2026, 11, 9))
    assert 'US 일간 11/06' in text                      # sha 없는 옛 기록은 바뀐 것으로 본다


def test_render_fits_limit():
    many = [post(f'posts/2026-11-{d:02d}.html', state='대기', findings=None) for d in range(1, 9)]
    many += [post(f'kr/news/2026-11-{d:02d}.html', state='대기', findings=None) for d in range(1, 9)]
    for p in many:
        p['number'] = {'kind': 'violation', 'violations': 3, 'warnings': 0, 'counts': COUNTS,
                       'lines': ['가' * 300, '나' * 300, '다' * 300]}
    text, _ = D.render(many, {}, at(2026, 11, 9))
    assert len(text) <= D.LIMIT
    assert '외' in text


def test_render_notes_go_first():
    text, _ = D.render([post()], {}, at(2026, 11, 9), notes=['최신 판을 못 받았어요'])
    assert text.splitlines()[1].startswith('⚠ 최신 판을 못 받았어요')


def test_totals_line():
    ps = [post(number={'kind': 'violation', 'violations': 2, 'warnings': 1, 'counts': COUNTS}),
          post('kr/posts/2026-11-06.html', findings=5)]
    text, _ = D.render(ps, {}, at(2026, 11, 9))
    assert '최근 7일: 글 2편 · 숫자 위반 2 · 숫자 경고 1 · codex 지적 7건' in text


def test_totals_show_unchecked_and_unfinished():
    # codex 구현 검토 #5 — 못 본 것을 0건처럼 보이지 않게
    p = post(state='대기', findings=None, number={'kind': 'error', 'reason': 'x'})
    text, _ = D.render([p], {}, at(2026, 11, 9))
    assert '숫자 판정 불가 1' in text and '검토 미완료 1' in text


# ── 언제 보내나 ───────────────────────────────────────────────────────────

def test_due():
    assert not D.due(at(2026, 11, 9, 8, 59), {})
    assert D.due(at(2026, 11, 9, 9, 0), {})
    assert not D.due(at(2026, 11, 9, 23), {'last_sent_day': '2026-11-09'})
    assert D.due(at(2026, 11, 10, 9, 5), {'last_sent_day': '2026-11-09'})


# ── 기록 파일 ─────────────────────────────────────────────────────────────

def test_state_roundtrip_and_corrupt(tmp_path):
    p = str(tmp_path / 's' / 'state.json')
    assert D.load_state(p) == {}
    D.save_state(p, {'last_sent_day': '2026-11-09'})
    assert D.load_state(p)['last_sent_day'] == '2026-11-09'
    with open(p, 'w') as fh:
        fh.write('{broken')
    with pytest.raises(D.StateError):
        D.load_state(p)


def test_digest_note(tmp_path):
    p = str(tmp_path / 'state.json')
    assert '한 번도' in D.digest_note(p, at(2026, 11, 9))
    D.save_state(p, {'last_sent': at(2026, 11, 9).isoformat(), 'last_sent_day': '2026-11-09'})
    assert D.digest_note(p, at(2026, 11, 9, 20)) == ''
    assert '35시간' in D.digest_note(p, at(2026, 11, 10, 20))
    D.save_state(p, {'last_sent': at(2026, 11, 9).isoformat(), 'last_error': '전송 실패 HTTP 401'})
    assert '실패' in D.digest_note(p, at(2026, 11, 9, 10))
    with open(p, 'w') as fh:
        fh.write('{')
    assert '손상' in D.digest_note(p, at(2026, 11, 9))


# ── 텔레그램 ─────────────────────────────────────────────────────────────

class FakeRun:
    def __init__(self, curl_out='{"ok": true}', curl_code=0, keychain=('TOKEN123', '42')):
        self.curl_out, self.curl_code, self.keychain = curl_out, curl_code, keychain
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        if args[0] == 'security':
            val = self.keychain[0] if '-a' in args and args[args.index('-a') + 1] == 'token' \
                else self.keychain[1]
            code = 0 if val else 44
            return subprocess.CompletedProcess(args, code, (val or '') + '\n', '')
        return subprocess.CompletedProcess(args, self.curl_code, self.curl_out, '')


def test_send_keeps_token_out_of_argv():
    run = FakeRun()
    D.send_telegram('안녕', run=run)
    curl = [c for c in run.calls if c[0][0] == 'curl'][0]
    assert not any('TOKEN123' in a for a in curl[0])
    assert 'TOKEN123' in curl[1]['input']                 # 설정은 stdin 으로
    assert not any('42' in a for a in curl[0]) and 'chat_id=42' in curl[1]['input']
    assert 'text=안녕' in curl[0]


def test_send_failures_raise_without_token():
    with pytest.raises(D.SendError) as e:
        D.send_telegram('x', run=FakeRun(keychain=('', '42')))
    assert '열쇠고리' in str(e.value)
    with pytest.raises(D.SendError) as e:
        D.send_telegram('x', run=FakeRun(curl_out='{"ok": false, "description": "Unauthorized TOKEN123"}'))
    assert 'TOKEN123' not in str(e.value)
    with pytest.raises(D.SendError):
        D.send_telegram('x', run=FakeRun(curl_code=28, curl_out=''))


# ── 숫자 재검사: 발행 커밋의 글과 데이터로 ────────────────────────────────────

def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / 'work')
    subprocess.run(['git', 'init', '-q', '-b', 'main', root], check=True)
    git(root, 'config', 'user.email', 't@t')
    git(root, 'config', 'user.name', 't')
    return root


def write_commit(root, files, msg):
    for rel, text in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as fh:
            fh.write(text)
        git(root, 'add', rel)
    git(root, 'commit', '-q', '-m', msg)
    return git(root, 'rev-parse', 'HEAD')


FAKE_CHECKER = '''import json, os, sys
a = sys.argv
html = a[a.index('--html') + 1]
datadir = a[a.index('--datadir') + 1]
md = json.load(open(os.path.join(datadir, 'market_data.json')))
print(json.dumps({'skipped': False, 'warnings': [], 'violations': [] if md['v'] == 1 else ['bad'],
                  'summary': 'number audit: x', 'counts': {'table_cells': 1, 'prose_judged': 0,
                  'unverified': 0, 'delegated': 0, 'excluded': 0, 'tokens_seen': 1},
                  'name': os.path.basename(html)}))
sys.exit(0 if md['v'] == 1 else 1)
'''


def test_replay_uses_data_from_the_publish_commit(repo, tmp_path):
    first = write_commit(repo, {'posts/2026-11-06.html': '<p>1</p>',
                                'data/market_data.json': '{"v": 1}'}, 'publish')
    write_commit(repo, {'data/market_data.json': '{"v": 2}'}, 'next day data')
    checker = tmp_path / 'checker.py'
    checker.write_text(FAKE_CHECKER)
    sha = git(repo, 'rev-parse', 'HEAD:posts/2026-11-06.html')
    r = D.replay_numbers(repo, 'posts/2026-11-06.html', sha, str(checker),
                         commit_of=lambda root, path, s: first)
    assert r['kind'] == 'ok' and r['commit'] == first[:8]


def test_replay_without_commit_or_data_is_error(repo, tmp_path):
    write_commit(repo, {'posts/2026-11-06.html': '<p>1</p>'}, 'publish')
    checker = tmp_path / 'checker.py'
    checker.write_text(FAKE_CHECKER)
    sha = git(repo, 'rev-parse', 'HEAD:posts/2026-11-06.html')
    assert D.replay_numbers(repo, 'posts/2026-11-06.html', sha, str(checker),
                            commit_of=lambda *a: None)['kind'] == 'error'
    head = git(repo, 'rev-parse', 'HEAD')
    r = D.replay_numbers(repo, 'posts/2026-11-06.html', sha, str(checker),
                         commit_of=lambda *a: head)
    assert r['kind'] == 'error' and 'market_data' in r['reason']


def test_needs_replay():
    assert D.needs_replay('posts/2026-11-06.html')
    assert not D.needs_replay('kr/posts/2026-11-06.html')
    assert not D.needs_replay('posts/2026-09-30.html')     # 적용일 전
    assert not D.needs_replay('news/2026-11-06.html')


def test_cli_dry_run_smoke(tmp_path):
    # 실제 레포를 읽는다 — 전송·알림 기록 없음. 단 만료 판정이 reviews/seen.json(미추적)을 갱신한다:
    # 세션 시작 훅(`pending --hook`)과 같은 부수 효과라 받아들인다.
    scripts = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, VERIFY_DIGEST_STATE=str(tmp_path / 'st.json'))
    r = subprocess.run([sys.executable, os.path.join(scripts, 'verify_digest.py'), '--dry-run',
                        '--no-fetch', '--no-replay'], capture_output=True, text=True, env=env,
                       cwd=os.path.dirname(scripts), timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.startswith('[검증 알림]')
    assert not os.path.exists(tmp_path / 'st.json')


def test_replay_falls_back_to_that_days_data(repo, tmp_path):
    # 글을 나중에 다시 그린 커밋(발행 커밋)엔 다음 날 데이터가 있다 — 그 날 판 데이터로 맞춘다
    day = write_commit(repo, {'data/market_data.json': '{"v": 1, "report_date": "2026-11-02"}'}, 'd1')
    later = write_commit(repo, {'posts/2026-11-02.html': '<p>1</p>',
                                'data/market_data.json': '{"v": 2, "report_date": "2026-11-04"}'},
                         'redraw')
    checker = tmp_path / 'checker.py'
    checker.write_text(FAKE_CHECKER)
    sha = git(repo, 'rev-parse', 'HEAD:posts/2026-11-02.html')
    r = D.replay_numbers(repo, 'posts/2026-11-02.html', sha, str(checker),
                         commit_of=lambda *a: later)
    assert r['kind'] == 'ok' and r['commit'] == later[:8] and r['data_commit'] == day[:8]


def test_replay_without_that_days_data_is_error(repo, tmp_path):
    later = write_commit(repo, {'posts/2026-11-02.html': '<p>1</p>',
                                'data/market_data.json': '{"v": 1, "report_date": "2026-11-04"}'}, 'p')
    checker = tmp_path / 'checker.py'
    checker.write_text(FAKE_CHECKER)
    sha = git(repo, 'rev-parse', 'HEAD:posts/2026-11-02.html')
    r = D.replay_numbers(repo, 'posts/2026-11-02.html', sha, str(checker),
                         commit_of=lambda *a: later)
    assert r['kind'] == 'error' and '그 날' in r['reason']


def test_block_marks_other_day_data():
    # codex 구현 검토 #3 — 다른 커밋의 그 날 데이터로 맞춘 것을 숨기지 않는다
    n = {'kind': 'ok', 'warnings': 0, 'violations': 0, 'counts': COUNTS, 'lines': [],
         'commit': 'aaaa1111', 'data_commit': 'bbbb2222'}
    n['checker'] = 'cccc3333'
    t = D.block(post(number=n))
    assert '발행 때 쓴 데이터인지 확인 불가' in t and '데이터 bbbb2222 · 검사기 cccc3333' in t and '추정' in t
    n['data_commit'] = 'aaaa1111'
    assert '수집판' not in D.block(post(number=n))


def test_review_line_shows_draft():
    p = post('weekly/2026-W45.html', state='대기', findings=None)
    p['draft'] = True
    assert '초안 나옴 — 사람이 확인해야 해요' in D.block(p)
    q = post('posts/2026-11-06.html', state='대기', findings=None)
    q['draft'] = True
    assert '초안 나옴 — Claude 확인·정정 대기' in D.block(q)


# ── CLI 전송 경로: 성공하면 기록, 실패하면 오류만 기록, 오늘 보냈으면 안 보낸다 ──────────────

@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    import verify_digest as V
    st = str(tmp_path / 'st' / 'state.json')
    monkeypatch.setenv(D.STATE_ENV, st)
    monkeypatch.setattr(D, 'now_kst', lambda: at(2026, 11, 9, 9, 20))
    monkeypatch.setattr(V, 'build', lambda state, now, args, notes: ([post()], {}, {'posts/2026-11-06.html': 's1'}))
    sent = []
    monkeypatch.setattr(D, 'send_telegram', lambda text: sent.append(text))
    return V, st, sent


def test_cli_send_records_state(cli_env):
    V, st, sent = cli_env
    assert V.main([]) == 0 and len(sent) == 1
    s = D.load_state(st)
    assert s['last_sent_day'] == '2026-11-09' and s['last_error'] is None
    assert 'posts/2026-11-06.html' in s['lines']
    assert V.main([]) == 0 and len(sent) == 1          # 오늘은 이미 보냈다


def test_cli_send_failure_keeps_day_open(cli_env, monkeypatch):
    V, st, sent = cli_env

    def boom(text):
        raise D.SendError('텔레그램이 거절했어요: Unauthorized')
    monkeypatch.setattr(D, 'send_telegram', boom)
    assert V.main([]) == 1
    s = D.load_state(st)
    assert 'last_sent_day' not in s and 'Unauthorized' in s['last_error']
    monkeypatch.setattr(D, 'send_telegram', lambda text: sent.append(text))
    assert V.main([]) == 0 and len(sent) == 1          # 다음 tick 에 다시 간다
    assert D.load_state(st)['last_error'] is None


def test_cli_unexpected_error_is_recorded(cli_env, monkeypatch):
    V, st, sent = cli_env

    def boom(state, now, args, notes):
        raise subprocess.TimeoutExpired(['git'], 60)
    monkeypatch.setattr(V, 'build', boom)
    assert V.main([]) == 1
    assert 'TimeoutExpired' in D.load_state(st)['last_error']


def test_cli_next_success_mentions_last_failure(cli_env):
    V, st, sent = cli_env
    D.save_state(st, {'last_error': '텔레그램이 거절했어요: x', 'last_attempt': at(2026, 11, 8, 10).isoformat()})
    assert V.main([]) == 0
    assert '지난번 알림이 실패했어요' in sent[0]


def test_cli_records_lines_and_open(cli_env, monkeypatch):
    V, st, sent = cli_env
    ps = [post(), post('kr/posts/2026-11-06.html', state='대기', findings=None)]
    monkeypatch.setattr(V, 'build', lambda state, now, args, notes: (ps, {}, {p['path']: p['sha'] for p in ps}))
    assert V.main([]) == 0
    s = D.load_state(st)
    assert s['lines']['posts/2026-11-06.html']['sha'] == 's1'
    assert s['open'] == ['kr/posts/2026-11-06.html']
    assert s['tracked'] == {p['path']: p['sha'] for p in ps}


def test_cli_lock_failure_is_recorded(cli_env, monkeypatch):
    V, st, sent = cli_env
    import fcntl

    def bad(fd, op):
        raise OSError(5, 'Input/output error')
    monkeypatch.setattr(fcntl, 'flock', bad)
    assert V.main([]) == 1
    assert '잠금' in D.load_state(st)['last_error']


def test_cli_contention_skips_quietly(cli_env, monkeypatch):
    V, st, sent = cli_env
    import fcntl

    def busy(fd, op):
        raise BlockingIOError(35, 'Resource temporarily unavailable')
    monkeypatch.setattr(fcntl, 'flock', busy)
    assert V.main([]) == 0 and sent == []


def test_cli_corrupt_state_is_moved_and_announced(cli_env):
    V, st, sent = cli_env
    os.makedirs(os.path.dirname(st))
    with open(st, 'w') as fh:
        fh.write('{')
    assert V.main([]) == 0
    assert '기록 파일이 손상돼' in sent[0]
    assert any(n.startswith('state.json.corrupt-') for n in os.listdir(os.path.dirname(st)))


def test_cli_not_due_before_nine(cli_env, monkeypatch):
    V, st, sent = cli_env
    monkeypatch.setattr(D, 'now_kst', lambda: at(2026, 11, 9, 8, 20))
    assert V.main([]) == 0 and sent == [] and not os.path.exists(st)


def test_render_puts_recent_first_when_cut():
    old = [post(f'kr/posts/2026-09-{d:02d}.html', state='만료', findings=None,
                number={'kind': 'violation', 'violations': 1, 'warnings': 0, 'counts': COUNTS,
                        'lines': ['가' * 300]}) for d in range(1, 29)]
    new = post('posts/2026-11-06.html')
    text, _ = D.render(old + [new], {}, at(2026, 11, 9))
    assert '외' in text and 'US 일간 11/06 — 검토 끝' in text


def test_unread_count_in_footer():
    text, _ = D.render([post(state='읽지 않음', findings=None), post('kr/posts/2026-11-06.html')], {},
                       at(2026, 11, 9))
    assert '읽지 않고 범위에 넣은 글 1편(90일 안' in text and '아직 안 끝난 글' not in text


# ── 2단계: 발행 전 기록 줄(2026-11-08) ─────────────────────────────────────

def _post(path, **kw):
    p = {'path': path, 'sha': 's', 'state': '완료', 'findings': 0, 'number': None, 'auto': True, 'draft': False}
    p.update(kw)
    return p


def test_target_post_separates_prepub_and_recheck(tmp_path):
    from review import prepub_view as V
    from review.tests import prepub_fixture as F
    repo = F.init(tmp_path)
    F.publish(repo, 'kr', '2026-11-09', workspace=False)
    p = _post('kr/posts/2026-11-09.html', prepub=V.view(str(repo), 'HEAD', 'kr', '2026-11-09'))
    text = D.block(p)
    assert '[발행 전 기록] 발행 전 기록 일치' in text
    assert '[발행 뒤 재검사] 숫자: 자동 재검사 없음(US 일간만 해요)' in text


def test_old_post_block_unchanged():
    # 대상이 아닌 글의 문장이 바뀌면 다음 요약에서 90일치가 「바뀜」으로 다시 온다
    p = _post('posts/2026-11-06.html')
    assert D.block(p).splitlines()[1] == ' · 숫자: 자동 검사 없음'


def test_prepub_read_error_line():
    p = _post('posts/2026-11-09.html', prepub={'error': 'fatal: bad object'})
    assert '[발행 전 기록] 읽지 못했어요' in D.block(p)


def test_publish_watch_tail_is_shown():
    text, _ = D.render([], {}, at(2026, 11, 10), extra_tail=['아직 안 올라온 세션: KR 일간 11/09'])
    assert '아직 안 올라온 세션: KR 일간 11/09' in text


def test_prepub_error_keeps_number_line():
    # codex 구현 검토 #11 — 기록 조회 오류가 숫자 재검사 결과를 가리지 않는다
    num = {'kind': 'violation', 'violations': 2, 'warnings': 0,
           'counts': {'table_cells': 10, 'prose_judged': 3, 'unverified': 5}}
    text = D.block(_post('posts/2026-11-09.html', prepub={'error': 'x'}, number=num))
    assert '[발행 전 기록] 읽지 못했어요' in text and '[발행 뒤 재검사] 숫자: 표 칸 10' in text and '위반 2' in text


def test_digest_survives_stage2_import_failure(monkeypatch):
    import sys as _sys
    import verify_digest as VD
    import review
    monkeypatch.setitem(_sys.modules, 'review.prepub_view', None)
    monkeypatch.delattr(review, 'prepub_view', raising=False)
    assert VD._prepub_target('posts/2026-11-09.html') == ('?', '2026-11-09')
    assert VD._prepub_target('posts/2026-11-06.html') is None
