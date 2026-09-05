import pytest

from china import gate as G
from china import syllabus as S


def lesson(lid, order, prereq=(), status='fixed'):
    return dict(id=lid, track='structure', title=f'{lid}', prereq=list(prereq),
                order=order, required_data=[], core_question='?', status=status)


SYL = S.load({'version': 1, 'lessons': [
    lesson('A01', 1), lesson('A02', 2, ['A01']), lesson('A03', 3, ['A02'])]})


def state(completed=()):
    return {'version': 1, 'completed': [
        {'id': lid, 'week': wk, 'url': f'/china/posts/{wk}.html',
         'last_reviewed_week': lr,
         'claims': [{'claim_id': f'{lid}-c1', 'text': f'{lid} 명제'}]}
        for lid, wk, lr in completed],
        'last_published_week': completed[-1][1] if completed else None}


# 실제 강의 구간은 본문의 70%다. 표식만 있고 내용이 없는 것을 잡는 하한(200자)이
# 있으므로 표본도 그만큼은 돼야 한다.
LESSON_OK = ('<section data-lesson="A02"><h2>강의</h2><p>'
             + '지방정부 재정이 어떻게 굴러가는지부터 봅니다. ' * 12
             + '</p></section>')
REVISIT_OK = ('<section data-revisit="A01" data-verdict="valid" data-claim="A01-c1">'
              '<p>지난주 A01 에서 세운 명제는 <b>유효</b>합니다.</p></section>')


# ── 진도 (C4) ──

def test_correct_lesson_marker_passes():
    assert G.check_progress(LESSON_OK, state([('A01', '2026-W36', None)]), SYL) == []


def test_missing_lesson_marker_fails():
    v = G.check_progress('<section><p>x</p></section>', state(), SYL)
    assert any('data-lesson' in x for x in v)


def test_two_lesson_markers_fail_even_if_one_is_right():
    html = LESSON_OK + '<section data-lesson="A03"><p>y</p></section>'
    v = G.check_progress(html, state([('A01', '2026-W36', None)]), SYL)
    assert any('하나' in x for x in v)


def test_hidden_correct_marker_does_not_satisfy_the_gate():
    html = ('<div hidden data-lesson="A02">정답표식</div>'
            '<section data-lesson="A03"><p>딴 얘기</p></section>')
    v = G.check_progress(html, state([('A01', '2026-W36', None)]), SYL)
    assert v and not any('하나' in x for x in v)   # 숨긴 것은 세지 않는다


def test_wrong_lesson_fails():
    v = G.check_progress('<section data-lesson="A03"><p>x</p></section>',
                         state([('A01', '2026-W36', None)]), SYL)
    assert any('A02' in x for x in v)


def test_unknown_lesson_id_fails():
    v = G.check_progress('<section data-lesson="Z99"><p>x</p></section>', state(), SYL)
    assert any('Z99' in x for x in v)


def test_empty_lesson_section_fails():
    v = G.check_progress('<section data-lesson="A01"></section>', state(), SYL)
    assert any('비었' in x for x in v)


def test_exhausted_syllabus_blocks_publication():
    full = state([('A01', '2026-W36', None), ('A02', '2026-W37', None),
                  ('A03', '2026-W38', None)])
    v = G.check_progress(LESSON_OK, full, SYL)
    assert any('소진' in x for x in v)


# ── 되짚기 (C2·C4·C11) ──

def test_first_issue_needs_no_revisit():
    assert G.check_revisit('<section data-lesson="A01"><p>x</p></section>', state()) == []


def test_revisit_block_required_once_something_is_completed():
    v = G.check_revisit(LESSON_OK, state([('A01', '2026-W36', None)]))
    assert any('data-revisit' in x for x in v)


def test_correct_revisit_passes():
    assert G.check_revisit(REVISIT_OK, state([('A01', '2026-W36', None)])) == []


def test_revisit_of_the_wrong_lesson_fails():
    st = state([('A01', '2026-W36', '2026-W38'), ('A02', '2026-W37', None)])
    html = REVISIT_OK.replace('data-revisit="A01"', 'data-revisit="A01"')
    v = G.check_revisit(html, st)
    assert any('A02' in x for x in v)      # 큐가 지목한 것은 A02 다


