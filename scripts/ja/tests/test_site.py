"""site — 일본어 목록 페이지. 지금 한글 원본으로 만들고, 레포에 남긴 결과물과 같은지 본다."""
import json
import re

import pytest

from scripts.common.analytics import MARKER
from scripts.ja import gate as GT
from scripts.ja import site as SI
from scripts.ja import extract as X
from scripts.ja.tests.corpus import ROOT

SITE = "https://fdo2a.github.io/"
JA = {"index.html": "ja/index.html", "japan/index.html": "ja/japan/index.html"}


def src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built():
    return SI.build(ROOT)


def test_repo_files_are_current(built):
    """한글 목록 페이지를 고치면 `python3 -m scripts.ja.site` 로 다시 만들어 함께 커밋한다."""
    for rel, html in built.items():
        assert (ROOT / rel).read_text(encoding="utf-8") == html, rel


@pytest.mark.parametrize("rel", sorted(JA))
def test_doc_gate_and_one_marker(built, rel):
    out = built[JA[rel]]
    assert GT.check_doc(out, src(rel)) == []
    assert out.count(MARKER) == 1
    assert (ROOT / JA[rel]).read_text(encoding="utf-8").count(MARKER) == 1


@pytest.mark.parametrize("rel,url,ko", [("index.html", SITE + "ja/", SITE),
                                        ("japan/index.html", SITE + "ja/japan/", SITE + "japan/")])
def test_head_points_at_the_japanese_edition(built, rel, url, ko):
    out = built[JA[rel]]
    assert re.search(r'<html\b[^>]*lang="ja"', out)
    assert f'<link rel="canonical" href="{url}">' in out
    assert f'<meta property="og:url" content="{url}">' in out
    assert '<meta property="og:locale" content="ja_JP">' in out
    assert f'<link rel="alternate" hreflang="ko" href="{ko}">' in out
    assert f'<link rel="alternate" hreflang="ja" href="{url}">' in out
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', out, re.S).group(1))
    assert ld["url"] == url and ld["inLanguage"] == "ja"


@pytest.mark.parametrize("rel,links", [
    ("index.html", [("./", "米国市場"), ("japan/", "日本市場")]),
    ("japan/index.html", [("../", "米国市場"), ("../japan/", "日本市場")]),
])
def test_menubar_drops_sections_without_an_edition(built, rel, links):
    out = built[JA[rel]]
    nav = re.search(r'<nav class="menubar">.*?</nav>', out, re.S).group(0)
    assert re.findall(r'<a href="([^"]*)"[^>]*>([^<]+)</a>', nav) == links
    assert nav.count(GT.lang_button(SITE + ("japan/" if rel.startswith("japan") else ""))) == 1
    assert not re.search(r'href="(?:\.\./)*(?:kr|thesis)/', out)
    assert "ja-lang-bar\">" not in out                        # assemble 의 막대는 메뉴바로 옮겼다
    assert ">日本語</a>" not in out                            # 한글판의 「日本語」 링크는 뺐다


def test_footer_links_go_to_the_korean_site_pages(built):
    out = built["ja/index.html"]
    assert 'href="../about.html"' in out and 'href="../privacy.html"' in out
    out = built["ja/japan/index.html"]
    assert 'href="../../about.html"' in out and "Bank of Japan Time-Series Data Search" in out


def test_script_strings_are_japanese(built):
    for out in built.values():
        body = re.search(r"<script>(.*?)</script>", out, re.S).group(1)
        assert not X.HANGUL.search(body)
        assert "['日','月','火','水','木','金','土']" in body and "件</span>" in body
    assert "'まだレポートがありません。'" in built["ja/index.html"]


def test_every_table_entry_is_used():
    """표에 죽은 줄이 쌓이지 않게 — 한글 원본이 바뀌어 안 쓰이게 된 줄은 지운다."""
    units = set()
    scripts = ""
    for rel in SI.PAGES:
        pruned = SI.prune(src(rel))
        units |= {u.ko for u in X.split(pruned).units}
        scripts += "".join(re.findall(r"<script>(.*?)</script>", pruned, re.S))
    assert set(SI.STRINGS) - units == set()
    assert {k for k in SI.SCRIPT_STRINGS if k not in scripts} == set()


