from us.price_gate import check


def _pc(flipped_keys=(), residual=0.25, r2=0.97):
    pairs = [('equity_rates', '주식과 금리'), ('equity_dollar', '주식과 달러'),
             ('gold_rates', '금과 금리'), ('memory_nasdaq', '메모리와 나스닥')]
    return {
        'correlations': [{'key': k, 'label_ko': lab, 'value': -0.3, 'prior': 0.4,
                          'flipped': k in flipped_keys, 'band': '반대로 움직임(느슨하게)'}
                         for k, lab in pairs],
        'sector_contribution': {'index_change': 0.82, 'estimated': True, 'fit_r2': r2,
                                'residual': residual, 'rows': [
                                    {'name': 'Technology', 'change': 2.96,
                                     'contribution': 0.999}]},
    }


BODY = '<section><p>시장은 조용했다.</p></section>'


def test_a_quiet_day_passes():
    assert check(BODY, _pc()) == []


def test_a_flipped_relationship_must_be_written_about():
    v = check(BODY, _pc(flipped_keys=('equity_rates',)))
    assert any('equity_rates' in x for x in v)


def test_a_flipped_relationship_is_satisfied_by_its_marker():
    html = BODY + '<p data-relation="equity_rates">주식과 금리가 최근 같이 움직이기 시작했다.</p>'
    assert check(html, _pc(flipped_keys=('equity_rates',))) == []


def test_every_flipped_relationship_needs_its_own_marker():
    html = BODY + '<p data-relation="equity_rates">…</p>'
    v = check(html, _pc(flipped_keys=('equity_rates', 'gold_rates')))
    assert len(v) == 1 and 'gold_rates' in v[0]


def test_a_marker_for_a_relationship_that_did_not_flip_is_allowed():
    html = BODY + '<p data-relation="gold_rates">금과 금리는 여전히 반대로 움직인다.</p>'
    assert check(html, _pc()) == []


def test_an_attribution_block_must_carry_the_unexplained_part():
    html = BODY + '<p data-attribution="1">기술이 1.00%p를 만들었다.</p>'
    v = check(html, _pc(residual=0.25))
    assert any('설명' in x for x in v)


def test_an_attribution_block_that_states_the_residual_passes():
    html = BODY + '<p data-attribution="1">기술이 1.00%p를 만들었고 0.25%p는 설명되지 않는다.</p>'
    assert check(html, _pc(residual=0.25)) == []


def test_attribution_is_refused_when_the_weights_barely_fit():
    html = BODY + '<p data-attribution="1">기술이 1.00%p를 만들었고 0.25%p는 설명되지 않는다.</p>'
    v = check(html, _pc(r2=0.80))
    assert any('0.8' in x for x in v)


def test_internal_vocabulary_must_not_reach_the_page():
    html = BODY + '<p>주성분 분석 결과 고유값이 높았다.</p>'
    v = check(html, _pc())
    assert any('주성분' in x for x in v)


def test_internal_field_names_must_not_reach_the_page():
    html = BODY + '<p>price_context의 multiple이 2.0이다.</p>'
    v = check(html, _pc())
    assert len(v) >= 1


def test_a_missing_price_context_block_is_not_a_violation():
    assert check(BODY, None) == []


def test_attribution_is_refused_when_the_fit_cannot_be_measured():
    html = BODY + '<p data-attribution="1">기술이 1.00%p를 만들었고 0.25%p는 설명되지 않는다.</p>'
    pc = _pc()
    pc['sector_contribution']['fit_r2'] = None
    assert check(html, pc) != []


def test_a_scorecard_claim_needs_enough_decisions_behind_it():
    html = BODY + '<p data-scorecard="1">확대 판단은 지금까지 70% 맞았습니다.</p>'
    v = check(html, _pc(), scorecard={'sufficient': False, 'scored': 8, 'min_sample': 20})
    assert any('표본' in x for x in v)


def test_a_scorecard_claim_passes_once_the_record_is_long_enough():
    html = BODY + '<p data-scorecard="1">확대 판단은 지금까지 70% 맞았습니다.</p>'
    assert check(html, _pc(), scorecard={'sufficient': True, 'scored': 24,
                                         'min_sample': 20}) == []


def test_no_scorecard_claim_means_no_scorecard_check():
    assert check(BODY, _pc(), scorecard={'sufficient': False, 'scored': 0,
                                         'min_sample': 20}) == []





