"""US 주간 인사이트 게이트 — 규칙이 산문에만 있던 자리를 막는다."""
import pytest

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


def test_generated_tables_are_exempt_but_a_hand_written_table_is_checked():
    # codex #8: 인사이트 모드에서 표 전체를 이름-수치 검사에서 빼면 작성자가 넣은 표도 빠졌다.
    from us import weekly_insight as I
    from us.period_gate import _strip_generated_tables
    from us.tests.test_weekly_insight import _agg, _snap
    agg, snap = _agg(), _snap()
    diag = I.build(agg, snap, {'events': []}, [])
    gen = I.render_tables(diag, agg)['performance']
    hand = '<table><tr><td>S&P 500</td><td>+4.035%</td></tr></table>'
    out = _strip_generated_tables(gen + hand, diag, agg)
    assert hand in out and '<table' not in out.replace(hand, '')   # 생성 표는 모두 빠지고 손 표만 남는다


# ── 2026-10-17 외부 피드백(W41) ─────────────────────────────────────────────

def _period(**over):
    return _diag(start_date='2026-10-05', end_date='2026-10-09', **over)


def test_a_question_section_that_walks_the_week_day_by_day_is_blocked():
    # W41 질문 절은 10월 5·6·7·8·9일을 차례로 짚었다 — 일간 다섯 편의 재서술이다.
    ps = ('10월 5일 나스닥이 올랐고 10월 6일 S&P가 올랐다.', '수요일에 금리가 정점을 찍었다.',
          '10월 8일 매출 보도가 나왔다.')
    out = G.check(_html(question_ps=ps), _period())
    assert any('네 날' in v for v in out)


def test_three_days_in_the_question_section_are_fine():
    ps = ('10월 8일 매출 보도가 나왔다.', '2026-10-09 광학주가 반등했다.', '수요일 금리 고점은 이틀 만에 가라앉았다.')
    assert not any('네 날' in v for v in G.check(_html(question_ps=ps), _period()))


def test_a_date_outside_the_week_does_not_count_toward_the_walk():
    ps = ('10월 5일과 10월 8일에 움직였다.', '10월 15일 TSMC 실적과 9월 25일 질문을 본다.')
    assert not any('네 날' in v for v in G.check(_html(question_ps=ps), _period()))


def test_relative_performance_written_as_a_fund_flow_is_blocked():
    # 자금 흐름 자료를 받지 않는다 — 가격이 갈린 것을 돈이 옮겨 간 것으로 쓰면 증거를 넘는다.
    for p in ('돈은 에너지·필수소비재·가치주로 옮겨 갔다.',
              '필수소비재 강세는 AI 하드웨어에서 빠진 돈이 머문 자리라고 본다.',
              '방어주로 자금이 몰렸다.'):
        html = _html(diag_p='원·달러가 움직였다. ' + p)
        assert G.check(html, _diag()) == [], p          # 막지 않는다 — 부정·인용도 걸리는 어휘라
        assert any('자금 이동' in v for v in G.warnings(html)), p


def test_ordinary_money_words_are_not_fund_flow_claims():
    for p in ('원·달러가 움직였다. 기업의 자금 조달 비용이 올랐다.',
              '원·달러가 움직였다. 돈을 버는 속도에 대한 기대가 내려갔다.'):
        assert not any('자금 이동' in v for v in G.warnings(_html(diag_p=p))), p


def test_a_long_narrative_draws_a_warning_not_a_block():
    long_p = '가' * (G.PROSE_WARN_CHARS + 50)
    html = _html(diag_p='원·달러가 움직였다. ' + long_p)
    assert G.check(html, _diag()) == []
    w = G.warnings(html)
    assert w and '6,000' in w[-1]
    assert G.warnings(_html()) == []


def test_the_length_count_skips_tables_captions_and_the_generated_review():
    big = '나' * (G.PROSE_WARN_CHARS + 10)
    html = _html().replace('<section data-section="review"><h2>복기</h2>',
                           '<section data-section="review"><h2>복기</h2>'
                           f'<section class="card" data-research-summary="x"><p>{big}</p></section>'
                           f'<p class="caption">{big}</p>')
    assert G.warnings(html) == []


# ── 본문이 꼽은 다음 주 일정은 표에 있어야 한다 (W41: CPI·TSMC·은행 실적이 표에 없었다) ──

_W41_NEXT = [{'date': '2026-10-13', 'kind': 'release', 'name_ko': '기존주택 판매', 'watch': '추세 확인'},
             {'date': '2026-10-15', 'kind': 'release', 'name_ko': '생산자물가(PPI)', 'watch': '추세 확인'},
             {'date': '2026-10-16', 'kind': 'expiry', 'name_ko': '지수 옵션 만기', 'watch': '만기 당일 수급'}]


