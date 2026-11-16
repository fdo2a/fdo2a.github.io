"""lists — 일본어 목록 json. 임시 루트에 한글 목록·원장·사이드카를 놓고 거른다."""
import json

import pytest

from scripts.ja import lists as L
from scripts.ja import state as S
from scripts.ja.tests.corpus import ROOT

POSTS = [
    {"date": "2026-11-13", "title": "미국 증시 마감 시황 — 가", "headline": "헤드 가"},
    {"date": "2026-11-12", "title": "미국 증시 마감 시황 — 나", "headline": "헤드 나"},
    {"date": "2026-11-11", "title": "미국 증시 마감 시황 — 다", "headline": "헤드 다"},
]
WEEKLY_JP = [{"key": "2026-W45", "title": "일본 시장 주간 — 라", "headline": "헤드 라",
              "start_date": "2026-11-02", "end_date": "2026-11-06", "label": "2026년 11월 2일~6일"}]


def _put(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _side(root, path, ko, ja):
    side = S.new_sidecar()
    side["list_src"], side["list"] = ko, ja
    S.save_sidecar(root, path, side)


def _ledger(root, **pages):
    S.save_ledger(root, {"version": 1, "pages": {p: {"status": s} for p, s in pages.items()}})


@pytest.fixture()
def root(tmp_path):
    _put(tmp_path, "posts.json", POSTS)
    _put(tmp_path, "japan/posts.json", WEEKLY_JP)
    return tmp_path


def test_empty_ledger_gives_five_empty_lists(root):
    out = L.build(root)
    assert sorted(out) == ["ja/japan/daily.json", "ja/japan/posts.json", "ja/news.json",
                           "ja/posts.json", "ja/weekly.json"]
    assert out["ja/posts.json"] == "[]" and out["ja/japan/posts.json"] == "[]\n"
    assert all(json.loads(t) == [] for t in out.values())


def test_only_published_and_notice_with_fresh_sidecar(root):
    _ledger(root, **{"posts/2026-11-13.html": "published", "posts/2026-11-12.html": "notice",
                     "posts/2026-11-11.html": "held"})
    for d, k in (("2026-11-13", "가"), ("2026-11-12", "나"), ("2026-11-11", "다")):
        _side(root, f"posts/{d}.html",
              {"title": f"미국 증시 마감 시황 — {k}", "headline": f"헤드 {k}"},
              {"title": f"米国株式市況 — {d}", "headline": f"見出し {d}"})
    rows = json.loads(L.build(root)["ja/posts.json"])
    assert rows == [{"date": "2026-11-13", "title": "米国株式市況 — 2026-11-13", "headline": "見出し 2026-11-13"},
                    {"date": "2026-11-12", "title": "米国株式市況 — 2026-11-12", "headline": "見出し 2026-11-12"}]
    assert list(rows[0]) == ["date", "title", "headline"]          # 한글판 필드 순서


def test_stale_or_missing_sidecar_field_drops_the_item(root):
    _ledger(root, **{"posts/2026-11-13.html": "published", "posts/2026-11-12.html": "published",
                     "posts/2026-11-11.html": "published"})
    _side(root, "posts/2026-11-13.html",                       # 한글 제목이 그 뒤에 바뀌었다
          {"title": "미국 증시 마감 시황 — 옛 제목", "headline": "헤드 가"}, {"title": "古い", "headline": "見出し"})
    _side(root, "posts/2026-11-12.html",                       # 헤드라인 번역이 없다
          {"title": "미국 증시 마감 시황 — 나", "headline": "헤드 나"}, {"title": "題"})
    # 2026-11-11 은 사이드카가 없다
    assert L.build(root)["ja/posts.json"] == "[]"


def test_label_is_translated_and_other_fields_kept(root):
    _ledger(root, **{"japan/posts/2026-W45.html": "published"})
    _side(root, "japan/posts/2026-W45.html",
          {"title": "일본 시장 주간 — 라", "headline": "헤드 라", "label": "2026년 11월 2일~6일"},
          {"title": "日本市場週次", "headline": "見出し", "label": "2026年11月2日〜6日"})
    text = L.build(root)["ja/japan/posts.json"]
    assert text.endswith("]\n")
    assert json.loads(text) == [{"key": "2026-W45", "title": "日本市場週次", "headline": "見出し",
                                 "start_date": "2026-11-02", "end_date": "2026-11-06",
                                 "label": "2026年11月2日〜6日"}]


def test_empty_and_hangul_free_values_need_no_sidecar_entry(root):
    _put(root, "news.json", [{"key": "2026-11-13", "title": "뉴스", "headline": ""}])
    _ledger(root, **{"news/2026-11-13.html": "published"})
    _side(root, "news/2026-11-13.html", {"title": "뉴스"}, {"title": "ニュース"})
    assert json.loads(L.build(root)["ja/news.json"]) == [{"key": "2026-11-13", "title": "ニュース", "headline": ""}]


def test_hangul_left_in_result_raises(root):
    _put(root, "news.json", [{"key": "2026-11-13", "title": "뉴스", "note": "한글 필드"}])
    _ledger(root, **{"news/2026-11-13.html": "published"})
    _side(root, "news/2026-11-13.html", {"title": "뉴스"}, {"title": "ニュース"})
    with pytest.raises(ValueError, match="한글"):
        L.build(root)
    _side(root, "news/2026-11-13.html", {"title": "뉴스"}, {"title": "번역 안 됨"})
    _put(root, "news.json", [{"key": "2026-11-13", "title": "뉴스"}])
    with pytest.raises(ValueError, match="한글"):
        L.build(root)


def test_serialization_matches_the_korean_writers():
    """한글판 다섯 파일이 `dumps(rows, tail)` 로 바이트까지 다시 써진다 — 일본어판도 같은 방식."""
    for rel, _folder, tail in L.LISTS:
        raw = (ROOT / rel).read_text(encoding="utf-8")
        assert L.dumps(json.loads(raw), tail) == raw, rel


def test_page_of_follows_the_index_order():
    assert L.page_of("posts", {"date": "2026-11-13"}) == "posts/2026-11-13.html"
    assert L.page_of("weekly", {"key": "2026-W46", "date": "x"}) == "weekly/2026-W46.html"
    assert L.page_of("news", {"slug": "s", "key": "k"}) == "news/s.html"


def test_repo_files_are_what_build_gives():
    """레포에 남긴 `ja/` 목록 다섯 개가 지금 원장으로 다시 만든 것과 같다."""
    for rel, text in L.build(ROOT).items():
        assert (ROOT / rel).read_text(encoding="utf-8") == text, rel


def test_write_is_idempotent(root):
    assert len(L.write(root)) == 5
    assert L.write(root) == []
