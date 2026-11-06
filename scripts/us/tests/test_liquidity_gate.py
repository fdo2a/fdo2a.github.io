import copy
import os
import subprocess
import sys

from us import liquidity as L
from us import liquidity_gate as G

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'liquidity')
RD = '2026-11-05'
NO_LEDGER = (set(), set())


def fx(name):
    with open(os.path.join(FX, name), encoding='utf-8') as fh:
        return fh.read()


def _round(big=('reserves',)):
    r = L.parse_h41(fx('h41_20261105.html'))
    prev = L.parse_h41(fx('h41_20261029.html'))
    r['late'] = False
    r['flags'] = {'rows': {k: {'wed_chg': r['rows'][k]['wed'] - prev['rows'][k]['wed']} for k in L.TABLE_ROWS},
                  'window': {'first': '2025-11-05', 'last': '2026-10-28', 'n': 52}}
    for k in L.FLAG_ROWS:
        r['flags']['rows'][k].update({'z': 2.5 if k in big else 0.3, 'big': k in big})
    return r


def _docs(kinds=('refunding', 'tbac')):
    b = L.parse_borrowing(fx('qra_borrowing_2026q4.html'), '2026Q4')
    r = L.parse_refunding(fx('qra_refunding_2026q4.html'), '2026Q4')
    t, _ = L.parse_tbac(fx('qra_tbac_2026q4.html'), '2026Q4')
    all_ = {'borrowing': dict(b, ok=True, late=True), 'refunding': dict(r, ok=True, late=True),
            'tbac': dict(t, ok=True, late=True)}
    return {k: all_[k] for k in kinds}


def book(h41=True, kinds=('refunding', 'tbac'), big=('reserves',), change='changed'):
    rounds = [_round(big)] if h41 else []
    q3 = L.parse_refunding(fx('qra_refunding_2026q3.html'), '2026Q3')['guidance']
    q4 = L.parse_refunding(fx('qra_refunding_2026q4.html'), '2026Q4')['guidance']
    ch, words = L.guidance_change(q3 if change != 'unknown' else None, q4)
    b = {'status': 'complete', 'report_date': RD, 'run_id': 'r',
         'h41': {'candidates': rounds, 'pool': [r['release_date'] for r in rounds], 'pending': [], 'overdue': []},
         'qra': {'round': '2026Q4', 'round_name': '2026 - 4th Quarter', 'candidates': _docs(kinds),
                 'guidance': {'change': ch, 'words': words, 'prev': q3, 'cur': q4, 'prev_round': '2026Q3'}}}
    b['today'] = bool(rounds) or bool(b['qra']['candidates'])
    return b


def liq_p(b):
    r = b['h41']['candidates'][0]
    wc = r['flags']['rows']['reserves']['wed_chg']
    return (f'<p data-liq="2026-11-05:reserves">지급준비금은 수요일 {L.fmt_usd(r["rows"]["reserves"]["wed"])}로 '
            f'한 주 사이 {L.fmt_usd(wc)} 늘었다. 같은 주 재무부 일반계정(TGA)이 '
            f'{L.fmt_usd(r["flags"]["rows"]["tga"]["wed_chg"])} 줄어 돈이 은행으로 돌아왔다.</p>')


REF_P = ('<p data-qra-doc="2026Q4:refunding">재무부는 이번 차환에서 1,250억 달러를 발행해 만기 970억 달러를 갚고 '
         '280억 달러를 새로 조달한다. 3년물 580억 달러, 10년물 420억 달러, 30년물 250억 달러다.</p>')
GUID_P = ('<p data-qra-guidance="2026Q4"><b data-guidance="changed">문구가 바뀌었다</b> — 8월 성명의 「at least」가 '
          '빠졌다.</p>')
TBAC_P = '<p data-qra-doc="2026Q4:tbac">자문위원회(TBAC)는 단기물 비중을 늘릴 여지가 있다고 봤다.</p>'
BOR_P = ('<p data-qra-doc="2026Q4:borrowing">재무부는 10-12월 순차입을 6,180억 달러, 연말 현금잔고를 8,500억 달러로 '
         '가정했다. 8월 추정보다 100억 달러 줄었다.</p>')


