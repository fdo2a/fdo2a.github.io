"""일본 일간 발행 게이트 — codex 설계 검토 #7·#8 재현을 하나씩 막는다."""
import copy

from japan import daily_gate as G
from japan import daily_render as R
from japan.tests.test_daily_render import SNAP, S

PROSE = {
    'comment': '<p>닛케이 225 는 <span data-ref="indices.nikkei.value">62,189.65</span> 로 '
               '<span data-ref="indices.nikkei.chg_pct">-0.8%</span> 내렸다. 반도체 장비주가 지수를 눌렀다.</p>',
    'today': '<p>오후 들어 낙폭을 줄였다.</p>',
    'equity': '<p>은행 업종은 0.4% 올랐다.</p>',
    'bonds': '<p>10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span> 로 '
             '<span data-ref="jgb.10Y.chg_bp">7.7bp</span> 내렸다.</p>',
    'yen': '<p>16:30 기준 달러/엔은 <span data-ref="fx.usdjpy.value">157.07</span> 엔이다.</p>',
    'macro': '<p>오늘 나온 지표는 없다.</p>',
    'news': '',
    'next': '<p>10월 30일 BOJ 결정문이 다음 확인 지점이다.</p>',
}


def body(prose=None, order=R.SECTIONS):
    prose = dict(PROSE, **(prose or {}))
    parts = ['<section class="card headline-card"><h1>제목</h1><p>요약.</p></section>']
    for s in order:
        tables = ''.join(f'<!--T:{t}-->' for t in R.PLACEHOLDERS.get(s, ()))
        parts.append(f'<section class="card" data-section="{s}"><h2>{R.TITLES[s]}</h2>{prose[s]}{tables}</section>')
    return '\n'.join(parts)


def html(prose=None, snap=SNAP, order=R.SECTIONS):
    return R.assemble(body(prose, order), {'title': '일본 증시 마감', 'summary': '요약'}, snap)


def check(h, snap=SNAP, name=f'{S}.html'):
    return G.check(h, snap, S, filename=name)


def test_clean_post_passes():
    assert check(html()) == []


def test_swapped_tenor_values_blocked():
    v = check(html({'bonds': '<p>10월 23일 기준 JGB 2년 금리는 <span data-ref="jgb.2Y.value">2.837%</span>, '
                             '10년은 <span data-ref="jgb.10Y.value">1.872%</span> 다.</p>'}))
    assert any('jgb.2Y.value' in m for m in v) and any('jgb.10Y.value' in m for m in v)


def test_core_value_outside_ref_blocked():
    v = check(html({'bonds': '<p>10월 23일 기준 JGB 2년 금리는 2.837% 다.</p>'}))
    assert any('data-ref' in m for m in v)


def test_wrong_unit_blocked():
    v = check(html({'bonds': '<p>10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837엔</span> 이다.</p>'}))
    assert any('단위' in m for m in v)


def test_stale_value_without_date_blocked():
    v = check(html({'bonds': '<p>JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span> 다.</p>'}))
    assert any('10월 23일' in m for m in v)


def test_today_jgb_wording_blocked():
    v = check(html({'bonds': '<p>10월 23일 기준, 오늘 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span> 다.</p>'}))
    assert any('오늘' in m for m in v)


def test_unknown_ref_blocked():
    v = check(html({'today': '<p><span data-ref="jgb.40Y.value">4.0%</span></p>'}))
    assert any('jgb.40Y.value' in m for m in v)


def test_invented_number_blocked():
    v = check(html({'today': '<p>거래대금은 4조 3,210억 엔이었다.</p>'}))
    assert any('43210' in m for m in v)


def test_unverified_marker_blocked():
    assert any('확인필요' in m for m in check(html({'today': '<p>[확인필요] 오후 반등.</p>'})))


def test_missing_register_blocked():
    h = html().replace('data-register="da"', '')
    assert any('data-register' in m for m in check(h))


def test_consensus_in_comment_blocked():
    v = check(html({'comment': PROSE['comment'] + '<p>지표는 시장 예상치를 웃돌았다.</p>'}))
    assert any('예상' in m for m in v)


def test_conditional_outlook_allowed():
    v = check(html({'comment': PROSE['comment'] + '<p>임금이 더 오르면 12월 인상 논의가 커질 수 있다.</p>'}))
    assert v == []


def test_order_mismatch_blocked():
    snap = copy.deepcopy(SNAP)
    snap['calendar']['event_day'] = [{'name_ko': 'BOJ 금융정책 결정문'}]
    v = check(html(snap=snap), snap)
    assert any('순서' in m for m in v)
    assert check(html(snap=snap, order=R.order(snap['calendar']['event_day'])), snap) == []


