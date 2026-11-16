"""runner.tick — 임시 bare 저장소 + 가짜 번역·검토. 실제 claude·codex 는 부르지 않는다."""
import json
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.ja import assemble as A
from scripts.ja import runner as R
from scripts.ja.review import ReviewFailed
from scripts.ja.tests.test_pipeline import FR, FT, HTML, NEWS, PATH, TITLE, HEAD, fake_ja, no_call

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 14, 11, 0, tzinfo=KST)          # 토 11:00 — 초기화(토 09:00) 뒤, 시각대 안
POST = "posts/2026-11-13.html"
POST_HTML = """<!DOCTYPE html>
<html lang="ko"><head><title>미국 증시 마감</title>
<link rel="canonical" href="https://fdo2a.github.io/posts/2026-11-13.html">
</head><body data-register="da">
<h1>미국 증시 마감</h1>
<p>다우는 0.5% 올랐다.</p>
<img src="../assets/yield_curve_2026-11-13.png" alt="미국 국채 수익률 커브" style="width:100%">
</body></html>
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _ident(repo):
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")


def commit(repo, files, msg="c", rm=()):
    git(repo, "pull", "-q", "--rebase", "origin", "main")
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body, encoding="utf-8")
    for rel in rm:
        (repo / rel).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    git(repo, "push", "-q", "origin", "HEAD:main")


def seed_files(post=False):
    files = {PATH: HTML, "japan/data/news/2026-11-13.json": json.dumps(NEWS, ensure_ascii=False),
             "japan/daily.json": json.dumps([{"date": "2026-11-13", "title": TITLE, "headline": HEAD}],
                                            ensure_ascii=False),
             "ja/state.json": json.dumps({"version": 1, "pages": {}}),
             "scripts/ja/marker.py": "X = 1\n"}
    if post:
        files[POST] = POST_HTML
        files["assets/yield_curve_2026-11-13.png"] = b"\x89PNG-ko"
        files["posts.json"] = json.dumps([{"date": "2026-11-13", "title": "미국 증시 마감"}], ensure_ascii=False)
    return files


@pytest.fixture
def env(tmp_path):
    """bare 원격 + 사람 쪽 작업 사본(work) + 사람 폴더(root, reviews/runner.json 자리) + cache."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    _ident(seed)
    for rel, body in seed_files().items():
        p = seed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "seed")
    bare = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(bare), str(work))
    _ident(work)
    root = tmp_path / "root"
    root.mkdir()
    return {"tmp": tmp_path, "bare": bare, "work": work, "root": root, "cache": tmp_path / "cache", "n": 0}


def fresh_clone(env, depth=None):
    env["n"] += 1
    dest = env["tmp"] / f"clone{env['n']}"
    args = ["clone", "-q"] + (["--depth", str(depth), "--no-local"] if depth else []) + [
        f"file://{env['bare']}" if depth else str(env["bare"]), str(dest)]
    git(env["tmp"], *args)
    _ident(dest)
    return dest


def cfg(**kw):
    base = dict(enabled=True, start=date(2026, 11, 1), max_pages_per_tick=2, weekly_token_budget=10**9,
                windows_kst=((0, 24),), week_reset=(5, 9))
    base.update(kw)
    return R.Cfg(**base)


def run(env, ft=None, fr=None, now=NOW, c=None, clone=None, **kw):
    clone = clone or fresh_clone(env)
    rep = R.tick(env["root"], clone, now=now, cfg=c or cfg(), translate=ft or FT(), review=fr or FR(),
                 cache_dir=env["cache"], **kw)
    return rep, clone


