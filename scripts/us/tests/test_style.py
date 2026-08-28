from us import style as S
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


def _wrap(*paras):
    return "<html><body>" + "".join("<p>%s</p>" % p for p in paras) + "</body></html>"


def _keys(html):
    return {f["key"] for f in S.findings(html)}


def test_transliterated_jargon_with_plain_korean_is_flagged():
    """풀어 쓸 수 있는 외래어는 한 번만 나와도 잡는다.

    2026-08-26 사용자 지시 — 「브레드스 확산 트리거같은 뭔 소린지 모르는 용어」.
    이 말들은 한국어 대응이 이미 있어서 굳이 음차할 이유가 없다.
    """
    html = _wrap("코스피는 브레드스가 좋아졌고 반도체가 아웃퍼폼했습니다.")
    found = [f for f in S.findings(html) if f["key"] == "jargon"]
    assert found, "브레드스·아웃퍼폼이 안 잡혔다"
    assert "브레드스" in found[0]["message"]
    assert "상승 종목 비율" in found[0]["message"], "풀어 쓸 말을 알려줘야 한다"


def test_plain_korean_alternative_passes():
    html = _wrap("코스피는 오른 종목이 늘었고 반도체가 시장보다 더 올랐습니다.")
    assert "jargon" not in _keys(html)


def test_technical_term_needs_gloss_on_first_use():
    """설명하면 쓸 수 있는 말 — 첫 등장에 풀이가 없으면 잡는다."""
    bare = _wrap("장기물 기간프리미엄이 올랐습니다.")
    assert "jargon_gloss" in _keys(bare)
    glossed = _wrap("장기물 기간프리미엄, 즉 만기가 길어 감수하는 위험의 대가가 올랐습니다.")
    assert "jargon_gloss" not in _keys(glossed)


def test_gloss_in_parenthesis_counts():
    html = _wrap("기간프리미엄(만기가 길수록 더 얹어 받는 값)이 올랐습니다.")
    assert "jargon_gloss" not in _keys(html)


def test_stacked_jargon_in_one_sentence_is_flagged():
    """한 문장에 낯선 말이 겹치면 풀이가 있어도 못 읽는다 — 사용자 예시가 이 형태다."""
    html = _wrap("레짐은 유지되나 확산지수가 트리거를 밑돌아 스탠스를 좁힙니다.")
    found = [f for f in S.findings(html) if f["key"] == "jargon_stack"]
    assert found


def test_jargon_ignores_tables_and_headings():
    html = ("<html><body><h2>브레드스</h2><table><tr><td>아웃퍼폼</td></tr></table>"
            "<p>오늘은 오른 종목이 더 많았습니다.</p></body></html>")
    assert "jargon" not in _keys(html)


def test_gloss_message_picks_the_right_particle():
    """「멀티플가」처럼 조사가 틀리면 검사 자체가 기계 티를 낸다."""
    assert S._subject_josa('멀티플') == '이'
    assert S._subject_josa('레짐') == '이'
    assert S._subject_josa('컨센서스') == '가'


# ── codex 검토(2026-08-26)가 잡은 오탐들 ────────────────────────────────────
def test_jargon_does_not_match_inside_longer_korean_words():
    """부분 문자열로 세면 멀쩡한 낱말이 걸린다 — 「베타테스트」의 「베타」."""
    assert "jargon" not in _keys(_wrap("서비스는 베타테스트를 시작했습니다."))
    assert "jargon_gloss" not in _keys(_wrap("서비스는 베타테스트를 시작했습니다."))


def test_jargon_matches_with_korean_particle_attached():
    """조사가 붙은 형태는 잡아야 한다 — 「브레드스가」·「인버전이」."""
    assert "jargon" in _keys(_wrap("브레드스가 나빠졌습니다."))
    assert "jargon" in _keys(_wrap("커브 인버전이 깊어졌습니다."))


def test_english_jargon_is_case_insensitive():
    for form in ("breadth", "Breadth", "BREADTH"):
        assert "jargon" in _keys(_wrap("%s가 나빠졌습니다." % form)), form