def test_a_new_korean_unit_raises():
    page = src("index.html").replace('<h2 class="list-title">', '<p>새로 넣은 문장</p>\n  <h2 class="list-title">', 1)
    with pytest.raises(SI.SiteError, match="STRINGS"):
        SI.build_page(page, "index.html")


def test_a_new_korean_script_string_raises():
    page = src("index.html").replace("const cache = {};", "const cache = {}; const note = '새 문구';", 1)
    with pytest.raises(SI.SiteError, match="script"):
        SI.build_page(page, "index.html")


@pytest.mark.parametrize("cut", ['\n    <a href="kr/">한국 시장</a>', '\n    <a href="thesis/">메모리 thesis</a>'])
def test_menubar_shape_change_raises(cut):
    page = src("index.html")
    assert cut in page
    with pytest.raises(SI.SiteError, match="메뉴바"):
        SI.prune(page.replace(cut, "", 1))


def test_a_section_link_outside_the_menubar_raises():
    page = src("index.html").replace("<footer>", '<footer><a href="kr/">한국</a>', 1)
    with pytest.raises(SI.SiteError, match="섹션"):
        SI.prune(page)


def test_url_inside_a_script_string_survives_comment_stripping():
    assert SI._script("const u = 'https://x.example/한';".replace("한", "")) == "const u = 'https://x.example/';"
    assert SI._script("a();  // 한글 주석\nb();") == "a();\nb();"


@pytest.mark.parametrize("rel,href", [("index.html", "ja/"), ("japan/index.html", "../ja/japan/")])
def test_korean_lists_carry_at_most_one_japanese_button(rel, href):
    # 첫 글이 공개되기 전에는 버튼이 없을 수 있다(코드를 먼저 올리는 순서) — 있으면 메뉴바에 하나
    page = src(rel)
    want = f'<a class="lang" href="{href}" hreflang="ja" lang="ja">日本語</a>'
    assert page.count("日本語") == page.count(want) <= 1
    if page.count(want):
        assert want in re.search(r'<nav class="menubar">.*?</nav>', page, re.S).group(0)


BUTTON = {"index.html": '\n    <a class="lang" href="ja/" hreflang="ja" lang="ja">日本語</a>',
          "japan/index.html": '\n    <a class="lang" href="../ja/japan/" hreflang="ja" lang="ja">日本語</a>'}


def _without_button(rel, css=False):
    page = src(rel)
    if BUTTON[rel] in page:
        page = page.replace(BUTTON[rel], "", 1)
    if css:
        page = re.sub(r"\.menubar a\.lang \{[^}]*\}", "", page, count=1)
    return page


@pytest.mark.parametrize("css", [False, True])
@pytest.mark.parametrize("rel", sorted(JA))
def test_builds_without_the_korean_japanese_button(rel, css):
    # B8 재현: 버튼을 빼도(그 CSS 까지 빼도) 일본어 목록 페이지가 만들어진다
    out = SI.build_page(_without_button(rel, css), rel)
    assert GT.check_doc(out, src(rel)) == []
    nav = re.search(r'<nav class="menubar">.*?</nav>', out, re.S).group(0)
    assert nav.count('class="ja-lang"') == 1 and 'lang="ja">日本語</a>' not in out


def test_two_japanese_buttons_still_raise():
    page = src("index.html")
    if BUTTON["index.html"] not in page:
        page = page.replace("</nav>", BUTTON["index.html"] + "\n  </nav>", 1)
    page = page.replace(BUTTON["index.html"], BUTTON["index.html"] * 2, 1)
    with pytest.raises(SI.SiteError, match="메뉴바"):
        SI.prune(page)


# ── 브라우저 실측(390·1280) ────────────────────────────────────────────────
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