def _nd(**over):
    return _period(next_week=_W41_NEXT, **over)


def _hn(diag, **kw):
    """조립기가 그린 다음 주 표를 넣은 본문."""
    from us import weekly_insight as I
    html = _html(**kw)
    return html.replace('<section data-section="next"><h2>다음</h2>',
                        '<section data-section="next"><h2>다음</h2>' + I._t_next(diag), 1)


def test_an_event_the_prose_names_for_next_week_must_be_in_the_table():
    nxt = '다음 주의 중심은 10월 14일 9월 CPI와 10월 15일 TSMC 실적이다. 기존주택 판매는 추세만 본다.'
    out = G.check(_hn(_nd(), next_p=nxt), _nd())
    assert any('CPI' in v for v in out)
    # 실적은 막지 않고 경고한다 — 주인 낱말 가려내기가 계속 틀렸다(codex 구현 검토 2회).
    assert not any('실적' in v for v in out)
    assert any('실적' in w for w in G.warnings(_hn(_nd(), next_p=nxt), _nd()))


def test_earnings_without_an_owner_word_are_not_an_event_claim():
    # W41: 「10월 16일 지수 옵션 만기가 실적 다음 날이라」 — 만기의 이야기다.
    nxt = '10월 16일 지수 옵션 만기가 실적 다음 날이라 움직임이 커 보일 수 있다. 기존주택 판매도 본다.'
    assert G.check(_hn(_nd(), next_p=nxt), _nd()) == []


def test_bank_earnings_on_a_day_with_only_a_housing_release_are_caught():
    nxt = '금리 민감 업종은 10월 13일 골드만삭스·JP모건 3분기 실적으로 시험받는다. 기존주택 판매도 본다.'
    assert any('실적' in w for w in G.warnings(_hn(_nd(), next_p=nxt), _nd()))
    ev = [{'date': '2026-10-13', 'name': '골드만삭스·JP모건 3분기 실적', 'watch': '순이자이익',
           'stake': '금융주 강세 지속'}]
    d = _nd(next_events=ev)
    assert G.check(_hn(d, next_p=nxt), d) == []
    assert not any('실적' in w for w in G.warnings(_hn(d, next_p=nxt), d))


def test_one_matching_event_does_not_excuse_another_in_the_same_sentence():
    nxt = '10월 15일 TSMC 실적과 생산자물가(PPI)를 본다. 기존주택 판매도 본다.'
    assert G.check(_hn(_nd(), next_p=nxt), _nd()) == []
    assert any('실적' in w for w in G.warnings(_hn(_nd(), next_p=nxt), _nd()))


def test_a_post_row_and_a_calendar_row_satisfy_the_check():
    nxt = '10월 15일 TSMC 실적과 생산자물가(PPI)를 본다. 10월 16일 만기가 겹친다.'
    ev = [{'date': '2026-10-15', 'name': 'TSMC 3분기 실적', 'watch': 'AI 수요', 'stake': 'AI 수익화 기대'}]
    posts = {'2026-10-09': '<p>다음 주 10월 15일 TSMC 3분기 실적이 AI 수요를 가른다.</p>'}
    assert G.check(_hn(_nd(next_events=ev), next_p=nxt), _nd(next_events=ev), post_texts=posts) == []


def test_a_deadline_sentence_that_names_no_event_is_not_checked():
    nxt = '10월 15일까지 반등하지 못하면 판단을 낮춘다. 기존주택 판매는 추세만 본다.'
    assert G.check(_hn(_nd(), next_p=nxt), _nd()) == []


def test_a_post_row_must_appear_with_its_date_in_one_sentence_of_a_post():
    ev = [{'date': '2026-10-14', 'name': 'TSMC 3분기 실적', 'watch': 'AI 수요', 'stake': 'AI'}]
    # 그 발행본에 TSMC 와 10월 14일이 따로따로 있을 뿐이다(codex 2026-10-17 #3).
    posts = {'2026-10-09': '<p>10월 14일 CPI가 나온다.</p><p>10월 15일 TSMC 실적이 나온다.</p>'}
    out = G.check(_hn(_nd(next_events=ev), next_p='기존주택 판매를 본다.'), _nd(next_events=ev), post_texts=posts)
    assert any('발행본' in v for v in out)


