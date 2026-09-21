"""뉴스 섹션 발행 게이트 — 실재하지 않는 기사를 막는다."""
from us.news_gate import MAX_CHARS, MIN_CHARS, check

COLLECTED = {'report_date': '2026-09-19', 'items': [
    {'guid': 'g1', 'category': 'top', 'source': 'CNBC', 'title': 'Alpha',
     'url': 'https://www.cnbc.com/2026/09/18/alpha.html', 'body_chars': 5000},
    {'guid': 'g2', 'category': 'economy', 'source': 'CNBC', 'title': 'Beta',
     'url': 'https://www.cnbc.com/2026/09/18/beta.html', 'body_chars': 4000},
    {'guid': 'g3', 'category': 'market', 'source': 'Yahoo Finance', 'title': 'Gamma',
     'url': 'https://finance.yahoo.com/news/gamma.html', 'body_chars': 0,
     'body_note': 'HTTPError'},
]}


def body(n=300):
    return '가' * n


def block(guid, chars=300, extra=''):
    return (f'<div class="news-item" data-news="{guid}">'
            f'<p class="news-head">제목 <span class="sub">CNBC</span></p>'
            f'<p>{body(chars)}</p>{extra}</div>')


def page(*blocks, title='오늘의 뉴스'):
    return ('<html><body><main>'
            '<section><h2>매크로</h2><p>앞 섹션</p></section>'
            f'<section><h2>{title}</h2><h3>주요</h3>' + ''.join(blocks) + '</section>'
            '<section><h2>AI 인프라</h2><p>뒤 섹션</p></section>'
            '</main></body></html>')


def test_a_clean_section_passes():
    assert check(page(block('g1'), block('g2')), COLLECTED) == []


# ── 지어낸 뉴스 ───────────────────────────────────────────────────────────
def test_an_item_whose_guid_was_never_collected_is_rejected():
    v = check(page(block('g1'), block('nope')), COLLECTED)
    assert any('nope' in m for m in v)


def test_the_message_names_the_offending_item_so_it_can_be_found():
    [m] = [m for m in check(page(block('ghost')), COLLECTED) if 'ghost' in m]
    assert '수집' in m


def test_an_item_with_no_marker_at_all_is_rejected():
    html = page('<div class="news-item"><p>' + body() + '</p></div>')
    assert any('data-news' in m for m in check(html, COLLECTED))


def test_the_same_article_cannot_be_printed_twice():
    v = check(page(block('g1'), block('g1')), COLLECTED)
    assert any('중복' in m for m in v)


def test_an_article_whose_body_we_failed_to_fetch_cannot_be_written_up():
    # g3 은 수집됐지만 본문을 못 받았다 — 요약할 재료가 없으므로 창작이 된다
    v = check(page(block('g3')), COLLECTED)
    assert any('본문' in m and 'g3' in m for m in v)


# ── 분량 ──────────────────────────────────────────────────────────────────
def test_a_translated_rss_blurb_is_too_short_to_pass():
    v = check(page(block('g1', chars=MIN_CHARS - 40)), COLLECTED)
    assert any('짧' in m for m in v)


def test_an_item_that_swallows_the_section_is_too_long():
    v = check(page(block('g1', chars=MAX_CHARS + 60)), COLLECTED)
    assert any('길' in m for m in v)


def test_length_counts_prose_only_not_the_headline_or_caption():
    # 제목·캡션을 길게 써서 분량을 채우는 우회를 막는다
    head = ('<p class="news-head">' + '제' * 400 + '</p>')
    html = page(f'<div class="news-item" data-news="g1">{head}'
                f'<p>{body(MIN_CHARS - 40)}</p></div>')
    assert any('짧' in m for m in check(html, COLLECTED))


def test_markup_inside_the_summary_does_not_inflate_the_count():
    inner = '<strong>' + body(MIN_CHARS + 20) + '</strong>'
    html = page(f'<div class="news-item" data-news="g1"><p>{inner}</p></div>')
    assert check(html, COLLECTED) == []


# ── 링크 규율 (source_gate 와 같은 규율) ──────────────────────────────────
def test_a_link_to_the_collected_article_is_allowed():
    extra = '<p><a href="https://www.cnbc.com/2026/09/18/alpha.html">원문</a></p>'
    assert check(page(block('g1', extra=extra)), COLLECTED) == []