def test_unknown_verdict_fails():
    v = G.check_revisit(REVISIT_OK.replace('data-verdict="valid"', 'data-verdict="ok"'),
                        state([('A01', '2026-W36', None)]))
    assert any('판정' in x for x in v)


def test_verdict_negated_in_prose_fails():
    html = REVISIT_OK.replace('<b>유효</b>합니다', '<b>유효</b>하지 않습니다')
    v = G.check_revisit(html, state([('A01', '2026-W36', None)]))
    assert any('부정' in x for x in v)


def test_claim_must_reference_a_real_claim_of_that_lesson():
    html = REVISIT_OK.replace('data-claim="A01-c1"', 'data-claim="A01-c9"')
    v = G.check_revisit(html, state([('A01', '2026-W36', None)]))
    assert any('A01-c9' in x for x in v)


def test_missing_claim_marker_fails():
    html = REVISIT_OK.replace(' data-claim="A01-c1"', '')
    v = G.check_revisit(html, state([('A01', '2026-W36', None)]))
    assert any('data-claim' in x for x in v)


# ── 수치 귀속 (C3) ──

MAN = {'cpi_yoy': {'2026-07': {'metric_id': 'cpi_yoy', 'period': '2026-07',
                               'value': 0.5, 'unit': '%', 'label_ko': '소비자물가 전년 대비',
                               'kind': 'change', 'source_key': 'nbs-cpi-2026-07'}},
       'cpi_food_yoy': {'2026-07': {'metric_id': 'cpi_food_yoy', 'period': '2026-07',
                                    'value': -1.5, 'unit': '%', 'label_ko': '식품',
                                    'kind': 'change', 'source_key': 'nbs-cpi-2026-07'}}}
DUMPS = {'nbs-cpi-2026-07': "CPI increased by 0.5%. Food decreased by 1.5%. "
                            "Pork decreased by 13.3%."}


def test_headline_number_bound_to_its_metric_passes():
    html = '<p><span data-metric="cpi_yoy" data-period="2026-07">0.5%</span> 올랐습니다.</p>'
    assert G.check_numbers(html, MAN, DUMPS) == []


def test_misattributed_headline_number_is_caught():
    """같은 릴리스 안의 다른 지표 값을 가져다 붙이는 것 — 집합 대조로는 못 잡던 창작."""
    html = '<p><span data-metric="cpi_yoy" data-period="2026-07">-1.5%</span></p>'
    v = G.check_numbers(html, MAN, DUMPS)
    assert any('cpi_yoy' in x for x in v)


def test_secondary_number_inside_a_cited_paragraph_passes():
    html = ('<p data-cite="nbs-cpi-2026-07">돼지고기가 13.3% 내렸습니다.</p>')
    assert G.check_numbers(html, MAN, DUMPS) == []


def test_secondary_number_not_in_the_cited_release_is_caught():
    html = '<p data-cite="nbs-cpi-2026-07">돼지고기가 22.7% 내렸습니다.</p>'
    v = G.check_numbers(html, MAN, DUMPS)
    assert any('22.7' in x for x in v)


def test_number_with_no_marker_at_all_is_caught():
    v = G.check_numbers('<p>수출이 7.2% 늘었습니다.</p>', MAN, DUMPS)
    assert any('7.2' in x for x in v)


def test_citing_an_uncollected_release_is_caught():
    html = '<p data-cite="nbs-ppi-2026-07">3.3% 입니다.</p>'
    v = G.check_numbers(html, MAN, DUMPS)
    assert any('nbs-ppi-2026-07' in x for x in v)


def test_years_and_lesson_ids_are_not_treated_as_numbers():
    html = '<p>2026년 A01 강의에서 다뤘습니다.</p>'
    assert G.check_numbers(html, MAN, DUMPS) == []


def test_unknown_metric_id_is_caught():
    html = '<p><span data-metric="cpi_nope" data-period="2026-07">0.5%</span></p>'
    v = G.check_numbers(html, MAN, DUMPS)
    assert any('cpi_nope' in x for x in v)


def test_metric_without_a_collected_period_is_caught():
    html = '<p><span data-metric="cpi_yoy" data-period="2026-06">0.5%</span></p>'
    v = G.check_numbers(html, MAN, DUMPS)
    assert any('2026-06' in x for x in v)


