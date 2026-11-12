"""매일 검증 알림(`review.digest`, CLI `scripts/verify_digest.py`) — 2026-11-08.

알림이 거짓말을 하는 자리를 막는다: 경고를 「이상 없음」으로 읽기, 늦게 끝난 검토 놓치기,
원장에 이름만 있는 글을 「검토 끝」으로 세기, 같은 내용 매일 반복, 4,000자 넘김.
"""
import json
import os
import re
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


def _many(n=3):
    # 원문 줄을 싣지 않게 된 뒤(2.5단계)로는 글 수로 한도를 넘긴다
    out = []
    for m in (9, 10, 11)[-n:]:
        for sec in ('posts', 'kr/posts'):
            out += [post(f'{sec}/2026-{m:02d}-{d:02d}.html', state='대기', findings=None,
                         number={'kind': 'violation', 'violations': 3, 'warnings': 0, 'counts': COUNTS, 'lines': [], 'kinds': {'위반': 3}})
                    for d in range(1, 9 if m == 11 else 29)]
    return out


def test_render_cut_posts_are_not_recorded():
    many = _many()
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
    many = _many()
    text, _ = D.render(many, {}, at(2026, 11, 9))
    assert len(text) <= D.LIMIT
    assert '외' in text


def test_render_notes_go_first():
    text, _ = D.render([post()], {}, at(2026, 11, 9), notes=[D.NOTE_STALE])
    assert text.splitlines()[1].startswith('⚠ 최신 판을 못 받았어요')


def test_totals_line():
    ps = [post(number={'kind': 'violation', 'violations': 2, 'warnings': 1, 'counts': COUNTS}),
          post('kr/posts/2026-11-06.html', findings=5)]
    text, _ = D.render(ps, {}, at(2026, 11, 9))
    assert '최근 7일: 글 2편 · 숫자 위반 2·경고 1(US 일간 자동 검사 범위 안) · codex 지적 7건(사실 오류로 확인된 수 아님)' in text


def test_totals_show_unchecked_and_unfinished():
    # codex 구현 검토 #5 — 못 본 것을 0건처럼 보이지 않게
    p = post(state='대기', findings=None, number={'kind': 'error', 'reason': 'x'})
    text, _ = D.render([p], {}, at(2026, 11, 9))
    assert '숫자 판정 불가 1' in text and '검토 미완료 1' in text


# ── 언제 보내나 ───────────────────────────────────────────────────────────

def test_due():
    assert not D.due(at(2026, 11, 9, 8, 59), {})
    assert D.due(at(2026, 11, 9, 9, 0), {})
    assert not D.due(at(2026, 11, 9, 23), {'last_submitted_day': '2026-11-09'})
    assert D.due(at(2026, 11, 10, 9, 5), {'last_submitted_day': '2026-11-09'})
    # 옛 이름은 첫 실행 때 옮긴다(설계 v7 #3) — 옮기기 전에는 판정에 쓰지 않는다
    assert not D.due(at(2026, 11, 9, 23), D.migrate({'last_sent_day': '2026-11-09'}))


# ── 기록 파일 ─────────────────────────────────────────────────────────────

def test_state_roundtrip_and_corrupt(tmp_path):
    p = str(tmp_path / 's' / 'state.json')
    assert D.load_state(p) == {}
    D.save_state(p, {'last_submitted_day': '2026-11-09'})
    assert D.load_state(p)['last_submitted_day'] == '2026-11-09'
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
    D.save_state(p, {'last_sent': at(2026, 11, 9).isoformat(), 'last_error': '/Users/x 전송 실패 HTTP 401'})
    note = D.digest_note(p, at(2026, 11, 9, 10))
    assert '실패 — 기타 오류' in note and '/Users/' not in note       # 옛 원문 사유는 종류로만
    D.save_state(p, {'last_sent': at(2026, 11, 9).isoformat(), 'last_error': '접수 오류'})
    assert '실패 — 접수 오류' in D.digest_note(p, at(2026, 11, 9, 10))
    # Worker 가 준 전송 시각(JS 의 Z·밀리초)을 그대로 저장해도 경과 시간이 나온다(설계 v9 #3)
    D.save_state(p, {'last_sent': '2026-11-09T00:00:00.123Z'})
    assert D.digest_note(p, at(2026, 11, 9, 20)) == ''
    assert '34시간' in D.digest_note(p, at(2026, 11, 10, 20))
    # 접수됐지만 24시간 넘게 전송 확인이 없다
    u = {'id': '2026-11-09:morning-digest:v1', 'date': '2026-11-09', 'v': 1, 'base': {},
         'accepted_at': at(2026, 11, 9, 9, 20).isoformat()}
    D.save_state(p, {'last_sent': at(2026, 11, 9).isoformat(), 'unconfirmed': [u]})
    assert D.digest_note(p, at(2026, 11, 9, 20)) == ''
    assert '24시간 넘게 전송 확인' in D.digest_note(p, at(2026, 11, 10, 10))
    D.save_state(p, {'unconfirmed': [u]})
    assert D.digest_note(p, at(2026, 11, 9, 20)) == ''
    with open(p, 'w') as fh:
        fh.write('{')
    assert '손상' in D.digest_note(p, at(2026, 11, 9))


# ── Worker 제출(2.5단계): 맥에는 텔레그램 토큰을 읽는 코드가 없다 ───────────────────

KEY = 'Kq7' + 'x' * 40
URL = 'https://alerts.example.test'
SID = '2026-11-09:morning-digest:v1'


class FakeWorker:
    """`security`·`curl` 을 흉내 낸다 — 시험은 실제 열쇠고리·네트워크를 부르지 않는다. 계약 §3 그대로."""

    def __init__(self, key=KEY, url=URL):
        self.key, self.url = key, url
        self.events, self.posts, self.calls, self.script = {}, [], [], []
        self.health = {'last_outbox_ok': at(2026, 11, 9, 9).isoformat(), 'last_outbox_read': None,
                       'backlog': 0, 'failed': 0}
        self.hook, self.status_down = None, False
        self.health_calls, self.no_hash, self.status_code = [], False, None
        self.health_out = {'format': 'alerts-health/1', 'ok': True, 'config_error': False,
                           'last_outbox_ok': None, 'backlog': 0}

    @staticmethod
    def _hash(body):                                          # 접수한 본문(text)의 sha256 — 계약 §3
        try:
            body = json.loads(body)['text']
        except (ValueError, TypeError, KeyError):
            pass
        return D.text_hash(body)

    def _out(self, args, code, text):
        return subprocess.CompletedProcess(args, 0, (text + '\n' + str(code)).encode(), b'')

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        if args[0] == 'security':
            assert args[args.index('-s') + 1] == 'fdo2a-alerts'
            val = {'digest_key': self.key, 'worker_url': self.url}[args[args.index('-a') + 1]]
            return subprocess.CompletedProcess(args, 0 if val else 44, (val or '') + '\n', '')
        assert args[0] == 'curl'
        conf = kw['input'].decode('utf-8')
        url = re.search(r'^url = "(.*)"$', conf, re.M).group(1)
        m = re.search(r'^data-binary = "(.*)"$', conf, re.M)
        if self.hook:
            self.hook()
        if url.endswith('/health'):                           # 공개 주소 — 키 없이
            self.health_calls.append(conf)
            if self.health_out is None:
                return subprocess.CompletedProcess(args, 28, b'', b'timeout')
            return self._out(args, 200, self.health_out if isinstance(self.health_out, str)
                             else json.dumps(self.health_out))
        assert f'header = "Authorization: Bearer {self.key}"' in conf
        if not m:                                             # GET /status
            if self.status_down:
                return subprocess.CompletedProcess(args, 28, b'', b'timeout')
            if self.status_code:
                return self._out(args, self.status_code, '')
            sid = url.split('?id=')[1] if '?id=' in url else None
            evs = [dict({'id': k, 'date': k[:10], 'state': e['state']},
                        **({'sent_at': e['sent_at']} if e['state'] == 'sent' else {}),
                        **({} if self.no_hash else {'hash': self._hash(e['body'])}))
                   for k, e in sorted(self.events.items()) if sid in (None, k)]
            return self._out(args, 200, json.dumps({'format': 'digest-status/1', 'events': evs,
                                                    'health': self.health}))
        body = re.sub(r'\\(.)', r'\1', m.group(1))
        self.posts.append(body)
        step = self.script.pop(0) if self.script else None
        if step == 'drop':                                    # 요청이 닿지 않았다
            return subprocess.CompletedProcess(args, 28, b'', b'timeout')
        if isinstance(step, tuple):
            return self._out(args, *step)
        sid = json.loads(body)['id']
        if sid in self.events:
            code = 200 if self.events[sid]['body'] == body else 409
        else:
            self.events[sid] = {'body': body, 'state': 'accepted'}
            code = 202
        if step == 'lost':                                    # 접수는 됐는데 응답이 끊겼다
            return subprocess.CompletedProcess(args, 56, b'', b'recv failure')
        return self._out(args, code, json.dumps({'id': sid, 'state': self.events[sid]['state']}))

    def send(self, sid, when):
        self.events[sid].update(state='sent', sent_at=when)

    def curls(self):
        return [c for c in self.calls if c[0][0] == 'curl']


