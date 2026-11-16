"""news — 원문이 일본어인 뉴스 항목은 원제·원문 매체명 그대로, 요약은 싣지 않는다."""
import html as H
import re

import pytest

from scripts.ja import news as N
from scripts.ja.tests.corpus import ROOT, read, target_paths

ITEM = re.compile(r'<div class="news-item" data-news="([^"]*)">(.*?)</div>', re.S)


def items(html):
    return {H.unescape(m.group(1)): m.group(2) for m in ITEM.finditer(html)}


@pytest.mark.parametrize("rec,want", [
    ({"title": "午後3時のドルは159円後半", "url": "https://finance.yahoo.co.jp/news/detail/x"}, True),
    ({"title": "日銀総裁会見", "url": "https://www.nikkei.co.jp/a"}, True),          # 가나 없음 + .jp + 한자
    ({"title": "日銀總裁發言", "url": "https://www.example.com/a"}, False),         # .jp 아님, 가나 없음
    ({"title": "Statement on Monetary Policy", "url": "https://www.boj.or.jp/en/mopo/x.pdf"}, False),
    ({"title": "BOJ 総裁 Ueda says rates will rise further this year", "url": "https://x.jp/a"}, False),
    ({"title": "일본 증시", "url": "https://x.jp/a"}, False),
    ({"title": "", "url": "https://x.jp/a"}, False),
    ({"title": "ソニー、決算", "url": "https://www.reuters.com/x"}, True),
])
def test_is_ja_origin(rec, want):
    assert N.is_ja_origin(rec) is want


SAMPLE = ('<div class="news-item" data-news="g1"><p class="news-head">한글 제목<span class="sub">로이터 · 11월 12일</span></p>'
          '<p data-summary="g1">한글 요약</p></div>\n'
          '<div class="news-item" data-news="g2"><p class="news-head">영문 기사 제목<span class="sub">CNBC · 11월 12일</span></p>'
          '<p data-summary="g2">요약</p></div>\n'
          '<div class="news-item" data-news="g3"><p class="news-head">모르는 기사<span class="sub">X · 11월 12일</span></p><p>요약</p></div>')
RECS = {
    "g1": {"guid": "g1", "url": "https://finance.yahoo.co.jp/news/detail/g1?a=1&b=2", "title": "円安&amp;株高 「けん制」", "source": "ロイター"},
    "g2": {"guid": "g2", "url": "https://www.cnbc.com/x", "title": "Stocks fall", "source": "CNBC"},
}


def test_localize_sample():
    out, rep = N.localize(SAMPLE, RECS)
    got = items(out)
    assert got["g1"] == ('<p class="news-head"><a href="https://finance.yahoo.co.jp/news/detail/g1?a=1&amp;b=2" rel="noopener">'
                         '円安&amp;株高 「けん制」</a><span class="sub">ロイター · 11월 12일</span></p>')
    assert got["g2"] == items(SAMPLE)["g2"]          # 일본어 원문이 아니면 손대지 않는다
    assert got["g3"] == items(SAMPLE)["g3"]
    assert rep.localized == ["g1"] and rep.kept == ["g2"] and rep.missing == ["g3"]


def test_localize_removes_every_summary_paragraph_variant():
    html = ('<div class="news-item" data-news="g1"><p class="news-head">제목<span class="sub">로이터 · 11월 4일</span></p>'
            '<p>요약 하나</p><p>요약 둘</p></div>')
    out, _ = N.localize(html, RECS)
    assert "요약" not in out and out.endswith("</span></p></div>")


def test_localize_is_idempotent():
    once, _ = N.localize(SAMPLE, RECS)
    twice, rep = N.localize(once, RECS)
    assert twice == once and rep.localized == ["g1"]


# ── 실물 ──────────────────────────────────────────────────────────────────

def test_lookup_covers_every_news_id_in_the_corpus():
    missing = {}
    for path in target_paths():
        ids = set(items(read(path)))
        if not ids:
            continue
        recs = N.lookup(ROOT, path)
        lost = sorted(i for i in ids if i not in recs)
        if lost:
            missing[path] = lost[:3]
    assert not missing


def test_japan_daily_all_items_localized():
    path = "japan/daily/2026-11-12.html"
    html = read(path)
    recs = N.lookup(ROOT, path)
    out, rep = N.localize(html, recs)
    assert rep.missing == [] and rep.kept == []
    assert len(rep.localized) == len(items(html)) == 8
    assert "data-summary" not in out
    for i, body in items(out).items():
        title = H.unescape(recs[i]["title"])
        assert H.unescape(re.search(r'<a [^>]*>(.*?)</a>', body).group(1)) == title
        assert f'<span class="sub">{H.escape(recs[i]["source"], quote=False)} · ' in body


