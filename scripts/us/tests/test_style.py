from us.style import findings, sentences


def page(body):
    return f'<html><body><div class="doc">{body}</div></body></html>'


def keys(html):
    return {f['key'] for f in findings(html)}


def test_a_page_that_talks_like_a_person_passes():
    html = page('<p>코스피는 어제보다 0.8% 올랐습니다. 반도체가 지수를 끌어올렸고, '
                '외국인이 사흘 만에 순매수로 돌아섰습니다.</p>'
                '<p>다음 분기 실적이 이 흐름을 이어갈지 가릅니다. 저는 반도체 비중을 '
                '유지하겠습니다.</p>')
    assert findings(html) == []


def test_impersonal_passive_verdicts_are_counted():
    html = page('<p>수급이 개선된 것으로 읽힌다. 실적은 양호한 것으로 판정된다. '
                '금리는 하락 압력을 받는 것으로 해석된다.</p>')
    assert 'impersonal' in keys(html)


def test_one_or_two_passives_are_tolerated():
    html = page('<p>수급이 개선된 것으로 읽힌다. 나머지는 제가 직접 씁니다. '
                '반도체가 지수를 끌어올렸습니다.</p>')
    assert 'impersonal' not in keys(html)


def test_translationese_connectors_are_counted():
    html = page('<p>금리 상승에 따른 부담이 커졌습니다. 실적 부진에 따른 매도가 '
                '이어졌습니다. 환율 하락에 따른 수혜가 예상됩니다. '
                '수급 개선을 통한 반등이 나왔습니다.</p>')
    assert 'translationese' in keys(html)


def test_headline_style_labels_without_a_verb_are_caught():
    html = page('<p><strong>동인.</strong> 반도체가 올랐습니다.</p>'
                '<p><strong>크로스에셋 정합성.</strong> 신호가 엇갈립니다.</p>'
                '<p><strong>다음 촉매.</strong> 실적 발표입니다.</p>')
    assert 'nominal_label' in keys(html)


def test_a_label_that_is_a_real_sentence_is_fine():
    html = page('<p><strong>오늘은 반도체를 그대로 둡니다.</strong> 수급이 아직 '
                '무너지지 않았습니다.</p>')
    assert 'nominal_label' not in keys(html)


def test_four_sentences_ending_the_same_way_in_a_row_are_caught():
    html = page('<p>지수가 올랐다. 반도체가 끌었다. 외국인이 샀다. 거래대금도 늘었다.</p>')
    assert 'monotone' in keys(html)


def test_three_in_a_row_is_still_fine():
    html = page('<p>지수가 올랐다. 반도체가 끌었다. 외국인이 샀습니다.</p>')
    assert 'monotone' not in keys(html)


def test_the_same_paragraph_opener_over_and_over_is_caught():
    body = ''.join(f'<p>다만 {i}번째 이야기가 있습니다.</p>' for i in range(6))
    assert 'opener' in keys(page(body))


def test_noun_ending_sentences_are_counted():
    html = page('<p>방향을 잃은 상태다. 반등을 떠받친 모양새다. 차익실현이 '
                '이어지는 국면이다.</p>')
    assert 'noun_ending' in keys(html)


def test_tables_and_headings_are_not_prose():
    """표 안의 짧은 라벨을 개조식으로 세면 매일 오탐이 난다."""
    html = page('<h2>전략 코멘트</h2><table><tr><td>동인</td><td>수급</td></tr></table>')
    assert findings(html) == []


def test_sentences_splits_on_terminators_not_on_decimal_points():
    text = '코스피는 2,700.15로 올랐다. 코스닥은 뒤졌습니다.'
    assert sentences(text) == ['코스피는 2,700.15로 올랐다.', '코스닥은 뒤졌습니다.']


def test_every_finding_says_what_to_do():
    html = page('<p>수급이 개선된 것으로 읽힌다. 실적은 양호한 것으로 판정된다. '
                '금리는 하락한 것으로 해석된다.</p>')
    for f in findings(html):
        assert f['message'] and f['key'] and f['count'] >= 1
