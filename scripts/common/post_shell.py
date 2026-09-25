"""Post shell — the part of a daily brief that is the same every day.

Writers used to hand-write the whole document: head, SEO meta, JSON-LD, AdSense loader,
~6 KB of CSS, top bar. The orchestrator then hand-injected the nav block and the SEO
meta a second time. Every day that cost output tokens and a long CSS spec in the
writer prompt, and it produced defects no gate looked at — the 2026-09-23 US post
carried description, canonical and og tags twice, and US CSS drifted across 125
selectors in 20 posts. This module renders all of it from two writer inputs:

    meta  {"title": SEO <title>, "summary": 1–2 sentence og/JSON-LD description}
    body  the sections that go inside <div class="doc"> (headline card with the one <h1>)

Everything else is derived: og:title from the date, meta description from the <h1>,
canonical/og:url from market + date, CSS from `post_css/<market>.css`.

Pure. CLI: scripts/render_post.py.

Design: docs/superpowers/specs/2026-09-24-post-shell.md
"""

import html as _html
import json
import re
from datetime import date as _date, timedelta
from pathlib import Path

from scripts.common.analytics import SNIPPET as ANALYTICS

CSS_DIR = Path(__file__).resolve().parent / 'post_css'
MARKER = '<!-- post-shell-v1 -->'
ADSENSE = ('<!-- adsense-loader --><script async src="https://pagead2.googlesyndication.com'
           '/pagead/js/adsbygoogle.js?client=ca-pub-9240461016907498" '
           'crossorigin="anonymous"></script>')
WEEKDAYS = '월화수목금토일'

_PILL = ('text-decoration:none;background:#fff;border:1px solid #E5E8EB;border-radius:9999px;'
         'padding:6px 14px;font-size:12px;font-weight:700;color:#191F28;')
_HOME = 'text-decoration:none;font-size:14px;font-weight:800;color:#0064FF;letter-spacing:-0.02em;'
_NAV_OPEN = ('<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;display:flex;'
             'align-items:center;gap:10px;">')

MARKETS = {
    'us': {
        'brand': 'US Market Brief', 'site': 'https://fdo2a.github.io/', 'dir': 'posts',
        'og': '미국 증시 모닝브리프', 'title_prefix': '미국 증시 마감 시황 — ',
        # Published the next morning KST, after the US close.
        'published_offset': 1,
        'extra_nav': '',
    },
    'kr': {
        'brand': 'KR Market Brief', 'site': 'https://fdo2a.github.io/kr/', 'dir': 'kr/posts',
        'og': '한국 증시 마감브리프', 'title_prefix': '코스피 마감 시황 — ',
        'published_offset': 0,
        'extra_nav': ('\n  <a href="../../index.html" style="text-decoration:none;font-size:12px;'
                      'font-weight:700;color:#8B95A1;margin-left:auto;">🇺🇸 미국 시장 →</a>'),
    },
    # 뉴스·산업 브리프(2026-09-26) — US 루틴이 브리프와 함께 쓰는 둘째 글. 오늘의 뉴스·메모리/DRAM·
    # AI 인프라·MLCC 가 브리프에서 여기로 옮겨 왔다. 조판은 US 와 같다(`css` 키).
    'news': {
        'brand': 'US News & Industry', 'site': 'https://fdo2a.github.io/', 'dir': 'news',
        'og': '미국 뉴스·산업 브리프', 'title_prefix': '미국 뉴스·산업 브리프 — ',
        'published_offset': 1, 'css': 'us', 'topbar': 'us',
        # 같은 날 브리프로 돌아가는 길. 브리프가 먼저 발행되므로 링크가 끊기지 않는다.
        'extra_nav': ('\n  <a href="../posts/{date}.html" style="text-decoration:none;font-size:12px;'
                      'font-weight:700;color:#8B95A1;margin-left:auto;">같은 날 시황 브리프 →</a>'),
    },
}

_FORBIDDEN = (('<!doctype', 'DOCTYPE'), ('<html', '<html>'), ('<head', '<head>'),
              ('<body', '<body>'))
_DOC_DIV = re.compile(r'<div\b[^>]*class=["\'][^"\']*\bdoc\b', re.I)
_H1 = re.compile(r'<h1\b[^>]*>(.*?)</h1>', re.S | re.I)
_STYLE = re.compile(r'<style\b[^>]*>(.*?)</style>', re.S | re.I)
_RULE = re.compile(r'([^{}]+)\{(?:[^{}]|\{[^{}]*\})*\}')
_TAG = re.compile(r'<[^>]+>')


def escape(text):
    return _html.escape(text, quote=True)


def unescape(text):
    return _html.unescape(text)


def plain(fragment):
    return re.sub(r'\s+', ' ', unescape(_TAG.sub('', fragment))).strip()


def css(market):
    name = MARKETS.get(market, {}).get('css', market)
    return (CSS_DIR / f'{name}.css').read_text(encoding='utf-8')


