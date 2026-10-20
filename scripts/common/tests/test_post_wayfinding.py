"""Contrast, mobile tables and wayfinding on daily posts — measured in a real browser.

2026-10-21 impeccable critique (20/40): muted text and the gain/loss colours were 2.6-3.5:1,
mobile tables dropped to 11px, and a 21,731px daily post had no way to move between posts.
Registered blocks (readability-v5, signcolor-v1, fund and sector renderers) are replayed byte
for byte by the review and publish gates, so they stay untouched; post_css overrides them.
"""
import json
import re

import pytest

from scripts.common import post_shell as S
from scripts.us import colorize, readability as R

sync_playwright = pytest.importorskip('playwright.sync_api').sync_playwright

MUTED, UP, DOWN = 'rgb(95, 107, 122)', 'rgb(0, 122, 69)', 'rgb(200, 40, 46)'
BACKGROUNDS = ('#FFFFFF', '#F2F4F6', '#F9FAFB', '#E8F2FF', '#E8F8EE', '#FFE8E8')


def _lum(hexcode):
    c = [int(hexcode.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize('token', ['#5F6B7A', '#007A45', '#C8282E'])
def test_tokens_pass_aa_on_every_page_background(token):
    assert min(_ratio(token, bg) for bg in BACKGROUNDS) >= 4.5


@pytest.mark.parametrize('market', ['us', 'kr'])
def test_post_css_has_no_failing_text_colour_left(market):
    # Attribute selectors that match the old inline colours are the override, not a use.
    css = re.sub(r'\[[^\]]*\]', '', S.css(market))
    # Bar fills may keep any colour; text colours may not. post_css has no bar fills.
    for old in ('#8B95A1', '#00A85A', '#FF4040'):
        assert re.search(r'(?<![-\w])color\s*:\s*' + old, css, re.I) is None, old


BODY = (
    '<section><div class="card headline-card"><h1>제목이다</h1><p>본문 첫 문단이다.</p>'
    '<p class="caption">캡션</p></div></section>'
    + ''.join(
        f'<section id="s{i}"><div class="card"><h2>섹션 {i}</h2>'
        + '<p>문단이다. ' * 40 + '</p>'
        '<div class="tbl-scroll"><table><thead><tr><th>자산</th><th>종가</th><th>1일</th>'
        '<th>1주</th><th>1개월</th><th>6개월</th><th>1년</th><th>비고</th></tr></thead><tbody>'
        '<tr><td>S&amp;P 500</td><td>6,712.30</td><td class="sc-up">+1.02%</td>'
        '<td class="sc-dn">-0.40%</td><td>+2.10%</td><td>+8.00%</td><td>+15.20%</td>'
        '<td><span class="sub">보조 설명</span></td></tr></tbody></table></div>'
        '</div></section>'
        for i in range(1, 7))
    + '<section><div class="card"><div class="fund-board"><span class="fb-p">+1.0%</span>'
    '<span class="fb-n">-1.0%</span><span class="fb-t">메모</span></div>'
    '<div class="spf-val" style="color:#e5342b">-1.00%</div>'
    '<div class="spf-val" style="color:#00a763">+1.00%</div>'
    '<div style="color: #8B95A1; font-size: 12.5px;">편집자</div></div></section>'
)
META = {'title': '미국 증시 마감 시황 — 테스트 | 2026-10-16', 'summary': '요약이다.'}
INDEX = [{'date': '2026-10-19'}, {'date': '2026-10-16'}, {'date': '2026-10-15'}]
NEWS = [{'key': '2026-10-16'}, {'key': '2026-10-15'}]


def _published(market='us', date='2026-10-16'):
    meta = dict(META, title=META['title'].replace('2026-10-16', date))
    if market == 'kr':
        meta['title'] = f'코스피 마감 시황 — 테스트 | {date}'
    out = S.render(market, date, meta, BODY)
    return colorize.apply(R.enhance_html(out)) if market == 'us' else R.enhance_html(out)


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(browser, html, width, market='us', index=INDEX, news=NEWS):
    page = browser.new_page(viewport={'width': width, 'height': 800})
    base = 'https://fdo2a.github.io/' + ('kr/' if market == 'kr' else '')

    def route(r):
        url = r.request.url
        if url.endswith('/posts.json'):
            return r.fulfill(body=json.dumps(index), content_type='application/json')
        if url.endswith('/news.json'):
            return r.fulfill(body=json.dumps(news), content_type='application/json')
        if url.endswith('.html'):
            return r.fulfill(body=html, content_type='text/html')
        return r.abort()
    page.route('**/*', route)
    page.goto(base + 'posts/2026-10-16.html')
    page.wait_for_timeout(300)
    return page


@pytest.mark.parametrize('market', ['us', 'kr'])
@pytest.mark.parametrize('width', [390, 1280])
def test_no_horizontal_page_scroll(browser, market, width):
    page = _open(browser, _published(market), width, market)
    assert page.evaluate('document.documentElement.scrollWidth') == width
    page.close()


@pytest.mark.parametrize('market', ['us', 'kr'])
def test_mobile_table_text_is_at_least_13px(browser, market):
    page = _open(browser, _published(market), 390, market)
    sizes = page.evaluate("""() => [...document.querySelectorAll('.tbl-scroll th, .tbl-scroll td,'
        + ' .tbl-scroll td .sub')].map(e => parseFloat(getComputedStyle(e).fontSize))""")
    assert sizes and min(sizes) >= 13
    page.close()


def test_mobile_stance_labels_are_at_least_12px(browser):
    table = ('<div class="tbl-scroll"><table class="stance-tbl"><thead><tr><th>자산군</th><th>등급</th>'
             '<th>유지</th><th>전일대비</th><th>논거</th><th>다음</th></tr></thead><tbody><tr>'
             '<td data-label="자산군">주식</td><td data-label="등급">중립</td><td data-label="유지">3일</td>'
             '<td data-label="전일대비">—</td><td data-label="논거">근거</td>'
             '<td data-label="다음">조건</td></tr></tbody></table></div>')
    html = S.render('us', '2026-10-16', META, BODY.replace('<p class="caption">', table + '<p class="caption">', 1))
    page = _open(browser, R.enhance_html(html), 390)
    out = page.evaluate("""() => [...document.querySelectorAll('.stance-tbl td')].map(e => [
        parseFloat(getComputedStyle(e).fontSize), parseFloat(getComputedStyle(e, '::before').fontSize)])""")
    assert min(a for a, _ in out) >= 13 and min(b for _, b in out) >= 12
    page.close()


def test_colours_meet_contrast_including_registered_and_inline_blocks(browser):
    page = _open(browser, _published('us'), 1280)
    got = page.evaluate("""() => {
        const c = s => getComputedStyle(document.querySelector(s)).color;
        return {caption: c('.caption'), label: c('.reading-map-label'), up: c('td.sc-up'),
                down: c('td.sc-dn'), fp: c('.fb-p'), fn: c('.fb-n'), ft: c('.fb-t'),
                spfn: c('.spf-val[style*="e5342b"]'), spfp: c('.spf-val[style*="00a763"]'),
                inline: c('div[style*="8B95A1"]')};
    }""")
    assert got == {'caption': MUTED, 'label': MUTED, 'up': UP, 'down': DOWN, 'fp': UP, 'fn': DOWN,
                   'ft': MUTED, 'spfn': DOWN, 'spfp': UP, 'inline': MUTED}
    page.close()


@pytest.mark.parametrize('width', [390, 1280])
def test_reading_map_sticks_to_the_top(browser, width):
    page = _open(browser, _published('us'), width)
    page.evaluate('window.scrollTo(0, 4000)')
    page.wait_for_timeout(200)
    top = page.evaluate("document.querySelector('nav.reading-map').getBoundingClientRect().top")
    assert top == 0
    page.close()


def test_anchor_jump_clears_the_sticky_map(browser):
    page = _open(browser, _published('us'), 390)
    page.evaluate("document.getElementById('s3').scrollIntoView()")
    page.wait_for_timeout(200)
    nav = page.evaluate("document.querySelector('nav.reading-map').getBoundingClientRect().bottom")
    h2 = page.evaluate("document.querySelector('#s3 h2').getBoundingClientRect().top")
    assert h2 >= nav
    page.close()


def test_footer_links_prev_next_and_same_day_news(browser):
    page = _open(browser, _published('us'), 1280)
    got = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('nav.post-foot a')]
        .filter(a => !a.hidden).map(a => [a.className || a.textContent.trim(), a.getAttribute('href')]))""")
    assert got['pf-prev'] == '2026-10-15.html'
    assert got['pf-next'] == '2026-10-19.html'
    assert got['pf-news'] == '../news/2026-10-16.html'
    page.close()


def test_footer_hides_what_does_not_exist(browser):
    page = _open(browser, _published('us', '2026-10-19'), 1280, news=[])
    hidden = page.evaluate("""() => Object.fromEntries(['pf-prev', 'pf-next', 'pf-news'].map(
        c => [c, document.querySelector('nav.post-foot .' + c).hidden]))""")
    # 10/19 is the newest post and has no news brief yet; 10/16 before it exists.
    assert hidden == {'pf-prev': False, 'pf-next': True, 'pf-news': True}
    page.close()


def test_current_section_is_marked_in_the_reading_map(browser):
    page = _open(browser, _published('us'), 1280)
    page.evaluate("document.getElementById('s3').scrollIntoView()")
    page.wait_for_timeout(400)
    current = page.evaluate(
        "[...document.querySelectorAll('nav.reading-map a[aria-current]')].map(a => a.getAttribute('href'))")
    assert current == ['#s3']
    page.close()


@pytest.mark.parametrize('market,index', [('us', '../posts.json'), ('kr', '../posts.json'),
                                          ('news', '../news.json')])
def test_footer_is_rendered_for_daily_markets(market, index):
    title = S.MARKETS[market]['title_prefix'] + '테스트 | 2026-10-16'
    out = S.render(market, '2026-10-16', dict(META, title=title), BODY)
    foot = re.search(r'<nav class="post-foot".*?</nav>', out, re.S).group(0)
    assert f'data-index="{index}"' in foot and 'data-key="2026-10-16"' in foot
    assert ('data-news-index=' in foot) == (market == 'us')
    assert '<a href="#">' in foot
    # The footer must not add a single reader-visible number.
    assert R.visible_numeric_tokens(foot) == []
    # Body extraction tools take the last </div> before </body> as the end of .doc.
    tail = out[out.rindex('</div>', 0, out.rindex('</body>')):]
    assert 'post-foot' in tail


def test_print_hides_the_footer_and_unsticks_the_map(browser):
    page = _open(browser, _published('us'), 1280)
    page.emulate_media(media='print')
    got = page.evaluate("""() => [getComputedStyle(document.querySelector('nav.post-foot')).display,
        getComputedStyle(document.querySelector('nav.reading-map')).position]""")
    assert got == ['none', 'static']
    page.close()


def test_contested_gate_still_trusts_posts_published_with_the_previous_shell_css():
    """News posts in the contested runner's 3-day window carry the CSS they were published with."""
    from scripts import check_contested
    trusted = check_contested.trusted_styles('us', '2026-10-20')
    for legacy in S.legacy_css('news'):
        assert any(legacy.strip() in s for s in trusted)
    assert len(S.legacy_css('news')) == 2
    assert any(S.css('us').strip() in s for s in trusted)


