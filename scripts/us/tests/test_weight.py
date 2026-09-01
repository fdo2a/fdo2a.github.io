from us.weight import (THRESHOLDS, check_volume, measure, prose_chars,  # noqa: F401
                       section_slice)

DOC = '''<h1>주식이 오른 하루</h1>
<section><h2>주식</h2><p>본문 열두 글자입니다</p>
<p class="caption">캡션은 세지 않는다</p>
<table><tr><td>짧은칸</td><td>이것은 마흔 글자를 넘기는 서술형 칸이라서 자수에 포함되어야 마땅한 칸이다</td></tr></table>
</section>
<section><h2>채권</h2><p>AT&amp;T</p></section>'''


def test_section_slice_uses_h2_not_headline():
    seg = section_slice(DOC, '주식')
    assert '본문 열두 글자입니다' in seg
    assert '오른 하루' not in seg


def test_section_slice_returns_none_when_absent():
    assert section_slice(DOC, '원자재') is None


def test_prose_chars_counts_paragraphs_and_long_cells_only():
    n = prose_chars(section_slice(DOC, '주식'))
    assert n == len('본문 열두 글자입니다') + len(
        '이것은 마흔 글자를 넘기는 서술형 칸이라서 자수에 포함되어야 마땅한 칸이다')


def test_prose_chars_decodes_entities():
    assert prose_chars(section_slice(DOC, '채권')) == len('AT&T')


def _doc(sizes):
    return '\n'.join(f'<section><h2>{t}</h2><p>{"가" * n}</p></section>'
                     for t, n in sizes.items())


US_FULL = {'오늘의 장': 800, '주식': 1900, '채권': 2000, 'FX': 650, '원자재': 750,
           '전략 코멘트': 400, '매크로 논리': 4400, '멀티에셋 매니저 전략': 2200}


def test_measure_groups_and_ratio():
    m = measure(_doc(US_FULL), 'us')
    assert m['recap'] == 800 + 1900 + 2000 + 650 + 750
    assert m['judgment'] == 400 + 4400 + 2200
    assert round(m['ratio'], 3) == round(m['recap'] / m['judgment'], 3)
    assert m['missing'] == []


def test_missing_section_is_a_violation_not_a_pass():
    doc = _doc({k: v for k, v in US_FULL.items() if k != '채권'})
    m = measure(doc, 'us')
    assert '채권' in m['missing']
    assert any('채권' in x for x in check_volume(m, market='us'))


def test_full_day_passes_thresholds():
    assert check_volume(measure(_doc(US_FULL), 'us'), False, 'us') == []


def test_measured_2026_08_27_shape_is_blocked():
    sizes = {'오늘의 장': 0, '주식': 1278, '채권': 1581, 'FX': 360, '원자재': 457,
             '전략 코멘트': 392, '매크로 논리': 4788, '멀티에셋 매니저 전략': 2244}
    v = check_volume(measure(_doc(sizes), 'us'), False, 'us')
    assert any('비율' in x or '÷' in x for x in v)
    assert any('매크로 논리' in x for x in v)


def test_abbreviated_day_caps_macro_and_raises_ratio_floor():
    v = check_volume(measure(_doc(US_FULL), 'us'), True, 'us')
    assert any('매크로 논리' in x and '2400' in x for x in v)
    ok = dict(US_FULL, **{'매크로 논리': 2000})
    assert check_volume(measure(_doc(ok), 'us'), True, 'us') == []


def test_deleting_judgment_to_game_the_ratio_is_blocked():
    sizes = dict(US_FULL, **{'매크로 논리': 500})
    v = check_volume(measure(_doc(sizes), 'us'), False, 'us')
    assert any('매크로 논리' in x and '3000' in x for x in v)


def test_kr_has_floor_but_no_ratio():
    sizes = {'오늘의 장': 700, '지수 & 장중': 900, '환율·금리': 700,
             '전략 코멘트': 700, '기술적 분석 & 트레이딩 전략': 500}
    assert check_volume(measure(_doc(sizes), 'kr'), market='kr') == []
    thin = dict(sizes, **{'지수 & 장중': 300})
    assert any('시황·가격군' in x
               for x in check_volume(measure(_doc(thin), 'kr'), market='kr'))


# --- 「지금 어디에 있나」·원인 문단 (설계 1-b) ---

from us.weight import (check, check_cause, check_lede,  # noqa: E402
                       check_macro_prices, check_position_vocab, check_standing)