def test_a_link_to_a_page_we_never_fetched_is_an_invented_citation():
    extra = '<p><a href="https://example.com/made-up">원문</a></p>'
    v = check(page(block('g1', extra=extra)), COLLECTED)
    assert any('example.com' in m for m in v)


def test_a_link_belonging_to_a_different_article_cannot_sit_in_this_block():
    extra = '<p><a href="https://www.cnbc.com/2026/09/18/beta.html">원문</a></p>'
    v = check(page(block('g1', extra=extra)), COLLECTED)
    assert any('beta' in m for m in v)


# ── 섹션 자체 ─────────────────────────────────────────────────────────────
def test_a_missing_section_is_a_violation_when_we_did_collect_news():
    html = '<html><body><section><h2>매크로</h2><p>x</p></section></body></html>'
    assert any('섹션' in m for m in check(html, COLLECTED))


def test_no_collection_means_no_obligation_the_feed_may_be_down():
    html = '<html><body><section><h2>매크로</h2><p>x</p></section></body></html>'
    assert check(html, {'report_date': '2026-09-19', 'items': []}) == []
    assert check(html, None) == []


def test_a_section_with_no_items_at_all_is_rejected():
    assert any('항목' in m for m in check(page(), COLLECTED))


def test_items_outside_the_section_are_not_counted_as_coverage():
    html = ('<html><body>'
            '<section><h2>매크로</h2>' + block('g1') + '</section>'
            '<section><h2>오늘의 뉴스</h2></section></body></html>')
    assert any('항목' in m for m in check(html, COLLECTED))


# ── 게이트가 읽는 것과 독자가 보는 것이 갈리는 자리 (2026-09-19 실측 우회) ──
def test_a_table_inside_an_item_does_not_truncate_the_block():
    # 첫 `</div>` 에서 자르면 정상 항목이 1자로 오판돼 발행이 막힌다
    inner = '<div class="tbl-scroll"><table><tr><td>x</td></tr></table></div>'
    html = page(f'<div class="news-item" data-news="g1">{inner}'
                f'<p>{body(300)}</p></div>')
    assert check(html, COLLECTED) == []


def test_nested_divs_two_deep_still_measure_the_whole_block():
    inner = '<div><div><span>x</span></div></div>'
    html = page(f'<div class="news-item" data-news="g1">{inner}'
                f'<p>{body(300)}</p></div>')
    assert check(html, COLLECTED) == []


def test_a_marker_hidden_in_a_comment_is_not_coverage():
    # 주석 블록으로 「항목 있음」을 통과시킬 수 없다 — 독자는 못 본다
    html = page(f'<!-- <div class="news-item" data-news="g1"><p>{body()}</p></div> -->')
    assert any('항목' in m for m in check(html, COLLECTED))


def test_a_commented_out_draft_does_not_raise_a_phantom_violation():
    html = page('<!-- <div data-news="ghost"><p>초안</p></div> -->', block('g1'))
    assert check(html, COLLECTED) == []


def test_a_display_none_item_is_not_coverage():
    html = page(f'<div class="news-item" data-news="g1" style="display:none">'
                f'<p>{body(300)}</p></div>')
    v = check(html, COLLECTED)
    assert any('숨' in m or '항목' in m for m in v)


def test_a_hidden_attribute_item_is_not_coverage_either():
    html = page(f'<div class="news-item" data-news="g1" hidden>'
                f'<p>{body(300)}</p></div>')
    assert check(html, COLLECTED) != []


# ── MLCC 뉴스는 다른 섹션에 있지만 같은 규율을 받는다 (2026-09-19) ──────────
MLCC_COLLECTED = {'report_date': '2026-09-19', 'items': COLLECTED['items'] + [
    {'guid': 'm1', 'category': 'mlcc', 'source': 'Yahoo Finance', 'title': 'Murata',
     'url': 'https://finance.yahoo.com/news/murata.html', 'body_chars': 3000},
]}


def mlcc_page(*blocks, news=True):
    digest = ('<section><h2>오늘의 뉴스</h2><h3>주요</h3>' + block('g1') + '</section>'
              if news else '')
    return ('<html><body><main>' + digest
            + '<section><h2>MLCC</h2>' + ''.join(blocks) + '</section>'
            + '</main></body></html>')


def test_an_mlcc_news_block_in_its_own_section_is_accepted():
    assert check(mlcc_page(block('m1')), MLCC_COLLECTED) == []


