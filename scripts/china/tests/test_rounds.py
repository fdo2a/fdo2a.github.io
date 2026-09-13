"""예정 회차 감시 — 2026-09-10 의 조용한 실패를 재현해 고정한다."""

from datetime import datetime

from china import rounds as R


def at(spec):
    """`'2026-09-14 15:00'` → KST aware datetime."""
    return datetime.strptime(spec, '%Y-%m-%d %H:%M').replace(tzinfo=R.KST)


def st(last=None):
    return {'last_published': last}


# ── 회차 계산 ──

def test_publish_day_counts_only_after_the_grace_hour():
    """루틴이 도는 중(11:00~14:00)에 「비었다」고 하면 매 회차 아침이 오경보다."""
    assert R.last_due_round(at('2026-09-17 15:00')).isoformat() == '2026-09-17'
    # 같은 목요일 아침 — 아직 이번 회차를 세지 않고 직전 월요일로 물러난다.
    assert R.last_due_round(at('2026-09-17 11:30')).isoformat() == '2026-09-14'


def test_non_publish_day_falls_back_to_the_previous_round():
    # 화·수요일에는 직전 월요일이 마지막 회차다.
    assert R.last_due_round(at('2026-09-16 09:00')).isoformat() == '2026-09-14'
    # 일요일에는 직전 목요일.
    assert R.last_due_round(at('2026-09-20 09:00')).isoformat() == '2026-09-17'


def test_rounds_before_this_cadence_are_not_judged():
    """주간·3일 주기 시절 날짜를 이 주기의 회차로 세면 과거가 통째로 「밀림」이 된다.
    A01 을 손으로 낸 09-13(일)도 예정 회차가 아니다 — 첫 예정 회차는 09-14(월)이다."""
    assert R.last_due_round(at('2026-09-10 15:00')) is None
    assert R.last_due_round(at('2026-09-13 15:00')) is None


# ── 밀림 판정 ──

def test_overdue_when_the_round_is_not_in_the_ledger():
    got = R.overdue(st('2026-09-13'), at('2026-09-14 15:00'))
    assert got is not None
    due, last = got
    assert due.isoformat() == '2026-09-14' and last == '2026-09-13'


def test_an_empty_ledger_is_the_shape_of_the_silent_failure():
    """09-10 이 죽었을 때 원장은 비어 있었다 — 이력에서 거꾸로 세는 감시는 기준점이 없어
    이 상태를 못 잡는다. 달력에서 회차를 먼저 구하는 이유가 이것뿐이다."""
    assert R.overdue(st(None), now=at('2026-09-14 15:00')) is not None
    assert '없음' in R.note(st(None), now=at('2026-09-14 15:00'))


def test_quiet_when_the_round_is_served():
    assert R.overdue(st('2026-09-14'), now=at('2026-09-14 15:00')) is None
    assert R.note(st('2026-09-14'), now=at('2026-09-14 15:00')) == ''


def test_the_grace_boundary_is_exact():
    """13:59 에 「비었다」고 하면 아직 도는 중인 루틴을 매 회차 고발한다."""
    assert R.overdue(st('2026-09-13'), now=at('2026-09-14 13:59')) is None
    assert R.overdue(st('2026-09-13'), now=at('2026-09-14 14:00')) is not None


def test_a_late_manual_publish_still_serves_the_round():
    """하루 늦게 손으로 낸 것도 회차를 메운 것이다 — 아니면 매번 오경보가 난다."""
    assert R.overdue(st('2026-09-15'), now=at('2026-09-16 09:00')) is None


def test_note_names_the_round_and_where_to_look():
    line = R.note(st('2026-09-13'), now=at('2026-09-14 15:00'))
    assert '2026-09-14' in line and '월' in line and 'list_runs' in line


# ── 오경보를 만드는 것들 ──

class _Exhausted:
    def next_lesson(self, completed):
        return None


class _HasNext:
    def next_lesson(self, completed):
        return 'A02'


def test_an_exhausted_syllabus_is_not_an_outage():
    """정상 정지(`syllabus.py` fail-closed)를 장애로 말하면 승격 전까지 매 세션 거짓
    경고가 뜨고, 그때부터 이 줄은 아무도 안 읽는다."""
    line = R.note(st('2026-09-13'), _Exhausted(), at('2026-09-14 15:00'))
    assert '소진' in line and '장애가 아니다' in line
    assert 'list_runs' not in line


def test_an_outage_still_reads_as_an_outage_when_lessons_remain():
    line = R.note(st('2026-09-13'), _HasNext(), at('2026-09-14 15:00'))
    assert 'list_runs' in line


def test_a_non_date_last_published_is_not_a_future_publication():
    """문자열 비교라 `"9999-99-99"` 가 들어오면 영원히 「발행됨」으로 읽힌다."""
    assert R.overdue(st('9999-99-99'), now=at('2026-09-14 15:00')) is not None
    assert '날짜가 아니다' in R.note(st('9999-99-99'), now=at('2026-09-14 15:00'))


def test_the_later_ledger_wins(tmp_path, monkeypatch):
    """작업 폴더만 보면 며칠 안 받아 온 것만으로 매 세션 오경보다."""
    import json
    (tmp_path / 'china/data').mkdir(parents=True)
    (tmp_path / 'china/data/curriculum_state.json').write_text(
        json.dumps({'last_published': '2026-09-13'}))

    class _Done:
        returncode = 0
        stdout = json.dumps({'last_published': '2026-09-17'})

    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: _Done())
    assert R.ledger(str(tmp_path))['last_published'] == '2026-09-17'


def test_the_working_tree_is_used_when_origin_has_no_ledger(tmp_path, monkeypatch):
    import json
    (tmp_path / 'china/data').mkdir(parents=True)
    (tmp_path / 'china/data/curriculum_state.json').write_text(
        json.dumps({'last_published': '2026-09-14'}))

    class _Missing:
        returncode = 128
        stdout = ''

    monkeypatch.setattr(R.subprocess, 'run', lambda *a, **k: _Missing())
    assert R.ledger(str(tmp_path))['last_published'] == '2026-09-14'
