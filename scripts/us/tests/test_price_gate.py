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


def test_a_changed_leading_force_must_be_written_about():
    pc = _pc()
    pc['drivers'] = {'first': {'group_ko': '원자재', 'share_pct': 41.2},
                     'second': {'group_ko': '금리', 'share_pct': 18.0},
                     'prior': '주식', 'changed': True}
    assert any('주도' in x for x in check(BODY, pc))


def test_a_changed_leading_force_is_satisfied_by_its_marker():
    pc = _pc()
    pc['drivers'] = {'first': {'group_ko': '원자재', 'share_pct': 41.2},
                     'second': {'group_ko': '금리', 'share_pct': 18.0},
                     'prior': '주식', 'changed': True}
    html = BODY + '<p data-driver="1">시장을 끄는 힘이 주식에서 원자재로 넘어갔습니다.</p>'
    assert check(html, pc) == []


def test_an_empty_driver_marker_does_not_satisfy_the_rule():
    pc = _pc()
    pc['drivers'] = {'first': {'group_ko': '원자재', 'share_pct': 41.2},
                     'second': {'group_ko': '금리', 'share_pct': 18.0},
                     'prior': {'first': '주식', 'second': '금리'}, 'changed': True}
    html = BODY + '<i data-driver="x"></i>'
    assert check(html, pc) != []


def test_a_scorecard_claim_with_no_scorecard_at_all_fails_closed():
    """성적표 파일을 못 읽었다는 것은 「표본이 충분하다」는 뜻이 아니다."""
    html = BODY + '<p data-scorecard="1">확대 판단은 70% 맞았습니다.</p>'
    assert check(html, _pc(), scorecard=None) != []