def _pending(text='요약', day='2026-11-09', v=1, base=None):
    return {'id': f'{day}:morning-digest:v{v}', 'date': day, 'v': v, 'text': text,
            'base': base if base is not None else {'lines': {}}, 'tries': []}


def test_no_telegram_token_code_path_remains():
    # 맥에서 텔레그램 토큰을 읽을 방법이 없어야 한다(설계 2.5 §4) — 직접 전송·대화 번호 설정 코드까지
    scripts = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel in ('review/digest.py', 'verify_digest.py'):
        with open(os.path.join(scripts, rel), encoding='utf-8') as fh:
            src = fh.read()
        for banned in ('fdo2a-telegram', 'sendMessage', 'api.telegram.org', 'getUpdates', 'setup_chat',
                       'setup-chat', 'send_telegram', 'TELEGRAM_BOT_TOKEN', "'token'", "'chat'"):
            assert banned not in src, (rel, banned)
    assert D.SERVICE == 'fdo2a-alerts'


def test_submit_keeps_key_and_body_out_of_argv(capsys):
    w = FakeWorker()
    body = D.request_body(_pending('본문 "따옴표" \\ 역슬래시\n둘째 줄'))
    assert D.post_digest(body, SID, run=w) == 'accepted'
    assert D.fetch_status(SID, run=w)['events'][SID]['state'] == 'accepted'
    for args, kw in w.calls:
        assert not any(KEY in a for a in args)                # 프로세스 목록에 안 남는다
    for args, kw in w.curls():
        assert not any('example.test' in a or '본문' in a for a in args)   # 주소·본문도 설정 stdin 으로
        assert args[-2:] == ['-K', '-'] and '--proto' in args
        assert KEY in kw['input'].decode('utf-8')
    assert w.posts == [body]                                  # 이스케이프를 거쳐도 같은 바이트
    out = capsys.readouterr()
    assert KEY not in out.out + out.err


def test_bad_keychain_values_never_reach_curl():
    for kw in ({'key': ''}, {'key': 'short'}, {'key': 'a' * 40 + '"\nurl = "https://evil.test'},
               {'url': 'http://alerts.example.test'}, {'url': 'https://a.test/x?k=1'}, {'url': ''}):
        w = FakeWorker(**kw)
        with pytest.raises(D.ConfigError) as e:
            D.post_digest('{}', SID, run=w)
        assert not w.curls() and KEY not in str(e.value)
        with pytest.raises(D.ConfigError):
            D.fetch_status(run=w)


def test_classify_responses():
    ok = json.dumps({'id': SID, 'state': 'accepted'})
    assert D.classify(202, ok, SID) == 'accepted'
    assert D.classify(200, json.dumps({'id': SID, 'state': 'sent'}), SID) == 'dup'
    assert D.classify(409, '{}', SID) == 'conflict'
    assert D.classify(400, '', SID) == 'rejected' and D.classify(401, '', SID) == 'rejected'
    assert D.classify(500, '', SID) == 'server' and D.classify(503, '', SID) == 'server'
    assert D.classify(None, '', SID) == 'noresp'
    # 약속에 없는 응답은 접수도 거절도 아니다 — 확인 불가 쪽
    for code in (403, 404, 413, 429, 302):
        assert D.classify(code, '', SID) == 'server'
    assert D.classify(200, '<html>login</html>', SID) == 'server'          # 중간 장비의 200
    assert D.classify(202, json.dumps({'id': 'other', 'state': 'accepted'}), SID) == 'server'
    assert D.classify(202, json.dumps({'id': SID, 'state': '???'}), SID) == 'server'


def test_transport_failures():
    w = FakeWorker()
    w.script = ['drop']
    assert D.post_digest('{"id":"x"}', SID, run=w) == 'noresp'
    w.status_down = True
    with pytest.raises(D.TransportError):
        D.fetch_status(run=w)

    def boom(args, **kw):
        if args[0] == 'curl':
            raise subprocess.TimeoutExpired(args, 60)
        return w(args, **kw)
    assert D.post_digest('{}', SID, run=boom) == 'noresp'


def test_request_fits_sixteen_kb_with_real_korean_text():
    p = _pending('가' * D.LIMIT)
    assert len(D.request_body(p).encode('utf-8')) <= D.MAX_BODY <= 16 * 1024
    assert json.loads(D.request_body(p)) == {'format': 'digest-submit/1', 'id': p['id'], 'date': p['date'],
                                             'kind': 'morning-digest', 'text': p['text']}


def test_compose_defers_posts_until_request_fits(monkeypatch):
    many = _many()
    full = D.compose(many, {}, at(2026, 11, 9), [], [], {}, {}, {})
    assert full['id'] == SID and len(full['text']) <= D.LIMIT
    monkeypatch.setattr(D, 'MAX_BODY', 6000)
    small = D.compose(many, {}, at(2026, 11, 9), [], [], {}, {}, {})
    assert len(D.request_body(small).encode('utf-8')) <= 6000
    assert 0 < len(small['base']['lines']) < len(full['base']['lines'])     # 더 미뤘다 — 줄 중간에서 자르지 않는다
    assert not small['text'].endswith('…') and '다음 알림에 이어서' in small['text']
    monkeypatch.setattr(D, 'MAX_BODY', 100)
    with pytest.raises(D.SizeError):
        D.compose(many, {}, at(2026, 11, 9), [], [], {}, {}, {})


# ── 제출 상태: pending → 접수 → 전송 확인 뒤에만 기준 전진 ───────────────────────────

def _attempt(state, now, w, saved=None):
    return D.attempt(state, now, (saved.append if saved is not None else lambda s: None),
                     lambda body, sid: D.post_digest(body, sid, run=w))


def test_try_is_recorded_before_the_request_leaves():
    w, snaps = FakeWorker(), []
    st = {'pending': _pending()}
    w.hook = lambda: snaps.append(json.loads(json.dumps(st)))
    saved = []
    assert _attempt(st, at(2026, 11, 9, 9, 20), w, saved) == 'accepted'
    # 보내는 순간의 상태: 본문이 고정돼 있고, 시도가 「응답 없음」으로 미리 적혀 있다(v9 #1)
    assert snaps[0]['pending']['text'] == '요약' and snaps[0]['pending']['tries'][0]['result'] == 'noresp'
    assert len(saved) == 2
    assert 'pending' not in st and st['last_submitted_day'] == '2026-11-09'
    assert st['unconfirmed'][0]['id'] == SID and 'text' not in st['unconfirmed'][0]
    assert 'lines' not in st                                   # 접수만으로는 기준이 전진하지 않는다


def test_retry_sends_the_identical_body():
    w = FakeWorker()
    w.script = ['drop', (503, ''), 'lost']
    st = {'pending': _pending('가\n"나"')}
    for i, want in enumerate(('noresp', 'server', 'noresp', 'dup')):
        assert _attempt(st, at(2026, 11, 9, 10 + i), w) == want
        if want != 'dup':
            assert st['pending']['tries'][-1]['result'] == want and st['last_error'] == '연결 오류'
    assert len(set(w.posts)) == 1 and len(w.posts) == 4        # 다시 만들지 않는다 → 409 없음
    assert 'pending' not in st and st['last_error'] is None


def test_rejected_and_conflict_are_recorded():
    w = FakeWorker()
    w.script = [(401, ''), (400, '')]
    st = {'pending': _pending()}
    # 401 = 키가 Worker 와 다르다 — 시도 기록에는 rejected, 따로 「제출 키 오류」로 남는다(codex 구현 1회 #2)
    assert _attempt(st, at(2026, 11, 9, 10), w) == 'rejected' and st['last_error'] == '제출 키 오류'
    assert st['auth_error'] == at(2026, 11, 9, 10).isoformat()
    assert _attempt(st, at(2026, 11, 9, 11), w) == 'rejected' and st['last_error'] == '접수 오류'
    assert 'auth_error' not in st                               # 400 은 키를 받아들였다는 뜻이다
    w.events[SID] = {'body': '다른 본문', 'state': 'sent', 'sent_at': at(2026, 11, 9, 9).isoformat()}
    assert _attempt(st, at(2026, 11, 9, 12), w) == 'conflict' and st['last_error'] == '충돌'
    assert [t['result'] for t in st['pending']['tries']] == ['rejected', 'rejected', 'conflict']


