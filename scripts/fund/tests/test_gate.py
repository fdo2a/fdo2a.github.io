import copy

import pytest

from fund import gate, render
from fund.tests.test_core_render import build as build_board
from fund.tests.test_kr_view import build as build_kr
from fund import kr_view

from fund.tests.test_core_render import LAST as DATE

EARLY = '2020-01-01'    # effective date used so fixture dates count as live


@pytest.fixture
def board():
    return build_board()


def unit(board, uid):
    return next(u for u in board['units'] if u['id'] == uid)


def us_post(board, regime=None, shift=None, extra='', block=None, title='트렌드 유닛 점검'):
    semis = unit(board, 'semis')
    regime = regime if regime is not None else (
        f'<p data-fund="regime" data-regime="{board["market_regime"]["name"]}">'
        'S&amp;P 500은 강세 국면을 이어 갔다.</p>')
    shift = shift if shift is not None else (
        f'<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 3개월 '
        f'{semis["ret_3m"]:.1f}% 올라 1위를 지켰다.</p>')
    block = render.board_html(board) if block is None else block
    return ('<html><body><main><section class="sec"><h2>매크로</h2><p>x</p></section>'
            f'<section class="sec"><h2>{title}</h2>{block}{regime}{shift}{extra}</section>'
            '<section class="sec"><h2>주목 섹터·종목</h2><p>y</p></section></main></body></html>')


def check_us(html, board, post_date=DATE):
    return gate.check(html, board, 'us', post_date, effective=EARLY)


def test_clean_post_passes(board):
    assert check_us(us_post(board), board) == []


def test_before_effective_date_never_checked(board):
    assert gate.check('<p>no section</p>', board, 'us', DATE, effective='2099-01-01') == []


def test_owed_but_missing_section_fails(board):
    v = check_us('<main><section><h2>매크로</h2></section></main>', board)
    assert any('트렌드 유닛 점검' in x for x in v)


def test_unavailable_data_forbids_section(board):
    d = dict(board, status='unavailable')
    v = check_us(us_post(board), d)
    assert v and any('없어야' in x for x in v)
    assert check_us('<main><section><h2>매크로</h2></section></main>', d) == []


def test_missing_data_file_forbids_section(board):
    assert gate.check(us_post(board), None, 'us', DATE, effective=EARLY) != []
    assert gate.check('<main></main>', None, 'us', DATE, effective=EARLY) == []


def test_report_date_mismatch_means_not_owed(board):
    d = dict(board, report_date='2000-01-01')
    assert check_us('<main><section><h2>매크로</h2></section></main>', d) == []


def test_tampered_block_fails(board):
    tampered = render.board_html(board).replace('<td>', '<td data-x="1">', 1)
    assert check_us(us_post(board, block=tampered), board)


def test_duplicate_block_fails(board):
    b = render.board_html(board)
    assert check_us(us_post(board, extra=b), board)


def test_hidden_or_commented_block_fails(board):
    b = render.board_html(board)
    hidden = b.replace('<div class="fund-board"', '<div hidden class="fund-board"', 1)
    assert check_us(us_post(board, block=hidden), board)
    assert check_us(us_post(board, block=f'<!-- {b} -->'), board)


def test_block_outside_section_fails(board):
    html = us_post(board).replace('<h2>매크로</h2><p>x</p>',
                                  '<h2>매크로</h2>' + render.board_html(board), 1)
    assert check_us(html, board)


def test_regime_marker_must_match(board):
    bad = '<p data-fund="regime" data-regime="장기 약세">약세 국면이다.</p>'
    v = check_us(us_post(board, regime=bad), board)
    assert any('국면' in x for x in v)


def test_shift_numbers_must_come_from_named_units(board):
    bad = '<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 3개월 47.3% 올랐다.</p>'
    v = check_us(us_post(board, shift=bad), board)
    assert any('47.3' in x for x in v)


def test_shift_rounded_number_allowed(board):
    semis = unit(board, 'semis')
    ok = (f'<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 3개월 '
          f'{round(semis["ret_3m"]):.0f}% 올랐다.</p>')
    assert check_us(us_post(board, shift=ok), board) == []


def test_shift_unknown_unit_fails(board):
    bad = '<p data-fund="shift" data-units="crypto">코인.</p>'
    assert check_us(us_post(board, shift=bad), board)


def test_forbidden_recommendation_words(board):
    extra = '<p>반도체 비중 확대가 맞다.</p>'
    v = check_us(us_post(board, extra=extra), board)
    assert any('비중 확대' in x for x in v)


