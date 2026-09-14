from us.source_gate import check

CPI_URL = 'https://www.bls.gov/news.release/cpi.nr0.htm'
PCE_URL = 'https://www.bea.gov/news/2026/personal-income-and-outlays-august-2026'
FOMC_URL = 'https://www.federalreserve.gov/newsevents/pressreleases/monetary20260917a.htm'


def _releases(*rows):
    """index.json shape: every attempt is recorded, failures included."""
    return {'report_date': '2026-09-11', 'releases': list(rows)}


def _rel(key, url, ok=True):
    return {'key': key, 'url': url, 'ok': ok, 'note': 'impersonate=safari',
            'chars': 20400, 'path': f'releases/{key}.txt'}


def _fed(key='fomc-20260917', urls=((FOMC_URL, True),)):
    return {'report_date': '2026-09-11', 'events': [
        {'key': key, 'kind_ko': 'FOMC 성명', 'fresh': True, 'tier': 1,
         'sources': [{'role': 'statement', 'label': 'FOMC 성명 전문',
                      'url': u, 'ok': ok, 'chars': 9000} for u, ok in urls]}]}


def _page(body, main=True):
    """A post as it actually ships — head URLs the gate must not touch."""
    head = (
        '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js">'
        '</script>'
        '<link rel="canonical" href="https://fdo2a.github.io/posts/2026-09-11.html">'
        '<meta property="og:url" content="https://fdo2a.github.io/posts/2026-09-11.html">'
        '<script type="application/ld+json">'
        '{"@type":"NewsArticle","url":"https://fdo2a.github.io/posts/2026-09-11.html"}'
        '</script>')
    inner = f'<main class="container doc">{body}</main>' if main else body
    return f'<html><head>{head}</head><body>{inner}</body></html>'


def _block(key, href=CPI_URL, label='BLS 소비자물가 발표문', attr='data-release'):
    link = f'<p class="caption">출처: <a href="{href}">{label}</a></p>' if href else ''
    return (f'<div {attr}="{key}"><p>주거비가 전월 대비 0.1% 올라 헤드라인 상승분의 '
            f'3분의 2를 만들었다.</p>{link}</div>')


# --- an absent index authorises nothing; it does not switch the gate off ------

def test_no_index_still_forbids_an_invented_link():
    """수집이 실패한 날이야말로 지어낸 링크가 실릴 확률이 가장 높은 날이다."""
    page = _page(f'<p>BLS 는 <a href="{CPI_URL}">이렇게</a> 밝혔다.</p>')
    assert check(page, None, None)


def test_no_index_and_no_links_still_passes():
    assert check(_page('<p>조용한 하루였다.</p>'), None, None) == []


def test_a_page_with_no_body_links_passes():
    assert check(_page('<p>조용한 하루였다.</p>'), _releases(), _fed()) == []


def test_head_urls_are_not_source_links():
    """AdSense·canonical·OG·JSON-LD are already in every post — a gate that reads
    「every external URL」 blocks publishing on day one."""
    assert check(_page('<p>조용한 하루였다.</p>'), _releases(_rel('cpi', CPI_URL)),
                 None) == []


def test_same_origin_navigation_is_not_a_source_link():
    body = ('<p>조용한 하루였다.</p>'
            '<a href="https://fdo2a.github.io/posts/2026-09-10.html">어제 브리프</a>'
            '<a href="../index.html">목록</a><a href="#top">맨 위로</a>')
    assert check(_page(body), _releases(), _fed()) == []


# --- the binding: a cited document is reachable from the block that cites it ---

def test_a_release_block_carries_its_source_link():
    html = _page(_block('cpi'))
    assert check(html, _releases(_rel('cpi', CPI_URL)), None) == []


def test_a_block_without_a_link_is_fine():
    """요구는 2026-09-14 에 철회됐다 — 출처는 링크가 아니라 문장의 주어로 간다."""
    html = _page(_block('cpi', href=None))
    assert check(html, _releases(_rel('cpi', CPI_URL)), None) == []


def test_a_link_in_the_wrong_block_does_not_count():
    """An allow-list of URLs would pass this: both URLs are collected, both ok."""
    html = _page(_block('cpi', href=PCE_URL, label='BEA 발표문')
                 + _block('pce', href=PCE_URL, label='BEA 발표문'))
    v = check(html, _releases(_rel('cpi', CPI_URL), _rel('pce', PCE_URL)), None)
    assert any('cpi' in x for x in v)


