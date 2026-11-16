"""runner — codex 구현 검토 1회차(B1-B11, (d), 부하 ②) 재현. 임시 bare 저장소 + 가짜 번역·검토."""
import ast
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.ja import news as NW
from scripts.ja import pipeline as P
from scripts.ja import publish as PB
from scripts.ja import runner as R
from scripts.ja.tests.test_pipeline import FR, FT, HTML, NEWS, PATH, no_call
from scripts.ja.tests.test_runner import (KST, NOW, cfg, commit, env, fresh_clone, git, remote_head,  # noqa: F401
                                          remote_ledger, remote_show, run)
from scripts.ja.translate import AuthExpired, LimitReached
from scripts.ja.translate import Out as TOut

REPO = Path(__file__).resolve().parents[3]
P2 = "japan/daily/2026-11-12.html"


def second_page(env):
    commit(env["work"], {P2: HTML.replace("2026-11-13", "2026-11-12"),
                         "japan/data/news/2026-11-12.json": json.dumps(NEWS, ensure_ascii=False)})


def fake_result(stop, status="pending", tokens=None, calls=None):
    return P.Result(status, None, {}, stop, {"stop": stop}, tokens or {"in": 0, "out": 0}, 0,
                    calls or {"translate": 0, "review": 0, "adjudicate": 0})


def budget(env):
    return json.loads((env["cache"] / "budget.json").read_text(encoding="utf-8"))["tokens"]


# ── B1 토큰 예산 ───────────────────────────────────────────────────────────

class Boom(FT):
    """첫 호출은 성공, 둘째 호출에서 pipeline 이 삼키지 않는 예외."""

    def __call__(self, units, **k):
        if self.calls:
            self.calls.append({})
            raise RuntimeError("boom")
        return super().__call__(units, **k)


def test_unexpected_exception_mid_page_keeps_spent_tokens_and_tick_survives(env):
    # 첫 번역은 기계 검사에 걸려(숫자 바꿈) 다시 부르고, 그 둘째 호출이 터진다
    ft = Boom(bad=lambda ko, n: "数字なし" if "159.81" in ko and n == 0 else None)
    rep, _ = run(env, ft=ft, fr=FR())
    assert budget(env) == 15 and rep.tokens == {"in": 10, "out": 5}
    assert any("RuntimeError" in e for e in rep.errors) and rep.pages[PATH] == "error"
    assert PATH not in (remote_ledger(env) or {})                      # 처음 글의 오류는 원장에 적지 않는다


def test_partial_tokens_of_a_failed_call_are_counted(env):
    class Half(FT):
        def __call__(self, units, **k):
            self.calls.append({})
            raise LimitReached("You've hit your weekly limit",
                               partial=TOut(texts={}, tokens={"in": 7, "out": 3}, calls=1))
    rep, _ = run(env, ft=Half(), fr=no_call)
    assert budget(env) == 10 and rep.pages[PATH] == "pending"


def test_token_cap_is_the_remaining_weekly_budget(env, monkeypatch):
    seen = []

    def spy(root, path, **k):
        if k["translate"] is R._no_model:
            raise R.NeedModel()
        seen.append(k["cfg"].token_cap)
        return fake_result("budget")
    R.state.write_json(env["cache"] / "budget.json",
                       {"week": R.week_start(NOW, (5, 9)).isoformat(), "tokens": 400})
    monkeypatch.setattr(R.pipeline, "build_page", spy)
    rep, _ = run(env, c=cfg(weekly_token_budget=1000))
    assert seen == [600]
    assert remote_ledger(env)[PATH]["reason"] == "주간 예산" and rep.pages[PATH] == "pending"


# ── B2 깨진 기록 파일 ──────────────────────────────────────────────────────

WEEK = R.week_start(NOW, (5, 9)).isoformat()


