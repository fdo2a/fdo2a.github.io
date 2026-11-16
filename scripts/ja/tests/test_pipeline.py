"""pipeline — 글 하나를 끝까지. 번역·검토는 가짜로 주입한다."""
import json
import re

import pytest

from scripts.ja import gate as GT
from scripts.ja import pipeline as P
from scripts.ja import state as S
from scripts.ja.review import Finding, ReviewFailed
from scripts.ja.review import Out as ROut
from scripts.ja.translate import LimitReached, ModelError
from scripts.ja.translate import Out as TOut

PATH = "japan/daily/2026-11-13.html"
TITLE = "일본 증시 마감 — 닛케이 0.53% 상승"
HEAD = "닛케이평균은 0.53% 올랐다."
HTML = f"""<!DOCTYPE html>
<html lang="ko"><head><title>{TITLE}</title>
<meta name="description" content="{HEAD}">
<link rel="canonical" href="https://fdo2a.github.io/{PATH}">
</head><body data-register="da">
<h1>{TITLE}</h1>
<p>닛케이평균이 <b>61,142.35</b>로 마감해 0.53% 올랐다.</p>
<p>달러/엔은 159.81엔이었다.</p>
<p>가타야마 사쓰키 재무상이 견제했다.</p>
<p data-fund="regime" data-regime="강세">국면은 강세다.</p>
<table><tr><th>지수</th></tr></table>
<div class="news-item" data-news="G1"><p class="news-head">한글 제목<span class="sub">로이터 · 11월 13일</span></p><p data-summary="G1">한글 요약</p></div>
</body></html>
"""
NEWS = {"items": [{"guid": "G1", "title": "為替、急激な動き＝片山財務相", "url": "https://jp.reuters.com/x",
                   "source": "ロイター"}]}