def test_a_hidden_link_is_judged_like_any_other():
    """숨긴 링크도 발행물에 들어 있다 — 스타일시트 한 줄이면 보인다."""
    html = _page(f'<div data-release="cpi"><p>주거비가 헤드라인을 만들었다.</p>'
                 f'<div style="display:none"><a href="https://evil.example/x">x</a></div></div>')
    assert any('evil.example' in x
               for x in check(html, _releases(_rel('cpi', CPI_URL)), None))


def test_a_link_to_a_document_we_failed_to_fetch_is_blocked():
    """ok:false stays in index.json. Linking it publishes a URL nobody verified."""
    html = _page(_block('cpi'))
    v = check(html, _releases(_rel('cpi', CPI_URL, ok=False)), None)
    assert any('cpi' in x or CPI_URL in x for x in v)


def test_a_mistyped_url_is_blocked():
    html = _page(_block('cpi', href='https://www.bls.gov/news.release/cpi.nr1.htm'))
    v = check(html, _releases(_rel('cpi', CPI_URL)), None)
    assert any('cpi' in x for x in v)


def test_an_unmarked_external_link_is_blocked():
    body = '<p>어느 기사에 <a href="https://example.com/x">이렇게</a> 나온다.</p>'
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('example.com' in x for x in v)


def test_a_dangerous_scheme_is_blocked():
    body = '<div data-release="cpi"><p>주거비.</p><a href="javascript:alert(1)">x</a></div>'
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('javascript' in x for x in v)


# --- fed events bind the same way --------------------------------------------

def test_a_fed_quote_block_carries_its_source_link():
    html = _page(_block('fomc-20260917', href=FOMC_URL, label='FOMC 성명 전문',
                        attr='data-fed-quote'))
    assert check(html, None, _fed()) == []


def test_a_fed_quote_block_without_a_link_is_fine():
    html = _page(_block('fomc-20260917', href=None, attr='data-fed-quote'))
    assert check(html, None, _fed()) == []


def test_a_fed_event_with_no_fetched_source_requires_no_link():
    html = _page(_block('fomc-20260917', href=None, attr='data-fed-quote'))
    assert check(html, None, _fed(urls=((FOMC_URL, False),))) == []


def test_a_link_in_navigation_chrome_is_not_a_source_link():
    """Nav and footer are navigation, not evidence."""
    body = ('<nav><a href="https://fdo2a.github.io/">홈</a></nav>'
            f'<main>{_block("cpi")}</main>'
            '<footer><a href="https://github.com/fdo2a">GitHub</a></footer>')
    html = f'<html><body>{body}</body></html>'
    assert check(html, _releases(_rel('cpi', CPI_URL)), None) == []


def test_an_entity_encoded_url_still_matches():
    html = _page(_block('cpi', href=CPI_URL.replace('&', '&amp;')))
    assert check(html, _releases(_rel('cpi', CPI_URL)), None) == []


def test_a_mistyped_url_is_not_reported_as_a_failed_fetch():
    """The diagnosis has to point at the URL, not at the collector."""
    html = _page(_block('cpi', href='https://www.bls.gov/news.release/cpi.nr1.htm'))
    v = check(html, _releases(_rel('cpi', CPI_URL)), None)
    assert any('수집한 원문 목록에 없다' in x for x in v)
    assert not any('ok:false' in x for x in v)


# --- 숨겼다고 넘어가지 않는다 (codex 구현 검토 단서, 2026-09-14) ------------
# 아래 입력은 전부 옛 계약에서 «통과»하던 것이다. 숨김 판정은 링크 의무를 채우지
# 못하게 하려고 있었고, 의무가 사라지자 「보지 말라」로 뒤집혔다.

def _bad(href=CPI_URL, style=None, cls=None, extra=''):
    a = (f'<a href="{href}"'
         + (f' style="{style}"' if style else '')
         + (f' class="{cls}"' if cls else '') + f'{extra}>BLS</a>')
    return _page(f'<div data-release="cpi"><p>주거비가 헤드라인을 만들었다.</p>{a}</div>')


def test_an_invisible_unauthorised_link_is_still_judged():
    for style in ('opacity:0', 'opacity:0.09', 'font-size:0',
                  'width:0;height:0;overflow:hidden', 'DISPLAY : none',
                  'visibility:hidden'):
        v = check(_bad(href='https://evil.example/x', style=style),
                  _releases(_rel('cpi', CPI_URL)), None)
        assert any('evil.example' in x for x in v), style