def _selectors(stylesheet):
    out = set()
    text = re.sub(r'/\*.*?\*/', '', stylesheet, flags=re.S)
    for match in _RULE.finditer(text):
        head = match.group(1).strip()
        if head.startswith('@'):
            inner = match.group(0)[match.group(0).index('{') + 1:-1]
            out |= _selectors(inner)
        else:
            out |= {' '.join(s.split()) for s in head.split(',') if s.strip()}
    return out


def _long_date(day):
    return f'{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]}요일)'


def validate(market, date, meta, body):
    """Everything wrong with the writer's inputs, as sentences. Empty means renderable."""
    errors = []
    if market not in MARKETS:
        return [f'market 은 {"·".join(MARKETS)} 중 하나다 ({market!r})']
    cfg = MARKETS[market]
    try:
        _date.fromisoformat(date)
    except (TypeError, ValueError):
        errors.append(f'date 는 YYYY-MM-DD 다 ({date!r})')
    title = (meta or {}).get('title') or ''
    if not (title.startswith(cfg['title_prefix']) and title.endswith(f' | {date}')
            and len(title) > len(cfg['title_prefix']) + len(date) + 3):
        errors.append(f'meta.title 은 「{cfg["title_prefix"]}[핵심구] | {date}」 형식이다 '
                      f'({title!r})')
    if not ((meta or {}).get('summary') or '').strip():
        errors.append('meta.summary 가 비었다 — og:description·JSON-LD 설명이 된다')
    low = body.lower()
    for needle, name in _FORBIDDEN:
        if needle in low:
            errors.append(f'본문에 {name} 가 있다 — 셸이 만든다. 섹션만 쓴다')
    if _DOC_DIV.search(body):
        errors.append('본문에 <div class="doc"> 가 있다 — 셸이 감싼다')
    n = len(_H1.findall(body))
    if n != 1:
        errors.append(f'<h1> 은 헤드라인 카드에 정확히 하나다 (지금 {n}개)')
    base = _selectors(css(market))
    for block in _STYLE.findall(body):
        clash = sorted(_selectors(block) & base)
        if clash:
            errors.append('본문 <style> 이 템플릿 선택자를 다시 정의한다: '
                          + ', '.join(clash[:6]) + ' — 조판은 템플릿 몫이다')
    return errors


def render(market, date, meta, body):
    """The complete document. Call `validate` first; this does not re-check."""
    cfg = MARKETS[market]
    day = _date.fromisoformat(date)
    url = f'https://fdo2a.github.io/{cfg["dir"]}/{date}.html'
    og_title = f'{cfg["og"]} — {_long_date(day)}'
    h1 = plain(_H1.search(body).group(1))
    description = f'{h1}. {date} {cfg["og"]}.'
    summary = meta['summary'].strip()
    published = (day + timedelta(days=cfg['published_offset'])).isoformat()
    ld = {'@context': 'https://schema.org', '@type': 'NewsArticle', 'headline': og_title,
          'description': summary, 'datePublished': published, 'dateModified': published,
          'author': {'@type': 'Organization', 'name': cfg['brand'], 'url': cfg['site']},
          'publisher': {'@type': 'Organization', 'name': cfg['brand'], 'url': cfg['site']},
          'mainEntityOfPage': url, 'inLanguage': 'ko'}
    # `</` inside a JSON string would close the <script> element early.
    ld_text = json.dumps(ld, ensure_ascii=False).replace('</', '<\\/')
    if cfg.get('topbar', market) == 'us':
        topbar = (f'<span class="brand">{cfg["brand"]}</span> · {day.year}년 {day.month}월 '
                  f'{day.day}일({WEEKDAYS[day.weekday()]}) 마감 기준')
    else:
        topbar = (f'<span class="brand">{cfg["brand"]}</span>'
                  f'<span class="date">{_long_date(day)} 마감</span>')
    nav = (f'{_NAV_OPEN}\n  <a href="../index.html" style="{_PILL}">‹ 전체 보고서</a>\n'
           f'  <a href="../index.html" style="{_HOME}">{cfg["brand"]}</a>'
           f'{cfg["extra_nav"].replace("{date}", date)}\n'
           '</div>')
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="description" content="{escape(description)}">\n'
        f'<link rel="canonical" href="{url}">\n'
        '<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{escape(og_title)}">\n'
        f'<meta property="og:url" content="{url}">\n'
        f'<meta property="og:description" content="{escape(summary)}">\n'
        f'<title>{escape(meta["title"].strip())}</title>\n'
        f'<script type="application/ld+json">\n{ld_text}\n</script>\n'
        f'{ADSENSE}\n{MARKER}\n<style>\n{css(market)}</style>\n{ANALYTICS}\n</head>\n'
        # US·KR 일간은 PM 이 읽는 -다 문서다 — check_style 이 이 선언을 보고 데스크 검사를 건다.
        f'<body data-register="da">\n<div class="topbar">{topbar}</div>\n{nav}\n'
        f'<div class="doc">{body}</div>\n</body>\n</html>\n'
    )
