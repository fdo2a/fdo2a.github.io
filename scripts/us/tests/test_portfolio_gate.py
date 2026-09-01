"""모의 포트폴리오 발행 게이트.

막는 것: 데이터에 없는 수치, 고지 누락(모의·설정일·벤치마크·하루 시차),
슬리브 표식 누락, 표본 미달인데 연율·샤프 인쇄, 기준일 어긋남, 내부 용어 노출.
못 막는 것: 그 수치가 그 문장의 지표에 속하는지 — 사람이 잡는다.
"""
import pytest

from us import portfolio as P
from us import portfolio_gate as G


def _perf():
    rows, nav, bench = [], P.BASE_NAV, P.BASE_NAV
    for i in range(1, 13):
        nav *= 1.002
        bench *= 1.001
        rows.append({'report_date': f'2026-08-{i + 13:02d}', 'nav': nav,
                     'ret_pct': 0.2, 'bench_nav': bench, 'bench_ret_pct': 0.1,
                     'active_pct': 0.1,
                     'contrib': {k: 0.0 for k in P.SLEEVE_ORDER},
                     'weights': P.sleeve_weights({'equities': 1, 'metals': 2}),
                     'grades': {**P.NEUTRAL_GRADES, 'equities': 1, 'metals': 2},
                     'rebalanced': False})
    s = P.summarize(rows)
    s['report_date'] = '2026-08-31'
    return s


def _book(as_of='2026-08-31'):
    return {'report_date': '2026-08-31', 'as_of': as_of, 'inception': '2026-08-14',
            'grades_from': '2026-08-28', 'gaps': []}


def _section(perf, extra='', markers=('basis', 'lag', 'perf')):
    rows = ''.join(
        f'<tr><td><span data-sleeve="{w["sleeve"]}">{w["label"]}</span></td>'
        f'<td>{w["weight_pct"]:.1f}%</td><td>{w["neutral_pct"]:.1f}%</td></tr>'
        for w in perf['weights'] if w['weight_pct'] > 0)
    itd = perf['returns']['itd']
    blocks = {
        'basis': '<p data-portfolio="basis">2026-08-14 설정한 모의 운용입니다. '
                 '벤치마크는 모든 등급이 중립인 같은 상품 구성입니다.</p>',
        'lag': '<p data-portfolio="lag">오늘 바뀐 등급은 다음 거래일 종가에 '
               '반영됩니다.</p>',
        'perf': f'<p data-portfolio="perf">설정 이후 {itd["portfolio"]:.2f}% '
                f'올라 벤치마크를 {itd["active"]:.2f}%포인트 앞섭니다.</p>',
    }
    body = ''.join(blocks[m] for m in markers)
    return ('<h2>모의 포트폴리오</h2><div class="card">' + body
            + f'<table>{rows}</table>' + extra + '</div>')


def _doc(section):
    return ('<html><body><main><h2>주식</h2><p>시황입니다.</p>'
            + section + '<h2>주목 섹터·종목</h2><p>끝.</p></main></body></html>')


def check(section_html, perf=None, book=None, report_date='2026-08-31'):
    perf = perf or _perf()
    return G.check(_doc(section_html), book or _book(), perf, report_date)


def test_a_well_formed_section_passes():
    perf = _perf()
    assert check(_section(perf), perf) == []


def test_a_missing_section_fails():
    assert any('섹션' in e for e in check('<h2>다른 섹션</h2><p>없다.</p>'))


@pytest.mark.parametrize('drop', ['basis', 'lag', 'perf'])
def test_every_required_marker_is_required(drop):
    perf = _perf()
    keep = tuple(m for m in ('basis', 'lag', 'perf') if m != drop)
    errs = check(_section(perf, markers=keep), perf)
    assert any(drop in e for e in errs)


def test_the_paper_disclosure_cannot_be_dropped():
    perf = _perf()
    sec = _section(perf).replace('모의 운용입니다', '운용입니다')
    assert any('모의' in e for e in check(sec, perf))


def test_the_inception_date_must_be_on_the_page():
    perf = _perf()
    sec = _section(perf).replace('2026-08-14 설정한', '얼마 전 설정한')
    assert any('설정일' in e for e in check(sec, perf))


def test_the_benchmark_must_be_defined():
    perf = _perf()
    sec = _section(perf).replace('중립인', '평범한')
    assert any('벤치마크' in e for e in check(sec, perf))


def test_the_one_session_lag_must_be_stated():
    perf = _perf()
    sec = _section(perf).replace('다음 거래일 종가에 반영됩니다', '이미 반영돼 있습니다')
    assert any('시차' in e for e in check(sec, perf))


def test_every_held_sleeve_needs_its_marker():
    perf = _perf()
    sec = _section(perf).replace('<span data-sleeve="metals">', '<span>')
    assert any('metals' in e for e in check(sec, perf))


