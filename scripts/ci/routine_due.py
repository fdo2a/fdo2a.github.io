#!/usr/bin/env python3
"""재시도 루틴의 첫 단계 — 모델 없이 「지금 돌 일이 있는가」를 판정한다 (2026-09-27).

    python3 scripts/ci/routine_due.py us|kr|weekly|japan|jp_daily  # 한 줄: DONE|BUSY|WAIT|DUE <이유>
    python3 scripts/ci/routine_due.py lock-name us|kr|jp_daily  # 루틴 잠금 이름 (run_lock.sh key 가 부른다)
    python3 scripts/ci/routine_due.py jp-session       # 일본 일간 세션·직전 세션 (잠금 전에 고정)
    python3 scripts/ci/routine_due.py japan-key        # 일본 주간 키·그 주 금요일·MOF 게시일 (STEP 0)
    python3 scripts/ci/routine_due.py week-key         # 달력상 이번 주 키 (주간 STEP 0 이 맞대 본다)
    python3 scripts/ci/routine_due.py week-end         # 달력상 그 주 마지막 US 거래일 (주간 스냅샷 기본 종료일)
    python3 scripts/ci/routine_due.py monthly          # 월간 STEP 0: DONE|WAIT|BLOCKED|DUE <KEY> <남은 시장·이유>

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
TOKYO = ZoneInfo('Asia/Tokyo')
STALE_MIN = {'us': 120, 'kr': 120, 'weekly': 240, 'japan': 240, 'jp_daily': 120}


def _trading_back(d, holidays=()):
    hol = set(holidays)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= timedelta(days=1)
    return d


def us_session(now, holidays=()):
    return _trading_back((now.astimezone(NY) - timedelta(hours=17)).date(), holidays).isoformat()


def kr_session(now, holidays=()):
    return _trading_back((now.astimezone(SEOUL) - timedelta(hours=16)).date(), holidays).isoformat()


def jp_session(now, holidays=()):
    """일본 일간의 기대 세션 — 도쿄 15:30 마감 전이면 직전 거래일. 루틴이 잠금 전에 한 번 정한다."""
    return _trading_back((now.astimezone(TOKYO) - timedelta(hours=15, minutes=30)).date(),
                         holidays).isoformat()


def jp_prev_session(session, holidays=()):
    return _trading_back(date.fromisoformat(session) - timedelta(days=1), holidays).isoformat()


def week_of(now, holidays=()):
    """주간 키 — 그 주 마지막 거래일(US 기대 세션)의 ISO 주. 데이터 날짜가 아니다(codex #4)."""
    y, w, _ = date.fromisoformat(us_session(now, holidays)).isocalendar()
    return f'{y}-W{w:02d}'


def japan_key(now):
    """일본 주간의 키 — 서울 날짜보다 **앞선** 마지막 금요일이 속한 ISO 주. JAPAN_ORCHESTRATOR STEP 0 이
    `japan-key` 로 이 값을 쓴다. 발행이 월·화로 밀려도 지난주를 가리킨다(2026-10-04)."""
    d = now.astimezone(SEOUL).date() - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    y, w, _ = d.isocalendar()
    return f'{y}-W{w:02d}'


def japan_friday(key):
    y, w = key.split('-W')
    return date.fromisocalendar(int(y), int(w), 5)


def japan_post_day(key, holidays=()):
    """MOF 가 그 주 마지막 도쿄 거래일의 커브를 올리는 날 — 다음 도쿄 영업일(2026-10-04 실측: 금요일분은
    주말에 없다). 보통 월요일, 월요일이 휴장이면 그 뒤. 휴장은 달력(JPX)으로만 본다."""
    last = _trading_back(japan_friday(key), holidays)
    return _trading_forward(last + timedelta(days=1), holidays)


def _trading_forward(d, holidays=()):
    hol = set(holidays)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d += timedelta(days=1)
    return d


def decide_japan(key, files, lock_age, today, holidays=()):
    path = f'japan/posts/{key}.html'
    if path in files:
        return 'DONE', f'{key} 발행 완료'
    post = japan_post_day(key, holidays)
    if today < post:
        return 'WAIT', f'{key} MOF 금요일 커브 게시일({post.isoformat()}) 전'
    if lock_age is not None and lock_age < STALE_MIN['japan']:
        return 'BUSY', f'{key} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{key} 미발행: {path}'


def lock_name(kind, now, key=None, holidays=()):
    """루틴이 잡는 이름 그대로 — `run_lock.sh key <prefix>` 가 이 함수를 부른다.

    **이름은 거래 세션이다.** 달력 날짜로 지으면 추석 사흘 동안 같은 9/23 세션을 처리하는
    런들이 서로 다른 잠금을 잡아 겹쳐 쓸 수 있다(구현 재검토 #1).
    """
    if kind == 'us':
        return f'us-{us_session(now, holidays)}'
    if kind == 'kr':
        return f'kr-{kr_session(now, holidays)}'
    if kind == 'japan':
        return f'japan-{key}'
    if kind == 'jp_daily':
        return f'jpd-{jp_session(now, holidays)}'
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


JP_LATE_HOURS = 6     # 자정을 넘긴 재시도가 어제 세션을 이어받는 창(JST)


def decide_jp_daily(now, files, lock_age, holidays=()):
    """보충 발행은 없다 — 기대 세션이 오늘(JST, 06시 전이면 어제)이 아니면 SKIP(codex 구현 검토 #11).
    휴장일·주말 저녁에 직전 미발행 세션을 DUE 로 돌려주면 루틴이 지난 세션을 발행한다."""
    session = jp_session(now, holidays)
    jst = now.astimezone(TOKYO)
    allowed = {jst.date().isoformat()}
    if jst.hour < JP_LATE_HOURS:
        allowed.add((jst.date() - timedelta(days=1)).isoformat())
    if session not in allowed:
        return 'SKIP', f'{session} 세션은 오늘 발행 대상이 아니다 — 보충 발행 없음'
    return _daily(session, files, lock_age, STALE_MIN['jp_daily'],
                  lambda d: (f'japan/daily/{d}.html',))


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


MONTHLY_POSTS = {'us': 'monthly/{}.html', 'kr': 'kr/monthly/{}.html'}


def decide_monthly(today, report_dates, aggs, files, holidays):
    """월간 STEP 0 — (판정, KEY, 남은 시장 csv 또는 이유). 2026-10-27 codex 설계 검토.

    KEY 는 서울 달력의 직전 달이다. report_date 의 달로 만들면 새 달 키가 되고(11/02 → 2026-11),
    report_date 의 직전 달로 만들면 수집이 밀린 날 지난달보다 한 달 앞을 소급 발행한다.
    `complete` 는 「본 세션 사이에 빈 날이 없다」일 뿐 달이 닫혔다는 뜻이 아니라서, 그 시장
    report_date 가 KEY 를 넘었는지와 집계 end_date 가 그 달 마지막 거래일인지를 따로 본다.
    이미 나간 시장의 데이터·집계는 보지 않는다(주간 codex #6).
    """
    from us.period import month_key, prev_month_key
    key = prev_month_key(today.isoformat())
    missing = [m for m in ('us', 'kr') if MONTHLY_POSTS[m].format(key) not in files]
    if not missing:
        return 'DONE', key, '발행 완료'
    early = [m for m in missing if not report_dates.get(m) or month_key(report_dates[m]) <= key]
    if early:
        return 'WAIT', key, f'데이터가 아직 {key} 를 넘지 않았다: {",".join(early)}'
    first = date(*(int(x) for x in key.split('-')), 1)
    days = [first + timedelta(days=i) for i in range(31)]
    bad = []
    # STEP 3 스코어카드는 US 집계로 만들므로 KR 만 남아도 US 집계는 있어야 한다(구현 검토 #2).
    for m in [m for m in ('us', 'kr') if m in missing or m == 'us']:
        agg = aggs.get(m) or {}
        hol = set(holidays.get(m, ()))
        want = [d.isoformat() for d in days
                if d.month == first.month and d.weekday() < 5 and d.isoformat() not in hol]
        if not agg.get('complete'):
            bad.append(f'{m} 집계 없음·불완전')
        elif agg.get('end_date') != want[-1]:
            bad.append(f'{m} 집계 끝 {agg.get("end_date")} ≠ 마지막 거래일 {want[-1]}')
        elif agg.get('sessions') != len(want):
            # 끝날만 맞고 중간·앞이 빈 집계도 complete 다(구현 검토 #1).
            bad.append(f'{m} 집계 {agg.get("sessions")}거래일 ≠ 달력 {len(want)}거래일')
    if bad:
        return 'BLOCKED', key, '; '.join(bad)
    return 'DUE', key, ','.join(missing)


# ── git 에서 사실을 모은다 ──────────────────────────────────────────────────────

def _git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=60)