def remote_show(env, rel):
    p = subprocess.run(["git", "show", f"main:{rel}"], cwd=env["bare"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def remote_ledger(env):
    return json.loads(remote_show(env, "ja/state.json"))["pages"]


def remote_head(env):
    return git(env["bare"], "rev-parse", "main")


# ── 설정·시각 ─────────────────────────────────────────────────────────────

def test_config_file_in_repo_parses():
    # 레포의 설정은 깨지면 안 된다(깨지면 조용히 꺼진다). 켜고 끄는 것은 사람이 정한다 — 값은 고정하지 않는다.
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    raw = json.loads((root / "ja/config.json").read_text(encoding="utf-8"))
    assert {"enabled", "start", "max_pages_per_tick", "weekly_token_budget", "windows_kst", "week_reset"} <= set(raw)
    c = R.load_config(root)
    assert c.why in ("", "enabled 가 false")
    assert R.Cfg().enabled is False                         # 기본값은 꺼짐


@pytest.mark.parametrize("obj", [None, [], {"enabled": "yes"}, {"enabled": True, "start": "11/14"},
                                 {"enabled": True, "windows_kst": [[15, 10]]},
                                 {"enabled": True, "week_reset": {"weekday": 7, "hour": 9}},
                                 {"enabled": True, "max_pages_per_tick": -1}])
def test_broken_config_is_disabled(obj):
    c = R.parse_config(obj)
    assert c.enabled is False and c.why


def test_missing_config_is_disabled(tmp_path):
    assert R.load_config(tmp_path).enabled is False


def test_windows_wrap_past_midnight():
    w = ((10, 15), (23, 29))
    at = lambda h, m=0: datetime(2026, 11, 14, h, m, tzinfo=KST)  # noqa: E731
    assert R.in_window(at(10), w) and R.in_window(at(14, 59), w) and not R.in_window(at(15), w)
    assert R.in_window(at(23), w) and R.in_window(at(4, 59), w) and not R.in_window(at(5), w)
    assert not R.in_window(at(7, 30), w) and not R.in_window(at(18), w)
    assert R.in_window(datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc), w)     # 10:00 KST


def test_week_start_is_saturday_nine_kst():
    assert R.week_start(datetime(2026, 11, 14, 9, 0, tzinfo=KST), (5, 9)) == datetime(2026, 11, 14, 9, tzinfo=KST)
    assert R.week_start(datetime(2026, 11, 14, 8, 59, tzinfo=KST), (5, 9)) == datetime(2026, 11, 7, 9, tzinfo=KST)
    assert R.week_start(datetime(2026, 11, 18, 3, 0, tzinfo=KST), (5, 9)) == datetime(2026, 11, 14, 9, tzinfo=KST)
    assert R.next_reset(NOW, (5, 9)) == datetime(2026, 11, 21, 9, tzinfo=KST)


def test_start_cut_uses_week_end_for_weeklies():
    s = date(2026, 11, 15)
    assert R.eligible("weekly/2026-W46.html", s)            # 11-09 ~ 11-15
    assert not R.eligible("weekly/2026-W45.html", s)
    assert not R.eligible("posts/2026-11-14.html", s) and R.eligible("posts/2026-11-15.html", s)
    assert not R.eligible("posts/2026-11-15.html", None)


# ── 꺼짐·잠금 ─────────────────────────────────────────────────────────────

def test_disabled_does_nothing(env):
    clone = fresh_clone(env)
    head = remote_head(env)
    rep = R.tick(env["root"], clone, now=NOW, cfg=R.Cfg(), translate=no_call, review=no_call,
                 cache_dir=env["cache"])
    assert rep.enabled is False and remote_head(env) == head and not env["cache"].exists()


def test_lock_held_skips(env):
    with R.tick_lock(env["cache"]) as got:
        assert got
        rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.skipped and not rep.pages


# ── 기본 길 ───────────────────────────────────────────────────────────────

def test_new_page_published_and_second_tick_is_idle(env):
    ft = FT()
    rep, _ = run(env, ft=ft)
    assert rep.pages == {PATH: "published"} and rep.publish == "pushed", rep
    assert rep.tokens == {"in": 10, "out": 5}
    html = remote_show(env, "ja/" + PATH)
    assert '<html lang="ja">' in html
    led = remote_ledger(env)
    assert led[PATH]["status"] == "published" and led[PATH]["renderer"] == A.RENDERER
    rows = json.loads(remote_show(env, "ja/japan/daily.json"))
    assert rows == [{"date": "2026-11-13", "title": fake_ja(TITLE), "headline": fake_ja(HEAD)}]
    assert remote_show(env, "ja/_tm/" + PATH + ".json")
    assert git(env["bare"], "log", "-1", "--format=%s", "main").startswith("ja: japan/daily/2026-11-13 (원본 ")
    head = remote_head(env)
    rep2, clone2 = run(env, ft=no_call, fr=no_call)
    assert rep2.pages == {} and rep2.publish == "" and remote_head(env) == head
    assert git(clone2, "status", "--porcelain") == ""
    last = json.loads((env["cache"] / "last.json").read_text(encoding="utf-8"))
    assert last["publish"] == "" and last["brakes"] == []


def test_pages_before_start_are_not_targets(env):
    rep, _ = run(env, ft=no_call, fr=no_call, c=cfg(start=date(2026, 11, 14)))
    assert rep.pages == {}
    rep, _ = run(env, ft=no_call, fr=no_call, c=cfg(start=None))
    assert rep.pages == {}


# ── 브레이크 ──────────────────────────────────────────────────────────────

def test_outside_window_defers_without_model(env):
    head = remote_head(env)
    rep, _ = run(env, ft=no_call, fr=no_call, now=datetime(2026, 11, 14, 8, 0, tzinfo=KST),
                 c=cfg(windows_kst=((10, 15),)))
    assert rep.brakes == ["시각대 밖"] and rep.pages == {PATH: "deferred"}
    # 아직 일본어판이 없는 새 글의 대기는 원장에 적지 않는다 — main 에 상태만 바뀐 커밋을 만들지 않는다.
    assert remote_head(env) == head
    assert PATH not in remote_ledger(env)
    assert remote_show(env, "ja/" + PATH) is None
    rep2, _ = run(env, ft=no_call, fr=no_call, now=datetime(2026, 11, 14, 8, 30, tzinfo=KST),
                  c=cfg(windows_kst=((10, 15),)))
    assert remote_head(env) == head and rep2.pages == {PATH: "deferred"}   # 같은 대기 — 커밋 없음
    rep3, _ = run(env)                                          # 시각대 안 — 발행
    assert rep3.pages == {PATH: "published"} and remote_ledger(env)[PATH]["status"] == "published"


def test_source_change_under_brake_gets_notice_then_clears(env):
    run(env)
    commit(env["work"], {PATH: HTML.replace("달러/엔은 159.81엔이었다.", "달러/엔은 159.90엔이었다.")})
    rep, _ = run(env, ft=no_call, fr=no_call, now=datetime(2026, 11, 14, 8, 0, tzinfo=KST),
                 c=cfg(windows_kst=((10, 15),)))
    assert rep.pages == {PATH: "notice"}
    html = remote_show(env, "ja/" + PATH)
    assert "data-ja-notice" in html and A.NOTICE_TEXT in html and "https://fdo2a.github.io/" + PATH in html
    led = remote_ledger(env)
    assert led[PATH]["status"] == "notice"
    rows = json.loads(remote_show(env, "ja/japan/daily.json"))
    assert len(rows) == 1                                       # 갱신 대기 문구가 붙은 글도 목록에 남는다
    rep2, _ = run(env)
    assert rep2.pages == {PATH: "published"}
    assert "data-ja-notice" not in remote_show(env, "ja/" + PATH) and "159.90" in remote_show(env, "ja/" + PATH)


def test_weekly_budget_brake(env):
    commit(env["work"], {"japan/daily/2026-11-12.html": HTML.replace("2026-11-13", "2026-11-12"),
                         "japan/data/news/2026-11-12.json": json.dumps(NEWS, ensure_ascii=False)})
    rep, _ = run(env, c=cfg(weekly_token_budget=10))
    # 첫 글(최근 날짜 먼저)이 15 토큰을 써 예산을 넘긴다 → 둘째 글은 미룬다
    assert rep.pages == {PATH: "published", "japan/daily/2026-11-12.html": "deferred"}
    assert "주간 토큰 예산" in rep.brakes
    rep2, _ = run(env, ft=no_call, fr=no_call, c=cfg(weekly_token_budget=10))
    assert "주간 토큰 예산" in rep2.brakes
    # 다음 주에는 누적이 0 부터
    rep3, _ = run(env, now=NOW + timedelta(days=7), c=cfg(weekly_token_budget=10))
    assert rep3.pages == {"japan/daily/2026-11-12.html": "published"}


def test_max_pages_per_tick_new_first(env):
    run(env)                                                    # 11-13 발행
    commit(env["work"], {"japan/daily/2026-11-12.html": HTML.replace("2026-11-13", "2026-11-12"),
                         "japan/data/news/2026-11-12.json": json.dumps(NEWS, ensure_ascii=False),
                         PATH: HTML.replace("159.81", "159.82")})
    rep, _ = run(env, c=cfg(max_pages_per_tick=1))
    # 새 글(11-12)이 고친 글(11-13)보다 먼저 — 11-13 은 미뤄져 갱신 대기 문구
    assert rep.pages == {"japan/daily/2026-11-12.html": "published", PATH: "notice"}


def test_own_limit_pends_and_brakes_until_reset_time(env):
    rep, _ = run(env, fr=FR(limit_at=0))
    assert rep.pages == {PATH: "pending"} and any(b.startswith("일본어판 한도") for b in rep.brakes)
    led = remote_ledger(env)
    assert led[PATH]["status"] == "pending" and led[PATH]["reason"] == "한도"
    lim = json.loads((env["cache"] / "limit.json").read_text(encoding="utf-8"))
    assert R._parse_ts(lim["until"]) == NOW + timedelta(hours=5)      # 문구에 시각이 없으면 5시간
    side = json.loads((env["cache"] / "tm" / (PATH + ".json")).read_text(encoding="utf-8"))
    assert side["units"]                                               # 번역은 로컬에 남았다
    rep2, _ = run(env, ft=no_call, fr=no_call, now=NOW + timedelta(hours=1))
    assert any(b.startswith("일본어판 한도") for b in rep2.brakes) and rep2.pages == {}
    ft = FT()
    rep3, _ = run(env, ft=ft, now=NOW + timedelta(hours=5, minutes=1))
    assert rep3.pages == {PATH: "published"} and ft.calls == []        # 번역은 잇고 검토만 다시


def test_own_limit_reads_claude_reset_time(env):
    until = R.own_limit_until("You've hit your weekly limit · resets Nov 21, 9am (Asia/Seoul)", NOW)
    assert until == datetime(2026, 11, 21, 9, tzinfo=KST)
    until = R.own_limit_until("ERROR: You've hit your usage limit. try again in 2 hours", NOW)
    assert until == NOW + timedelta(hours=2)


def test_korean_side_limit_latches_until_next_reset(env):
    (env["root"] / "reviews").mkdir()
    rj = env["root"] / "reviews" / "runner.json"
    rj.write_text(json.dumps({"limit_hits": {"2026-11-14": 1}}), encoding="utf-8")
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.brakes == ["한글 쪽 한도(11/21 09:00까지)"] and rep.pages == {PATH: "deferred"}
    rj.write_text(json.dumps({"limit_hits": {}}), encoding="utf-8")          # 흔적이 사라져도
    rep2, _ = run(env, ft=no_call, fr=no_call, now=NOW + timedelta(days=2))
    assert rep2.brakes == ["한글 쪽 한도(11/21 09:00까지)"]
    rep3, _ = run(env, now=datetime(2026, 11, 21, 10, tzinfo=KST))
    assert rep3.brakes == [] and rep3.pages == {PATH: "published"}


@pytest.mark.parametrize("obj,hit", [
    ({"limit_hits": {"2026-11-13": 2}}, False),            # 지난주(초기화 전 날짜)
    ({"limit_hits": {"2026-11-14": 1}}, True),
    ({"correction_blocked_until": "2026-11-15T09:00:00+09:00"}, True),
    ({"correction_blocked_until": "2026-11-14T10:00:00+09:00"}, False),   # 이미 지났다
    ({"errors": {"정정-us": {"kind": "한도", "detail": "x"}}}, True),
    ({"errors": {"us": {"kind": "판정불가", "detail": "x"}}}, False),
    ({}, False),
])
def test_korean_limit_signals(tmp_path, obj, hit):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "runner.json").write_text(json.dumps(obj), encoding="utf-8")
    assert bool(R.korean_limit_signals(tmp_path, NOW, cfg())) is hit