def test_signal_vocab_blocked():
    v = check(html({'comment': PROSE['comment'] + '<p>신호 집계로는 A 경로가 우세하다.</p>'}))
    assert any('주간' in m for m in v)


def test_contribution_wording_blocked():
    v = check(html({'equity': '<p>도쿄일렉트론이 지수 기여 하위였다.</p>'}))
    assert any('기여' in m for m in v)


def test_credit_missing_blocked():
    h = html().replace(R.BOJ_CREDIT.split('"')[0], 'X')
    assert any('크레디트' in m for m in check(h))


def test_incomplete_snapshot_blocked():
    snap = copy.deepcopy(SNAP)
    snap['complete'] = False
    assert any('complete' in m for m in check(html(snap=snap), snap))


def test_filename_session_mismatch_blocked():
    assert any('파일' in m for m in check(html(), name='2026-10-27.html'))


def test_buy_side_blocked():
    assert any('buy-side' in m for m in check(html({'today': '<p>buy-side 수급이 몰렸다.</p>'})))


def test_movers_checked():
    snap = copy.deepcopy(SNAP)
    snap['movers'] = {'report_date': S, 'groups': [{'id': 'g1', 'industry': '전기·정밀', 'direction': 'down',
                      'reasons': ['등락 하위'], 'members': [{'name': '어드밴테스트', 'change_pct': -6.2, 'close': 1.0}]}]}
    assert any('움직인 종목' in m for m in check(html(snap=snap), snap))
    ok = html({'equity': '<p data-mover="g1">어드밴테스트(-6.2%)가 내렸다 — 확인된 재료 없음.</p>'}, snap=snap)
    assert check(ok, snap) == []


def test_cli(tmp_path, capsys):
    import json
    import check_japan_daily as CLI
    d = tmp_path / 'japan' / 'data' / 'daily' / 'candidate'
    d.mkdir(parents=True)
    (d / f'{S}.json').write_text(json.dumps(SNAP, ensure_ascii=False), encoding='utf-8')
    post = tmp_path / 'japan' / 'daily'
    post.mkdir(parents=True)
    (post / f'{S}.html').write_text(html(), encoding='utf-8')
    assert CLI.main(['--session', S, '--root', str(tmp_path)]) == 0
    (post / f'{S}.html').write_text(html({'today': '<p>[확인필요]</p>'}), encoding='utf-8')
    assert CLI.main(['--session', S, '--root', str(tmp_path)]) == 1


def test_breadth_counts_allowed_from_snapshot():
    snap = copy.deepcopy(SNAP)
    snap['sector_breadth'] = {'total': 17, 'counted': 16, 'up': 13, 'down': 3, 'flat': 0}
    ok = html({'equity': '<p>업종 17개 가운데 13개가 올랐다.</p>'}, snap=snap)
    assert check(ok, snap) == []
    bad = html({'equity': '<p>업종 17개 가운데 14개가 올랐다.</p>'}, snap=snap)
    assert any('14' in m for m in check(bad, snap))


# ── codex 구현 검토 단계 B ─────────────────────────────────────────────────────

def test_explicit_sign_must_match():   # #3
    v = check(html({'today': '<p>닛케이는 <span data-ref="indices.nikkei.chg_pct">+0.8%</span> 올랐다.</p>'}))
    assert any('부호' in m for m in v)


def test_headline_invented_number_blocked():   # #5
    h = html().replace('<h1>제목</h1>', '<h1>닛케이 225, 100,000포인트 돌파</h1>')
    assert any('100000' in m for m in check(h))


def test_writer_table_rejected_by_assemble():   # #5
    b = body({'today': '<div class="tbl-scroll"><table><tr><td>99,999</td></tr></table></div>'})
    assert any('표' in e for e in R.validate_body(b, R.SECTIONS))


def test_hand_table_numbers_checked():   # #5
    h = html().replace('<p>오후 들어 낙폭을 줄였다.</p>',
                       '<p>오후 들어 낙폭을 줄였다.</p><table><tr><td>77,777</td></tr></table>', 1)
    assert '77,777' in h
    assert any('77777' in m for m in check(h))


def test_rounded_core_value_needs_ref():   # #6
    v = check(html({'yen': '<p>16:30 기준 달러/엔은 157.1엔이다.</p>'}))
    assert any('data-ref' in m for m in v)


