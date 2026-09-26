"""US 주간 인사이트 게이트 — 규칙이 산문에만 있던 자리를 막는다."""
from us import weekly_insight_gate as G

BOX = "<p data-interp>금리가 오르는데 신용이 조용하다는 조합은 시장이 강한 지표를 할인율 상승으로만 받아들이고 이익 전망은 건드리지 않았다는 뜻이다. 금리가 오르는데 신용이 조용하다는 조합은 시장이 강한 지표를 할인율 상승으로만 받아들이고 이익 전망은 건드리지 않았다는 뜻이다. 금리가 오르는데 신용이 조용하다는 조합은 시장이 강한 지표를 할인율 상승으로만 받아들이고 이익 전망은 건드리지 않았다는 뜻이다. </p>"


def _diag(**over):
    d = {'anomalies': [
        {'name': 'USD/KRW', 'label': '원·달러', 'z': 3.1, 'flagged': True},
        {'name': 'S&P 500', 'label': 'S&P 500', 'z': 0.2, 'flagged': False}],
        'next_week': [{'date': '2026-09-29', 'name_ko': 'JOLTS 구인·이직'}],
        'fetch_status': {}}
    d.update(over)
    return d


def _html(diag_p='원·달러가 이번 주 가장 크게 움직였다.', review_p='가설 하나가 틀렸다.',
          question_ps=('시장은 인상을 반영했다.',), next_p='JOLTS 가 가를 것이다.'):
    q = ''.join(f'<p>{t}</p>' for t in question_ps)
    return (
        '<body data-register="da"><section class="card headline-card"><h1>제목</h1></section>'
        f'<section data-section="question"><h2>질문</h2>{q}<p data-alt>대안.</p>'
        '<p data-watch>관측.</p></section>'
        '<section data-section="diag"><h2>진단</h2><table><tr><td>S&P 500</td></tr></table>'
        f'<p>{diag_p}</p>{BOX}</section>'
        f'<section data-section="positioning"><h2>포지션</h2><p>해설.</p>{BOX}</section>'
        f'<section data-section="review"><h2>복기</h2><p>{review_p}</p></section>'
        f'<section data-section="next"><h2>다음</h2><p>{next_p}</p>{BOX}</section>'
        '<section data-section="appendix"><h2>부록</h2></section></body>')


def test_clean_draft_passes():
    assert G.check(_html(), _diag()) == []


def test_flagged_asset_left_out_of_the_diagnosis_prose_is_blocked():
    # W38: 원·달러 +3.35% 를 표에만 싣고 본문에서 한 번도 설명하지 않았다.
    out = G.check(_html(diag_p='주식은 조용했다.'), _diag())
    assert any('원·달러' in v for v in out)


def test_a_name_that_only_appears_in_a_table_does_not_count():
    d = _diag(anomalies=[{'name': 'S&P 500', 'label': 'S&P 500', 'z': 2.5, 'flagged': True}])
    assert any('S&P 500' in v for v in G.check(_html(diag_p='조용했다.'), d))


def test_gold_alias_does_not_match_rates_or_financials():
    d = _diag(anomalies=[{'name': 'Gold', 'label': '금', 'z': 2.4, 'flagged': True}])
    out = G.check(_html(diag_p='금리가 오르고 금융주가 밀렸다.'), d)
    assert any('금' in v for v in out)
    assert G.check(_html(diag_p='금값이 뛰었다.'), d) == []


def test_dormant_trigger_is_not_declared_a_bad_threshold():
    # W38 복기: 「이 트리거의 문턱 자체가 너무 빡빡하다고 봐야 한다」 — 작성 규칙 위반.
    out = G.check(_html(review_p='이 트리거의 문턱 자체가 너무 빡빡하다고 봐야 한다.'), _diag())
    assert any('문턱' in v for v in out)
    out = G.check(_html(review_p='다섯 트리거가 잠든 것은 문턱 설계를 다시 봐야 한다는 신호다.'), _diag())
    assert any('문턱' in v for v in out)


def test_weekday_by_weekday_paragraphs_are_blocked():
    ps = ('월요일에 반도체가 흔들렸다.', '화요일에는 유가가 뛰었다.', '수요일 FOMC 가 올렸다.')
    assert any('요일' in v for v in G.check(_html(question_ps=ps), _diag()))


def test_one_dated_paragraph_is_fine():
    ps = ('2026-09-16 FOMC 가 25bp 를 올렸다.', '시장은 그 뒤 추가 인상을 반영했다.')
    assert G.check(_html(question_ps=ps), _diag()) == []


def test_next_week_prose_must_touch_a_scheduled_event():
    out = G.check(_html(next_p='지켜볼 것이 많다.'), _diag())
    assert any('일정' in v for v in out)


def test_failed_snapshot_source_blocks_publication():
    out = G.check(_html(), _diag(fetch_status={'cftc:097741': 'error: timeout'}))
    assert any('cftc:097741' in v for v in out)


def test_analysis_sections_need_a_commentary_box():
    # 2026-09-26 사용자: 「지금은 단순 정리에 가까운 것 같은데 해설을 붙여」
    out = G.check(_html().replace(BOX, '', 1), _diag())
    assert any('해석' in v and 'diag' in v for v in out)


def test_a_one_line_commentary_is_not_enough():
    short = '<p data-interp>금리가 올랐다.</p>'
    out = G.check(_html().replace(BOX, short, 1), _diag())
    assert any('자다' in v for v in out)


def test_provenance_ignores_generated_tables_but_still_checks_prose():
    from us.period_gate import _check_provenance
    import re
    from us.post_check import body_text
    agg = {'commodities': {'WTI': {'start': 95.47, 'end': 94.09, 'pct': -1.4455}}}
    table = '<h3>원자재 — WTI</h3><table><tr><td>2026-09-21</td><td>92.13</td><td>-3.50%</td></tr></table>'
    prose = table.replace('<table>', '<p>').replace('</table>', '</p>')
    stripped = body_text(re.sub(r'<table\b.*?</table>', ' ', table, flags=re.S))
    assert _check_provenance(stripped, agg) == []
    assert _check_provenance(body_text(prose), agg)      # 산문으로 쓰면 여전히 잡는다
