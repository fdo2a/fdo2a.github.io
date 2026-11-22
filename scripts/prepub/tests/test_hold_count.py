"""선행 묶음 ② — 같은 실패로 처음부터 다시 쓰기를 되풀이하지 않는다(설계 auto_resume v1.5 §6.1, 2026-11-22).

「검토 미실행」은 지금까지 전부 잠금을 풀어(release) 다음 슬롯이 수집·작성부터 다시 했다. 다시 해도 똑같이 실패하는
부호(로그인 없음 등)는 하루 최대 8번 Opus 작성 + 제출을 태웠다. 이제 cmd_hold 가 origin/main 의 같은 날짜 기록을 읽어 센다.
"""
import json

import pytest

import prepub_review as cli
from prepub import submit


def _status(tmp_path, state):
    (tmp_path / 'status.json').write_text(json.dumps({'state': state, 'request_id': RID}))


RID = 'us-2026-11-07-0123456789ab'


def _fake_push(monkeypatch, prev, read_ok=True, push_ok=True, sent=None):
    """push_record 의 git 만 가짜다 — build(앞 기록 글자) 는 진짜 판정 코드를 탄다.

    prev = origin/main 에 있던 같은 날짜 기록(dict·글자·None=없음). read_ok=False 는 받기 실패(build 를 부르지 못한다).
    """
    raw = prev if prev is None else (prev if isinstance(prev, str) else json.dumps(prev, ensure_ascii=False, indent=1)).encode()

    def fake(root, rel, message, build=None, **k):
        if not read_ok:
            raise cli.RecordPushError('git fetch: 실패')
        if not build(raw):
            return None
        if not push_ok:
            raise cli.RecordPushError('rejected')
        if sent is not None:
            sent.append(json.loads(open(f'{root}/{rel}', encoding='utf-8').read()))
        return 'd' * 40
    monkeypatch.setattr(cli, 'push_record', fake)


def _line(tmp_path, monkeypatch, capsys, state, prev=None, read_ok=True, push_ok=True, push=True, sent=None):
    _status(tmp_path, state)
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    _fake_push(monkeypatch, prev, read_ok, push_ok, sent)
    argv = ['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']
    assert cli.main(argv + (['--push'] if push else [])) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))
    return out, rec


def _hold(tmp_path, monkeypatch, capsys, state, **kw):
    """마지막 줄의 lock= 값과 쓴 기록."""
    out, rec = _line(tmp_path, monkeypatch, capsys, state, **kw)
    return out.rsplit('lock=', 1)[1], rec


def _prev(state, attempt=None, last=None, **over):
    """이 코드가 쓰는 꼴 그대로의 세움 기록 — 횟수 칸 없이 부르면 11/22 M 의 꼴."""
    r = {'section': 'us', 'date': '2026-11-07', 'request_id': RID, 'state': state,
         'reason': cli.PUBLIC_REASON[state], 'hold': True, 'recorded_at': '2026-11-07T22:10:00Z'}
    if attempt is not None:
        r['attempt'], r['last_counted'] = attempt, last
    r.update(over)
    return r


def _published(tmp_path, monkeypatch, split=None):
    """cmd_record 가 실제로 쓰는 발행 기록."""
    import hashlib
    d = tmp_path / 'pub'
    d.mkdir(exist_ok=True)
    (d / 'final.html').write_text('<p>판정을 마친 판</p>', encoding='utf-8')
    (d / 'status.json').write_text(json.dumps({
        'state': 'facts_done', 'request_id': RID, 'draft_sha': 'a' * 40,
        'facts_sha256': hashlib.sha256((d / 'final.html').read_bytes()).hexdigest()}))
    if split is not None:
        (d / 'split.json').write_text(json.dumps(split))
    monkeypatch.setattr(cli, 'ROOT', str(d / 'repo'))
    assert cli.main(['record', '--dir', str(d), '--html', str(d / 'final.html'), '--section', 'us',
                     '--date', '2026-11-07']) == 0
    return json.loads((d / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))


# ── 부호의 세 갈래는 「검토 미실행」 목록을 남김없이 가른다 ─────────────────────────────

def test_every_not_run_code_falls_in_exactly_one_branch():
    branches = (cli.HUMAN_CODES, cli.WAIT_CODES, cli.COUNTED_CODES)
    for code in cli.NOT_RUN:
        assert sum(code in b for b in branches) == 1, code
    assert set().union(*branches) == set(cli.NOT_RUN)
    assert cli.HUMAN_CODES == frozenset({'auth_missing'}) and cli.WAIT_CODES == frozenset({'limit'})