MACRO_SNAP = copy.deepcopy(SNAP)
MACRO_SNAP['macro'] = [{'name_ko': '기업물가지수(전체)', 'status': 'released', 'period': '2026-09', 'value': 123.45,
                        'prev_period': '2026-08', 'prev_value': 123.0, 'yoy': 2.1, 'unit': 'CY2020 average=100'}]


def test_macro_value_needs_ref():   # #6
    v = check(html({'macro': '<p>9월 기업물가지수는 123.45 다.</p>'}, snap=MACRO_SNAP), MACRO_SNAP)
    assert any('data-ref' in m for m in v)
    ok = html({'macro': '<p>9월 기업물가지수는 <span data-ref="macro.0.value">123.45</span> 로 전년보다 '
                        '<span data-ref="macro.0.yoy">2.1%</span> 높다.</p>'}, snap=MACRO_SNAP)
    assert check(ok, MACRO_SNAP) == []


def test_macro_ref_requires_released():   # #6
    snap = copy.deepcopy(MACRO_SNAP)
    snap['macro'][0]['status'] = 'pending'
    v = check(html({'macro': '<p>9월 기업물가지수는 <span data-ref="macro.0.value">123.45</span> 다.</p>'}, snap=snap), snap)
    assert any('released' in m or '발표' in m for m in v)


def test_unit_outside_span_checked():   # #7
    v = check(html({'bonds': '<p>10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837</span>엔이다.</p>'}))
    assert any('단위' in m for m in v)


def test_macro_unit_from_snapshot():   # #7
    v = check(html({'macro': '<p>9월 기업물가지수는 <span data-ref="macro.0.value">123.45엔</span> 이다.</p>'},
                   snap=MACRO_SNAP), MACRO_SNAP)
    assert any('단위' in m for m in v)


MOVER_SNAP = copy.deepcopy(SNAP)
MOVER_SNAP['movers'] = {'report_date': S, 'groups': [{'id': 'g1', 'industry': '전기·정밀', 'direction': 'down',
                        'reasons': ['등락 하위'], 'members': [{'name': '어드밴테스트', 'change_pct': -6.2, 'close': 1.0}]}]}
NEWS = {'report_date': S, 'items': [{'guid': 'n1', 'summary_ko': '정부가 반도체 보조금 3,000억 엔을 줄이기로 했다.',
                                     'title': '補助金削減'}]}


def test_mover_cause_needs_citation():   # #8
    p = '<p data-mover="g1">어드밴테스트(-6.2%)는 정부 보조금 축소로 급락했다.</p>'
    v = G.check(html({'equity': p}, snap=MOVER_SNAP), MOVER_SNAP, S, filename=f'{S}.html', news=NEWS)
    assert any('data-cite' in m for m in v)


def test_mover_cite_must_exist_and_numbers_from_it():   # #8
    p = ('<p data-mover="g1" data-cite="n1">어드밴테스트(-6.2%)는 정부가 보조금 3,000억 엔을 줄인다는 소식에 '
         '내렸다.</p>')
    assert G.check(html({'equity': p}, snap=MOVER_SNAP), MOVER_SNAP, S, filename=f'{S}.html', news=NEWS) == []
    bad = p.replace('data-cite="n1"', 'data-cite="zz"')
    v = G.check(html({'equity': bad}, snap=MOVER_SNAP), MOVER_SNAP, S, filename=f'{S}.html', news=NEWS)
    assert any('zz' in m for m in v)


def test_metadata_digits_not_citable():
    snap = copy.deepcopy(SNAP)
    snap['calendar']['version'] = '9909ab'
    snap['ran_at'] = '2026-10-26T07:31:45.778812+00:00'
    snap['sectors'][1]['why'] = '공식 62285.61 vs yfinance 77777'
    v = check(html({'today': '<p>거래대금 9909억 엔, 778812주, 77777.</p>'}, snap=snap), snap)
    assert any('9909' in m for m in v) and any('778812' in m for m in v) and any('77777' in m for m in v)


def _naver_snap():
    snap = copy.deepcopy(SNAP)
    for t in ('2Y', '10Y'):
        snap['jgb'][t].update(period=S, prev_period='2026-10-23', source='naver')
    return snap


def test_today_jgb_allowed_for_same_session_naver():
    snap = _naver_snap()
    p = {'bonds': '<p>오늘 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span> 로 '
                  '<span data-ref="jgb.10Y.chg_bp">7.7bp</span> 내렸다.</p>'}
    assert check(html(p, snap), snap) == []