# 1등 자산군 교체를 지키던 세 테스트는 은퇴했다 — 그 사건은 3년 381개 창에서
# 한 번도 일어나지 않았다. 대체 계약은 아래 「동승자」다.


def test_a_scorecard_claim_with_no_scorecard_at_all_fails_closed():
    """성적표 파일을 못 읽었다는 것은 「표본이 충분하다」는 뜻이 아니다."""
    html = BODY + '<p data-scorecard="1">확대 판단은 70% 맞았습니다.</p>'
    assert check(html, _pc(), scorecard=None) != []


# ── 표식 우회 (codex 검토 2026-09-07: 재현됨) ──────────────────────────────

def test_a_marker_hidden_in_a_comment_does_not_satisfy_the_rule():
    """주석은 독자가 못 본다. 게이트가 읽는 문장과 독자가 보는 문장이 갈리는
    자리가 곧 게이트가 뚫리는 자리다."""
    html = BODY + '<!-- <p data-relation="equity_rates">주식과 금리가 뒤집혔다.</p> -->'
    assert check(html, _pc(flipped_keys=('equity_rates',))) != []


def test_a_residual_that_only_appears_inside_a_larger_number_is_not_accepted():
    """잔차 0.25 를 「10.25%」가 대신 만족시키면 안 된다."""
    html = BODY + '<p data-attribution="1">기술이 지수를 10.25%포인트 끌어올렸습니다.</p>'
    assert check(html, _pc(residual=0.25)) != []


# ── 동승자 (2026-09-07) ────────────────────────────────────────────────────

def _drivers(companion='금리', prior_companion='원자재', changed=True):
    return {'first': {'group_ko': '주식', 'share_pct': 42.9},
            'second': {'group_ko': '금리', 'share_pct': 18.4},
            'companion': None if companion is None else
            {'group_ko': companion, 'loading': 0.265, 'gap_pct': 24.0},
            'prior': {'first': '주식', 'second': '금리'},
            'companion_prior': prior_companion,
            'companion_changed': changed}


def test_a_changed_companion_must_be_written_about():
    pc = _pc()
    pc['drivers'] = _drivers()
    assert any('동승' in x or '함께' in x or '연결' in x for x in check(BODY, pc)), check(BODY, pc)


def test_a_changed_companion_is_satisfied_by_its_marker():
    pc = _pc()
    pc['drivers'] = _drivers()
    html = BODY + ('<p data-driver="1">공통 움직임에 원자재 대신 금리가 붙어 있습니다.</p>')
    assert check(html, pc) == []


def test_an_unchanged_companion_needs_no_marker():
    pc = _pc()
    pc['drivers'] = _drivers(changed=False)
    assert check(BODY, pc) == []


def test_an_empty_driver_marker_still_does_not_satisfy_the_rule():
    pc = _pc()
    pc['drivers'] = _drivers()
    assert check(BODY + '<i data-driver="x"></i>', pc) != []


# ── 5년 뒤 5년 금리 (2026-09-07) ──────────────────────────────────────────
#
# 매일 해석 문단을 강제하면 채움 문장이 된다(codex 검토). 값과 기준일은 매일
# 필수, 해석은 그날 할 말이 있을 때만.

def _fwd(nominal=5.02, date='2026-09-03', gap=None):
    return {'nominal': nominal, 'real': 2.69, 'date': date,
            'chg_1d_bp': -2.0, 'breakeven_implied': 2.33, 'breakeven_gap_bp': gap}


def test_the_forward_rate_must_reach_the_page():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    assert any('5년' in x for x in check(BODY, pc)), check(BODY, pc)


def test_the_forward_rate_passes_once_it_is_stated_with_its_basis_date():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">9월 3일 기준 5년 뒤 5년 금리는 5.02%입니다.</p>'
    assert check(html, pc) == []


def test_the_forward_block_must_state_its_basis_date():
    """기준일이 발행일보다 이를 수 있다 — 09-04 발행본의 값이 09-03 것이다."""
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">5년 뒤 5년 금리는 5.02%입니다.</p>'
    assert check(html, pc) != []


def test_a_forward_figure_inside_a_bigger_number_does_not_count():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">9월 3일 기준 지수는 15.02였습니다.</p>'
    assert check(html, pc) != []


def test_a_stale_cross_check_lifts_the_forward_requirement():
    pc = _pc()
    pc['forward_5y5y'] = _fwd(gap=-22.0)
    assert not any('5년' in x for x in check(BODY, pc))


