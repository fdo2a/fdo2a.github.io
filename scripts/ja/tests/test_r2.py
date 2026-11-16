"""codex 구현 재검토 2회차 지적의 재현 시험."""
import subprocess

import pytest

from scripts.ja import assemble as A
from scripts.ja import gate
from scripts.ja import pipeline as P
from scripts.ja import review as RV
from scripts.ja import runner as R
from scripts.ja import translate as T
from scripts.ja.review import Finding
from scripts.ja.tests.test_pipeline import FR, FRA, FT, PATH, build, make_root, no_call
from scripts.ja.tests.test_runner import NOW, cfg, env, remote_head, remote_show, run  # noqa: F401


# ── #2 금액 규모·달러 종류 ─────────────────────────────────────────────────

@pytest.mark.parametrize("ko,ja,code", [
    ("매출은 1억 달러다.", "売上は1万ドルだ。", "scale"),          # 규모가 바뀜
    ("매출은 1억 달러다.", "売上は1ドルだ。", "scale"),            # 규모가 빠짐
    ("관객 3만 명", "観客3千人", "scale"),                          # 통화가 없어도
    ("매출 1억 달러, 비용 1만 달러", "売上1万ドル、費用1億ドル", "scale"),   # 같은 숫자의 규모가 맞바뀜(3회차 #2)
    ("5호주달러", "5米ドル", "currency"),                           # 다른 달러
    ("3캐나다달러", "3ドル", "currency"),
])
def test_scale_and_dollar_kind_bad(ko, ja, code):
    assert [p.code for p in gate.check_unit(ko, ja) if not p.soft] == [code]


@pytest.mark.parametrize("ko,ja", [
    ("매출은 1억 달러다.", "売上は1億ドルだ。"),
    ("5호주달러", "5豪ドル"),
    ("미국 달러 5달러", "米ドル5ドル"),
    ("$1억 규모", "1億ドル規模"),                          # 기호 금액은 규모가 뒤에 온다 — 비교하지 않는다
    ("시총 3조 2천억 원", "時価総額3兆2千億ウォン"),
    ("1,500만 달러", "1500万ドル"),
    ("관객 3만 명", "観客3万人"),
    ("닛케이는 6만1077.90엔에 마감", "日経平均は6万1077.90円で引けた"),
    ("매출 1억 달러, 비용 1만 달러", "売上1億ドル、費用1万ドル"),
    ("3년 만기 국채", "3年物国債"),                          # 「만기」의 만은 숫자에 붙지 않았다
])
def test_scale_and_dollar_kind_ok(ko, ja):
    assert [p for p in gate.check_unit(ko, ja) if not p.soft] == []


# ── #5 따옴표 없는 주소 ────────────────────────────────────────────────────

def test_unquoted_url_is_quoted_when_rewritten():
    src = '<html lang="ko"><head></head><body><a href=../assets/a&#32;b.png>x</a></body></html>'
    out = A.build(src, "posts/2026-11-13.html", {}, ko_url="https://x/posts/2026-11-13.html", ja_base="https://x/ja/")
    assert '<a href="../../assets/a b.png">' in out


# ── #1 고정 번역도 첫 검토 범위에 ──────────────────────────────────────────

def test_fixed_only_change_is_still_reviewed_and_held(tmp_path):
    root = make_root(tmp_path)

    def find(rows, scope, n):
        uid = next(r["id"] for r in rows if r["ko"] == "지수")
        assert uid in scope                                  # 고정 단위가 범위에 있어야 지적할 수 있다
        return [Finding(uid, "不自然", "문맥에 안 맞는다", "指標")]
    r = build(root, fr=FR(find=find))
    assert r.status == "held" and r.detail["stop"] == "fixed"


def test_reviewed_page_does_not_review_fixed_again(tmp_path):
    root = make_root(tmp_path)
    r = build(root)
    assert r.status == "ready"
    r2 = build(root, side=r.sidecar, ft=no_call, fr=no_call)   # 바뀐 것이 없으면 검토 호출도 없다
    assert r2.status == "ready"


