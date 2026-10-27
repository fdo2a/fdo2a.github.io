"""One header pattern, home tabs in the URL, and fonts that actually load.

2026-10-21 impeccable critique P2: daily posts showed the brand twice (topbar, pill, brand link),
the US weekly had no way back to the index, the home tab was lost on back/refresh, and the
font stack named Pretendard without ever loading it (document.fonts was empty).
"""
import json
import re
from pathlib import Path

import pytest

from scripts.common import post_shell as S
from scripts.us import readability as R

ROOT = Path(__file__).resolve().parents[3]
BODY = '<section><div class="card headline-card"><h1>제목이다</h1><p>본문이다.</p></div></section>'


def _render(market, date='2026-10-19'):
    title = S.MARKETS[market]['title_prefix'] + f'테스트 | {date}'
    return S.render(market, date, {'title': title, 'summary': '요약'}, BODY)


def _crumbs(html):
    return re.search(r'<nav class="crumbs".*?</nav>', html, re.S).group(0)


@pytest.mark.parametrize('market,trail,aside', [
    ('us', [('미국 시장', '../index.html'), ('일간', '../index.html?span=daily')], None),
    ('news', [('미국 시장', '../index.html'), ('뉴스·산업', '../index.html?span=news')],
     ('같은 날 시황 브리프 →', '../posts/2026-10-19.html')),
    ('kr', [('한국 시장', '../index.html'), ('일간', '../index.html?span=daily')],
     ('미국 시장 →', '../../index.html')),
])
def test_daily_breadcrumbs(market, trail, aside):
    out = _render(market)
    nav = _crumbs(out)
    links = re.findall(r'<a(?: class="([^"]*)")? href="([^"]*)">([^<]*)</a>', nav)
    assert [(t, h) for c, h, t in links if c != 'crumbs-aside'] == trail
    got_aside = [(t, h) for c, h, t in links if c == 'crumbs-aside']
    assert got_aside == ([aside] if aside else [])


@pytest.mark.parametrize('market', ['us', 'news', 'kr'])
def test_brand_is_shown_once_and_the_old_pill_row_is_gone(market):
    out = _render(market)
    body = out[out.index('<body'):]
    visible = re.sub(r'<script\b.*?</script>|<[^>]+>', ' ', body, flags=re.S)
    assert visible.count(S.MARKETS[market]['brand']) == 1
    assert '‹ 전체 보고서' not in out and '🇺🇸' not in out
    assert re.search(r'<div class="topbar">(.*?)</div>', out)      # parsers match it verbatim


@pytest.mark.parametrize('market', ['us', 'news', 'kr'])
def test_breadcrumbs_carry_no_numbers(market):
    # A date in the crumbs would enter recap evidence and widen the weekly allowlist (codex P1).
    assert R.visible_numeric_tokens(_crumbs(_render(market))) == []


def test_weekly_and_japan_have_a_way_back():
    from scripts.us import weekly_insight
    from scripts.japan import render as J
    for module in (weekly_insight, J):
        src = Path(module.__file__).read_text(encoding='utf-8')
        assert 'S.crumbs(' in src, module.__name__
    nav = S.crumbs([('미국 시장', '../index.html'), ('주간', '../index.html?span=weekly')])
    assert 'href="../index.html?span=weekly"' in nav and R.visible_numeric_tokens(nav) == []


FONT = 'pretendardvariable-dynamic-subset.min.css'


@pytest.mark.parametrize('market', ['us', 'news', 'kr'])
def test_post_head_loads_the_font(market):
    head = _render(market).split('</head>')[0]
    assert FONT in head and 'rel="preconnect"' in head


@pytest.mark.parametrize('path', ['index.html', 'kr/index.html', 'japan/index.html'])
def test_index_pages_load_the_font_and_share_the_stack(path):
    html = (ROOT / path).read_text(encoding='utf-8')
    assert FONT in html
    assert "Toss Product Sans" not in html
    assert "'Pretendard Variable', Pretendard" in html


def test_post_css_and_thesis_share_the_stack():
    for text in (S.css('us'), S.css('kr'),
                 (ROOT / 'scripts/build_thesis_pages.py').read_text(encoding='utf-8')):
        assert 'Toss Product Sans' not in text
        assert "'Pretendard Variable', Pretendard" in text
    assert FONT in (ROOT / 'scripts/build_thesis_pages.py').read_text(encoding='utf-8')


# ── home tabs ──────────────────────────────────────────────────────────────
sync_playwright = pytest.importorskip('playwright.sync_api').sync_playwright