def test_today_wording_reverse_order_blocked_for_mof():
    v = check(html({'bonds': '<p>10월 23일 기준 JGB 10년 금리는 오늘 '
                             '<span data-ref="jgb.10Y.value">2.837%</span> 다.</p>'}))
    assert any('오늘' in m for m in v)


def test_today_call_rate_blocked_even_with_naver():
    snap = _naver_snap()
    v = check(html({'bonds': '<p>10월 22일 기준 콜금리는 오늘 '
                             '<span data-ref="call_rate.value">1.227%</span> 다.</p>'}, snap), snap)
    assert any('콜금리는 오늘' in m for m in v)


def test_today_after_decimal_blocked_for_mof_and_call():
    # 소수점은 문장 끝이 아니다(구현 검토 #1)
    v = check(html({'bonds': '<p>10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span>로 오늘 올랐다.</p>'}))
    assert any('JGB 는 오늘' in m for m in v)
    v = check(html({'bonds': '<p>10월 22일 기준 콜금리는 <span data-ref="call_rate.value">1.227%</span>로 오늘 올랐다.</p>'}))
    assert any('콜금리는 오늘' in m for m in v)


def test_today_in_any_jgb_sentence_blocked_for_mof():
    # 문장 단위 — 거리·동사 목록이 놓친 재검토 #1 입력. 「JGB와 오늘 증시」 오탐은 감수한다(문장을 나눈다)
    for text in ('10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span>이며 오늘 기준이다.',
                 '10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span>로 장중 정책 기대를 반영하면서 오늘 올랐다.',
                 '10월 23일 기준 JGB와 오늘 내수주는 다른 흐름이다.'):
        assert any('JGB 는 오늘' in m for m in check(html({'bonds': f'<p>{text}</p>'}))), text


def test_today_elsewhere_in_jgb_paragraph_blocked_for_mof():
    # 주어를 생략한 다음 문장·태그로 쪼갠 이름(재검토 2차 #1·#2)
    for text in ('10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span>다. 오늘 올랐다.',
                 '10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span>인가? 오늘 올랐다.',
                 '10월 23일 기준 J<span>GB</span> 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span>로 오늘 올랐다.'):
        assert any('JGB 는 오늘' in m for m in check(html({'bonds': f'<p>{text}</p>'}))), text


def test_today_in_separate_paragraph_allowed_for_mof():
    assert check(html({'bonds': '<p>10월 23일 기준 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span> 다.</p>'
                                '<p>오늘 증시는 다른 흐름이었다.</p>'})) == []


def test_naver_day_jgb_and_call_in_one_paragraph_allowed():
    snap = _naver_snap()
    p = {'bonds': '<p>오늘 JGB 10년 금리는 <span data-ref="jgb.10Y.value">2.837%</span> 다. '
                  '10월 22일 기준 콜금리는 <span data-ref="call_rate.value">1.227%</span> 다.</p>'}
    assert check(html(p, snap), snap) == []


def test_today_br_call_rate_blocked():
    # <br> 은 경계다 — 이어 붙이면 「오늘콜금리」 로 콜 검사를 우회한다(재검토 3차 #1)
    for tag in ('<br>', '<wbr>', '<img src="/icon.png" alt="">', '<span>', '</span>'):
        v = check(html({'bonds': f'<p>10월 22일 기준 오늘{tag}콜금리는 <span data-ref="call_rate.value">1.227%</span>다.</p>'}))
        assert any('콜금리는 오늘' in m for m in v), tag


def test_today_check_never_weaker_than_old_rule():
    # origin/main 의 규칙(태그를 공백으로 바꾼 본문에 `오늘[^.。]{0,15}(JGB|국채|콜)`)이 막던 입력은 MOF 날 전부 막는다
    # (재검토 3·4차 — 태그 처리를 바꿀 때마다 회귀가 났다)
    import itertools
    import re
    old = re.compile(r'오늘[^.。]{0,15}(JGB|국채|콜)')
    tags = ['', '<br>', '<wbr>', '<img alt="">', '<span>', '</span>', ' ', '&nbsp;', '<i></i>']
    names = ['콜금리', 'JGB', '국채', '무담보 콜', '무담보콜금리', '콜 O/N']
    for a, b, name, mark in itertools.product(tags, tags, names, ['', '?', '!']):
        para = f'<p>10월 22일 기준{a}오늘{mark}{b}{name}는 <span data-ref="call_rate.value">1.227%</span>다.</p>'
        if old.search(G._plain(para)):
            assert any('오늘' in m for m in check(html({'bonds': para}))), para