PC = {
    'levels': {'S&P 500': {'value': 7730.99, 'percentile': 98.6, 'band': '매우 높음',
                           'sessions': 504},
               '30Y': {'value': 5.191, 'percentile': 96.8, 'band': '매우 높음',
                       'sessions': 504}},
    'moves': {'S&P 500': {'change': 0.72, 'multiple': 0.84, 'band': '보통'},
              'Gold': {'change': 3.4, 'multiple': 2.6, 'band': '큼'},
              '30Y': {'change': 0.005, 'multiple': 0.14, 'band': '미미'}},
}

GOOD_STANDING = ('<p data-standing="equities">S&P 500은 7,730으로 최근 2년 가운데 거의 '
                 '꼭대기(위에서 1.4% 안)에 있습니다. 7월 말 조정을 되돌린 뒤 한 달째 이 '
                 '언저리에서 옆걸음이고, 오늘 0.72% 상승은 평소 하루 폭의 0.8배라 방향을 '
                 '새로 잡은 하루는 아니었습니다.</p>')

MD = {'indices': [{'name': 'S&P 500', 'close': 7730.99, 'change_pct': 0.72}],
      'fx': [{'name': 'DXY', 'close': 99.114, 'change_pct': -0.056}]}


def _sec(title, inner):
    return f'<section><h2>{title}</h2>{inner}</section>'


def test_missing_standing_paragraph_is_a_violation():
    doc = _sec('주식', '<p>나스닥은 09:30 저점을 찍었습니다.</p>')
    assert any('주식' in x and 'data-standing' in x for x in check_standing(doc, PC))


def test_standing_paragraph_must_be_substantive():
    doc = _sec('주식', '<p data-standing="equities">주식은 높습니다.</p>')
    assert any('120자' in x for x in check_standing(doc, PC))


def test_good_standing_paragraph_passes():
    assert check_standing(_sec('주식', GOOD_STANDING), PC) == []


def test_big_mover_needs_a_cause_paragraph():
    doc = _sec('원자재', '<p>금이 크게 올랐습니다.</p>')
    assert any('Gold' in x for x in check_cause(doc, PC))


def test_quiet_asset_is_exempt_from_cause():
    doc = _sec('채권', '<p>커브는 조용했습니다.</p>')
    assert check_cause(doc, PC) == []


def test_no_price_context_skips_both():
    doc = _sec('주식', '<p>본문</p>')
    assert check_standing(doc, {}) == []
    assert check_cause(doc, {}) == []


def test_macro_group_may_not_repeat_a_price_the_asset_section_printed():
    doc = (_sec('FX', '<p>DXY는 -0.04% 내린 99.13으로 마감했습니다.</p>')
           + _sec('매크로 논리', '<div data-macro-group="dollar">'
                  '<p>오늘 DXY는 99.13으로 마감해 이 경로와 결이 같았습니다.</p></div>'))
    assert any('dollar' in x and '99.13' in x for x in check_macro_prices(doc))


def test_macro_group_may_keep_structural_logic():
    doc = _sec('FX', '<p>DXY는 99.13으로 마감했습니다.</p>') + _sec('매크로 논리', '<div data-macro-group="dollar">'
               '<p>실질금리 격차가 줄면 달러가 약해지는 경로입니다. 확인 지표는 20일 '
               '수익률이 -3% 아래로 확대되는지입니다.</p></div>')
    assert check_macro_prices(doc) == []


def test_price_section_may_not_restate_the_stance():
    doc = _sec('FX', '<p>달러 소폭 숏을 그대로 유지합니다.</p>')
    assert any('FX' in x for x in check_position_vocab(doc))


def test_bare_neutral_is_not_flagged():
    doc = _sec('FX', '<p>거의 중립적인 하루였습니다.</p>')
    assert check_position_vocab(doc) == []


LEDE_GOOD = _sec('전략 코멘트',
                 '<p data-lede="event">엔비디아 실적이 하루를 지배했습니다.</p>'
                 '<p data-lede="meaning">이 숫자가 AI 캐펙스 기대를 떠받칩니다.</p>'
                 '<p data-lede="action">2~6주 시계에서 메모리를 축소합니다.</p>'
                 '<p data-lede="invalidation">20일 초과수익이 +5%p를 넘으면 되돌립니다.</p>')


def test_lede_order_passes_when_correct():
    assert check_lede(LEDE_GOOD) == []


def test_lede_out_of_order_is_flagged():
    swapped = LEDE_GOOD.replace('data-lede="event"', 'data-lede="ZZ"', 1) \
                       .replace('data-lede="action"', 'data-lede="event"', 1) \
                       .replace('data-lede="ZZ"', 'data-lede="action"', 1)
    assert check_lede(swapped) != []