def post(b, body=None, extra=''):
    if body is None:
        body = ''
        if b['h41']['candidates'] and any(b['h41']['candidates'][0]['flags']['rows'][k]['big'] for k in L.FLAG_ROWS):
            body += liq_p(b)
        kinds = set(b['qra']['candidates'])
        if 'borrowing' in kinds:
            body += BOR_P
        if 'refunding' in kinds:
            body += REF_P + GUID_P
        if 'tbac' in kinds:
            body += TBAC_P
    sec = (f'<section data-liquidity-day="{RD}"><h2>유동성·수급</h2>' + L.render_tables(b) + body + '</section>')
    return (f'<html><body data-register="da"><section><h2>국채 입찰</h2><p>입찰.</p></section>'
            f'{sec}{extra}<section><h2>FX</h2><p>달러.</p></section></body></html>')


def test_happy_path():
    b = book()
    assert G.check(post(b), b, RD, NO_LEDGER) == []


def test_borrowing_only_day():
    b = book(h41=False, kinds=('borrowing',))
    assert G.check(post(b), b, RD, NO_LEDGER) == []


def test_silence_without_releases():
    b = book(h41=False, kinds=())
    assert G.check('<html><body><section><h2>FX</h2></section></body></html>', b, RD, NO_LEDGER) == []
    assert G.check(post(b, body='<p data-liq="x">x</p>'), b, RD, NO_LEDGER)


def test_section_required_when_releases():
    b = book()
    errs = G.check('<html><body><section><h2>FX</h2></section></body></html>', b, RD, NO_LEDGER)
    assert any('섹션이 없다' in e for e in errs)


def test_unusable_book_blocks_section():
    b = book()
    for bad in (None, dict(b, status='running'), dict(b, report_date='2026-11-04'), dict(b, disabled=True)):
        assert G.check(post(b), bad, RD, NO_LEDGER)
        assert G.check('<html><body></body></html>', bad, RD, NO_LEDGER) == []


def test_ledger_changed_is_flagged_first():
    b = book()
    errs = G.check(post(b), b, RD, ({'2026-11-05'}, set()))
    assert errs and errs[0].startswith(G.LEDGER_CHANGED)
    errs = G.check(post(b), b, RD, (set(), {'2026Q4:refunding'}))
    assert errs[0].startswith(G.LEDGER_CHANGED)


def test_ledger_shrink_with_cap_lets_next_round_in_is_flagged():
    b = book()
    b['h41']['pool'] = ['2026-10-29', '2026-11-05']
    b['h41']['candidates'] = [_round()]          # 책이 10/29 를 원장에 있다고 봤다
    assert G.check(post(b), b, RD, ({'2026-10-29'}, set())) == []
    assert G.check(post(b), b, RD, NO_LEDGER)[0].startswith(G.LEDGER_CHANGED)


def test_table_cell_and_caption_tamper():
    b = book()
    html = post(b)
    assert any('데이터와 다르다' in e for e in G.check(html.replace('2조 9,628억 달러', '2조 9,629억 달러', 1), b, RD, NO_LEDGER))
    assert any('캡션' in e for e in G.check(html.replace('출처: 연준 H.4.1', '출처: 연준', 1), b, RD, NO_LEDGER))
    assert G.check(html.replace('</tbody>', '<tr><td>x</td><td>1조 달러</td></tr></tbody>', 1), b, RD, NO_LEDGER)


def test_liq_paragraph_exactly_once_and_only_for_flagged_rows():
    b = book()
    html = post(b)
    assert G.check(html.replace(liq_p(b), ''), b, RD, NO_LEDGER)
    assert G.check(html.replace(liq_p(b), liq_p(b) * 2), b, RD, NO_LEDGER)
    extra = '<p data-liq="2026-11-05:tga">재무부 일반계정(TGA)은 9,362억 달러다.</p>'
    assert any('이례적 행이 아니다' in e for e in G.check(html.replace(REF_P, REF_P + extra), b, RD, NO_LEDGER))


def test_liq_paragraph_numbers_required_and_owned_by_row():
    b = book()
    r = b['h41']['candidates'][0]
    wc = L.fmt_usd(r['flags']['rows']['reserves']['wed_chg'])
    html = post(b)
    assert any('주간 변화' in e for e in G.check(html.replace(f'한 주 사이 {wc}', '한 주 사이 크게', 1), b, RD, NO_LEDGER))
    assert any('아니다' in e for e in G.check(html.replace(f'한 주 사이 {wc}', f'한 주 사이 {wc} (약 700억 달러)', 1),
                                                 b, RD, NO_LEDGER))
    # TGA 값을 지준 이름 아래 쓰면(역할이 섞이면) 막힌다
    tga = L.fmt_usd(r['flags']['rows']['tga']['wed_chg'])
    swapped = html.replace(f'재무부 일반계정(TGA)이 {tga}', f'지준이 {tga}', 1)
    assert any('아니다' in e for e in G.check(swapped, b, RD, NO_LEDGER))
    assert any('수치' in e for e in G.check(html.replace(' 늘었다.', ' 늘었다(2.5%).', 1), b, RD, NO_LEDGER))


