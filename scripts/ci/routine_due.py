#!/usr/bin/env python3
"""재시도 루틴의 첫 단계 — 모델 없이 「지금 돌 일이 있는가」를 판정한다 (2026-09-27).

    python3 scripts/ci/routine_due.py us|kr|weekly|japan|jp_daily  # 한 줄: DONE|BUSY|WAIT|DUE|HOLD <이유> (HOLD = us 만, 2026-11-22)
                                       # us 는 LATE <D> 미발행: … 도 (현재 세션이 DONE·HOLD 일 때 지난 5거래일의 빠진 글, 2026-11-27)
    python3 scripts/ci/routine_due.py lock-name us|kr|jp_daily  # 루틴 잠금 이름 (run_lock.sh key 가 부른다)
    python3 scripts/ci/routine_due.py lock-name us --session D  # 늦은 글 — 세션을 정한 런의 잠금 이름
    python3 scripts/ci/routine_due.py jp-session       # 일본 일간 세션·직전 세션 (잠금 전에 고정)
    python3 scripts/ci/routine_due.py japan-key        # 일본 주간 키·그 주 금요일·MOF 게시일 (STEP 0)
    python3 scripts/ci/routine_due.py week-key         # 달력상 이번 주 키 (주간 STEP 0 이 맞대 본다)
    python3 scripts/ci/routine_due.py week-end         # 달력상 그 주 마지막 US 거래일 (주간 스냅샷 기본 종료일)
    python3 scripts/ci/routine_due.py weekly-ready KEY # 주간 STEP 1 — DONE|READY <남은 시장>|WAIT|ERROR (잠금을 보지 않는다)

본 루틴이 5시간 한도로 죽으면 다시 띄울 장치가 없었다(9/25 US 뉴스·산업 브리프). 재시도
루틴이 3시간마다 뜨고, 이 스크립트가 `DUE` 일 때만 오케스트레이터를 읽는다. 나머지는 곧바로
끝난다 — 할 일이 없는 재시도가 오케스트레이터를 읽으면 그 자체가 한도를 태운다.

판정 순서는 루틴과 같다: **기대 세션을 먼저 정하고**(데이터에 적힌 날짜가 아니다 — 수집이
밀린 날 어제 글이 있다고 끝내면 오늘 글이 영영 안 나온다), 그 세션의 글이 다 있으면 DONE,
그 세션의 잠금이 살아 있으면 BUSY, 아니면 DUE. 주간은 남은 시장마다 **그 주가 끝났고 집계가 그 마지막
거래일까지 왔을 때만** DUE 다(`weekly_holds`) — 아니면 WAIT. 집계의 `complete` 는 「받은 날짜 안에 빠진
계열이 없다」는 뜻일 뿐이라 주 중간 집계도 참이다(2026-11-19 목요일에 DUE 가 났다). 주간 루틴은 집계를
다시 만들지 않으므로 돌려도 같은 자리에서 멈춘다.

**휴장은 달력(`data/market_holidays.json`)으로만 판정한다.** 「마감 뒤 수집했는데 날짜가
이전」은 휴장과 시세 지연을 가르지 못해, 지연된 거래일을 휴장으로 보고 글을 조용히 건너뛴다
(codex 구현 검토 #2). 일간은 달력에 없는 휴장일이 DUE 로 떨어져 재시도가 헛돌 뿐이다 — 틀리는 방향을
토큰 쪽으로 둔다. **주간은 반대다**: 그 주 마지막 날의 휴장이 달력에 없으면 집계가 「하루 모자란」 것으로
보여 WAIT 로 묶인다(이유에 기대한 날과 실제 끝 날을 적는다). 달력이 그 주 금요일을 덮지 못하면
(`valid_through`) 추측하지 않고 WAIT 「달력이 … 에서 끝난다」. 묶인 주는 retry_gate 가 빨갛게 알린다.
거래일을 휴장으로 잘못 넣으면 하루 일찍 통과한다 — 달력으로는 알 수 없다.

잠금의 최종 판정은 `run_lock.sh acquire` 다. 여기서 BUSY 는 그 날짜 키의 잠금이 stale
기준보다 젊을 때뿐이다.

설계: docs/superpowers/specs/2026-09-27-routine-retry-after-limit.md
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
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
    """US 기대 세션 — 뉴욕 16:45 전이면 직전 거래일. 본 런(16:50 ET, 2026-11-23)보다 먼저 넘어가야 본 런이 오늘 세션을 본다."""
    return _trading_back((now.astimezone(NY) - timedelta(hours=16, minutes=45)).date(), holidays).isoformat()


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


def lock_name(kind, now, key=None, holidays=(), session=None):
    """루틴이 잡는 이름 그대로 — `run_lock.sh key <prefix>` 가 이 함수를 부른다.

    **이름은 거래 세션이다.** 달력 날짜로 지으면 추석 사흘 동안 같은 9/23 세션을 처리하는
    런들이 서로 다른 잠금을 잡아 겹쳐 쓸 수 있다(구현 재검토 #1). `session` = 늦은 글처럼 세션을 이미
    정한 런(`run_lock.sh key us --session <D>`) — US 만.
    """
    if kind == 'us':
        return f'us-{session or us_session(now, holidays)}'
    if kind == 'kr':
        return f'kr-{kr_session(now, holidays)}'
    if kind == 'japan':
        return f'japan-{key}'
    if kind == 'jp_daily':
        return f'jpd-{jp_session(now, holidays)}'
    return f'weekly-{key}'


def _daily(session, files, lock_age, stale, want, flag=None):
    missing = [p for p in want(session) if p not in files]
    if not missing:
        return 'DONE', f'{session} 발행 완료'
    # 발행 전 검사가 세웠거나(held), 받아들인 수정을 고치다 죽었다(판정·수정 표시 + stale) — 사람을 기다린다.
    # 재시도가 처음부터 다시 쓰면 그 수정이 사라진다(2026-11-22). 루틴의 acquire 도 같은 표시에 exit 6 이다.
    if flag == 'held':
        return 'HOLD', f'{session} 발행 전 검사로 세움 — 사람이 unhold 해야 다시 쓴다'
    # 판정·수정 표시는 첫 글(브리프 — 발행 전 검사가 붙은 글)이 없을 때만 본다. 브리프가 나간 뒤 남은 표시는
    # 뉴스 이어 쓰기를 막지 않는다(루틴은 브리프 push 직후 표시를 뗀다 — run_lock.sh renew … clear).
    if flag in ('judging', 'fixing') and missing[0] == want(session)[0] and (lock_age is None or lock_age >= stale):
        return 'HOLD', f'{session} 검토 지적을 {"판정" if flag == "judging" else "수정"}하다 멈춤 ({lock_age}분 무응답) — 사람 확인'
    if lock_age is not None and lock_age < stale:
        return 'BUSY', f'{session} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{session} 미발행: {", ".join(missing)}'


def us_want(d):
    return (f'posts/{d}.html', f'news/{d}.html')


def decide_us(now, files, lock_age, holidays=(), flag=None):
    return _daily(us_session(now, holidays), files, lock_age, STALE_MIN['us'], us_want, flag)


LATE_SESSIONS = 5     # 늦은 글을 내는 창 — 현재 세션 앞의 거래일 수
# 본 런(16:50 ET) 앞 2시간에는 늦은 글을 시작하지 않는다 — 둘이 함께 돌면 연구 원장(해시 사슬)에 동시에 덧붙인다.
# 16:45 ET 에 세션이 넘어가면 현재 세션이 DUE 라 늦은 글은 어차피 기다린다. 휴장일은 본 런이 없어 막지 않는다.
LATE_QUIET = (time(14, 45), time(16, 45))


def us_late_sessions(now, holidays=()):
    """현재 US 세션 **앞의** 5거래일, 오래된 것부터."""
    d, out = date.fromisoformat(us_session(now, holidays)), []
    while len(out) < LATE_SESSIONS:
        d = _trading_back(d - timedelta(days=1), holidays)
        out.append(d.isoformat())
    return out[::-1]


def decide_us_late(now, files, current, locks, holidays=(), collected=lambda d: True):
    """늦은 글 (2026-11-27) — 현재 세션이 DONE·HOLD 일 때만 지난 5거래일의 빠진 세션을 본다.

    지난 세션마다 `_daily` 를 그대로 돌린다: DUE → 늦은 대상, BUSY → 다른 런이 쓰는 중, HOLD·DONE → 대상 아님
    (세움·죽은 판정 표시는 지금처럼 사람 몫). `locks` = {세션: (나이, 표시)} — 없는 세션은 잠금 없음.
    `collected(D)` 가 거짓이면(그날 수집 커밋이 없다 — 달력에 없는 휴장일 등) 대상이 아니다.
    늦은 글은 한 번에 하나: 대상 가운데 하나라도 BUSY 면 BUSY, 아니면 가장 오래된 대상 하나를 LATE.
    """
    if current[0] not in ('DONE', 'HOLD'):
        return current
    ny = now.astimezone(NY)
    if LATE_QUIET[0] <= ny.time() < LATE_QUIET[1] and _trading_back(ny.date(), holidays) == ny.date():
        return current
    busy = due = None
    for s in us_late_sessions(now, holidays):
        age, flag = locks.get(s, (None, None))
        word, why = _daily(s, files, age, STALE_MIN['us'], us_want, flag)
        if word == 'BUSY' and busy is None:
            busy = why
        elif word == 'DUE' and due is None and collected(s):
            due = why
    if busy:
        return 'BUSY', f'{busy} — 늦은 글'
    if due:
        return 'LATE', due
    return current


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


KR_NEWS_FROM = '2026-11-06'     # KR 뉴스 글 분리 — `kr.news.SPLIT_FROM` 과 같다(테스트)
KR_NEWS_CATEGORIES = ('politics', 'policy', 'macro', 'industry', 'global')


def kr_news_expected(collected):
    """그날 KR 뉴스 글이 나와야 하는가 — 요약까지 된 갈래 기사가 하나라도 있으면. 수집분이 없거나 비면
    오케스트레이터가 글을 내지 않으므로(STEP 3.5) 재시도 루틴이 그 글을 영영 기다리지 않게 한다."""
    items = (collected or {}).get('items') if isinstance(collected, dict) else None
    return any(isinstance(it, dict) and it.get('summary_ko') and it.get('category') in KR_NEWS_CATEGORIES
               for it in items or [])


def decide_kr(now, files, lock_age, holidays=(), news_expected=lambda d: False):
    """마감브리프, 그리고 2026-11-06 부터 뉴스 글(실을 기사가 있는 날만). US 처럼 두 글이 다 나와야 DONE —
    브리프 뒤 한도로 죽어 뉴스 글이 빠진 날을 재시도가 잇는다(Fable 설계 검토 M2)."""
    def want(d):
        news = (f'kr/news/{d}.html',) if d >= KR_NEWS_FROM and news_expected(d) else ()
        return (f'kr/posts/{d}.html',) + news
    return _daily(kr_session(now, holidays), files, lock_age, STALE_MIN['kr'], want)


WEEKLY = {'us': ('weekly/{}.html', 'data/weekly/{}.json', us_session),
          'kr': ('kr/weekly/{}.html', 'kr/data/weekly/{}.json', kr_session)}


def weekly_missing(key, files):
    """아직 원격에 없는 주간 글 — {시장: 경로}."""
    return {m: post.format(key) for m, (post, _, _) in WEEKLY.items() if post.format(key) not in files}


def _day(text):
    """날짜로 읽히는 문자열이면 date, 아니면 None. 비교는 글자가 아니라 이 값으로 한다 —
    `2027-W01-1` 도 날짜로 읽히지만 글자로는 11월보다 뒤다(codex 설계 4회차)."""
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def weekly_holds(key, markets, now, cal, aggs=None):
    """그 주 주간을 아직 낼 수 없는 이유들(없으면 낼 수 있다). cal = {시장: (휴장일, valid_through)}.

    시장마다 그 주 금요일에서 휴장을 거슬러 올라간 날이 「마지막 거래일」이다. 그 세션이 닫혔고, 집계가
    complete 이며, 집계의 end_date 가 바로 그 날이어야 한다. `aggs` 가 None 이면(fetch 실패) 시계만 본다.
    """
    friday = japan_friday(key)
    why = []
    for m in markets:
        dates, through = cal.get(m) or ((), None)
        end = _day(through)
        if end is None or friday > end:
            why.append(f'{m} 달력이 {end.isoformat() if end else "읽지 못함"} 에서 끝난다 — data/market_holidays.json 을 채운다')
            continue                              # 마지막 거래일을 모른다 — 아래는 추측이 된다
        last = _trading_back(friday, dates).isoformat()
        if WEEKLY[m][2](now, dates) < last:
            why.append(f'{m} 마지막 거래일 {last} 마감 전')
        if aggs is None:
            continue
        agg = aggs.get(m)
        if not isinstance(agg, dict) or agg.get('complete') is not True:
            why.append(f'{m} 집계 불완전')
        elif agg.get('end_date') != last:
            why.append(f'{m} 집계 끝 {agg.get("end_date")} ≠ 마지막 거래일 {last}')
    return why


def decide_weekly(key, aggs, files, lock_age, now, cal):
    missing = weekly_missing(key, files)
    if not missing:
        return 'DONE', f'{key} 발행 완료'
    # 남은 시장만 본다 — 이미 나간 쪽 집계가 사라졌다고 남은 글을 막지 않는다(codex #6).
    why = weekly_holds(key, missing, now, cal, aggs)
    if why:
        return 'WAIT', f'{key} {"; ".join(why)}'
    if lock_age is not None and lock_age < STALE_MIN['weekly']:
        return 'BUSY', f'{key} 작성 중 (잠금 {lock_age}분 전)'
    return 'DUE', f'{key} 미발행: {", ".join(missing.values())}'


def valid_key(key):
    try:
        y, w = key.split('-W')
        return len(y) == 4 and len(w) == 2 and y.isdigit() and w.isdigit() and bool(japan_friday(key))
    except ValueError:
        return False


# ── git 에서 사실을 모은다 ──────────────────────────────────────────────────────

def _git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=60)


def _show_json(path, ref='origin/main'):
    out = _git('show', f'{ref}:{path}')
    try:
        return json.loads(out.stdout) if out.returncode == 0 else None
    except ValueError:
        return None


ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')


def _tree_json(path):
    """작업 트리의 JSON — 없거나 깨졌으면 None."""
    try:
        with open(os.path.join(ROOT, path), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _calendar(market, ref='origin/main'):
    """(그 시장 휴장일, valid_through). 원격 판 → 작업 폴더 판 순. 못 읽으면 ((), None).
    valid_through 는 날짜로 읽히는 문자열일 때만(YYYY-MM-DD 로 고쳐 돌려준다) — 아니면 None(주간 판정이 「달력 끝」으로 멈춘다)."""
    cal = _show_json('data/market_holidays.json', ref)
    if cal is None:
        cal = _tree_json('data/market_holidays.json')
    got = cal.get(market) if isinstance(cal, dict) else None
    days = got.get('dates') if isinstance(got, dict) else None
    if not isinstance(days, list):
        return (), None
    end = _day(got.get('valid_through'))
    return tuple(days), end.isoformat() if end else None


def _holidays(market, ref='origin/main'):
    """달력의 그 시장 휴장일. 못 읽으면 빈 목록 — 일간 판정이 DUE 쪽으로 기운다."""
    return _calendar(market, ref)[0]


class GitLookupError(RuntimeError):
    """git 조회 자체가 실패했다 — 「수집분 없음」과 다르다. 판정 불가는 DUE 쪽으로 보낸다."""


def brief_publish_commit(post_path, ref='origin/main', git=None):
    """그 글을 처음 넣은 커밋(발행 커밋)의 해시, 없으면 None. git 이 실패하면 GitLookupError.
    KR 뉴스 입력(아래)과 뉴스 글의 텔레그램 입력(scripts/tg_news.py)이 같이 쓴다 — `git` 은 다른
    작업 폴더에서 부를 때 넘기는 실행기다."""
    out = (git or _git)('log', ref, '--diff-filter=A', '--format=%H', '-1', '--', post_path)
    if out.returncode:
        raise GitLookupError(out.stderr.strip()[:200])
    return out.stdout.strip() or None


def brief_news_input(day, ref='origin/main'):
    """그날 KR 마감브리프 **발행 커밋**의 뉴스 수집분 — 뉴스 글의 근거이자 「뉴스 글이 나와야 하나」의 판정 근거.
    발행 뒤 재수집이 파일을 바꿔도 이 판이 정본이다(codex 구현 검토 2026-11-06 #2·#3). 브리프가 없으면 None,
    그 커밋에 수집분이 없으면 {}. git 이 실패하면 GitLookupError(codex 재확인 #2 — 실패를 「뉴스 없음」으로
    읽으면 뉴스 글을 건너뛰고 재시도도 DONE 이 된다)."""
    commit = brief_publish_commit(f'kr/posts/{day}.html', ref)
    if not commit:
        return None
    path = f'kr/data/news/{day}.json'
    if _git('cat-file', '-e', f'{commit}:{path}').returncode:
        return {}                                 # 그 커밋에 파일이 없다 — 수집이 그날 실패한 것
    shown = _git('show', f'{commit}:{path}')
    if shown.returncode:
        raise GitLookupError(shown.stderr.strip()[:200])
    try:
        return json.loads(shown.stdout)
    except ValueError:
        return {}


def _kr_news_expected_at(day):
    try:
        return kr_news_expected(brief_news_input(day))
    except GitLookupError:
        return True                               # 판정 불가 → 기다린다(DUE) — 틀려도 오케스트레이터 가드가 막는다


def _files(*dirs, ref='origin/main'):
    out = _git('ls-tree', '-r', '--name-only', ref, '--', *dirs)
    return set(out.stdout.split())


def _lock_state(name, now):
    """(마지막 갱신 이후 분 | None, 표시 | None). 표시: `held`(세움) · `judging`·`fixing`(판정·수정 중 — 2026-11-22).

    잠금이 없거나 `released` 표시면 (None, None) — run_lock.sh 와 같은 규칙. 클라우드에서 ref 삭제가 거부돼
    release 는 ref 를 지우지 않고 표시 커밋으로 바꾼다(2026-10-20). 표시를 살아 있는 잠금으로 읽으면 쓰지 않고
    끝난 런이 120분 동안 BUSY 를 만든다. `held` 의 나이는 의미가 없지만 None 으로 두면 옛 호출자가 「잠금 없음」
    으로 읽는다 — 그래서 나이를 그대로 준다.
    """
    ref = f'refs/heads/locks/{name}'
    seen = f'refs/run_lock/{name}'
    if not _git('ls-remote', 'origin', ref).stdout.strip():
        return None, None
    if _git('fetch', '-q', 'origin', f'+{ref}:{seen}').returncode:
        return None, None
    out = _git('log', '-1', '--format=%ct%n%s', seen).stdout.split('\n')
    if len(out) < 2 or not out[0].strip().isdigit():
        return None, None
    subject = out[1]
    if subject.startswith('released '):
        return None, None
    age = max(0, int((now.timestamp() - int(out[0])) // 60))
    if subject.startswith('held '):
        return age, 'held'
    for mark in ('judging', 'fixing'):
        if subject.endswith(f' state={mark}'):
            return age, mark
    return age, None


def _us_collected(day):
    """그 세션의 수집 커밋이 origin/main 에 있는가 — 늦은 글의 작업 공간을 꺼낼 수 있는가(late_workspace.py).
    git 조회 실패는 예외로 올린다 — 판정이 빨갛게 끝나고(retry_gate 의 「판정 실패」) 쏘지 않는다."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import late_workspace
    return late_workspace.find_commit(day, 'origin/main') is not None


def _lock_age(name, now):
    """잠금의 마지막 갱신 이후 분. 잠금이 없거나 `released` 표시면 None."""
    return _lock_state(name, now)[0]


def main(argv=None):
    args = argv or sys.argv[1:] or ['']
    if args[0] == 'lock-name':
        if len(args) < 2 or args[1] not in ('us', 'kr', 'jp_daily'):
            print('usage: routine_due.py lock-name us|kr|jp_daily', file=sys.stderr)
            return 2
        if len(args) > 2:
            # 늦은 글 — 세션을 이미 정한 런(`LATE <D>`). 잠금은 그 세션 이름으로 잡는다.
            if args[1] != 'us' or len(args) != 4 or args[2] != '--session' or not _day(args[3]) \
                    or _day(args[3]).isoformat() != args[3]:
                print('usage: routine_due.py lock-name us --session YYYY-MM-DD', file=sys.stderr)
                return 2
            print(lock_name('us', None, session=args[3]))
            return 0
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
    if args[0] == 'kr-news-input':
        # KR STEP 0·3.5 — 브리프 발행 커밋의 뉴스 수집분을 <outdir>/news/<day>.json 으로 꺼내고 한 단어로 답한다:
        # expected(실을 기사 있음) · none(파일 없음·실을 기사 없음 — 뉴스 글을 내지 않는다) · no-brief.
        # 잠금을 쥔 런도 쓸 수 있게 잠금을 보지 않는다(codex #1 — `kr` 판정은 자기 잠금에 BUSY 를 낸다).
        if len(args) != 3:
            print('usage: routine_due.py kr-news-input DAY OUTDIR', file=sys.stderr)
            return 2
        day, outdir = args[1], args[2]
        # 조회 실패는 `error` — 오케스트레이터는 그 런에서 뉴스 글을 건너뛰고 보고한다. 재시도 판정은
        # 같은 실패를 DUE 로 읽어 다음 회차가 다시 본다(codex 재확인 #2).
        if _git('fetch', '-q', 'origin', 'main').returncode:
            print('error fetch 실패')
            return 0
        try:
            data = brief_news_input(day)
        except GitLookupError as e:
            print(f'error {e}')
            return 0
        if data is None:
            print('no-brief')
            return 0
        if data is not None:
            os.makedirs(os.path.join(outdir, 'news'), exist_ok=True)
            with open(os.path.join(outdir, 'news', f'{day}.json'), 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        print('expected' if kr_news_expected(data) else 'none')
        return 0
    if args[0] == 'week-key':
        # 주간 오케스트레이터가 데이터로 정한 키와 맞대 본다 — 다르면 데이터가 밀린 것이다.
        print(week_of(datetime.now(timezone.utc), _holidays('us')))
        return 0
    if args[0] == 'weekly-ready':
        # 주간 STEP 1 — 잠금을 쥔 런이 부른다(`weekly` 는 자기 잠금에 BUSY 를 낸다). 키는 받은 그대로 쓴다:
        # 루틴은 STEP 0 에서 정한 키를, 주 키가 넘어간 뒤의 수동 복구는 손으로 고른 키를 준다.
        # 집계는 작성자가 읽는 작업 트리에서, 발행 여부는 방금 fetch 한 원격에서 본다. READY 만 진행이다.
        if len(args) != 2 or not valid_key(args[1]):
            print('usage: routine_due.py weekly-ready YYYY-Www', file=sys.stderr)
            return 2
        key = args[1]
        if _git('fetch', '-q', 'origin', 'main').returncode:
            print('ERROR fetch 실패 — 발행 여부를 확인할 수 없다')
            return 1
        listed = _git('ls-tree', '-r', '--name-only', 'origin/main', '--', 'weekly', 'kr/weekly')
        if listed.returncode:
            print('ERROR origin/main 목록을 읽지 못했다')
            return 1
        missing = weekly_missing(key, set(listed.stdout.split()))
        if not missing:
            print(f'DONE {key}')
            return 0
        why = weekly_holds(key, missing, datetime.now(timezone.utc),
                           {m: _calendar(m) for m in missing},
                           {m: _tree_json(WEEKLY[m][1].format(key)) for m in missing})
        if why:
            print(f'WAIT {key} {"; ".join(why)}')
            return 1
        print(f'READY {key} {",".join(missing)}')
        return 0
    kind = args[0]
    if kind not in ('us', 'kr', 'weekly', 'japan', 'jp_daily'):
        print('usage: routine_due.py us|kr|weekly|japan|jp_daily', file=sys.stderr)
        return 2
    stale = ''
    if _git('fetch', '-q', 'origin', 'main').returncode:
        # 판정 불가는 DUE 로 보낸다 — 틀려도 오케스트레이터의 가드가 막는다. 반대로
        # DONE 으로 보내면 글이 조용히 빠진다.
        if kind != 'weekly':
            print('DUE fetch 실패 — 오케스트레이터가 판정한다')
            return 0
        # 주간만 예외: 무조건 DUE 면 주 중간에도 세션이 뜬다. 가진 origin/main 으로 같은 규칙을 그대로 적용한다.
        # 옛 판은 발행·집계를 적게 볼 뿐이라 틀려도 WAIT·DUE 쪽이고(발행된 글은 지워지지 않는다), DUE 가 나가도
        # STEP 1 의 weekly-ready 가 fetch 를 다시 해 닫는다.
        stale = ' (fetch 실패 — 가진 origin/main 기준)'
    now = datetime.now(timezone.utc)
    if kind == 'us':
        hol = _holidays('us')
        age, flag = _lock_state(lock_name('us', now, holidays=hol), now)
        files = _files('posts', 'news')
        verdict = decide_us(now, files, age, hol, flag)
        if verdict[0] in ('DONE', 'HOLD'):
            locks = {s: _lock_state(lock_name('us', now, session=s), now)
                     for s in us_late_sessions(now, hol) if any(p not in files for p in us_want(s))}
            verdict = decide_us_late(now, files, verdict, locks, hol, _us_collected)
    elif kind == 'kr':
        hol = _holidays('kr')
        verdict = decide_kr(now, _files('kr/posts', 'kr/news'),
                            _lock_age(lock_name('kr', now, holidays=hol), now), hol,
                            _kr_news_expected_at)
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
                                _lock_age(lock_name('weekly', now, key), now), now,
                                {m: _calendar(m) for m in WEEKLY})
    print(' '.join(verdict) + stale)
    return 0


if __name__ == '__main__':
    sys.exit(main())