# ── ① 사람 손 = 첫 번째에 바로 세움 ──────────────────────────────────────────────

def test_a_missing_login_holds_on_the_first_failure(tmp_path, monkeypatch, capsys):
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'auth_missing')
    assert lock == 'hold:recovery_needed' and rec['state'] == 'auth_missing'


def test_a_missing_login_without_push_keeps_the_old_release(tmp_path, monkeypatch, capsys):
    """--push 없이 부른 hold 는 M 그대로다(codex 구현 3회차 ⑥) — 루틴(§5)은 늘 --push 로 부른다."""
    lock, _ = _hold(tmp_path, monkeypatch, capsys, 'auth_missing', push=False)
    assert lock == 'release'


# ── ②③ 세는 실패 — 같은 부호 2번, 또는 3번째면 세움 ──────────────────────────────────

COUNTED = sorted(cli.COUNTED_CODES)


@pytest.mark.parametrize('code', COUNTED)
def test_a_first_counted_failure_still_starts_over(tmp_path, monkeypatch, capsys, code):
    lock, rec = _hold(tmp_path, monkeypatch, capsys, code)
    assert lock == 'release' and rec['attempt'] == 1 and rec['last_counted'] == code


@pytest.mark.parametrize('code', COUNTED)
def test_the_same_code_twice_in_a_row_holds(tmp_path, monkeypatch, capsys, code):
    lock, rec = _hold(tmp_path, monkeypatch, capsys, code, prev=_prev(code, 1, code))
    assert lock == 'hold:recovery_needed' and rec['attempt'] == 2


@pytest.mark.parametrize('code', COUNTED)
def test_a_different_code_after_one_failure_starts_over(tmp_path, monkeypatch, capsys, code):
    other = next(c for c in COUNTED if c != code)
    lock, rec = _hold(tmp_path, monkeypatch, capsys, code, prev=_prev(other, 1, other))
    assert lock == 'release' and rec['attempt'] == 2 and rec['last_counted'] == code


@pytest.mark.parametrize('code', COUNTED)
def test_the_third_counted_failure_holds_whatever_the_code(tmp_path, monkeypatch, capsys, code):
    other = next(c for c in COUNTED if c != code)
    lock, rec = _hold(tmp_path, monkeypatch, capsys, code, prev=_prev(other, 2, other))
    assert lock == 'hold:recovery_needed' and rec['attempt'] == 3


@pytest.mark.parametrize('split', [None, {'clarity': [], 'clarity_meta': {}}])
def test_a_published_record_of_the_same_date_cannot_be_counted(tmp_path, monkeypatch, capsys, split):
    """이미 발행한 날짜에 또 세우는 일은 정상 흐름에 없다 — 발행 기록의 꼴을 따지지 않고 「셀 수 없다」(codex 구현 3회차 ⑤)."""
    pub = _published(tmp_path, monkeypatch, split)
    assert cli._carried(json.dumps(pub, ensure_ascii=False, indent=1).encode(), 'us', '2026-11-07') is None
    sent = []
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'timeout', prev=pub, sent=sent)
    assert lock == 'hold:recovery_needed' and rec['attempt'] is None
    out, _ = _line(tmp_path, monkeypatch, capsys, 'limit', prev=pub, sent=(kept := []))
    assert out.endswith('pushed=skipped lock=release') and kept == []      # 한도는 발행 기록을 덮지 않는다


def test_an_m_era_record_without_counts_counts_as_one(tmp_path, monkeypatch, capsys):
    """11/22 M 이 쓴 기록에는 횟수 칸이 없다 — 세는 부호였으면 1번으로 읽는다."""
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'timeout', prev=_prev('timeout'))
    assert lock == 'hold:recovery_needed' and rec['attempt'] == 2
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'failed', prev=_prev('limit'))
    assert lock == 'release' and rec['attempt'] == 1


# ── ④ 한도 대기는 세지 않고, 세움이 되지 않는다 ───────────────────────────────────────

def test_a_limit_never_holds_and_carries_the_counts_unchanged(tmp_path, monkeypatch, capsys):
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'limit', prev=_prev('timeout', 2, 'timeout'))
    assert lock == 'release' and rec['attempt'] == 2 and rec['last_counted'] == 'timeout'
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'limit', read_ok=False)
    assert lock == 'release'
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'limit', push_ok=False)
    assert lock == 'release'


