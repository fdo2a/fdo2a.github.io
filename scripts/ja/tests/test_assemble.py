"""assemble — 일본어 글로 조립. 실물 다섯 경로 대표 글을 더미 일본어로 채워 문서 검사까지."""
import json
import posixpath
import re

import pytest

from scripts.common.analytics import MARKER
from scripts.ja import assemble as A
from scripts.ja import extract as X
from scripts.ja import gate as GT
from scripts.ja import news as N
from scripts.ja import state as S
from scripts.ja.tests.corpus import ROOT, read, target_paths

PH = re.compile(r"⟦/?[a-z]+/?⟧")
REPS = ["posts/2026-11-12.html", "news/2026-11-12.html", "weekly/2026-W46.html",
        "japan/daily/2026-11-12.html", "japan/posts/2026-W44.html",
        "posts/2026-07-29.html", "posts/2026-09-22.html", "weekly/2026-W35.html", "japan/daily/2026-10-27.html"]
SITE = "https://fdo2a.github.io/"


def dummy_texts(doc):
    """모든 단위를 더미 일본어로 — glossary 가 답하는 것은 그 답으로."""
    plan = S.plan(doc, None)
    texts = plan.texts()
    for u in doc.units:
        if u.uid not in texts:
            texts[u.uid] = "ダミー" + "".join(PH.findall(u.ko)) if u.kind == "text" else "ダミー"
    return texts


def built(path):
    html, _ = N.localize(read(path), N.lookup(ROOT, path))
    doc = X.split(html)
    return html, A.build(html, path, dummy_texts(doc), ko_url=SITE + path)


@pytest.mark.parametrize("path", REPS)
def test_build_passes_doc_gate(path):
    src, out = built(path)
    assert GT.check_doc(out, src) == []
    assert out.count(MARKER) == (1 if MARKER in src else 0)


@pytest.mark.parametrize("path", REPS)
def test_head_values(path):
    src, out = built(path)
    ja_url = SITE + "ja/" + path
    assert re.search(r'<html\b[^>]*lang="ja"', out)
    assert f'<link rel="canonical" href="{ja_url}">' in out
    assert f'<link rel="alternate" hreflang="ko" href="{SITE + path}">' in out
    assert f'<link rel="alternate" hreflang="ja" href="{ja_url}">' in out
    if 'property="og:url"' in src:
        assert f'<meta property="og:url" content="{ja_url}">' in out
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', out, re.S)
    if m:
        ld = json.loads(m.group(1))
        assert ld.get("inLanguage", "ja") == "ja"
        main = ld.get("mainEntityOfPage")
        if main is not None:
            assert (main.get("@id") if isinstance(main, dict) else main) == ja_url
        if "url" in ld:
            assert ld["url"] == ja_url
        if isinstance(ld.get("publisher"), dict) and "url" in ld["publisher"]:
            assert ld["publisher"]["url"] == SITE             # 사이트 주소는 그대로
    if 'data-register="da"' in src:
        assert 'data-register="ja"' in out and 'data-register="da"' not in out
    # 일본어 글자 설정은 head 끝 한 덩어리, 원본 keep-all 은 지우지 않는다
    assert out.count('<style id="ja-typography">') == 1
    assert out.index('<style id="ja-typography">') < out.index("</head>")
    assert ("keep-all" in src) == ("keep-all" in out)
    assert GT.lang_button(SITE + path) in out


def _virtual_ja_tree():
    pages = {f"ja/{p}" for p in target_paths()}
    extra = {"ja/index.html", "ja/posts.json", "ja/news.json", "ja/weekly.json", "ja/japan/index.html"}
    curves = {f"ja/assets/{p.name}" for p in (ROOT / "assets").glob("yield_curve_*.png")}
    return pages | extra | curves


LINK = re.compile(r'\s(href|src|data-index|data-news-index)="([^"]*)"')


def _rel_targets(html, base_dir):
    for m in LINK.finditer(html):
        v = m.group(2)
        if not v or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|#|//|/", v):
            continue
        v = v.split("#")[0].split("?")[0]
        yield m.group(1), m.group(2), posixpath.normpath(posixpath.join(base_dir, v))


@pytest.mark.parametrize("path", REPS)
def test_relative_links_resolve(path):
    src, out = built(path)
    tree = _virtual_ja_tree()
    broken_before = {raw for _a, raw, t in _rel_targets(src, posixpath.dirname(path)) if not (ROOT / t).exists()}
    bad = []
    for attr, raw, target in _rel_targets(out, posixpath.join("ja", posixpath.dirname(path))):
        if raw in broken_before:
            continue
        if target in tree or (not target.startswith("ja/") and (ROOT / target).exists()):
            continue
        bad.append((attr, raw, target))
    assert not bad


def test_rewrite_url_rules():
    rw = A.rewrite_relative
    assert rw("../index.html", "posts/2026-11-12.html") == "../index.html"
    assert rw("../posts.json", "posts/2026-11-12.html") == "../posts.json"
    assert rw("../assets/yield_curve_2026-11-12.png", "posts/2026-11-12.html") == "../assets/yield_curve_2026-11-12.png"
    assert rw("../assets/logo.svg", "posts/2026-11-12.html") == "../../assets/logo.svg"
    assert rw("../kr/posts/2026-11-12.html", "posts/2026-11-12.html") == "../../kr/posts/2026-11-12.html"
    assert rw("../../about.html#x", "japan/daily/2026-11-12.html") == "../../../about.html#x"
    assert rw("../thesis/mu.html?q=1", "news/2026-11-12.html") == "../../thesis/mu.html?q=1"
    assert rw("https://example.com/a", "posts/x.html") == "https://example.com/a"
    assert rw("#read-1", "posts/x.html") == "#read-1"