def test_net_buying_is_not_a_recommendation(board):
    extra = '<p data-fund="risk">외국인은 순매수했다.</p>'
    assert check_us(us_post(board, extra=extra), board) == []


def test_marker_outside_section_fails(board):
    html = us_post(board).replace('<p>y</p>', '<p data-fund="risk">밖</p>', 1)
    assert check_us(html, board)


# --- KR ---

def kr_post(data, observe=None):
    obs = observe if observe is not None else (
        '<p data-fund="observe" data-units="defense">우주항공과국방 업종이 3.1% 올랐다.</p>')
    return ('<main><section><h2>환율·금리</h2><p>x</p></section>'
            '<section><h2>아시아 세션 유닛 관측</h2>' + kr_view.html(data)
            + '<p data-fund="fx_cash">원/달러는 1,350.78원에서 끝났고 CD 91일물은 3.210%였다.</p>'
            + obs + '</section></main>')


def test_kr_clean_passes():
    d = build_kr()
    assert gate.check(kr_post(d), d, 'kr', '2026-10-02', effective='2026-10-01') == []


def test_kr_observe_number_must_exist():
    d = build_kr()
    bad = '<p data-fund="observe" data-units="defense">우주항공과국방 업종이 9.9% 올랐다.</p>'
    v = gate.check(kr_post(d, bad), d, 'kr', '2026-10-02', effective='2026-10-01')
    assert any('9.9' in x for x in v)


def test_hidden_section_fails(board):
    html = us_post(board).replace('<section class="sec"><h2>트렌드 유닛 점검</h2>',
                                  '<section class="sec" hidden><h2>트렌드 유닛 점검</h2>', 1)
    v = check_us(html, board)
    assert any('숨겨' in x for x in v)


def test_two_blocks_inside_section_reports_not_crashes(board):
    b = render.board_html(board)
    v = check_us(us_post(board, block=b + b), board)
    assert any('정확히 하나' in x for x in v)


def test_hidden_wrapper_inside_section_fails(board):
    b = render.board_html(board)
    v = check_us(us_post(board, block=f'<div style="display: none">{b}</div>'), board)
    assert any('숨겨' in x for x in v)


# --- codex 구현 검토 1차 재현 (2026-10-06) ---

def test_markers_on_non_paragraph_tags_are_rejected(board):
    html = us_post(board,
                   regime='<div data-fund="regime" data-regime="장기 약세">약세다.</div>',
                   shift='<div data-fund="shift" data-units="crypto">12345%다.</div>')
    assert check_us(html, board)


@pytest.mark.parametrize('wrap', [
    lambda h, b: h.replace('<main>', '<main hidden>', 1),
    lambda h, b: h.replace(b, '<template>' + b + '</template>', 1),
    lambda h, b: h.replace(b, '<details>' + b + '</details>', 1),
    lambda h, b: h.replace('<html>', '<html><body style="display:none">', 1),
])
def test_block_hidden_by_any_ancestor_fails(board, wrap):
    b = render.board_html(board)
    v = check_us(wrap(us_post(board), b), board)
    assert any('숨겨' in x or '보이' in x for x in v), v


def test_open_details_is_visible(board):
    b = render.board_html(board)
    html = us_post(board).replace(b, '<details open><summary>표</summary>' + b + '</details>', 1)
    assert check_us(html, board) == []


def test_flipped_sign_fails(board):
    semis = unit(board, 'semis')
    bad = (f'<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 3개월 '
           f'{-semis["ret_3m"]:+.1f}%를 기록했다.</p>')
    assert check_us(us_post(board, shift=bad), board)


def test_unsigned_magnitude_with_direction_word_passes(board):
    semis = unit(board, 'semis')
    ok = (f'<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 3개월 '
          f'{abs(semis["ret_3m"]):.1f}% 움직였다.</p>')
    assert check_us(us_post(board, shift=ok), board) == []


def test_percent_value_written_as_points_fails(board):
    semis = unit(board, 'semis')
    bad = (f'<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 '
           f'{semis["ret_3m"]:.1f}%p 앞섰다.</p>')
    assert check_us(us_post(board, shift=bad), board)


def test_entities_do_not_hide_numbers_or_words(board):
    bad = '<p data-fund="shift" data-units="semis">반도체 999&#37; 올랐다.</p>'
    assert check_us(us_post(board, shift=bad), board)
    extra = '<p>반도체를 매수&#54616;라.</p>'
    assert any('매수' in x for x in check_us(us_post(board, extra=extra), board))


@pytest.mark.parametrize('phrase', ['반도체 매수를 권한다.', '반도체를 매수해야 한다.',
                                    '반도체는 매도하는 편이 낫다.', '비중을 늘려야 한다.'])
