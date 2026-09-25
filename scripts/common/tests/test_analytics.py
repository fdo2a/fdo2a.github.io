"""Visit counter loader — one rule places it, and every visitor page has it."""
import subprocess
from pathlib import Path

from scripts.common import analytics as A
from scripts.common import post_shell as S

ROOT = Path(__file__).resolve().parents[3]

PAGE = '<!DOCTYPE html>\n<html><head>\n<title>t</title>\n</head>\n<body><p>본문</p></body></html>\n'


def test_goes_right_before_head_close():
    out = A.inject(PAGE)
    assert out == PAGE.replace('</head>', A.SNIPPET + '\n</head>')
    assert out.count(A.MARKER) == 1


def test_idempotent():
    once = A.inject(PAGE)
    assert A.inject(once) == once


def test_first_head_close_only_and_case_insensitive():
    page = '<HTML><HEAD><title>x</title></HEAD><body>&lt;/head&gt;</body></HTML>'
    assert A.inject(page) == page.replace('</HEAD>', A.SNIPPET + '\n</HEAD>', 1)


def test_headless_early_post_gets_it_after_the_ad_loader():
    """2026-07 초기 글 셋은 <head> 래퍼가 없다 — 광고 로더 바로 뒤에 붙는다."""
    ad = ('<!-- adsense-loader -->\n<script async src="https://pagead2.googlesyndication.com'
          '/pagead/js/adsbygoogle.js?client=ca-pub-1" crossorigin="anonymous"></script>')
    page = '<!-- article-schema -->\n' + ad + '\n<style>p{}</style>\n<p>본문</p>'
    assert A.inject(page) == page.replace(ad, ad + '\n' + A.SNIPPET)


def test_fragment_without_anchor_is_left_alone():
    frag = '<section><p>조각</p></section>'
    assert A.inject(frag) == frag


def test_verify_post_sees_no_change():
    """소급 삽입 뒤 `verify_post.py` 가 수치·태그 구조 변화를 보고하지 않는다."""
    from scripts.us.post_check import markup_diff, report
    page = PAGE.replace('본문', '코스피 2.1% 상승, 3,120.45')
    assert report(page, A.inject(page)) == []
    assert markup_diff(page, A.inject(page)) == []


def test_is_page():
    assert A.is_page('index.html')
    assert A.is_page('kr/posts/2026-09-24.html')
    assert A.is_page('thesis/micron.html')
    assert not A.is_page('kr/data/section.html')
    assert not A.is_page('scripts/kr/tests/fixtures/a.html')
    assert not A.is_page('docs/x.html')
    assert not A.is_page('posts.json')


def test_post_shell_places_it_where_inject_would():
    html = S.render('us', '2026-09-23', {'title': '미국 증시 마감 시황 — 테스트 | 2026-09-23',
                                          'summary': '요약.'},
                    '<div class="card"><h1>헤드라인</h1><p>본문</p></div>')
    assert html.count(A.MARKER) == 1
    assert A.inject(html.replace(A.SNIPPET + '\n', '')) == html


def test_every_tracked_visitor_page_has_it():
    """새 페이지 생성기가 로더를 빠뜨리면 여기서 걸린다 — `inject_analytics.py` 로 고친다."""
    out = subprocess.run(['git', 'ls-files', '-z', '*.html'], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    pages = [rel for rel in out.split('\0') if rel and A.is_page(rel)]
    assert len(pages) > 100
    missing = [rel for rel in pages
               if (ROOT / rel).exists()
               and (ROOT / rel).read_text(encoding='utf-8').count(A.MARKER) != 1]
    assert missing == []