def test_a_limit_between_two_same_failures_does_not_reset_the_streak(tmp_path, monkeypatch, capsys):
    _, after_limit = _hold(tmp_path, monkeypatch, capsys, 'limit', prev=_prev('timeout', 1, 'timeout'))
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'timeout', prev=after_limit)
    assert lock == 'hold:recovery_needed' and rec['attempt'] == 2


@pytest.mark.parametrize('prev', ['not json', {'hold': True, 'state': []}, _prev('timeout', None) | {'attempt': None, 'last_counted': None}])
def test_a_limit_does_not_overwrite_a_record_it_cannot_read(tmp_path, monkeypatch, capsys, prev):
    """읽지 못한 기록에 실제 횟수가 있을 수 있다 — limit 은 올리지 않고 release 한다(codex 구현 2회차 ④)."""
    sent = []
    out, _ = _line(tmp_path, monkeypatch, capsys, 'limit', prev=prev, sent=sent)
    assert out.endswith('pushed=skipped lock=release') and sent == []


# ── ⑤ 셀 수 없으면 막는 쪽 ──────────────────────────────────────────────────────

def test_a_failed_fetch_holds_a_counted_failure(tmp_path, monkeypatch, capsys):
    out, rec = _line(tmp_path, monkeypatch, capsys, 'timeout', read_ok=False)
    assert out.endswith('pushed=failed lock=hold:recovery_needed')
    assert rec['attempt'] is None and rec['last_counted'] is None      # 로컬 기록도 0 이 아니라 「모름」


@pytest.mark.parametrize('bad', [{'attempt': 'x', 'last_counted': 'timeout'}, {'attempt': True, 'last_counted': None},
                                 {'attempt': -1, 'last_counted': None}, {'attempt': 1, 'last_counted': 'eyJhbG'},
                                 {'attempt': 1000, 'last_counted': None}, {'attempt': None, 'last_counted': None},
                                 {'attempt': 1.0, 'last_counted': 'timeout'}])
def test_a_malformed_count_is_unreadable(tmp_path, monkeypatch, capsys, bad):
    sent = []
    lock, rec = _hold(tmp_path, monkeypatch, capsys, 'failed', prev=dict(_prev('timeout'), **bad), sent=sent)
    assert lock == 'hold:recovery_needed'
    assert rec['attempt'] is None and rec['last_counted'] is None      # 「모름」으로 남긴다
    assert sent == [rec]                                               # 세운 기록은 올린다(사람이 부호를 본다)


# codex 구현 2회차 ②③⑤⑥ — 이 코드가 쓸 수 없는 조합·꼴·자료형은 전부 「셀 수 없다」
IMPOSSIBLE = [
    _prev('timeout', 0, None),                                  # 세는 부호인데 0번
    _prev('timeout', 1, 'failed'),                              # 세는 부호인데 마지막이 남의 부호
    _prev('limit', 0, 'timeout'), _prev('limit', 1, None),      # 0 ⇔ 마지막 없음
    _prev('limit', 1, 'limit'), _prev('limit', 1, 'auth_missing'),
    {'state': 'reviewed'},                                      # 칸 하나짜리 「발행 기록」
    {'section': 'us', 'date': '2026-11-07', 'state': 'reviewed', 'facts_done': True},
    dict(_prev('timeout'), state=[]), _prev('timeout', 1, []), _prev('timeout', 1, {}), dict(_prev('timeout'), state=None),
    dict(_prev('timeout'), state={'a': 1}),
    _prev('timeout', hold='yes'), _prev('timeout', hold=False), _prev('timeout', hold=1),
    _prev('timeout', section='kr'), _prev('timeout', date='2026-11-06'),
    _prev('timeout', reason='다른 글자'), _prev('timeout', extra=1),
    _prev('timeout', 1, 'timeout', extra=1),
    {k: v for k, v in _prev('timeout').items() if k != 'recorded_at'},
    _prev('timeout', recorded_at=[]), _prev('timeout', recorded_at='어제'), _prev('timeout', request_id='eyJhbG'),
    _prev('timeout', request_id=7),
    '{"section":"us","date":"2026-11-07","request_id":null,"state":"limit","reason":"codex 사용 한도","hold":true,'
    '"recorded_at":"2026-11-07T22:10:00Z","attempt":2,"attempt":0,"last_counted":null}',     # 같은 칸 두 번
    _prev('reviewed', reason=''),                               # 세움 기록의 state 가 닫힌 목록 밖
    {}, {'state': 'timeout'}, {'hold': True, 'state': 'eyJhbG'}, {'hold': False}, {'state': 'facts_done'},
    ['not', 'a', 'dict'], 'null', '3', '"timeout"', 'not json', '', '[' * 5000,
]


