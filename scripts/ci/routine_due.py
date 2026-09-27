#!/usr/bin/env python3
"""재시도 루틴의 첫 단계 — 모델 없이 「지금 돌 일이 있는가」를 판정한다 (2026-09-27).

    python3 scripts/ci/routine_due.py us|kr|weekly     # 한 줄: DONE|BUSY|WAIT|DUE <이유>
    python3 scripts/ci/routine_due.py lock-name us|kr  # 루틴 잠금 이름 (run_lock.sh key 가 부른다)

본 루틴이 5시간 한도로 죽으면 다시 띄울 장치가 없었다(9/25 US 뉴스·산업 브리프). 재시도
루틴이 3시간마다 뜨고, 이 스크립트가 `DUE` 일 때만 오케스트레이터를 읽는다. 나머지는 곧바로
끝난다 — 할 일이 없는 재시도가 오케스트레이터를 읽으면 그 자체가 한도를 태운다.

판정 순서는 루틴과 같다: **기대 세션을 먼저 정하고**(데이터에 적힌 날짜가 아니다 — 수집이
밀린 날 어제 글이 있다고 끝내면 오늘 글이 영영 안 나온다), 그 세션의 글이 다 있으면 DONE,
그 세션의 잠금이 살아 있으면 BUSY, 아니면 DUE. 마감 한참 뒤에 수집했는데도 데이터가 전
세션이면 휴장으로 보고 DONE. 주간은 집계가 불완전하면 WAIT — 주간 루틴은 집계를 다시
만들지 않으므로 돌려도 같은 자리에서 멈춘다.

잠금의 최종 판정은 `run_lock.sh acquire` 다. 여기서 BUSY 는 그 날짜 키의 잠금이 stale
기준보다 젊을 때뿐이다.

설계: docs/superpowers/specs/2026-09-27-routine-retry-after-limit.md
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
SEOUL = ZoneInfo('Asia/Seoul')
STALE_MIN = {'us': 120, 'kr': 120, 'weekly': 180}
# 이 시각 뒤에 **수집기가** 돌았는데도 데이터가 전 세션이면 휴장이다. 소스 지연(네이버
# 국채 종가 17:05 ET, KR 마감 직후)을 휴장으로 오판하면 그날 글이 빠지므로 넉넉히 늦춘다.
US_CLOSE = (18, 0)
KR_CLOSE = (18, 0)
# 휴장일에는 주 데이터 파일이 안 바뀌어 커밋되지 않는다(9/24~26 추석 실측). 수집기 커밋은
# 디렉터리의 다른 파일을 바꾸므로 **수집기 메시지가 붙은 디렉터리 커밋**을 본다 — 아무
# 커밋이나 보면 발행 커밋이 data/macro.json 을 건드린 것을 수집으로 착각한다.
COLLECTOR = {'us': ('data', '^data: market data for'),
             'kr': ('kr/data', '^data: kr market data for')}


def _weekday_back(d):
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def us_session(now):
    return _weekday_back((now.astimezone(NY) - timedelta(hours=17)).date()).isoformat()


def kr_session(now):
    return _weekday_back((now.astimezone(SEOUL) - timedelta(hours=16)).date()).isoformat()


def lock_name(kind, now, key=None):
    """루틴이 잡는 이름 그대로 — `run_lock.sh key <prefix>` 와 같은 규칙."""
    if kind == 'us':
        return f'us-{(now.astimezone(NY) - timedelta(hours=17)).date().isoformat()}'
    if kind == 'kr':
        return f'kr-{(now.astimezone(SEOUL) - timedelta(hours=16)).date().isoformat()}'
    return f'weekly-{key}'


def _after_close(committed, session, tz, hm):
    y, m, d = map(int, session.split('-'))
    return committed is not None and committed >= datetime(y, m, d, *hm, tzinfo=tz)


def _daily(session, data, committed, files, lock_age, stale, want, tz, close):
    got = (data or {}).get('report_date')
    if got and got < session and (data or {}).get('complete') and _after_close(
            committed, session, tz, close):
        return 'DONE', f'{session} 휴장으로 본다 — 마감 뒤 수집이 {got}'
    missing = [p for p in want(session) if p not in files]
    if not missing:
        return 'DONE', f'{session} 발행 완료'
    if lock_age is not None and lock_age < stale:
        return 'BUSY', f'{session} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{session} 미발행: {", ".join(missing)}'


def decide_us(now, data, committed, files, lock_age):
    return _daily(us_session(now), data, committed, files, lock_age, STALE_MIN['us'],
                  lambda d: (f'posts/{d}.html', f'news/{d}.html'), NY, US_CLOSE)


def decide_kr(now, data, committed, files, lock_age):
    return _daily(kr_session(now), data, committed, files, lock_age, STALE_MIN['kr'],
                  lambda d: (f'kr/posts/{d}.html',), SEOUL, KR_CLOSE)


def decide_weekly(key, aggs, files, lock_age):
    want = (f'weekly/{key}.html', f'kr/weekly/{key}.html')
    missing = [p for p in want if p not in files]
    if not missing:
        return 'DONE', f'{key} 발행 완료'
    bad = [m for m, a in aggs.items() if not (a or {}).get('complete')]
    if bad:
        return 'WAIT', f'{key} 집계 불완전: {", ".join(bad)} — 주간 루틴이 고칠 수 없다'
    if lock_age is not None and lock_age < STALE_MIN['weekly']:
        return 'BUSY', f'{key} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{key} 미발행: {", ".join(missing)}'


# ── git 에서 사실을 모은다 ──────────────────────────────────────────────────────

def _git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=60)


def _show_json(path):
    out = _git('show', f'origin/main:{path}')
    try:
        return json.loads(out.stdout) if out.returncode == 0 else None
    except ValueError:
        return None


def _collected(kind):
    path, pattern = COLLECTOR[kind]
    out = _git('log', '-1', '--format=%ct', f'--grep={pattern}', 'origin/main', '--', path)
    s = out.stdout.strip()
    return datetime.fromtimestamp(int(s), timezone.utc) if s else None


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
        print(lock_name(args[1], datetime.now(timezone.utc)))
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
        path = 'data/market_data.json'
        verdict = decide_us(now, _show_json(path), _collected('us'), _files('posts', 'news'),
                            _lock_age(lock_name('us', now), now))
    elif kind == 'kr':
        path = 'kr/data/kr_market_data.json'
        verdict = decide_kr(now, _show_json(path), _collected('kr'), _files('kr/posts'),
                            _lock_age(lock_name('kr', now), now))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from us.period import week_key
        data = _show_json('data/market_data.json') or {}
        if not data.get('report_date'):
            print('DUE 주 키를 못 정했다 — 오케스트레이터가 판정한다')
            return 0
        key = week_key(data['report_date'])
        aggs = {'us': _show_json(f'data/weekly/{key}.json'),
                'kr': _show_json(f'kr/data/weekly/{key}.json')}
        verdict = decide_weekly(key, aggs, _files('weekly', 'kr/weekly'),
                                _lock_age(lock_name('weekly', now, key), now))
    print(' '.join(verdict))
    return 0


if __name__ == '__main__':
    sys.exit(main())
