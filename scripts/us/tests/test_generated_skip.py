"""공용 모듈의 「코드 생성 문장 건너뛰기」(일본 일간 v2, 2026-11-19)는 US·KR 글에서 아무것도 바꾸지 않는다.

건너뛰는 것은 일본 일간 문서(canonical /japan/daily/)의 `<p data-gen="topix|sectors|curve">` 뿐이고, 그 문서는
`japan/daily_gate.verify_generated` 가 바이트 대조를 따로 한다. 다른 문서에 같은 표식을 달아도 건너뛰지 않는다.
"""
import glob
import os

import pytest

from common import telegram_gate as TG
from us import readability as RD
from us import style as ST

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
POSTS = sorted(glob.glob(os.path.join(ROOT, 'posts', '2026-11-1*.html')))[-3:] + \
    sorted(glob.glob(os.path.join(ROOT, 'kr', 'posts', '2026-11-1*.html')))[-3:]


@pytest.mark.parametrize('path', POSTS, ids=os.path.basename)
def test_us_kr_posts_have_nothing_to_skip(path):
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    assert ST.generated_elements(html) == [] and ST.drop_generated(html) == html


@pytest.mark.parametrize('path', POSTS, ids=os.path.basename)
def test_us_kr_outputs_identical_with_skip_disabled(path, monkeypatch):
    """건너뛰기를 끈(항등) 판과 결과가 같다 — 조판·문체·읽기 쉬움 셋 다."""
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    got = (RD.enhance_html(html), ST.findings(html), RD.measure(html))
    monkeypatch.setattr(ST, 'drop_generated', lambda h: h)
    monkeypatch.setattr(ST, 'generated_elements', lambda h: [])
    monkeypatch.setattr(RD, 'drop_generated', lambda h: h)
    monkeypatch.setattr(RD, 'generated_elements', lambda h: [])
    assert (RD.enhance_html(html), ST.findings(html), RD.measure(html)) == got


def _doc(canonical, extra):
    return (f'<!DOCTYPE html><html><head><link rel="canonical" href="{canonical}"></head>'
            f'<body data-register="da"><section class="card"><p>시장은 약했다.</p>{extra}</section></body></html>')


BAD = '<p data-gen="topix">시장이 약했습니다. 매수가 몰렸습니다. 지수가 내렸습니다.</p>'


def test_marker_outside_japan_daily_is_not_skipped():
    us = _doc('https://fdo2a.github.io/posts/2026-11-18.html', BAD)
    jp = _doc('https://fdo2a.github.io/japan/daily/2026-11-18.html', BAD)
    assert ST.generated_elements(us) == [] and ST.generated_elements(jp) == [BAD]
    assert ST.findings(us) != ST.findings(_doc('https://fdo2a.github.io/posts/2026-11-18.html', ''))
    assert ST.findings(jp) == ST.findings(_doc('https://fdo2a.github.io/japan/daily/2026-11-18.html', ''))
    assert any('습니다' in p for p in RD.paragraphs(us)) and not any('습니다' in p for p in RD.paragraphs(jp))


def test_only_the_exact_generated_shape_is_skipped():
    for el in ('<p data-gen="other">시장이 약했습니다.</p>', '<p class="x" data-gen="topix">약했습니다.</p>',
               '<p data-gen="topix">약했습니다.<b>x</b></p>'):
        jp = _doc('https://fdo2a.github.io/japan/daily/2026-11-18.html', el)
        assert ST.generated_elements(jp) == []


def test_typesetting_keeps_generated_bytes_and_numbers():
    el = '<p data-gen="curve">2~10년 금리 스프레드는 100.9bp로 전 거래일 대비 0.1bp 축소됐다.</p>'
    jp = _doc('https://fdo2a.github.io/japan/daily/2026-11-18.html', el)
    out = RD.enhance_html(jp)
    assert out.count(el) == 1 and 'gen-keep' not in out


def test_telegram_skip_empty_is_old_behaviour():
    html = _doc('https://fdo2a.github.io/posts/2026-11-18.html', '<p>일본은행이 12월 회의에서 금리를 올릴 가능성이 커졌다는 시각이 나왔다.</p>')
    data = {'items': [{'id': 'c/1', 'kind': 'opinion', 'summary_ko': '일본은행이 12월 회의에서 금리를 올릴 가능성이 커졌다는 시각이 나왔다.'}]}
    w1, w2 = [], []
    assert TG.check(html, data, warnings=w1) == TG.check(html, data, warnings=w2, skip=())
    assert w1 == w2 and w1                       # 겹침 경고가 그대로 난다
    w3 = []
    TG.check(html, data, warnings=w3, skip=('<p>일본은행이 12월 회의에서 금리를 올릴 가능성이 커졌다는 시각이 나왔다.</p>',))
    assert w3 == []                              # 호출자가 넘긴 조각만 빠진다
