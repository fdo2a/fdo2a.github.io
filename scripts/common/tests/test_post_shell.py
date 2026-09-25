"""Post shell — writers author the body; the shell owns head, CSS, top bar and nav.

Design: docs/superpowers/specs/2026-09-24-post-shell.md
"""
import json
import re
from pathlib import Path

import pytest

from scripts.common import post_shell as S

ROOT = Path(__file__).resolve().parents[3]


def _split(path):
    """A published post → (meta, body) — the inverse of render, for round-trip tests."""
    html = (ROOT / path).read_text(encoding='utf-8')
    start = html.index('<div class="doc">') + len('<div class="doc">')
    end = html.rindex('</div>', 0, html.rindex('</body>'))
    title = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
    summary = re.search(r'property="og:description" content="([^"]*)"', html).group(1)
    return {'title': S.unescape(title), 'summary': S.unescape(summary)}, html[start:end]


@pytest.mark.parametrize('market,date,path', [
    ('us', '2026-09-23', 'posts/2026-09-23.html'),
    ('kr', '2026-09-23', 'kr/posts/2026-09-23.html'),
])
def test_round_trip_keeps_the_body_and_fixes_the_head(market, date, path):
    meta, body = _split(path)
    out = S.render(market, date, meta, body)
    head = out[:out.index('<body')]
    # 손으로 쓴 head 는 description·canonical·og 를 두 번씩 실었다(2026-09-23 US).
    for tag in ('name="description"', 'rel="canonical"', 'property="og:title"',
                'property="og:url"', 'property="og:description"', '<title>',
                'application/ld+json', 'adsense-loader', 'post-shell-v1'):
        assert head.count(tag) == 1, tag
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                              head, re.S).group(1))
    assert ld['@type'] == 'NewsArticle' and ld['inLanguage'] == 'ko'
    assert ld['mainEntityOfPage'].endswith(path)
    assert ld['headline'] == re.search(r'property="og:title" content="([^"]*)"', head).group(1)
    assert body in out                                   # 본문은 한 글자도 안 바뀐다
    assert out.count('<div class="doc">') == 1
    assert '전체 보고서' in out and 'class="topbar"' in out
    h1 = re.search(r'<h1>(.*?)</h1>', body, re.S).group(1)
    assert f'content="{S.escape(S.plain(h1))}. {date}' in head   # description 은 h1 에서


def test_css_comes_from_the_template_not_the_writer():
    meta, body = _split('kr/posts/2026-09-23.html')
    out = S.render('kr', '2026-09-23', meta, body)
    assert S.css('kr') in out


@pytest.mark.parametrize('body,needle', [
    ('<html><body><h1>x</h1></body></html>', '<html'),
    ('<h1>a</h1><h1>b</h1>', 'h1'),
    ('<p>no heading</p>', 'h1'),
    ('<div class="doc"><h1>a</h1></div>', 'doc'),
    ('<style>.card { padding:0 }</style><h1>a</h1>', '.card'),
])
def test_body_contract_violations_are_named(body, needle):
    errors = S.validate('us', '2026-09-23', {'title': '미국 증시 마감 시황 — x | 2026-09-23',
                                             'summary': '요약'}, body)
    assert errors and any(needle in e for e in errors), errors


def test_widget_styles_that_do_not_touch_the_template_are_allowed():
    body = '<h1>a</h1><style>.spf-grid{display:grid}</style>'
    assert S.validate('us', '2026-09-23', {'title': '미국 증시 마감 시황 — x | 2026-09-23',
                                           'summary': '요약'}, body) == []


@pytest.mark.parametrize('market,title', [
    ('us', 'US Market Brief — 2026-09-23'),
    ('us', '미국 증시 마감 시황 — x | 2026-09-22'),
    ('kr', '미국 증시 마감 시황 — x | 2026-09-23'),
])
def test_seo_title_format_is_enforced(market, title):
    errors = S.validate(market, '2026-09-23', {'title': title, 'summary': 's'}, '<h1>a</h1>')
    assert any('title' in e for e in errors)


def test_json_ld_cannot_be_closed_by_the_summary():
    out = S.render('us', '2026-09-23', {'title': '미국 증시 마감 시황 — x | 2026-09-23',
                                        'summary': 'a</script><script>alert(1)'}, '<h1>a</h1>')
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', out, re.S).group(1)
    assert json.loads(ld)['description'].startswith('a</script>')


def test_daily_shell_declares_the_desk_register():
    """US·KR 일간은 PM 이 읽는 -다 문서다(2026-09-24). 선언이 있어야 check_style 이 데스크 검사를 한다."""
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from us.style import is_desk_register
    for market, path in (('us', 'posts/2026-09-23.html'), ('kr', 'kr/posts/2026-09-23.html')):
        meta, body = _split(path)
        assert is_desk_register(S.render(market, '2026-09-23', meta, body)), market


# ── 뉴스·산업 브리프 (2026-09-26) ─────────────────────────────────────────
# 사용자 지시 「오늘의 뉴스, 메모리/DRAM, AI 인프라, MLCC…를 시황 레포트에서 제외시킨 뒤, 새로운
# 글을 하나 더 만드는 방향으로」 — US 루틴이 브리프와 함께 쓰는 둘째 글.
NEWS_META = {'title': '미국 뉴스·산업 브리프 — 엔저 경계와 HBM 증설 | 2026-09-25', 'summary': '요약'}


def test_news_post_lives_under_news_with_its_own_canonical():
    out = S.render('news', '2026-09-25', NEWS_META, '<h1>엔저 경계와 HBM 증설</h1>')
    assert 'href="https://fdo2a.github.io/news/2026-09-25.html"' in out
    assert S.validate('news', '2026-09-25', NEWS_META, '<h1>a</h1>') == []


def test_news_post_reuses_the_us_stylesheet():
    assert S.css('news') == S.css('us')


def test_news_post_links_back_to_the_same_day_brief():
    out = S.render('news', '2026-09-25', NEWS_META, '<h1>a</h1>')
    assert 'href="../posts/2026-09-25.html"' in out


def test_news_post_title_format_is_its_own():
    errors = S.validate('news', '2026-09-25', {'title': '미국 증시 마감 시황 — x | 2026-09-25',
                                               'summary': 's'}, '<h1>a</h1>')
    assert any('미국 뉴스·산업 브리프' in e for e in errors)


def test_news_post_is_a_desk_document():
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from us.style import is_desk_register
    assert is_desk_register(S.render('news', '2026-09-25', NEWS_META, '<h1>a</h1>'))
