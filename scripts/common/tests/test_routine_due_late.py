"""늦은 글 — 지난 US 세션을 그날 자료로 (2026-11-27).

11/24 글은 발행 전 검사에 세워졌고, 고친 코드가 올라온 뒤에도 11/25 글이 나가자 재시도 판정이 현재 세션만 봐
다시 보지 않았다. 현재 세션이 DONE·HOLD 일 때만 최근 5거래일의 빠진 세션을 `LATE` 로 낸다 — 본 글이 먼저다.
설계: ../plans/attachments/2026-11-17-prepub-all/auto_resume_design_v2.md §2.2 (로컬)
"""
from datetime import datetime, timezone
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'routine_due_late', os.path.join(HERE, '..', '..', 'ci', 'routine_due.py'))
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)

THANKSGIVING = ('2026-11-26',)
# 11/27 07:00 KST = 11/26 17:00 ET(추수감사절) — 현재 세션은 11/25
NOW = datetime(2026, 11, 26, 22, 0, tzinfo=timezone.utc)


def both(*days):
    return {p for d in days for p in (f'posts/{d}.html', f'news/{d}.html')}


PUBLISHED = both('2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-23', '2026-11-25')


def late(files, locks=None, now=NOW, collected=lambda d: True, current=None):
    current = current or rd.decide_us(now, files, None, THANKSGIVING)
    return rd.decide_us_late(now, files, current, locks or {}, THANKSGIVING, collected)


def test_window_is_the_five_sessions_before_the_current_one_across_thanksgiving():
    assert rd.us_session(NOW, THANKSGIVING) == '2026-11-25'
    assert rd.us_late_sessions(NOW, THANKSGIVING) == [
        '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-23', '2026-11-24']
    # 월요일 11/30 세션 — 휴장 11/26 을 건너 다섯
    mon = datetime(2026, 11, 30, 22, 0, tzinfo=timezone.utc)
    assert rd.us_late_sessions(mon, THANKSGIVING) == [
        '2026-11-20', '2026-11-23', '2026-11-24', '2026-11-25', '2026-11-27']


def test_a_released_missed_session_is_late():
    verdict = late(PUBLISHED)
    assert verdict == ('LATE', '2026-11-24 미발행: posts/2026-11-24.html, news/2026-11-24.html')


def test_a_held_missed_session_is_not_late():
    assert late(PUBLISHED, {'2026-11-24': (3000, 'held')})[0] == 'DONE'


def test_a_dead_judging_mark_waits_for_a_person_like_today():
    assert late(PUBLISHED, {'2026-11-24': (999, 'judging')})[0] == 'DONE'


def test_a_late_run_in_progress_is_busy_and_only_one_runs():
    word, why = late(PUBLISHED - both('2026-11-20'), {'2026-11-24': (10, None)})
    assert word == 'BUSY' and why.startswith('2026-11-24 ')


def test_the_oldest_late_session_goes_first():
    assert late(PUBLISHED - both('2026-11-19'))[1].startswith('2026-11-19 ')


def test_a_missing_news_post_alone_is_late():
    files = PUBLISHED | {'posts/2026-11-24.html'}
    assert late(files) == ('LATE', '2026-11-24 미발행: news/2026-11-24.html')


def test_no_collection_commit_is_no_target():
    """달력에 없는 휴장일은 수집 커밋이 없다 — LATE 로 다섯 날 동안 헛발화하지 않는다."""
    assert late(PUBLISHED, collected=lambda d: d != '2026-11-24')[0] == 'DONE'


def test_outside_the_window_is_not_late():
    assert late((PUBLISHED | both('2026-11-24')) - both('2026-11-17'))[0] == 'DONE'


@pytest.mark.parametrize('word', ['DUE', 'BUSY'])
def test_the_current_session_goes_first(word):
    current = (word, '2026-11-25 x')
    assert late(PUBLISHED, current=current) == current


def test_a_held_current_session_lets_a_late_one_run():
    assert late(PUBLISHED, current=('HOLD', '2026-11-25 세움'))[0] == 'LATE'


def test_lock_name_takes_an_explicit_session():
    assert rd.lock_name('us', NOW, holidays=THANKSGIVING) == 'us-2026-11-25'
    assert rd.lock_name('us', NOW, holidays=THANKSGIVING, session='2026-11-24') == 'us-2026-11-24'


def test_lock_name_cli_session(capsys):
    assert rd.main(['lock-name', 'us', '--session', '2026-11-24']) == 0
    assert capsys.readouterr().out == 'us-2026-11-24\n'
    assert rd.main(['lock-name', 'us', '--session', '11/24']) == 2


def test_main_us_prints_late_when_the_current_session_is_done(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(rd, '_git', lambda *a: type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})())
    monkeypatch.setattr(rd, '_holidays', lambda m, ref='origin/main': THANKSGIVING)
    monkeypatch.setattr(rd, '_files', lambda *a, **k: set(PUBLISHED))

    def state(name, now):
        calls.append(name)
        return (None, None)
    monkeypatch.setattr(rd, '_lock_state', state)
    monkeypatch.setattr(rd, '_us_collected', lambda d: True)
    monkeypatch.setattr(rd, 'datetime', type('D', (), {'now': staticmethod(lambda tz=None: NOW)}))
    assert rd.main(['us']) == 0
    assert capsys.readouterr().out.startswith('LATE 2026-11-24 미발행:')
    # 잠금은 현재 세션과, 글이 빠진 지난 세션만 본다
    assert calls == ['us-2026-11-25', 'us-2026-11-24']
