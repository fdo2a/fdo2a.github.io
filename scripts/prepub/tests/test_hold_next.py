"""즉시 알림(설계 instant_telegram v1.4 §4.2, 2026-11-22) — 보류 기록의 닫힌 칸 `next`.

감시(publish_watch)는 기록만 보고 「자동 재시도」/「사람 확인」을 알린다. 그래서 `next` 는 `lock=` 과 늘 같아야 한다
(`pushed=failed` 인 세는 실패만 예외 — 그 기록은 main 에 없다). 감시가 세는 규칙을 다시 계산하지 않는다.
05647fff 의 세는 동작은 그대로다 — test_hold_count.py 가 지킨다.
"""
import json

import pytest

import prepub_review as cli
from prepub import submit
from prepub.tests.test_hold_count import RID, _prev

CODES = sorted(cli.NOT_RUN) + list(cli.HOLD_CODES)
COUNTED = sorted(cli.COUNTED_CODES)


def _with_next(rec, nxt='retry'):
    """셋째 꼴(횟수 + next) — 쓰는 순서 그대로."""
    out = dict(rec)
    out['next'] = nxt
    return out


def _prev_cases(code):
    """앞 기록 경우 — 없음·같은 부호·다른 부호·limit·못 읽음, 둘째·셋째 꼴 둘 다."""
    other = next(c for c in COUNTED if c != code)
    same = _prev(code, 1, code) if code in cli.COUNTED_CODES else _prev(code, 0, None)
    cases = {'none': None, 'same': same, 'other': _prev(other, 1, other),
             'limit': _prev('limit', 1, 'timeout'), 'unreadable': 'not json',
             'm_shape': _prev(code)}
    for k in ('same', 'other', 'limit'):
        cases[f'{k}_n'] = _with_next(cases[k], 'person' if k == 'same' else 'retry')
    return cases


CASES = [(code, k) for code in CODES for k in _prev_cases(code)]


def _run(tmp_path, monkeypatch, capsys, code, prev, push=True, push_ok=True):
    (tmp_path / 'status.json').write_text(json.dumps({'state': code, 'request_id': RID}))
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    monkeypatch.setattr(submit, 'upload', lambda *a, **k: 'c' * 40)
    raw = prev if prev is None else (prev if isinstance(prev, str)
                                     else json.dumps(prev, ensure_ascii=False, indent=1)).encode()
    sent = []

    def fake(root, rel, message, build=None, **k):
        if not build(raw):
            return None
        if not push_ok:
            raise cli.RecordPushError('rejected')
        sent.append(open(f'{root}/{rel}', encoding='utf-8').read())
        return 'd' * 40
    monkeypatch.setattr(cli, 'push_record', fake)
    argv = ['hold', '--dir', str(tmp_path), '--section', 'us', '--date', '2026-11-07']
    assert cli.main(argv + (['--push'] if push else [])) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads((tmp_path / 'repo/reviews/prepublish/us/2026-11-07.json').read_text(encoding='utf-8'))
    return out, rec, sent


def _oracle(code, prev, push):
    """05647fff 의 lock= — 세는 규칙을 이 시험 안에서 따로 적는다(구현을 보고 맞추지 않게)."""
    if code in cli.HOLD_CODES:
        return f'hold:{code}'
    if not push:
        return 'release'
    if code == 'auth_missing':
        return 'hold:recovery_needed'
    if code == 'limit':
        return 'release'
    carried = cli._carried(None if prev is None else (prev if isinstance(prev, str) else
                                                      json.dumps(prev, ensure_ascii=False, indent=1)).encode(),
                           'us', '2026-11-07')
    if carried is None:
        return 'hold:recovery_needed'
    n, last = carried
    return 'hold:recovery_needed' if (code == last or n + 1 >= 3) else 'release'


# ── 점검표 3 — 부호 18 × 앞 기록 경우 × --push 유무의 모든 줄에서 next == lock= ──────────────────

@pytest.mark.parametrize('push', [True, False])
@pytest.mark.parametrize('code, case', CASES)
def test_next_matches_the_lock_line_in_every_row(tmp_path, monkeypatch, capsys, code, case, push):
    prev = _prev_cases(code)[case]
    out, rec, sent = _run(tmp_path, monkeypatch, capsys, code, prev, push=push)
    lock = out.rsplit('lock=', 1)[1]
    assert lock == _oracle(code, prev, push), (code, case, push)          # 05647fff 의 결과 그대로
    assert rec['next'] == ('person' if lock.startswith('hold:') else 'retry'), (code, case, push, lock)
    if sent:                                                               # main 에 올라간 기록도 같은 값
        assert json.loads(sent[-1])['next'] == rec['next']