def test_an_invented_article_outside_the_digest_is_caught_too():
    v = check(mlcc_page(block('phantom')), MLCC_COLLECTED)
    assert any('phantom' in m for m in v)


def test_the_length_band_applies_outside_the_digest_as_well():
    v = check(mlcc_page(block('m1', chars=MIN_CHARS - 50)), MLCC_COLLECTED)
    assert any('짧' in m for m in v)


def test_the_same_article_cannot_appear_in_two_different_sections():
    v = check(mlcc_page(block('g1')), MLCC_COLLECTED)
    assert any('중복' in m for m in v)


def test_mlcc_items_alone_do_not_satisfy_the_digest_section():
    v = check(mlcc_page(block('m1'), news=False), MLCC_COLLECTED)
    assert any('섹션' in m for m in v)


def test_a_day_with_only_mlcc_news_owes_no_digest_section():
    only_mlcc = {'report_date': '2026-09-19',
                 'items': [MLCC_COLLECTED['items'][-1]]}
    assert check(mlcc_page(block('m1'), news=False), only_mlcc) == []


# ── codex 적대적 검토 2026-09-19: 재현된 우회로 ──────────────────────────
def test_a_day_with_no_collection_still_refuses_invented_articles():
    """#1 [치명] 수집 실패가 검사 자체를 해제했다 — 지어낸 기사가 실릴 확률이
    가장 높은 날에 게이트가 꺼졌다."""
    v = check(page(block('fake')), {'report_date': '2026-09-19', 'items': []})
    assert any('fake' in m for m in v)


def test_no_collection_and_no_news_blocks_is_still_fine():
    html = '<html><body><section><h2>매크로</h2><p>x</p></section></body></html>'
    assert check(html, {'report_date': '2026-09-19', 'items': []}) == []


def test_a_closing_div_inside_an_attribute_does_not_end_the_block():
    """#7 [중대] 속성값 안의 `</div>` 를 닫는 태그로 세어 뒤쪽 본문이 검사 밖으로."""
    html = page(f'<div class="news-item" data-news="g1"><p>{body(300)}</p>'
                f'<span title="</div>"></span>'
                f'<p><a href="https://evil.example/x">링크</a></p></div>')
    assert any('evil.example' in m for m in check(html, COLLECTED))


def test_entities_are_decoded_before_counting_length():
    """#8 [중대] `&#44032;` 40개를 320자로 셌다 — 독자가 보는 것은 40자다."""
    html = page(f'<div class="news-item" data-news="g1"><p>{"&#44032;" * 40}</p></div>')
    assert any('짧' in m for m in check(html, COLLECTED))


def test_a_valueless_hidden_attribute_is_still_hidden():
    """#6 [중대] `hidden=""` 를 정규식이 놓쳤다."""
    html = page(f'<div class="news-item" data-news="g1" hidden=""><p>{body(300)}</p></div>')
    assert check(html, COLLECTED) != []


def test_an_item_hidden_by_its_parent_is_not_coverage():
    """#6b [중대] 숨김이 부모에 있으면 독자는 못 보는데 게이트는 셌다."""
    html = page(f'<div style="display:none"><div class="news-item" data-news="g1">'
                f'<p>{body(300)}</p></div></div>')
    assert check(html, COLLECTED) != []


def test_unmarked_prose_in_the_news_section_is_caught_whatever_tag_it_uses():
    """#10 [중대] 표식 검사가 `news-item` 클래스를 자진해 붙인 div 에만 걸렸다."""
    html = page(block('g1') + f'<article><h3>조작 기사</h3><p>{body(300)}</p></article>')
    assert any('표식' in m or '밖' in m for m in check(html, COLLECTED))


def test_yesterdays_collection_cannot_justify_todays_page():
    """#11 [중대] 오늘 수집이 실패하면 어제 파일이 오늘의 근거가 됐다."""
    stale = dict(COLLECTED, report_date='2026-09-18')
    v = check(page(block('g1')), stale, report_date='2026-09-19')
    assert any('2026-09-18' in m for m in v)


def test_a_matching_report_date_passes():
    assert check(page(block('g1')), COLLECTED, report_date='2026-09-19') == []