def test_footer_is_not_read_as_a_news_article():
    """news_gate counts any element carrying `data-news` as an article (codex 2026-10-21)."""
    from scripts.us import news_gate
    from html.parser import HTMLParser
    foot = S.footer('us', '2026-10-16')
    found = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if news_gate._is_item(dict(attrs)):
                found.append(tag)
    P().feed(foot)
    assert found == []


def test_inline_overrides_ignore_background_and_border_colours(browser):
    body = BODY + ('<section><div class="card">'
                   '<p id="bg" style="background-color:#00a763;color:#191F28">배경</p>'
                   '<p id="bd" style="border-color:#e5342b;color:#191F28">테두리</p>'
                   '<p id="sp" style="font-size:12.5px; color:#8B95A1;">세미콜론 뒤</p>'
                   '</div></section>')
    page = _open(browser, R.enhance_html(S.render('us', '2026-10-16', META, body)), 1280)
    got = page.evaluate("""() => ['bg', 'bd', 'sp'].map(i => getComputedStyle(document.getElementById(i)).color)""")
    assert got == ['rgb(25, 31, 40)', 'rgb(25, 31, 40)', MUTED]
    page.close()


@pytest.mark.parametrize('width', [390, 1280])
def test_reading_map_is_not_scrolled_sideways_at_the_top(browser, width):
    """Marking the first section must not scroll the 「빠른 이동」 label out of view."""
    page = _open(browser, _published('us'), width)
    page.wait_for_timeout(300)
    assert page.evaluate("document.querySelector('nav.reading-map').scrollLeft") == 0
    page.close()


def test_current_chip_is_scrolled_into_view_on_mobile(browser):
    page = _open(browser, _published('us'), 390)
    page.evaluate("document.getElementById('s5').scrollIntoView()")
    page.wait_for_timeout(400)
    got = page.evaluate("""() => { const a = document.querySelector('nav.reading-map a[aria-current]');
        const r = a.getBoundingClientRect(), m = a.parentElement.getBoundingClientRect();
        return [a.getAttribute('href'), r.left >= m.left, r.right <= m.right]; }""")
    assert got == ['#s5', True, True]
    page.close()