# ── 수집 완전성 (C5) ──

def test_discovered_but_unfetched_tier1_blocks_publication():
    idx = {'releases': [{'key': 'nbs-cpi-2026-07', 'tier': 1, 'discovered': True,
                         'fetch_status': 'failed', 'http_status': 403}]}
    v = G.check_release_coverage(idx)
    assert any('nbs-cpi-2026-07' in x for x in v)


def test_all_fetched_passes():
    idx = {'releases': [{'key': 'k', 'tier': 1, 'discovered': True,
                         'fetch_status': 'ok', 'http_status': 200}]}
    assert G.check_release_coverage(idx) == []


def test_failed_tier2_is_a_warning_not_a_block():
    idx = {'releases': [{'key': 'k', 'tier': 2, 'discovered': True,
                         'fetch_status': 'failed', 'http_status': 500}]}
    assert G.check_release_coverage(idx) == []


# ── 시황 상한 (C7) ──

def test_recap_within_cap_passes():
    html = ('<section data-block="lesson"><p>' + '교재 ' * 200 + '</p></section>'
            '<section data-block="markets"><p>' + '시황 ' * 20 + '</p></section>')
    assert G.check_recap_cap(html) == []


def test_recap_over_cap_fails():
    html = ('<section data-block="lesson"><p>' + '교재 ' * 20 + '</p></section>'
            '<section data-block="markets"><p>' + '시황 ' * 200 + '</p></section>')
    v = G.check_recap_cap(html)
    assert any('상한' in x for x in v)


def test_recap_hidden_in_headings_and_quotes_still_counts():
    body = '<h3>' + '시황 ' * 100 + '</h3><blockquote>' + '시황 ' * 100 + '</blockquote>'
    html = ('<section data-block="lesson"><p>' + '교재 ' * 20 + '</p></section>'
            '<section data-block="markets">' + body + '</section>')
    v = G.check_recap_cap(html)
    assert any('상한' in x for x in v)


# ── 포지션 어휘 (C6) ──

def test_position_vocabulary_is_blocked_anywhere_in_the_body():
    v = G.check_position_vocab('<li>비중확대 의견입니다.</li>')
    assert any('비중확대' in x for x in v)


def test_target_price_and_buy_sell_are_blocked():
    assert G.check_position_vocab('<p>목표주가 12만원</p>')
    assert G.check_position_vocab('<td>매수 추천</td>')


def test_descriptive_use_is_not_a_position_call():
    """「스프레드가 소폭확대됐다」 같은 서술은 등급이 아니다 — US 게이트의 조사 교훈."""
    assert G.check_position_vocab('<p>스프레드가 소폭확대됐습니다.</p>') == []


def test_bare_neutral_is_not_checked():
    assert G.check_position_vocab('<p>판단은 중립입니다.</p>') == []


def test_hidden_position_word_is_ignored():
    assert G.check_position_vocab('<p hidden>비중확대</p>') == []


# ── 용어 풀이 (C6) ──

def test_unglossed_chinese_term_is_caught():
    v = G.check_gloss('<p>총사회융자가 늘었습니다.</p>')
    assert any('총사회융자' in x for x in v)


def test_glossed_first_use_passes():
    html = ('<p>총사회융자(실물경제가 금융권에서 조달한 자금 총액)가 늘었습니다.</p>'
            '<p>총사회융자는 그 뒤로도 늘었습니다.</p>')
    assert G.check_gloss(html) == []


def test_gloss_may_come_as_a_following_clause():
    html = '<p>후커우, 곧 도시 호적 제도가 소비를 누릅니다.</p>'
    assert G.check_gloss(html) == []


def test_value_from_another_period_of_the_same_metric_is_caught():
    """지표는 맞는데 달이 다른 값 — 지표별로만 좁히면 통과하던 창작."""
    man = {'cpi_yoy': {
        '2026-07': {'metric_id': 'cpi_yoy', 'period': '2026-07', 'value': 0.5,
                    'unit': '%', 'label_ko': '소비자물가', 'kind': 'change',
                    'source_key': 'k7'},
        '2026-06': {'metric_id': 'cpi_yoy', 'period': '2026-06', 'value': 0.2,
                    'unit': '%', 'label_ko': '소비자물가', 'kind': 'change',
                    'source_key': 'k6'}}}
    html = '<p><span data-metric="cpi_yoy" data-period="2026-07">0.2%</span></p>'
    v = G.check_numbers(html, man, {})
    assert any('0.2' in x for x in v)