def test_liq_direction_reversed():
    b = book()
    html = post(b)
    errs = G.check(html.replace(' 늘었다. 같은 주', ' 줄었다. 같은 주', 1), b, RD, NO_LEDGER)
    assert any('늘었는데 반대로' in e for e in errs)


def test_hidden_and_unmarked_and_outside():
    b = book()
    html = post(b)
    assert G.check(html.replace('<p data-liq=', '<p hidden data-liq=', 1), b, RD, NO_LEDGER)
    assert any('무표식' in e for e in G.check(html.replace(REF_P, REF_P + '<p>유동성이 풀렸다.</p>'), b, RD, NO_LEDGER))
    assert any('밖에' in e for e in G.check(post(b, extra='<p data-liq="2026-11-05:reserves">x</p>'), b, RD, NO_LEDGER))
    assert G.check(html.replace('<section data-liquidity-day', '<div hidden><section data-liquidity-day', 1)
                   .replace('</section><section><h2>FX', '</section></div><section><h2>FX', 1), b, RD, NO_LEDGER)


def test_qra_paragraph_values():
    b = book()
    html = post(b)
    assert any('필수 값' in e for e in G.check(html.replace('280억 달러를 새로', '일부를 새로', 1), b, RD, NO_LEDGER))
    assert any('값이 아니다' in e for e in G.check(html.replace('30년물 250억', '30년물 260억', 1), b, RD, NO_LEDGER))


def test_borrowing_compare_month_and_direction():
    b = book(h41=False, kinds=('borrowing',))
    html = post(b)
    assert any('비교 월' in e for e in G.check(html.replace('8월 추정보다', '5월 추정보다'), b, RD, NO_LEDGER))
    assert any('줄었는데 늘었다고' in e for e in G.check(html.replace('100억 달러 줄었다', '100억 달러 늘었다'), b, RD, NO_LEDGER))
    nov = copy.deepcopy(b)
    nov['qra']['candidates']['borrowing']['vs_prior'] = None
    assert any('비교를 썼다' in e for e in G.check(post(nov), nov, RD, NO_LEDGER))


def test_guidance_marker_and_quote():
    b = book()
    html = post(b)
    assert any('낱말' in e for e in G.check(html.replace('「at least」가', '한 구절이'), b, RD, NO_LEDGER))
    assert any('가이던스 표식' in e for e in G.check(html.replace('data-guidance="changed"', 'data-guidance="same"'), b, RD, NO_LEDGER))
    assert any('정확히 하나' in e for e in G.check(html.replace(GUID_P, ''), b, RD, NO_LEDGER))
    u = book(change='unknown')
    assert any('빼라' in e for e in G.check(post(u), u, RD, NO_LEDGER))
    assert G.check(post(u).replace(GUID_P, ''), u, RD, NO_LEDGER) == []


def test_tbac_view_rules():
    b = book()
    html = post(b)
    assert any('수치' in e for e in G.check(html.replace('여지가 있다고', '여지가 10%쯤 있다고'), b, RD, NO_LEDGER))
    assert any('결정' in e for e in G.check(html.replace('봤다.', '결정했다.'), b, RD, NO_LEDGER))
    assert G.check(html.replace(TBAC_P, ''), b, RD, NO_LEDGER) == []          # TBAC 는 선택


def test_floor_phrases():
    b = book()
    html = post(b)
    assert any('오늘' in e for e in G.check(html.replace('지급준비금은 수요일', '지급준비금은 오늘', 1), b, RD, NO_LEDGER))
    bad = html.replace('돌아왔다.', '돌아왔다. 지준이 늘어난 탓에 10년물 금리가 내렸다.')
    assert any('단정' in e for e in G.check(bad, b, RD, NO_LEDGER))


def test_gate_survives_the_typesetters(tmp_path):
    b = book()
    f = tmp_path / 'morning_brief_2026-11-05.html'
    f.write_text(post(b), encoding='utf-8')
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for s in ('apply_readability.py', 'apply_colors.py'):
        subprocess.run([sys.executable, os.path.join(here, s), str(f)], check=True, capture_output=True)
    assert G.check(f.read_text(encoding='utf-8'), b, RD, NO_LEDGER) == []