@pytest.mark.parametrize("name,body", [
    ("budget.json", "{"),
    ("budget.json", json.dumps({"week": WEEK, "tokens": "many"})),
    ("limit.json", json.dumps({"until": "soon"})),
    ("ko_limit.json", "[]"),
    ("attempts.json", json.dumps({PATH: "x"})),
    ("auth.json", "{"),
    ("review_calls.json", json.dumps({"2026-11-14": "a"})),
])
def test_corrupt_cache_file_brakes_and_is_not_overwritten(env, name, body):
    p = env["cache"] / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    head = remote_head(env)
    for i in range(2):                                         # 두 번째 tick 에도 그대로 — 스스로 풀리지 않는다
        rep, _ = run(env, ft=no_call, fr=no_call, now=NOW + timedelta(minutes=30 * i))
        assert f"기록 파일 깨짐({name})" in rep.brakes and rep.pages == {PATH: "deferred"}
        assert p.read_text(encoding="utf-8") == body
    assert remote_head(env) == head
    last = json.loads((env["cache"] / "last.json").read_text(encoding="utf-8"))
    assert last["corrupt"] == [name]
    assert R.summary({}, NOW, last)[1] == f"일본어판: 기록 파일이 깨져 멈춤 — {name}"      # 머리 바로 뒤(꼬리부터 줄인다)


def test_corrupt_korean_runner_file_brakes(env):
    (env["root"] / "reviews").mkdir()
    (env["root"] / "reviews" / "runner.json").write_text("{", encoding="utf-8")
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert "기록 파일 깨짐(reviews/runner.json)" in rep.brakes and rep.pages == {PATH: "deferred"}


def test_missing_cache_files_are_a_clean_start(env):
    rep, _ = run(env)
    assert rep.brakes == [] and rep.pages == {PATH: "published"}


# ── B3 없던 의존 파일·공유 코드 ────────────────────────────────────────────

def test_news_candidates_cover_existing_data_files(tmp_path):
    # 넓은 범위(앞뒤 40일·주차 ±8)에 후보가 될 만한 파일을 전부 깔고, data_files 가 고른 것이 후보 안에 드는지
    from datetime import date
    base = date(2026, 11, 13)
    rels = []
    for i in range(-40, 41):
        s = (base + timedelta(days=i)).isoformat()
        rels += [f"data/news/{s}.json", f"japan/data/news/{s}.json", f"japan/data/news/daily/{s}.json"]
        y, w, _ = (base + timedelta(days=i)).isocalendar()
        rels.append(f"japan/data/{y}-W{w:02d}.news.json")
    for rel in rels:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("{}", encoding="utf-8")
    for path in (PATH, "weekly/2026-W46.html", "news/2026-11-01.html"):
        have = {p.relative_to(tmp_path).as_posix() for p in NW.data_files(tmp_path, path)}
        assert have and have <= set(R.news_candidates(path)), have - set(R.news_candidates(path))


def test_inputs_expect_has_absent_candidates_but_deps_do_not(env):
    clone = fresh_clone(env)
    inp = R.inputs(clone, PATH, live=set())
    exp = inp.expect()
    assert exp["japan/data/news/daily/2026-11-13.json"] == ""
    assert "japan/data/news/daily/2026-11-13.json" not in inp.deps


def test_dependency_that_appears_during_push_abandons(env, monkeypatch):
    real = PB.push

    def racing(clone, **k):
        commit(env["work"], {"japan/data/news/daily/2026-11-13.json": json.dumps(NEWS, ensure_ascii=False)})
        return real(clone, **k)
    monkeypatch.setattr(PB, "push", racing)
    rep, _ = run(env)
    assert rep.publish.startswith("abandoned: 원본이 그 사이 바뀌었다")
    assert remote_show(env, "ja/" + PATH) is None


def _ja_imports():
    names = set()
    for f in list((REPO / "scripts/ja").glob("*.py")) + [REPO / "scripts/ja_local.py"]:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
                names |= {f"{node.module}.{a.name}" for a in node.names}     # from pkg import 모듈
    return sorted(names)


# 브레이크(`runner.cloud_missing`)만 정하는 모듈과 그 import — 만든 글에 닿지 않아 푸시 재확인 대상이 아니다
SIGNAL_ONLY = ("scripts/review/publish_watch.py", "scripts/review/prepub_view.py", "scripts/verification/")


