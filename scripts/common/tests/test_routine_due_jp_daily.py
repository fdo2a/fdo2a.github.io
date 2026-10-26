"""일본 일간 — 도쿄 세션·잠금·발행 판정 (2026-10-27).

세션은 잠금 전에 고정한다(codex 설계 검토 #11). 자정을 넘긴 재시도가 새 달력 날짜로
넘어가면 어제 세션을 놓친다.
"""
from datetime import datetime, timezone
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'routine_due', os.path.join(HERE, '..', '..', 'ci', 'routine_due.py'))
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_jp_session_evening():
    assert rd.jp_session(utc(2026, 10, 26, 10, 0)) == '2026-10-26'      # 19:00 KST


def test_jp_session_before_close():
    assert rd.jp_session(utc(2026, 10, 26, 5, 0)) == '2026-10-23'       # 14:00 KST 월요일


def test_jp_session_after_midnight():
    assert rd.jp_session(utc(2026, 10, 26, 15, 30)) == '2026-10-26'     # 10/27 00:30 KST


def test_jp_session_skips_holiday():
    assert rd.jp_session(utc(2026, 11, 3, 10, 0), ('2026-11-03',)) == '2026-11-02'


def test_jp_prev_session_holiday():
    assert rd.jp_prev_session('2026-11-04', ('2026-11-03',)) == '2026-11-02'
    assert rd.jp_prev_session('2026-10-26') == '2026-10-23'


def test_decide_jp_daily_done_busy_due():
    now = utc(2026, 10, 26, 10, 0)
    assert rd.decide_jp_daily(now, {'japan/daily/2026-10-26.html'}, None)[0] == 'DONE'
    assert rd.decide_jp_daily(now, set(), 30)[0] == 'BUSY'
    assert rd.decide_jp_daily(now, set(), rd.STALE_MIN['jp_daily'] + 1)[0] == 'DUE'
    assert rd.decide_jp_daily(now, {'japan/posts/2026-W43.html'}, None)[0] == 'DUE'


def test_lock_name_jp_daily():
    assert rd.lock_name('jp_daily', utc(2026, 10, 26, 15, 30)) == 'jpd-2026-10-26'


def test_lock_name_cli_accepts_jp_daily(capsys, monkeypatch):
    monkeypatch.setattr(rd, '_holidays', lambda m: ())
    assert rd.main(['lock-name', 'jp_daily']) == 0
    assert capsys.readouterr().out.startswith('jpd-')


def test_jp_session_cli(capsys, monkeypatch):
    monkeypatch.setattr(rd, '_holidays', lambda m: ())
    assert rd.main(['jp-session']) == 0
    s, prev = capsys.readouterr().out.split()
    assert prev < s


def test_weekly_japan_lock_unchanged():
    assert rd.lock_name('japan', utc(2026, 10, 26, 10, 0), 'W43') == 'japan-W43'
