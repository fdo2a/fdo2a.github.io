"""state — 번역 기억(사이드카)과 원장. 파일 형식만(git 은 2차)."""
import json

from scripts.ja import extract as X
from scripts.ja import glossary as G
from scripts.ja import state as S

HTML = ('<nav aria-label="현재 위치"><a>미국 시장</a></nav>'
        '<p>첫 문장이다.</p><p>둘째 문장이다.</p><p>셋째 문장이다.</p><p>넷째 문장이다.</p>'
        '<table><tr><th>지수</th></tr><tr><td data-label="종목">엔비디아</td></tr><tr><td data-label="종목">엔비디아</td></tr></table>')


def test_key_is_nfc_plus_glossary_version():
    import hashlib
    import unicodedata
    ko = "첫 문장이다."
    want = hashlib.sha256((unicodedata.normalize("NFC", ko) + "\0" + G.VERSION).encode()).hexdigest()[:16]
    assert S.key(ko) == want
    nfd = unicodedata.normalize("NFD", ko)
    assert S.key(nfd) == S.key(ko)


def test_plan_fixed_reuse_todo_recheck():
    doc = X.split(HTML)
    kos = [u.ko for u in doc.units]
    assert kos == ["현재 위치", "⟦a⟧미국 시장⟦/a⟧", "첫 문장이다.", "둘째 문장이다.", "셋째 문장이다.",
                   "넷째 문장이다.", "지수", "종목", "엔비디아", "종목", "엔비디아"]
    side = S.new_sidecar()
    for ko, ja in [("첫 문장이다.", "一文目だ。"), ("셋째 문장이다.", "三文目だ。"), ("넷째 문장이다.", "四文目だ。")]:
        side["units"][S.key(ko)] = {"ko": ko, "ja": ja, "status": "reviewed"}
    p = S.plan(doc, side)
    assert set(p.fixed) == {0, 1, 6, 7, 9}
    assert set(p.reused) == {2, 4, 5}
    assert [u.ko for u in p.todo] == ["둘째 문장이다.", "엔비디아"]       # 키로 중복 제거
    assert sorted(p.uids_of(p.todo[1])) == [8, 10]
    # 이웃(앞뒤 text 단위)이 todo 인 재사용 단위 → 검토 범위
    assert sorted(u.uid for u in p.recheck) == [2, 4]
    texts = p.texts({S.key("둘째 문장이다."): "二文目だ。", S.key("엔비디아"): "エヌビディア"})
    assert texts[3] == "二文目だ。" and texts[8] == texts[10] == "エヌビディア"
    assert p.complete(texts)
    assert not p.complete(p.texts())


def test_record_updates_sidecar_units():
    doc = X.split(HTML)
    p = S.plan(doc, None)
    side = S.record(None, p, {S.key("둘째 문장이다."): "二文目だ。"}, status="translated",
                    source_blob="abc", renderer="r1", deps={"data/news/x.json": "d1"})
    assert side["source_blob"] == "abc" and side["glossary"] == G.VERSION and side["deps"] == {"data/news/x.json": "d1"}
    assert side["units"][S.key("둘째 문장이다.")] == {"ko": "둘째 문장이다.", "ja": "二文目だ。", "status": "translated"}
    side2 = S.record(side, p, {S.key("둘째 문장이다."): "二文目だ。"}, status="reviewed")
    assert side2["units"][S.key("둘째 문장이다.")]["status"] == "reviewed"


def test_text_hash_depends_only_on_unit_keys():
    a = X.split("<p>하나</p><p>둘</p>")
    b = X.split('<div class="x"><p>하나</p>\n<p>둘</p></div>')
    c = X.split("<p>하나</p><p>셋</p>")
    assert S.text_hash(a) == S.text_hash(b) != S.text_hash(c)


def test_classify():
    entry = {"source_blob": "s1", "text_hash": "t1", "deps": {"a": "1"}, "renderer": "r1", "status": "published"}
    assert S.classify(None, "s1", {"a": "1"}, "t1", "r1") == "new"
    assert S.classify(entry, "s1", {"a": "1"}, "t1", "r1") == "fresh"
    assert S.classify(entry, "s2", {"a": "1"}, "t1", "r1") == "reassemble"
    assert S.classify(entry, "s1", {"a": "2"}, "t1", "r1") == "reassemble"
    assert S.classify(entry, "s1", {"a": "1"}, "t1", "r2") == "reassemble"
    assert S.classify(entry, "s2", {"a": "1"}, "t2", "r1") == "retranslate"


def test_atomic_io_and_broken_json(tmp_path):
    p = tmp_path / "ja" / "state.json"
    obj, why = S.read_json(p)
    assert obj is None and "없" in why
    S.write_json(p, {"a": "한"})
    assert S.read_json(p) == ({"a": "한"}, None)
    assert not [x for x in p.parent.iterdir() if x.name != "state.json"]   # 임시 파일이 남지 않는다
    p.write_text("{broken", encoding="utf-8")
    obj, why = S.read_json(p)
    assert obj is None and "JSON" in why


def test_ledger_roundtrip(tmp_path):
    led, why = S.load_ledger(tmp_path)
    assert led == {"version": S.LEDGER_VERSION, "pages": {}} and why
    S.set_page(led, "posts/2026-11-12.html", source_blob="s", text_hash="t", status="held",
               reason="news missing", deps={"a": "1"}, renderer="r1", now="2026-11-14T09:00:00+09:00")
    S.save_ledger(tmp_path, led)
    back, why = S.load_ledger(tmp_path)
    assert why is None
    e = back["pages"]["posts/2026-11-12.html"]
    assert e["status"] == "held" and e["rounds"] == 1 and e["updated"] == "2026-11-14T09:00:00+09:00"
    S.set_page(back, "posts/2026-11-12.html", source_blob="s", text_hash="t", status="published", reason="",
               now="2026-11-14T10:00:00+09:00")
    assert back["pages"]["posts/2026-11-12.html"]["rounds"] == 2
    try:
        S.set_page(back, "x.html", source_blob="s", text_hash="t", status="bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("bad status accepted")
    assert json.loads((tmp_path / "ja" / "state.json").read_text())["version"] == S.LEDGER_VERSION


def test_sidecar_paths_and_load(tmp_path):
    assert S.sidecar_path(tmp_path, "japan/daily/2026-11-12.html") == tmp_path / "ja/_tm/japan/daily/2026-11-12.html.json"
    side, why = S.load_sidecar(tmp_path, "posts/x.html")
    assert side == S.new_sidecar() and why
    S.save_sidecar(tmp_path, "posts/x.html", {"units": {}, "source_blob": "b"})
    side, why = S.load_sidecar(tmp_path, "posts/x.html")
    assert side["source_blob"] == "b" and why is None