@pytest.mark.parametrize('prev', IMPOSSIBLE)
def test_a_record_this_code_could_not_have_written_is_unreadable(tmp_path, monkeypatch, capsys, prev):
    raw = (prev if isinstance(prev, str) else json.dumps(prev, ensure_ascii=False, indent=1)).encode()
    assert cli._carried(raw, 'us', '2026-11-07') is None
    out, _ = _line(tmp_path, monkeypatch, capsys, 'timeout', prev=prev)
    assert out.endswith('pushed=ok lock=hold:recovery_needed')        # 죽지 않고 lock= 줄까지 간다


def test_a_failed_record_push_holds_a_counted_failure(tmp_path, monkeypatch, capsys):
    lock, _ = _hold(tmp_path, monkeypatch, capsys, 'timeout', push_ok=False)
    assert lock == 'hold:recovery_needed'


def test_a_held_counted_failure_uploads_materials_after_the_push_decided_it(tmp_path, monkeypatch, capsys):
    sent = []
    _status(tmp_path, 'timeout')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda files, branch, msg, *a, **k: sent.append(branch))
    _fake_push(monkeypatch, None, push_ok=False)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07', '--push']) == 0
    assert capsys.readouterr().out.strip().endswith('materials=private pushed=failed lock=hold:recovery_needed')
    assert sent == ['holds']


# ── ⑥ M 의 동작은 그대로 ──────────────────────────────────────────────────────────

def test_without_push_nothing_is_read_and_counted_failures_start_over(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'push_record', lambda *a, **k: pytest.fail('push 없이 원격을 건드렸다'))
    monkeypatch.setattr(__import__('subprocess'), 'run',
                        lambda *a, **k: pytest.fail('push 없이 git 을 불렀다'))
    _status(tmp_path, 'timeout')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']) == 0
    assert capsys.readouterr().out.strip().endswith('pushed=skipped lock=release')


@pytest.mark.parametrize('code', ['recovery_needed', 'style_abort'])   # --state 로 받는 판정 뒤 부호
@pytest.mark.parametrize('prev, want', [(_prev('timeout', 1, 'timeout'), (1, 'timeout')), (None, (0, None)),
                                        ('not json', (None, None)), (_prev('timeout', 0, None), (None, None))])
def test_judged_codes_keep_their_own_hold_and_always_push(tmp_path, monkeypatch, capsys, code, prev, want):
    sent = []
    _status(tmp_path, 'reviewed')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    _fake_push(monkeypatch, prev, sent=sent)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07',
                     '--state', code, '--push']) == 0
    assert capsys.readouterr().out.strip().endswith(f'materials=private pushed=ok lock=hold:{code}')
    assert len(sent) == 1 and (sent[0]['attempt'], sent[0]['last_counted']) == want and sent[0]['state'] == code


@pytest.mark.parametrize('exc', [OSError('git missing'), __import__('subprocess').TimeoutExpired('git', 60),
                                 TypeError('unhashable'), RecursionError()])
def test_a_crashing_record_push_still_saves_materials_and_prints_the_lock(tmp_path, monkeypatch, capsys, exc):
    sent = []
    (tmp_path / 'status.json').write_text(json.dumps({'state': 'reviewed'}))
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda files, branch, msg, *a, **k: sent.append(branch))

    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(cli, 'push_record', boom)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07',
                     '--state', 'recovery_needed', '--push']) == 0
    assert capsys.readouterr().out.strip().endswith('materials=private pushed=failed lock=hold:recovery_needed')
    assert sent == ['holds']


# ── ⑦ 공개 기록에는 닫힌 값뿐 ────────────────────────────────────────────────────

def test_the_new_fields_are_closed_values(tmp_path, monkeypatch, capsys):
    _, rec = _hold(tmp_path, monkeypatch, capsys, 'timeout', prev=_prev('failed', 1, 'failed'))
    # 11/22 즉시 알림 — 닫힌 칸 next 를 더한 셋째 꼴(test_hold_next.py)
    assert set(rec) == cli.HOLD_KEYS_N == {'section', 'date', 'request_id', 'state', 'reason', 'hold', 'recorded_at',
                                           'attempt', 'last_counted', 'next'}
    assert type(rec['attempt']) is int and rec['last_counted'] in cli.COUNTED_CODES