def test_an_invented_number_is_caught():
    perf = _perf()
    assert any('데이터에 없는 수치' in e
               for e in check(_section(perf, extra='<p>수익률은 37.42%였습니다.</p>'),
                              perf))


def test_a_number_that_is_in_the_data_passes():
    perf = _perf()
    nav = perf['nav']
    assert check(_section(perf, extra=f'<p>기준가는 {nav:,.2f}입니다.</p>'), perf) == []


def test_a_short_record_may_not_annualise():
    perf = _perf()
    assert perf['insufficient'] is True
    errs = check(_section(perf, extra='<p>연율로 환산하면 크게 늘어납니다.</p>'), perf)
    assert any('표본' in e for e in errs)


def test_a_long_record_may_discuss_risk():
    perf = _perf()
    perf['insufficient'] = False
    assert check(_section(perf, extra='<p>변동성은 낮았습니다.</p>'), perf) == []


def test_a_stale_book_must_say_so():
    perf, book = _perf(), _book(as_of='2026-08-27')
    errs = check(_section(perf), perf, book)
    assert any('결측' in e for e in errs)
    sec = _section(perf, extra='<p>8월 28일은 종가 결측으로 원장에 담지 않았습니다.</p>')
    assert [e for e in check(sec, perf, book) if '결측' in e] == []


def test_a_book_dated_to_another_session_fails_closed():
    perf = _perf()
    errs = G.check(_doc(_section(perf)), _book(), perf, '2026-09-01')
    assert any('기준일' in e for e in errs)


def test_a_missing_book_fails_closed_rather_than_passing():
    assert any('데이터' in e for e in G.check(_doc('<p>x</p>'), None, None, '2026-08-31'))


def test_internal_vocabulary_may_not_reach_the_page():
    perf = _perf()
    errs = check(_section(perf, extra='<p>portfolio_perf.json 을 참고했습니다.</p>'),
                 perf)
    assert any('내부 용어' in e for e in errs)


def test_banned_words_still_apply_here():
    perf = _perf()
    errs = check(_section(perf, extra='<p>바이사이드 관점입니다.</p>'), perf)
    assert any('금지 어휘' in e for e in errs)


# ── 2026-09-01 codex 검토에서 뚫린 경로들 ───────────────────────────────
def test_a_level_may_not_be_printed_as_a_return():
    """기준가 988.36 이 「988.36% 올랐다」로 통과하던 구멍."""
    perf = _perf()
    nav = perf['nav']
    errs = check(_section(perf, extra=f'<p>설정 이후 {nav:.2f}% 올랐습니다.</p>'), perf)
    assert any('데이터에 없는' in e or '단위' in e for e in errs)


def test_a_bare_integer_is_checked_too():
    """단위 없는 숫자를 검사에서 빼면 창작한 정수가 그대로 실린다."""
    perf = _perf()
    assert any('데이터에 없는' in e
               for e in check(_section(perf, extra='<p>기준가는 777입니다.</p>'), perf))
    assert any('데이터에 없는' in e
               for e in check(_section(perf, extra='<p>기준가는 777.7입니다.</p>'),
                              perf))


def test_a_second_hidden_section_is_refused():
    """숨은 사본이 검사를 통과하고 보이는 쪽이 창작을 싣던 구멍."""
    perf = _perf()
    doc = _doc('<div style="display:none">' + _section(perf) + '</div>'
               + _section(perf, extra='<p>수익률은 37.42%였습니다.</p>'))
    assert any('두 번' in e or '중복' in e
               for e in G.check(doc, _book(), perf, '2026-08-31'))


def test_a_snapshot_dated_apart_from_its_ledger_fails():
    perf = _perf()
    perf['report_date'] = '2026-08-27'
    assert any('원장' in e for e in check(_section(perf), perf))


def test_the_stale_date_itself_must_be_named():
    """「결측」 한 단어로 고지 의무가 끝나던 구멍."""
    perf, book = _perf(), _book(as_of='2026-08-27')
    perf['report_date'] = '2026-08-27'
    book['gaps'] = ['2026-08-28']
    sec = _section(perf, extra='<p>결측입니다.</p>')
    errs = check(sec, perf, book)
    assert any('2026-08-27' in e or '2026-08-28' in e for e in errs)
    ok = _section(perf, extra='<p>8월 28일 종가가 결측이라 8월 27일에서 멈췄습니다.</p>')
    assert [e for e in check(ok, perf, book) if '결측' in e or '멈춘' in e] == []


def test_an_empty_promise_does_not_satisfy_the_performance_block():
    perf = _perf()
    sec = _section(perf, markers=('basis', 'lag'))
    sec = sec.replace('<table>',
                      '<p data-portfolio="perf">성과 수치는 다음에 '
                      '확인하겠습니다.</p><table>')
    assert any('perf' in e for e in check(sec, perf))