DAILY = [{'date': '2026-10-19', 'title': '일간 하나', 'headline': 'h'}]
WEEKLY = [{'key': '2026-W42', 'title': '주간 하나', 'headline': 'h', 'end_date': '2026-10-16'}]


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _home(browser, query='', fail=(), hold=None):
    """Open index.html at https://fdo2a.github.io/{query}; json served from fixtures."""
    page = browser.new_page(viewport={'width': 390, 'height': 800})
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    held = []
    data = {'posts.json': DAILY, 'weekly.json': WEEKLY, 'news.json': []}

    def route(r):
        url = r.request.url
        name = url.split('/')[-1].split('?')[0]
        if name in data:
            if name in fail:
                return r.fulfill(status=500, body='')
            if hold and name == hold:
                held.append(r)
                return None
            return r.fulfill(body=json.dumps(data[name]), content_type='application/json')
        if url.startswith('https://fdo2a.github.io/'):
            return r.fulfill(body=html, content_type='text/html')
        return r.abort()
    page.route('**/*', route)
    page.goto('https://fdo2a.github.io/' + query)
    page.wait_for_timeout(300)
    return page, held, data


def _state(page):
    return page.evaluate("""() => ({
        tab: document.querySelector('.subnav [aria-selected="true"]').dataset.span,
        url: location.search,
        titles: [...document.querySelectorAll('#list .title')].map(e => e.textContent),
        empty: (document.querySelector('#list .empty') || {}).textContent || ''})""")


def test_span_in_the_url_opens_that_tab(browser):
    page, _, _ = _home(browser, '?span=weekly')
    assert _state(page)['tab'] == 'weekly' and _state(page)['titles'] == ['주간 하나']
    page.close()


def test_unknown_span_falls_back_to_daily(browser):
    page, _, _ = _home(browser, '?span=<script>')
    assert _state(page)['tab'] == 'daily' and _state(page)['titles'] == ['일간 하나']
    page.close()


def test_abolished_monthly_span_falls_back_to_daily(browser):
    page, _, _ = _home(browser, '?span=monthly')
    assert _state(page)['tab'] == 'daily' and _state(page)['titles'] == ['일간 하나']
    page.close()


def test_clicking_a_tab_writes_the_url(browser):
    page, _, _ = _home(browser)
    page.click('.subnav [data-span="weekly"]')
    page.wait_for_timeout(200)
    assert _state(page)['url'] == '?span=weekly'
    page.click('.subnav [data-span="daily"]')
    page.wait_for_timeout(200)
    assert _state(page)['url'] == ''
    page.close()


def test_failure_shows_retry_and_retry_recovers(browser):
    page, _, _ = _home(browser, fail=('posts.json',))
    assert '불러오지 못했습니다' in _state(page)['empty']
    page.unroute('**/*')
    page.route('**/posts.json', lambda r: r.fulfill(body=json.dumps(DAILY), content_type='application/json'))
    page.click('#list button.retry')
    page.wait_for_timeout(300)
    assert _state(page)['titles'] == ['일간 하나']
    page.close()


def test_late_response_does_not_overwrite_the_selected_tab(browser):
    page, held, data = _home(browser, hold='posts.json')
    page.click('.subnav [data-span="weekly"]')
    page.wait_for_timeout(200)
    held[0].fulfill(body=json.dumps(data['posts.json']), content_type='application/json')
    page.wait_for_timeout(300)
    st = _state(page)
    assert st['tab'] == 'weekly' and st['titles'] == ['주간 하나'] and st['url'] == '?span=weekly'
    page.close()


def test_subnav_is_a_tablist_distinct_from_the_menubar(browser):
    page, _, _ = _home(browser)
    got = page.evaluate("""() => {
        const sub = document.querySelector('.subnav'), btn = sub.querySelector('[aria-selected="true"]');
        const cs = getComputedStyle(btn);
        return {role: sub.getAttribute('role'), tabs: sub.querySelectorAll('[role="tab"]').length,
                radius: parseFloat(cs.borderTopLeftRadius), height: btn.getBoundingClientRect().height,
                underline: parseFloat(cs.borderBottomWidth) > 0};
    }""")
    assert got['role'] == 'tablist' and got['tabs'] == 3
    assert got['radius'] >= 12 and got['height'] >= 36 and not got['underline']
    page.close()


def test_blocked_font_cdn_falls_back_without_breaking_layout(browser):
    page, _, _ = _home(browser)
    assert page.evaluate('document.documentElement.scrollWidth') == 390
    family = page.evaluate("getComputedStyle(document.body).fontFamily")
    assert family.startswith('"Pretendard Variable"')
    page.close()


def test_tabs_follow_the_keyboard_tab_pattern(browser):
    page, _, _ = _home(browser)
    page.focus('.subnav [data-span="daily"]')
    page.keyboard.press('ArrowRight')
    page.wait_for_timeout(200)
    got = page.evaluate("""() => ({focus: document.activeElement.dataset.span,
        tabindex: [...document.querySelectorAll('.subnav [role=tab]')].map(b => b.tabIndex),
        panel: document.getElementById('list').getAttribute('role'),
        controls: document.querySelector('.subnav [role=tab]').getAttribute('aria-controls')})""")
    assert got == {'focus': 'weekly', 'tabindex': [-1, 0, -1], 'panel': 'tabpanel', 'controls': 'list'}
    assert _state(page)['tab'] == 'weekly' and _state(page)['url'] == '?span=weekly'
    page.keyboard.press('End')
    page.wait_for_timeout(200)
    assert _state(page)['tab'] == 'news'
    page.close()