def test_recommendation_forms_fail(board, phrase):
    assert check_us(us_post(board, extra=f'<p>{phrase}</p>'), board)


@pytest.mark.parametrize('phrase', ['외국인은 순매수했다.', '매수세가 몰렸다.', '순매도가 이어졌다.'])
def test_observational_trading_words_pass(board, phrase):
    assert check_us(us_post(board, extra=f'<p data-fund="risk">{phrase}</p>'), board) == []


def test_missing_regime_day_uses_undetermined_marker(board):
    d = dict(board, market_regime=None, status='partial')
    ok = '<p data-fund="regime" data-regime="미판정">국면을 가를 이력이 부족하다.</p>'
    assert check_us(us_post(d, regime=ok), d) == []
    # but 미판정 is not accepted when a regime exists
    assert check_us(us_post(board, regime=ok), board)


def test_risk_paragraph_numbers_are_checked(board):
    bad = '<p data-fund="risk">하이일드 스프레드가 5거래일 99bp 넓어졌다.</p>'
    assert check_us(us_post(board, extra=bad), board)
    ok = '<p data-fund="risk">하이일드 스프레드가 5거래일 39bp 넓어졌다.</p>'
    assert check_us(us_post(board, extra=ok), board) == []


# --- codex 구현 재검토 재현: DOM 해석 차이 ---

def test_duplicate_attributes_are_rejected(board):
    html = us_post(board).replace('<main>', '<main style="display:none" style="">', 1)
    assert check_us(html, board)


@pytest.mark.parametrize('tag', ['textarea', 'xmp', 'select', 'noscript', 'script', 'title'])
def test_block_inside_non_display_container_fails(board, tag):
    b = render.board_html(board)
    assert check_us(us_post(board, block=f'<{tag}>{b}</{tag}>'), board)


def test_self_closing_non_void_tag_still_wraps(board):
    html = us_post(board).replace('<main>', '<main hidden/>', 1)
    assert check_us(html, board)


def test_block_level_child_closes_the_marker_paragraph(board):
    bad = '<p data-fund="shift" data-units="semis"><div>움직였다.</div></p>'
    assert any('비어' in x for x in check_us(us_post(board, shift=bad), board))


def test_hidden_child_text_does_not_count(board):
    bad = '<p data-fund="shift" data-units="semis"><span hidden>움직였다.</span></p>'
    assert any('비어' in x for x in check_us(us_post(board, shift=bad), board))


@pytest.mark.parametrize('fig', ['.5%', '− 13.4%', '- 13.4%', '－13.4%'])
def test_odd_number_forms_are_checked(board, fig):
    semis = unit(board, 'semis')
    assert semis['ret_3m'] > 0
    bad = f'<p data-fund="shift" data-units="semis">반도체·AI 하드웨어는 {fig} 움직였다.</p>'
    assert check_us(us_post(board, shift=bad), board), fig


def test_rank_change_keeps_its_sign(board):
    d = copy.deepcopy(board)
    u = next(x for x in d['units'] if x['id'] == 'semis')
    u.update(rank=20, rank_5d=12, rank_chg=-8)
    good = '<p data-fund="shift" data-units="semis">반도체는 순위가 -8위 바뀌었다.</p>'
    bad = '<p data-fund="shift" data-units="semis">반도체는 순위가 +8위 바뀌었다.</p>'
    d_html = lambda p: us_post(d, shift=p)
    assert check_us(d_html(good), d) == []
    assert check_us(d_html(bad), d)


@pytest.mark.parametrize('phrase', ['반도체 매수가 바람직하다.', '반도체 매도를 제안한다.',
                                    '반도체를 사라.', '지금이 매수 적기다.', '반도체를 팔아라.'])
def test_more_recommendation_forms_fail(board, phrase):
    assert check_us(us_post(board, extra=f'<p>{phrase}</p>'), board), phrase


def test_disappear_is_not_buy(board):
    assert check_us(us_post(board, extra='<p data-fund="risk">하락 압력이 사라졌다.</p>'), board) == []


def test_duplicate_attribute_elsewhere_in_the_document_is_not_our_business(board):
    html = us_post(board).replace('<h2>주목 섹터·종목</h2><p>y</p>',
                                  '<h2>주목 섹터·종목</h2><p class="a" class="b">y</p>', 1)
    assert check_us(html, board) == []


def test_self_closing_svg_does_not_hide_what_follows(board):
    html = us_post(board).replace('<main>', '<main><svg/>', 1)
    assert check_us(html, board) == []


def test_void_duplicate_attribute_inside_section_fails(board):
    assert check_us(us_post(board, extra='<img src="x" src="y">'), board)