def test_numeric_parenthesis_is_not_a_gloss():
    """「기간프리미엄(3.2%)」은 뜻을 푼 것이 아니다."""
    assert "jargon_gloss" in _keys(_wrap("기간프리미엄(3.2%)이 올랐습니다."))
    assert "jargon_gloss" in _keys(_wrap("기간프리미엄(AAPL)이 올랐습니다."))


def test_one_terms_gloss_does_not_excuse_another():
    """문단을 이어 붙여 훑으면 남의 풀이가 내 풀이로 셈된다."""
    html = _wrap("베타(지수가 1% 움직일 때 이 종목이 얼마나 움직이나)를 봅니다.",
                 "레짐은 그대로입니다.")
    found = [f for f in S.findings(html) if f["key"] == "jargon_gloss"]
    assert found and "레짐" in found[0]["message"]
    assert "베타" not in found[0]["message"]


def test_gloss_must_be_in_the_same_sentence():
    html = _wrap("레짐은 그대로입니다. 참고로 이것은 국면을 뜻하는 말입니다.")
    assert "jargon_gloss" in _keys(html)


def test_overlapping_terms_count_once():
    """「디스인버전」 하나를 「인버전」까지 둘로 세면 안 된다."""
    assert "jargon_stack" not in _keys(_wrap("디스인버전이 진행됐습니다."))


def test_caption_paragraphs_are_not_checked():
    html = '<html><body><p class="caption">breadth 자료입니다.</p>' \
           '<p>오늘은 오른 종목이 더 많았습니다.</p></body></html>'
    assert "jargon" not in _keys(html)


def test_subject_josa_handles_empty_and_non_hangul():
    assert S._subject_josa("") == "이"
    assert S._subject_josa("breadth") == "이"


def test_stack_counts_distinct_terms_not_repeats():
    """같은 말을 두 번 쓴 것은 겹침이 아니다 — 실측 KR 08-24에서 나온 오탐."""
    assert "jargon_stack" not in _keys(
        _wrap("비철금속(breadth 65%)과 전기제품(breadth 58%)이 올랐습니다."))
    assert "jargon_stack" in _keys(
        _wrap("레짐은 그대로지만 확산지수가 밀렸습니다."))


def test_trigger_and_stance_are_ordinary_market_words():
    """2026-08-28 사용자 지시로 COMMON으로 옮겼다 — 시장 기사에 흔한 말이라
    풀이를 요구하면 오히려 글이 늘어진다. 2026-08-26에는 GLOSS였다."""
    assert "jargon_gloss" not in _keys(_wrap("확대 트리거를 넘어섰습니다."))
    assert "jargon_gloss" not in _keys(_wrap("연준 스탠스가 바뀌었습니다."))


def test_jargon_matches_inside_korean_compounds():
    """뒤에 뭐가 붙어도 여전히 그 말이다 — 「브레드스발」·「프록시성」.

    예시가 2026-08-28에 바뀌었다: 원래 쓰던 「밸류에이션발」·「숏커버성」·
    「캐리트레이드」는 이제 COMMON이라 검사 대상이 아니다. 검사하는 것은
    분류가 아니라 **접미사가 붙어도 낱말을 찾아내는 능력**이므로, 여전히
    걸려야 할 말로 예시만 옮겼다.
    """
    for text in ("브레드스발 반등이었습니다.", "프록시성 지표에 그쳤습니다.",
                 "인버전발 우려가 커졌습니다.", "레짐성 변화로 보입니다."):
        assert "jargon" in _keys(_wrap(text)) or "jargon_gloss" in _keys(_wrap(text)), text


def test_known_compounds_that_are_not_jargon_pass():
    """「베타테스트」의 「베타」는 주가 민감도가 아니다."""
    assert "jargon" not in _keys(_wrap("서비스는 베타테스트를 시작했습니다."))
    assert "jargon_gloss" not in _keys(_wrap("서비스는 베타테스트를 시작했습니다."))


def test_uncommon_particles_still_match():
    for text in ("브레드스마저 나빠졌습니다.", "브레드스조차 밀렸습니다.",
                 "브레드스밖에 남지 않았습니다."):
        assert "jargon" in _keys(_wrap(text)), text