# ── 닫힘 — 어떤 부호 순서로 이어 써도 규칙이 지켜지고, 쓴 기록은 다시 읽힌다 ─────────────────

def test_every_sequence_of_four_codes_keeps_the_rules():
    """부호 18종의 길이 4 까지의 순서 전부(104,976갈래)를 기록을 물려 가며 돌린다. 세움 뒤에도 잇는다(사람이 기록을 안 지우고 푼 경우)."""
    codes = sorted(cli.NOT_RUN) + list(cli.HOLD_CODES)
    seen = [0]

    def walk(raw, n, last, depth):
        carried = cli._carried(raw, 'us', '2026-11-07')
        assert carried == (n, last), raw                               # 이 코드가 쓴 기록은 늘 그대로 읽힌다
        if depth == 4:
            seen[0] += 1
            return
        for code in codes:
            rec, stop = cli._hold_rec('us', '2026-11-07', RID, code, carried)
            n2, last2 = (n + 1, code) if code in cli.COUNTED_CODES else (n, last)
            if code in cli.COUNTED_CODES:
                assert stop == (code == last or n + 1 >= 3), (raw, code)   # ②③
            else:
                assert stop is False, (raw, code)       # ④ limit 은 세움이 아니다(사람 손 ①·판정 뒤 부호는 cmd_hold 가 정한다)
            assert (rec['attempt'], rec['last_counted']) == (n2, last2)    # ④ 올리지도 지우지도 않는다
            assert set(rec) == cli.HOLD_KEYS_N
            walk(json.dumps(rec, ensure_ascii=False, indent=1).encode(), n2, last2, depth + 1)
    walk(None, 0, None, 0)
    assert seen[0] == 18 ** 4


def test_an_unknown_count_stays_unknown_until_the_record_is_removed():
    rec, stop = cli._hold_rec('us', '2026-11-07', RID, 'timeout', None)
    assert stop and rec['attempt'] is None
    for code in sorted(cli.NOT_RUN) + list(cli.HOLD_CODES):
        nxt, stop = cli._hold_rec('us', '2026-11-07', RID, code, cli._carried(json.dumps(rec, ensure_ascii=False, indent=1).encode(), 'us', '2026-11-07'))
        assert nxt['attempt'] is None
        assert stop == (code in cli.COUNTED_CODES), code                # 세는 실패는 세움(사람 손은 cmd_hold 가 늘 세운다)


# ── 진짜 git — 읽은 판과 올리는 바탕이 같은 받기다 ──────────────────────────────────

REL = 'reviews/prepublish/us/2026-11-07.json'


def _git(cwd, *a):
    import subprocess
    return subprocess.run(['git', '-C', str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


def _repo_with(tmp_path, files):
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(origin))
    work = tmp_path / 'work'
    _git(tmp_path, 'clone', '-q', str(origin), str(work))
    (work / 'README').write_text('x')
    for rel, body in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(body)
    _git(work, 'add', '-A')
    _git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'base')
    _git(work, 'push', '-q', 'origin', 'HEAD:main')
    return work


def _real_hold(tmp_path, monkeypatch, capsys, work, state):
    d = tmp_path / 'run'
    d.mkdir(exist_ok=True)
    _status(d, state)
    monkeypatch.setattr(cli, 'ROOT', str(work))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    for k, v in (('GIT_AUTHOR_NAME', 't'), ('GIT_AUTHOR_EMAIL', 't@t'), ('GIT_COMMITTER_NAME', 't'),
                 ('GIT_COMMITTER_EMAIL', 't@t')):
        monkeypatch.setenv(k, v)
    assert cli.main(['hold', '--dir', str(d), '--section', 'us', '--date', '2026-11-07', '--push']) == 0
    return capsys.readouterr().out.strip().splitlines()[-1]


def _origin_record(tmp_path):
    return _git(tmp_path / 'origin.git', 'show', f'main:{REL}')