def test_a_cross_check_gap_of_exactly_fifteen_still_requires_the_forward():
    pc = _pc()
    pc['forward_5y5y'] = _fwd(gap=15.0)
    assert any('5년' in x for x in check(BODY, pc))


def test_no_forward_rate_means_no_forward_check():
    pc = _pc()
    pc['forward_5y5y'] = None
    assert check(BODY, pc) == []


# ── 응집도 (2026-09-07) ────────────────────────────────────────────────────

def _coh(pct, top1=55.0):
    from us.price_context import percentile_band
    return {'n_assets': 10, 'top1_pct': top1, 'top3_pct': 78.0,
            'percentile': pct, 'band': percentile_band(pct), 'history_windows': 252}


def test_an_unusual_cohesion_must_be_written_about():
    pc = _pc()
    pc['cohesion'] = _coh(96.0)
    assert any('한 덩어리' in x or '응집' in x or '함께' in x for x in check(BODY, pc)), check(BODY, pc)



def test_an_ordinary_cohesion_is_not_forced_onto_the_page():
    pc = _pc()
    pc['cohesion'] = _coh(59.5, top1=42.9)
    assert check(BODY, pc) == []


def test_an_unusually_scattered_market_must_also_be_written_about():
    pc = _pc()
    pc['cohesion'] = _coh(4.0, top1=33.6)
    assert check(BODY, pc) != []


def test_cohesion_without_a_percentile_is_not_forced():
    pc = _pc()
    pc['cohesion'] = {'n_assets': 10, 'top1_pct': 55.0, 'top3_pct': 78.0,
                      'percentile': None, 'band': None, 'history_windows': None}
    assert check(BODY, pc) == []


# ── codex 구현 검토(2026-09-07)가 재현한 우회 경로 ─────────────────────────

def test_a_marker_the_reader_cannot_see_does_not_satisfy_the_rule():
    """주석만 막으면 hidden·template·script 가 그대로 남는다 — 셋 다 재현됐다."""
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    for hidden in ('<p hidden data-forward="1">9월 3일 기준 5.02%</p>',
                   '<template><p data-forward="1">9월 3일 기준 5.02%</p></template>',
                   '<script><p data-forward="1">9월 3일 기준 5.02%</p></script>',
                   '<p style="display:none" data-forward="1">9월 3일 기준 5.02%</p>'):
        assert check(BODY + hidden, pc) != [], hidden


def test_a_data_attribute_named_hidden_is_not_mistaken_for_the_attribute():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-hidden="x" data-forward="1">9월 3일 기준 5.02%입니다.</p>'
    assert check(html, pc) == []


def test_the_forward_value_and_its_basis_date_must_sit_in_one_block():
    """블록을 합쳐서 검사하면 값에 틀린 날짜를 붙여 놓고도 통과한다."""
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = (BODY + '<p data-forward="1">9월 4일 기준 5.02%입니다.</p>'
            + '<p data-forward="1">9월 3일에는 다른 얘기를 했습니다.</p>')
    assert check(html, pc) != []


def test_a_basis_date_with_the_wrong_year_does_not_count():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">2025년 9월 3일 기준 5.02%입니다.</p>'
    assert check(html, pc) != []


def test_a_basis_date_needs_a_real_month():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">19월 3일 기준 5.02%입니다.</p>'
    assert check(html, pc) != []


def test_an_iso_basis_date_counts():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">2026-09-03 기준 5.02%입니다.</p>'
    assert check(html, pc) == []


def test_a_negative_number_does_not_satisfy_a_positive_rate():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    html = BODY + '<p data-forward="1">9월 3일 기준 -5.02%였습니다.</p>'
    assert check(html, pc) != []


def test_a_signed_residual_still_counts_because_it_is_printed_with_its_sign():
    html = BODY + '<p data-attribution="1">설명되지 않는 몫은 -0.25%포인트입니다.</p>'
    assert check(html, _pc(residual=0.25)) == []


def test_an_unusual_cohesion_must_be_told_as_unusual_not_just_numbered():
    """값만으로는 43%가 높은지 낮은지 알 수 없다 — 통제 어휘가 함께 나와야 한다."""
    pc = _pc()
    pc['cohesion'] = _coh(96.0)
    html = BODY + '<p data-cohesion="1">열 개 자산 움직임의 55.0%가 한 힘에서 나옵니다.</p>'
    assert check(html, pc) != []


def test_an_unusual_cohesion_passes_once_the_band_is_stated():
    pc = _pc()
    pc['cohesion'] = _coh(96.0)
    html = BODY + ('<p data-cohesion="1">열 개 자산 움직임의 55.0%가 한 힘에서 나옵니다.'
                   ' 지난 1년 기준으로 매우 높음에 해당합니다.</p>')
    assert check(html, pc) == []