# ── #3 판정은 지적받은 출현의 문맥으로 ─────────────────────────────────────

def _twice_html():
    from scripts.ja.tests.test_pipeline import HTML
    extra = "<p>닛케이평균은 0.53% 올랐다.</p><p>뒤 문단이다.</p>"
    return HTML.replace("</body>", extra + "</body>")


def test_adjudication_uses_the_flagged_occurrence(tmp_path):
    root = make_root(tmp_path, html=_twice_html())
    sent = "닛케이평균은 0.53% 올랐다."

    def find(rows, scope, n):
        nxt = next(r["id"] for r in rows if r["ko"] == "뒤 문단이다.")
        return [Finding(nxt - 1, "誤訳", "뒤 문맥에서는 다르다", "")]     # 본문의 둘째 출현(첫 출현은 앞쪽)

    seen = {}

    def choose(items):
        seen["items"] = items
        return {it["id"]: ("A", "맞다") for it in items}
    fr = FRA(find=find, choose=choose)
    r = build(root, fr=fr)
    assert fr.adj_calls, r.reason
    # 지적받은 둘째 출현의 이웃이 실린다(3회차부터는 그 키의 모든 출현에 묻는다)
    assert any(it["after"] and it["after"]["ko"] == "뒤 문단이다." for it in seen["items"])


def test_adjudication_needs_every_flagged_occurrence_to_agree(tmp_path):
    root = make_root(tmp_path, html=_twice_html())
    sent = "닛케이평균은 0.53% 올랐다."

    def find(rows, scope, n):
        return [Finding(r["id"], "誤訳", "다르다", "") for r in rows if r["ko"] == sent and r["id"] in
                {x["id"] for x in rows}][:2]

    def choose(items):
        return {it["id"]: (("A", "맞다") if i == 0 else ("neither", "아니다")) for i, it in enumerate(items)}
    r = build(root, fr=FRA(find=find, choose=choose))
    assert r.status == "held" and r.detail["stop"] == "blocking"


# ── #4 자식 프로세스 하나마다 세고, 다음 호출 전에 상한을 본다 ─────────────

def test_claude_call_reports_usage_through_the_hook(monkeypatch):
    seen = []
    monkeypatch.setattr(T, "ON_CALL", lambda *a: seen.append(a))
    monkeypatch.setattr(T, "check_env", lambda env: None)

    def fake_run(args, **kw):
        return subprocess.CompletedProcess(args, 0, stdout='{"subtype": "success", "structured_output": {"items": []},'
                                           ' "usage": {"input_tokens": 7, "output_tokens": 3}}', stderr="")
    T.call("p", {}, {}, "sonnet", run=fake_run)
    assert seen == [("before", "translate", None), ("after", "translate", {"input_tokens": 7, "output_tokens": 3})]


def test_before_hook_can_stop_a_claude_call(monkeypatch):
    def stop(phase, kind, usage):
        raise T.CapReached("budget", "주간 토큰 예산")
    monkeypatch.setattr(T, "ON_CALL", stop)
    monkeypatch.setattr(T, "check_env", lambda env: None)
    with pytest.raises(T.CapReached):
        T.call("p", {}, {}, "sonnet", run=lambda *a, **k: pytest.fail("불렀다"))