def test_post_rows_are_not_rechecked_without_the_posts_and_bad_cells_are_blocked():
    ev = [{'date': '2026-10-15', 'name': 'TSMC 실적', 'watch': '가이던스 446억 달러', 'stake': 'AI'}]
    out = G.check(_hn(_nd(next_events=ev), next_p='기존주택 판매를 본다.'), _nd(next_events=ev))
    assert any('숫자' in v for v in out)



def test_dates_bind_to_their_own_events_not_to_the_sentence():
    # codex 2026-10-17 #2: 날짜를 문장째 합치면 서로 바뀐 날짜가 통과했다.
    cal = [{'date': '2026-10-14', 'kind': 'release', 'name_ko': '소비자물가(CPI)', 'watch': 'x'}]
    ev = [{'date': '2026-10-15', 'name': 'TSMC 3분기 실적', 'watch': 'AI 수요', 'stake': 'AI'}]
    d = _period(next_week=cal, next_events=ev)
    bad = _hn(d, next_p='10월 14일 TSMC 실적과 10월 15일 CPI를 본다. 소비자물가가 가른다.')
    assert any('CPI' in v for v in G.check(bad, d)) and any('실적' in w for w in G.warnings(bad, d))
    good = _hn(d, next_p='10월 14일 CPI와 10월 15일 TSMC 실적을 본다. 소비자물가가 가른다.')
    assert G.check(good, d) == [] and not any('실적' in w for w in G.warnings(good, d))


def test_real_w42_post_phrasing_does_not_trip_the_check():
    # 10/16 발행본 문장 그대로 — FOMC 는 대조하지 않고, 실적은 발행본 예고로 더하면 된다.
    cal = [{'date': '2026-10-23', 'kind': 'release', 'name_ko': '미시간대 소비자심리', 'watch': 'x'}]
    ev = [{'date': '2026-10-22', 'name': '웨스턴디지털 실적', 'watch': '저장장치 수요', 'stake': '메모리 약세'}]
    d = _diag(start_date='2026-10-12', end_date='2026-10-16', next_week=cal, next_events=ev)
    nxt = ('10월 22일 웨스턴디지털 실적과 27~28일 FOMC가 다음 분기점이다. '
           '10월 23일 10:00 ET(10월 23일 23:00 KST) 미시간대 소비자심리가 나온다.')
    posts = {'2026-10-16': '<p>10월 22일 웨스턴디지털 실적과 27~28일 FOMC가 다음 분기점이다.</p>'}
    assert G.check(_hn(d, next_p=nxt), d, post_texts=posts) == []
    # 회계 분기를 끼워도 주인은 날짜 바로 뒤 낱말이다(codex #3).
    nxt2 = '10월 22일 웨스턴디지털 회계 1분기 실적을 본다. 미시간대 소비자심리도 본다.'
    assert G.check(_hn(d, next_p=nxt2), d, post_texts=posts) == []


def test_an_invented_description_beside_a_real_name_is_not_in_the_posts():
    ev = [{'date': '2026-10-22', 'name': '웨스턴디지털 파산 신청', 'watch': 'x', 'stake': 'y'}]
    d = _diag(start_date='2026-10-12', end_date='2026-10-16', next_week=[], next_events=ev)
    posts = {'2026-10-16': '<p>10월 22일 웨스턴디지털 실적과 27~28일 FOMC가 다음 분기점이다.</p>'}
    out = G.check(_hn(d, next_p='웨스턴디지털을 본다.'), d, post_texts=posts)
    assert any('발행본' in v for v in out)


def test_the_headline_and_prose_after_the_research_summary_are_checked():
    d = _nd()
    h1 = _hn(d).replace('<h1>제목</h1>', '<h1>10월 14일 CPI가 가를 물가 기대</h1>')
    assert any('CPI' in v for v in G.check(h1, d))
    rv = _hn(d, review_p='x').replace(
        '<h2>복기</h2><p>x</p>',
        '<h2>복기</h2><section class="card" data-research-summary="f"><p>표</p></section>'
        '<p>10월 14일 CPI를 본다.</p>')
    assert any('CPI' in v for v in G.check(rv, d))


def test_a_removed_next_table_is_caught():
    d = _nd(next_events=[])          # 2026-10-17 조립기가 쓴 진단
    out = G.check(_html(next_p='기존주택 판매를 본다.'), d)
    assert any('다시 그린 표' in v for v in out)
    assert not any('다시 그린 표' in v for v in G.check(_hn(d, next_p='기존주택 판매를 본다.'), d))
    # 그 전 진단(키 없음)으로 발행한 4열 표는 다시 검사하지 않는다.
    assert not any('다시 그린 표' in v for v in G.check(_html(next_p='기존주택 판매를 본다.'), _nd()))