def test_the_count_is_read_from_origin_not_from_the_local_copy(tmp_path, monkeypatch, capsys):
    work = _repo_with(tmp_path, {REL: json.dumps(_prev('timeout', 1, 'timeout'), ensure_ascii=False, indent=1)})
    (work / REL).write_text('{"local": "not what origin has"}')
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'failed')
    assert out.endswith('attempt=2 materials=none pushed=ok lock=release')
    rec = json.loads(_origin_record(tmp_path))
    assert (rec['attempt'], rec['last_counted'], rec['state']) == (2, 'failed', 'failed')
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'failed')    # 방금 올린 기록을 다음 런이 읽는다
    assert out.endswith('attempt=3 materials=private pushed=ok lock=hold:recovery_needed')
    assert _git(tmp_path / 'origin.git', 'diff-tree', '--no-commit-id', '--name-only', '-r', 'main') == REL


def test_no_record_on_origin_is_a_first_failure(tmp_path, monkeypatch, capsys):
    work = _repo_with(tmp_path, {})
    assert _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout').endswith('attempt=1 materials=none pushed=ok lock=release')


def test_a_failed_fetch_pushes_nothing(tmp_path, monkeypatch, capsys):
    """받기가 실패하면 올리기도 없다 — 「읽기만 실패하고 덮어쓰기는 성공」하는 틈이 없다(codex 구현 2회차 ④)."""
    before = json.dumps(_prev('timeout', 2, 'timeout'))
    work = _repo_with(tmp_path, {REL: before})
    real = __import__('subprocess').run
    calls = []

    def run(cmd, *a, **k):
        calls.append(cmd[3])
        if cmd[3] == 'fetch' and calls.count('fetch') == 1:
            return __import__('subprocess').CompletedProcess(cmd, 1, '', 'network down')
        return real(cmd, *a, **k)
    monkeypatch.setattr(__import__('subprocess'), 'run', run)
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'limit')
    assert out.endswith('pushed=failed lock=release') and 'push' not in calls
    monkeypatch.undo()
    assert _origin_record(tmp_path) == before


@pytest.mark.parametrize('body', ['not json', json.dumps({'hold': True, 'state': 'timeout', 'attempt': 0,
                                                          'last_counted': None})])
def test_a_limit_leaves_an_unreadable_record_on_origin_untouched(tmp_path, monkeypatch, capsys, body):
    work = _repo_with(tmp_path, {REL: body})
    head = _git(tmp_path / 'origin.git', 'rev-parse', 'main')
    assert _real_hold(tmp_path, monkeypatch, capsys, work, 'limit').endswith('pushed=skipped lock=release')
    assert _git(tmp_path / 'origin.git', 'rev-parse', 'main') == head
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout')   # 세는 실패는 그 기록을 못 세니 세운다
    assert out.endswith('attempt=None materials=private pushed=ok lock=hold:recovery_needed')


def test_a_directory_where_the_record_should_be_is_unreadable(tmp_path, monkeypatch, capsys):
    work = _repo_with(tmp_path, {REL + '/x': 'y'})
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout')
    assert out.rsplit('lock=', 1)[1] == 'hold:recovery_needed'


def test_a_rejected_push_recounts_from_the_record_that_won(tmp_path, monkeypatch, capsys):
    """올리는 사이 main 이 바뀌면 다시 받아 **그 판의 기록**으로 다시 센다 — lock= 은 실제로 올라간 회차의 판정이다."""
    work = _repo_with(tmp_path, {})
    other = tmp_path / 'other'
    _git(tmp_path, 'clone', '-q', str(tmp_path / 'origin.git'), str(other))
    import subprocess
    real, state = subprocess.run, {'done': False}

    def run(cmd, *a, **k):
        if cmd[3] == 'push' and not state['done']:
            state['done'] = True                                       # 첫 push 직전에 남이 같은 기록을 올린다
            (other / REL).parent.mkdir(parents=True)
            (other / REL).write_text(json.dumps(_prev('timeout', 1, 'timeout'), ensure_ascii=False, indent=1))
            real(['git', '-C', str(other), 'add', '-A'], check=True)
            real(['git', '-C', str(other), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'o'],
                 check=True)
            real(['git', '-C', str(other), 'push', '-q', 'origin', 'HEAD:main'], check=True)
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(__import__('time'), 'sleep', lambda s: None)
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout')
    assert out.endswith('attempt=2 materials=private pushed=ok lock=hold:recovery_needed')
    monkeypatch.undo()
    assert json.loads(_origin_record(tmp_path))['attempt'] == 2