def test_target_price_word_does_not_fire_on_ordinary_korean():
    """「목표가 정해지면」의 「목표가」는 목표 + 주격조사다 — 목표주가가 아니다."""
    assert G.check_position_vocab('<p>목표가 정해지면 한도로 번역됩니다.</p>') == []
    assert G.check_position_vocab('<p>목표가 12만원입니다.</p>')


# ── codex 2차 검토 (2026-09-05) ──

MAN2 = {'cpi_yoy': {'2026-07': {'metric_id': 'cpi_yoy', 'period': '2026-07',
                                'value': 0.5, 'unit': '%', 'label_ko': '소비자물가 전년 대비',
                                'kind': 'change', 'source_key': 'nbs-cpi-2026-07'}},
        'cpi_food_yoy': {'2026-07': {'metric_id': 'cpi_food_yoy', 'period': '2026-07',
                                     'value': -1.5, 'unit': '%', 'label_ko': '식품 물가 전년 대비',
                                     'kind': 'change', 'source_key': 'nbs-cpi-2026-07'}}}
DUMPS2 = {'nbs-cpi-2026-07': 'CPI increased by 0.5%. Food decreased by 1.5%. '
                             'Eggs decreased by 14.4%. Pork decreased by 13.3%.'}


def test_negative_value_printed_as_a_rise_is_caught():
    """실제 -1.5% 를 「1.5% 상승」으로 쓰는 것 — 절댓값 허용의 뒷문."""
    html = ('<p><span data-metric="cpi_food_yoy" data-period="2026-07">1.5%</span> '
            '상승했습니다.</p>')
    assert G.check_numbers(html, MAN2, DUMPS2)


def test_negative_value_printed_as_a_fall_passes():
    html = ('<p>식품 물가는 <span data-metric="cpi_food_yoy" data-period="2026-07">1.5%'
            '</span> 내렸습니다.</p>')
    assert G.check_numbers(html, MAN2, DUMPS2) == []


def test_unicode_minus_cannot_disguise_a_sign():
    html = '<p><span data-metric="cpi_yoy" data-period="2026-07">−0.5%</span></p>'
    assert G.check_numbers(html, MAN2, DUMPS2)


def test_headline_label_inside_a_cited_paragraph_needs_a_binding():
    """달걀 14.4% 를 「소비자물가 14.4% 상승」으로 옮겨 적는 우회."""
    html = '<p data-cite="nbs-cpi-2026-07">소비자물가가 14.4% 올랐습니다.</p>'
    v = G.check_numbers(html, MAN2, DUMPS2)
    assert any('data-metric' in x for x in v)


def test_cited_paragraph_without_a_headline_label_is_fine():
    html = '<p data-cite="nbs-cpi-2026-07">달걀 값이 14.4% 내렸습니다.</p>'
    assert G.check_numbers(html, MAN2, DUMPS2) == []


def test_naming_the_release_is_not_claiming_its_headline():
    """「7월 소비자물가 원문을 보면 돼지고기가 13.3% 내렸다」 — 이름은 릴리스를
    가리키고 수치는 다른 항목이다. 이름이 숫자 옆에 붙었을 때만 걸어야 한다."""
    html = ('<p data-cite="nbs-cpi-2026-07">7월 소비자물가 원문을 보면 돼지고기 값이 '
            '13.3% 내렸습니다.</p>')
    assert G.check_numbers(html, MAN2, DUMPS2) == []


def test_adjacent_cells_do_not_merge_into_one_number():
    html = '<table><tr><td>0.5</td><td>0.9</td></tr></table>'
    v = G.check_numbers(html, MAN2, DUMPS2)
    assert not any('0.50.9' in x for x in v)