def test_only_the_first_indicator_after_a_date_is_that_days_event():
    nxt = '10월 15일 생산자물가(PPI)는 CPI가 낸 답을 한 번 더 확인한다. 기존주택 판매도 본다.'
    assert G.check(_hn(_nd(), next_p=nxt), _nd()) == []



_W42_POST = {'2026-10-16': '<p>10월 22일 웨스턴디지털 실적과 27~28일 FOMC가 다음 분기점이다.</p>'}


def _w42(ev):
    return _diag(start_date='2026-10-12', end_date='2026-10-16', next_week=[], next_events=ev)


def test_a_post_row_must_sit_right_after_its_own_date_in_the_post():
    # codex 재검토 #2: 같은 문장의 FOMC 가 10월 22일 일정으로 통과했다.
    d = _w42([{'date': '2026-10-22', 'name': 'FOMC', 'watch': 'x', 'stake': 'y'}])
    assert any('발행본' in v for v in G.check(_hn(d, next_p='FOMC를 본다.'), d, post_texts=_W42_POST))
    d = _w42([{'date': '2026-10-22', 'name': '웨스턴디지털 실적', 'watch': 'x', 'stake': 'y'}])
    assert G.check(_hn(d, next_p='웨스턴디지털을 본다.'), d, post_texts=_W42_POST) == []


def test_parentheses_do_not_launder_an_invented_description():
    # codex 재검토 #1: 괄호 안 회사 이름만 보면 「파산 신청(웨스턴디지털)」이 통과했다.
    d = _w42([{'date': '2026-10-22', 'name': '파산 신청(웨스턴디지털)', 'watch': 'x', 'stake': 'y'}])
    assert any('발행본' in v for v in G.check(_hn(d, next_p='웨스턴디지털을 본다.'), d, post_texts=_W42_POST))


def test_an_extra_table_in_the_next_section_is_caught():
    # codex 재검토 #5: 생성 표를 두고 표를 하나 더 끼우면 통과했다.
    d = _nd(next_events=[])
    html = _hn(d, next_p='기존주택 판매를 본다.').replace(
        '<p>기존주택 판매를 본다.</p>',
        '<table><tr><td>2026-10-22</td><td>웨스턴디지털 파산 신청</td></tr></table><p>기존주택 판매를 본다.</p>')
    assert any('다시 그린 표' in v for v in G.check(html, d))



def test_a_nested_section_cannot_hide_a_table():
    # codex 3차: 절 안의 <section> 이 바깥 절을 일찍 닫아 그 뒤 표가 대조에서 빠졌다.
    d = _nd(next_events=[])
    html = _hn(d, next_p='기존주택 판매를 본다.').replace(
        '<p>기존주택 판매를 본다.</p>',
        '<p>기존주택 판매를 본다.</p><section><h3>참고 일정</h3></section>'
        '<table><tr><td>2026-10-22</td><td>웨스턴디지털 파산 신청</td></tr></table>')
    assert any('다른 <section>' in v for v in G.check(html, d))
    # 생성된 연구 요약은 예외다.
    rv = _hn(d, next_p='기존주택 판매를 본다.').replace(
        '<h2>복기</h2>', '<h2>복기</h2><section class="card" data-research-summary="f"><p>표</p></section>')
    assert not any('다른 <section>' in v for v in G.check(rv, d))



@pytest.mark.parametrize('tag', ['<SECTION class="card">', '<Section>', '<section id="x">'])
@pytest.mark.parametrize('where', ['question', 'diag', 'positioning', 'review', 'next'])
def test_a_nested_section_is_caught_in_any_case_and_any_section(tag, where):
    d = _nd(next_events=[])
    html = _hn(d, next_p='기존주택 판매를 본다.')
    head = f'<section data-section="{where}">'
    i = html.index(head) + len(head)
    html = html[:i] + f'{tag}<h3>참고</h3></SECTION><table><tr><td>가짜</td></tr></table>' + html[i:]
    assert any('다른 <section>' in v for v in G.check(html, d))



def test_a_lookalike_summary_attribute_is_not_exempt():
    d = _nd(next_events=[])
    html = _hn(d, next_p='기존주택 판매를 본다.').replace(
        '<h2>복기</h2>', '<h2>복기</h2><SECTION data-research-summary-note="x"><h3>참고</h3></section>'
                       '<table><tr><td>가짜</td></tr></table>')
    assert any('다른 <section>' in v for v in G.check(html, d))