def test_an_empty_relationship_marker_does_not_satisfy_the_rule():
    """표식만 달고 내용을 비우면 서술한 것이 아니다 — 다른 규칙과 같은 기준."""
    html = BODY + '<p data-relation="equity_rates"></p>'
    assert check(html, _pc(flipped_keys=('equity_rates',))) != []


def test_the_cohesion_message_names_the_window_it_compared():
    pc = _pc()
    pc['cohesion'] = _coh(96.0)
    assert any('252' in x for x in check(BODY, pc)), check(BODY, pc)


# ── HTML 을 정규식으로 읽던 것을 파서로 바꾼다 (codex 3차 검토 2026-09-07) ──
#
# 정규식으로는 중첩·속성·엔티티를 못 가른다. 아래는 전부 codex 가 실제로
# 재현한 통과 경로이거나, 정상 본문을 지워 버리던 경로다.

def _fwd_pc():
    pc = _pc()
    pc['forward_5y5y'] = _fwd()
    return pc


def test_a_nested_hidden_block_hides_the_whole_subtree():
    html = BODY + ('<div hidden><div>숨김</div>'
                   '<p data-forward="1">9월 3일 기준 5.02%</p></div>')
    assert check(html, _fwd_pc()) != []


def test_a_nested_template_hides_the_whole_subtree():
    html = BODY + ('<template><template></template>'
                   '<p data-forward="1">9월 3일 기준 5.02%</p></template>')
    assert check(html, _fwd_pc()) != []


def test_an_attribute_that_merely_mentions_display_none_hides_nothing():
    html = BODY + '<div title="display:none 예시"><p data-forward="1">9월 3일 기준 5.02%</p></div>'
    assert check(html, _fwd_pc()) == []


def test_an_attribute_that_merely_mentions_hidden_hides_nothing():
    html = BODY + '<div title=" hidden 예시"><p data-forward="1">9월 3일 기준 5.02%</p></div>'
    assert check(html, _fwd_pc()) == []


def test_a_tag_whose_name_starts_with_script_is_not_a_script():
    html = BODY + ('<script-demo><p data-forward="1">9월 3일 기준 5.02%</p></script-demo>'
                   '<script></script>')
    assert check(html, _fwd_pc()) == []


def test_a_marker_split_across_inline_tags_is_still_read():
    html = BODY + '<p data-forward="1">9월 3일 기준 <b>5.02</b>%입니다.</p>'
    assert check(html, _fwd_pc()) == []


def test_a_minus_sign_separated_from_the_number_still_does_not_count():
    for bad in ('9월 3일 기준 - 5.02%였습니다.', '9월 3일 기준 −<span>5.02</span>%였습니다.'):
        assert check(BODY + f'<p data-forward="1">{bad}</p>', _fwd_pc()) != [], bad


def test_a_plus_sign_does_not_disqualify_a_positive_rate():
    html = BODY + '<p data-forward="1">9월 3일 기준 +5.02%입니다.</p>'
    assert check(html, _fwd_pc()) == []


def test_a_negative_cohesion_figure_does_not_satisfy_the_share():
    pc = _pc()
    pc['cohesion'] = _coh(96.0)
    html = BODY + '<p data-cohesion="1">-55.0%로 매우 높음입니다.</p>'
    assert check(html, pc) != []


def test_a_wrong_year_written_with_a_particle_is_still_a_wrong_year():
    for bad in ('2025년도 9월 3일 기준 5.02%', '2025년의 9월 3일 기준 5.02%',
                '12026년 9월 3일 기준 5.02%'):
        assert check(BODY + f'<p data-forward="1">{bad}</p>', _fwd_pc()) != [], bad


def test_the_right_year_written_out_still_counts():
    html = BODY + '<p data-forward="1">2026년 9월 3일 기준 5.02%입니다.</p>'
    assert check(html, _fwd_pc()) == []


def test_a_marker_holding_only_a_non_breaking_space_is_empty():
    html = BODY + '<p data-relation="equity_rates">&nbsp;</p>'
    assert check(html, _pc(flipped_keys=('equity_rates',))) != []


def test_a_greater_than_inside_an_attribute_does_not_open_the_block():
    html = BODY + '<p data-relation="equity_rates" title=">"></p>'
    assert check(html, _pc(flipped_keys=('equity_rates',))) != []
