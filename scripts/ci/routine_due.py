#!/usr/bin/env python3
"""재시도 루틴의 첫 단계 — 모델 없이 「지금 돌 일이 있는가」를 판정한다 (2026-09-27).

    python3 scripts/ci/routine_due.py us|kr|weekly     # 한 줄: DONE|BUSY|WAIT|DUE <이유>
    python3 scripts/ci/routine_due.py lock-name us|kr  # 루틴 잠금 이름 (run_lock.sh key 가 부른다)

본 루틴이 5시간 한도로 죽으면 다시 띄울 장치가 없었다(9/25 US 뉴스·산업 브리프). 재시도
루틴이 3시간마다 뜨고, 이 스크립트가 `DUE` 일 때만 오케스트레이터를 읽는다. 나머지는 곧바로
끝난다 — 할 일이 없는 재시도가 오케스트레이터를 읽으면 그 자체가 한도를 태운다.

판정 순서는 루틴과 같다: **기대 세션을 먼저 정하고**(데이터에 적힌 날짜가 아니다 — 수집이
밀린 날 어제 글이 있다고 끝내면 오늘 글이 영영 안 나온다), 그 세션의 글이 다 있으면 DONE,
그 세션의 잠금이 살아 있으면 BUSY, 아니면 DUE. 주간은 남은 시장의 집계가 불완전하면 WAIT —
주간 루틴은 집계를 다시 만들지 않으므로 돌려도 같은 자리에서 멈춘다.

**휴장은 달력(`data/market_holidays.json`)으로만 판정한다.** 「마감 뒤 수집했는데 날짜가
이전」은 휴장과 시세 지연을 가르지 못해, 지연된 거래일을 휴장으로 보고 글을 조용히 건너뛴다
(codex 구현 검토 #2). 달력에 없는 휴장일은 DUE 로 떨어져 재시도가 헛돌 뿐이다 — 틀리는 방향을
토큰 쪽으로 둔다.

잠금의 최종 판정은 `run_lock.sh acquire` 다. 여기서 BUSY 는 그 날짜 키의 잠금이 stale
기준보다 젊을 때뿐이다.

설계: docs/superpowers/specs/2026-09-27-routine-retry-after-limit.md
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
SEOUL = ZoneInfo('Asia/Seoul')
STALE_MIN = {'us': 120, 'kr': 120, 'weekly': 240}


def _trading_back(d, holidays=()):
    hol = set(holidays)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= timedelta(days=1)
    return d


def us_session(now, holidays=()):
    return _trading_back((now.astimezone(NY) - timedelta(hours=17)).date(), holidays).isoformat()


def kr_session(now, holidays=()):
    return _trading_back((now.astimezone(SEOUL) - timedelta(hours=16)).date(), holidays).isoformat()


def week_of(now, holidays=()):
    """주간 키 — 그 주 마지막 거래일(US 기대 세션)의 ISO 주. 데이터 날짜가 아니다(codex #4)."""
    y, w, _ = date.fromisoformat(us_session(now, holidays)).isocalendar()
    return f'{y}-W{w:02d}'


def lock_name(kind, now, key=None, holidays=()):
    """루틴이 잡는 이름 그대로 — `run_lock.sh key <prefix>` 가 이 함수를 부른다.

    **이름은 거래 세션이다.** 달력 날짜로 지으면 추석 사흘 동안 같은 9/23 세션을 처리하는
    런들이 서로 다른 잠금을 잡아 겹쳐 쓸 수 있다(구현 재검토 #1).
    """
    if kind == 'us':
        return f'us-{us_session(now, holidays)}'
    if kind == 'kr':
        return f'kr-{kr_session(now, holidays)}'
    return f'weekly-{key}'


def _daily(session, files, lock_age, stale, want):
    missing = [p for p in want(session) if p not in files]
    if not missing:
        return 'DONE', f'{session} 발행 완료'
    if lock_age is not None and lock_age < stale:
        return 'BUSY', f'{session} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{session} 미발행: {", ".join(missing)}'


def decide_us(now, files, lock_age, holidays=()):
    return _daily(us_session(now, holidays), files, lock_age, STALE_MIN['us'],
                  lambda d: (f'posts/{d}.html', f'news/{d}.html'))


def decide_kr(now, files, lock_age, holidays=()):
    return _daily(kr_session(now, holidays), files, lock_age, STALE_MIN['kr'],
                  lambda d: (f'kr/posts/{d}.html',))


def decide_weekly(key, aggs, files, lock_age):
    want = {'us': f'weekly/{key}.html', 'kr': f'kr/weekly/{key}.html'}
    missing = {m: p for m, p in want.items() if p not in files}
    if not missing:
        return 'DONE', f'{key} 발행 완료'
    # 남은 시장의 집계만 본다 — 이미 나간 쪽 집계가 사라졌다고 남은 글을 막지 않는다(codex #6).
    bad = [m for m in missing if not (aggs.get(m) or {}).get('complete')]
    if bad:
        return 'WAIT', f'{key} 집계 불완전: {", ".join(bad)} — 주간 루틴이 고칠 수 없다'
    if lock_age is not None and lock_age < STALE_MIN['weekly']:
        return 'BUSY', f'{key} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{key} 미발행: {", ".join(missing.values())}'


# ── git 에서 사실을 모은다 ──────────────────────────────────────────────────────

def _git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=60)


