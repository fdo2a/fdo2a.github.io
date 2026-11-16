"""일본어판 러너 한 tick — 무엇을 다시 만들지 고르고, 브레이크를 지키며 모델을 부르고, `ja/**` 만 발행한다.

    tick(root, clone, *, now, cfg, translate, review, cache_dir) -> Report

- `root`  — 사람 폴더(`site/`). **읽기만** 한다: 한글 쪽 러너의 로컬 기록 `reviews/runner.json`(추적 안 함).
- `clone` — 이 tick 만 쓰는 origin/main 사본(git 작업 트리). 여기서 글을 읽고, `ja/**` 를 쓰고, 커밋·푸시한다.
- `cache_dir` — 레포 밖 로컬 상태(잃어도 다시 번역하는 비용뿐): 잠금, 주간 토큰 누적(`budget.json`), 일본어판 한도
  (`limit.json`), 한글 쪽 한도 걸쇠(`ko_limit.json`), 로그인 만료(`auth.json`), 하루 검토 호출 수(`review_calls.json`),
  한글 발행 누락 걸쇠(`ko_missing.json`), 시도 기록(`attempts.json`), 번역 기억(`tm/<path>.json`),
  보류 상세(`logs/<path>.json`), 마지막 보고(`last.json`).
  기록 파일이 **없으면** 처음 상태, **깨졌으면**(못 읽음·JSON 아님·꼴이 다름) 브레이크 `cache_corrupt` — 0 으로 읽지
  않고, 깨진 파일을 덮어 쓰지도 않는다(덮으면 다음 tick 에 브레이크가 저절로 풀린다).

브레이크(하나라도 걸리면 모델을 부르지 않는다 — 모델 호출 0 인 재조립·알림 문구·삭제는 계속한다):
시각대 밖 · 이번 주 토큰 예산 소진 · 일본어판 자신의 한도(재개 시각까지) · 한글 쪽 한도(다음 초기화까지) ·
기록 파일 깨짐 · 로그인 만료(6시간, 그 뒤 한 편만 시험) · 하루 검토 상한 · 한글 발행 누락(기한 + 24시간까지).

글마다(`_Tick.page`):
1. 발행된 일본어판이 있고 입력(원본 blob·의존 파일·단위 해시·렌더러 판·링크 대상의 발행 여부)이 그대로면 건너뛴다.
2. 같은 입력으로 이미 실패했으면(`attempts.json`) 다시 하지 않는다 — 예외: 검토 실패·모델 오류·처리 오류·그림은
   하루 3번, 한도·예산·로그인·대기는 브레이크가 풀리면. 사람은 `ja_local.py retry <path>` 로 기록을 지운다.
3. 그림이 필요하면(`assets/yield_curve_<d>.png` 를 쓰는 글) 먼저 만든다 — 얕은 사본이라 못 찾으면 한 번 더
   가져와 다시, 그래도 못 만들면 보류(모델을 부르기 전에).
4. 모델 없이 한 번 조립해 본다(가짜 번역기가 불리면 `NeedModel`). 되면 끝(재조립), 모델이 필요하면 줄을 선다.
5. 줄은 새 글 먼저·최근 글 먼저·같은 날이면 링크 대상(posts) 먼저, tick 당 `max_pages_per_tick` 편. 브레이크면 미룬다.
6. 실패(보류·대기·미룸·처리 오류)인데 발행된 일본어판이 있고 입력이 바뀌었으면 그 글에 「한국어판이 갱신됐다」
   문구를 입혀 다시 낸다(`notice`).

원장(`ja/state.json`, 공개된다)의 `reason` 은 짧은 고정 꼴뿐이다(글 경로·단위 번호·사유). 검토 지적 전문은 `logs/`.
"""
from __future__ import annotations

import copy
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import assemble, chart, lists, news, pipeline, publish, state
from . import translate as T

KST = timezone(timedelta(hours=9))
SCOPE = re.compile(r"(?:posts|news|weekly|japan/daily|japan/posts)/(?:\d{4}-\d{2}-\d{2}|\d{4}-W\d{2})\.html")
SCOPE_DIRS = ("posts", "news", "weekly", "japan/daily", "japan/posts")
# 같은 날이면 링크 대상이 먼저 — news 는 그날 posts 를, weekly 는 일간을 가리킨다
RANK = {"posts": 0, "japan/daily": 1, "japan/posts": 2, "weekly": 3, "news": 4}
CHART_SRC = re.compile(r"assets/yield_curve_(\d{4}-\d{2}-\d{2})\.png")
MAIN = ("source_blob", "text_hash", "deps", "renderer")
LIVE = ("published", "notice")
LINK = "link:"
RETRY_PER_DAY = 3
OWN_LIMIT_FALLBACK = timedelta(hours=5)
AUTH_HOLD = timedelta(hours=6)
# 사용량을 돌려주지 못한 claude 호출 하나에 잡는 토큰 — 실측한 가장 큰 호출(입력 약 2만·출력 약 1만)보다 크게.
UNKNOWN_CALL = {"in": 30_000, "out": 15_000}
STALE_LAST = timedelta(hours=26)
CHART_BACK_DAYS = 3          # 얕은 사본을 그날 - 3일까지 더 가져온다
GLOSSARY_FILE = Path(__file__).with_name("glossary.py")
DEFAULT_CACHE = os.path.expanduser("~/Library/Caches/fdo2a-ja")
CACHE_ENV = "JA_CACHE_DIR"
ALERTS_BRANCH = "alerts-state"
KO_RUNNER = "reviews/runner.json"

# 같은 입력이면 다시 안 하는 보류 가운데 사람이 손대야 풀리는 것(알림에 「사람이 풀어야 함」)
HUMAN = ("blocking", "gate", "doc", "names", "fixed", "news_lang", "news_malformed", "missing_units")
ALWAYS_RETRY = ("limit", "deferred", "budget", "review_cap", "auth")          # 브레이크가 풀리면 다시
DAILY_RETRY = ("review_failed", "model", "chart", "error")      # 하루 3번
PENDING = ("limit", "model", "deferred", "budget", "review_cap", "auth", "error")
# 미룰 때 사유를 이어받는 코드 — settle() 이 이미 원장에 적은 것만. 처리 오류(error)는 원장에 없으니 이어받으면
# 브레이크로 미뤄진 새 글이 원장에 처음 적힌다(상태만 바뀐 커밋).
CARRY = ("limit", "model", "auth", "budget", "review_cap")


def cache_dir_default() -> str:
    return os.environ.get(CACHE_ENV) or DEFAULT_CACHE


RUN_CFG = pipeline.Config(review_on_names_hold=False)   # 확인 안 된 인명이면 검토 전에 보류 — 한도를 아낀다


# ── 설정 ──────────────────────────────────────────────────────────────────

@dataclass
class Cfg:
    enabled: bool = False
    start: date | None = None
    max_pages_per_tick: int = 2
    weekly_token_budget: int = 2_500_000
    max_review_calls_per_day: int = 16    # codex 검토+판정, KST 날짜 — 한글 검토 러너와 한도를 나눈다
    windows_kst: tuple = ((10, 15), (23, 29))
    week_reset: tuple = (5, 9)       # (요일 월=0, 시) KST
    why: str = ""                    # 꺼진 까닭(깨진 설정 등)