# ── codex 구현 3회차 ⑥⑦ ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('code, first', [('recovery_needed', 'materials'), ('style_abort', 'materials')])
def test_judged_codes_save_materials_before_the_public_record_as_before(tmp_path, monkeypatch, capsys, code, first):
    order = []
    _status(tmp_path, 'reviewed')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: order.append('materials'))
    monkeypatch.setattr(cli, 'push_record', lambda *a, build=None, **k: (build(None), order.append('record'))[1] or 'd' * 40)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07',
                     '--state', code, '--push']) == 0
    assert order == ['materials', 'record']
    assert capsys.readouterr().out.strip().endswith(f'materials=private pushed=ok lock=hold:{code}')


@pytest.mark.parametrize('date', ['drafttext', '2026-13-01', '2026-11-7', '../../x', '2026-11-07\n', ''])
def test_a_date_that_is_not_a_date_never_reaches_the_public_record(tmp_path, monkeypatch, date):
    _status(tmp_path, 'timeout')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(cli, 'push_record', lambda *a, **k: pytest.fail('올렸다'))
    with pytest.raises(SystemExit):
        cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', date, '--push'])
    assert not (tmp_path / 'repo').exists()


# ── codex 구현 4회차 ───────────────────────────────────────────────────────────────

def _canon(rec):
    return json.dumps(rec, ensure_ascii=False, indent=1)


@pytest.mark.parametrize('wrap', ['\u00a0%s\x0b', ' %s', '%s\n', '\ufeff%s'])
def test_a_record_with_bytes_around_it_is_unreadable_all_the_way_from_git(tmp_path, monkeypatch, capsys, wrap):
    """git 출력을 다듬어(.strip) 읽으면 이 코드가 쓰지 않은 글자가 붙은 기록이 정상으로 읽힌다(⑤)."""
    work = _repo_with(tmp_path, {REL: wrap % _canon(_prev('limit', 0, None))})
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout')
    assert out.endswith('attempt=None materials=private pushed=ok lock=hold:recovery_needed')


def test_a_record_git_cannot_decode_is_unreadable(tmp_path, monkeypatch, capsys):
    work = _repo_with(tmp_path, {})
    (work / REL).parent.mkdir(parents=True)
    (work / REL).write_bytes(_canon(_prev('limit', 0, None)).encode() + b'\xff')
    _git(work, 'add', '-A')
    _git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'bad')
    _git(work, 'push', '-q', 'origin', 'HEAD:main')
    assert _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout').endswith('lock=hold:recovery_needed')


@pytest.mark.parametrize('prev', [_prev('limit', 0, None, recorded_at='2026-99-99T99:99:99Z'),
                                  json.dumps(_prev('limit', 0, None)),                    # 한 줄 꼴 — _write 의 꼴이 아니다
                                  _canon(_prev('limit', 0, None)).replace('"hold": true', '"hold":true')])
def test_a_record_not_in_the_written_form_is_unreadable(prev):
    raw = prev if isinstance(prev, str) else _canon(prev)
    assert cli._carried(raw.encode(), 'us', '2026-11-07') is None
    assert cli._carried(_canon(_prev('limit', 0, None)).encode(), 'us', '2026-11-07') == (0, None)


@pytest.mark.parametrize('exc', [AttributeError("'list' object has no attribute 'get'"), KeyError('object'),
                                 ValueError('bad json')])
@pytest.mark.parametrize('state, prev, lock', [('auth_missing', None, 'hold:recovery_needed'),
                                               ('timeout', _prev('timeout', 1, 'timeout'), 'hold:recovery_needed'),
                                               ('mismatch', _prev('failed', 2, 'failed'), 'hold:recovery_needed')])
def test_any_crash_while_saving_materials_still_prints_the_lock(tmp_path, monkeypatch, capsys, exc, state, prev, lock):
    out, _ = _line(tmp_path, monkeypatch, capsys, state, prev=prev)        # 도우미가 upload 를 깔아 둔다 — 아래서 바꾼다
    assert out.endswith(f'lock={lock}')

    def boom(*a, **k):
        raise exc
    _status(tmp_path, state)
    monkeypatch.setattr(submit, 'upload', boom)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07', '--push']) == 0
    assert capsys.readouterr().out.strip().endswith(f'materials=failed pushed=ok lock={lock}')