def test_korean_limit_file_missing_or_broken(tmp_path):
    assert R.korean_limit_signals(tmp_path, NOW, cfg()) == []          # 없음 = 흔적 없음
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "runner.json").write_text("{", encoding="utf-8")
    with pytest.raises(R.CacheCorrupt):                                 # 깨짐 ≠ 흔적 없음(codex 구현 1회 #2)
        R.korean_limit_signals(tmp_path, NOW, cfg())


# ── 보류·재시도 ───────────────────────────────────────────────────────────

def test_held_is_not_retried_with_same_input(env):
    ft = FT(names=["가타야마 사쓰키"])
    rep, _ = run(env, ft=ft, fr=no_call)                  # 러너는 인명 보류면 검토를 부르지 않는다
    assert rep.pages == {PATH: "held"}
    led = remote_ledger(env)
    assert led[PATH]["status"] == "held" and led[PATH]["reason"] == "확인 안 된 인명: 가타야마 사쓰키"
    log = json.loads((env["cache"] / "logs" / (PATH + ".json")).read_text(encoding="utf-8"))
    assert log["detail"]["unverified_names"] == ["가타야마 사쓰키"]
    head = remote_head(env)
    rep2, _ = run(env, ft=no_call, fr=no_call)
    assert rep2.pages == {} and remote_head(env) == head
    # 용어집이 바뀌면 다시 한다
    import scripts.ja.runner as RR
    old = RR.glossary_version
    RR.glossary_version = lambda: "changed"
    try:
        rep3, _ = run(env)
    finally:
        RR.glossary_version = old
    assert rep3.pages == {PATH: "published"}