def test_og_locale_becomes_ja_jp():
    path = "posts/2026-08-03.html"
    src, out = built(path)
    assert '<meta property="og:locale" content="ko_KR">' in src
    assert '<meta property="og:locale" content="ja_JP">' in out and "ko_KR" not in out


def test_hangul_comments_dropped_marker_comments_kept():
    src = ('<!DOCTYPE html>\n<html lang="ko">\n<head><style>/* 한글 주석 */ body{word-break:keep-all}</style>'
           '<!-- post-shell-v1 --></head><body><!-- 한글 주석 --><p>본문</p></body></html>')
    doc = X.split(src)
    out = A.build(src, "posts/2026-01-01.html", {0: "本文"}, ko_url=SITE + "posts/2026-01-01.html")
    assert "<!-- post-shell-v1 -->" in out and "한글" not in out and "keep-all" in out
    assert GT.check_doc(out, src) == []
    assert len(doc.units) == 1


def test_fragment_without_html_tag_is_flagged():
    path = "posts/2026-07-10.html"
    src = read(path)
    assert "<html" not in src
    doc = X.split(src)
    out = A.build(src, path, dummy_texts(doc), ko_url=SITE + path)
    assert "lang" in {p.code for p in GT.check_doc(out, src)}


def test_notice_idempotent_and_removable():
    src, out = built("posts/2026-11-12.html")
    once = A.with_notice(out, SITE + "posts/2026-11-12.html")
    assert A.NOTICE_TEXT in once
    assert A.with_notice(once, SITE + "posts/2026-11-12.html") == once
    assert once.index(A.NOTICE_TEXT) < once.index('<div class="topbar">')
    assert A.without_notice(once) == out
    assert GT.check_doc(once, src) == []


FRAGMENTS = {"posts/2026-07-10.html", "posts/2026-07-13.html", "posts/2026-07-15.html"}


def test_whole_corpus_builds_clean_except_fragments():
    """대상 글 전부: 더미로 채운 조립본이 문서 검사를 통과한다. `<html>` 이 없는 7월 조각 3편만
    lang 으로 막힌다(2차가 보류한다)."""
    flagged = {}
    for path in target_paths():
        src, out = built(path)
        codes = sorted({p.code for p in GT.check_doc(out, src)})
        if codes:
            flagged[path] = codes
    assert flagged == {p: ["lang"] for p in FRAGMENTS}


def test_directory_itself_is_out_of_ja():
    # A9 재현: `../kr/` 은 정규화하면 `kr` — 접두사 `kr/` 만 보면 `ja/kr/` 로 간다
    rw = A.rewrite_relative
    assert rw("../kr/", "posts/2026-11-13.html") == "../../kr/"
    assert rw("../thesis/", "news/2026-11-13.html") == "../../thesis/"
    assert rw("../../kr/", "japan/daily/2026-11-13.html") == "../../../kr/"
    assert rw("../kr", "posts/2026-11-13.html") == "../../kr"
    assert rw("../", "posts/2026-11-13.html") == "../"                 # 일본어판 첫 화면은 있다


def test_live_links_to_unpublished_articles_go_korean():
    rw = A.rewrite_relative
    live = {"posts/2026-11-13.html"}
    assert rw("../posts/2026-11-13.html", "news/2026-11-13.html", live) == "../posts/2026-11-13.html"
    assert rw("../news/2026-11-12.html#a", "news/2026-11-13.html", live) == "../../news/2026-11-12.html#a"
    assert rw("../news/2026-11-12.html", "news/2026-11-13.html", None) == "../news/2026-11-12.html"
    assert rw("../posts.json", "news/2026-11-13.html", set()) == "../posts.json"            # 목록 json 그대로
    assert rw("../index.html", "news/2026-11-13.html", set()) == "../index.html"            # 목록 페이지 그대로
    assert rw("2026-11-13.html", "news/2026-11-13.html", set()) == "2026-11-13.html"        # 자기 자신
    assert rw("../news/x.html", "news/2026-11-13.html", set(), "data-index") == "../news/x.html"


def test_link_targets():
    html = ('<a href="../posts/2026-11-13.html">a</a><a href="2026-11-13.html">self</a>'
            '<a href="../posts.json">l</a><a href="../kr/posts/2026-11-13.html">kr</a>'
            '<a href="../japan/daily/2026-11-12.html?x#y">j</a><a href="../posts/2026-11-13.html">dup</a>'
            '<a href="https://fdo2a.github.io/news/2026-11-12.html">abs</a><img src="../news/x.html">')
    assert A.link_targets(html, "news/2026-11-13.html") == ["posts/2026-11-13.html", "japan/daily/2026-11-12.html"]


def test_link_targets_in_real_news_page():
    from scripts.ja.tests.corpus import read
    assert "posts/2026-11-13.html" in A.link_targets(read("news/2026-11-13.html"), "news/2026-11-13.html")