def test_number_audit_delegates_only_when_gate_passes():
    from us import number_audit as N
    b = book()
    b['ledger'] = {'h41': [], 'qra': []}
    data = {'market_data': {'report_date': RD}, 'liquidity': b}
    ok = N.audit(post(b), data, prose='warn')
    assert ok.delegated_by.get('check_liquidity', 0) > 40 and ok.unverified == 0
    bad = N.audit(post(b).replace('2조 9,628억 달러', '2조 9,629억 달러', 1), data, prose='warn')
    assert 'check_liquidity' not in bad.delegated_by and bad.unverified > 0


def test_cli_end_to_end(tmp_path):
    import json
    b = book()
    ws = tmp_path / 'ws'
    (ws / 'liquidity').mkdir(parents=True)
    (ws / 'liquidity' / 'liquidity.json').write_text(json.dumps(b, ensure_ascii=False))
    (ws / 'market_data.json').write_text(json.dumps({'report_date': RD}))
    repo = tmp_path / 'repo'
    (repo / 'posts').mkdir(parents=True)
    f = tmp_path / f'morning_brief_{RD}.html'
    f.write_text(post(b), encoding='utf-8')
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cli = [sys.executable, os.path.join(here, 'check_liquidity.py'), '--html', str(f), '--datadir', str(ws),
           '--repo', str(repo)]
    assert subprocess.run(cli, capture_output=True).returncode == 0
    (repo / 'posts' / '2026-11-04.html').write_text('<table data-h41-release="2026-11-05"></table>')
    r = subprocess.run(cli, capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout.startswith('ledger_changed:')
    (repo / 'posts' / '2026-11-04.html').unlink()
    (repo / 'posts' / f'{RD}.html').write_text(post(b))          # 이 글 자신(STEP 3 복사본)은 원장이 아니다
    assert subprocess.run(cli, capture_output=True).returncode == 0


# ── codex 구현 검토 1차(IMPL NO: 7) 재현 ─────────────────────────────────────

def test_impl1_role_swaps_and_signs():
    b = book()
    html = post(b)
    swap = html.replace('1,250억 달러를 발행해 만기 970억 달러', '970억 달러를 발행해 만기 1,250억 달러')
    assert G.check(swap, b, RD, NO_LEDGER)
    r = b['h41']['candidates'][0]
    wc = L.fmt_usd(r['flags']['rows']['reserves']['wed_chg'])
    lvl = L.fmt_usd(r['rows']['reserves']['wed'])
    assert any('부호' in e for e in G.check(html.replace(f'한 주 사이 {wc} 늘었다', f'한 주 사이 -{wc} 늘었다'),
                                           b, RD, NO_LEDGER))
    both = html.replace(f'수요일 {lvl}로 한 주 사이 {wc} 늘었다', f'수요일 {wc}로 한 주 사이 {lvl} 늘었다')
    assert G.check(both, b, RD, NO_LEDGER)


def test_impl1_marker_on_non_paragraph_and_not_delegated():
    from us import number_audit as N
    b = book()
    b['ledger'] = {'h41': [], 'qra': []}
    bad = post(b).replace('</section><section><h2>FX', '<div data-liq="x">연준은 999조 달러를 찍었다.</div></section>'
                                                         '<section><h2>FX', 1)
    assert any('<p> 에만' in e for e in G.check(bad, b, RD, NO_LEDGER))
    r = N.audit(bad, {'market_data': {'report_date': RD}, 'liquidity': b}, prose='warn')
    assert 'check_liquidity' not in r.delegated_by


def test_impl1_single_quote_hidden_style():
    b = book()
    html = post(b)
    assert G.check(html.replace('<p data-liq=', "<p style='display:none' data-liq=", 1), b, RD, NO_LEDGER)
    assert G.check(html.replace('<p data-qra-doc=', "<p style='visibility:hidden' data-qra-doc=", 1), b, RD, NO_LEDGER)


def test_impl1_compare_without_noun():
    b = book(h41=False, kinds=('borrowing',))
    html = post(b)
    errs = G.check(html.replace('8월 추정보다 100억 달러 줄었다', '5월보다 100억 달러 늘었다'), b, RD, NO_LEDGER)
    assert any('비교 월' in e for e in errs) and any('줄었는데 늘었다고' in e for e in errs)
    assert G.check(html.replace('8월 추정보다 100억 달러 줄었다', '100억 달러 줄었다'), b, RD, NO_LEDGER)


# ── codex 구현 재검토(IMPL NO: 3) 재현 ──────────────────────────────────────

def test_impl2_level_with_ro_is_not_a_change():
    b = book()
    r = b['h41']['candidates'][0]
    wc = L.fmt_usd(r['flags']['rows']['reserves']['wed_chg'])
    lvl = L.fmt_usd(r['rows']['reserves']['wed'])
    html = post(b).replace(f'지급준비금은 수요일 {lvl}로 한 주 사이 {wc} 늘었다.',
                           f'지급준비금은 {lvl}로 늘었다. 한 주 사이 {wc} 늘었다.')
    assert G.check(html, b, RD, NO_LEDGER) == []


def test_impl2_first_direction_word_wins():
    b = book(h41=False, kinds=('borrowing',))
    html = post(b).replace('8월 추정보다 100억 달러 줄었다', '8월 추정보다 100억 달러 늘었다(감소가 아니다)')
    assert any('늘었다고' in e for e in G.check(html, b, RD, NO_LEDGER))


def test_impl3_negated_direction_word_is_skipped():
    b = book(h41=False, kinds=('borrowing',))
    html = post(b)
    ok = html.replace('8월 추정보다 100억 달러 줄었다', '8월 추정보다 증가하지 않고 100억 달러 줄었다')
    assert G.check(ok, b, RD, NO_LEDGER) == []
    bad = html.replace('8월 추정보다 100억 달러 줄었다', '8월 추정보다 감소하지 않고 100억 달러 늘었다')
    assert any('늘었다고' in e for e in G.check(bad, b, RD, NO_LEDGER))
    ok2 = html.replace('8월 추정보다 100억 달러 줄었다', '8월 추정보다 100억 달러 줄었다(늘지 않았다)')
    assert G.check(ok2, b, RD, NO_LEDGER) == []


def test_impl4_text_outside_cells_in_table_fails():
    from us import number_audit as N
    b = book()
    b['ledger'] = {'h41': [], 'qra': []}
    bad = post(b).replace('<thead>', '<caption>999999억 달러</caption><thead>', 1)
    assert any('다시 그린 표' in e for e in G.check(bad, b, RD, NO_LEDGER))
    r = N.audit(bad, {'market_data': {'report_date': RD}, 'liquidity': b}, prose='warn')
    assert 'check_liquidity' not in r.delegated_by


def test_impl5_caption_class_on_other_element():
    from us import number_audit as N
    b = book()
    b['ledger'] = {'h41': [], 'qra': []}
    bad = post(b).replace('</section><section><h2>FX', '<span class="caption">999999억 달러</span></section>'
                                                         '<section><h2>FX', 1)
    assert any('캡션은' in e for e in G.check(bad, b, RD, NO_LEDGER))
    r = N.audit(bad, {'market_data': {'report_date': RD}, 'liquidity': b}, prose='warn')
    assert 'check_liquidity' not in r.delegated_by


def test_text_outside_known_blocks_fails():
    b = book()
    bad = post(b).replace('</section><section><h2>FX', '<div>지준이 크게 늘었다.</div></section><section><h2>FX', 1)
    assert any('밖의 글자' in e for e in G.check(bad, b, RD, NO_LEDGER))


def test_impl6_nested_div_in_caption_and_extra_heading():
    from us import number_audit as N
    b = book()
    b['ledger'] = {'h41': [], 'qra': []}
    bad = post(b).replace('출처: 연준 H.4.1</div>', '출처: 연준 H.4.1<div></div><h3>거짓 999999억 달러</h3></div>', 1)
    errs = G.check(bad, b, RD, NO_LEDGER)
    assert any('캡션 안에 태그' in e for e in errs) and any('제목은 하나' in e for e in errs)
    r = N.audit(bad, {'market_data': {'report_date': RD}, 'liquidity': b}, prose='warn')
    assert 'check_liquidity' not in r.delegated_by


def test_impl7_comment_inside_attribute_desync():
    b = book()
    bad = post(b).replace('250억 달러다.</p>', '250억 달러다.<span title="<!--">999999억 달러<!-- --></span></p>', 1)
    errs = G.check(bad, b, RD, NO_LEDGER)
    assert any('주석' in e for e in errs) and any('속성값' in e for e in errs)


def test_impl8_fake_heading_in_comment_then_attribute_comment():
    b = book()
    html = post(b).replace('<section data-liquidity-day', '<!-- <section><h2>유동성·수급</h2></section> -->'
                                                           '<section data-liquidity-day', 1)
    bad = html.replace('250억 달러다.</p>', '250억 달러다.<span title="<!--">999999억 달러<!-- --></span></p>', 1)
    errs = G.check(bad, b, RD, NO_LEDGER)
    assert any('주석 기호' in e for e in errs)
    assert G.check(html, b, RD, NO_LEDGER) == []           # 섹션 밖 주석의 가짜 제목만으로는 막지 않는다