def test_a_stylesheet_cannot_take_a_link_out_of_scope():
    """CSS 엔진 없이 렌더 결과를 맞힐 수 없다 — 미디어쿼리 하나로 뚫렸다."""
    for css in ('.gone{display:none}',
                '@media (max-width:600px){.gone{display:none}}',
                '.gone{display:none} .gone{display:inline}'):
        html = (_bad(href='https://evil.example/x', cls='gone')
                .replace('</head>', f'<style>{css}</style></head>'))
        v = check(html, _releases(_rel('cpi', CPI_URL)), None)
        assert any('evil.example' in x for x in v), css


def test_script_and_template_are_not_the_document():
    """렌더되지 않는 것은 숨긴 것이 아니라 문서가 아니다."""
    for tag in ('script', 'template'):
        html = _page(f'<div data-release="cpi"><p>주거비.</p>'
                     f'<{tag}><a href="https://evil.example/x">BLS</a></{tag}></div>')
        assert check(html, _releases(_rel('cpi', CPI_URL)), None) == [], tag


def test_a_visible_class_still_counts():
    html = _bad(cls='caption').replace('</head>', '<style>.caption{color:#888}</style></head>')
    assert check(html, _releases(_rel('cpi', CPI_URL)), None) == []


def test_a_nested_anchor_is_still_checked():
    """HTML5 splits nested anchors; the reader must not let the outer one swallow
    the inner href."""
    body = (f'<div data-release="cpi"><p>주거비.</p>'
            f'<a href="{CPI_URL}">BLS<a href="https://evil.example/x">evil</a></a></div>')
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('evil.example' in x for x in v)


def test_an_unclosed_anchor_is_still_checked():
    body = '<p>기사: <a href="https://evil.example/x">evil'
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('evil.example' in x for x in v)


def test_a_duplicate_href_is_read_the_way_a_browser_reads_it():
    """HTML keeps the first duplicate attribute — so does the gate."""
    body = (f'<div data-release="cpi"><p>주거비.</p>'
            f'<a href="https://evil.example/x" href="{CPI_URL}">BLS</a></div>')
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('evil.example' in x for x in v)


def test_a_self_closing_main_does_not_take_the_body_out_of_scope():
    body = '<main/><p>기사: <a href="https://evil.example/x">evil</a></p>'
    html = f'<html><body>{body}</body></html>'
    v = check(html, _releases(_rel('cpi', CPI_URL)), None)
    assert any('evil.example' in x for x in v)


def test_a_backslash_url_is_not_mistaken_for_a_relative_path():
    body = '<p>기사: <a href="https:\\\\evil.example\\x">evil</a></p>'
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('evil.example' in x for x in v)


def test_a_scheme_without_a_host_is_blocked():
    body = '<p>기사: <a href="https:///x">evil</a></p>'
    v = check(_page(body), _releases(_rel('cpi', CPI_URL)), None)
    assert any('호스트' in x for x in v)


def test_the_innermost_block_owns_the_link():
    """A correct ancestor must not authorise a link sitting in a different claim."""
    body = (f'<div data-release="cpi"><p>주거비.</p>'
            f'<div data-release="pce"><p>소비.</p><a href="{CPI_URL}">BLS</a></div>'
            f'</div>')
    v = check(_page(body), _releases(_rel('cpi', CPI_URL), _rel('pce', PCE_URL, ok=False)),
              None)
    assert any('pce' in x and 'cpi' in x for x in v)


# --- fed: the quote is where the link is owed ---------------------------------

def test_a_fed_link_must_still_sit_in_a_fed_block():
    """요구는 없어도 «어디에 붙느냐»는 그대로다."""
    body = _block('fomc-20260917', href=FOMC_URL, label='FOMC 성명 전문',
                  attr='data-release')
    v = check(_page(body), _releases(_rel('fomc-20260917', CPI_URL)), _fed())
    assert any('data-release' in x for x in v)


def test_a_release_key_and_a_fed_key_do_not_authorise_each_other():
    body = _block('clash', href=FOMC_URL, label='FOMC', attr='data-release')
    v = check(_page(body), _releases(_rel('clash', CPI_URL)), _fed(key='clash'))
    assert any('data-release="clash"' in x for x in v)