def test_gloss_must_follow_the_term_immediately():
    """멀리 떨어진 남의 괄호가 이 말의 풀이로 셈되면 안 된다."""
    html = _wrap("레짐은 유지되나 삼성전자(005930)가 밀렸습니다.")
    assert "jargon_gloss" in _keys(html)


def test_src_class_paragraph_is_excluded():
    html = '<html><body><p class="src">breadth 출처입니다.</p>' \
           '<p>오늘은 오른 종목이 더 많았습니다.</p></body></html>'
    assert "jargon" not in _keys(html)


def test_class_token_matching_is_exact():
    """`class="my-note-widget"`은 각주가 아니다 — 부분 문자열로 빼면 본문이 샌다."""
    html = '<html><body><p class="my-note-widget">breadth가 나빠졌습니다.</p></body></html>'
    assert "jargon" in _keys(html)


def test_spans_resolves_overlap_not_just_dedup():
    hits = S._spans("디스인버전이 진행됐습니다.", ["인버전", "디스인버전"])
    assert [term for _, _, term in hits] == ["디스인버전"]


def test_later_sentence_gloss_does_not_clear_earlier_term():
    """문장 분리가 완벽하지 않아도 풀이가 낱말 바로 뒤에 고정돼 있어 안 샌다."""
    html = _wrap("레짐 상승. 베타(지수 대비 민감도)는 낮아졌습니다.")
    found = [f for f in S.findings(html) if f["key"] == "jargon_gloss"]
    assert found and "레짐" in found[0]["message"]


# ── 업계용어·경제뉴스 상용어는 그대로 쓴다 (2026-08-28 사용자 지시) ──────────
# 「어려운 말」의 기준은 «독자가 처음 보는 말»이지 «외래어»가 아니다. 경제
# 뉴스를 읽는 사람이 이미 수없이 본 말까지 풀어 쓰면 글이 유치해진다.

def test_terms_common_in_economic_news_pass_untouched():
    for text in ("컨센서스를 밑돌았습니다.", "밸류에이션 부담이 커졌습니다.",
                 "가이던스를 낮췄습니다.", "모멘텀이 살아났습니다.",
                 "멀티플이 낮아졌습니다.", "리스크온 흐름이 이어졌습니다.",
                 "반도체가 아웃퍼폼했습니다.", "비중은 오버웨이트를 유지합니다.",
                 "커브가 스티프닝했습니다.", "숏커버가 들어왔습니다.",
                 "기대인플레가 올랐습니다.", "확대 트리거를 넘어섰습니다.",
                 "연준 스탠스가 바뀌었습니다.", "익스포저를 줄였습니다."):
        assert "jargon" not in _keys(_wrap(text)), text
        assert "jargon_gloss" not in _keys(_wrap(text)), text


def test_common_terms_do_not_count_toward_a_stacked_sentence():
    html = _wrap("컨센서스를 밑돌았지만 밸류에이션 부담이 줄어 모멘텀은 살아났습니다.")
    assert "jargon_stack" not in _keys(html)


def test_words_a_news_reader_has_never_seen_are_still_flagged():
    """사용자가 처음 문제 삼은 말은 그대로 걸려야 한다."""
    found = [f for f in S.findings(_wrap("브레드스가 좋아졌습니다.")) if f["key"] == "jargon"]
    assert found and "상승 종목 비율" in found[0]["message"]


def test_house_coinages_are_still_flagged():
    for text in ("컨빅션이 높습니다.", "프록시로 삼았습니다.", "바텀아웃 신호입니다.",
                 "캐치업 랠리였습니다."):
        assert "jargon" in _keys(_wrap(text)), text


def test_genuinely_specialist_terms_still_need_one_gloss():
    assert "jargon_gloss" in _keys(_wrap("장기물 기간프리미엄이 올랐습니다."))
    assert "jargon_gloss" in _keys(_wrap("레짐은 그대로입니다."))
    assert "jargon_gloss" in _keys(_wrap("확산지수가 밀렸습니다."))


def test_a_word_that_merely_contains_a_flagged_term_passes():
    """「프록시서버」의 「프록시」는 대리 지표가 아니다 — NOT_JARGON이 막는다."""
    assert "jargon" not in _keys(_wrap("프록시서버를 거쳐 접속합니다."))
    assert "jargon" in _keys(_wrap("프록시로 삼았습니다."))