def test_missing_key_is_not_counted_as_a_try():
    w = FakeWorker(key='')
    st = {'pending': _pending()}
    with pytest.raises(D.ConfigError):
        _attempt(st, at(2026, 11, 9, 10), w)
    assert st['pending']['tries'] == [] and st['last_error'] == '제출 키 없음'


def _unc(day, v=1, **base):
    return {'id': f'{day}:morning-digest:v{v}', 'date': day, 'v': v, 'base': base,
            'accepted_at': f'{day}T09:20:00+09:00', 'hash': D.text_hash(f'{day} v{v} 본문')}


def _ev(u, state='sent', sent_at='2026-11-09T00:21:03.512Z'):
    e = {'id': u['id'], 'date': u['date'], 'state': state, 'hash': u['hash']}
    if state == 'sent':
        e['sent_at'] = sent_at
    return e


def test_confirm_applies_base_only_when_sent():
    u = _unc('2026-11-09', lines={'a': {'sha': '1', 'text': 't'}}, open=['a'], tracked={'a': '1'},
             all=['a'], numbers={})
    st = {'unconfirmed': [u], 'lines': {}, 'last_error': '연결 오류'}
    for state in ('accepted', 'queued', 'sending'):
        assert not D.confirm(st, {u['id']: _ev(u, state)}, at(2026, 11, 9, 10))
        assert st['lines'] == {} and len(st['unconfirmed']) == 1
    assert not D.confirm(st, {}, at(2026, 11, 9, 10))           # 아직 목록에 없다 — 기다린다
    assert D.confirm(st, {u['id']: _ev(u)}, at(2026, 11, 9, 11))
    assert st['lines'] == u['base']['lines'] and st['open'] == ['a'] and st['unconfirmed'] == []
    assert st['applied'] == ['2026-11-09', 1] and st['last_error'] is None
    assert st['last_sent'] == '2026-11-09T00:21:03.512Z'        # Worker 가 준 시각 그대로(v9 #3)


def test_confirm_is_monotonic_by_date_and_version():
    old, v2, v1 = _unc('2026-11-08', lines={'old': {}}), _unc('2026-11-09', 2, lines={'v2': {}}), \
        _unc('2026-11-09', 1, lines={'v1': {}})
    st = {'unconfirmed': [v2], 'lines': {}}
    D.confirm(st, {v2['id']: _ev(v2, sent_at='2026-11-09T10:00:00+09:00')}, at(2026, 11, 9, 11))
    assert st['lines'] == {'v2': {}}
    # 늦게 확인된 옛 요약·같은 날 v1 이 새 기준을 덮지 않는다(v8 #2·v9 #2)
    st['unconfirmed'] = [v1, old]
    D.confirm(st, {v1['id']: _ev(v1, sent_at='2026-11-09T09:30:00+09:00'),
                   old['id']: _ev(old, sent_at='2026-11-08T09:30:00+09:00')}, at(2026, 11, 9, 12))
    assert st['lines'] == {'v2': {}} and st['applied'] == ['2026-11-09', 2] and st['unconfirmed'] == []
    assert st['last_sent'] == '2026-11-09T10:00:00+09:00'       # 전송 시각도 뒤로 가지 않는다
    # 여럿이면 날짜 순으로
    st = {'unconfirmed': [_unc('2026-11-10', lines={'new': {}}), old], 'lines': {}}
    D.confirm(st, {old['id']: _ev(old), '2026-11-10:morning-digest:v1': _ev(_unc('2026-11-10'))},
              at(2026, 11, 10, 12))
    assert st['lines'] == {'new': {}} and st['applied'] == ['2026-11-10', 1]


def test_confirm_failed_send_drops_without_applying():
    u = _unc('2026-11-09', lines={'a': {}})
    for state, kind in (('failed_permanent', '전송 오류'), ('held', '전송 보류')):
        st = {'unconfirmed': [dict(u)], 'lines': {}}
        assert D.confirm(st, {u['id']: _ev(u, state)}, at(2026, 11, 10, 9))
        assert st['lines'] == {} and st['unconfirmed'] == [] and st['last_error'] == kind
    st = {'unconfirmed': [dict(u)], 'lines': {}}                # Worker 가 더는 돌려주지 않는 옛 사건
    assert D.confirm(st, {}, at(2026, 11, 30, 9)) and st['last_error'] == '확인 불가' and st['lines'] == {}
    st = {'unconfirmed': [dict(u)]}                             # 시각이 계약과 다르면 확인한 시각으로
    D.confirm(st, {u['id']: _ev(u, sent_at='어제쯤')}, at(2026, 11, 10, 9))
    assert st['last_sent'] == at(2026, 11, 10, 9).isoformat()


def _tried(*results, day='2026-11-09'):
    p = _pending(day=day)
    p['tries'] = [{'at': 'x', 'result': r} for r in results]
    return p


def _none(sid):
    return None


def _down(sid):
    raise D.TransportError('응답 없음')


