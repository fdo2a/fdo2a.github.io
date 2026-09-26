"""뉴스 자리표시 확장과 그 우회 차단."""
from us import news_expand as X
from us import style
from us.news_gate import check as news_check

SUMMARY = ('연준이 기준금리 인상을 결정했다. 시장은 추가 인상을 반영했다. 채권 금리는 상승했다. '
           '주가는 하락했다. 달러는 강세였다.')
NEWS = {'report_date': '2026-09-25', 'items': [
    {'guid': 'g1', 'source': 'CNBC', 'category': 'macro', 'url': 'https://www.cnbc.com/x',
     'published': '2026-09-25T13:00:00+00:00', 'summary_ko': SUMMARY},
    {'guid': 'g2', 'source': 'Yahoo!ニュース', 'wire': '共同通信', 'region': 'japan',
     'url': 'https://news.yahoo.co.jp/a', 'published': '2026-09-25T01:00:00+00:00',
     'summary_ko': '일본은행이 금리를 동결했습니다.'},
    {'guid': 'g3', 'source': 'x', 'url': 'https://www.boj.or.jp/en/y.pdf',
     'published': '2026-09-18T01:00:00+00:00', 'summary_ko': '결정했다.'},
]}


def test_placeholder_becomes_the_standard_block_with_the_verbatim_summary():
    out, errs = X.expand('<!--NEWS:g1|연준 인상-->', NEWS)
    assert errs == []
    assert 'data-news="g1"' in out and '연준 인상' in out and 'CNBC · 9월 25일' in out
    assert f'<p data-summary="g1">{SUMMARY}</p>' in out


def test_link_sentence_is_appended():
    out, _ = X.expand('<!--NEWS:g1|연준 인상|같은 날 2년물이 올랐다.-->', NEWS)
    assert out.count('같은 날 2년물이 올랐다.') == 1


def test_polite_summary_is_refused_and_the_placeholder_left_in_place():
    out, errs = X.expand('<!--NEWS:g2|일본은행 동결-->', NEWS)
    assert errs and '습니다' in errs[0] and '<!--NEWS:g2' in out


def test_boj_url_gets_its_korean_name():
    assert X.caption(NEWS['items'][2]) == '일본은행 · 9월 18일'


def test_unknown_guid_is_an_error():
    _, errs = X.expand('<!--NEWS:zz|제목-->', NEWS)
    assert errs and '수집분에 없는' in errs[0]


def _runs(html):
    return [f for f in style.findings(html) if '이어졌다' in str(f)]


def test_summary_paragraph_is_exempt_from_the_ending_run_check():
    out, _ = X.expand('<!--NEWS:g1|연준 인상-->', NEWS)
    wrap = '<body data-register="da"><section><h2>오늘의 뉴스</h2>{}</section></body>'
    assert not _runs(wrap.format(out))
    # 같은 문단을 작성자가 직접 쓰면(표시 없음) 「했다」 4연속으로 걸린다 — 면제가 표시에 묶여 있다.
    assert _runs(wrap.format(out.replace(' data-summary="g1"', '')))


def test_prose_hidden_under_data_summary_is_blocked_by_the_news_gate():
    fake = ('<section><h2>오늘의 뉴스</h2><div class="news-item" data-news="g1">'
            '<p class="news-head">제목</p><p data-summary="g1">작성자가 지어낸 문장이다.</p></div></section>')
    assert any('data-summary' in v for v in news_check(fake, NEWS, '2026-09-25'))