def _int(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def parse_config(obj) -> Cfg:
    """깨졌으면 `enabled=False` 와 까닭. 모르는 열쇠는 무시한다."""
    if not isinstance(obj, dict):
        return Cfg(why="설정이 객체가 아니다")
    c = Cfg()
    try:
        if not isinstance(obj.get("enabled", False), bool):
            raise ValueError("enabled")
        st = obj.get("start")
        if st is not None:
            if not isinstance(st, str):
                raise ValueError("start")
            c.start = date.fromisoformat(st)
        for k, lo, hi in (("max_pages_per_tick", 0, 50), ("weekly_token_budget", 0, 10**9),
                          ("max_review_calls_per_day", 0, 10_000)):
            if k in obj:
                if not _int(obj[k], lo, hi):
                    raise ValueError(k)
                setattr(c, k, obj[k])
        if "windows_kst" in obj:
            w = obj["windows_kst"]
            if not isinstance(w, list) or not all(isinstance(x, list) and len(x) == 2 and _int(x[0], 0, 47)
                                                  and _int(x[1], 1, 48) and x[0] < x[1] for x in w):
                raise ValueError("windows_kst")
            c.windows_kst = tuple((a, b) for a, b in w)
        if "week_reset" in obj:
            r = obj["week_reset"]
            if not isinstance(r, dict) or not _int(r.get("weekday"), 0, 6) or not _int(r.get("hour"), 0, 23):
                raise ValueError("week_reset")
            c.week_reset = (r["weekday"], r["hour"])
    except ValueError as e:
        return Cfg(why=f"설정 값이 잘못됐다({e})")
    c.enabled = obj.get("enabled") is True
    if not c.enabled:
        c.why = "enabled 가 false"
    return c


def load_config(root) -> Cfg:
    obj, why = state.read_json(Path(root) / "ja" / "config.json")
    return Cfg(why=why) if obj is None else parse_config(obj)


# ── 시각 ──────────────────────────────────────────────────────────────────

def kst(now: datetime) -> datetime:
    return now.astimezone(KST)


def in_window(now, windows) -> bool:
    n = kst(now)
    x = n.hour + n.minute / 60
    return any(a <= x < b or a <= x + 24 < b for a, b in windows)


def week_start(now, reset) -> datetime:
    """가장 최근의 초기화 시각(≤ now)."""
    wd, hr = reset
    n = kst(now)
    c = n.replace(hour=hr, minute=0, second=0, microsecond=0) - timedelta(days=(n.weekday() - wd) % 7)
    return c - timedelta(days=7) if c > n else c


def next_reset(now, reset) -> datetime:
    return week_start(now, reset) + timedelta(days=7)


def _parse_ts(s):
    try:
        t = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else None


def _hm(t):
    return kst(t).strftime("%m/%d %H:%M")


# ── 로컬 상태(cache_dir) ──────────────────────────────────────────────────

class CacheCorrupt(Exception):
    """기록 파일이 깨졌다 — 처음 상태(없음)로 보지 않는다."""

    def __init__(self, name):
        super().__init__(name)
        self.name = name


def _ts_field(*keys):
    return lambda o: all(_parse_ts(o.get(k)) for k in keys)


# 파일 → 맞는 꼴. 꼴이 다르면 깨진 것이다(문자열 토큰을 0 으로 읽으면 예산이 풀린다).
CHECKS = {
    "budget.json": lambda o: isinstance(o.get("week"), str) and _int(o.get("tokens"), 0, 10**12),
    "limit.json": _ts_field("until"),
    "ko_limit.json": _ts_field("until"),
    "ko_missing.json": _ts_field("until"),
    "auth.json": _ts_field("since", "until"),
    "attempts.json": lambda o: all(isinstance(v, dict) and isinstance(v.get("fp"), str) and isinstance(v.get("code"), str)
                                   for v in o.values()),
    "review_calls.json": lambda o: all(isinstance(k, str) and _int(v, 0, 10**6) for k, v in o.items()),
    # reviews/runner.json 은 남의 파일이고 그쪽 읽는 코드도 칸의 꼴을 너그럽게 본다 — 못 읽음·JSON 아님·객체 아님만 깨짐
}


def load_file(path, check=None):
    """(객체, 깨짐?) — 없으면 (None, False). 읽기 실패·JSON 아님·객체 아님·꼴이 다름은 (None, True)."""
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    except (OSError, UnicodeDecodeError):
        return None, True
    try:
        obj = json.loads(raw)
    except ValueError:
        return None, True
    if not isinstance(obj, dict) or (check and not check(obj)):
        return None, True
    return obj, False


class Local:
    """cache_dir 의 기록 파일. 깨진 파일은 `bad` 에 이름을 남기고 다시 쓰지 않는다."""

    def __init__(self, cache_dir):
        self.dir = Path(cache_dir)
        self.bad = []

    def _mark(self, name):
        if name not in self.bad:
            self.bad.append(name)

    def get(self, name) -> dict:
        obj, bad = load_file(self.dir / name, CHECKS.get(name))
        if bad:
            self._mark(name)
        return obj or {}

    def get_root(self, root, rel=KO_RUNNER) -> dict:
        """사람 폴더의 파일(읽기만)."""
        obj, bad = load_file(Path(root) / rel, CHECKS.get(rel))
        if bad:
            self._mark(rel)
        return obj or {}

    def put(self, name, obj):
        if name in self.bad:
            return                       # 깨진 기록을 덮지 않는다 — 사람이 볼 때까지 브레이크가 남게
        state.write_json(self.dir / name, obj)

    def drop(self, name) -> bool:
        p = self.dir / name
        if name in self.bad or not p.exists():
            return False
        p.unlink()
        return True


def _loc(x) -> Local:
    return x if isinstance(x, Local) else Local(x)


def budget_used(cache, now, cfg) -> int:
    b = _loc(cache).get("budget.json")
    return b["tokens"] if b.get("week") == week_start(now, cfg.week_reset).isoformat() else 0


def add_budget(cache, now, cfg, tokens) -> int:
    loc = _loc(cache)
    n = budget_used(loc, now, cfg) + int((tokens or {}).get("in") or 0) + int((tokens or {}).get("out") or 0)
    loc.put("budget.json", {"week": week_start(now, cfg.week_reset).isoformat(), "tokens": n})
    return n


def review_calls(cache, now) -> int:
    return _loc(cache).get("review_calls.json").get(kst(now).date().isoformat(), 0)


def add_review_calls(cache, now, n) -> int:
    loc = _loc(cache)
    day = kst(now).date().isoformat()
    got = loc.get("review_calls.json")
    got = {d: v for d, v in got.items() if d >= (kst(now).date() - timedelta(days=7)).isoformat()}
    got[day] = got.get(day, 0) + int(n)
    loc.put("review_calls.json", got)
    return got[day]


def _retry_fns():
    try:
        from scripts.review.runner import claude_retry_at, retry_at
    except ImportError:          # scripts/ 를 경로에 둔 쪽(매일 요약)
        from review.runner import claude_retry_at, retry_at
    return claude_retry_at, retry_at


def _publish_watch():
    try:
        from scripts.review import publish_watch
    except ImportError:
        from review import publish_watch
    return publish_watch


def own_limit_until(text, now) -> datetime:
    """한도 오류 문구의 재개 시각(Claude 꼴 → codex 꼴), 못 읽으면 5시간 뒤."""
    claude_retry_at, retry_at = _retry_fns()
    for fn in (claude_retry_at, retry_at):
        try:
            got = fn(text or "", now)
        except Exception:  # noqa: BLE001 — 시각을 못 읽으면 기본값
            got = None
        t = _parse_ts(got) if got else None
        if t and t > now:
            return t
    return now + OWN_LIMIT_FALLBACK


def note_own_limit(cache, now, text) -> datetime:
    until = own_limit_until(text, now)
    _loc(cache).put("limit.json", {"until": until.isoformat(), "why": (text or "")[:300], "at": now.isoformat()})
    return until


def korean_limit_signals(root, now, cfg, loc=None) -> list:
    """한글 쪽 러너(`review_gate.py run`)가 `reviews/runner.json`(로컬, 추적 안 함)에 남긴 한도 흔적.

    - `limit_hits: {KST 날짜: 횟수}` — codex 한도. 이번 주(초기화가 든 날 포함) 날짜가 있으면.
    - `correction_blocked_until` — 정정(Claude) 한도의 재개 시각. 지나면 러너가 지우므로 보이는 동안 걸쇠를 건다.
    - `errors[*].kind == '한도'` — 아직 풀리지 않은 한도 오류(날짜 없음).
    파일이 없으면 흔적 없음, 깨졌으면 `CacheCorrupt`(loc 를 주면 거기 남기고 빈 목록).
    클라우드 루틴·쟁점 러너의 한도는 로컬에 남지 않는다 — 여기서 못 본다."""
    own = loc or Local(os.devnull)
    obj = own.get_root(root)
    if KO_RUNNER in own.bad and loc is None:
        raise CacheCorrupt(KO_RUNNER)
    out = []
    ws = week_start(now, cfg.week_reset).date().isoformat()
    hits = obj.get("limit_hits")
    if isinstance(hits, dict):
        days = sorted(d for d, n in hits.items() if isinstance(d, str) and d >= ws and _int(n, 1, 10**6))
        if days:
            out.append(f"codex 한도 {days[-1]}")
    t = _parse_ts(obj.get("correction_blocked_until"))
    if t and t > now:
        out.append("Claude 한도(정정)")
    errs = obj.get("errors")
    if isinstance(errs, dict):
        for k, v in sorted(errs.items()):
            if isinstance(v, dict) and v.get("kind") == "한도":
                out.append(f"한도 오류({str(k)[:20]})")
    return out


def _latch(loc, name, now, sig, until_if_seen):
    """흔적을 보면 그 시각까지 걸쇠. 걸려 있으면 (그 시각, 본 흔적), 아니면 (None, [])."""
    latch = loc.get(name)
    until = _parse_ts(latch.get("until"))
    if sig:
        if until is None or until < until_if_seen:
            loc.put(name, {"until": until_if_seen.isoformat(), "seen": now.isoformat(), "why": sig})
        return until_if_seen, sig
    if until and until > now:
        return until, [str(x)[:40] for x in latch.get("why") or []] if isinstance(latch.get("why"), list) else []
    return None, []


def korean_limit_until(root, cache, now, cfg):
    """한글 쪽 한도 걸쇠 — 흔적을 보면 다음 초기화까지. 걸려 있으면 그 시각, 아니면 None."""
    loc = _loc(cache)
    return _latch(loc, "ko_limit.json", now, korean_limit_signals(root, now, cfg, loc), next_reset(now, cfg.week_reset))[0]


MISSING_HOLD = timedelta(hours=24)


def cloud_missing(clone, now):
    """(기한이 지난 지 하루 안인 미발행 세션들, 못 읽은 까닭, 걸쇠를 풀 시각). `alerts-state:verify_publish.json`(GitHub 계산 상태) —
    `review.digest.publish_tail` 과 같은 명시적 refspec 으로 사본에 받는다(사람 폴더는 건드리지 않는다).
    발행 누락 신호일 뿐 한도의 원인 기록이 아니고, 감시 범위도 US·KR 이다 — 못 읽으면 브레이크를 걸지 않는다."""
    ref = f"refs/remotes/origin/{ALERTS_BRANCH}"
    args = ["fetch", "--quiet"] + (["--depth=1"] if _shallow(clone) else []) + \
        ["origin", f"+refs/heads/{ALERTS_BRANCH}:{ref}"]
    try:
        got = subprocess.run(["git", *args], cwd=clone, capture_output=True, text=True, timeout=120)
        if got.returncode:
            return [], "가져오지 못함", None
        show = subprocess.run(["git", "show", f"{ref}:verify_publish.json"], cwd=clone, capture_output=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return [], "가져오지 못함", None
    if show.returncode:
        return [], "파일 없음", None
    W = _publish_watch()
    try:
        st = W.loads_state(show.stdout)
    except W.StateError:
        return [], "내용 검증 실패", None
    ok = _parse_ts(st.get("last_ok"))
    if ok is None or now - ok > W.GITHUB_STALE:
        return [], "낡음", None
    today = kst(now).date()
    out, until = [], None
    for key, s in st["sessions"].items():
        if s in ("missing", "missing_quiet"):
            market, day = key.split(":", 1)
            # 영영 안 올라온 세션은 상태에 계속 missing 으로 남는다 — 기한이 지난 지 하루 안인 것만(아니면
            # 매일 멈춘다). 기한이 밤 23시인 KR 도 하루는 쉬게 「그날 자정」이 아니라 기한 + 24시간까지 건다.
            due = W.deadline(market, day)
            if kst(due).date() <= today and now - due < MISSING_HOLD:
                out.append(key)
                until = max(until or due, due)
    return sorted(out), "", (until + MISSING_HOLD if until else None)


@contextmanager
def tick_lock(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    fh = open(Path(cache_dir) / ".lock", "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        fh.close()


def _shallow(clone) -> bool:
    p = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=clone, capture_output=True, text=True)
    return p.stdout.strip() == "true"


# ── 시도 기록 ─────────────────────────────────────────────────────────────

def may_retry(att, today: str) -> bool:
    code = (att or {}).get("code")
    if code in ALWAYS_RETRY:
        return True
    if code in DAILY_RETRY:      # 그림은 모델을 안 쓴다 — 일시 실패(fetch·글꼴)도 다시
        return not (att.get("day") == today and int(att.get("n") or 0) >= RETRY_PER_DAY)
    return False


def forget_attempt(cache_dir, path) -> bool:
    """깨진 시도 기록은 고치지 않는다 — `CacheCorrupt`."""
    loc = Local(cache_dir)
    att = loc.get("attempts.json")
    if loc.bad:
        raise CacheCorrupt(loc.bad[0])
    if path not in att:
        return False
    att.pop(path)
    loc.put("attempts.json", att)
    return True


def clear_auth(cache_dir) -> bool:
    """`ja_local.py retry --auth` — 터미널에서 다시 로그인한 뒤. 다음 tick 이 바로 부른다."""
    p = Path(cache_dir) / "auth.json"
    if not p.exists():
        return False
    p.unlink()
    return True


# ── 입력 ──────────────────────────────────────────────────────────────────

def glossary_version() -> str:
    return hashlib.sha1(GLOSSARY_FILE.read_bytes()).hexdigest()[:12]


def page_date(path: str) -> date:
    """일간은 그날, 주간은 그 주의 끝(일요일)."""
    return news._span(path)[1]


def rank(path: str) -> int:
    return RANK.get(path.rsplit("/", 1)[0], 9)


def news_candidates(path) -> list:
    """`news.data_files` 가 볼 수 있는 후보 전부(없는 것까지) — 푸시 재확인에서 「그때 없던 파일이 생겼다」를 잡는다.
    `news.data_files` 는 있는 것만 돌려주므로 같은 창(`BEFORE_DAYS`·`AFTER_DAYS`·주차 0/7/14일 전)을 여기서 편다.
    `test_news_candidates_cover_existing_data_files` 가 넓은 범위의 파일을 깔아 놓고 부분집합인지 본다."""
    first, last, weeks = news._span(path)
    out = []
    d = first - timedelta(days=news.BEFORE_DAYS)
    while d <= last + timedelta(days=news.AFTER_DAYS):
        s = d.isoformat()
        out += [f"data/news/{s}.json", f"japan/data/news/{s}.json", f"japan/data/news/daily/{s}.json"]
        d += timedelta(days=1)
    for y, w in weeks:
        mon = date.fromisocalendar(y, w, 1)
        for back in (0, 7, 14):
            yy, ww, _ = (mon - timedelta(days=back)).isocalendar()
            out.append(f"japan/data/{yy}-W{ww:02d}.news.json")
    return out


@dataclass
class Inputs:
    path: str
    source_blob: str
    deps: dict
    text_hash: str | None
    renderer: str
    glossary: str
    charts: list = field(default_factory=list)      # 그림 날짜
    absent: list = field(default_factory=list)      # 지금은 없는 뉴스 데이터 후보
    links: list = field(default_factory=list)       # 이 글이 가리키는 일본어판 범위의 글

    @property
    def main(self) -> dict:
        return {"source_blob": self.source_blob, "text_hash": self.text_hash, "deps": dict(self.deps),
                "renderer": self.renderer}

    @property
    def fp(self) -> str:
        # 링크 대상의 발행 여부는 재조립만 부른다 — 시도 열쇠에 넣으면 보류 글이 대상 발행 때마다 모델로 간다
        deps = _plain(self.deps)
        raw = json.dumps([self.source_blob, deps, self.text_hash, self.renderer, self.glossary],
                         sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def expect(self) -> dict:
        """푸시 재확인용 — 없던 후보는 「없음」(빈 값)으로, 링크 열쇠는 경로가 아니라서 뺀다."""
        deps = _plain(self.deps)
        return {self.path: self.source_blob, **{a: "" for a in self.absent}, **deps}

    def relink(self, live) -> "Inputs":
        deps = _plain(self.deps)
        deps.update({LINK + t: "1" if t in live else "0" for t in self.links})
        return dataclasses.replace(self, deps=deps)


def _plain(deps) -> dict:
    return {k: v for k, v in (deps or {}).items() if not k.startswith(LINK)}


def inputs(clone, path, gloss=None, live=frozenset()) -> Inputs:
    clone = Path(clone)
    raw = (clone / path).read_bytes()
    deps = {}
    for f in news.data_files(clone, path):
        deps[f.relative_to(clone).as_posix()] = pipeline.blob_sha(f.read_bytes())
    absent = [c for c in news_candidates(path) if c not in deps]
    rel, _entry = pipeline.list_entry(clone, path)
    if rel:
        rows, _ = state.read_json(clone / rel)
        deps[publish.LIST_PREFIX + rel] = publish.item_hash(rows, Path(path).stem)
    text = raw.decode("utf-8", "replace")
    charts = sorted(set(CHART_SRC.findall(text)))
    for d in charts:
        a = clone / chart.asset_rel(d)
        deps[chart.asset_rel(d)] = pipeline.blob_sha(a.read_bytes()) if a.is_file() else ""
    th, _why = pipeline.text_hash_of(clone, path)
    inp = Inputs(path, pipeline.blob_sha(raw), deps, th, assemble.RENDERER, gloss or glossary_version(), charts,
                 absent, assemble.link_targets(text, path))
    return inp.relink(live)


# ── 짧은 사유(공개 원장용) ─────────────────────────────────────────────────

def _ids(xs, n=5):
    xs = [str(x) for x in xs]
    return "·".join(f"#{x}" for x in xs[:n]) + (f" 외 {len(xs) - n}" if len(xs) > n else "")


FIXED_REASON = {"review_failed": "검토 실패(codex 응답)", "missing_units": "번역이 빠진 단위", "limit": "한도",
                "model": "모델 오류", "auth": "로그인 만료", "budget": "주간 예산", "review_cap": "하루 검토 상한", "fixed": "고정 번역 지적",
                "news_lang": "원문 언어 불확실", "news_malformed": "뉴스 항목 꼴", "error": "처리 오류"}


def short_reason(res) -> tuple:
    """(code, 사유). 사유는 원장·알림에 나간다 — 고정 꼴 + 단위 번호·인명까지만."""
    d = res.detail or {}
    code = d.get("stop") or res.status
    if code == "news_missing":
        return code, f"뉴스 기록 없음 {len((d.get('news') or {}).get('missing') or [])}건"
    if code == "gate":
        ids = sorted(int(k) for k in (d.get("gate_failed") or {}))
        return code, f"기계 검사 {len(ids)}단위({_ids(ids)})"
    if code == "names":
        nm = [str(x)[:20] for x in d.get("unverified_names") or []]
        return code, "확인 안 된 인명: " + ", ".join(nm[:3]) + (f" 외 {len(nm) - 3}" if len(nm) > 3 else "")
    if code == "blocking":
        ids = sorted({f.get("id") for f in d.get("blocking") or [] if isinstance(f, dict)}, key=str)
        return code, f"검토 지적 {len(d.get('blocking') or [])}건({_ids(ids)})"
    if code == "fixed":
        ids = sorted({f.get("id") for f in d.get("fixed_findings") or [] if isinstance(f, dict)}, key=str)
        return code, f"고정 번역 지적 {len(ids)}단위({_ids(ids)})" if ids else FIXED_REASON[code]
    if code == "doc":
        codes = sorted({str(p).split(":")[0][:20] for p in d.get("doc_problems") or []})
        return code, "문서 검사: " + ",".join(codes)
    if code in FIXED_REASON:
        return code, FIXED_REASON[code]
    return str(code)[:20], (res.reason or "")[:60]


# ── 보고 ──────────────────────────────────────────────────────────────────

@dataclass
class Report:
    enabled: bool = True
    skipped: str = ""                                      # 잠금·꺼짐
    brakes: list = field(default_factory=list)
    pages: dict = field(default_factory=dict)              # path → 결과
    reasons: dict = field(default_factory=dict)            # path → 짧은 사유
    tokens: dict = field(default_factory=lambda: {"in": 0, "out": 0})
    model_pages: int = 0
    publish: str = ""
    errors: list = field(default_factory=list)
    corrupt: list = field(default_factory=list)            # 깨진 기록 파일
    auth: str = ""                                         # 로그인 만료 걸쇠의 끝(있을 때)
    signals: list = field(default_factory=list)            # 못 읽은 보조 신호

    def line(self) -> str:
        if self.skipped:
            return f"건너뜀 — {self.skipped}"
        cnt = {}
        for v in self.pages.values():
            cnt[v] = cnt.get(v, 0) + 1
        body = ", ".join(f"{k} {n}" for k, n in sorted(cnt.items())) or "할 일 없음"
        tail = f" · 브레이크: {', '.join(self.brakes)}" if self.brakes else ""
        tail += f" · 토큰 {self.tokens['in']}/{self.tokens['out']}" if self.model_pages else ""
        tail += f" · 발행 {self.publish}" if self.publish else ""
        tail += f" · 오류 {'; '.join(self.errors)}" if self.errors else ""
        tail += f" · 신호 {'; '.join(self.signals)}" if self.signals else ""
        return body + tail

    def to_json(self, now) -> dict:
        return {"at": now.isoformat(timespec="seconds"), "skipped": self.skipped, "brakes": list(self.brakes),
                "pages": dict(self.pages), "reasons": dict(self.reasons), "tokens": dict(self.tokens),
                "model_pages": self.model_pages, "publish": self.publish, "errors": list(self.errors),
                "corrupt": list(self.corrupt), "auth": self.auth, "signals": list(self.signals)}


class NeedModel(Exception):
    """모델 없이 조립해 보다가 번역·검토가 필요해졌다 — pipeline 이 삼키는 예외(LimitReached 등)가 아니다."""


def _no_model(*_a, **_k):
    raise NeedModel()


# ── tick ──────────────────────────────────────────────────────────────────

def _git(cwd, *args, check=True, timeout=120):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}")
    return p.stdout


def scope_tree(clone) -> dict:
    out = {}
    for line in _git(clone, "ls-tree", "-r", "HEAD", "--", *SCOPE_DIRS).splitlines():
        meta, _, path = line.partition("\t")
        if SCOPE.fullmatch(path):
            out[path] = meta.split()[2]
    return out


def eligible(path, start) -> bool:
    if start is None:
        return False
    try:
        return page_date(path) >= start
    except ValueError:
        return False


class _Meter:
    """모델 호출마다 바로 기록한다 — 글이 끝나기 전에 죽어도(예외·프로세스 종료) 쓴 토큰·검토 호출이 남게."""

    def __init__(self, t):
        self.t = t
        self.translated = False          # claude 가 한 번이라도 답했다 — 로그인은 살아 있다
        self.tok = {"in": 0, "out": 0}   # 갈고리가 이미 적은 토큰 — 함수가 돌려준 합계에서 뺀다(두 번 세지 않게)
        self.rev = 0                     # 갈고리가 이미 센 검토 호출

    def _tokens(self, tok):
        tok = tok or {}
        for k in ("in", "out"):
            self.t.rep.tokens[k] += int(tok.get(k) or 0)
        add_budget(self.t.loc, self.t.now, self.t.cfg, tok)

    def on_call(self, phase, kind, usage=None):
        """자식 프로세스 하나마다(`translate.ON_CALL`). 띄우기 전에 상한을 보고, 끝나면 바로 적는다."""
        t = self.t
        if phase == "before":
            if kind == "translate" and budget_used(t.loc, t.now, t.cfg) >= t.cfg.weekly_token_budget:
                raise T.CapReached("budget", "주간 토큰 예산")
            n = review_calls(t.loc, t.now)
            if kind == "review" and n >= t.cfg.max_review_calls_per_day:
                raise T.CapReached("review_cap", f"하루 검토 상한({n}/{t.cfg.max_review_calls_per_day})")
        elif kind == "translate":
            if usage is None:
                tok = dict(UNKNOWN_CALL)     # 시간 초과·깨진 응답 — 쓴 양을 모른다. 0 으로 두면 예산이 샌다
            else:
                tok = {"in": 0, "out": 0}
                T._add_usage(tok, usage)
                self.translated = True
            self._tokens(tok)
            for k in tok:
                self.tok[k] += tok[k]
        else:
            add_review_calls(t.loc, t.now, 1)
            self.rev += 1

    @contextmanager
    def hooked(self):
        prev, T.ON_CALL = T.ON_CALL, self.on_call
        try:
            yield
        finally:
            T.ON_CALL = prev

    def _rest(self, tok, before):
        """함수가 돌려준 토큰에서 그 사이 갈고리가 적은 만큼을 뺀 나머지(가짜 함수는 갈고리를 안 부른다)."""
        tok = tok or {}
        return {k: max(0, int(tok.get(k) or 0) - (self.tok[k] - before[k])) for k in ("in", "out")}

    def translate(self, fn):
        def call(*a, **k):
            before = dict(self.tok)
            try:
                out = fn(*a, **k)
            except (T.LimitReached, T.ModelError, T.CapReached) as e:
                if e.partial is not None:
                    self._tokens(self._rest(e.partial.tokens, before))
                raise
            self._tokens(self._rest(out.tokens, before))
            self.translated = True
            return out
        return call

    def _counted(self, fn):
        def call(*a, **k):
            before = self.rev
            try:
                out = fn(*a, **k)
            except T.CapReached:
                raise                    # 부르지 않은 호출은 세지 않는다
            except Exception:
                add_review_calls(self.t.loc, self.t.now, max(0, 1 - (self.rev - before)))
                raise
            add_review_calls(self.t.loc, self.t.now, max(0, out.calls - (self.rev - before)))
            return out
        return call

    def review(self, fn):
        call = self._counted(fn)
        adj = getattr(fn, "adjudicate", None)        # 판정은 선택 속성(pipeline 과 같은 규칙)
        if adj is not None:
            call.adjudicate = self._counted(adj)
        return call


class _Tick:
    def __init__(self, root, clone, now, cfg, translate, review, cache_dir):
        self.root, self.clone, self.now, self.cfg = Path(root), Path(clone), now, cfg
        self.translate, self.review, self.cache = translate, review, Path(cache_dir)
        self.loc = Local(cache_dir)
        self.today = kst(now).date().isoformat()
        self.now_s = kst(now).isoformat(timespec="seconds")
        self.rep = Report()
        self.ledger, _ = state.load_ledger(self.clone)
        self.attempts = self.loc.get("attempts.json")
        self.touched = {}            # path → expect(원본·의존 파일) — 이번 커밋에 든 글
        self.hold_publish = False    # 목록을 못 만들었다 — 이번 tick 은 밀지 않는다
        self.ready_tm = []           # 푸시가 되면 지울 로컬 번역 기억
        self.gloss = glossary_version()
        self.trial = False           # 로그인 만료 6시간 뒤 — 이번 tick 은 한 편만
        self.made_live = set()       # 모델 단계에서 새로 나간 글 — 그 글을 가리키는 글을 다시 조립한다

    # ── 브레이크 ──
    def brakes(self):
        out, loc, now, cfg = [], self.loc, self.now, self.cfg
        if not in_window(now, cfg.windows_kst):
            out.append("시각대 밖")
        if budget_used(loc, now, cfg) >= cfg.weekly_token_budget:
            out.append("주간 토큰 예산")
        own = _parse_ts(loc.get("limit.json").get("until"))
        if own and own > now:
            out.append(f"일본어판 한도({_hm(own)}까지)")
        ko = korean_limit_until(self.root, loc, now, cfg)
        if ko:
            out.append(f"한글 쪽 한도({_hm(ko)}까지)")
        a = loc.get("auth.json")
        until = _parse_ts(a.get("until"))
        if until:
            self.rep.auth = until.isoformat()
            if until > now:
                out.append(f"로그인 만료({_hm(until)}까지)")
            else:
                self.trial = True
        n = review_calls(loc, now)
        if n >= cfg.max_review_calls_per_day:
            out.append(f"하루 검토 상한({n}/{cfg.max_review_calls_per_day})")
        keys, why, hold = cloud_missing(self.clone, now)
        if why:
            self.rep.signals.append(f"클라우드 발행 누락 신호를 못 읽음({why})")
        until, seen = _latch(loc, "ko_missing.json", now, keys, hold or now)
        if until:
            out.append(f"한글 발행 누락({', '.join(seen)})")
        if loc.bad:
            out.append(f"기록 파일 깨짐({', '.join(loc.bad)})")
        self.rep.corrupt = list(loc.bad)
        return out

    def add_brake(self, b):
        if b not in self.rep.brakes:
            self.rep.brakes.append(b)

    # ── 원장 ──
    def entry(self, path):
        return self.ledger["pages"].get(path)

    def put(self, path, status, reason, main, expect):
        old = self.entry(path)
        if old and old.get("status") == status and (old.get("reason") or "") == reason \
                and all(old.get(k) == main.get(k) for k in MAIN):
            return False
        state.set_page(self.ledger, path, status=status, reason=reason, now=self.now_s, **main)
        self.touched[path] = expect
        return True

    def ja_file(self, path) -> Path:
        return self.clone / "ja" / path

    def live(self, path) -> bool:
        e = self.entry(path)
        return bool(e and e.get("status") in LIVE and self.ja_file(path).is_file())

    def live_set(self) -> set:
        return {p for p in self.ledger["pages"] if self.live(p)}

    def _write_file(self, p: Path, text: str) -> bool:
        if p.is_file() and p.read_text(encoding="utf-8") == text:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return True

    @contextmanager
    def guard(self, path, inp):
        """예외가 나면 이 글이 이번에 쓴 `ja/` 파일·원장·보고를 되돌린다 — 반쯤 쓴 파일이 다음 커밋에 실리지 않게."""
        files = [self.ja_file(path), state.sidecar_path(self.clone, path)] + \
            [self.clone / chart.out_rel(d) for d in (inp.charts if inp else [])]
        saved = {p: p.read_bytes() if p.is_file() else None for p in files}
        entry = copy.deepcopy(self.entry(path))
        touched = (path in self.touched, self.touched.get(path))
        try:
            yield
        except Exception:
            for p, b in saved.items():
                if b is None:
                    if p.is_file():
                        p.unlink()
                elif not p.is_file() or p.read_bytes() != b:
                    p.write_bytes(b)
            if entry is None:
                self.ledger["pages"].pop(path, None)
            else:
                self.ledger["pages"][path] = entry
            if touched[0]:
                self.touched[path] = touched[1]
            else:
                self.touched.pop(path, None)
            self.rep.pages.pop(path, None)
            self.rep.reasons.pop(path, None)
            if path in self.ready_tm:
                self.ready_tm.remove(path)
            raise

    # ── 로컬 번역 기억 ──
    def tm_path(self, path) -> Path:
        return self.cache / "tm" / (path + ".json")

    def sidecar(self, path):
        obj, _ = state.read_json(self.tm_path(path))
        if isinstance(obj, dict) and isinstance(obj.get("units"), dict):
            return obj
        side, _why = state.load_sidecar(self.clone, path)
        return side

    def log(self, path, res):
        state.write_json(self.cache / "logs" / (path + ".json"),
                         {"at": self.now_s, "status": res.status, "reason": res.reason, "detail": res.detail,
                          "tokens": res.tokens, "calls": res.calls})

    def remember(self, path, inp, code, reason):
        old = self.attempts.get(path) or {}
        if code == "deferred":
            if old.get("fp") == inp.fp:
                return                                   # 실패 기록을 미룸으로 덮지 않는다(횟수 유지)
            n = 0
        else:
            same = old.get("fp") == inp.fp and old.get("code") == code and old.get("day") == self.today
            n = int(old.get("n") or 0) + 1 if same else 1
        self.attempts[path] = {"fp": inp.fp, "code": code, "reason": reason, "day": self.today, "n": n}
        self.loc.put("attempts.json", self.attempts)

    # ── 결과 반영 ──
    def done(self, path, inp, res, outcome):
        """ready — 일본어 글·사이드카·그림을 쓰고 원장 published. 바뀐 것이 없으면 커밋에 넣지 않는다."""
        changed = self._write_file(self.ja_file(path), res.html_ja)
        for d in inp.charts:
            src = self.cache / "chart" / chart.out_rel(d)
            if src.is_file():
                dst = self.clone / chart.out_rel(d)
                if not dst.is_file() or dst.read_bytes() != src.read_bytes():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    changed = True
        side_p = state.sidecar_path(self.clone, path)
        before = side_p.read_bytes() if side_p.is_file() else None
        state.save_sidecar(self.clone, path, res.sidecar)
        changed = side_p.read_bytes() != before or changed
        state.write_json(self.tm_path(path), res.sidecar)       # 푸시가 포기돼도 다음 tick 이 0 호출로
        self.ready_tm.append(path)
        changed = self.put(path, "published", "", inp.main, inp.expect()) or changed
        if changed:
            self.touched[path] = inp.expect()
            self.rep.pages[path] = outcome
        if self.attempts.pop(path, None) is not None:
            self.loc.put("attempts.json", self.attempts)

    def notice(self, path, reason, expect) -> bool:
        """나가 있는 글에 갱신 대기 문구 — 원장은 발행 판의 입력을 그대로 둔다(새 입력을 적으면 fresh 로 굳는다)."""
        old = self.entry(path)
        html = self.ja_file(path).read_text(encoding="utf-8")
        changed = self._write_file(self.ja_file(path), assemble.with_notice(html, pipeline.KO_BASE + path))
        changed = self.put(path, "notice", reason, {k: old.get(k) for k in MAIN}, expect) or changed
        if changed:
            self.touched[path] = expect
            self.rep.pages[path] = "notice"
            self.rep.reasons[path] = reason
        return changed

    def failed(self, path, inp, code, reason, outcome):
        """보류·대기·미룸. 발행된 일본어판이 있으면 갱신 대기 문구(notice), 없으면 원장 held/pending."""
        if self.live(path):
            if self.moved(path, inp, inp.source_blob):
                return self.notice(path, reason, inp.expect())
            # 한글 쪽은 그대로인데 못 만들었다(사전·렌더러 판이 바뀌어 새 고정 번역이 검토를 기다리는 등) —
            # 나가 있는 글은 여전히 원문과 맞다. 「韓国語版が更新されました」를 붙이지 않고 그대로 둔다.
            self.rep.pages[path] = outcome
            self.rep.reasons[path] = reason
            return False
        status = "pending" if code in PENDING else "held"
        changed = self.put(path, status, reason, inp.main, inp.expect())
        if changed:
            self.touched[path] = inp.expect()
            self.rep.pages[path] = outcome
            self.rep.reasons[path] = reason
        return changed

    def moved(self, path, inp, blob) -> bool:
        """나가 있는 일본어판이 본 한글 쪽 입력(원문·본문 글자·의존 파일)과 지금 것이 다른가."""
        e = self.entry(path)
        if inp is None:
            return blob != e.get("source_blob")
        return (inp.source_blob != e.get("source_blob") or inp.text_hash != e.get("text_hash")
                or _plain(inp.deps) != _plain(e.get("deps") or {}))

    def crashed(self, path, inp, exc, blob, model):
        """글 하나의 예외 — tick 은 계속. 나가 있는 글의 원문이 바뀌었으면 갱신 대기 문구를 붙인다."""
        self.rep.errors.append(f"{path}: {type(exc).__name__}: {str(exc)[:120]}")
        reason = FIXED_REASON["error"]
        if model and inp is not None:
            self.remember(path, inp, "error", reason)     # 모델을 쓴 실패만 센다 — 하루 3번
        if not self.live(path):
            self.rep.pages[path] = "error"
            self.rep.reasons[path] = reason
            return
        # 한글 쪽 입력이 바뀐 때만 — 렌더러 판·링크 열쇠만 바뀐 재조립 중 예외에 「갱신됐다」를 붙이지 않는다
        if not self.moved(path, inp, blob):
            return
        try:
            self.notice(path, reason, inp.expect() if inp is not None else {path: blob})
        except Exception as e2:  # noqa: BLE001 — 문구도 못 붙였다: 보고만
            self.rep.errors.append(f"{path}: notice {type(e2).__name__}: {str(e2)[:80]}")

    def delete(self, path):
        for p in (self.ja_file(path), state.sidecar_path(self.clone, path)):
            if p.is_file():
                p.unlink()
        if path.startswith("posts/"):
            a = self.clone / chart.out_rel(Path(path).stem)
            if a.is_file():
                a.unlink()
        self.ledger["pages"].pop(path, None)
        self.touched[path] = {path: ""}
        if self.attempts.pop(path, None) is not None:
            self.loc.put("attempts.json", self.attempts)
        if self.tm_path(path).is_file():
            self.tm_path(path).unlink()
        self.rep.pages[path] = "deleted"

    # ── 그림 ──
    def ensure_charts(self, path, inp):
        """(True, "") 또는 (False, 사유). 일본어 그림은 cache_dir/chart 에 만들고, 글이 나갈 때 사본에 옮긴다."""
        old_deps = (self.entry(path) or {}).get("deps") or {}
        stamps_p = self.cache / "chart" / "stamps.json"
        stamps, _ = load_file(stamps_p)              # 그림 도장은 잃어도 다시 그리면 그만 — 깨져도 브레이크가 아니다
        stamps = stamps or {}
        for d in inp.charts:
            ko_blob = inp.deps.get(chart.asset_rel(d))
            dst = self.clone / chart.out_rel(d)
            if dst.is_file() and self.live(path) and old_deps.get(chart.asset_rel(d)) == ko_blob:
                continue
            if stamps.get(d) == ko_blob and (self.cache / "chart" / chart.out_rel(d)).is_file():
                continue                                     # 이 한글 그림으로 이미 만들어 뒀다
            made, why = chart.render_why(self.clone, d, dest_root=self.cache / "chart")
            if made is None and _shallow(self.clone):
                since = (date.fromisoformat(d) - timedelta(days=CHART_BACK_DAYS)).isoformat()
                subprocess.run(["git", "fetch", "-q", f"--shallow-since={since}", "origin", "main"],
                               cwd=self.clone, capture_output=True, text=True, timeout=300)
                made, why = chart.render_why(self.clone, d, dest_root=self.cache / "chart")
            if made is None:
                return False, f"그림 {d}: {str(why)[:80]}"
            stamps[d] = ko_blob
            state.write_json(stamps_p, stamps)
        return True, ""

    # ── 한 글 ──
    def classify(self, path, inp):
        e = self.entry(path)
        return state.classify(e, inp.source_blob, inp.deps, inp.text_hash, inp.renderer)

    def page(self, path, blob):
        """모델이 필요하면 (path, inp, kind) 를 돌려준다. 아니면 None(여기서 끝냈다). 예외는 `crashed`."""
        inp = None
        try:
            inp = inputs(self.clone, path, self.gloss, live=self.live_set())
            with self.guard(path, inp):
                return self._page(path, inp)
        except Exception as e:  # noqa: BLE001 — 한 글의 예외가 tick 을 멈추지 않게
            self.crashed(path, inp, e, blob, model=False)
            return None

    def _page(self, path, inp):
        kind = self.classify(path, inp)
        e = self.entry(path)
        if self.live(path) and kind == "fresh":
            if e.get("status") == "notice":           # 원본이 발행 판으로 돌아왔다 — 문구를 걷는다
                html = self.ja_file(path).read_text(encoding="utf-8")
                self._write_file(self.ja_file(path), assemble.without_notice(html))
                self.put(path, "published", "", inp.main, inp.expect())
                self.touched[path] = inp.expect()
                self.rep.pages[path] = "published"
            return None
        att = self.attempts.get(path)
        if att and att.get("fp") == inp.fp and not may_retry(att, self.today):
            # 같은 입력으로 다시 하지 않는다 — 원장·문구만 맞춘다(푸시가 포기된 뒤에도 따라오게)
            self.failed(path, inp, att.get("code"), att.get("reason") or "", "held")
            return None
        ok, why = self.ensure_charts(path, inp)
        if not ok:
            self.remember(path, inp, "chart", why)
            self.failed(path, inp, "chart", why, "held")
            return None
        res = self.build(path, model=False)
        if res is None:
            return (path, inp, "new" if e is None else kind)
        self.settle(path, inp, res, "reassembled" if self.live(path) else "published")
        return None

    def build(self, path, model, meter=None):
        try:
            if model:
                used = budget_used(self.loc, self.now, self.cfg)
                cfg = dataclasses.replace(RUN_CFG, token_cap=max(0, self.cfg.weekly_token_budget - used))
                tr, rv = meter.translate(self.translate), meter.review(self.review)
            else:
                cfg, tr, rv = RUN_CFG, _no_model, _no_model
            with (meter.hooked() if model else nullcontext()):
                return pipeline.build_page(self.clone, path, sidecar=self.sidecar(path), translate=tr, review=rv,
                                           cfg=cfg, live=self.live_set())
        except NeedModel:
            return None

    def settle(self, path, inp, res, ok_outcome):
        if res.status == "ready":
            self.done(path, inp, res, ok_outcome)
            return
        code, reason = short_reason(res)
        self.log(path, res)
        state.write_json(self.tm_path(path), res.sidecar)      # 다음에 이어 쓴다(레포 밖)
        self.remember(path, inp, code, reason)
        self.failed(path, inp, code, reason, "pending" if res.status == "pending" else "held")
        if code == "limit":
            until = note_own_limit(self.loc, self.now, res.reason)
            self.add_brake(f"일본어판 한도({_hm(until)}까지)")
        if code == "auth":
            until = self.now + AUTH_HOLD
            self.loc.put("auth.json", {"since": self.now.isoformat(), "until": until.isoformat()})
            self.rep.auth = until.isoformat()
            self.add_brake(f"로그인 만료({_hm(until)}까지)")
        if code == "budget":
            self.add_brake("주간 토큰 예산")

    def model_page(self, path, inp):
        self.rep.model_pages += 1
        meter = _Meter(self)
        was_live = self.live(path)
        try:
            inp = inp.relink(self.live_set())      # 앞 글이 이번 tick 에 나갔을 수 있다
            with self.guard(path, inp):
                res = self.build(path, model=True, meter=meter)
                if res is None:                        # 진짜 모델에서는 생기지 않는다
                    self.rep.errors.append(f"{path}: NeedModel")
                else:
                    self.settle(path, inp, res, "published")
        except Exception as e:  # noqa: BLE001
            self.crashed(path, inp, e, inp.source_blob, model=True)
        if meter.translated and self.rep.auth and "auth.json" not in self.loc.bad:
            if self.loc.drop("auth.json"):             # 시험한 한 편이 claude 답을 받았다 — 로그인이 살아 있다
                self.rep.auth = ""
        if not was_live and self.live(path):
            self.made_live.add(path)
        if budget_used(self.loc, self.now, self.cfg) >= self.cfg.weekly_token_budget:
            self.add_brake("주간 토큰 예산")
        n = review_calls(self.loc, self.now)
        if n >= self.cfg.max_review_calls_per_day:
            self.add_brake(f"하루 검토 상한({n}/{self.cfg.max_review_calls_per_day})")
        if self.loc.bad:
            self.add_brake(f"기록 파일 깨짐({', '.join(self.loc.bad)})")
            self.rep.corrupt = list(self.loc.bad)

    def run(self):
        cfg, rep = self.cfg, self.rep
        rep.brakes = self.brakes()
        tree = scope_tree(self.clone)
        pages = self.ledger["pages"]
        for path in sorted(p for p in list(pages) if p not in tree):
            self.delete(path)
        order = lambda p: (page_date(p), rank(p), p)  # noqa: E731 — 링크 대상(posts)이 먼저 조립되게
        targets = sorted({p for p in tree if eligible(p, cfg.start)} | {p for p in pages if p in tree}, key=order)
        queue = []
        for path in targets:
            got = self.page(path, tree[path])
            if got:
                queue.append(got)
        queue.sort(key=lambda q: (q[2] != "new", -page_date(q[0]).toordinal(), rank(q[0]), q[0]))
        modeled = set()
        for path, inp, _kind in queue:
            if rep.brakes or rep.model_pages >= cfg.max_pages_per_tick or (self.trial and rep.model_pages >= 1):
                code, why = "deferred", "대기"            # 원장은 고정 문구 — 브레이크는 보고·알림에
                att = self.attempts.get(path) or {}
                if att.get("fp") == inp.fp and att.get("code") in CARRY:
                    code, why = att["code"], att.get("reason") or why     # 한도로 멈춘 글은 「한도」 그대로
                self.remember(path, inp, "deferred", why)
                if code == "deferred" and not self.live(path):
                    # 아직 일본어판이 없는 새 글의 「대기」는 원장에 적지 않는다 — 적으면 한글 글이
                    # 올라온 직후마다 `ja/state.json` 만 바뀐 커밋이 main 에 하나씩 더 생긴다.
                    # 대기 사실은 이 tick 의 보고(cache 의 last.json)와 알림으로만 남긴다.
                    rep.pages[path] = "deferred"
                    rep.reasons[path] = why
                    continue
                self.failed(path, inp, code, why, "deferred")
                continue
            modeled.add(path)
            self.model_page(path, inp)
        if self.made_live:
            # 이번 tick 에 새로 나간 글을 가리키는 글 — 모델 없이 다시 조립(모델이 필요하면 다음 tick)
            for path in targets:
                if path in modeled or path not in self.ledger["pages"]:
                    continue
                try:
                    links = assemble.link_targets((self.clone / path).read_text(encoding="utf-8"), path)
                except Exception as e:  # noqa: BLE001 — 다음 tick 의 page() 가 다시 본다
                    rep.errors.append(f"{path}: 링크 {type(e).__name__}: {str(e)[:80]}")
                    continue
                if self.made_live & set(links):
                    self.page(path, tree[path])
        if self.touched:
            state.save_ledger(self.clone, self.ledger)
            try:
                lists.write(self.clone)
            except ValueError as e:
                rep.errors.append(f"목록: {str(e)[:120]}")
                self.hold_publish = True
        rep.corrupt = list(self.loc.bad)
        return rep


def tick(root, clone, *, now, cfg, translate, review, cache_dir=DEFAULT_CACHE, push=True) -> Report:
    if not cfg.enabled:
        return Report(enabled=False, skipped=cfg.why or "꺼짐")
    with tick_lock(cache_dir) as got:
        if not got:
            return Report(skipped="다른 tick 이 돌고 있다")
        t = _Tick(root, clone, now, cfg, translate, review, cache_dir)
        rep = t.run()
        if t.touched and not t.hold_publish and push:
            base = _git(clone, "rev-parse", "HEAD").strip()
            names = sorted(t.touched)
            what = ", ".join(n.rsplit(".", 1)[0] for n in names[:3]) + (f" 외 {len(names) - 3}" if len(names) > 3
                                                                         else "")
            expect = {p: e for p, e in t.touched.items()}
            try:
                rep.publish = publish.push(clone, message=f"ja: {what} (원본 {base[:7]})", expect=expect)
            except (publish.OutsideJa, publish.GitError) as e:
                rep.publish = f"error: {str(e)[:200]}"
            if rep.publish == "pushed":
                for p in t.ready_tm:
                    if t.tm_path(p).is_file():
                        t.tm_path(p).unlink()
        elif t.touched and t.hold_publish:
            rep.publish = "보류(목록 오류)"
        state.write_json(Path(cache_dir) / "last.json", rep.to_json(now))
        return rep


# ── 요약(매일 아침 알림·status) ───────────────────────────────────────────

def summary(ledger, now, last=None, attempts=None) -> list:
    """원장 → 알림 줄. 무엇이·왜 — 보류·갱신 대기 글마다 짧은 사유. `attempts` 는 로컬 시도 기록(멈춘 코드)."""
    pages = (ledger or {}).get("pages") or {}
    att = attempts if isinstance(attempts, dict) else {}
    since = now - timedelta(hours=24)
    by = {"published": [], "held": [], "pending": [], "notice": []}
    for p, e in sorted(pages.items()):
        if isinstance(e, dict) and e.get("status") in by:
            by[e["status"]].append((p, e))
    fresh = [p for p, e in by["published"] if (_parse_ts(e.get("updated")) or since) > since]
    head = (f"일본어판 — 지난 하루 발행 {len(fresh)}편 · 보류 {len(by['held'])}편 · 대기 {len(by['pending'])}편"
            + (f" · 갱신 대기 문구 {len(by['notice'])}편" if by["notice"] else ""))
    out = [head]
    fresh_last = isinstance(last, dict) and (_parse_ts(last.get("at")) or now - STALE_LAST * 2) >= now - STALE_LAST
    if fresh_last:
        # 매일 요약은 꼬리 끝 줄부터 줄인다 — 멈춘 까닭(깨진 기록·로그인)은 머리 바로 뒤에
        if last.get("corrupt"):
            out.append("일본어판: 기록 파일이 깨져 멈춤 — " + ", ".join(str(x)[:40] for x in last["corrupt"][:4]))
        if last.get("auth"):
            out.append("일본어판: 로그인 만료 — 터미널에서 `claude auth login` 뒤 `ja_local.py retry --auth`")

    def human(p):
        return isinstance(att.get(p), dict) and att[p].get("code") in HUMAN

    rows = [("보류", p, e) for p, e in by["held"]] + [("갱신 대기", p, e) for p, e in by["notice"]]
    for label, p, e in rows[:5]:
        tag = "(사람이 풀어야 함)" if human(p) else ""
        out.append(f"일본어판 {label}{tag} {p.rsplit('.', 1)[0]}: {(e.get('reason') or '-')[:80]}")
    if len(rows) > 5:
        out.append(f"일본어판 보류·갱신 대기 외 {len(rows) - 5}편 — ja_local.py status 로 확인")
    if any(human(p) for _l, p, _e in rows):
        out.append("일본어판 보류 풀기: 인명은 glossary.NAMES 에, 고정 번역 지적은 용어집에 고치면 다음 tick 이 다시 하고, "
                   "나머지는 원인을 본 뒤 `ja_local.py retry <path>`")
    if isinstance(last, dict):
        at = _parse_ts(last.get("at"))
        if at is None or now - at > STALE_LAST:
            out.append("일본어판 러너가 하루 넘게 돌지 않았어요" + (f"(마지막 {_hm(at)})" if at else ""))
        else:
            for s in (last.get("signals") or [])[:2]:
                out.append(f"일본어판: {str(s)[:60]}")
            if last.get("brakes"):
                out.append("일본어판 브레이크: " + ", ".join(str(b)[:40] for b in last["brakes"][:4]))
            pub = str(last.get("publish") or "")
            if pub and pub not in ("pushed", "nothing"):
                out.append(f"일본어판 발행: {pub[:80]}")
            if last.get("errors"):
                out.append(f"일본어판 러너 오류 {len(last['errors'])}건 — 맥 로그에서 확인")
    return out


def digest_lines(root, now, cache_dir=None, rev="origin/main") -> list:
    """매일 아침 요약에 넣을 줄 — origin/main 의 설정이 꺼져 있으면 빈 목록."""
    def show(rel):
        p = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, text=True,
                           timeout=60)
        if p.returncode:
            return None
        try:
            return json.loads(p.stdout)
        except ValueError:
            return None
    cfg = parse_config(show("ja/config.json"))
    if not cfg.enabled:
        return []
    ledger = show("ja/state.json")
    cache = Path(cache_dir or cache_dir_default())
    last, _ = state.read_json(cache / "last.json")
    attempts = Local(cache).get("attempts.json")         # 깨졌으면 빈 것 — 깨진 사실은 last.json 의 corrupt 줄로
    return summary(ledger if isinstance(ledger, dict) else {}, now, last if isinstance(last, dict) else {}, attempts)