def test_expiry_outcomes():
    now = at(2026, 11, 10, 9, 20)
    # 모든 시도가 400·401 → 접수 실패(조회가 실패해도 서버가 매번 안 받았다고 말했다)
    for lookup in (_none, _down):
        st = {'pending': _tried('rejected', 'rejected')}
        assert D.settle(st, now, lookup, True) == 'failed' and 'pending' not in st
        assert D.carry_lines(st, now.date()) == ['어제 요약 접수 실패(제출 시도 2번: 거절 2)']       # 3a §G — 시도 내역이 붙는다
    # 5xx·무응답이 하나라도 → 확인 불가(v9 #1·v10 #1)
    for tries in (('rejected', 'server'), ('noresp',), ('rejected', 'noresp', 'rejected')):
        st = {'pending': _tried(*tries)}
        assert D.settle(st, now, _none, True) == 'unknown'
        assert D.carry_lines(st, now.date())[0].startswith('어제 요약 접수 여부 확인 불가(제출 시도 ')
    # 조회가 「접수 이후」로 돌려주면 접수로 기록 — 안내 없음, 전송 확인을 기다린다
    st = {'pending': _tried('noresp')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'queued', 'hash': D.text_hash('요약')}, True) == 'accepted'
    assert st['unconfirmed'][0]['id'] == SID and not st.get('carry') and st['last_submitted_day'] == '2026-11-09'
    assert D.due(now, st)                                       # 오늘 치는 따로 낸다
    # 409(v11): 사건이 있으면 「접수됨 — 다른 본문」, 기준은 적용하지 않는다. 조회 실패·없음이면 확인 불가
    st = {'pending': _tried('conflict')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent', 'hash': D.text_hash('다른 본문')}, True) == 'conflict'
    assert not st.get('unconfirmed') and st['last_submitted_day'] == '2026-11-09'
    assert D.carry_lines(st, now.date()) == ['어제 요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요']
    for lookup in (_none, _down):
        st = {'pending': _tried('rejected', 'conflict')}
        assert D.settle(st, now, lookup, True) == 'unknown'
    # 시도가 하나도 없다 = 열쇠고리에서 막혀 요청이 나간 적이 없다(시도는 보내기 전에 적는다) → 접수 실패
    st = {'pending': _tried()}
    assert D.settle(st, now, _none, True) == 'failed'
    # 기한 전에는 버리지 않는다
    st = {'pending': _tried('noresp')}
    assert D.settle(st, now, _down, False) is None and 'pending' in st
    # 더 오래된 날짜는 날짜로 적는다
    st = {'pending': _tried('noresp', day='2026-11-06')}
    D.settle(st, now, _none, True)
    assert D.carry_lines(st, now.date()) == \
        ['11/06 요약 접수 여부 확인 불가(제출 시도 1번: 응답 못 받음 1 · Worker 상태 목록에 그 사건이 없었어요)']


def test_migrate_old_direct_send_state():
    old = {'last_sent': at(2026, 11, 9, 9, 20).isoformat(), 'last_sent_day': '2026-11-09',
           'last_error': 'TimeoutExpired: /Users/x/…', 'lines': {'a': {'sha': '1', 'text': 't'}},
           'pending': 'broken'}
    st = D.migrate(dict(old))
    assert 'last_sent_day' not in st and st['last_submitted_day'] == '2026-11-09'
    assert st['last_sent'] == old['last_sent'] and st['lines'] == old['lines']
    assert st['last_error'] == '기타 오류' and 'pending' not in st
    assert not D.due(at(2026, 11, 9, 12), st) and D.due(at(2026, 11, 10, 9), st)
    assert D.migrate({}) == {} and D.pending_of({}) is None and D.unconfirmed({}) == []


# ── 기밀: 구조로 먼저, 정규식은 보조 ─────────────────────────────────────────

def test_number_line_carries_kinds_not_raw_checker_lines():
    out = _out(warnings=['경고(문장): /Users/x 의 3.2% 는…', '경고(표): 칸을 비웠다'], violations=[])
    r = D.number_result(0, out, '', False)
    assert r['kinds'] == {'경고(문장)': 1, '경고(표)': 1}
    text = D.block(post(number=r))
    assert '종류: 경고(문장) 1 · 경고(표) 1' in text and '/Users/' not in text and '3.2%' not in text
    bad = D.number_result(2, '', 'FATAL: /private/var/folders/x/data 를 못 읽었다', False)
    text = D.block(post(number=bad))
    assert '판정 불가 — 검사기가 입력을 읽지 못했어요' in text and '/private/' not in text
    assert '/private/' in bad['reason']                        # 자세한 사유는 맥 안에서만


def test_prepub_error_text_is_not_shown():
    p = _post('posts/2026-11-09.html', prepub={'error': 'OSError: /Users/x/Library/…'})
    assert '/Users/' not in D.block(p) and '[발행 전 기록] 읽지 못했어요' in D.block(p)


def test_notes_only_from_the_fixed_list():
    ok = [D.NOTE_FIRST, D.NOTE_STALE, D.NOTE_CORRUPT, '지난 알림 실패 — 접수 오류', '지난 알림 실패 — 전송 오류',
          '공개판에서 사라진 글 2건: US 일간 11/06, KR 뉴스 11/05',
          f'{D.KEEP_DAYS}일이 지나 추적을 멈춘 글 1건(안 끝났거나 못 보낸 글): US 주간 8/01']
    ok += D.kr_index_gap_notes({'2026-W45': {'missing': ['indices.KOSPI.2026-11-05']}})
    assert len(ok) == 8 and D.safe_notes(ok) == ok
    got = D.safe_notes([D.NOTE_STALE, '지난번 알림이 실패했어요 — OSError: /Users/x', 'KeyError: reviews/pending'])
    assert got == [D.NOTE_STALE, '기타 안내 2건 — 맥에서 확인']
    # reconcile 이 만드는 안내는 전부 목록 안이다
    st = {'last_sent': 'x', 'lines': {'posts/2026-11-01.html': {'sha': 's', 'text': 't'}}, 'all': [],
          'tracked': {'posts/2026-07-01.html': 'a'}, 'open': ['posts/2026-07-01.html']}
    _, notes, _ = D.reconcile([], st, {'posts/2026-07-01.html': 'a', 'posts/2026-06-01.html': 'b'},
                              date(2026, 11, 9))
    assert len(notes) == 3 and D.safe_notes(notes) == notes
    text, _ = D.render([post()], {}, at(2026, 11, 9), notes=['Traceback … /Users/x'])
    assert '/Users/' not in text and '⚠ 기타 안내 1건' in text


def test_scrub_replaces_line_and_keeps_base_back(monkeypatch):
    for leak in ('/Users/daeyoung/x', '~/Library/Application Support', '/private/tmp/y',
                 '123456789:AAF' + 'a' * 32, 'ghp_' + 'a' * 36, 'sk-ant-api03-xyz', 'reviews/pending',
                 '2026-11-06-us-abc1234.md', '2026-11-07-kr_weekly-0123abc.md'):
        assert D.scrub(f'앞\n · 줄 {leak} 끝\n뒤') == (f'앞\n{D.REDACTED}\n뒤', 1), leak
    for fine in ('risk-off 장세', 'posts/2026-11-06.html', '데이터 bbbb2222 · 검사기 cccc3333', D.CAVEAT):
        assert D.scrub(fine) == (fine, 0)
    a, b = post(), post('kr/posts/2026-11-06.html')
    real = D._review_line
    monkeypatch.setattr(D, '_review_line',
                        lambda p: ' · codex 검토: /Users/x/reviews/pending 참고' if p is a else real(p))
    text, lines = D.render([a, b], {}, at(2026, 11, 9), extra_tail=['발행 알림: ~/Library 를 못 읽음'])
    assert '/Users/' not in text and '~/Library' not in text and text.count(D.REDACTED) == 2
    assert '2줄 생략 — 맥에서 확인' in text
    assert a['path'] not in lines and b['path'] in lines        # 걸린 글은 다음 요약에서 다시 확인한다
    clean, _ = D.render([b], {}, at(2026, 11, 9))
    assert '생략' not in clean


# ── 꼬리: GitHub 계산 기록(alerts-state)·전송기 상태 ───────────────────────────────

class FakeGit:
    def __init__(self, show=None, ls=0, ref=True):
        self.show, self.ls, self.ref, self.calls = show, ls, ref, []

    def __call__(self, args, **kw):
        assert args[:3] == ['git', '-C', '/repo']
        cmd = args[3]
        self.calls.append(args[3:])
        code, out = 0, b''
        if cmd == 'ls-remote':
            code = self.ls
        elif cmd == 'rev-parse':
            code = 0 if self.ref else 1
        elif cmd == 'show':
            assert args[4] == 'refs/remotes/origin/alerts-state:verify_publish.json'
            code, out = (0, self.show) if self.show is not None else (128, b'')
        return subprocess.CompletedProcess(args, code, out, b'')


def _publish_state(**kw):
    from review import publish_watch as W
    st = W.new_state('test')
    st.update(kw)
    return json.dumps(st).encode('utf-8')


def test_publish_tail_reads_alerts_state_branch(monkeypatch):
    from review import publish_watch as W
    seen = []
    monkeypatch.setattr(W, 'summary_lines_from',
                        lambda st, now, stale=None: seen.append((st, stale)) or ['아직 안 올라온 세션: KR 일간 11/09'])
    g = FakeGit(_publish_state(last_ok=at(2026, 11, 10, 8).isoformat()))
    assert D.publish_tail('/repo', at(2026, 11, 10, 9), run=g) == ['아직 안 올라온 세션: KR 일간 11/09']
    assert seen[0][0]['format'] == W.FORMAT and seen[0][1] == W.GITHUB_STALE     # 2시간이 아니라 GitHub 기준
    assert [c[0] for c in g.calls] == ['ls-remote', 'fetch', 'rev-parse', 'show']
    assert '+refs/heads/alerts-state:refs/remotes/origin/alerts-state' in g.calls[1]   # 사본이 main 만 받아도
    g = FakeGit(_publish_state())
    D.publish_tail('/repo', at(2026, 11, 10, 9), fetch=False, run=g)
    assert [c[0] for c in g.calls] == ['rev-parse', 'show']     # --no-fetch 는 원격을 안 부른다


def test_publish_tail_with_the_real_summary_function():
    # 흉내 없이 — GitHub 계산 상태 모양을 실제 함수가 받는다. 문구는 그쪽 몫이라 모양만 본다
    now = at(2026, 11, 10, 9)
    quiet = D.publish_tail('/repo', now, run=FakeGit(_publish_state(last_ok=at(2026, 11, 10, 3).isoformat())))
    assert quiet == []                                          # 6시간 전 — GitHub 기준(9시간) 안이라 조용하다
    late = D.publish_tail('/repo', now, run=FakeGit(_publish_state(last_ok=at(2026, 11, 9, 20).isoformat())))
    assert len(late) == 1 and all(isinstance(x, str) for x in late) and late != [D.TAIL_UNREAD]
    never = D.publish_tail('/repo', now, run=FakeGit(_publish_state()))
    assert never and never != [D.TAIL_UNREAD] and never != [D.TAIL_MISSING]


def test_publish_tail_missing_and_unreadable(monkeypatch):
    now = at(2026, 11, 10, 9)
    assert D.publish_tail('/repo', now, run=FakeGit(ls=2)) == [D.TAIL_MISSING]          # 원격에 브랜치 없음
    # 원격을 안 봤으면 「아직 없어요」라고 단정하지 않는다(3a §E)
    assert D.publish_tail('/repo', now, fetch=False, run=FakeGit(ref=False)) == [D.TAIL_NO_COPY]
    # 네트워크 실패를 「아직 없어요」로 읽지 않는다 — 3a 부터 어디서 막혔는지 고정 낱말로 붙는다
    assert D.publish_tail('/repo', now, run=FakeGit(ls=128, ref=False)) == [D.tail_unread('원격 확인 실패', '받아 둔 사본 없음')]
    assert D.publish_tail('/repo', now, run=FakeGit(show=None)) == [D.tail_unread('받아 둔 사본에서 파일을 못 읽음')]
    for broken in (b'{broken', b'{"format": "other"}', b'{"format": "verify-publish/1"}'):
        assert D.publish_tail('/repo', now, run=FakeGit(show=broken)) == [D.tail_unread('상태 파일 내용 검증 실패')]

    def boom(args, **kw):
        raise subprocess.TimeoutExpired(args, 60)
    assert D.publish_tail('/repo', now, run=boom) == [D.tail_unread('원격 확인 실패', '받아 둔 사본을 확인하지 못함')]
    # 원격이 안 닿아도 받아 둔 판이 있으면 그것으로(오래됐는지는 그 상태의 last_ok 가 말한다) — 사본으로 읽었다고 밝힌다
    from review import publish_watch as W
    monkeypatch.setattr(W, 'summary_lines_from', lambda st, now, stale=None: ['x'])
    assert D.publish_tail('/repo', now, run=FakeGit(_publish_state(), ls=128)) == [f'{D.TAIL_COPY}(원격 확인 실패)', 'x']
    assert 'GitHub 계산 기록이 아직 없어요' in D.TAIL_MISSING and '상태를 못 읽었어요' in D.TAIL_UNREAD


def test_health_line_only_when_abnormal():
    now = at(2026, 11, 10, 9, 20)
    ok = {'last_outbox_ok': '2026-11-10T00:05:00.000Z', 'last_outbox_read': None, 'backlog': 0, 'failed': 0}
    assert D.health_lines(ok, now) == []
    assert D.health_lines(dict(ok, backlog=2, failed=1), now) == ['전송기: 밀린 알림 2건 · 영구 실패 1건']
    assert D.health_lines(dict(ok, last_outbox_ok='2026-11-09T23:00:00+09:00'), now) == \
        ['전송기: GitHub 계산 기록 마지막 정상 10시간 전']
    assert D.health_lines(dict(ok, last_outbox_ok='2026-11-10T00:21:00+09:00'), now) == []   # 9시간 미만
    assert '읽은 적이 없어요' in D.health_lines(dict(ok, last_outbox_ok=None), now)[0]
    assert '못 읽었어요' in D.health_lines(dict(ok, last_outbox_ok='?', backlog='x'), now)[0]
    assert D.health_lines(None, now) == ['전송기: 상태를 못 읽었어요 — 전송 여부를 몰라요']
    assert all(len(D.health_lines(h, now)) <= 1 for h in (ok, None, dict(ok, backlog=9, failed=9)))

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
    assert 'codex 검토: 검토 진행 중' in D.block(p) and '초안' not in D.block(p)   # 초안 유무를 쓰지 않는다
    q = post('posts/2026-11-06.html', state='대기', findings=None)
    assert 'codex 검토: 대기' in D.block(q)


# ── CLI 제출 경로: 고정 → 제출 → 접수 → 전송 확인 뒤에만 기준 전진 ─────────────────────

@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    import verify_digest as V
    st = str(tmp_path / 'st' / 'state.json')
    clock = {'now': at(2026, 11, 9, 9, 20)}
    w = FakeWorker()
    monkeypatch.setenv(D.STATE_ENV, st)
    monkeypatch.setattr(D, 'now_kst', lambda: clock['now'])
    monkeypatch.setattr(V, 'build', lambda state, now, args, notes: ([post()], {}, {'posts/2026-11-06.html': 's1'}))
    monkeypatch.setattr(D, 'publish_tail', lambda root, now, fetch=True: [])
    real_post, real_status = D.post_digest, D.fetch_status
    monkeypatch.setattr(D, 'post_digest', lambda body, sid: real_post(body, sid, run=w))
    monkeypatch.setattr(D, 'fetch_status', lambda sid=None: real_status(sid, run=w))
    w.clock = clock
    return V, st, w


def _texts(w):
    return [json.loads(b)['text'] for b in w.posts]


def test_cli_submit_fixes_body_first_and_waits_for_sent(cli_env):
    V, st, w = cli_env
    seen = []
    w.hook = lambda: seen.append(D.load_state(st) if os.path.exists(st) else None)
    assert V.main([]) == 0 and len(w.posts) == 1
    at_post = [s for s in seen if s and s.get('pending')][-1]
    assert at_post['pending']['id'] == SID and at_post['pending']['text'] == _texts(w)[0]   # 네트워크 전에 저장
    assert at_post['pending']['tries'][-1]['result'] == 'noresp'
    s = D.load_state(st)
    assert s['last_submitted_day'] == '2026-11-09' and s['last_error'] is None and 'pending' not in s
    assert 'lines' not in s and not s.get('last_sent')          # 접수 ≠ 전송
    assert s['unconfirmed'][0]['base']['lines']['posts/2026-11-06.html']['sha'] == 's1'
    assert set(s['unconfirmed'][0]['base']) == {'lines', 'open', 'tracked', 'all', 'numbers'}
    w.hook = None
    assert V.main([]) == 0 and len(w.posts) == 1                # 오늘은 이미 접수됐다
    # 다음 tick(9시가 아니어도): Worker 가 sent 로 돌려주면 그때 기준이 전진한다
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    w.send(SID, '2026-11-09T00:21:07.000Z')
    assert V.main([]) == 0 and len(w.posts) == 1
    s = D.load_state(st)
    assert 'posts/2026-11-06.html' in s['lines'] and s['unconfirmed'] == []
    assert s['last_sent'] == '2026-11-09T00:21:07.000Z' and s['applied'] == ['2026-11-09', 1]
    assert D.digest_note(st, at(2026, 11, 9, 20)) == ''


def test_cli_accepted_but_unsent_repeats_changes_next_day(cli_env):
    V, st, w = cli_env
    assert V.main([]) == 0
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0 and len(w.posts) == 2
    first, second = _texts(w)
    assert '■ US 일간 11/06' in first and '■ US 일간 11/06' in second    # 전송 확인이 없어 같은 변화를 다시 담는다
    assert '첫 알림이라' in second
    assert '전송기: 밀린' not in second
    s = D.load_state(st)
    assert [u['date'] for u in s['unconfirmed']] == ['2026-11-09', '2026-11-10'] and 'lines' not in s
    # 둘 다 전송되면 날짜 순으로 적용돼 최신 기준이 남고, 다음 날은 바뀐 것이 없다
    w.send(SID, at(2026, 11, 10, 9, 30).isoformat())
    w.send('2026-11-10:morning-digest:v1', at(2026, 11, 10, 9, 31).isoformat())
    w.clock['now'] = at(2026, 11, 11, 9, 20)
    assert V.main([]) == 0
    assert '바뀐 상태가 없어요' in _texts(w)[2] and '첫 알림' not in _texts(w)[2]
    assert D.load_state(st)['applied'] == ['2026-11-10', 1]


def test_cli_noresp_retries_identical_body_every_tick(cli_env, monkeypatch):
    V, st, w = cli_env
    w.script = ['drop', 'drop']
    assert V.main([]) == 1
    s = D.load_state(st)
    assert s['pending']['tries'][-1]['result'] == 'noresp' and s['last_error'] == '연결 오류'
    assert 'last_submitted_day' not in s
    # 다음 tick 에 글이 바뀌어 있어도 고정해 둔 본문 그대로 낸다(다시 만들지 않는다)
    monkeypatch.setattr(V, 'build', lambda *a: (_ for _ in ()).throw(AssertionError('다시 만들면 안 된다')))
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 1
    w.clock['now'] = at(2026, 11, 9, 11, 20)
    assert V.main([]) == 0
    assert len(w.posts) == 3 and len(set(w.posts)) == 1
    s = D.load_state(st)
    assert s['last_submitted_day'] == '2026-11-09' and s['last_error'] is None and 'pending' not in s


def test_cli_lost_response_is_settled_by_reposting_the_same_body(cli_env):
    V, st, w = cli_env
    w.script = ['lost']
    assert V.main([]) == 1 and D.load_state(st)['pending']['tries'][-1]['result'] == 'noresp'
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0 and len(w.posts) == 2 and len(set(w.posts)) == 1   # 200(같은 본문) → 내 것이 맞다
    s = D.load_state(st)
    assert 'pending' not in s and s['unconfirmed'][0]['id'] == SID and s['last_submitted_day'] == '2026-11-09'


def test_cli_id_in_status_with_someone_elses_body_is_conflict_not_accepted(cli_env):
    # 기록을 잃고 새로 만든 본문이 무응답이었고, Worker 에는 같은 id 의 옛 본문이 있다 — /status 만 믿으면
    # 가지 않은 본문의 기준이 적용된다. 다시 내 보면 409 다.
    V, st, w = cli_env
    w.script = ['drop']
    assert V.main([]) == 1
    w.events[SID] = {'body': '기록을 잃기 전에 낸 본문', 'state': 'sent', 'sent_at': at(2026, 11, 9, 9, 1).isoformat()}
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert not s.get('unconfirmed') and 'lines' not in s and s['carry'][0]['kind'] == 'conflict'


def _expire(cli_env, script, ticks=1):
    V, st, w = cli_env
    w.script = list(script)
    for i in range(ticks):
        w.clock['now'] = at(2026, 11, 9, 9 + i, 20)
        assert V.main([]) == 1
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    return V, st, w


def test_cli_yesterday_all_rejected_is_reported_as_failed(cli_env):
    V, st, w = _expire(cli_env, [(401, ''), (400, '')], ticks=2)
    assert V.main([]) == 0
    text = _texts(w)[-1]
    assert json.loads(w.posts[-1])['id'] == '2026-11-10:morning-digest:v1'    # 새 날짜 id 로 새로 만든다
    assert '어제 요약 접수 실패' in text and '⚠ 지난 알림 실패 — 접수 오류' in text
    assert '■ US 일간 11/06' in text                             # 어제 못 전한 변화를 다시 담는다
    s = D.load_state(st)
    assert s['carry'] == [] and s['last_submitted_day'] == '2026-11-10'


def test_cli_yesterday_uncertain_is_not_called_failed(cli_env):
    V, st, w = _expire(cli_env, [(401, ''), 'drop'], ticks=2)
    assert V.main([]) == 0
    assert '어제 요약 접수 여부 확인 불가' in _texts(w)[-1] and '접수 실패' not in _texts(w)[-1]


def test_cli_yesterday_status_down_is_uncertain(cli_env):
    V, st, w = _expire(cli_env, [(500, '')])
    w.status_down = True
    assert V.main([]) == 0
    text = _texts(w)[-1]
    assert '어제 요약 접수 여부 확인 불가' in text and '전송기: 상태를 못 읽었어요' in text


def test_cli_yesterday_accepted_late_is_recorded_not_reported(cli_env):
    V, st, w = _expire(cli_env, ['lost'])
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    text = _texts(w)[-1]
    assert '어제 요약' not in text and len(w.posts) == 2
    assert [u['date'] for u in D.load_state(st)['unconfirmed']] == ['2026-11-09', '2026-11-10']


def test_cli_before_nine_keeps_retrying_yesterday(cli_env):
    V, st, w = _expire(cli_env, ['drop'])
    w.clock['now'] = at(2026, 11, 10, 3, 20)
    assert V.main([]) == 0                                      # 어제 치가 새벽에 접수됐다(Worker 는 어제 날짜를 받는다)
    assert json.loads(w.posts[-1])['id'] == SID and len(set(w.posts)) == 1
    s = D.load_state(st)
    assert s['last_submitted_day'] == '2026-11-09' and D.due(at(2026, 11, 10, 9, 20), s)


def test_cli_conflict_is_recorded_as_accepted_elsewhere(cli_env):
    V, st, w = cli_env
    w.events[SID] = {'body': '상태를 잃기 전에 낸 다른 본문', 'state': 'accepted'}
    assert V.main([]) == 0
    s = D.load_state(st)
    assert 'pending' not in s and s['last_submitted_day'] == '2026-11-09' and not s.get('unconfirmed')
    assert s['carry'] == [{'date': '2026-11-09', 'kind': 'conflict'}] and 'lines' not in s
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    assert '어제 요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요' in _texts(w)[-1]
    # 조회가 안 되면 버리지 않고 다음 tick 에 다시 확인한다
    w.events['2026-11-11:morning-digest:v1'] = {'body': 'x', 'state': 'accepted'}
    w.clock['now'] = at(2026, 11, 11, 9, 20)
    real = D.fetch_status
    D.fetch_status = lambda sid=None: (_ for _ in ()).throw(D.TransportError('x')) if sid else real(sid)
    try:
        assert V.main([]) == 1
    finally:
        D.fetch_status = real
    assert D.load_state(st)['pending']['tries'][-1]['result'] == 'conflict'


def test_cli_send_failure_at_worker_is_mentioned_next_time(cli_env):
    V, st, w = cli_env
    assert V.main([]) == 0
    w.events[SID]['state'] = 'failed_permanent'
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0
    assert '전송 오류' in D.digest_note(st, w.clock['now'])
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    assert '⚠ 지난 알림 실패 — 전송 오류' in _texts(w)[-1] and '■ US 일간 11/06' in _texts(w)[-1]


def test_cli_health_line_from_status(cli_env):
    V, st, w = cli_env
    w.health.update(backlog=3, last_outbox_ok=at(2026, 11, 8, 20).isoformat())
    assert V.main([]) == 0
    assert '전송기: 밀린 알림 3건 · GitHub 계산 기록 마지막 정상 13시간 전' in _texts(w)[0]


def test_cli_missing_key_is_recorded_without_request(cli_env):
    V, st, w = cli_env
    w.key = ''
    assert V.main([]) == 1
    s = D.load_state(st)
    assert s['last_error'] == '제출 키 없음' and not w.curls() and 'pending' not in s
    assert '제출 키 없음' in D.digest_note(st, w.clock['now'])


def test_cli_force_submits_a_new_version(cli_env):
    V, st, w = cli_env
    assert V.main([]) == 0 and V.main(['--force']) == 0
    assert [json.loads(b)['id'][-2:] for b in w.posts] == ['v1', 'v2']    # 같은 id 에 다른 본문(409)을 내지 않는다
    assert D.load_state(st)['submitted'] == {'date': '2026-11-09', 'v': 2}


def test_cli_unexpected_error_is_recorded_as_kind(cli_env, monkeypatch, capsys):
    V, st, w = cli_env

    def boom(state, now, args, notes):
        raise subprocess.TimeoutExpired(['git', '-C', '/Users/x/repo'], 60)
    monkeypatch.setattr(V, 'build', boom)
    assert V.main([]) == 1
    s = D.load_state(st)
    assert s['last_error'] == '요약 만들기 오류' and '/Users/' not in json.dumps(s, ensure_ascii=False)
    assert 'TimeoutExpired' in capsys.readouterr().err          # 자세한 사유는 이 맥의 로그에만
    assert not w.posts


def test_cli_migrates_old_state_and_mentions_old_failure_as_kind(cli_env):
    V, st, w = cli_env
    a = post()
    D.save_state(st, {'last_error': '텔레그램이 거절했어요: /Users/x', 'last_sent_day': '2026-11-08',
                      'last_sent': at(2026, 11, 8, 9, 20).isoformat(),
                      'lines': {a['path']: seen_line(a)}, 'tracked': {a['path']: 's1'}, 'all': [a['path']]})
    assert V.main([]) == 0
    text = _texts(w)[0]
    assert '⚠ 지난 알림 실패 — 기타 오류' in text and '/Users/' not in text and '텔레그램이' not in text
    assert '바뀐 상태가 없어요' in text and '첫 알림' not in text       # 옛 전달 기록을 그대로 기준으로 쓴다
    s = D.load_state(st)
    assert 'last_sent_day' not in s and s['last_submitted_day'] == '2026-11-09'
    assert s['last_sent'] == at(2026, 11, 8, 9, 20).isoformat()


def test_cli_migrated_state_does_not_resubmit_same_day(cli_env):
    V, st, w = cli_env
    D.save_state(st, {'last_sent_day': '2026-11-09', 'last_sent': at(2026, 11, 9, 9, 5).isoformat()})
    assert V.main([]) == 0 and not w.calls                      # 오늘 치는 옛 방식으로 이미 갔다
    assert not w.posts


def test_cli_records_base_open_and_tracked(cli_env, monkeypatch):
    V, st, w = cli_env
    ps = [post(), post('kr/posts/2026-11-06.html', state='대기', findings=None)]
    monkeypatch.setattr(V, 'build', lambda state, now, args, notes: (ps, {}, {p['path']: p['sha'] for p in ps}))
    assert V.main([]) == 0
    w.send(SID, at(2026, 11, 9, 9, 21).isoformat())
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert s['lines']['posts/2026-11-06.html']['sha'] == 's1'
    assert s['open'] == ['kr/posts/2026-11-06.html']
    assert s['tracked'] == {p['path']: p['sha'] for p in ps}


def test_cli_lock_failure_is_recorded(cli_env, monkeypatch):
    V, st, w = cli_env
    import fcntl

    def bad(fd, op):
        raise OSError(5, 'Input/output error')
    monkeypatch.setattr(fcntl, 'flock', bad)
    assert V.main([]) == 1
    assert D.load_state(st)['last_error'] == '잠금 오류'


def test_cli_contention_skips_quietly(cli_env, monkeypatch):
    V, st, w = cli_env
    import fcntl

    def busy(fd, op):
        raise BlockingIOError(35, 'Resource temporarily unavailable')
    monkeypatch.setattr(fcntl, 'flock', busy)
    assert V.main([]) == 0 and not w.calls


def test_cli_corrupt_state_is_moved_and_announced(cli_env):
    V, st, w = cli_env
    os.makedirs(os.path.dirname(st))
    with open(st, 'w') as fh:
        fh.write('{')
    assert V.main([]) == 0
    assert '기록 파일이 손상돼' in _texts(w)[0]
    assert any(n.startswith('state.json.corrupt-') for n in os.listdir(os.path.dirname(st)))


def test_cli_not_due_before_nine(cli_env):
    V, st, w = cli_env
    w.clock['now'] = at(2026, 11, 9, 8, 20)
    assert V.main([]) == 0 and not w.calls and not os.path.exists(st)


def test_cli_dry_run_touches_neither_keychain_nor_worker(cli_env, capsys):
    V, st, w = cli_env
    assert V.main(['--dry-run']) == 0
    assert not w.calls and not os.path.exists(st)
    assert capsys.readouterr().out.startswith('[검증 알림]')

def test_render_puts_recent_first_when_cut():
    old = [post(f'{sec}/2026-{m:02d}-{d:02d}.html', state='만료', findings=None,
                number={'kind': 'violation', 'violations': 1, 'warnings': 0, 'counts': COUNTS,
                        'lines': [], 'kinds': {'위반': 1}})
           for m in (9, 10) for d in range(1, 29) for sec in ('kr/posts', 'japan/daily')]
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
    assert '[발행 전 기록] 발행본과 검사 기록 일치' in text
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


# ── 전송기 설정 오류는 텔레그램 밖에서 보인다(2026-11-10 사용자 결정) ──────────────────────

def test_health_line_mentions_config_error():
    now = at(2026, 11, 10, 9, 20)
    ok = {'last_outbox_ok': '2026-11-10T00:05:00.000Z', 'last_outbox_read': None, 'backlog': 0, 'failed': 0,
          'config_error': None}
    assert D.health_lines(ok, now) == []
    bad = dict(ok, backlog=2, config_error={'code': 401, 'kind': 'token /Users/x', 'since': '2026-11-10T00:00:00Z'})
    assert D.health_lines(bad, now) == \
        ['전송기: 설정 오류 — 텔레그램으로 못 보내는 중(11/10 09:00 부터 · Cloudflare 설정 확인) · 밀린 알림 2건']   # Worker 가 준 글자는 안 옮긴다(3a §D — 모르는 분류는 빼고 시각만)


def test_worker_note_reports_config_error_without_the_key(tmp_path):
    p = str(tmp_path / 'state.json')
    w = FakeWorker()
    assert D.worker_note(p, run=w) == ''
    w.health_out['config_error'] = True
    assert D.worker_note(p, run=w) == '[검증 알림] 전송기 설정 오류 — 텔레그램으로 못 보내는 중(Cloudflare 상태 확인)'
    assert len(w.health_calls) == 2 and not any('Authorization' in c for c in w.health_calls)
    assert not any('digest_key' in a for a, _ in w.calls)            # 훅은 제출 키를 읽지 않는다
    curl = w.curls()[-1][0]
    assert curl[curl.index('--max-time') + 1] == '5' and not any('example.test' in a for a in curl)
    assert not os.path.exists(p)                                    # 요약 기록 파일은 건드리지 않는다


def test_worker_note_says_unreachable_only_on_third_failure(tmp_path):
    p = str(tmp_path / 'state.json')
    D.save_state(p, {'pending': 'x'})
    w = FakeWorker()
    w.health_out = None
    assert [D.worker_note(p, run=w) for _ in range(4)] == \
        ['', '', '[검증 알림] 전송기 상태 확인 불가', '[검증 알림] 전송기 상태 확인 불가']
    w.health_out = '<html>login</html>'                             # 약속과 다른 응답도 실패로 센다(정상으로 읽지 않는다)
    assert D.worker_note(p, run=w) == '[검증 알림] 전송기 상태 확인 불가'
    w.health_out = {'format': 'alerts-health/1', 'ok': True, 'config_error': False, 'last_outbox_ok': None, 'backlog': 0}
    assert D.worker_note(p, run=w) == ''                            # 한 번 읽히면 횟수를 지운다
    w.health_out = {'format': 'alerts-health/1', 'config_error': 'yes'}
    assert D.worker_note(p, run=w) == ''                            # 다시 1번째 실패
    assert D.load_state(p) == {'pending': 'x'}                      # 횟수는 옆 파일에


def test_worker_note_skips_silently_without_url(tmp_path):
    p = str(tmp_path / 'state.json')
    for url in ('', 'http://alerts.example.test', 'https://a.test/path'):
        w = FakeWorker(url=url)
        assert [D.worker_note(p, run=w) for _ in range(4)] == [''] * 4 and not w.curls()
    assert not os.path.exists(p + '.health')


def test_cli_status_prints_local_and_worker_lines(cli_env, capsys, monkeypatch):
    V, st, w = cli_env
    w.health_out['config_error'] = True
    monkeypatch.setattr(D, 'worker_note', lambda path, _real=D.worker_note: _real(path, run=w))
    assert V.main(['--status']) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ['[검증 알림] 아직 한 번도 안 보냈어요',
                   '[검증 알림] 전송기 설정 오류 — 텔레그램으로 못 보내는 중(Cloudflare 상태 확인)']
    assert not w.posts and not os.path.exists(st)
    monkeypatch.setattr(D, 'worker_note', lambda path: (_ for _ in ()).throw(RuntimeError('x')))
    assert V.main(['--status']) == 0                                # 훅 한 줄 때문에 세션 시작이 깨지지 않는다
    with pytest.raises(SystemExit):
        V.main(['--setup-chat'])


# ── codex 구현 1회 #4: id 가 있다는 사실만으로 자기 본문이라 믿지 않는다(hash 대조) ─────────────

def test_confirm_needs_matching_hash_to_apply_base():
    u = _unc('2026-11-09', lines={'a': {}})
    other = dict(_ev(u), hash=D.text_hash('기록을 잃기 전에 낸 다른 본문'))
    st = {'unconfirmed': [dict(u)], 'lines': {}}
    assert D.confirm(st, {u['id']: other}, at(2026, 11, 10, 9))
    assert st['lines'] == {} and st['unconfirmed'] == [] and 'applied' not in st and not st.get('last_sent')
    assert D.carry_lines(st, date(2026, 11, 10)) == ['어제 요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요']
    # 전송 전이어도 다른 본문이면 기다리지 않는다
    st = {'unconfirmed': [dict(u)], 'lines': {}}
    assert D.confirm(st, {u['id']: dict(other, state='queued')}, at(2026, 11, 9, 10)) and st['unconfirmed'] == []
    # hash 가 없거나 모양이 이상하면 대조할 수 없다 — 적용하지 않고 「확인 불가」
    for h in (None, 'abc', 12):
        ev = _ev(u)
        ev.pop('hash')
        if h is not None:
            ev['hash'] = h
        st = {'unconfirmed': [dict(u)], 'lines': {}}
        assert D.confirm(st, {u['id']: ev}, at(2026, 11, 10, 9))
        assert st['lines'] == {} and 'applied' not in st and st['last_error'] == '확인 불가'
        assert D.carry_lines(st, date(2026, 11, 10)) == \
            ['어제 요약 전송 확인 불가 — Worker 응답에서 본문 대조 값을 확인하지 못했어요']     # 3a §G — 「주지 않았다」 단정을 뺐다
        waiting = {'unconfirmed': [dict(u)], 'lines': {}}       # 전송 전에는 그냥 기다린다
        assert not D.confirm(waiting, {u['id']: dict(ev, state='queued')}, at(2026, 11, 9, 10))
    legacy = dict(u)
    legacy.pop('hash')                                          # 맥 쪽에 해시가 없는 기록도 적용하지 않는다
    st = {'unconfirmed': [legacy], 'lines': {}}
    D.confirm(st, {u['id']: _ev(u)}, at(2026, 11, 10, 9))
    assert st['lines'] == {}
    assert _ev(u)['hash'].upper() != _ev(u)['hash']
    st = {'unconfirmed': [dict(u)], 'lines': {}}                # 대소문자만 다른 것은 같은 값이다
    D.confirm(st, {u['id']: dict(_ev(u), hash=u['hash'].upper())}, at(2026, 11, 10, 9))
    assert st['lines'] == {'a': {}}


def test_settle_compares_hash_not_presence():
    now = at(2026, 11, 10, 9, 20)
    mine, theirs = D.text_hash('요약'), D.text_hash('다른 본문')
    # 409 를 못 받았어도(무응답) 다른 본문이 접수돼 있으면 충돌이다 — 기준을 싣지 않는다
    st = {'pending': _tried('noresp')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent', 'hash': theirs}, True) == 'conflict'
    assert not st.get('unconfirmed') and 'pending' not in st
    # 409 를 받았더라도 hash 가 내 본문이면 내 것이다
    st = {'pending': _tried('conflict')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'accepted', 'hash': mine}, True) == 'accepted'
    assert st['unconfirmed'][0]['hash'] == mine
    # hash 없는 응답: 내 본문이라 믿지 않는다 — 기한 전이면 그대로, 지났으면 확인 불가
    st = {'pending': _tried('noresp')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent'}, False) is None and 'pending' in st
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent'}, True) == 'unknown'
    assert not st.get('unconfirmed') and D.carry_lines(st, now.date()) == \
        ['어제 요약 접수 여부 확인 불가(제출 시도 1번: 응답 못 받음 1 · Worker 응답에서 본문 대조 값을 확인하지 못했어요)']


def test_cli_lost_state_new_body_no_response_then_expiry_does_not_apply_base(cli_env):
    # codex 가 든 경우 그대로: 기록을 잃고 같은 id 로 다른 본문을 만들었고, 제출은 응답이 없었다(409 기록 없음).
    # 다음 날 /status 에 그 id 가 sent 로 있어도 보내지 않은 새 본문의 기준을 적용하지 않는다.
    V, st, w = cli_env
    w.events[SID] = {'body': '기록을 잃기 전에 낸 본문', 'state': 'sent', 'sent_at': at(2026, 11, 9, 9, 1).isoformat()}
    w.script = ['drop']
    assert V.main([]) == 1 and D.load_state(st)['pending']['tries'][-1]['result'] == 'noresp'
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert 'lines' not in s and 'applied' not in s
    assert [u['date'] for u in s['unconfirmed']] == ['2026-11-10']
    text = _texts(w)[-1]
    assert '어제 요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요' in text and '■ US 일간 11/06' in text


def test_cli_status_without_hash_never_applies_base(cli_env):
    V, st, w = cli_env
    w.no_hash = True
    assert V.main([]) == 0
    w.send(SID, at(2026, 11, 9, 9, 21).isoformat())
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert 'lines' not in s and s['last_error'] == '확인 불가' and s['unconfirmed'] == []


# ── codex 구현 1회 #2: 401 은 설정 오류로 보이고, 접수 안 된 제출본은 지우지 않는다 ─────────────

def test_cli_unauthorized_is_visible_and_pending_is_archived(cli_env):
    V, st, w = cli_env
    w.script = [(401, '')] * 30
    w.status_code = 401
    assert V.main([]) == 1
    s = D.load_state(st)
    assert s['last_error'] == '제출 키 오류' and s['auth_error']
    hook = D.digest_note(st, w.clock['now'])
    assert hook == '[검증 알림] 요약 제출 키 오류 — Worker 가 제출을 거부해요(키체인 digest_key 와 Worker Secret 확인)'
    first = s['pending']['text']
    # 다음 날 9시 뒤: 어제 치는 버리지 않고 옆 파일에 남긴다. 기준은 적용되지 않는다
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 1
    arch = D.archive_path(st)
    assert arch.endswith('state.expired.jsonl') and os.stat(arch).st_mode & 0o777 == 0o600
    with open(arch, encoding='utf-8') as fh:
        rows = [json.loads(x) for x in fh]
    assert len(rows) == 1 and rows[0]['outcome'] == 'failed'
    assert rows[0]['pending']['text'] == first and rows[0]['pending']['id'] == SID
    assert set(rows[0]['pending']['base']) == {'lines', 'open', 'tracked', 'all', 'numbers'}
    assert all(t['result'] == 'rejected' for t in rows[0]['pending']['tries'])
    s = D.load_state(st)
    assert 'lines' not in s and s['pending']['date'] == '2026-11-10'
    assert not any(json.loads(b)['id'] == SID and json.loads(b)['date'] != '2026-11-09' for b in w.posts)
    assert sum(json.loads(b)['id'] == SID for b in w.posts) == 1          # 기한이 지난 것은 다시 내지 않는다
    # 키를 고친 뒤: 새벽에 오늘 치가 접수돼도, 다음 요약 머리에 한 번은 알린다
    w.script, w.status_code = [], None
    w.clock['now'] = at(2026, 11, 10, 10, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert 'auth_error' not in s and s['last_error'] is None
    assert D.digest_note(st, w.clock['now']) == ''
    text = _texts(w)[-1]
    assert '⚠ 요약 제출 키 오류가 있었어요 — Worker 가 제출을 거부했어요(키체인 digest_key 와 Worker Secret 확인)' in text
    assert '어제 요약 접수 실패' in text and '■ US 일간 11/06' in text     # 내용은 다시 담긴다


def test_cli_status_401_alone_sets_the_hook_line(cli_env):
    V, st, w = cli_env
    assert V.main([]) == 0                                       # 접수됨 — 전송 확인 대기
    w.status_code = 401
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0
    assert '요약 제출 키 오류' in D.digest_note(st, w.clock['now'])
    w.status_code = None
    w.clock['now'] = at(2026, 11, 9, 11, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert 'auth_error' not in s and D.carry_notes(s) == [D.AUTH_NOTE]     # 다음 요약 머리에 남아 있다
    assert D.safe_notes([D.AUTH_NOTE]) == [D.AUTH_NOTE]


def test_archive_keeps_thirty_days(tmp_path):
    st = str(tmp_path / 'verify_digest.json')
    assert D.archive_path(st) == str(tmp_path / 'verify_digest.expired.jsonl')
    D.archive_expired(st, _tried('noresp', day='2026-10-01'), 'unknown', at(2026, 10, 2, 9))
    D.archive_expired(st, _tried('rejected', day='2026-10-20'), 'failed', at(2026, 10, 21, 9))
    D.archive_expired(st, _tried('noresp'), 'unknown', at(2026, 11, 10, 9))
    with open(D.archive_path(st), encoding='utf-8') as fh:
        rows = [json.loads(x) for x in fh]
    assert [r['pending']['date'] for r in rows] == ['2026-10-20', '2026-11-09']     # 30일 넘은 것만 지운다
    assert not os.path.exists(st)                                # 기록 파일은 건드리지 않는다


def test_cli_archive_failure_does_not_block_the_next_digest(cli_env, monkeypatch, capsys):
    V, st, w = _expire(cli_env, ['drop'])

    def boom(*a):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(D, 'append_archive', boom)
    assert V.main([]) == 0 and '어제 요약 접수 여부 확인 불가' in _texts(w)[-1]
    assert '보관하지 못했다' in capsys.readouterr().err
    left = D.load_state(st).get('unarchived')                   # 원문은 기록 파일 안에 남는다(codex 구현 2회 #2)
    assert left and left[0]['pending']['text'] and left[0]['outcome'] == 'unknown'


def test_archive_unreadable_existing_file_is_not_replaced(tmp_path):
    st = str(tmp_path / 'verify_digest.json')
    D.archive_expired(st, _tried('noresp'), 'unknown', at(2026, 11, 10, 9))
    dest = D.archive_path(st)
    os.chmod(dest, 0o200)                                       # 쓰기만 — 읽기 실패(codex 구현 2회 #8)
    try:
        with pytest.raises(OSError):
            D.archive_expired(st, _tried('rejected'), 'failed', at(2026, 11, 10, 10))
    finally:
        os.chmod(dest, 0o600)
    with open(dest, encoding='utf-8') as fh:
        assert len(fh.read().splitlines()) == 1                 # 기존 줄이 그대로


def test_archive_keeps_unparseable_lines(tmp_path):
    st = str(tmp_path / 'verify_digest.json')
    with open(D.archive_path(st), 'w', encoding='utf-8') as fh:
        fh.write('{깨진 줄\n')
    D.archive_expired(st, _tried('noresp'), 'unknown', at(2026, 11, 10, 9))
    with open(D.archive_path(st), encoding='utf-8') as fh:
        lines = fh.read().splitlines()
    assert lines[0] == '{깨진 줄' and len(lines) == 2


def test_archive_undecodable_file_is_kept_and_raises_oserror(tmp_path):
    st = str(tmp_path / 'verify_digest.json')
    with open(D.archive_path(st), 'wb') as fh:
        fh.write(b'\xff\xfe broken\n')
    with pytest.raises(OSError):                                # 호출부가 잡는 실패로(codex 구현 3회 #1)
        D.archive_expired(st, _tried('noresp'), 'unknown', at(2026, 11, 10, 9))
    with open(D.archive_path(st), 'rb') as fh:
        assert fh.read() == b'\xff\xfe broken\n'


def test_cli_reachive_success_is_saved_even_on_idle_tick(cli_env):
    V, st, w = cli_env
    assert V.main([]) == 0                                      # 오늘 요약 제출 — 이후 tick 은 할 일이 없다
    s = D.load_state(st)
    s['unarchived'] = [{'archived_at': at(2026, 11, 9, 9).isoformat(), 'outcome': 'unknown',
                        'pending': {'id': '2026-11-08:morning-digest:v1', 'text': '옛 원문'}}]
    D.save_state(st, s)
    assert V.main([]) == 0
    assert 'unarchived' not in D.load_state(st)                 # 재보관 성공이 저장된다(codex 구현 3회 #2)
    with open(D.archive_path(st), encoding='utf-8') as fh:
        assert sum('옛 원문' in x for x in fh) == 1
    assert V.main([]) == 0
    with open(D.archive_path(st), encoding='utf-8') as fh:
        assert sum('옛 원문' in x for x in fh) == 1                # 다음 tick 에 또 보관하지 않는다