def _show_json(path):
    out = _git('show', f'origin/main:{path}')
    try:
        return json.loads(out.stdout) if out.returncode == 0 else None
    except ValueError:
        return None


def _holidays(market):
    """달력의 그 시장 휴장일. 원격 판 → 작업 폴더 판 순. 못 읽으면 빈 목록 — 판정이 DUE 쪽으로 기운다."""
    cal = _show_json('data/market_holidays.json')
    if cal is None:
        try:
            here = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                                'data', 'market_holidays.json')
            with open(here, encoding='utf-8') as fh:
                cal = json.load(fh)
        except (OSError, ValueError):
            cal = {}
    got = (cal or {}).get(market) or {}
    days = got.get('dates')
    return tuple(days) if isinstance(days, list) else ()


def _files(*dirs):
    out = _git('ls-tree', '-r', '--name-only', 'origin/main', '--', *dirs)
    return set(out.stdout.split())


def _lock_age(name, now):
    ref = f'refs/heads/locks/{name}'
    if not _git('ls-remote', 'origin', ref).stdout.strip():
        return None
    if _git('fetch', '-q', 'origin', ref).returncode:
        return None
    s = _git('log', '-1', '--format=%ct', 'FETCH_HEAD').stdout.strip()
    return int((now.timestamp() - int(s)) // 60) if s else None


def main(argv=None):
    args = argv or sys.argv[1:] or ['']
    if args[0] == 'lock-name':
        if len(args) < 2 or args[1] not in ('us', 'kr'):
            print('usage: routine_due.py lock-name us|kr', file=sys.stderr)
            return 2
        print(lock_name(args[1], datetime.now(timezone.utc), holidays=_holidays(args[1])))
        return 0
    kind = args[0]
    if kind not in ('us', 'kr', 'weekly'):
        print('usage: routine_due.py us|kr|weekly', file=sys.stderr)
        return 2
    if _git('fetch', '-q', 'origin', 'main').returncode:
        # 판정 불가는 DUE 로 보낸다 — 틀려도 오케스트레이터의 가드가 막는다. 반대로
        # DONE 으로 보내면 글이 조용히 빠진다.
        print('DUE fetch 실패 — 오케스트레이터가 판정한다')
        return 0
    now = datetime.now(timezone.utc)
    if kind == 'us':
        hol = _holidays('us')
        verdict = decide_us(now, _files('posts', 'news'),
                            _lock_age(lock_name('us', now, holidays=hol), now), hol)
    elif kind == 'kr':
        hol = _holidays('kr')
        verdict = decide_kr(now, _files('kr/posts'),
                            _lock_age(lock_name('kr', now, holidays=hol), now), hol)
    else:
        key = week_of(now, _holidays('us'))
        aggs = {'us': _show_json(f'data/weekly/{key}.json'),
                'kr': _show_json(f'kr/data/weekly/{key}.json')}
        verdict = decide_weekly(key, aggs, _files('weekly', 'kr/weekly'),
                                _lock_age(lock_name('weekly', now, key), now))
    print(' '.join(verdict))
    return 0


if __name__ == '__main__':
    sys.exit(main())