def test_required_data_must_appear_as_a_bound_metric():
    syl = S.load({'version': 1, 'lessons': [
        dict(id='A01', track='structure', title='x', prereq=[], order=1,
             required_data=['cpi_yoy'], core_question='?', status='fixed')]})
    html = ('<section data-lesson="A01"><p>' + '설명입니다. ' * 30 + '</p></section>')
    v = G.check_progress(html, state(), syl, man=MAN2)
    assert any('cpi_yoy' in x for x in v)


def test_required_data_satisfied_when_bound():
    syl = S.load({'version': 1, 'lessons': [
        dict(id='A01', track='structure', title='x', prereq=[], order=1,
             required_data=['cpi_yoy'], core_question='?', status='fixed')]})
    html = ('<section data-lesson="A01"><p>' + '설명입니다. ' * 30
            + '<span data-metric="cpi_yoy" data-period="2026-07">0.5%</span></p></section>')
    assert G.check_progress(html, state(), syl, man=MAN2) == []


def test_lesson_marker_must_sit_on_a_top_level_section():
    html = ('<section><div data-lesson="A02"><p>' + '본문입니다. ' * 40
            + '</p></div></section>')
    v = G.check_progress(html, state([('A01', '2026-W36', None)]), SYL)
    assert any('section' in x for x in v)


def test_market_prose_outside_the_markets_block_still_counts():
    """`data-block="markets"` 를 지우면 상한을 피하던 우회."""
    html = ('<section data-block="lesson"><p>' + '교재 ' * 20 + '</p></section>'
            '<section><p>' + '상해종합지수가 1.2% 올랐고 위안 환율은 내렸습니다. ' * 12
            + '</p></section>')
    v = G.check_recap_cap(html)
    assert any('상한' in x for x in v)


def test_verdict_negated_further_into_the_sentence_fails():
    html = REVISIT_OK.replace('<b>유효</b>합니다', '<b>유효</b>한 것은 아닙니다')
    v = G.check_revisit(html, state([('A01', '2026-W36', None)]))
    assert any('부정' in x for x in v)


def test_recommendation_phrasing_is_a_position_call():
    assert G.check_position_vocab('<p>매수를 권합니다.</p>')
    assert G.check_position_vocab('<p>매수\n추천 의견입니다.</p>')


def test_a_stray_opposite_direction_word_cannot_neutralise_the_sign_check():
    """문단 어딘가에 반대 방향어를 하나 심어 부호 검사를 무력화하는 우회."""
    man = {'cpi_yoy': {'2026-07': {'metric_id': 'cpi_yoy', 'period': '2026-07',
                                   'value': -0.5, 'unit': '%', 'label_ko': '소비자물가',
                                   'kind': 'change', 'source_key': 'k'}}}
    bad = ('<p>지난달 하락 흐름과 달리 <span data-metric="cpi_yoy" data-period="2026-07">'
           '0.5%</span> 상승했습니다.</p>')
    assert G.check_numbers(bad, man, {})
    good = ('<p>지난달 상승 흐름과 달리 <span data-metric="cpi_yoy" data-period="2026-07">'
            '0.5%</span> 내렸습니다.</p>')
    assert G.check_numbers(good, man, {}) == []


# ── codex 3차 (2026-09-05) ──

MAN3 = {'cpi_yoy': {'2026-07': {'metric_id': 'cpi_yoy', 'period': '2026-07',
                                'value': -0.5, 'unit': '%', 'label_ko': '소비자물가 전년 대비',
                                'kind': 'change', 'source_key': 'k'}},
        'cpi_food_yoy': {'2026-07': {'metric_id': 'cpi_food_yoy', 'period': '2026-07',
                                     'value': -1.5, 'unit': '%', 'label_ko': '식품 물가 전년 대비',
                                     'kind': 'change', 'source_key': 'k'}}}
DUMP3 = {'k': 'CPI decreased by 0.5%. Food decreased by 1.5%. Pork decreased by 13.3%. '
              'Eggs decreased by 14.4%.'}


def test_opposite_direction_word_in_the_same_clause_still_fails():
    html = ('<p><span data-metric="cpi_yoy" data-period="2026-07">0.5%</span> '
            '상승하고 다른 값은 하락했습니다.</p>')
    assert G.check_numbers(html, MAN3, DUMP3)


def test_spaced_unicode_minus_is_normalised():
    html = '<p><span data-metric="cpi_yoy" data-period="2026-07">− 0.5%</span></p>'
    assert G.check_numbers(html, MAN3, DUMP3) == []


