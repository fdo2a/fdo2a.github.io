"""알림이 「무엇이·왜」를 말한다(2026-11-11 사용자 지시 「실패했다고만 말하지 말고 그 이유까지」).

판정·차단은 그대로 — 문구만. 이유는 공개 레포 기록(verification/*.json)에 이미 있는 값과 고정 문구만 쓴다.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from review import prepub_view as V
from review import publish_watch as W
from review.tests import prepub_fixture as F
from verification import record as R

KST = timezone(timedelta(hours=9))
D = '2026-11-09'


def rewrite(repo, fn, market='us', date=D):
    p = os.path.join(str(repo), R.record_path(market, date))
    rec = json.load(open(p, encoding='utf-8'))
    fn(rec)
    F.write(repo, R.record_path(market, date), json.dumps(rec, ensure_ascii=False))
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')


def view(repo, market='us', date=D):
    return V.view(str(repo), 'HEAD', market, date)


# ── 발행 건별 알림 ────────────────────────────────────────────────────────

def test_workspace_inputs_are_named_with_the_reason(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo)                                     # <datadir>/macro_next.json 이 workspace-only

    def add(rec):
        rec['inputs']['files'].append({'path': '<tg>/telegram.json', 'sha256': 'x', 'ref': 'workspace-only'})
    rewrite(repo, add)
    text = V.render_publish(view(repo), who=V.GITHUB)
    assert '대조 불가 1칸(작업 공간 전용 입력)' in text
    assert '작업 공간 전용 입력: 대조 불가 2개 — 루틴 작업 공간에만 있던 파일이라 원본을 보관하지 않았어요' in text
    assert 'macro_next.json, 텔레그램 입력 telegram.json' in text


def test_many_workspace_inputs_are_cut_with_count(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def add(rec):
        rec['inputs']['files'] += [{'path': f'<datadir>/f{i}.json', 'sha256': 'x', 'ref': 'workspace-only'}
                                   for i in range(11)]
    rewrite(repo, add)
    text = V.render_publish(view(repo))
    assert 'f7.json (외 3개)' in text and 'f8.json' not in text


def test_unknown_category_carries_its_reason(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.git(repo, 'rm', '-q', 'scripts/g2.py')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    text = V.render_publish(view(repo))
    assert '검사 코드: 대조 불가 — 그 커밋에 검사 코드 파일이 없다 — check_numbers(scripts/g2.py)' in text


def test_every_unknown_or_mismatch_line_has_a_reason(tmp_path):
    # 어느 칸이든 대조 불가·불일치 줄은 「 — 」 뒤에 이유가 있다
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def mangle(rec):
        rec['repo_inputs'] = {}
        rec['inputs']['files'].append({'path': '<datadir>/x', 'sha256': 'x', 'ref': 'weird'})
        rec['gates'][0]['script_sha256'] = ''
        rec['post']['sha256'] = 'bad'
    rewrite(repo, mangle)
    text = V.render_publish(view(repo))
    lines = [x for x in text.splitlines() if ': 대조 불가' in x or ': 불일치' in x]
    assert len(lines) >= 4
    assert all(' — ' in x for x in lines), lines


def gate_warn(rec, name='g1', **kw):
    g = next(x for x in rec['gates'] if x['name'] == name)
    g.update(kw)
    rec['summary']['warned'] = [name]
    rec['summary']['status'] = 'pass_with_warnings'


def test_warning_shows_the_checkers_own_reason(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rewrite(repo, lambda r: gate_warn(r, status='warn', items=['분량: 본문 10117자', '경고: 서술형 본문이 10117자다',
                                                               '경고: 시황군 3698자 < 판단군 4999자', '경고: 셋째']))
    text = V.render_publish(view(repo))
    assert ' · 경고: g1 — 서술형 본문이 10117자다; 시황군 3698자 < 판단군 4999자 (외 1건)' in text
    assert '분량:' not in text                          # 경고 줄이 있으면 정보 줄은 이유로 쓰지 않는다


def test_reason_field_wins_and_missing_reason_is_said(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def two(rec):
        rec['gates'][0].update(status='not_run', reason='적용일 전 글이라 검사하지 않았다', items=['x'])
        rec['gates'][1].update(status='warn', items=[])
        rec['summary']['not_run'] = ['g1']
        rec['summary']['warned'] = ['check_numbers']
    rewrite(repo, two)
    text = V.render_publish(view(repo))
    assert ' · 실행 안 함: g1 — 적용일 전 글이라 검사하지 않았다' in text
    assert ' · 경고: check_numbers — 이유가 기록에 없어요' in text


def test_long_reasons_stay_inside_one_event(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo)

    def many(rec):
        rec['gates'] = [{'name': f'g{i}', 'argv': ['scripts/g1.py'], 'status': 'warn', 'required': True,
                         'script_sha256': rec['gates'][0]['script_sha256'],
                         'items': ['경고: ' + '가' * 300] * 5} for i in range(40)]
        rec['summary']['warned'] = [g['name'] for g in rec['gates']]
        rec['inputs']['files'] += [{'path': f'<datadir>/{"n" * 70}{i}', 'sha256': 'x', 'ref': 'workspace-only'}
                                   for i in range(30)]
    rewrite(repo, many)
    text = V.render_publish(view(repo))
    assert len(text) <= W.MAX_TEXT
    assert '외 34개' in text                               # 검사기 이름도 잘리면 남은 수를 적는다


def test_unverified_numbers_show_reasons_and_old_records_say_so(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False, numbers={'table_cells': 5, 'prose_judged': 2, 'unverified': 9,
                                               'unverified_by': {'자산 없음': 5, '시점·구간 단서': 2, '어림수': 1,
                                                                 '연구 원장': 1, '지표 해부': 0}})
    text = V.render_publish(view(repo))
    assert '자동 대조하지 못한 수치 9개 — 자산 없음 5 · 시점·구간 단서 2 · 어림수 1 · 연구 원장 1' in text
    assert '지표 해부' not in text
    (tmp_path / 'b').mkdir()
    repo2 = F.init(tmp_path / 'b')
    F.publish(repo2, workspace=False, numbers={'table_cells': 5, 'prose_judged': 2, 'unverified': 9})
    assert '9개 — 이 기록에는 이유별 내역이 없어요' in V.render_publish(view(repo2))


def test_unreadable_summary_says_what_is_missing(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rewrite(repo, lambda r: r['summary'].pop('blocking'))
    text = V.render_publish(view(repo))
    assert '기록의 요약을 읽지 못했어요 — 요약에 빠졌거나 형식이 다른 칸: blocking' in text


def test_digest_lines_name_categories_without_checker_text(tmp_path):
    # 맥 요약은 검사기 원문을 싣지 않는다(기존 계약) — 칸 이름·고정 분류만
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False, numbers={'table_cells': 1, 'prose_judged': 1, 'unverified': 3,
                                               'unverified_by': {'자산 없음': 3}})
    F.git(repo, 'rm', '-q', 'scripts/g2.py')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    lines = '\n'.join(V.digest_lines(view(repo)))
    assert '레포 안 대조 불가(검사 코드)' in lines
    assert 'scripts/g2.py' not in lines
    assert '자동 대조하지 못한 수치 3개 — 자산 없음 3' in lines


def test_reasons_do_not_change_the_fingerprint(tmp_path):
    # 문구가 바뀌어도 이미 만든 사건을 다시 만들지 않는다 — 같은 id 다른 본문은 Worker 가 거절한다(codex 설계 검토 #3)
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rewrite(repo, lambda r: r['gates'][0].update(items=['경고: 다른 이유'], reason='바뀐 이유'))
    fp = V.fingerprint(view(repo))
    assert '바뀐 이유' not in fp and '다른 이유' not in fp


# ── 기록이 숫자 이유를 남긴다 ─────────────────────────────────────────────

def test_record_keeps_unverified_by_as_counts_only(tmp_path):
    res = {}
    out = json.dumps({'skipped': False, 'warnings': [], 'violations': [], 'summary': 's',
                      'counts': {'unverified': 4}, 'unverified_by': {'자산 없음': 3, '어림수': 1, 'x': 'y',
                                                                     'z': 0, 'b': True}})
    st = R._classify({'json': True}, 0, out, '', {'repo': str(tmp_path)}, res)
    assert st == 'pass'
    assert res['numbers']['unverified_by'] == {'자산 없음': 3, '어림수': 1}


def test_check_numbers_json_has_unverified_by():
    import inspect
    import check_numbers
    assert "'unverified_by'" in inspect.getsource(check_numbers.main)


# ── 미발행·사라짐·기준점·요약 꼬리 ────────────────────────────────────────

def test_missing_note_distinguishes_collection_states(tmp_path):
    repo = F.init(tmp_path)
    c = F.git(repo, 'rev-parse', 'HEAD')
    note = W._collection_note(str(repo), c, 'kr', D)
    assert '읽지 못했어요' in note and '확정하지 못했어요' in note
    for body, want in ((dict(report_date=D, complete=True), '완전한 수집 데이터는 레포에 있어요'),
                       (dict(report_date=D, complete=False), '완전하지 않아요'),
                       (dict(report_date='2026-11-06', complete=True), '앞선 판이에요'),
                       (dict(report_date='2026-11-10', complete=True), '다음 판이에요'),
                       (dict(complete=True), '없거나 날짜 형식이 아니에요')):
        F.write(repo, 'kr/data/kr_market_data.json', json.dumps(body))
        c = F.commit(repo, 'kr data')
        note = W._collection_note(str(repo), c, 'kr', D)
        assert want in note and note.startswith('원인: 확정하지 못했어요'), note


def test_gone_names_the_deleting_commit(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.git(repo, 'rm', '-q', 'posts/2026-11-09.html')
    c = F.commit(repo, 'Remove 11/09 brief (bad numbers)')
    out = W._deleted_by(str(repo), c, 'posts/2026-11-09.html')
    assert out.startswith('지운 커밋 ') and '「Remove 11/09 brief (bad numbers)」' in out
    assert W._deleted_by(str(repo), c, 'posts/none.html').startswith('지운 커밋을 찾지 못했어요')


def test_gap_says_why(tmp_path):
    repo = F.init(tmp_path)
    tip = F.git(repo, 'rev-parse', 'HEAD')
    ok, why = W._ancestry(str(repo), 'ab' * 20, tip)
    assert ok is False and '이 클론에 없어요' in why
    F.git(repo, 'checkout', '-q', '-b', 'side')
    side = F.commit(repo, 'side')
    F.git(repo, 'checkout', '-q', 'main')
    ok, why = W._ancestry(str(repo), side, tip)
    assert ok is False and '조상이 아니에요' in why


def test_summary_tail_names_markets_reasons_and_pending(tmp_path):
    now = datetime(2026, 11, 11, 9, tzinfo=KST)
    st = W.new_state('처음 실행했어요')
    st['last_ok'] = now.isoformat()
    st['calendar'] = {'kr': now.isoformat()}
    st['calendar_why'] = {'kr': 'data/market_holidays.json 에 kr.dates 목록이 없어요'}
    for i in range(5):
        W.add_event(st, 'publish', f'posts/2026-11-{10 + i}.html', 'x', now, extra=str(i))
    lines = '\n'.join(W.summary_lines_from(st, now))
    assert 'KR 일간(data/market_holidays.json 에 kr.dates 목록이 없어요)' in lines
    assert '발행 알림 미전송 5건(US 일간 11/10, US 일간 11/11, US 일간 11/12 외 2건)' in lines
    assert '연속 실패 0회' not in lines


def test_stale_tail_gives_the_last_failure_reason(tmp_path):
    now = datetime(2026, 11, 11, 9, tzinfo=KST)
    st = W.new_state('처음 실행했어요')
    st['last_ok'] = (now - timedelta(hours=10)).isoformat()
    st['fetch'] = {'why': '읽기 실패 — ls-tree abc'}
    assert '마지막 실패: 레포를 읽지 못함(git 읽기 오류)' in '\n'.join(W.summary_lines_from(st, now))
    st['fetch'] = {}
    assert '실패 기록이 없어요' in '\n'.join(W.summary_lines_from(st, now))


# ── codex 구현 검토 1회 ───────────────────────────────────────────────────

def test_budget_is_shared_across_all_categories(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo)

    def many(rec):
        sha_ = rec['gates'][0]['script_sha256']
        rec['gates'] = [{'name': f'g{i}', 'argv': ['scripts/g1.py'], 'status': st, 'required': True,
                         'script_sha256': sha_, 'reason': '이' * 200}
                        for i, st in enumerate(['fail'] * 12 + ['indeterminate'] * 6 + ['not_run'] * 6 + ['partial'] * 6)]
        names = [g['name'] for g in rec['gates']]
        rec['summary'].update(blocking=names[:12], not_run=names[18:24])
    rewrite(repo, many)
    text = V.render_publish(view(repo))
    assert len(text) <= V.TEXT_LIMIT <= W.MAX_TEXT
    assert '이유 일부는 길이 제한으로 줄였어요' in text


def test_fit_drops_tail_lines_and_says_how_many():
    text = V._fit(['머리'] + ['x' * 500] * 20, '맺음말')
    assert len(text) <= V.TEXT_LIMIT and text.startswith('머리') and text.endswith('맺음말')
    assert '길이 제한으로 줄' in text


def test_unknown_unverified_kind_is_not_printed():
    n = {'unverified': 3, 'unverified_by': {'검사기 원문: 고객 이름 홍길동': 2, '자산 없음': 1}}
    out = V._unverified_why(n)
    assert '홍길동' not in out and '분류 밖 이유 2' in out and '자산 없음 1' in out


def test_vocabulary_matches_number_audit():
    from us import number_audit as N
    assert V.UNVERIFIED_KINDS == N.UNVERIFIED_KINDS | {N.UNVERIFIED_OTHER}
    res = N.Result()
    N._unverified(res, '새 이유')
    N._unverified(res, '자산 없음', 2)
    assert res.unverified_by == {N.UNVERIFIED_OTHER: 1, '자산 없음': 2}


def test_complete_flag_unknown_is_not_called_incomplete(tmp_path):
    repo = F.init(tmp_path)
    for body in (dict(report_date=D), dict(report_date=D, complete='true')):
        F.write(repo, 'kr/data/kr_market_data.json', json.dumps(body))
        c = F.commit(repo, 'kr')
        note = W._collection_note(str(repo), c, 'kr', D)
        assert '완전하지 않아요' not in note and 'complete' in note and '읽지 못했어요' in note


def test_bad_calendar_why_is_state_corruption():
    st = W.new_state('처음 실행했어요')
    st['calendar_why'] = ['bad']
    import pytest
    with pytest.raises(W.StateError):
        W.loads_state(W.dumps_state(st))
    st['calendar_why'] = {'kr': '이유'}
    assert W.loads_state(W.dumps_state(st))['calendar_why'] == {'kr': '이유'}


def test_corrupt_state_reason_has_no_raw_values():
    import verify_publish as P
    st = W.new_state('x')
    W.add_event(st, 'publish', 'posts/2026-11-10.html', 'x', datetime(2026, 11, 11, tzinfo=KST))
    st['events'][0]['created'] = 'sk-private-value'
    try:
        W.loads_state(W.dumps_state(st))
    except W.StateError as exc:
        why = P._corrupt_why(exc)
    assert 'sk-private' not in why and why == '내용 검증 실패'
    try:
        W.loads_state('{not json')
    except W.StateError as exc:
        assert P._corrupt_why(exc) == 'JSON 으로 읽지 못함'
    st2 = W.new_state('x')
    st2['events'] = {}
    try:
        W.loads_state(W.dumps_state(st2))
    except W.StateError as exc:
        assert P._corrupt_why(exc) == 'events 칸이 이상함'


# ── codex 구현 재검토 2회 ────────────────────────────────────────────────

def test_null_calendar_why_is_corruption():
    import pytest
    st = W.new_state('x')
    st['calendar_why'] = None
    with pytest.raises(W.StateError):
        W.loads_state(W.dumps_state(st))


def test_summary_tail_never_prints_git_error_text():
    now = datetime(2026, 11, 11, 9, tzinfo=KST)
    st = W.new_state('x')
    st['last_ok'] = (now - timedelta(hours=10)).isoformat()
    st['fetch'] = {'why': '읽기 실패 — fatal: secret-token@host/repo'}
    lines = '\n'.join(W.summary_lines_from(st, now))
    assert 'secret-token' not in lines and '레포를 읽지 못함(git 읽기 오류)' in lines


def test_integrity_labels_are_fixed_phrases(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def bad(rec):
        rec['summary']['integrity'] = ['고객 이름 홍길동', '검사 중에 입력 파일이 바뀌었다 — 다시 기록해야 한다']
    rewrite(repo, bad)
    lines = '\n'.join(V.digest_lines(view(repo)))
    assert '홍길동' not in lines
    assert '무결성 경보(기타 무결성 경보, 검사 중 입력 파일이 바뀜)' in lines


def test_integrity_kinds_cover_record_phrases():
    import inspect
    src = inspect.getsource(R)
    import re as _re
    phrases = {m.split(' — ')[0] for m in _re.findall(r"integrity\.append\('([^']+)'\)", src)}
    assert phrases and phrases <= set(V.INTEGRITY_KINDS)


# ── codex 구현 재검토 3회 ────────────────────────────────────────────────

def test_calendar_reason_outside_fixed_phrases_is_hidden():
    now = datetime(2026, 11, 11, 9, tzinfo=KST)
    st = W.new_state('x')
    st['last_ok'] = now.isoformat()
    st['calendar'] = {'us': 'x', 'zz': 'y'}
    st['calendar_why'] = {'us': 'SECRET-CALENDAR', 'zz': 'data/market_holidays.json 이 JSON 이 아니에요'}
    lines = '\n'.join(W.summary_lines_from(st, now))
    assert 'SECRET' not in lines and 'US 일간(기타 사유)' in lines
    assert '모르는 시장(기타 사유)' in lines


def test_status_and_gate_names_outside_identifiers_are_hidden(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def bad(rec):
        rec['summary']['status'] = 'SECRET-STATUS'
        rec['gates'][0].update(name='SECRET-GATE', status='not_run')
        rec['summary']['warned'] = ['SECRET WARN']
    rewrite(repo, bad)
    v = view(repo)
    digest = '\n'.join(V.digest_lines(v))
    assert 'SECRET' not in digest and '모르는 판정' in digest           # 맥 요약은 고정 문구만
    pub = V.render_publish(v)
    assert 'SECRET-STATUS' not in pub and '모르는 판정' in pub          # 판정 이름은 건별 알림도 고정 문구
    assert 'SECRET-GATE' in pub                                         # 검사기 이름은 공개 기록 값 그대로(Fable #5)


# ── codex 구현 재검토 4회 ────────────────────────────────────────────────

def test_identifier_shaped_name_outside_config_is_hidden(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def bad(rec):
        rec['gates'].append({'name': 'secret_token_abc123', 'status': 'not_run', 'argv': []})
        rec['summary']['warned'] = ['secret_token_abc123', 'g1']
    rewrite(repo, bad)
    v = view(repo)
    assert 'secret_token' not in '\n'.join(V.digest_lines(v))
    assert '경고: g1' in V.render_publish(v)


def test_calendar_unknown_market_code_never_printed():
    now = datetime(2026, 11, 11, 9, tzinfo=KST)
    st = W.new_state('x')
    st['last_ok'] = now.isoformat()
    st['calendar'] = {'secret_token': 'x'}
    st['calendar_why'] = {'secret_token': 'data/market_holidays.json 에 secret_token.dates 목록이 없어요'}
    lines = '\n'.join(W.summary_lines_from(st, now))
    assert 'secret_token' not in lines and '모르는 시장(기타 사유)' in lines


def test_pending_key_outside_known_shapes_is_hidden():
    now = datetime(2026, 11, 11, 9, tzinfo=KST)
    st = W.new_state('x')
    st['last_ok'] = now.isoformat()
    for k in ('secret arbitrary text', 'us:2026-11-10', 'sys:fetch', 'posts/2026-11-10.html'):
        W.add_event(st, 'x', k, 'x', now)
    lines = '\n'.join(W.summary_lines_from(st, now))
    assert 'secret' not in lines
    assert '미전송 4건(알 수 없는 항목, US 일간 11/10 세션, 시스템 알림 외 1건)' in lines


# ── codex 구현 재검토 5회 ────────────────────────────────────────────────

def test_non_list_items_do_not_crash(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def bad(rec):
        rec['gates'][0].update(status='warn', items=42)
        rec['summary']['warned'] = ['g1']
    rewrite(repo, bad)
    assert '경고: g1 — 이유가 기록에 없어요' in V.render_publish(view(repo))


def test_bad_report_date_is_not_echoed(tmp_path):
    repo = F.init(tmp_path)
    for rd in ('x' * 5000, '2026-11-1', 7, '2026-99-99', '2026-02-30'):
        F.write(repo, 'kr/data/kr_market_data.json', json.dumps({'report_date': rd, 'complete': True}))
        c = F.commit(repo, 'kr')
        note = W._collection_note(str(repo), c, 'kr', D)
        assert len(note) < 200 and '날짜 형식이 아니에요' in note


def test_non_string_list_items_do_not_crash(tmp_path):
    # codex 재검토 7회: summary.integrity: [{}] 에서 렌더가 멈췄다
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def bad(rec):
        rec['summary'].update(integrity=[{}], warned=[{}], blocking=[[1]])
    rewrite(repo, bad)
    v = view(repo)
    text = V.render_publish(v) + '\n'.join(V.digest_lines(v))
    assert '형식이 다른 무결성 항목' in text and '형식이 다른 항목' in text


# ── codex 구현 재검토 8회 ────────────────────────────────────────────────

def test_odd_optional_fields_do_not_crash(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def bad(rec):
        rec['code'] = 'broken'
        rec['created_at'] = 'broken'
        rec['gates'].append({'name': [], 'argv': []})
        rec['gates'].append({'name': 'g', 'argv': 1})
        rec['gates'].append({'name': 'g', 'argv': {'x': 1}})
    rewrite(repo, bad)
    v = view(repo)
    V.render_publish(v)
    V.digest_lines(v)
    assert v['check']['cats']['scripts'] in ('대조 불가', '불일치')


def test_state_with_bad_session_key_or_naive_time_is_corruption():
    import pytest
    for mut in (lambda st: st['sessions'].update({'bad': 'missing'}),
                lambda st: st.update(last_ok='2026-11-01T00:00:00')):
        st = W.new_state('x')
        mut(st)
        with pytest.raises(W.StateError):
            W.loads_state(W.dumps_state(st))


def test_real_state_branch_still_loads():
    import subprocess
    raw = subprocess.run(['git', 'show', 'origin/alerts-state:verify_publish.json'], capture_output=True)
    if raw.returncode:
        import pytest
        pytest.skip('상태 브랜치 없음')
    W.loads_state(raw.stdout)


# ── codex 구현 재검토 9회 ────────────────────────────────────────────────

def test_more_corrupt_shapes(tmp_path):
    import pytest
    for mut in (lambda st: st['fetch'].update(since='bad'), lambda st: st['fetch'].update(since='2026-11-01T00:00:00'),
                lambda st: st.update(last_seen='x\0y')):
        st = W.new_state('x')
        mut(st)
        with pytest.raises(W.StateError):
            W.loads_state(W.dumps_state(st))
    repo = F.init(tmp_path)
    F.write(repo, 'data/market_holidays.json', json.dumps({'us': [1]}))
    c = F.commit(repo, 'cal')
    assert W._holidays(str(repo), 'us', c) == (None, 'data/market_holidays.json 에 us.dates 목록이 없어요')
    F.publish(repo, workspace=False)

    def nul(rec):
        rec['gates'][0]['argv'] = ['x\u0000y']
        rec['inputs']['files'].append({'path': '<datadir>/z', 'sha256': 'x', 'ref': 'repo:x\u0000y'})
    rewrite(repo, nul)
    v = view(repo)
    assert v['check']['cats']['scripts'] == '대조 불가' and v['check']['cats']['repo_inputs'] == '대조 불가'


def test_unknown_status_keeps_fingerprint_but_display_is_fixed(tmp_path):
    # 재검토 10회: 표시용 정규화가 지문을 바꾸면 기록 변화 없이 「상태 바뀜」 알림이 생긴다
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rewrite(repo, lambda r: r['summary'].update(status='unexpected'))
    v = view(repo)
    assert '"unexpected"' in V.fingerprint(v)
    shown = V.render_publish(v) + '\n'.join(V.digest_lines(v))
    assert 'unexpected' not in shown and '모르는 판정' in shown


def test_display_cleanup_does_not_change_judgments(tmp_path):
    # 재검토 11회: 표시용 이름 정규화가 fully_verified·anomalies 를 바꾸면 안 된다
    rec = {'summary': F.summary(status='pass'), 'gates': [
        {'name': 'check_numbers', 'status': 'pass', 'numbers': {'unverified': 0, 'table_cells': 1}},
        {'name': 'old_gate', 'status': 'fail', 'required': True}]}
    r = V.recorded(rec, allowed=None)                       # 설정을 못 읽은 경우
    v = {'kind': V.OK, 'recorded': r, 'check': {'cats': {}, 'unknown': []}, 'same_commit': True}
    assert r['numbers'] == {'unverified': 0, 'table_cells': 1}
    assert '필수 검사 실패(old_gate)' in V.anomalies(v)
    assert '필수 검사 실패(이름 모를 검사기)' in V.anomaly_labels(v)


# ── Fable 전체 검토(재검토 11회 뒤) ──────────────────────────────────────

def test_odd_git_paths_are_unknown_not_a_stall(tmp_path):
    repo = F.init(tmp_path)
    base = F.git(repo, 'rev-parse', 'HEAD')
    F.publish(repo, workspace=False)

    def bad(rec):
        for i, p in enumerate(('../x', '/abs', '.', '..', ':/', 'a//b', 'a/../b')):
            rec['inputs']['files'].append({'path': f'<datadir>/f{i}', 'sha256': 'x', 'ref': f'git:{base}:{p}'})
        rec['inputs']['files'].append({'path': '<datadir>/r', 'sha256': 'x', 'ref': 'repo:../x'})
    rewrite(repo, bad)
    v = view(repo)                                  # ReadError → GitError 로 감시가 멈추지 않는다
    assert v['check']['cats']['repo_inputs'] == '대조 불가'


def test_lone_surrogate_record_is_unreadable_not_a_crash(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    p = os.path.join(str(repo), R.record_path('us', D))
    raw = open(p, encoding='utf-8').read().replace('"g1"', '"g1\\ud800"', 1)
    F.write(repo, R.record_path('us', D), raw)
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    v = view(repo)
    text = V.render_publish(v)
    W.text_hash(text)
    assert '기록' in text


def test_non_string_config_names_do_not_crash():
    r = V.recorded({'summary': F.summary(), 'gates': [{'name': 'g1', 'status': 'pass'}]}, allowed=[['a'], {'b': 1}, 'g1'])
    assert r['readable'] and r['allowed'] == frozenset({'g1'})


def test_missing_event_id_follows_its_cause_line(tmp_path):
    # 원인 줄이 바뀌면 다른 id — 상태 초기화 뒤 같은 id·다른 본문으로 Worker 에 거절당하지 않게
    repo = F.init(tmp_path)
    st = W.new_state('x')
    now = datetime(2026, 11, 10, 13, tzinfo=KST)
    W.step(st, str(repo), now, True, ref='HEAD', who=V.GITHUB)
    a = {e['id']: e['hash'] for e in st['events'] if e['kind'] == 'missing'}
    F.write(repo, 'kr/data/kr_market_data.json', json.dumps({'report_date': '2026-11-10', 'complete': True}))
    F.commit(repo, 'kr data')
    st2 = W.new_state('x')
    W.step(st2, str(repo), now, True, ref='HEAD', who=V.GITHUB)
    b = {e['id']: e['hash'] for e in st2['events'] if e['kind'] == 'missing'}
    assert a and b and not any(i in b and b[i] != h for i, h in a.items())


def test_publish_event_id_includes_body_hash(tmp_path, monkeypatch):
    # codex 최종 검토: 상태 초기화 뒤 문구가 다르면 같은 id 로 다른 본문이 실렸다
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    now = datetime(2026, 11, 10, 13, tzinfo=KST)
    st = W.new_state('x')
    W.step(st, str(repo), now, True, ref='HEAD', who=V.GITHUB)
    a = {e['id']: e['hash'] for e in st['events'] if e['kind'] == 'publish'}
    monkeypatch.setattr(V, 'footer', lambda who=V.MAC: '※ 다른 맺음말')
    st2 = W.new_state('x')
    W.step(st2, str(repo), now, True, ref='HEAD', who=V.GITHUB)
    b = {e['id']: e['hash'] for e in st2['events'] if e['kind'] == 'publish'}
    assert a and b and not set(a) & set(b)


def test_count_header_is_skipped_for_the_detail_line():
    # KR 11/11 check_style: 머리줄 「경고 1건(발행은 막지 않는다) — <html>」 대신 아래 줄이 이유다
    g = {'status': 'warn', 'reason': '', 'items': ['경고 1건(발행은 막지 않는다) — <html>',
                                                     '· 날수를 고유어로 썼다 — 「이틀」 — 다시 읽어 보고, 자연스러우면 그대로 둔다']}
    assert V.gate_reasons(g) == ['날수를 고유어로 썼다 — 「이틀」 — 다시 읽어 보고, 자연스러우면 그대로 둔다']
