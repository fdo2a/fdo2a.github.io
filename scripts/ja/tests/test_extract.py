"""extract — 뼈대와 번역 단위. 무손실·전수 덮기·비겹침을 실물 전부로 잰다."""
import re

import pytest

from scripts.ja import extract as X
from scripts.ja.tests.corpus import read, target_paths

HANGUL = re.compile(r"[가-힣]")
PH = re.compile(r"⟦/?[a-z]+/?⟧")


def dummy(unit):
    """한글 없는 더미 번역 — 자리표시는 그대로 둔다."""
    return "X" + "".join(PH.findall(unit.ko)) if unit.kind == "text" else "X"


def outside_raw(html):
    """script·style·주석을 뺀 나머지(ld+json 은 남긴다 — 단위가 덮어야 한다)."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<script(?![^>]*ld\+json)[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    return re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)


# ── 작은 사례 ──────────────────────────────────────────────────────────────

def units(html):
    return X.split(html).units


def test_paragraph_with_inline_tags_is_one_unit_with_placeholders():
    html = '<p>엔비디아가 <b>4.34%</b> 내렸고 <a href="x">S&amp;P 500</a>은 버텼다.</p>'
    (u,) = units(html)
    assert u.kind == "text"
    assert u.ko == "엔비디아가 ⟦a⟧4.34%⟦/a⟧ 내렸고 ⟦b⟧S&P 500⟦/b⟧은 버텼다."
    assert u.ph["⟦a⟧"] == "<b>" and u.ph["⟦/b⟧"] == "</a>"
    assert u.block == "p"


def test_join_without_texts_is_identity_and_with_texts_escapes():
    html = '<p>엔비디아가 <b>4.34%</b> 내렸고 <a href="x">S&amp;P 500</a>은 버텼다.</p>'
    doc = X.split(html)
    assert X.join(doc) == html
    out = X.join(doc, {0: "エヌビディアは⟦a⟧4.34%⟦/a⟧下落、⟦b⟧S&P 500⟦/b⟧ <堅調>"})
    assert out == '<p>エヌビディアは<b>4.34%</b>下落、<a href="x">S&amp;P 500</a> &lt;堅調&gt;</p>'


def test_join_accepts_list_aligned_with_units():
    doc = X.split("<p>하나</p><p>둘</p>")
    assert X.join(doc, ["一", "二"]) == "<p>一</p><p>二</p>"


def test_block_children_split_runs():
    html = ('<details data-provenance><summary>계산 근거</summary>입력: 일간 종가</details>'
            '<div class="topbar"><span class="brand">US Market Brief</span> · 2026년 11월 12일(목) 마감 기준</div>'
            '<nav class="crumbs" aria-label="현재 위치"><a href="../index.html">미국 시장</a>'
            '<span class="crumbs-sep" aria-hidden="true">›</span><a href="../index.html?span=daily">일간</a></nav>')
    got = [(u.kind, u.ko) for u in units(html)]
    assert got == [
        ("text", "계산 근거"),
        ("text", "입력: 일간 종가"),
        ("text", "⟦a⟧US Market Brief⟦/a⟧ · 2026년 11월 12일(목) 마감 기준"),
        ("attr", "현재 위치"),
        ("text", "⟦a⟧미국 시장⟦/a⟧⟦b⟧›⟦/b⟧⟦c⟧일간⟦/c⟧"),
    ]


def test_edge_whitespace_and_unpaired_edge_tags_stay_in_skeleton():
    html = "<li>\n  </span>  한글 문장  <br>\n</li>"
    (u,) = units(html)
    assert u.ko == "한글 문장"
    assert html[u.start:u.end] == "한글 문장"


def test_void_and_unpaired_middle_tags_become_atomic():
    (u,) = units("<p>윗줄<br>아랫줄</span>끝</p>")
    assert u.ko == "윗줄⟦a/⟧아랫줄⟦b/⟧끝"


def test_code_is_opaque():
    (u,) = units("<p>함수 <code>a<b>1</b></code> 를 쓴다</p>")
    assert u.ko == "함수 ⟦a/⟧ 를 쓴다"
    assert u.ph["⟦a/⟧"] == "<code>a<b>1</b></code>"


def test_letters_past_26_go_aa():
    assert X.letter(0) == "a" and X.letter(25) == "z" and X.letter(26) == "aa" and X.letter(27) == "ab"


def test_tl_s_is_inline():
    (u,) = units("<h1><tl-s>엔비디아 CEO 사임…</tl-s><tl-s>반도체</tl-s></h1>")
    assert u.ko == "⟦a⟧엔비디아 CEO 사임…⟦/a⟧⟦b⟧반도체⟦/b⟧"
    assert u.block == "h1"


def test_runs_without_hangul_are_not_units():
    assert units("<p>S&amp;P 500 <b>+1.2%</b></p><td>61,248.59</td>") == []


def test_attr_units_and_meta():
    html = ('<head><meta name="description" content="엔비디아 &amp; AMD">'
            '<meta property="og:title" content="제목"><meta name="viewport" content="width=device-width">'
            '<title>미국 증시 | 2026-11-12</title></head>'
            '<td data-label="지수">닛케이225</td><img src="a.png" alt="수익률 &quot;커브&quot;">')
    got = [(u.kind, u.attr, u.ko) for u in units(html)]
    assert got == [
        ("attr", "content", "엔비디아 & AMD"),
        ("attr", "content", "제목"),
        ("text", None, "미국 증시 | 2026-11-12"),
        ("attr", "data-label", "지수"),
        ("text", None, "닛케이225"),
        ("attr", "alt", '수익률 "커브"'),
    ]
    doc = X.split(html)
    out = X.join(doc, {0: "NVIDIA & AMD", 5: '利回り"カーブ"'})
    assert 'content="NVIDIA &amp; AMD"' in out
    assert 'alt="利回り&quot;カーブ&quot;"' in out


def test_inline_tag_with_hangul_attr_breaks_the_run():
    html = '<p>앞 문장 <img alt="그림" src="x.png"> 뒷 문장</p>'
    got = [(u.kind, u.ko) for u in units(html)]
    assert got == [("text", "앞 문장"), ("attr", "그림"), ("text", "뒷 문장")]


def test_script_style_comment_are_not_units():
    html = "<style>/* 한글 주석 */</style><script>var a='한글';</script><!-- 한글 --><p>본문</p>"
    assert [u.ko for u in units(html)] == ["본문"]


def test_jsonld_units_and_rewrite():
    html = ('<script type="application/ld+json">\n{"headline": "미국 증시", "n": 3, '
            '"author": {"name": "US Market Brief"}, "about": [{"name": "엔비디아 \\"CEO\\""}], '
            '"inLanguage": "ko"}\n</script>')
    us = units(html)
    assert [(u.kind, u.path, u.ko) for u in us] == [
        ("jsonld", ("headline",), "미국 증시"),
        ("jsonld", ("about", 0, "name"), '엔비디아 "CEO"'),
    ]
    doc = X.split(html)
    assert X.join(doc) == html
    out = X.join(doc, {0: "米国株 </script>", 1: "エヌビディア"})
    assert '"headline": "米国株 <\\/script>"' in out
    assert '"name": "エヌビディア"' in out and '"n": 3' in out


def test_json_strings_positions():
    text = '{"a": "x", "b": [1, "y\\u00e9"], "c": {"d": true}}'
    got = X.json_strings(text)
    assert [(p, text[s:e], v) for p, s, e, v in got] == [
        (("a",), '"x"', "x"), (("b", 1), '"y\\u00e9"', "yé")]


def test_section_context():
    html = '<section id="read-1"><h2>전략 코멘트</h2><div class="card"><p>본문</p></div></section>'
    us = units(html)
    assert [(u.section, u.block) for u in us] == [("read-1", "h2"), ("read-1", "p")]


def test_unknown_placeholder_in_translation_raises():
    doc = X.split("<p>한글 <b>굵게</b></p>")
    with pytest.raises(ValueError):
        X.join(doc, {0: "日本語 ⟦z⟧太字⟦/z⟧"})


def test_crlf_survives():
    html = "<p>한 줄\r\n다음 줄</p>\r\n"
    doc = X.split(html)
    assert X.join(doc) == html and doc.units[0].ko == "한 줄\r\n다음 줄"


# ── 실물 오라클 ────────────────────────────────────────────────────────────

PATHS = target_paths()


def test_corpus_covers_all_five_paths():
    for d in ("posts/", "news/", "weekly/", "japan/daily/", "japan/posts/"):
        assert any(p.startswith(d) for p in PATHS), d


@pytest.mark.parametrize("path", PATHS)
def test_oracle(path):
    html = read(path)
    doc = X.split(html)
    # ① 무손실
    assert X.join(doc).encode("utf-8") == html.encode("utf-8")
    # ③ 겹치지 않는다(원본 범위 순서대로)
    spans = sorted((u.start, u.end) for u in doc.units)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2, (path, s1, e1, s2, e2, html[s1:e2][:200])
    # ② 더미로 바꾸면 script·style·주석 밖에 한글이 없다
    out = X.join(doc, {u.uid: dummy(u) for u in doc.units})
    rest = outside_raw(out)
    left = [m.start() for m in HANGUL.finditer(rest)]
    assert not left, (path, [rest[max(0, i - 60):i + 30] for i in left[:3]])


def test_unquoted_attr_translation_is_always_quoted():
    # A7 재현: `<p title=한글>` 에 공백 든 번역 → 따옴표 없이 쓰면 뒤가 다른 속성이 된다
    html = "<p title=한글>한글</p>"
    doc = X.split(html)
    attr = next(u for u in doc.units if u.kind == "attr")
    out = X.join(doc, {attr.uid: '日本 語"x"', next(u for u in doc.units if u.kind == "text").uid: "日本語"})
    assert out == '<p title="日本 語&quot;x&quot;">日本語</p>'
    assert X.join(doc) == html                                  # 번역이 없으면 원본 그대로
