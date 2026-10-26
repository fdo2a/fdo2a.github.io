"""일본 일간 달력 overlay — `japan/data/calendar_daily.json` (2026-10-27).

주간 달력(`calendar.json`)의 행 의미는 건드리지 않는다. 일간은 회의 기간(`kind: meeting`)과
결과 공표(`kind: release`)를 따로 적어, 회의 시작일에 매크로 절이 위로 오지 않게 한다
(codex 설계 검토 #5). 행마다 원출처 `source`·확인일 `checked_at` — 확인 못 한 날짜는 넣지 않는다.
스냅샷이 당일 행·14일 일정·`version()` 을 고정하고, 재검사는 스냅샷만 본다.

Pure — 네트워크 없음.
"""
import hashlib
import json
from datetime import date, timedelta

PATH = 'japan/data/calendar_daily.json'


def load(path=PATH):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def version(cal):
    canon = json.dumps(cal, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()[:12]


def today_events(cal, session):
    return [e for e in (cal or {}).get('events', []) if e.get('date') == session]


def event_day(cal, session):
    """매크로 절을 위로 올리는 날 — 그날 나온 major 결과 공표뿐이다."""
    return [e for e in today_events(cal, session)
            if e.get('kind') == 'release' and e.get('tier') == 'major']


def upcoming(cal, session, days=14):
    end = (date.fromisoformat(session) + timedelta(days=days)).isoformat()
    rows = [e for e in (cal or {}).get('events', []) if session < (e.get('date') or '') <= end]
    return sorted(rows, key=lambda e: (e['date'], e.get('time_jst') or ''))