def test_the_local_record_is_written_before_materials_are_uploaded(tmp_path, monkeypatch):
    """M 의 순서 — 로컬 기록을 못 쓰면 비공개 업로드에 닿지 않는다(⑥)."""
    (tmp_path / 'status.json').write_text(json.dumps({'state': 'reviewed'}))
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: pytest.fail('기록을 쓰기 전에 올렸다'))

    def deny(path, obj):
        raise PermissionError(path)
    monkeypatch.setattr(cli, '_write', deny)
    for extra in ([], ['--push']):
        monkeypatch.setattr(cli, 'push_record', lambda *a, **k: pytest.fail('기록을 쓰기 전에 올렸다'))
        with pytest.raises(PermissionError):
            cli.main(['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07',
                      '--state', 'style_abort', *extra])


def test_a_push_that_landed_but_reported_failure_is_not_counted_twice(tmp_path, monkeypatch, capsys):
    work = _repo_with(tmp_path, {})
    import subprocess
    real, state = subprocess.run, {'done': False}

    def run(cmd, *a, **k):
        out = real(cmd, *a, **k)
        if cmd[3] == 'push' and not state['done']:
            state['done'] = True
            return subprocess.CompletedProcess(cmd, 1, '', 'connection reset')   # 반영됐는데 실패로 돌아왔다
        return out
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(__import__('time'), 'sleep', lambda s: None)
    out = _real_hold(tmp_path, monkeypatch, capsys, work, 'timeout')
    assert out.endswith('attempt=1 materials=none pushed=ok lock=release')
    monkeypatch.undo()
    assert json.loads(_origin_record(tmp_path))['attempt'] == 1


# ── codex 구현 5회차(상한) — 재현 뒤 사용자 「고쳐서 받아」로 고침(codex 재검토 없음) ──────────────────────────────────────

def test_a_record_with_its_fields_in_another_order_is_unreadable():
    rec = _prev('limit', 0, None)
    flipped = _canon(dict(reversed(list(rec.items())))).encode()
    assert cli._carried(_canon(rec).encode(), 'us', '2026-11-07') == (0, None)
    assert cli._carried(flipped, 'us', '2026-11-07') is None


def test_a_judged_hold_still_pushes_its_record_when_only_the_previous_blob_cannot_be_read(tmp_path, monkeypatch, capsys):
    work = _repo_with(tmp_path, {REL: _canon(_prev('timeout', 1, 'timeout'))})
    import subprocess
    real = subprocess.run

    def run(cmd, *a, **k):
        if cmd[3] == 'cat-file':
            return subprocess.CompletedProcess(cmd, 1, b'', b'boom')
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, 'run', run)
    d = tmp_path / 'run'
    d.mkdir()
    (d / 'status.json').write_text(json.dumps({'state': 'reviewed', 'request_id': RID}))
    monkeypatch.setattr(cli, 'ROOT', str(work))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    for k in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.setenv(k, 't@t')
    assert cli.main(['hold', '--dir', str(d), '--section', 'us', '--date', '2026-11-07', '--state', 'style_abort',
                     '--push']) == 0
    assert capsys.readouterr().out.strip().endswith('pushed=ok lock=hold:style_abort')


@pytest.mark.parametrize('code, ending', [('timeout', 'pushed=ok lock=hold:recovery_needed'),
                                          ('limit', 'pushed=skipped lock=release')])
def test_when_only_the_previous_blob_cannot_be_read_counted_holds_and_limit_leaves_it(tmp_path, monkeypatch, capsys,
                                                                                    code, ending):
    work = _repo_with(tmp_path, {REL: _canon(_prev('timeout', 1, 'timeout'))})
    import subprocess
    real = subprocess.run

    def run(cmd, *a, **k):
        if cmd[3] == 'cat-file':
            return subprocess.CompletedProcess(cmd, 1, b'', b'boom')
        return real(cmd, *a, **k)
    monkeypatch.setattr(subprocess, 'run', run)
    d = tmp_path / 'run'
    d.mkdir()
    (d / 'status.json').write_text(json.dumps({'state': code, 'request_id': RID}))
    monkeypatch.setattr(cli, 'ROOT', str(work))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    for k in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.setenv(k, 't@t')
    assert cli.main(['hold', '--dir', str(d), '--section', 'us', '--date', '2026-11-07', '--push']) == 0
    assert capsys.readouterr().out.strip().endswith(ending)
    monkeypatch.undo()
    origin = json.loads(_origin_record(tmp_path))
    # 세는 실패는 「모름」을 올리고, 한도는 앞 기록을 그대로 둔다
    assert origin['attempt'] == (None if code == 'timeout' else 1)