def test_retry_command_forgets_the_attempt(env):
    run(env, ft=FT(names=["가타야마 사쓰키"]), fr=no_call)
    assert R.forget_attempt(env["cache"], PATH) is True and R.forget_attempt(env["cache"], PATH) is False
    ft = FT(names=["가타야마 사쓰키"])
    run(env, ft=ft, fr=no_call)
    assert len(ft.calls) == 1                              # 강제로 한 번 더


class AlwaysFail:
    def __init__(self):
        self.calls = 0

    def __call__(self, rows, scope):
        self.calls += 1
        raise ReviewFailed("형식 오류")


def test_review_failure_retried_three_times_a_day(env):
    fr = AlwaysFail()
    for i in range(4):
        rep, _ = run(env, fr=fr, now=NOW + timedelta(minutes=30 * i))
    assert fr.calls == 3
    assert remote_ledger(env)[PATH]["reason"] == "검토 실패(codex 응답)"
    run(env, fr=fr, now=NOW + timedelta(days=1))
    assert fr.calls == 4                                    # 다음 날 다시


def test_ledger_reason_is_short_and_detail_goes_to_cache(env):
    from scripts.ja.review import Finding

    def find(rows, scope, n):
        uid = next(r["id"] for r in rows if "달러/엔" in r["ko"])
        return [Finding(uid, "誤訳", "원문은 159.81엔인데 訳은 내부 문구 SECRETLINE", "ドル円は159.81円")]
    rep, _ = run(env, fr=FR(find=find))
    led = remote_ledger(env)
    assert led[PATH]["status"] == "held" and led[PATH]["reason"].startswith("검토 지적 ")
    assert "SECRETLINE" not in remote_show(env, "ja/state.json")
    assert "SECRETLINE" in (env["cache"] / "logs" / (PATH + ".json")).read_text(encoding="utf-8")