def test_one_binding_does_not_exempt_the_rest_of_the_cited_paragraph():
    """정상 data-metric 하나를 곁들여 나머지 참칭 검사를 건너뛰던 우회."""
    html = ('<p data-cite="k">'
            '<span data-metric="cpi_food_yoy" data-period="2026-07">1.5%</span> 내렸고, '
            '소비자물가는 14.4% 올랐습니다.</p>')
    v = G.check_numbers(html, MAN3, DUMP3)
    assert any('data-metric' in x for x in v)


def test_naming_the_release_then_quoting_another_item_is_fine():
    """오탐 회귀 — 이름은 릴리스를 가리키고 수치는 다른 항목이다."""
    html = '<p data-cite="k">소비자물가 원문에서 돼지고기는 13.3% 내렸습니다.</p>'
    assert G.check_numbers(html, MAN3, DUMP3) == []


def test_inline_tag_cannot_manufacture_a_number():
    html = '<p data-cite="k">달걀은 1<b>4</b>.4% 내렸습니다.</p>'
    assert G.check_numbers(html, MAN3, DUMP3) == []
    bad = '<p data-cite="k">달걀은 4<b>4</b>% 내렸습니다.</p>'
    assert G.check_numbers(bad, MAN3, DUMP3)


def test_empty_binding_does_not_satisfy_required_data():
    syl = S.load({'version': 1, 'lessons': [
        dict(id='A01', track='structure', title='x', prereq=[], order=1,
             required_data=['cpi_yoy'], core_question='?', status='fixed')]})
    html = ('<section data-lesson="A01"><p>' + '설명입니다. ' * 30
            + '<span data-metric="cpi_yoy" data-period="2026-07"></span></p></section>')
    assert G.check_progress(html, state(), syl, man=MAN3)


def test_layout_wrapper_does_not_break_the_lesson_marker():
    html = ('<div class="container"><section data-lesson="A01"><p>'
            + '설명입니다. ' * 30 + '</p></section></div>')
    assert G.check_progress(html, state(), SYL) == []


def test_institutional_prose_is_not_market_recap():
    """A09 의 제도 설명이 시황 100% 로 거부되던 오탐."""
    html = ('<section data-lesson="A09"><p>'
            + '환율이 움직일 수 있는 범위를 중앙은행이 정하고 그 안에서만 거래됩니다. ' * 6
            + '</p></section>')
    assert G.check_recap_cap(html) == []


def test_market_prose_without_the_block_still_counts_even_in_a_heading():
    body = ('<h3>상해종합지수가 1.2% 올랐습니다</h3>'
            '<td>구리 선물은 0.8% 내렸습니다</td>') * 8
    html = ('<section data-block="lesson"><p>' + '교재 ' * 20 + '</p></section>'
            '<section>' + body + '</section>')
    assert any('상한' in x for x in G.check_recap_cap(html))


def test_verdict_negation_survives_a_line_break():
    html = REVISIT_OK.replace('<b>유효</b>합니다', '<b>유효</b>한 것은\n아닙니다')
    assert any('부정' in x for x in G.check_revisit(html, state([('A01', '2026-W36', None)])))


def test_a_later_unrelated_negative_does_not_flag_the_verdict():
    """오탐 회귀 — 「없습니다」가 부정하는 것은 추가 수정이지 판정이 아니다."""
    html = REVISIT_OK.replace('<b>유효</b>합니다', '<b>유효</b>하며 추가 수정은 필요가 없습니다')
    assert G.check_revisit(html, state([('A01', '2026-W36', None)])) == []


def test_indirect_recommendation_phrasings_are_caught():
    for s in ('매수할 것을 권합니다', '매수하는 편을 추천합니다', '비중 확대를 권합니다'):
        assert G.check_position_vocab(f'<p>{s}</p>'), s


def test_broken_index_blocks_publication():
    idx = {'releases': [], 'index_ok': False}
    assert G.check_release_coverage(idx)


def test_healthy_empty_index_is_still_a_failure():
    """인덱스는 늘 최근 릴리스를 싣는다 — 0건은 조용한 주가 아니다."""
    assert G.check_release_coverage({'releases': [], 'index_ok': True})