def test_when_every_body_failed_the_section_may_be_omitted():
    """#5 [중대] 본문을 하나도 못 받은 날 축소 발행이 막혔다."""
    nobody = {'report_date': '2026-09-19', 'items': [
        {'guid': 'g1', 'category': 'top', 'url': 'https://x/a', 'body_chars': 0,
         'body_note': 'HTTPError'}]}
    html = '<html><body><section><h2>매크로</h2><p>x</p></section></body></html>'
    assert check(html, nobody) == []


# ── codex 2차 검토 2026-09-19: 정규식 파싱의 한계와 내가 만든 회귀 ──────────
def test_a_closing_section_inside_an_attribute_does_not_end_the_section():
    """2차 #1 — 속성값의 `</section>` 으로 구간이 잘려 뒤쪽 기사가 검사 밖으로."""
    html = page(block('g1') + '<span title="</section>"></span>'
                + f'<article><p>{body(300)}</p></article>')
    assert check(html, COLLECTED) != []


def test_an_unclosed_item_does_not_borrow_the_next_sections_prose():
    """2차 #3 — 닫지 않은 블록이 EOF 까지 삼켜 다음 섹션 본문으로 분량을 채웠다."""
    html = ('<html><body><section><h2>오늘의 뉴스</h2>'
            '<div class="news-item" data-news="g1"><p>가</p></section>'
            f'<section><h2>AI 인프라</h2><p>{body(300)}</p></section></body></html>')
    assert any('짧' in m for m in check(html, COLLECTED))


def test_a_fake_closing_div_inside_a_script_does_not_end_the_block():
    """2차 #4 — script 텍스트의 `</div>` 가 스택을 pop 해 뒤쪽 링크를 밀어냈다."""
    html = page(f'<div class="news-item" data-news="g1"><p>{body(300)}</p>'
                f'<script>var x = "</div>";</script>'
                f'<p><a href="https://evil.example/x">링크</a></p></div>')
    assert any('evil.example' in m for m in check(html, COLLECTED))


def test_an_item_hidden_by_a_non_div_ancestor_is_not_coverage():
    """2차 #5 — 숨김 전파가 div 에만 걸려 `<section hidden>` 을 놓쳤다."""
    html = ('<html><body><section><h2>오늘의 뉴스</h2>'
            '<section hidden>' + block('g1') + '</section></section></body></html>')
    assert check(html, COLLECTED) != []


def test_hidden_prose_inside_a_visible_item_does_not_count_toward_length():
    """2차 #5b — 보이는 블록 안에 `<p hidden>` 으로 분량을 채웠다."""
    html = page(f'<div class="news-item" data-news="g1">'
                f'<p hidden>{body(300)}</p></div>')
    assert any('짧' in m for m in check(html, COLLECTED))


def test_single_quoted_attributes_are_read_like_double_quoted_ones():
    """2차 #6 — 작은따옴표 표식을 못 읽어 빈 수집분 검사까지 우회했다."""
    html = page("<div class='news-item' data-news='ghost'><p>" + body(150) + "</p></div>")
    v = check(html, {'report_date': '2026-09-19', 'items': []})
    assert any('ghost' in m for m in v)


def test_nbsp_padding_is_not_prose():
    """2차 #7 — `&nbsp;` 300개가 300자로 계산됐다."""
    html = page(f'<div class="news-item" data-news="g1"><p>{"&nbsp;" * 300}</p></div>')
    assert any('짧' in m for m in check(html, COLLECTED))


def test_a_heading_alone_does_not_satisfy_the_length_floor():
    """2차 #8 — 항목 안 `<h3>` 300자만 있고 본문이 없어도 통과했다."""
    html = page(f'<div class="news-item" data-news="g1"><h3>{body(300)}</h3></div>')
    assert any('짧' in m for m in check(html, COLLECTED))


def test_headings_tables_and_captions_are_not_stray_prose():
    """2차 #8b — 정상 조판(분류 제목·표·캡션)을 표식 밖 산문으로 오탐했다."""
    html = page('<h3>주요</h3>' + block('g1')
                + '<div class="tbl-scroll"><table><tr><td>' + 'x' * 100
                + '</td></tr></table></div>'
                + '<p class="caption">' + '주' * 100 + '</p>')
    assert check(html, COLLECTED) == []


def test_a_collection_without_a_date_cannot_justify_a_dated_page():
    """2차 #15 — `and got` 이 날짜 미기재를 면제했다."""
    undated = {'items': COLLECTED['items']}
    v = check(page(block('g1')), undated, report_date='2026-09-19')
    assert any('날짜' in m or '수집분' in m for m in v)