def _show_json(path, ref='origin/main'):
    out = _git('show', f'{ref}:{path}')
    try:
        return json.loads(out.stdout) if out.returncode == 0 else None
    except ValueError:
        return None


def _holidays(market, ref='origin/main'):
    """달력의 그 시장 휴장일. 원격 판 → 작업 폴더 판 순. 못 읽으면 빈 목록 — 판정이 DUE 쪽으로 기운다."""
    cal = _show_json('data/market_holidays.json', ref)
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


def _files(*dirs, ref='origin/main'):
    out = _git('ls-tree', '-r', '--name-only', ref, '--', *dirs)
    return set(out.stdout.split())


def _lock_age(name, now):
    """잠금의 마지막 갱신 이후 분. 잠금이 없거나 `released` 표시면 None — run_lock.sh 와 같은 규칙.

    클라우드에서 ref 삭제가 거부돼 release 는 ref 를 지우지 않고 표시 커밋으로 바꾼다
    (2026-10-20). 표시를 살아 있는 잠금으로 읽으면 쓰지 않고 끝난 런이 120분 동안 BUSY 를 만든다.
    """
    ref = f'refs/heads/locks/{name}'
    seen = f'refs/run_lock/{name}'
    if not _git('ls-remote', 'origin', ref).stdout.strip():
        return None
    if _git('fetch', '-q', 'origin', f'+{ref}:{seen}').returncode:
        return None
    out = _git('log', '-1', '--format=%ct%n%s', seen).stdout.split('\n')
    if len(out) < 2 or not out[0].strip().isdigit():
        return None
    if out[1].startswith('released '):
        return None
    return max(0, int((now.timestamp() - int(out[0])) // 60))


def main(argv=None):
    args = argv or sys.argv[1:] or ['']
    if args[0] == 'lock-name':
        if len(args) < 2 or args[1] not in ('us', 'kr', 'jp_daily'):
            print('usage: routine_due.py lock-name us|kr|jp_daily', file=sys.stderr)
            return 2
        market = 'jp' if args[1] == 'jp_daily' else args[1]
        print(lock_name(args[1], datetime.now(timezone.utc), holidays=_holidays(market)))
        return 0
    if args[0] == 'week-end':
        # 주간 스냅샷 워크플로의 기본 종료일 — 달력상 그 주 마지막 US 거래일.
        print(us_session(datetime.now(timezone.utc), _holidays('us')))
        return 0
    if args[0] == 'japan-key':
        # 일본 STEP 0 — 키, 그 주 금요일(스냅샷 종료일), MOF 게시일.
        key = japan_key(datetime.now(timezone.utc))
        print(key, japan_friday(key).isoformat(), japan_post_day(key, _holidays('jp')).isoformat())
        return 0
    if args[0] == 'jp-session':
        # 일본 일간 STEP 0 — 잠금 전에 세션과 직전 세션을 고정한다(codex 설계 검토 #11).
        hol = _holidays('jp')
        s = jp_session(datetime.now(timezone.utc), hol)
        print(s, jp_prev_session(s, hol))
        return 0
    if args[0] == 'week-key':
        # 주간 오케스트레이터가 데이터로 정한 키와 맞대 본다 — 다르면 데이터가 밀린 것이다.
        print(week_of(datetime.now(timezone.utc), _holidays('us')))
        return 0
    if args[0] == 'monthly':
        return _monthly()
    kind = args[0]
    if kind not in ('us', 'kr', 'weekly', 'japan', 'jp_daily'):
        print('usage: routine_due.py us|kr|weekly|japan|jp_daily', file=sys.stderr)
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
    elif kind == 'jp_daily':
        hol = _holidays('jp')
        verdict = decide_jp_daily(now, _files('japan/daily'),
                                  _lock_age(lock_name('jp_daily', now, holidays=hol), now), hol)
    elif kind == 'japan':
        key = japan_key(now)
        verdict = decide_japan(key, _files('japan/posts'),
                               _lock_age(lock_name('japan', now, key), now),
                               now.astimezone(SEOUL).date(), _holidays('jp'))
    else:
        key = week_of(now, _holidays('us'))
        aggs = {'us': _show_json(f'data/weekly/{key}.json'),
                'kr': _show_json(f'kr/data/weekly/{key}.json')}
        verdict = decide_weekly(key, aggs, _files('weekly', 'kr/weekly'),
                                _lock_age(lock_name('weekly', now, key), now))
    print(' '.join(verdict))
    return 0


def _monthly():
    """월간은 KEY 가 있어야 진행하므로 판정 불가를 DUE 로 보내지 않는다 — BLOCKED 로 알린다.

    사실은 fetch 한 origin/main 이 아니라 오케스트레이터가 pull 해 둔 HEAD 에서 읽는다 — 판정과
    작성이 같은 커밋을 봐야 한다(구현 검토 #3). 이미 나간 글을 놓쳐도 STEP 6 의 재확인이 막는다.
    """
    today = datetime.now(timezone.utc).astimezone(SEOUL).date()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    from us.period import prev_month_key
    key = prev_month_key(today.isoformat())
    try:
        rds = {m: (_show_json(p, 'HEAD') or {}).get('report_date')
               for m, p in (('us', 'data/market_data.json'), ('kr', 'kr/data/kr_market_data.json'))}
        aggs = {'us': _show_json(f'data/monthly/{key}.json', 'HEAD'),
                'kr': _show_json(f'kr/data/monthly/{key}.json', 'HEAD')}
        files = _files('monthly', 'kr/monthly', ref='HEAD')
        hol = {'us': _holidays('us', 'HEAD'), 'kr': _holidays('kr', 'HEAD')}
    except (subprocess.SubprocessError, OSError) as e:
        print(f'BLOCKED {key} git 실패 — 판정 불가: {type(e).__name__}')
        return 0
    print(' '.join(decide_monthly(today, rds, aggs, files, hol)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