def test_codex_call_is_counted_even_when_it_fails(monkeypatch):
    seen = []
    monkeypatch.setattr(T, "ON_CALL", lambda *a: seen.append(a[:2]))

    def fake_run(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")
    with pytest.raises(RV.ReviewFailed):
        RV._call("p", run=fake_run, timeout=5)
    assert seen == [("before", "review"), ("after", "review")]


class ChunkyReview(FR):
    """한 번 불리면 codex 를 n 번 띄우는 검토(실제 `review.review` 가 범위를 조각낼 때처럼)."""

    def __init__(self, n):
        super().__init__()
        self.n, self.children = n, 0

    def __call__(self, rows, scope):
        for _ in range(self.n):
            T.hook("before", "review")
            self.children += 1
            T.hook("after", "review")
        out = super().__call__(rows, scope)
        out.calls = self.n
        return out


def test_review_cap_stops_between_child_calls(env):
    fr = ChunkyReview(3)
    rep, _ = run(env, fr=fr, c=cfg(max_review_calls_per_day=2))
    assert fr.children == 2                                    # 셋째는 띄우지 않았다
    assert R.review_calls(R._loc(env["cache"]), NOW) == 2      # 두 번 세지도, 덜 세지도 않는다
    assert rep.pages == {PATH: "pending"} and "하루 검토 상한(2/2)" in rep.brakes
    rep2, _ = run(env, ft=no_call, c=cfg(max_review_calls_per_day=2), now=NOW.replace(day=NOW.day + 1))
    assert rep2.pages == {PATH: "published"}                   # 다음 날 번역 없이 검토부터 잇는다


class ChunkyTranslate(FT):
    """한 번 불리면 claude 를 두 번 띄우는 번역(형식 오류 재시도처럼). 둘째 앞에서 상한을 본다."""

    def __init__(self):
        super().__init__()
        self.children = 0

    def __call__(self, units, **kw):
        for _ in range(2):
            T.hook("before", "translate")
            self.children += 1
            T.hook("after", "translate", {"input_tokens": 60, "output_tokens": 40})
        out = super().__call__(units, **kw)
        out.tokens = {"in": 120, "out": 80}
        return out


def test_budget_is_checked_before_each_child_call(env):
    ft = ChunkyTranslate()
    rep, _ = run(env, ft=ft, c=cfg(weekly_token_budget=100))
    assert ft.children == 1                                    # 첫 호출로 예산을 다 썼다 — 둘째는 띄우지 않는다
    assert R.budget_used(R._loc(env["cache"]), NOW, cfg(weekly_token_budget=100)) == 100
    assert rep.pages == {PATH: "pending"} and "주간 토큰 예산" in rep.brakes


def test_hooked_tokens_are_not_counted_twice(env):
    ft = ChunkyTranslate()
    rep, _ = run(env, ft=ft)
    assert rep.pages == {PATH: "published"}
    assert R.budget_used(R._loc(env["cache"]), NOW, cfg()) == 200 * ft.children // 2


def test_hook_is_removed_after_the_page(env):
    run(env)
    assert T.ON_CALL is None


# ══ 3회차 ═════════════════════════════════════════════════════════════════

# ── #1 기존 글에서 고정 문구만 바뀌어도 검토받는다 ─────────────────────────

def test_changed_fixed_pair_on_reviewed_page_is_reviewed(tmp_path):
    from scripts.ja.tests.test_pipeline import HTML
    root = make_root(tmp_path)
    r = build(root)
    assert r.status == "ready" and r.sidecar["fixed_ok"]
    assert 'data-regime="강세"' in HTML and "횡보" not in HTML
    (root / PATH).write_text(HTML.replace('data-regime="강세"', 'data-regime="횡보"'), encoding="utf-8")
    fr = FR()
    r2 = build(root, side=r.sidecar, ft=no_call, fr=fr)
    assert r2.status == "ready" and len(fr.calls) == 1
    kos = {x["id"]: x["ko"] for x in fr.calls[0]["rows"]}
    assert [kos[i] for i in fr.calls[0]["scope"]] == ["횡보"]          # 새 쌍 하나만
    r3 = build(root, side=r2.sidecar, ft=no_call, fr=no_call)
    assert r3.status == "ready"


def test_blocked_fixed_pair_is_not_remembered(tmp_path):
    root = make_root(tmp_path)

    def find(rows, scope, n):
        return [Finding(next(r["id"] for r in rows if r["ko"] == "지수"), "誤訳", "x", "指標")]
    r = build(root, fr=FR(find=find))
    assert r.status == "held" and r.detail["stop"] == "fixed"
    fr = FR()
    r2 = build(root, side=r.sidecar, ft=no_call, fr=fr)                 # 다음에도 그 쌍은 다시 검토 범위에
    kos = {x["id"]: x["ko"] for x in fr.calls[0]["rows"]}
    assert "지수" in [kos[i] for i in fr.calls[0]["scope"]]


# ── #3 판정이 고른 수정안은 모든 출현에서 받아들여져야 한다 ────────────────

def _flag_second(rows, scope, n):
    nxt = next(r["id"] for r in rows if r["ko"] == "뒤 문단이다.")
    return [Finding(nxt - 1, "誤訳", "뒤 문맥에서는 다르다", "あああ 0.53% いいい")]


def test_adjudication_asks_every_occurrence(tmp_path):
    root = make_root(tmp_path, html=_twice_html())
    seen = {}

    def choose(items):
        seen["items"] = items
        return {it["id"]: ("B", "B 가 맞다") for it in items}
    r = build(root, fr=FRA(find=_flag_second, choose=choose))
    assert len(seen["items"]) >= 2 and len({it["b"] for it in seen["items"]}) == 1   # 지적 안 받은 출현에도 같은 B
    assert r.status == "ready"


def test_B_rejected_at_an_unflagged_occurrence_is_held(tmp_path):
    root = make_root(tmp_path, html=_twice_html())

    def choose(items):
        return {it["id"]: (("A", "여기서는 A") if i == 0 else ("B", "여기서는 B")) for i, it in enumerate(items)}
    r = build(root, fr=FRA(find=_flag_second, choose=choose))
    assert r.status == "held" and r.detail["stop"] == "blocking"


# ── #4 빠진 단위를 다시 묻다 멈춰도 받은 답은 남는다 ───────────────────────

def test_answers_kept_when_cap_hits_before_asking_for_missing(monkeypatch):
    calls = []

    def fake_one(batch, **kw):
        calls.append([T._uid(u) for u in batch])
        if len(calls) == 2:
            raise T.CapReached("budget", "주간 토큰 예산")
        return [{"id": 1, "ja": "いち"}]                     # 둘 중 하나만 답했다
    monkeypatch.setattr(T, "_one", fake_one)
    with pytest.raises(T.CapReached) as e:
        T.translate([{"id": 1, "ko": "하나"}, {"id": 2, "ko": "둘"}], context=[], names={})
    assert e.value.partial.texts == {1: "いち"}


# ── #5 사용량을 못 받은 호출 ───────────────────────────────────────────────

def test_timeout_and_garbage_report_unknown_usage(monkeypatch):
    seen = []
    monkeypatch.setattr(T, "ON_CALL", lambda *a: seen.append(a))
    monkeypatch.setattr(T, "check_env", lambda env: None)

    def slow(args, **kw):
        raise subprocess.TimeoutExpired(args, 1)
    with pytest.raises(T.ModelError):
        T.call("p", {}, {}, "sonnet", run=slow)
    with pytest.raises(T.ModelError):
        T.call("p", {}, {}, "sonnet", run=lambda a, **k: subprocess.CompletedProcess(a, 1, stdout="garbage", stderr=""))
    assert [s for s in seen if s[0] == "after"] == [("after", "translate", None)] * 2


def test_limit_and_auth_answers_are_not_charged(monkeypatch):
    seen = []
    monkeypatch.setattr(T, "ON_CALL", lambda *a: seen.append(a))
    monkeypatch.setattr(T, "check_env", lambda env: None)
    with pytest.raises(T.AuthExpired):
        T.call("p", {}, {}, "sonnet", run=lambda a, **k: subprocess.CompletedProcess(
            a, 1, stdout="", stderr="Failed to authenticate. Run claude auth login"))
    assert [s for s in seen if s[0] == "after"] == []


class TimeoutTranslate(FT):
    def __call__(self, units, **kw):
        T.hook("before", "translate")
        T.hook("after", "translate", None)
        raise T.ModelError("timeout")


def test_unknown_usage_is_charged_generously(env):
    rep, _ = run(env, ft=TimeoutTranslate())
    assert rep.pages == {PATH: "pending"}
    assert R.budget_used(R._loc(env["cache"]), NOW, cfg()) == sum(R.UNKNOWN_CALL.values())


# ── #6 검토가 조각 중간에 멈춰도 끝낸 조각은 남는다 ────────────────────────

def test_review_partial_rides_on_the_exception(monkeypatch):
    n = {"calls": 0}

    def fake_call(prompt, **kw):
        n["calls"] += 1
        if n["calls"] == 2:
            raise T.CapReached("review_cap", "하루 검토 상한")
        return '{"findings": [], "reviewed_ids": [1]}'
    monkeypatch.setattr(RV, "_call", fake_call)
    monkeypatch.setattr(RV, "chunks", lambda rows, limit=None: [[r] for r in rows])
    rows = [{"id": 1, "ko": "하나다.", "ja": "一つだ。"}, {"id": 2, "ko": "둘이다.", "ja": "二つだ。"}]
    with pytest.raises(T.CapReached) as e:
        RV.review(rows, [1, 2])
    assert e.value.partial.reviewed == {1} and e.value.partial.calls == 1


class HalfReview(FR):
    """범위의 앞 절반만 판정하고 상한에 걸린다."""

    def __call__(self, rows, scope):
        self.calls.append({"rows": rows, "scope": list(scope)})
        if len(self.calls) == 1:
            half = list(scope)[:len(scope) // 2]
            e = T.CapReached("review_cap", "하루 검토 상한")
            e.partial = RV.Out(findings=[], reviewed=set(half), calls=1)
            raise e
        return RV.Out(findings=[], reviewed=set(scope), calls=1)


def test_page_resumes_review_after_the_finished_part(tmp_path):
    root = make_root(tmp_path)
    fr = HalfReview()
    r = build(root, fr=fr)
    assert r.status == "pending" and r.detail["stop"] == "review_cap"
    first = fr.calls[0]["scope"]
    r2 = build(root, side=r.sidecar, ft=no_call, fr=fr)
    assert r2.status == "ready"
    rows = {x["id"]: x["ko"] for x in fr.calls[0]["rows"]}
    done = set(first[:len(first) // 2])
    rest_kos = {rows[i] for i in first if i not in done}
    # 끝낸 절반 가운데, 같은 문장의 다른 출현이 못 끝낸 쪽에 남아 있지 않은 것은 다시 검토하지 않는다
    settled = {i for i in done if rows[i] not in rest_kos}
    assert settled and not (set(fr.calls[1]["scope"]) & settled) and len(fr.calls[1]["scope"]) < len(first)


# ── 본체 점검: 한글 쪽이 그대로면 「갱신됐다」를 붙이지 않는다 ───────────────

def test_new_fixed_pair_blocked_on_live_page_leaves_it_alone(env, monkeypatch):
    """사전 값이 바뀌고 렌더러 판이 오른 뒤, 새 고정 번역이 검토에서 막혔다 — 한글 원문은 그대로다."""
    from scripts.ja import glossary as G
    run(env)
    head, before = remote_head(env), remote_show(env, "ja/" + PATH)
    assert "data-ja-notice" not in before
    monkeypatch.setattr(A, "RENDERER", "r-test")
    monkeypatch.setitem(G.ATTR_VALUES["data-regime"], "강세", "強含み")

    def find(rows, scope, n):
        return [Finding(i, "誤訳", "x", "強気") for i in scope if next(r for r in rows if r["id"] == i)["ko"] == "강세"]
    rep, _ = run(env, ft=no_call, fr=FR(find=find))
    assert rep.pages == {PATH: "held"} and "고정 번역" in rep.reasons[PATH]
    assert remote_head(env) == head and remote_show(env, "ja/" + PATH) == before     # 문구도, 커밋도 없다


def test_new_fixed_pair_deferred_on_live_page_leaves_it_alone(env, monkeypatch):
    from scripts.ja import glossary as G
    run(env)
    head = remote_head(env)
    monkeypatch.setattr(A, "RENDERER", "r-test")
    monkeypatch.setitem(G.ATTR_VALUES["data-regime"], "강세", "強含み")
    rep, _ = run(env, ft=no_call, fr=no_call, c=cfg(windows_kst=((3, 4),)))            # 시각대 밖
    assert rep.pages == {PATH: "deferred"} and remote_head(env) == head
    rep2, _ = run(env, ft=no_call)                                                     # 풀리면 검토만 하고 나간다
    assert rep2.pages == {PATH: "published"} and "強含み" in remote_show(env, "ja/" + PATH)
    assert "data-ja-notice" not in remote_show(env, "ja/" + PATH)


# ══ 4회차 ═════════════════════════════════════════════════════════════════

def test_scale_reads_the_same_number_tokens_as_the_number_check():
    ko, ja = "매출 1.2,3억", "売上1.2,3万"
    assert gate.numbers(ko) == [n for n, _s in gate.scaled_numbers(ko)]
    assert [p.code for p in gate.check_unit(ko, ja) if not p.soft] == ["scale"]
    assert [p for p in gate.check_unit("2,3분기에 3억 늘었다", "2,3四半期に3億増えた") if not p.soft] == []


def test_scale_tokens_match_number_tokens_on_real_pages():
    """규모 검사가 숫자 검사와 다른 숫자를 읽으면 조용히 건너뛴다 — 실제 글의 모든 단위에서 같아야 한다."""
    import glob
    from scripts.ja import extract as X
    for f in sorted(glob.glob("posts/2026-11-1*.html") + glob.glob("news/2026-11-1*.html")):
        for u in X.split(open(f, encoding="utf-8").read()).units:
            assert gate.numbers(u.ko) == [n for n, _s in gate.scaled_numbers(u.ko)], (f, u.ko[:60])


class CutBeforeLast(FR):
    """범위의 마지막 단위를 판정하기 전에 상한에 걸린다(첫 호출만)."""

    def __call__(self, rows, scope):
        self.calls.append({"rows": rows, "scope": list(scope)})
        if len(self.calls) == 1:
            e = T.CapReached("review_cap", "하루 검토 상한")
            e.partial = RV.Out(findings=[], reviewed=set(list(scope)[:-1]), calls=1)
            raise e
        return RV.Out(findings=[], reviewed=set(scope), calls=1)


def test_repeated_sentence_is_not_reviewed_until_every_occurrence_is(tmp_path):
    from scripts.ja.tests.test_pipeline import HEAD
    root = make_root(tmp_path, html=_twice_html())
    fr = CutBeforeLast()
    r = build(root, fr=fr)
    assert r.status == "pending"
    rows = {x["id"]: x["ko"] for x in fr.calls[0]["rows"]}
    last = fr.calls[0]["scope"][-1]
    assert sum(1 for i in fr.calls[0]["scope"] if rows[i] == rows[last]) >= 2     # 마지막 단위는 반복 문장의 한 출현
    r2 = build(root, side=r.sidecar, ft=no_call, fr=fr)
    assert r2.status == "ready" and len(fr.calls) == 2                            # 검토 없이 나가지 않는다
    assert last in fr.calls[1]["scope"]


# ══ 5회차 ═════════════════════════════════════════════════════════════════

def test_reviewed_ids_outside_the_asked_chunk_are_not_trusted(monkeypatch):
    """첫 조각의 답이 다른 조각의 단위까지 판정했다고 하고, 둘째 조각 전에 끊긴다."""
    n = {"calls": 0}

    def fake_call(prompt, **kw):
        n["calls"] += 1
        if n["calls"] == 2:
            raise T.CapReached("review_cap", "하루 검토 상한")
        return '{"findings": [], "reviewed_ids": [1, 2]}'
    monkeypatch.setattr(RV, "_call", fake_call)
    monkeypatch.setattr(RV, "chunks", lambda rows, limit=None: [[r] for r in rows])
    rows = [{"id": 1, "ko": "같은 문장이다.", "ja": "同じ文だ。"}, {"id": 2, "ko": "같은 문장이다.", "ja": "同じ文だ。"}]
    with pytest.raises(T.CapReached) as e:
        RV.review(rows, [1, 2])
    assert e.value.partial.reviewed == {1}


def test_validate_returns_only_asked_ids():
    found, reviewed = RV.validate({"findings": [], "reviewed_ids": [1, 2, 3]}, [1], {1, 2, 3})
    assert reviewed == {1}