def test_lede_missing_paragraph_is_flagged():
    missing = LEDE_GOOD.replace(
        '<p data-lede="meaning">이 숫자가 AI 캐펙스 기대를 떠받칩니다.</p>', '')
    assert any('meaning' in x for x in check_lede(missing))


def test_check_runs_every_gate_for_us():
    v = check(_doc(US_FULL), market='us', market_data=MD,
              macro_eval={'abbreviated': False})
    assert any('data-lede' in x for x in v)


def test_check_skips_us_only_gates_for_kr():
    doc = _doc({'오늘의 장': 700, '지수 & 장중': 900, '환율·금리': 700,
                '전략 코멘트': 700, '기술적 분석 & 트레이딩 전략': 500})
    v = check(doc, market='kr', market_data=MD, macro_eval=None)
    assert not any('§9' in x for x in v)


# --- 판별력 있는 테스트 (2026-08-30 codex 검토: 무력 테스트 교체) ---

import os  # noqa: E402

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def _real_post():
    with open(os.path.join(_ROOT, 'posts', '2026-08-27.html'), encoding='utf-8') as fh:
        return fh.read()


def _real_market_data():
    import json
    with open(os.path.join(_ROOT, 'data', 'market_data.json'), encoding='utf-8') as fh:
        return json.load(fh)


def test_real_post_reproduces_the_spec_numbers():
    """합성이 아니라 실제 발행본을 센다 — 엔티티 디코드나 슬라이싱이 깨지면 틀어진다."""
    m = measure(_real_post(), 'us')
    assert m['sections']['주식'] == 1278
    assert m['sections']['채권'] == 1581
    assert m['sections']['FX'] == 360
    assert m['sections']['원자재'] == 457
    assert m['sections']['매크로 논리'] == 4788
    assert m['sections']['멀티에셋 매니저 전략'] == 887 + 1357
    assert m['recap'] == 3676 and m['judgment'] == 7424


def test_real_post_is_blocked_on_every_designed_axis():
    """check()가 모든 검사를 실제로 돌리는가 — 하나를 빈 함수로 바꾸면 이 테스트가 죽는다."""
    v = check(_real_post(), market='us', market_data=_real_market_data(),
              macro_eval={'abbreviated': False})
    assert any('÷' in x for x in v)                       # 비율
    assert any('매크로 논리' in x and '상한' in x for x in v)   # 매크로 상한
    assert any('data-standing' in x for x in v)            # 「지금 어디에 있나」
    assert any('포지션 등급 어휘' in x for x in v)             # 스탠스 되풀이
    assert any('data-lede' in x for x in v)                # §2 순서
    assert any('§9' in x and '되풀이' in x for x in v)        # 경로 블록 가격 중복


def test_ratio_floor_actually_bites_on_an_abbreviated_day():
    """축약일 1.00 문턱이 실제로 무는가 — 0.75로 낮추면 이 테스트가 죽는다."""
    sizes = {'오늘의 장': 800, '주식': 1500, '채권': 1500, 'FX': 900, '원자재': 900,
             '전략 코멘트': 400, '매크로 논리': 3200, '멀티에셋 매니저 전략': 2400}
    m = measure(_doc(sizes), 'us')
    assert 0.75 < m['ratio'] < 1.00
    assert check_volume(m, False, 'us') == []
    assert any('÷' in x and '축약일' in x for x in check_volume(m, True, 'us'))


def test_position_vocab_does_not_flag_ordinary_prose():
    for prose in ('신용스프레드는 전일보다 소폭확대됐습니다.',
                  '상승 종목 비중확대로 시장 폭이 개선됐습니다.'):
        assert check_position_vocab(_sec('채권', f'<p>{prose}</p>')) == []


def test_sign_and_unit_do_not_collide():
    doc = (_sec('FX', '<p>DXY는 -0.50% 내렸습니다.</p>')
           + _sec('매크로 논리', '<div data-macro-group="dollar">'
                  '<p>오늘 기대인플레는 +0.50%p 올랐습니다.</p></div>'))
    assert check_macro_prices(doc) == []


def test_paper_portfolio_counts_as_judgment_not_a_free_pass():
    """포트폴리오 섹션이 비율 밖에 있으면 판단군이 무한정 커질 수 있다."""
    doc = ('<h2>주식</h2><p>' + '가' * 100 + '</p>'
           '<h2>모의 포트폴리오</h2><p>' + '나' * 200 + '</p>')
    m = measure(doc, 'us')
    assert m['sections']['모의 포트폴리오'] == 200
    assert m['judgment'] >= 200


def test_older_posts_without_the_portfolio_section_are_not_violations():
    doc = '<h2>주식</h2><p>가</p>'
    assert '모의 포트폴리오' not in measure(doc, 'us')['missing']