def test_the_table_covers_all_eighteen_codes():
    assert len(CODES) == 18 and len(set(CODES)) == 18
    assert len(CASES) == 18 * 9


@pytest.mark.parametrize('code', COUNTED)
def test_a_failed_push_is_the_one_exception(tmp_path, monkeypatch, capsys, code):
    """기록 push 가 실패한 세는 실패 — lock 은 hold 로 덮지만 그 기록은 main 에 없다(감시가 읽을 일이 없다)."""
    out, rec, sent = _run(tmp_path, monkeypatch, capsys, code, None, push_ok=False)
    assert out.endswith('pushed=failed lock=hold:recovery_needed') and sent == []
    assert rec['next'] == 'retry'                                         # 로컬 기록은 지은 그대로


def test_a_limit_never_says_person(tmp_path, monkeypatch, capsys):
    for prev in (None, 'not json', _prev('timeout', 2, 'timeout')):
        out, rec, _ = _run(tmp_path, monkeypatch, capsys, 'limit', prev)
        assert out.endswith('lock=release') and rec['next'] == 'retry'


# ── 셋째 꼴은 _carried 의 세 검사(순서·키 집합·값) 전부를 지나 「셀 수 있음」 ─────────────────────

def test_the_third_shape_is_written_in_the_declared_order():
    rec, _ = cli._hold_rec('us', '2026-11-07', RID, 'timeout', (0, None), push=True)
    assert tuple(rec) == cli.HOLD_ORDER_N == cli.HOLD_ORDER + ('next',)
    assert frozenset(rec) == cli.HOLD_KEYS_N and rec['next'] in cli.NEXT_VALUES == ('retry', 'person')


@pytest.mark.parametrize('nxt', ['retry', 'person'])
def test_the_third_shape_counts_like_the_second(nxt):
    for prev, want in ((_prev('timeout', 1, 'timeout'), (1, 'timeout')), (_prev('limit', 2, 'failed'), (2, 'failed')),
                       (_prev('recovery_needed', 0, None), (0, None))):
        raw = json.dumps(_with_next(prev, nxt), ensure_ascii=False, indent=1).encode()
        assert cli._carried(raw, 'us', '2026-11-07') == want
        assert cli._carried(json.dumps(prev, ensure_ascii=False, indent=1).encode(), 'us', '2026-11-07') == want


@pytest.mark.parametrize('bad', ['stop', 'resume', '', None, True, 1, ['retry'], 'Retry', 'retry ', {'a': 1}])
def test_a_bad_next_value_is_unreadable(bad):
    raw = json.dumps(_with_next(_prev('timeout', 1, 'timeout'), bad), ensure_ascii=False, indent=1).encode()
    assert cli._carried(raw, 'us', '2026-11-07') is None


def test_next_out_of_order_or_beside_the_m_shape_is_unreadable():
    p = _prev('timeout', 1, 'timeout')
    first = {'next': 'retry', **p}                                        # 순서가 다르다
    assert cli._carried(json.dumps(first, ensure_ascii=False, indent=1).encode(), 'us', '2026-11-07') is None
    m_next = _with_next(_prev('timeout'))                                 # 횟수 칸 없이 next 만
    assert cli._carried(json.dumps(m_next, ensure_ascii=False, indent=1).encode(), 'us', '2026-11-07') is None


def test_next_does_not_change_the_carried_counts():
    """같은 기록에서 next 만 바꿔도 (attempt, last_counted) 는 같다 — 감시용 칸이 세는 규칙에 들지 않는다."""
    p = _prev('failed', 2, 'failed')
    got = {cli._carried(json.dumps(_with_next(p, n), ensure_ascii=False, indent=1).encode(), 'us', '2026-11-07')
           for n in cli.NEXT_VALUES}
    assert got == {(2, 'failed')}


def test_without_push_next_is_retry_for_every_not_run_code():
    for code in CODES:
        rec, _ = cli._hold_rec('us', '2026-11-07', RID, code, None)
        assert rec['next'] == ('person' if code in cli.HOLD_CODES else 'retry'), code
