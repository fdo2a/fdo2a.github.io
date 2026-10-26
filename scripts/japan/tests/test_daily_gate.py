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