def test_reassemble_on_renderer_bump_needs_no_model(env, monkeypatch):
    run(env)
    monkeypatch.setattr(A, "RENDERER", "r-test")
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.pages == {PATH: "reassembled"} and remote_ledger(env)[PATH]["renderer"] == "r-test"


def test_deleted_source_removes_japanese_page(env):
    run(env)
    commit(env["work"], {"japan/daily.json": "[]"}, rm=[PATH])
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.pages == {PATH: "deleted"}
    assert remote_show(env, "ja/" + PATH) is None and remote_show(env, "ja/_tm/" + PATH + ".json") is None
    assert PATH not in remote_ledger(env) and json.loads(remote_show(env, "ja/japan/daily.json")) == []


def test_abandoned_push_is_redone_without_model(env, monkeypatch):
    from scripts.ja import publish as PB
    monkeypatch.setattr(PB, "push", lambda clone, **k: "abandoned: 원본이 그 사이 바뀌었다(x)")
    rep, _ = run(env)
    assert rep.publish.startswith("abandoned") and remote_show(env, "ja/" + PATH) is None
    monkeypatch.undo()
    rep2, _ = run(env, ft=no_call, fr=no_call)
    assert rep2.pages == {PATH: "published"} and rep2.publish == "pushed"
    assert not (env["cache"] / "tm" / (PATH + ".json")).exists()        # 푸시가 되면 로컬 기억을 지운다


def test_held_after_abandoned_push_is_not_redone(env, monkeypatch):
    from scripts.ja import publish as PB
    monkeypatch.setattr(PB, "push", lambda clone, **k: "abandoned: x")
    run(env, ft=FT(names=["가타야마 사쓰키"]), fr=no_call)
    monkeypatch.undo()
    rep, _ = run(env, ft=no_call, fr=no_call)               # 시도 기록은 로컬 — 모델 없이 원장만
    assert rep.pages == {PATH: "held"} and remote_ledger(env)[PATH]["status"] == "held"


# ── 그림 ──────────────────────────────────────────────────────────────────

def _with_post(env):
    files = seed_files(post=True)
    commit(env["work"], {k: files[k] for k in (POST, "assets/yield_curve_2026-11-13.png", "posts.json")})