def test_code_paths_cover_shared_code_the_edition_loads():
    code = ("import importlib, json, sys\n"
            f"sys.path[:0] = [{str(REPO)!r}, {str(REPO / 'scripts')!r}]\n"
            f"for n in {_ja_imports()!r}:\n"
            "    try:\n        importlib.import_module(n)\n    except Exception:\n        pass\n"
            "print(json.dumps(sorted({getattr(m, '__file__', None) or '' for m in list(sys.modules.values())})))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
    files = [Path(f).resolve() for f in json.loads(out.stdout) if f]
    rel = sorted({f.relative_to(REPO).as_posix() for f in files if REPO / "scripts" in f.parents})
    loose = [r for r in rel if r != "scripts/__init__.py" and not r.startswith(SIGNAL_ONLY)
             and not any(r == c or r.startswith(c.rstrip("/") + "/") for c in PB.CODE_PATHS)]
    assert "scripts/collect_market_data.py" in rel and "scripts/review/runner.py" in rel
    assert "scripts/review/publish_watch.py" in rel                     # 예외 목록이 헛돌지 않게
    assert loose == []


# ── B4 다른 글의 목록 변경 ─────────────────────────────────────────────────

def test_korean_list_change_abandons_and_next_tick_needs_no_model(env, monkeypatch):
    real = PB.push

    def racing(clone, **k):
        rows = [{"date": "2026-11-13", "title": "일본 증시 마감 — 닛케이 0.53% 상승",
                 "headline": "닛케이평균은 0.53% 올랐다."},
                {"date": "2026-11-11", "title": "다른 글 제목 바뀜"}]
        commit(env["work"], {"japan/daily.json": json.dumps(rows, ensure_ascii=False)})
        return real(clone, **k)
    monkeypatch.setattr(PB, "push", racing)
    rep, _ = run(env)
    assert rep.publish == "abandoned: 한글 목록이 그 사이 바뀌었다(japan/daily.json)"
    assert remote_show(env, "ja/" + PATH) is None
    monkeypatch.setattr(PB, "push", real)
    rep2, _ = run(env, ft=no_call, fr=no_call)                 # 포기 뒤 다음 tick — 모델 호출 0
    assert rep2.pages == {PATH: "published"} and rep2.publish == "pushed" and rep2.model_pages == 0


# ── B5 글 처리 중 예외 ─────────────────────────────────────────────────────

def test_exception_on_changed_live_page_puts_notice(env, monkeypatch):
    run(env)
    commit(env["work"], {PATH: HTML.replace("159.81", "159.90")})

    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(R.pipeline, "build_page", boom)
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.pages == {PATH: "notice"} and any("OSError" in e for e in rep.errors)
    led = remote_ledger(env)
    assert led[PATH]["status"] == "notice" and led[PATH]["reason"] == "처리 오류"
    assert "data-ja-notice" in remote_show(env, "ja/" + PATH)
    head = remote_head(env)
    rep2, _ = run(env, ft=no_call, fr=no_call)                 # 같은 실패 — 커밋 없음
    assert remote_head(env) == head and rep2.publish == ""


def test_exception_in_inputs_on_changed_live_page_puts_notice(env, monkeypatch):
    run(env)
    commit(env["work"], {PATH: HTML.replace("159.81", "159.90")})
    monkeypatch.setattr(R, "inputs", lambda *a, **k: (_ for _ in ()).throw(ValueError("read")))
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.pages == {PATH: "notice"} and remote_ledger(env)[PATH]["reason"] == "처리 오류"


def test_exception_after_files_written_leaves_no_orphan(env, monkeypatch):
    def broken(*a, **k):
        raise OSError("sidecar")
    monkeypatch.setattr(R.state, "save_sidecar", broken)
    rep, clone = run(env)
    assert any("OSError" in e for e in rep.errors)
    assert not (clone / "ja" / PATH).exists() and PATH not in R.state.load_ledger(clone)[0]["pages"]
    assert git(clone, "status", "--porcelain") == ""


def test_crash_then_brake_does_not_write_new_page_to_ledger(env, monkeypatch):
    real = R.pipeline.build_page

    def boom(root, path, **k):
        if k["translate"] is R._no_model:
            return real(root, path, **k)
        raise OSError("disk")
    monkeypatch.setattr(R.pipeline, "build_page", boom)
    run(env)
    monkeypatch.setattr(R.pipeline, "build_page", real)
    head = remote_head(env)
    rep, _ = run(env, ft=no_call, fr=no_call, now=datetime(2026, 11, 14, 8, 0, tzinfo=KST),
                 c=cfg(windows_kst=((10, 15),)))
    assert rep.pages == {PATH: "deferred"} and remote_head(env) == head
    assert PATH not in remote_ledger(env)


def test_crash_during_renderer_reassembly_leaves_live_page_alone(env, monkeypatch):
    from scripts.ja import assemble as A
    run(env)
    head = remote_head(env)
    before = remote_show(env, "ja/" + PATH)
    monkeypatch.setattr(A, "RENDERER", "r-test")

    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(R.pipeline, "build_page", boom)
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert any("OSError" in e for e in rep.errors) and PATH not in rep.pages
    assert remote_head(env) == head and remote_show(env, "ja/" + PATH) == before


# ── B6 로그인 만료 ─────────────────────────────────────────────────────────

class AuthOnce(FT):
    def __init__(self, n_auth=1):
        super().__init__()
        self.n_auth = n_auth

    def __call__(self, units, **k):
        if self.n_auth > 0:
            self.n_auth -= 1
            self.calls.append({})
            raise AuthExpired("Failed to authenticate. Run claude auth login")
        return super().__call__(units, **k)


def test_auth_expiry_is_a_global_brake_then_one_trial(env):
    second_page(env)
    ft = AuthOnce()
    rep, _ = run(env, ft=ft, fr=FR())
    assert len(ft.calls) == 1 and rep.model_pages == 1           # 둘째 글은 부르지 않는다
    assert rep.pages[PATH] == "pending" and rep.pages[P2] == "deferred"
    assert remote_ledger(env)[PATH]["reason"] == "로그인 만료"
    auth = json.loads((env["cache"] / "auth.json").read_text(encoding="utf-8"))
    assert R._parse_ts(auth["until"]) == NOW + timedelta(hours=6)
    last = json.loads((env["cache"] / "last.json").read_text(encoding="utf-8"))
    assert "일본어판: 로그인 만료 — 터미널에서 `claude auth login`" in " ".join(R.summary({}, NOW, last))
    rep2, _ = run(env, ft=no_call, fr=no_call, now=NOW + timedelta(hours=3))
    assert any(b.startswith("로그인 만료") for b in rep2.brakes)
    ft3 = FT()
    rep3, _ = run(env, ft=ft3, now=NOW + timedelta(hours=6, minutes=1))   # 6시간 뒤 — 한 편만 시험
    assert rep3.model_pages == 1 and list(rep3.pages.values()).count("published") == 1
    assert not (env["cache"] / "auth.json").exists()                     # 되면 풀린다
    rep4, _ = run(env, now=NOW + timedelta(hours=6, minutes=31))
    assert rep4.brakes == [] and "published" in rep4.pages.values()


def test_auth_trial_failing_again_rearms(env):
    run(env, ft=AuthOnce(), fr=FR())
    rep, _ = run(env, ft=AuthOnce(), fr=FR(), now=NOW + timedelta(hours=7))
    auth = json.loads((env["cache"] / "auth.json").read_text(encoding="utf-8"))
    assert R._parse_ts(auth["until"]) == NOW + timedelta(hours=13) and rep.model_pages == 1
    assert any(b.startswith("로그인 만료") for b in rep.brakes)


def test_retry_auth_clears_the_brake(env):
    run(env, ft=AuthOnce(), fr=FR())
    assert R.clear_auth(env["cache"]) is True and R.clear_auth(env["cache"]) is False
    rep, _ = run(env, now=NOW + timedelta(hours=1))
    assert rep.pages == {PATH: "published"}


# ── B7 글 사이 링크 ────────────────────────────────────────────────────────

NEWS_PAGE = "news/2026-11-13.html"
NEWS_HTML = """<!DOCTYPE html>
<html lang="ko"><head><title>뉴스 정리</title>
<link rel="canonical" href="https://fdo2a.github.io/news/2026-11-13.html">
</head><body data-register="da">
<h1>뉴스 정리</h1>
<p>자세한 시황은 <a href="../posts/2026-11-13.html">마감 보고서</a>에 있다.</p>
</body></html>
"""
POST = "posts/2026-11-13.html"
POST_HTML = """<!DOCTYPE html>
<html lang="ko"><head><title>미국 증시 마감</title>
<link rel="canonical" href="https://fdo2a.github.io/posts/2026-11-13.html">
</head><body data-register="da">
<h1>미국 증시 마감</h1>
<p>다우는 0.5% 올랐다.</p>
<p>가타야마 사쓰키 재무상이 견제했다.</p>
</body></html>
"""


def _with_news_and_post(env):
    commit(env["work"], {NEWS_PAGE: NEWS_HTML, POST: POST_HTML,
                         "news.json": json.dumps([{"date": "2026-11-13", "title": "뉴스 정리"}], ensure_ascii=False),
                         "posts.json": json.dumps([{"date": "2026-11-13", "title": "미국 증시 마감"}],
                                                  ensure_ascii=False)})


def test_link_to_unpublished_page_goes_korean_then_follows_publication(env, monkeypatch):
    _with_news_and_post(env)
    rep, _ = run(env, ft=FT(names=["가타야마 사쓰키"]), fr=FR(), c=cfg(max_pages_per_tick=5))
    assert rep.pages[POST] == "held" and rep.pages[NEWS_PAGE] == "published"
    led = remote_ledger(env)
    assert led[NEWS_PAGE]["deps"]["link:" + POST] == "0"
    html = remote_show(env, "ja/" + NEWS_PAGE)
    assert 'href="../../posts/2026-11-13.html"' in html                  # 한글 원문으로
    monkeypatch.setattr(R, "glossary_version", lambda: "names-added")
    rep2, _ = run(env, c=cfg(max_pages_per_tick=5))
    assert rep2.pages[POST] == "published" and rep2.pages[NEWS_PAGE] == "reassembled"
    assert 'href="../posts/2026-11-13.html"' in remote_show(env, "ja/" + NEWS_PAGE)
    assert remote_ledger(env)[NEWS_PAGE]["deps"]["link:" + POST] == "1"
    head = remote_head(env)
    rep3, _ = run(env, ft=no_call, fr=no_call, c=cfg(max_pages_per_tick=5))
    assert rep3.pages == {} and remote_head(env) == head


def test_link_target_deletion_reassembles_without_model(env):
    _with_news_and_post(env)
    run(env, c=cfg(max_pages_per_tick=5))
    commit(env["work"], {"posts.json": "[]"}, rm=[POST])
    rep, _ = run(env, ft=no_call, fr=no_call, c=cfg(max_pages_per_tick=5))
    assert rep.pages[POST] == "deleted" and rep.pages[NEWS_PAGE] == "reassembled"
    assert 'href="../../posts/2026-11-13.html"' in remote_show(env, "ja/" + NEWS_PAGE)


def test_link_target_comes_first_in_queue(env):
    _with_news_and_post(env)
    rep, _ = run(env, c=cfg(max_pages_per_tick=1))
    assert rep.pages[POST] == "published" and rep.pages[NEWS_PAGE] == "deferred"


def test_link_deps_stay_out_of_retry_key_and_push_check(env):
    clone = fresh_clone(env)
    a = R.inputs(clone, PATH, live=set())
    b = R.inputs(clone, PATH, live={POST})
    a.deps["link:" + POST], b.deps["link:" + POST] = "0", "1"
    assert a.fp == b.fp and not any(k.startswith("link:") for k in a.expect())


# ── B9 사람이 풀어야 하는 보류 ─────────────────────────────────────────────

def test_summary_marks_holds_that_need_a_human():
    led = {"pages": {"news/2026-11-13.html": {"status": "held", "reason": "확인 안 된 인명: 가타야마"},
                     "posts/2026-11-13.html": {"status": "held", "reason": "그림 2026-11-13: x"}}}
    att = {"news/2026-11-13.html": {"code": "names"}, "posts/2026-11-13.html": {"code": "chart"}}
    out = R.summary(led, NOW, None, attempts=att)
    assert "일본어판 보류(사람이 풀어야 함) news/2026-11-13: 확인 안 된 인명: 가타야마" in out
    assert "일본어판 보류 posts/2026-11-13: 그림 2026-11-13: x" in out
    assert any(x.startswith("일본어판 보류 풀기:") and "ja_local.py retry" in x for x in out)


@pytest.mark.parametrize("stop,reason", [("auth", "로그인 만료"), ("budget", "주간 예산"),
                                         ("news_lang", "원문 언어 불확실"), ("news_malformed", "뉴스 항목 꼴"),
                                         ("fixed", "고정 번역 지적")])
def test_short_reason_for_new_stop_codes(stop, reason):
    code, why = R.short_reason(fake_result(stop))
    assert code == stop and why.startswith(reason)


def test_fixed_reason_names_unit_ids():
    r = fake_result("fixed", status="held")
    r.detail["fixed_findings"] = [{"id": 7, "kind": "誤訳"}, {"id": 3, "kind": "不自然"}, {"id": 7, "kind": "不自然"}]
    assert R.short_reason(r) == ("fixed", "고정 번역 지적 2단위(#3·#7)")


def test_retry_rules_for_new_stop_codes():
    for code in ("auth", "budget"):
        assert R.may_retry({"code": code, "day": "2026-11-14", "n": 9}, "2026-11-14")
    for code in ("fixed", "news_lang", "news_malformed"):
        assert not R.may_retry({"code": code, "day": "2026-11-13", "n": 1}, "2026-11-14")
    assert R.may_retry({"code": "error", "day": "2026-11-14", "n": 2}, "2026-11-14")
    assert not R.may_retry({"code": "error", "day": "2026-11-14", "n": 3}, "2026-11-14")


# ── B11 확인한 기준 위에서만 ───────────────────────────────────────────────

def test_push_refuses_when_head_is_not_origin_main(env):
    clone = fresh_clone(env)
    (clone / "posts").mkdir(exist_ok=True)
    (clone / "posts/x.html").write_text("한글", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "local korean edit")
    (clone / "ja").mkdir(exist_ok=True)
    (clone / "ja/x.json").write_text("{}", encoding="utf-8")
    head = remote_head(env)
    with pytest.raises(PB.GitError):
        PB.push(clone, message="ja: x", expect={})
    assert remote_head(env) == head and git(clone, "diff", "--cached", "--name-only") == ""


# ── (d) 클라우드 발행 누락 신호 ────────────────────────────────────────────

def _alerts(env, sessions, last_ok=NOW):
    from scripts.review import publish_watch as W
    st = W.new_state("test")
    st["last_ok"], st["sessions"] = last_ok.isoformat(), dict(sessions)
    tmp = env["tmp"] / "alerts"
    if not tmp.exists():
        git(env["tmp"], "clone", "-q", str(env["bare"]), str(tmp))
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        git(tmp, "checkout", "-q", "--orphan", "alerts-state")
        git(tmp, "rm", "-rqf", ".")
    (tmp / "verify_publish.json").write_text(W.dumps_state(st), encoding="utf-8")
    git(tmp, "add", "-A")
    git(tmp, "commit", "-qm", "state")
    git(tmp, "push", "-qf", "origin", "alerts-state")


def test_missing_cloud_publish_brakes_for_a_day_after_its_deadline(env):
    _alerts(env, {"us:2026-11-13": "missing", "kr:2026-11-12": "missing"})    # us 기한은 11/14 12:00 KST
    rep, _ = run(env, ft=no_call, fr=no_call)
    assert rep.brakes == ["한글 발행 누락(us:2026-11-13)"] and rep.pages == {PATH: "deferred"}
    _alerts(env, {"us:2026-11-13": "resolved"})
    rep2, _ = run(env, ft=no_call, fr=no_call, now=NOW + timedelta(hours=5))
    assert rep2.brakes == ["한글 발행 누락(us:2026-11-13)"]                    # 풀려도 기한 + 24시간까지
    rep3, _ = run(env, ft=no_call, fr=no_call, now=datetime(2026, 11, 15, 0, 5, tzinfo=KST))
    assert rep3.brakes == ["한글 발행 누락(us:2026-11-13)"]                    # 자정을 넘겨도 걸려 있다
    rep4, _ = run(env, now=datetime(2026, 11, 15, 12, 5, tzinfo=KST))
    assert rep4.brakes == [] and rep4.pages == {PATH: "published"}


def test_kr_miss_at_night_still_holds_past_midnight(env):
    _alerts(env, {"kr:2026-11-13": "missing"})                                # kr 기한은 11/13 23:00 KST
    rep, _ = run(env, ft=no_call, fr=no_call, now=datetime(2026, 11, 14, 0, 30, tzinfo=KST))
    assert rep.brakes == ["한글 발행 누락(kr:2026-11-13)"]


def test_missing_signal_on_shallow_clone(env):
    for i in range(3):
        commit(env["work"], {"noise.txt": str(i)})
    _alerts(env, {"us:2026-11-13": "missing"})
    clone = fresh_clone(env, depth=2)
    rep, _ = run(env, ft=no_call, fr=no_call, clone=clone)
    assert rep.brakes == ["한글 발행 누락(us:2026-11-13)"]
    assert git(clone, "rev-list", "--count", "HEAD") == "2"                  # main 의 깊이는 그대로


def test_old_missing_session_does_not_brake(env):
    _alerts(env, {"kr:2026-11-10": "missing", "us:2026-11-11": "missing_quiet"})
    rep, _ = run(env)
    assert rep.brakes == [] and rep.pages == {PATH: "published"}


@pytest.mark.parametrize("setup,why", [(None, "가져오지 못함"), ("stale", "낡음")])
def test_unreadable_signal_does_not_brake_but_is_reported(env, setup, why):
    if setup == "stale":
        _alerts(env, {"us:2026-11-13": "missing"}, last_ok=NOW - timedelta(hours=10))
    rep, _ = run(env)
    assert rep.brakes == [] and rep.pages == {PATH: "published"}
    assert rep.signals == [f"클라우드 발행 누락 신호를 못 읽음({why})"]
    last = json.loads((env["cache"] / "last.json").read_text(encoding="utf-8"))
    assert f"일본어판: 클라우드 발행 누락 신호를 못 읽음({why})" in R.summary({}, NOW, last)


# ── codex 부하 ② 하루 검토 상한 ────────────────────────────────────────────

def test_daily_review_cap(env):
    second_page(env)
    rep, _ = run(env, c=cfg(max_review_calls_per_day=1))
    assert rep.pages == {PATH: "published", P2: "deferred"} and "하루 검토 상한(1/1)" in rep.brakes
    rep2, _ = run(env, ft=no_call, fr=no_call, c=cfg(max_review_calls_per_day=1), now=NOW + timedelta(hours=2))
    assert "하루 검토 상한(1/1)" in rep2.brakes
    rep3, _ = run(env, c=cfg(max_review_calls_per_day=1), now=NOW + timedelta(days=1))
    assert rep3.pages == {P2: "published"}


def test_review_cap_config_key():
    assert R.parse_config({"enabled": True, "max_review_calls_per_day": 5}).max_review_calls_per_day == 5
    assert R.Cfg().max_review_calls_per_day == 16
    assert R.parse_config({"enabled": True, "max_review_calls_per_day": "5"}).enabled is False
