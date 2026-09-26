"""일본 주간 게이트."""
from japan import gate as G
from japan.render import SECTIONS

BOX = "<p data-interp>금리가 오르는데 신용이 조용하다는 조합은 시장이 강한 지표를 할인율 상승으로만 받아들이고 이익 전망은 건드리지 않았다는 뜻이다. 금리가 오르는데 신용이 조용하다는 조합은 시장이 강한 지표를 할인율 상승으로만 받아들이고 이익 전망은 건드리지 않았다는 뜻이다. 금리가 오르는데 신용이 조용하다는 조합은 시장이 강한 지표를 할인율 상승으로만 받아들이고 이익 전망은 건드리지 않았다는 뜻이다. </p>"


def _diag(**over):
    d = {'flows': {'res_foreign_ltdebt_word': '순매도', 'res_foreign_ltdebt_4w_word': '순매수',
                   'nonres_jp_equity_word': '순매도', 'nonres_jp_equity_4w': -1550,
                   'res_foreign_ltdebt_net': -200, 'res_foreign_ltdebt_4w': 500},
         'positioning': {'date': '2026-09-15', 'lev_net': 10},
         'next_events': [{'date': '2026-10-01', 'name_ko': '단칸(9월 조사)'}],
         'fetch_status': {}}
    d.update(over)
    return d


def _html(**prose):
    base = {s: '해설이다.' for s in SECTIONS}
    base['scenario'] = '인상 지속 신호가 둘, 인상 중단 신호가 하나다.'
    base['next'] = '단칸이 가를 것이다.'
    base['yen'] = '2026-09-15 기준 엔 선물 포지션은 엔 매수 쪽이다.'
    base.update(prose)
    secs = ''.join(f'<section data-section="{s}"><h2>{s}</h2><p>{base[s]}</p>'
                   f'{BOX if s in G.COMMENTARY_SECTIONS else ""}</section>' for s in SECTIONS)
    return f'<body data-register="da"><section class="card headline-card"><h1>제목</h1></section>{secs}</body>'


def test_clean_draft_passes():
    assert G.check(_html(), _diag()) == []


def test_bond_direction_word_must_match_the_data():
    out = G.check(_html(flows='이번 주 거주자는 해외채권을 순매수했다.'), _diag())
    assert any('해외채권' in v for v in out)


def test_four_week_sentence_is_checked_against_the_four_week_sum():
    assert G.check(_html(flows='4주 합계로는 해외 중장기채를 순매수했다.'), _diag()) == []
    out = G.check(_html(flows='4주 합계로는 해외 중장기채를 순매도했다.'), _diag())
    assert out


def test_hedge_paragraph_needs_the_approximation_label():
    out = G.check(_html(flows='헤지 후 미 국채가 JGB 보다 낮다.'), _diag())
    assert any('근사' in v for v in out)
    assert G.check(_html(flows='근사로 본 헤지 후 미 국채가 JGB 보다 낮다.'), _diag()) == []


def test_positioning_without_its_tuesday_date_is_blocked():
    out = G.check(_html(yen='CFTC 엔 선물 포지션은 엔 매수 쪽이다.'), _diag())
    assert any('기준일' in v for v in out)


def test_scenario_must_name_both_branches():
    out = G.check(_html(scenario='인상 지속 쪽으로 기울었다.'), _diag())
    assert any('인상 중단' in v for v in out)


def test_invented_number_is_blocked_but_a_news_number_is_allowed():
    out = G.check(_html(boj='물가가 3.7% 올랐다.'), _diag())
    assert any('3.7' in v for v in out)
    assert G.check(_html(boj='물가가 3.7% 올랐다.'), _diag(), news_texts=['CPI 3.7% 상승']) == []


def test_failed_source_blocks():
    out = G.check(_html(), _diag(fetch_status={'mof:week': 'error: 403'}))
    assert any('mof:week' in v for v in out)


def test_missing_section_is_named():
    html = _html().replace('data-section="equity"', 'data-section="x"')
    assert any('equity' in v for v in G.check(html, _diag()))


def test_korean_jo_eok_amounts_are_read_as_one_number():
    # 「1조 6,065억 엔」은 16,065억 엔이다. 쪼개 읽으면 6065 가 창작으로 걸린다.
    d = _diag(flows={**_diag()['flows'], 'res_foreign_ltdebt_4w': -16065,
                     'res_foreign_ltdebt_4w_word': '순매도'})
    assert G.check(_html(flows='4주 합계로 해외 중장기채를 1조 6,065억 엔 순매도했다.'), d) == []


def test_korean_dates_and_week_keys_are_not_figures():
    html = _html(boj='9월 회의(9월 17~18일)의 의견 요약은 10월 1일에 나온다.').replace(
        '<h1>제목</h1>', '<h1>제목</h1><p>2026-W39</p>')
    assert G.check(html, _diag()) == []


def test_analysis_sections_need_a_commentary_box():
    html = _html()
    i = html.index('data-section="flows"')
    j = html.index('</section>', i)
    out = G.check(html[:i] + html[i:j].replace(BOX, '') + html[j:], _diag())
    assert any('flows' in v and '해석' in v for v in out)