def test_us_news_global_yahoo_item_localized_rest_kept():
    path = "news/2026-11-12.html"
    html = read(path)
    out, rep = N.localize(html, N.lookup(ROOT, path))
    assert rep.missing == []
    assert any("news.yahoo.co.jp" in i for i in rep.localized)
    assert all("yahoo.co.jp" in i or "nikkei" in i or ".jp" in i for i in rep.localized)
    before, after = items(html), items(out)
    for i in rep.kept:
        assert after[i] == before[i]


def test_boj_english_pdf_is_translated_not_localized():
    path = "japan/posts/2026-W44.html"
    out, rep = N.localize(read(path), N.lookup(ROOT, path))
    boj = [i for i in rep.kept if "boj.or.jp/en/" in i]
    assert boj and not any("boj.or.jp/en/" in i for i in rep.localized)
    assert rep.missing == []


# ── 1회차 codex 구현 검토 ─────────────────────────────────────────────────

@pytest.mark.parametrize("rec,want", [
    ({"title": "東京株式市場大幅下落", "url": "https://example.com/x"}, "unsure"),   # A4 재현: 한자만·.jp 아님
    ({"title": "日銀總裁發言", "url": "https://www.example.com/a"}, "unsure"),
    ({"title": "日銀総裁会見", "url": "https://www.nikkei.co.jp/a"}, "ja"),            # .jp + 한자만은 그대로 일본어
    ({"title": "ソニー、決算", "url": "https://www.reuters.com/x"}, "ja"),
    ({"title": "Stocks fall", "url": "https://www.cnbc.com/x"}, "other"),
    ({"title": "일본 증시", "url": "https://x.jp/a"}, "other"),
])
def test_origin_three_way(rec, want):
    assert N.origin(rec) == want
    assert N.is_ja_origin(rec) is (want == "ja")


def _one(head_and_rest, nid="g1"):
    return f'<div class="news-item" data-news="{nid}">{head_and_rest}</div>'


HEAD = '<p class="news-head">제목<span class="sub">로이터 · 11월 4일</span></p>'


def test_unsure_language_is_reported_and_left_alone():
    recs = {"g1": {"guid": "g1", "title": "東京株式市場大幅下落", "url": "https://example.com/x"}}
    html = _one(HEAD + '<p data-summary="g1">요약</p>')
    out, rep = N.localize(html, recs)
    assert rep.unsure == ["g1"] and out == html


def test_item_with_attributes_in_other_order_is_malformed_not_missed():
    # A5 재현: `<div data-news="id" class="news-item">` — 항목을 못 알아보면 ID 누락 보류도 안 걸린다
    html = '<div data-news="g1" class="news-item">' + HEAD + '<p data-summary="g1">요약</p></div>'
    out, rep = N.localize(html, RECS)
    assert rep.malformed and out == html


def test_non_summary_paragraph_after_head_is_not_deleted():
    # A5 재현: 머리 뒤의 `<p class="correction">` 은 요약이 아니다 — 지우지 않고 보류
    html = _one(HEAD + '<p data-summary="g1">요약</p><p class="correction">정정 안내</p>')
    out, rep = N.localize(html, RECS)
    assert rep.malformed == ["g1"] and "정정 안내" in out and out == html


def test_other_element_after_head_is_malformed():
    html = _one(HEAD + '<p data-summary="g1">요약</p><ul><li>목록</li></ul>')
    out, rep = N.localize(html, RECS)
    assert rep.malformed == ["g1"] and out == html


def test_plain_and_summary_paragraphs_are_removed():
    html = _one(HEAD + '\n<p data-summary="g1">요약</p>\n<p>둘째 요약</p>\n')
    out, rep = N.localize(html, RECS)
    assert rep.localized == ["g1"] and not rep.malformed and "요약" not in out


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "//evil.example/x", "", "ftp://x.jp/a"])
def test_non_http_url_is_malformed(url):
    # A6 재현: 가나 제목 + `javascript:` 주소 → 링크로 넣지 않는다
    recs = {"g1": {"guid": "g1", "title": "円安が進む", "url": url, "source": "ロイター"}}
    out, rep = N.localize(_one(HEAD + '<p data-summary="g1">요약</p>'), recs)
    assert rep.malformed == ["g1"] and "javascript" not in out.replace(url, "") and "<a " not in out


def test_count_of_news_attributes_must_match_items():
    assert N.count_items('<div class="news-item" data-news="a"></div><p data-news="b">x</p>'
                         '<div data-news-index="news.json"></div><script>q("[data-news=x]")</script>') == 2


def test_corpus_has_no_malformed_or_unsure_items():
    # 켜는 순간 영영 멈추는 글이 없는지 — 실물 전부
    bad = {}
    for path in target_paths():
        html = read(path)
        out, rep = N.localize(html, N.lookup(ROOT, path))
        found = rep.localized + rep.kept + rep.missing + rep.malformed + rep.unsure
        if rep.malformed or rep.unsure or N.count_items(html) != len(found):
            bad[path] = (rep.malformed[:2], rep.unsure[:2], N.count_items(html), len(found))
    assert not bad