def test_english_risk_words_are_banned_too_while_the_record_is_short():
    perf = _perf()
    errs = check(_section(perf, extra='<p>CAGR 기준으로는 다릅니다.</p>'), perf)
    assert any('표본' in e for e in errs)


def test_the_frozen_book_must_say_the_grades_did_not_arrive():
    perf, book = _perf(), _book()
    book['stance_frozen'] = True
    assert any('동결' in e for e in check(_section(perf), perf, book))


# ── 2026-09-01 codex 2차 검토 ───────────────────────────────────────────
def test_a_level_relabelled_in_hangul_percent_is_caught():
    perf = _perf()
    nav = perf['nav']
    errs = check(_section(perf, extra=f'<p>설정 이후 {nav:.2f}퍼센트입니다.</p>'), perf)
    assert any('비율' in e for e in errs)


def test_basis_points_have_no_business_in_this_section():
    """-1.16% 를 -1.16bp 로 바꿔 다는 100배 오류가 통과하던 구멍."""
    perf = _perf()
    itd = perf['returns']['itd']['portfolio']
    errs = check(_section(perf, extra=f'<p>손익은 {itd:.2f}bp입니다.</p>'), perf)
    assert any('bp' in e for e in errs)


def test_a_return_reused_as_a_bare_level_is_caught():
    perf = _perf()
    itd = perf['returns']['itd']['portfolio']
    errs = check(_section(perf, extra=f'<p>기준가는 {itd:.2f}입니다.</p>'), perf)
    assert any('데이터에 없는' in e for e in errs)


def test_inline_markup_cannot_hide_a_duplicate_heading():
    perf = _perf()
    marked = _section(perf).replace('<h2>모의 포트폴리오</h2>',
                                    '<h2><span>모의 포트폴리오</span></h2>')
    doc = _doc('<div style="display:none">' + marked + '</div>'
               + _section(perf, extra='<p>수익률은 37.42%였습니다.</p>'))
    assert any('두 번' in e for e in G.check(doc, _book(), perf, '2026-08-31'))


def test_a_book_with_no_as_of_cannot_slip_past_the_freshness_checks():
    perf, book = _perf(), _book()
    del book['as_of']
    assert any('기준일' in e or 'as_of' in e for e in check(_section(perf), perf, book))


def test_an_empty_ledger_has_nothing_to_publish():
    perf = _perf()
    section = _section(perf)
    perf['sessions'] = 0
    assert any('비어' in e for e in check(section, perf))


def test_more_risk_vocabulary_is_covered():
    perf = _perf()
    for word in ('표준편차', 'Calmar', '정보비율', '트래킹 에러'):
        errs = check(_section(perf, extra=f'<p>{word} 기준으로는 다릅니다.</p>'), perf)
        assert any('표본' in e for e in errs), word


# ── 2026-09-01 codex 3차 검토 ───────────────────────────────────────────
def test_the_applied_book_date_must_match_the_page():
    """발행본이 「8월 31일에 정한 등급」이라 썼는데 정본은 8월 28일이던 실제 모순."""
    perf, book = _perf(), _book()
    sec = _section(perf).replace('다음 거래일 종가에 반영됩니다.',
                                 '다음 거래일 종가에 반영됩니다. 지금 비중은 '
                                 '8월 31일에 정한 등급에서 나왔습니다.')
    assert any('2026-08-28' in e for e in check(sec, perf, book))
    ok = _section(perf).replace('다음 거래일 종가에 반영됩니다.',
                                '다음 거래일 종가에 반영됩니다. 지금 비중은 '
                                '8월 28일에 정한 등급에서 나왔습니다.')
    assert check(ok, perf, book) == []


@pytest.mark.parametrize('bad', ['1000BP', '1000 베이시스 포인트', '1e3%', '−0.02%'])
def test_odd_unit_spellings_do_not_slip_through(bad):
    perf = _perf()
    errs = check(_section(perf, extra=f'<p>수치는 {bad}입니다.</p>'), perf)
    assert errs, bad


# ── 2026-09-01 codex 4차 ────────────────────────────────────────────────
@pytest.mark.parametrize('claim', ['8월31일에 정한 등급', '2026-08-31에 정한 등급'])
def test_every_spelling_of_a_wrong_applied_date_is_caught(claim):
    perf, book = _perf(), _book()
    sec = _section(perf).replace('다음 거래일 종가에 반영됩니다.',
                                 f'다음 거래일 종가에 반영됩니다. 지금 비중은 {claim}에서 '
                                 '나왔습니다.')
    assert any('등급 책의 날짜' in e for e in check(sec, perf, book))