def test_chart_failure_holds_before_model(env, monkeypatch):
    _with_post(env)
    from scripts.ja import chart as CH
    monkeypatch.setattr(CH, "render_why", lambda root, d, dest_root=None: (None, "수집 커밋이 없다"))
    ft = FT()
    rep, _ = run(env, ft=ft)
    assert rep.pages[POST] == "held" and remote_ledger(env)[POST]["reason"].startswith("그림 2026-11-13")
    assert all("미국" not in k for c in ft.calls for k in c["kos"])        # 그 글에는 모델을 안 불렀다


def test_chart_failure_is_retried_three_times_a_day(env, monkeypatch):
    _with_post(env)
    from scripts.ja import chart as CH
    calls = []

    def fail(root, d, dest_root=None):
        calls.append(d)
        return None, "글꼴이 없다"
    monkeypatch.setattr(CH, "render_why", fail)
    for i in range(4):
        run(env, ft=no_call if i else FT(), fr=no_call if i else FR(), now=NOW + timedelta(minutes=30 * i))
    assert len(calls) == 3


def test_chart_is_rendered_and_published_with_page(env, monkeypatch):
    _with_post(env)
    from scripts.ja import chart as CH

    def fake(root, d, dest_root=None):
        p = dest_root / CH.out_rel(d)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG-ja")
        return p, None
    monkeypatch.setattr(CH, "render_why", fake)
    rep, _ = run(env)
    assert rep.pages[POST] == "published"
    assert subprocess.run(["git", "cat-file", "-e", "main:ja/assets/yield_curve_2026-11-13.png"],
                          cwd=env["bare"]).returncode == 0
    assert 'src="../assets/yield_curve_2026-11-13.png"' in remote_show(env, "ja/" + POST)


def test_shallow_clone_is_deepened_for_the_chart(env, monkeypatch):
    _with_post(env)
    old = git(env["work"], "rev-parse", "HEAD")
    for i in range(3):
        commit(env["work"], {"noise.txt": str(i)})
    from scripts.ja import chart as CH
    seen = []

    def fake(root, d, dest_root=None):
        ok = subprocess.run(["git", "cat-file", "-e", old], cwd=root).returncode == 0
        seen.append(ok)
        if not ok:
            return None, "얕은 클론"
        p = dest_root / CH.out_rel(d)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG-ja")
        return p, None
    monkeypatch.setattr(CH, "render_why", fake)
    clone = fresh_clone(env, depth=1)
    rep, _ = run(env, clone=clone)
    assert seen == [False, True] and rep.pages[POST] == "published"


# ── 요약 ──────────────────────────────────────────────────────────────────

def test_summary_lines():
    led = {"pages": {
        "posts/2026-11-13.html": {"status": "published", "updated": "2026-11-14T10:00:00+09:00"},
        "posts/2026-11-01.html": {"status": "published", "updated": "2026-11-02T10:00:00+09:00"},
        "news/2026-11-13.html": {"status": "held", "reason": "확인 안 된 인명: 가타야마 사쓰키"},
        "japan/daily/2026-11-13.html": {"status": "pending", "reason": "대기"},
        "weekly/2026-W46.html": {"status": "notice", "reason": "검토 지적 2건(#3·#9)"}}}
    last = {"at": "2026-11-14T10:30:00+09:00", "brakes": ["시각대 밖"], "publish": "pushed", "errors": []}
    out = R.summary(led, NOW, last)
    assert out[0] == "일본어판 — 지난 하루 발행 1편 · 보류 1편 · 대기 1편 · 갱신 대기 문구 1편"
    assert "일본어판 보류 news/2026-11-13: 확인 안 된 인명: 가타야마 사쓰키" in out
    assert "일본어판 갱신 대기 weekly/2026-W46: 검토 지적 2건(#3·#9)" in out
    assert "일본어판 브레이크: 시각대 밖" in out
    stale = R.summary(led, NOW, {"at": "2026-11-12T10:00:00+09:00"})
    assert stale[-1].startswith("일본어판 러너가 하루 넘게 돌지 않았어요")


def test_digest_lines_off_when_disabled_on_origin(env):
    assert R.digest_lines(env["work"], NOW, cache_dir=env["cache"]) == []
    commit(env["work"], {"ja/config.json": json.dumps({"enabled": True, "start": "2026-11-01"})})
    git(env["work"], "fetch", "-q", "origin")
    got = R.digest_lines(env["work"], NOW, cache_dir=env["cache"])
    assert got[0].startswith("일본어판 — 지난 하루 발행 0편")