def make_root(tmp_path, html=HTML, news=NEWS, listing=True):
    (tmp_path / "japan/daily").mkdir(parents=True)
    (tmp_path / PATH).write_text(html, encoding="utf-8")
    (tmp_path / "japan/data/news").mkdir(parents=True)
    if news is not None:
        (tmp_path / "japan/data/news/2026-11-13.json").write_text(json.dumps(news, ensure_ascii=False),
                                                                  encoding="utf-8")
    items = [{"date": "2026-11-12", "title": "전날", "headline": "전날 요약"}]
    if listing:
        items.insert(0, {"date": "2026-11-13", "title": TITLE, "headline": HEAD})
    (tmp_path / "japan/daily.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return tmp_path


_FAKE_CUR = {"원": "ウォン", "엔": "円", "달러": "ドル", "유로": "ユーロ", "위안": "元"}


def fake_ja(ko):
    """한글 → 가나(숫자·자리표시·라틴은 그대로, 숫자에 붙은 통화는 일본어 단위로) — 기계 검사를 통과하는 가짜 번역."""
    ko = re.sub(r"(\d)(\s*)(원|엔|달러|유로|위안)", lambda m: m.group(1) + m.group(2) + _FAKE_CUR[m.group(3)], ko)
    return re.sub(r"[가-힣]", "あ", ko)


class FT:
    """가짜 번역기. bad(ko)→ja 로 특정 단위의 답을 바꾼다. names 는 첫 호출에 낸다."""

    def __init__(self, bad=None, names=(), limit_at=None, error_at=None):
        self.calls, self.bad, self.names = [], bad or (lambda ko, n: None), list(names)
        self.limit_at, self.error_at = limit_at, error_at

    def __call__(self, units, *, context, names, model, hints=None):
        n = len(self.calls)
        self.calls.append({"kos": [u.ko for u in units], "model": model, "hints": hints or {},
                           "context": context, "names": names})
        if self.limit_at == n:
            raise LimitReached("You've hit your weekly limit")
        if self.error_at == n:
            raise ModelError("timeout")
        texts = {}
        for u in units:
            alt = self.bad(u.ko, n)
            texts[u.uid] = fake_ja(u.ko) if alt is None else alt
        nm = [x for x in self.names if any(x in u.ko for u in units)]
        return TOut(texts=texts, unverified_names=nm, tokens={"in": 10, "out": 5}, calls=1)


class FR:
    """가짜 검토. find(rows, scope, n) → [Finding]."""

    def __init__(self, find=None, fail_at=None, limit_at=None):
        self.calls, self.find, self.fail_at, self.limit_at = [], find or (lambda r, s, n: []), fail_at, limit_at

    def __call__(self, rows, scope):
        n = len(self.calls)
        self.calls.append({"rows": rows, "scope": list(scope)})
        if self.fail_at == n:
            raise ReviewFailed("reviewed_ids 부족")
        if self.limit_at == n:
            raise LimitReached("ERROR: You've hit your usage limit.")
        return ROut(findings=self.find(rows, scope, n), reviewed=set(scope), calls=1)


def no_call(*a, **k):
    raise AssertionError("모델을 부르면 안 된다")


NAMES_OK = P.Config(review_on_names_hold=True)


def build(root, side=None, ft=None, fr=None, cfg=None):
    return P.build_page(root, PATH, sidecar=side, translate=ft or FT(), review=fr or FR(), cfg=cfg)


def uid_of(res_rows, needle):
    return next(r["id"] for r in res_rows if needle in r["ko"])


# ── 기본 길 ───────────────────────────────────────────────────────────────

def test_ready_path(tmp_path):
    root = make_root(tmp_path)
    ft, fr = FT(), FR()
    r = build(root, ft=ft, fr=fr)
    assert r.status == "ready", (r.reason, r.detail)
    assert not re.search("[가-힣]", GT._LANG_RE.sub("", r.html_ja))
    assert '<html lang="ja">' in r.html_ja
    assert "為替、急激な動き＝片山財務相" in r.html_ja and "한글 요약" not in r.html_ja
    kos = [k for c in ft.calls for k in c["kos"]]
    assert kos.count(TITLE) == 1                       # <title>·h1·목록 제목은 같은 키 — 한 번만
    assert "국면은 강세다." in kos and "강세" not in kos   # data-regime 은 사전, 본문은 모델
    assert 'data-regime="強気"' in r.html_ja
    assert all(v["status"] == "reviewed" for v in r.sidecar["units"].values())
    assert r.sidecar["list_src"] == {"title": TITLE, "headline": HEAD}
    assert r.sidecar["list"] == {"title": fake_ja(TITLE), "headline": fake_ja(HEAD)}
    assert r.sidecar["source_blob"] == P.blob_sha(HTML.encode())
    assert r.calls == {"translate": 1, "review": 1, "adjudicate": 0} and r.tokens == {"in": 10, "out": 5}
    # 검토는 글 전체를 문맥으로, scope 는 새로 번역한 것
    rows = fr.calls[0]["rows"]
    assert [x["id"] for x in rows] == sorted(x["id"] for x in rows)          # 문서 순서, 고정 단위 포함
    assert any(x["ko"] == "지수" and x["ja"] == "指数" for x in rows)
    scope_kos = [next(x["ko"] for x in rows if x["id"] == i) for i in fr.calls[0]["scope"]]
    # 고정 번역도 그 글의 문맥에서 검토받는다(codex 2회차 #1) — 쌍마다 첫 출현 하나, 원제 머리는 빼고
    assert scope_kos.count("지수") == 1 and not any("為替" in k for k in scope_kos)
    assert len(set(scope_kos) - {"지수", "강세"}) == len(r.sidecar["units"])
    assert scope_kos.count(TITLE) == 3                  # 같은 문장의 출현 전부가 범위에(<title>·h1·목록)
    # 이름 참고 자료: 용어집 + 그 글의 일본어 원제
    assert "為替、急激な動き＝片山財務相" in ft.calls[0]["names"]["titles"]


def test_second_run_is_zero_calls_and_skeleton_change_too(tmp_path):
    root = make_root(tmp_path)
    r1 = build(root)
    assert r1.status == "ready"
    r2 = build(root, side=r1.sidecar, ft=no_call, fr=no_call)
    assert r2.status == "ready" and r2.calls == {"translate": 0, "review": 0, "adjudicate": 0}
    assert r2.html_ja == r1.html_ja
    # 조판만 바뀜(속성·공백) → 여전히 0 호출
    (root / PATH).write_text(HTML.replace("<h1>", '<h1 class="t">').replace("</p>\n<p>", "</p>\n\n<p>"),
                             encoding="utf-8")
    r3 = build(root, side=r1.sidecar, ft=no_call, fr=no_call)
    assert r3.status == "ready" and r3.calls == {"translate": 0, "review": 0, "adjudicate": 0}
    assert '<h1 class="t">' in r3.html_ja


def test_one_sentence_changed_translates_only_that_and_rechecks_neighbors(tmp_path):
    root = make_root(tmp_path)
    r1 = build(root)
    (root / PATH).write_text(HTML.replace("159.81엔이었다", "159.82엔이었다"), encoding="utf-8")
    ft, fr = FT(), FR()
    r2 = build(root, side=r1.sidecar, ft=ft, fr=fr)
    assert r2.status == "ready"
    assert [c["kos"] for c in ft.calls] == [["달러/엔은 159.82엔이었다."]]
    rows = fr.calls[0]["rows"]
    scope_kos = {next(x["ko"] for x in rows if x["id"] == i) for i in fr.calls[0]["scope"]}
    assert "달러/엔은 159.82엔이었다." in scope_kos
    assert any("61,142.35" in k for k in scope_kos)       # 앞 이웃(재사용) 재검토


def test_news_missing_is_held_without_calls(tmp_path):
    root = make_root(tmp_path, news={"items": []})
    r = build(root, ft=no_call, fr=no_call)
    assert r.status == "held" and "G1" in r.reason and r.html_ja is None


def test_list_entry_missing_is_noted(tmp_path):
    root = make_root(tmp_path, listing=False)
    r = build(root)
    assert r.status == "ready" and "list_missing" in r.detail
    assert r.sidecar["list_src"] == {} and r.sidecar["list"] == {}


def test_no_review(tmp_path):
    root = make_root(tmp_path)
    r = build(root, fr=no_call, cfg=P.Config(review=False))
    assert r.status == "ready" and r.detail["review_skipped"]
    assert {v["status"] for v in r.sidecar["units"].values()} == {"translated"}
    # 다음에 검토를 켜면 재사용된 translated 단위가 검토 범위에 들어간다
    fr = FR()
    r2 = build(root, side=r.sidecar, ft=no_call, fr=fr)
    assert r2.status == "ready" and len(fr.calls) == 1
    kos = {x["id"]: x["ko"] for x in fr.calls[0]["rows"]}
    assert {kos[i] for i in fr.calls[0]["scope"]} - {"지수", "강세"} == {v["ko"] for v in r.sidecar["units"].values()}
    assert {v["status"] for v in r2.sidecar["units"].values()} == {"reviewed"}


# ── 기계 검사 ─────────────────────────────────────────────────────────────

def test_gate_failure_retried_with_hints_then_ok(tmp_path):
    root = make_root(tmp_path)
    bad = lambda ko, n: "ドル円は159.8円だった。" if "159.81" in ko and n == 0 else None
    ft = FT(bad=bad)
    r = build(root, ft=ft)
    assert r.status == "ready"
    assert ft.calls[1]["kos"] == ["달러/엔은 159.81엔이었다."]
    h = list(ft.calls[1]["hints"].values())[0]
    assert h["prev"] == "ドル円は159.8円だった。" and "number" in h["problem"]


def test_gate_failure_left_is_held_and_not_saved(tmp_path):
    root = make_root(tmp_path)
    bad = lambda ko, n: "달러" if "159.81" in ko else None
    ft = FT(bad=bad)
    r = build(root, ft=ft, fr=no_call)
    assert r.status == "held" and "기계 검사" in r.reason and r.html_ja is None
    assert len(ft.calls) == 3                             # 첫 번역 + 재번역 2회
    kos = {v["ko"] for v in r.sidecar["units"].values()}
    assert "달러/엔은 159.81엔이었다." not in kos
    assert TITLE in kos                                   # 통과한 것은 translated 로 남는다
    assert {v["status"] for v in r.sidecar["units"].values()} == {"translated"}


# ── 인명 ──────────────────────────────────────────────────────────────────

def test_unverified_names_held_but_reviewed_and_name_units_not_saved(tmp_path):
    root = make_root(tmp_path)
    fr = FR()
    r = build(root, ft=FT(names=["가타야마 사쓰키"]), fr=fr)
    assert r.status == "held" and "가타야마 사쓰키" in r.reason
    assert len(fr.calls) == 1                             # 검토는 돈다(지적을 한꺼번에)
    kos = {v["ko"]: v["status"] for v in r.sidecar["units"].values()}
    assert "가타야마 사쓰키 재무상이 견제했다." not in kos
    assert kos[TITLE] == "reviewed"
    assert r.detail["unverified_names"] == ["가타야마 사쓰키"]
    # 사람이 용어집에 더하면(가짜 번역기가 이름을 더 안 낸다) 그 단위만 다시 번역
    ft2 = FT()
    r2 = build(root, side=r.sidecar, ft=ft2, fr=FR())
    assert r2.status == "ready"
    assert [c["kos"] for c in ft2.calls] == [["가타야마 사쓰키 재무상이 견제했다."]]


def test_names_hold_without_review_when_configured(tmp_path):
    root = make_root(tmp_path)
    r = build(root, ft=FT(names=["가타야마 사쓰키"]), fr=no_call, cfg=P.Config(review_on_names_hold=False))
    assert r.status == "held" and "인명" in r.reason


# ── 검토와 고치기 ─────────────────────────────────────────────────────────

def _find_on(needle, kind, rounds):
    def find(rows, scope, n):
        if n not in rounds:
            return []
        uid = next(x["id"] for x in rows if needle in x["ko"] and x["id"] in scope)
        return [Finding(uid, kind, "방향이 반대다", "ドル円は159.81円だった。")]
    return find


def test_fix_loop_one_round(tmp_path):
    root = make_root(tmp_path)
    ft, fr = FT(), FR(find=_find_on("159.81", "誤訳", {0}))
    r = build(root, ft=ft, fr=fr)
    assert r.status == "ready" and r.rounds == 1
    fix = ft.calls[1]
    assert fix["kos"] == ["달러/엔은 159.81엔이었다."] and fix["model"] == "sonnet"
    h = list(fix["hints"].values())[0]
    assert h["suggestion"] == "ドル円は159.81円だった。" and "誤訳" in h["problem"]
    rows = fr.calls[1]["rows"]
    rescope = {next(x["ko"] for x in rows if x["id"] == i) for i in fr.calls[1]["scope"]}
    assert "달러/엔은 159.81엔이었다." in rescope and len(rescope) == 3     # 고친 단위 + 앞뒤 이웃
    assert all(v["status"] == "reviewed" for v in r.sidecar["units"].values())


def test_fix_loop_escalates_to_opus_then_held(tmp_path):
    root = make_root(tmp_path)
    ft, fr = FT(), FR(find=_find_on("159.81", "誤訳", {0, 1, 2}))
    r = build(root, ft=ft, fr=fr)
    assert r.status == "held" and "검토 지적" in r.reason and r.rounds == 2
    assert [c["model"] for c in ft.calls[1:]] == ["sonnet", "opus"]
    assert len(fr.calls) == 3
    assert "달러/엔은 159.81엔이었다." not in {v["ko"] for v in r.sidecar["units"].values()}
    assert r.detail["blocking"][0]["kind"] == "誤訳"


def test_unnatural_twice_stays_on_sonnet(tmp_path):
    root = make_root(tmp_path)
    ft = FT()
    r = build(root, ft=ft, fr=FR(find=_find_on("159.81", "不自然", {0, 1})))
    assert r.status == "ready" and [c["model"] for c in ft.calls[1:]] == ["sonnet", "sonnet"]


def test_preference_is_recorded_not_blocking(tmp_path):
    root = make_root(tmp_path)
    r = build(root, fr=FR(find=_find_on("159.81", "好み", {0})))
    assert r.status == "ready" and r.rounds == 0
    assert r.detail["prefs"][0]["kind"] == "好み"


def test_review_failed_is_held(tmp_path):
    root = make_root(tmp_path)
    r = build(root, fr=FR(fail_at=0))
    assert r.status == "held" and r.reason.startswith("검토 실패")
    assert {v["status"] for v in r.sidecar["units"].values()} == {"translated"}


# ── 한도 ──────────────────────────────────────────────────────────────────

def test_limit_in_review_is_pending_and_resumes_without_retranslation(tmp_path):
    root = make_root(tmp_path)
    r = build(root, fr=FR(limit_at=0))
    assert r.status == "pending" and r.html_ja is None and r.reason.startswith("한도")
    assert r.sidecar["units"] and {v["status"] for v in r.sidecar["units"].values()} == {"translated"}
    assert "list" not in r.sidecar
    fr = FR()
    r2 = build(root, side=r.sidecar, ft=no_call, fr=fr)
    kos = {x["id"]: x["ko"] for x in fr.calls[0]["rows"]}
    assert r2.status == "ready"
    assert {kos[i] for i in fr.calls[0]["scope"]} - {"지수", "강세"} == {v["ko"] for v in r.sidecar["units"].values()}


def test_limit_in_translate_is_pending(tmp_path):
    root = make_root(tmp_path)
    r = build(root, ft=FT(limit_at=0), fr=no_call)
    assert r.status == "pending" and r.html_ja is None and r.sidecar["units"] == {}


def test_limit_during_fix_drops_open_finding_from_memory(tmp_path):
    root = make_root(tmp_path)
    r1 = build(root)
    # 다음 실행: 이웃이 바뀌어 재검토된 옛 단위(reviewed)가 誤訳 → 고치려다 한도
    (root / PATH).write_text(HTML.replace("159.81엔이었다", "159.82엔이었다"), encoding="utf-8")
    ft = FT(limit_at=1)
    r2 = build(root, side=r1.sidecar, ft=ft, fr=FR(find=_find_on("61,142.35", "誤訳", {0})))
    assert r2.status == "pending"
    kos = {v["ko"] for v in r2.sidecar["units"].values()}
    assert not any("61,142.35" in k for k in kos)          # 지적이 열린 옛 기억은 지운다
    assert "달러/엔은 159.82엔이었다." in kos


def test_model_error_is_pending(tmp_path):
    root = make_root(tmp_path)
    r = build(root, ft=FT(error_at=0), fr=no_call)
    assert r.status == "pending" and "모델 오류" in r.reason


def test_sign_flag_in_detail(tmp_path):
    html = HTML.replace("<p>달러/엔은 159.81엔이었다.</p>", "<p>달러/엔은 -0.2% 움직였다.</p>")
    root = make_root(tmp_path, html=html)
    lost = lambda ko, n: "ドル円はあ0.2%あああ。" if "-0.2%" in ko else None
    fr = FR()
    r = build(root, ft=FT(bad=lost), fr=fr)
    row = next(x for x in fr.calls[0]["rows"] if "-0.2%" in x["ko"])
    assert any(f.startswith("sign") for f in row["flags"])
    assert any(any(f.startswith("sign") for f in s["flags"]) for s in r.detail["soft"])


def test_every_review_is_logged(tmp_path):
    root = make_root(tmp_path)
    r = build(root, fr=FR(find=_find_on("159.81", "誤訳", {0})))
    logs = r.detail["reviews"]
    assert len(logs) == 2 and logs[0]["findings"][0]["kind"] == "誤訳" and logs[1]["findings"] == []
    assert logs[1]["scope"] == 3


def test_stop_code_names_why_it_stopped(tmp_path):
    root = make_root(tmp_path)
    assert build(root, fr=FR(fail_at=0)).detail["stop"] == "review_failed"
    assert build(root, ft=FT(limit_at=0), fr=no_call).detail["stop"] == "limit"
    assert build(root, ft=FT(error_at=0), fr=no_call).detail["stop"] == "model"
    assert build(root, ft=FT(names=["가타야마 사쓰키"]), fr=FR(),
                 cfg=P.Config(review_on_names_hold=False)).detail["stop"] == "names"
    assert "stop" not in build(root).detail
    root2 = make_root(tmp_path / "b", news=None)
    assert build(root2, ft=no_call, fr=no_call).detail["stop"] == "news_missing"


def test_text_hash_of_matches_units_and_needs_no_model(tmp_path):
    root = make_root(tmp_path)
    th, why = P.text_hash_of(root, PATH)
    assert why is None and th
    (root / "japan/daily.json").write_text("[]", encoding="utf-8")        # 목록 단위가 빠지면 달라진다
    assert P.text_hash_of(root, PATH)[0] != th
    root2 = make_root(tmp_path / "b", news=None)
    assert P.text_hash_of(root2, PATH) == (None, P.text_hash_of(root2, PATH)[1]) and P.text_hash_of(root2, PATH)[1]


# ── 재검토 이력과 마지막 판정 ─────────────────────────────────────────────

from scripts.ja import review as RV                       # noqa: E402
from scripts.ja.review import AdjOut, Verdict             # noqa: E402

TARGET = "달러/엔은 159.81엔이었다."


class FRA(FR):
    """판정까지 하는 가짜 검토. choose(items) → {uid: (choice, reason)} 또는 예외."""

    def __init__(self, find=None, choose=None, **kw):
        super().__init__(find=find, **kw)
        self.adj_calls = []

        def adjudicate(items):
            self.adj_calls.append(items)
            got = choose(items)
            return AdjOut(verdicts={i: Verdict(i, c, r) for i, (c, r) in got.items()}, calls=1)
        self.adjudicate = adjudicate


def _flip(suggestions):
    """회차마다 TARGET 에 誤訳 — 수정안은 회차별로 바뀐다(검토자가 자기 말을 뒤집는다)."""
    def find(rows, scope, n):
        uid = next((x["id"] for x in rows if x["ko"] == TARGET and x["id"] in scope), None)
        if uid is None or n >= len(suggestions):
            return []
        return [Finding(uid, "誤訳", f"{n}회차 지적", suggestions[n])]
    return find


FLIP = ["ドル円は159.81円の高水準だった。", "ドル円は159.81円の高い伸びだった。", "ドル円は159.81円の高水準だった。"]


def test_flip_flopping_reviewer_adjudicated_A_is_ready(tmp_path):
    root = make_root(tmp_path)
    fr = FRA(find=_flip(FLIP), choose=lambda items: {it["id"]: ("A", "원문과 같다") for it in items})
    r = build(root, fr=fr)
    assert r.status == "ready", r.reason
    assert r.calls["adjudicate"] == 1 and len(fr.calls) == 3          # 판정 뒤 재검토 없음
    item = fr.adj_calls[0][0]
    assert item["ko"] == TARGET and item["b"] == FLIP[2] and item["a"] != FLIP[2]
    assert [h["findings"][0]["suggestion"] for h in item["history"]] == FLIP
    assert item["before"]["ko"].startswith("닛케이평균이") and item["after"]["ko"].startswith("가타야마")
    rec = r.detail["adjudication"][0]
    assert (rec["id"], rec["choice"], rec["reason"], rec["result"]) == (item["id"], "A", "원문과 같다", "A")
    st = {v["ko"]: v["status"] for v in r.sidecar["units"].values()}
    assert st[TARGET] == "reviewed"


def test_adjudicated_B_passing_gate_is_used(tmp_path):
    root = make_root(tmp_path)
    fr = FRA(find=_flip(FLIP), choose=lambda items: {it["id"]: ("B", "B 가 낫다") for it in items})
    r = build(root, fr=fr)
    assert r.status == "ready" and FLIP[2] in r.html_ja
    assert {v["ko"]: v["ja"] for v in r.sidecar["units"].values()}[TARGET] == FLIP[2]


def test_adjudicated_B_failing_number_gate_is_held(tmp_path):
    root = make_root(tmp_path)
    bad = ["ドル円は160円だった。"] * 3
    fr = FRA(find=_flip(bad), choose=lambda items: {it["id"]: ("B", "B") for it in items})
    r = build(root, fr=fr)
    assert r.status == "held" and r.detail["stop"] == "blocking"
    rec = r.detail["adjudication"][0]
    assert rec["result"] == "held" and rec["gate"].startswith("number")
    assert "B 기계 검사" in r.reason
    assert TARGET not in {v["ko"] for v in r.sidecar["units"].values()}


def test_adjudicated_neither_is_held_with_unit_id(tmp_path):
    root = make_root(tmp_path)
    fr = FRA(find=_flip(FLIP), choose=lambda items: {it["id"]: ("neither", "둘 다 틀림") for it in items})
    r = build(root, fr=fr)
    uid = fr.adj_calls[0][0]["id"]
    assert r.status == "held" and f"#{uid}" in r.reason and "neither" in r.reason
    assert r.detail["blocking"][0]["id"] == uid


def test_adjudication_missing_unit_is_review_failed(tmp_path):
    """판정 응답이 단위를 빠뜨림 — 실제 review.adjudicate 의 검증을 가짜 codex 로 거친다."""
    from scripts.ja.tests.test_review import Fake
    root = make_root(tmp_path)
    fr = FR(find=_flip(FLIP))
    fake_codex = Fake(lambda d: {"verdicts": []})
    fr.adjudicate = lambda items: RV.adjudicate(items, run=fake_codex)
    r = build(root, fr=fr)
    assert r.status == "held" and r.detail["stop"] == "review_failed" and "판정하지 않은" in r.reason
    assert TARGET not in {v["ko"] for v in r.sidecar["units"].values()}


def test_adjudication_limit_is_pending(tmp_path):
    root = make_root(tmp_path)

    def choose(items):
        raise LimitReached("ERROR: You've hit your usage limit.")
    r = build(root, fr=FRA(find=_flip(FLIP), choose=choose))
    assert r.status == "pending" and r.detail["stop"] == "limit"


def test_no_adjudication_when_nothing_left(tmp_path):
    root = make_root(tmp_path)
    fr = FRA(find=_find_on("159.81", "誤訳", {0}), choose=lambda items: pytest.fail("판정하면 안 된다"))
    r = build(root, fr=fr)
    assert r.status == "ready" and r.calls["adjudicate"] == 0 and fr.adj_calls == []
    assert "adjudication" not in r.detail


def test_without_adjudicator_held_as_before(tmp_path):
    root = make_root(tmp_path)
    r = build(root, fr=FR(find=_flip(FLIP)))
    assert r.status == "held" and r.detail["adjudication"] == {"skipped": "판정 함수 없음"}


def test_rereview_rows_carry_history(tmp_path):
    root = make_root(tmp_path)
    fr = FR(find=_flip(FLIP[:1]))
    r = build(root, fr=fr)
    assert r.status == "ready"
    first = next(x for x in fr.calls[0]["rows"] if x["ko"] == TARGET)
    assert "history" not in first
    again = next(x for x in fr.calls[1]["rows"] if x["ko"] == TARGET)
    assert again["history"] == [{"ja": first["ja"], "findings": [
        {"kind": "誤訳", "reason": "0회차 지적", "suggestion": FLIP[0]}]}]
    others = [x for x in fr.calls[1]["rows"] if x["ko"] != TARGET]
    assert all("history" not in x for x in others)


def test_real_review_has_adjudicate():
    assert callable(P.real_review().adjudicate)


# ── 1회차 codex 구현 검토 ─────────────────────────────────────────────────

LONG = "가" * 4990                                         # 묶음(BATCH_CHARS) 하나를 거의 채운다


def _two_batch_html():
    return HTML.replace("<p>가타야마 사쓰키 재무상이 견제했다.</p>", f"<p>{LONG}</p>")


def test_partial_translation_survives_limit_in_second_batch(tmp_path):
    # A10/B1 재현: 첫 묶음 성공, 둘째 묶음에서 한도 → 토큰과 통과한 번역이 남는다
    root = make_root(tmp_path, html=_two_batch_html())
    ft = FT(limit_at=1)
    r = build(root, ft=ft, fr=no_call)
    assert len(ft.calls) == 2
    assert r.status == "pending" and r.detail["stop"] == "limit"
    assert r.tokens == {"in": 10, "out": 5} and r.calls["translate"] == 1
    kos = {v["ko"] for v in r.sidecar["units"].values()}
    assert set(ft.calls[0]["kos"]) <= kos and LONG not in kos
    assert {v["status"] for v in r.sidecar["units"].values()} == {"translated"}
    # 다음 번에는 남은 묶음만 번역한다
    ft2 = FT()
    r2 = build(root, side=r.sidecar, ft=ft2, fr=FR())
    assert r2.status == "ready" and [c["kos"] for c in ft2.calls] == [ft.calls[1]["kos"]]


def test_partial_on_exception_object_is_absorbed(tmp_path):
    # 실제 translate 는 한 묶음 안에서도 앞 호출의 결과를 partial 로 싣는다
    root = make_root(tmp_path)

    def ft(units, *, context, names, model, hints=None):
        part = TOut(texts={units[0].uid: fake_ja(units[0].ko)}, tokens={"in": 7, "out": 3}, calls=1)
        raise ModelError("timeout", partial=part)
    r = build(root, ft=ft, fr=no_call)
    assert r.status == "pending" and r.detail["stop"] == "model"
    assert r.tokens == {"in": 7, "out": 3} and r.calls["translate"] == 1 and len(r.sidecar["units"]) == 1


def test_token_cap_stops_before_next_batch(tmp_path):
    root = make_root(tmp_path, html=_two_batch_html())
    ft = FT()
    r = build(root, ft=ft, fr=no_call, cfg=P.Config(token_cap=15))
    assert len(ft.calls) == 1 and r.status == "pending" and r.detail["stop"] == "budget"
    assert r.tokens == {"in": 10, "out": 5} and r.sidecar["units"]
    assert "15" in r.reason and "가" not in r.reason


def test_token_cap_not_reached_is_ready(tmp_path):
    root = make_root(tmp_path)
    assert build(root, cfg=P.Config(token_cap=10_000)).status == "ready"


def test_auth_expired_is_its_own_stop(tmp_path):
    from scripts.ja.translate import AuthExpired
    root = make_root(tmp_path)

    def ft(units, **kw):
        raise AuthExpired("Failed to authenticate · Please run claude auth login")
    r = build(root, ft=ft, fr=no_call)
    assert r.status == "pending" and r.detail["stop"] == "auth" and "authenticate" not in r.reason


def test_direction_flag_reaches_reviewer(tmp_path):
    root = make_root(tmp_path)
    flip = lambda ko, n: "あああは⟦a⟧61,142.35⟦/a⟧であああ0.53%下落した。" if "61,142.35" in ko else None
    fr = FR()
    r = build(root, ft=FT(bad=flip), fr=fr)
    row = next(x for x in fr.calls[0]["rows"] if "61,142.35" in x["ko"])
    assert any(f.startswith("direction") for f in row["flags"])


DUP = "같은 문장이 두 번 나온다."


def test_repeated_sentence_every_occurrence_in_first_review(tmp_path):
    # A2 재현: 같은 문장이 다른 문단에 두 번 → 첫 검토의 범위에 두 출현이 다 든다
    html = HTML.replace("<table>", f"<p>{DUP}</p>\n<h2>다른 문맥</h2>\n<p>{DUP}</p>\n<table>")
    root = make_root(tmp_path, html=html)
    fr = FR()
    r = build(root, fr=fr)
    rows = fr.calls[0]["rows"]
    dup_ids = [x["id"] for x in rows if x["ko"] == DUP]
    assert len(dup_ids) == 2 and set(dup_ids) <= set(fr.calls[0]["scope"])
    assert r.status == "ready"


def test_blocking_on_second_occurrence_blocks_the_key(tmp_path):
    html = HTML.replace("<table>", f"<p>{DUP}</p>\n<h2>다른 문맥</h2>\n<p>{DUP}</p>\n<table>")
    root = make_root(tmp_path, html=html)

    def find(rows, scope, n):
        ids = [x["id"] for x in rows if x["ko"] == DUP and x["id"] in scope]
        return [Finding(ids[-1], "誤訳", "둘째 자리에서는 뜻이 다르다", "")] if len(ids) == 2 and n == 0 else []
    ft = FT()
    r = build(root, ft=ft, fr=FR(find=find))
    assert [c["kos"] for c in ft.calls[1:]] == [[DUP]]                # 키로 고친다


def test_fixed_unit_failing_gate_is_held(tmp_path, monkeypatch):
    # A3 ①: 고정 번역도 기계 검사를 거친다
    from scripts.ja import glossary as G
    monkeypatch.setitem(G.DICT, "지수", "指数1")
    root = make_root(tmp_path)
    r = build(root, fr=no_call)
    assert r.status == "held" and r.detail["stop"] == "gate"
    assert any(v.startswith("number") for v in r.detail["gate_failed"].values())


def test_blocking_finding_on_fixed_unit_holds_with_unit_id(tmp_path):
    # A3 ② 재현: 사전 단위에 온 誤訳 은 무시하지 않는다 — stop=fixed, 사유에 단위 번호
    root = make_root(tmp_path)
    holder = {}

    def find(rows, scope, n):
        uid = next(x["id"] for x in rows if x["ko"] == "지수")
        holder["uid"] = uid
        return ([Finding(uid, "誤訳", "문맥상 다른 뜻", "インデックス")] +
                [Finding(next(x["id"] for x in rows if "159.81" in x["ko"]), "誤訳", "x", "")]) if n == 0 else []
    fr, ft = FR(find=find), FT()
    r = build(root, ft=ft, fr=fr)
    assert r.status == "held" and r.detail["stop"] == "fixed"
    assert len(fr.calls) == 1 and len(ft.calls) == 1           # 어차피 보류 — 고치기 고리를 돌지 않는다
    assert f"#{holder['uid']}" in r.reason and "문맥상" not in r.reason
    assert r.detail["fixed_findings"][0]["id"] == holder["uid"]


def test_preference_on_fixed_unit_is_only_logged(tmp_path):
    root = make_root(tmp_path)

    def find(rows, scope, n):
        uid = next(x["id"] for x in rows if x["ko"] == "지수")
        return [Finding(uid, "好み", "취향", "インデックス")]
    r = build(root, fr=FR(find=find))
    assert r.status == "ready" and r.detail["glossary_findings"][0]["kind"] == "好み"


@pytest.mark.parametrize("variant,stop", [
    ('<div class="news-item" data-news="G1"><p class="news-head">한글 제목<span class="sub">로이터 · 11월 13일</span></p>'
     '<p data-summary="G1">한글 요약</p><p class="correction">정정</p></div>', "news_malformed"),
    ('<div data-news="G1" class="news-item"><p class="news-head">한글 제목<span class="sub">로이터 · 11월 13일</span></p>'
     '<p data-summary="G1">한글 요약</p></div>', "news_malformed"),
])
def test_news_structure_problems_hold(tmp_path, variant, stop):
    html = re.sub(r'<div class="news-item".*?</div>', lambda m: variant, HTML, flags=re.S)
    root = make_root(tmp_path, html=html)
    r = build(root, ft=no_call, fr=no_call)
    assert r.status == "held" and r.detail["stop"] == stop


def test_news_bad_url_holds(tmp_path):
    news = {"items": [dict(NEWS["items"][0], url="javascript:alert(1)")]}
    r = build(make_root(tmp_path, news=news), ft=no_call, fr=no_call)
    assert r.status == "held" and r.detail["stop"] == "news_malformed"


def test_news_unsure_language_holds(tmp_path):
    news = {"items": [dict(NEWS["items"][0], title="東京株式市場大幅下落", url="https://example.com/x")]}
    r = build(make_root(tmp_path, news=news), ft=no_call, fr=no_call)
    assert r.status == "held" and r.detail["stop"] == "news_lang"


def test_rereview_carries_only_fixed_units_and_neighbors(tmp_path):
    # codex 부하 ①: 재검토에 싣는 행은 고친 단위 + 이웃(+ 그 바로 앞뒤 문맥)뿐 — 첫 검토는 글 전체
    root = make_root(tmp_path)
    fr = FR(find=_find_on("159.81", "誤訳", {0}))
    r = build(root, fr=fr)
    assert r.status == "ready"
    first, again = fr.calls[0]["rows"], fr.calls[1]["rows"]
    assert len(again) < len(first)
    ids = [x["id"] for x in again]
    assert set(fr.calls[1]["scope"]) <= set(ids) and ids == sorted(ids)
    assert len(set(ids) - set(fr.calls[1]["scope"])) <= 2        # 범위 바로 앞뒤의 문맥 한 줄씩
    assert sum(x["ko"] == TITLE for x in again) <= 1 < sum(x["ko"] == TITLE for x in first)


def test_live_set_sends_unpublished_links_to_korean(tmp_path):
    html = HTML.replace("<table>", '<p><a href="../../news/2026-11-13.html">같은 날 뉴스</a> · '
                                   '<a href="../../posts/2026-11-13.html">시황</a></p>\n<table>')
    root = make_root(tmp_path, html=html)
    r = P.build_page(root, PATH, sidecar=None, translate=FT(), review=FR(), live={"posts/2026-11-13.html"})
    assert r.status == "ready"
    assert 'href="../../../news/2026-11-13.html"' in r.html_ja          # 안 나간 글 → 한글 원문
    assert 'href="../../posts/2026-11-13.html"' in r.html_ja            # 나간 글 → 일본어판
    r0 = P.build_page(root, PATH, sidecar=None, translate=FT(), review=FR())
    assert 'href="../../news/2026-11-13.html"' in r0.html_ja            # live=None 이면 지금처럼


def test_limit_reason_keeps_reset_time_for_the_runner(tmp_path):
    # 러너(note_own_limit)가 `reason` 의 한도 문구에서 재개 시각을 읽는다 — 짧게 줄이면 5시간 기본값으로 떨어진다
    root = make_root(tmp_path)
    msg = "You've hit your weekly limit · resets Nov 21 at 9am (Asia/Seoul)"

    def ft(units, **kw):
        raise LimitReached(msg)
    r = build(root, ft=ft, fr=no_call)
    assert r.detail["stop"] == "limit" and "resets Nov 21 at 9am" in r.reason