def test_a_second_wrong_claim_after_a_right_one_is_caught():
    perf, book = _perf(), _book()
    sec = _section(perf).replace(
        '다음 거래일 종가에 반영됩니다.',
        '다음 거래일 종가에 반영됩니다. 지금 비중은 8월 28일에 정한 등급입니다. '
        '사실은 8월 31일에 정한 등급입니다.')
    assert any('등급 책의 날짜' in e for e in check(sec, perf, book))


def test_a_unicode_minus_without_a_space_keeps_its_sign():
    """「손익은−0.02%」의 부호가 이음표 제거 규칙에 지워지던 구멍."""
    perf = _perf()
    errs = check(_section(perf, extra='<p>손익은−0.02%입니다.</p>'), perf)
    assert any('비율' in e for e in errs)


def test_a_padded_provenance_claim_does_not_slip_through():
    """날짜와 「정한 등급」 사이에 수식어를 끼워 넣어 빠져나가던 구멍."""
    perf, book = _perf(), _book()
    sec = _section(perf).replace(
        '다음 거래일 종가에 반영됩니다.',
        '다음 거래일 종가에 반영됩니다. 8월 31일에 위원회와 리스크 담당의 최종 합의를 '
        '거쳐 정한 등급입니다.')
    assert any('등급 책의 날짜' in e for e in check(sec, perf, book))


def test_no_amount_of_padding_gets_a_wrong_date_past_the_check():
    """고정 자수 창은 그 길이만큼만 막는다 — 창 자체를 없앤다."""
    perf, book = _perf(), _book()
    pad = '위원회와 리스크 담당이 여러 차례 검토한 끝에 ' * 4
    sec = _section(perf).replace(
        '다음 거래일 종가에 반영됩니다.',
        f'다음 거래일 종가에 반영됩니다. 8월 31일에 {pad}정한 등급입니다.')
    assert any('등급 책의 날짜' in e for e in check(sec, perf, book))


def test_a_decimal_point_does_not_end_a_sentence():
    """수익률의 소수점에서 문장이 갈리면 그 뒤의 잘못된 출처 주장이 빠져나간다."""
    perf, book = _perf(), _book()
    itd = perf['returns']['itd']['portfolio']
    sec = _section(perf).replace(
        '다음 거래일 종가에 반영됩니다.',
        f'다음 거래일 종가에 반영됩니다. 8월 31일에 설정 이후 수익률 {itd:.2f}%를 '
        '확인하고 정한 등급입니다.')
    assert any('등급 책의 날짜' in e for e in check(sec, perf, book))


@pytest.mark.parametrize('mark', ['.', '?', '!', '。'])
def test_a_number_before_a_sentence_end_still_ends_the_sentence(mark):
    """소수점을 보호하려다 「1,024.27? 8월 28일에…」를 한 문장으로 붙이면 안 된다."""
    perf, book = _perf(), _book()
    nav = perf['nav']
    sec = _section(perf).replace(
        '다음 거래일 종가에 반영됩니다.',
        f'다음 거래일 종가에 반영됩니다. 8월 31일 기준가는 {nav:,.2f}{mark} '
        '8월 28일에 정한 등급입니다.')
    assert [e for e in check(sec, perf, book) if '등급 책의 날짜' in e] == []


@pytest.mark.parametrize('split', [
    '2.<span>42</span>%', '2.<span></span>42%', '2.<br hidden>42%',
    '2.<span><b></b></span>42%', '2.<i></i><em></em>42%',
    '2.<div hidden></div>42%', '2.<span><div hidden></div></span>42%',
    '2.<div style="display:inline"></div>42%',
    '2.<span title=">"></span>42%', "2.<span title='>'></span>42%",
    '2.<!-- > -->42%', '2.<!--\n>\n-->42%', '2.<!-- > --!>42%',
])
def test_a_tag_inside_a_number_fails_closed(split):
    """태그가 공백으로 치환되면 「2.<span>42</span>%」가 두 수치로 쪼개져 검사를
    통째로 피해 간다 — 숫자 사이에 태그가 끼는 것 자체를 막는다. 하나만 막으면
    두 개를 붙이고, br 을 면제하면 br 로 쪼갠다(2026-09-01 codex 8·9차)."""
    perf = _perf()
    sec = _section(perf, extra=f'<p>수익률은 {split}입니다.</p>')
    assert any('태그' in e for e in check(sec, perf))


@pytest.mark.parametrize('markup', [
    '<table><tr><td>10</td><td>20</td></tr></table>',
    '<p>10</p><p>20</p>',
    '<ul><li>10</li><li>20</li></ul>',
    '<table><tr><td>10</td></tr><tr><td>20</td></tr></table>',
    '<p>10<strong>가</strong></p><p>20</p>',
])
def test_ordinary_block_boundaries_are_not_mistaken_for_split_numbers(markup):
    perf = _perf()
    assert [e for e in check(_section(perf, extra=markup), perf)
            if '태그' in e] == []