DAILY = [{"date": "2026-11-13", "title": "米国株式市況 — テスト", "headline": "見出し"}]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(browser, rel, width, data):
    """`https://fdo2a.github.io/<dir>` 로 연다 — html 은 레포 파일, 목록 json 은 `data`(없으면 레포 파일)."""
    page = browser.new_page(viewport={"width": width, "height": 900})

    def route(r):
        url = r.request.url
        if not url.startswith(SITE):
            return r.abort()
        path = url[len(SITE):].split("?")[0]
        path = path + "index.html" if path == "" or path.endswith("/") else path
        if path in data:
            return r.fulfill(body=json.dumps(data[path]), content_type="application/json")
        f = ROOT / path
        if f.is_file():
            return r.fulfill(body=f.read_bytes(),
                             content_type="application/json" if f.suffix == ".json" else "text/html; charset=utf-8")
        return r.fulfill(status=404, body="")
    page.route("**/*", route)
    page.goto(SITE + rel[:-len("index.html")])
    page.wait_for_timeout(300)
    return page


def _tabs(page):
    out = []
    for btn in page.query_selector_all(".subnav button"):
        btn.click()
        page.wait_for_timeout(150)
        out.append((btn.text_content(), page.evaluate("[...document.querySelectorAll('#list .empty')]"
                                                      ".map(e => e.textContent.trim())"),
                    page.evaluate("document.documentElement.scrollWidth")))
    return out


EMPTY = {
    "ja/index.html": [("日次", ["まだレポートがありません。"]), ("週次", ["まだ週次レポートがありません。"]),
                      ("ニュース・産業", ["まだニュース・産業ブリーフがありません。"])],
    "ja/japan/index.html": [("日次", ["まだ日次大引けブリーフがありません。"]), ("週次", ["まだ週次レポートがありません。"])],
}


# The repo's own lists stop being empty once the edition publishes — feed empty ones.
NO_POSTS = {f"ja/{name}": [] for name in ("posts.json", "weekly.json", "news.json",
                                          "japan/daily.json", "japan/posts.json")}


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("rel", sorted(EMPTY))
def test_empty_lists_in_japanese_without_overflow(browser, rel, width):
    page = _open(browser, rel, width, NO_POSTS)
    assert page.evaluate("document.documentElement.scrollWidth") == width
    got = _tabs(page)
    assert [(t, e) for t, e, _ in got] == EMPTY[rel]
    assert all(sw == width for _, _, sw in got)
    page.close()


@pytest.mark.parametrize("width", [390, 1280])
def test_a_listed_post_renders_with_japanese_labels(browser, width):
    page = _open(browser, "ja/index.html", width, {"ja/posts.json": DAILY})
    assert page.evaluate("document.querySelector('a.post .date').textContent") == "2026-11-13 (金)"
    assert page.evaluate("document.querySelector('summary').textContent") == "2026年11月1件"
    assert page.evaluate("document.querySelector('a.post').getAttribute('href')") == "posts/2026-11-13.html"
    assert page.evaluate("document.documentElement.scrollWidth") == width
    page.close()


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("rel", ["index.html", "japan/index.html", "ja/index.html", "ja/japan/index.html"])
def test_language_button_keeps_the_menubar_on_one_row(browser, rel, width):
    page = _open(browser, rel, width, {})
    rows = page.evaluate("new Set([...document.querySelectorAll('nav.menubar > a')]"
                         ".map(a => Math.round(a.getBoundingClientRect().top))).size")
    assert rows == 1
    assert page.evaluate("document.documentElement.scrollWidth") == width
    page.close()


def test_names_match_the_glossary_and_translation_prompt(built):
    # C5·C6: 「마감브리프」=大引けブリーフ, 「뉴스·산업」=ニュース・産業, 「거래일」=営業日 — 목록·지시문·용어집이 같다
    from scripts.ja import glossary as G
    from scripts.ja import translate as T
    text = "".join(built.values()) + repr(SI.STRINGS) + repr(SI.SCRIPT_STRINGS)
    for bad in ("クロージングブリーフ", "ニュース・業界", "取引日"):
        assert bad not in text, bad
    assert "大引けブリーフ" in text and "ニュース・産業" in text
    assert G.DICT["뉴스·산업"] == "ニュース・産業" and "大引けブリーフ" in T.PROMPT
