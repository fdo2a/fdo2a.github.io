import datetime as dt
import os
import subprocess
import sys

import pytest

from us import auction_gate as G
from us import auctions as A
from us import upcoming as U

RD = '2026-10-27'


def row(day, kind='Note', term='5-Year', orig=None, btc=2.40, ind=40e9, dirr=20e9, pd=10e9,
        hy='4.845', cusip=None, reopening='No', amt='70000000000', **extra):
    sec_type = {'TIPS': 'Note', 'FRN': 'Note', 'Bill': 'Bill'}.get(kind, kind)
    r = {'competitiveAuctionCloseDate': f'{day}T00:00:00', 'type': kind,
         'securityType': sec_type, 'securityTerm': term, 'originalSecurityTerm': orig or term,
         'reopening': reopening, 'cusip': cusip or f'C{day}{term}{kind}',
         'offeringAmount': amt, 'competitiveAuctionCloseTime': '01:00 PM',
         'bidToCoverRatio': '' if btc is None else f'{btc:.2f}', 'highYield': hy,
         'highDiscountMargin': '', 'indirectBiddersCompetitiveParAwarded': ind,
         'directBiddersCompetitiveParAwarded': dirr, 'primaryDealersCompetitiveParAwarded': pd,
         'inflationProtected': 'Yes' if kind == 'TIPS' else ('No' if kind != 'Bill' else ''),
         'floatingRate': 'Yes' if kind == 'FRN' else ('No' if kind != 'Bill' else '')}
    r.update(extra)
    return r


def history(n=6, btc=2.30, pd=10e9, start=dt.date(2026, 4, 27)):
    """매달 같은 5년물. 응찰 2.30, 딜러 10/70 = 14.3%."""
    out = []
    for i in range(n):
        day = start + dt.timedelta(days=30 * i)
        out.append(row(day.isoformat(), btc=btc, pd=pd, cusip=f'H{i}'))
    return out


def bill(day=RD):
    return row(day, kind='Bill', term='13-Week', hy='', cusip=f'B{day}')


# --- 정규화 -------------------------------------------------------------------

def test_tips_is_not_mixed_into_nominal_notes():
    """TIPS 는 securityType 이 Note 로 온다 — type 을 보지 않으면 명목 5년물 평균에 섞인다."""
    it = A.normalize(row(RD, kind='TIPS', hy='2.367'))
    assert it['kind'] == 'tips' and it['key'] == 'tips-5y'
    assert it['label_ko'] == '5년 TIPS'
    assert A.fmt_rate(it) == '실질 2.367%'


def test_reopening_is_keyed_by_original_term():
    it = A.normalize(row(RD, term='9-Year 10-Month', orig='10-Year', reopening='Yes'))
    assert it['key'] == 'nominal-10y' and it['label_ko'] == '10년물 재발행'


def test_frn_prints_a_margin_not_a_yield():
    it = A.normalize(row(RD, kind='FRN', term='2-Year', hy='', highDiscountMargin='0.038'))
    assert it['high_yield'] is None and A.fmt_rate(it) == '할인마진 0.038%'


def test_bills_are_out_of_scope():
    assert A.normalize(bill()) is None


def test_shares_are_of_competitive_awards():
    it = A.normalize(row(RD, ind=40e9, dirr=20e9, pd=10e9))
    assert (it['indirect_pct'], it['direct_pct'], it['dealer_pct']) == (57.1, 28.6, 14.3)


# --- 판정 ---------------------------------------------------------------------

@pytest.mark.parametrize('btc,dealer,want', [
    (0.05, -1.0, '수요 강함'),      # 경계 포함
    (0.044, 0.0, '평균 수준'),      # 반올림 0.04
    (0.049, 0.0, '수요 강함'),      # 반올림 0.05 = 경계
    (0.02, -2.4, '수요 강함'),      # 한쪽만 움직였다
    (-0.07, 0.4, '수요 약함'),
    (-0.14, -6.2, '엇갈림'),        # 두 신호가 반대
    (0.0, 0.94, '평균 수준'),
    (None, 1.0, None),
])
def test_demand_rule(btc, dealer, want):
    assert A.demand(btc, dealer) == want


def test_compare_uses_only_earlier_same_key_auctions():
    items = [A.normalize(r) for r in history(8)]
    later = A.normalize(row('2027-06-01', cusip='LATER', btc=9.99))
    tips = A.normalize(row('2026-09-01', kind='TIPS', cusip='T', btc=9.99))
    today = A.normalize(row(RD, btc=2.40, pd=8e9))
    out = A.compare(today, items + [later, tips])
    assert out['n_hist'] == 6 and out['avg6']['bid_to_cover'] == 2.30
    assert out['btc_vs_avg'] == 0.10 and out['demand_ko'] == '수요 강함'
    assert out['tail_bp'] is None


def test_short_history_has_no_verdict():
    items = [A.normalize(r) for r in history(2)]
    out = A.compare(A.normalize(row(RD)), items)
    assert out['insufficient'] and out['demand_ko'] is None and out['n_hist'] == 2


# --- 책 -----------------------------------------------------------------------

def test_empty_window_is_a_failure_not_a_quiet_day():
    """2026-10-22 뒤 FiscalData 가 멈춰 2주 동안 0건이 「입찰 없음」으로 읽혔다."""
    with pytest.raises(A.AuctionError):
        A.build(RD, history(6), [])


def test_announced_but_unresulted_coupon_is_pending():
    ann = [row(RD, btc=None, cusip='TODAY')]
    book = A.build(RD, history(6) + [bill()], ann)
    assert book['today'] == [] and not book['complete']
    assert book['pending'][0]['label_ko'] == '5년물'


def test_today_and_next():
    results = history(6) + [bill(), row(RD, cusip='TODAY', btc=2.40, pd=8e9)]
    ann = [row(RD, cusip='TODAY'), row('2026-11-03', term='10-Year', btc=None, cusip='N')]
    book = A.build(RD, results, ann, yields={'5Y': {'level': 4.80, 'bp': -2.04, 'date': RD,
                                                    'source': 'Naver'}})
    assert book['complete'] and [t['key'] for t in book['today']] == ['nominal-5y']
    assert book['today'][0]['yield_ref'] == {'tenor': '5Y', 'level': 4.80, 'bp': -2.0,
                                             'date': RD, 'source': 'Naver'}
    assert book['next'][0]['label_ko'] == '10년물'


def test_yield_from_another_day_is_not_attached():
    it = A.compare(A.normalize(row(RD)), [])
    assert A.yield_ref(it, {'5Y': {'level': 4.8, 'bp': 1, 'date': '2026-10-24'}}, RD) is None


def test_table_is_empty_without_auctions():
    assert A.render_table(A.failed(RD, 'x')) == ''


def test_calendar_adapter_keeps_bills_and_times():
    rows = [A.to_fiscal(bill('2026-10-29')), A.to_fiscal(row('2026-10-29', btc=None))]
    ev = U.auction_events(rows, dt.date(2026, 10, 28), dt.date(2026, 11, 5))
    assert {e['name_ko'].split(' ')[0] for e in ev} == {'13-Week', '5-Year'}
    assert all(e['time_et'] == '13:00' for e in ev)
    res = U.auction_results([A.to_fiscal(row(RD))], dt.date.fromisoformat(RD))
    assert res[0]['dealer_pct'] == 14.3


# --- 게이트 -------------------------------------------------------------------

def _book(btc=2.40, pd=8e9, today=True):
    results = history(6) + [bill()] + ([row(RD, cusip='TODAY', btc=btc, pd=pd)] if today else [])
    return A.build(RD, results, [], yields={'5Y': {'level': 4.80, 'bp': -2.0, 'date': RD,
                                                   'source': 'Naver'}})


def block(book, body=None):
    t = book['today'][0]
    body = body or (f'5년물 700억 달러 입찰은 {t["high_yield"]:.3f}%에 낙찰됐다. 응찰배율은 '
                    f'{t["bid_to_cover"]:.2f}배로 직전 6회 평균보다 {abs(t["btc_vs_avg"]):.2f}배 높았고, '
                    f'딜러 비중은 {t["dealer_pct"]:.1f}%로 평균보다 낮았다. '
                    f'<b data-demand>{t["demand_ko"]}</b>으로 읽는다. 5년물 금리는 2.0bp 내렸다.')
    return f'<p data-auction="{t["key"]}">{body}</p>'


def post(book, blk=None, extra=''):
    sec = (f'<section data-auction-day="{book["report_date"]}"><h2>국채 입찰</h2>'
           + A.render_table(book) + (blk if blk is not None else block(book)) + '</section>')
    return (f'<html><body data-register="da"><section><h2>채권</h2><p>금리.</p></section>'
            f'{sec}{extra}<section><h2>FX</h2><p>달러.</p></section></body></html>')


def test_happy_path_passes():
    b = _book()
    assert b['today'][0]['demand_ko'] == '수요 강함'
    assert G.check(post(b), b, RD) == []


def test_silence_on_a_day_without_auctions():
    b = _book(today=False)
    assert G.check('<html><body><h2>채권</h2></body></html>', b, RD) == []
    bad = '<html><body><section><h2>국채 입찰</h2><p>없다.</p></section></body></html>'
    assert G.check(bad, b, RD)


@pytest.mark.parametrize('book', [None, A.failed(RD, 'boom'), dict(_book(), report_date='2026-10-24')])
def test_unusable_book_forbids_the_section(book):
    good = _book()
    assert G.check(post(good), book, RD)
    assert G.check('<html><body><h2>채권</h2></body></html>', book, RD) == []


def test_missing_section_on_an_auction_day_fails_closed():
    assert G.check('<html><body><h2>채권</h2></body></html>', _book(), RD)


def test_tampered_or_duplicated_table_row():
    b = _book()
    html = post(b)
    assert G.check(html.replace('2.40배', '2.50배', 1), b, RD)
    one = A.render_table(b).split('<tbody>')[1].split('</tbody>')[0]
    hidden = one.replace('<tr ', '<tr hidden ', 1)
    errs = G.check(html.replace('</tbody>', hidden + '</tbody>', 1), b, RD)
    assert any('2개' in e for e in errs)


def test_invented_number_and_wrong_direction_and_label():
    b = _book()
    assert any('수치' in e for e in G.check(post(b, block(b).replace('2.0bp', '7.5bp')), b, RD))
    wrong = block(b).replace('평균보다 0.10배 높았고', '평균보다 0.10배 낮았고')
    assert any('낮다고' in e for e in G.check(post(b, wrong), b, RD))
    lab = block(b).replace('>수요 강함<', '>수요 약함<')
    assert any('판정 표식' in e for e in G.check(post(b, lab), b, RD))


def test_tail_words_are_banned():
    b = _book()
    assert any('테일' in e for e in G.check(post(b, block(b).replace('읽는다.', '읽는다. 테일은 없었다.')), b, RD))


def test_marker_outside_the_section():
    b = _book()
    assert G.check(post(b, extra='<p data-auction="nominal-5y">x</p>'), b, RD)


def test_gate_survives_the_typesetters(tmp_path):
    """실제 발행 순서: apply_readability → apply_colors → 게이트."""
    b = _book()
    f = tmp_path / 'morning_brief_2026-10-27.html'
    f.write_text(post(b), encoding='utf-8')
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for s in ('apply_readability.py', 'apply_colors.py'):
        subprocess.run([sys.executable, os.path.join(here, s), str(f)], check=True,
                       capture_output=True)
    assert G.check(f.read_text(encoding='utf-8'), b, RD) == []


# --- codex 구현 검토(IMPL NO: 9) 재현 ---------------------------------------------

def test_r1_extra_unkeyed_row_or_hidden_row_fails():
    b = _book()
    html = post(b)
    assert G.check(html.replace('</tbody>', '<tr><td>5년물</td><td>999억 달러</td></tr></tbody>'), b, RD)
    assert G.check(html.replace('<tr data-auction-row', '<tr hidden data-auction-row', 1), b, RD)


def test_r2_hidden_block_and_bare_marker_outside():
    b = _book()
    assert G.check(post(b).replace('<p data-auction=', '<p hidden data-auction=', 1), b, RD)
    assert G.check(post(b, extra='<div data-auction-day>x</div>'), b, RD)
    assert G.check(post(b, extra='<span style="display:none" data-demand>수요 강함</span>'), b, RD)


def test_r3_contradicting_label_in_prose():
    b = _book()
    assert G.check(post(b, block(b).replace('읽는다.', '읽는다. 다만 수요 약함이다.')), b, RD)


@pytest.mark.parametrize('phrase', ['평균보다 0.10배 낮았고, 과거보다 높았고',
                                    '평균보다 높지 않았고'])
def test_r4_direction_with_mixed_or_negated_words(phrase):
    b = _book()
    blk = block(b).replace('평균보다 0.10배 높았고', phrase)
    assert G.check(post(b, blk), b, RD)


def test_r4_plain_phrasings_still_pass():
    b = _book()
    for phrase in ('평균(2.30배)을 0.10배 웃돌았고', '평균과 비슷했고'):
        assert G.check(post(b, block(b).replace('평균보다 0.10배 높았고', phrase)), b, RD) == []


def test_r5_caption_is_generated_text():
    b = _book()
    assert G.check(post(b).replace('출처: 미 재무부', '999억 달러. 출처: 미 재무부'), b, RD)


def test_r8_short_history_shows_no_average():
    results = history(2) + [bill(), row(RD, cusip='TODAY')]
    b = A.build(RD, results, [])
    assert b['today'][0]['insufficient']
    assert '(' not in ''.join(A.cells(b['today'][0])[3:7])
    assert '평균' not in A.caption(b)


def test_r9_missing_rate_is_pending_not_done():
    ann = [row(RD, cusip='TODAY')]
    results = history(6) + [bill(), row(RD, cusip='TODAY', hy='')]
    b = A.build(RD, results, ann)
    assert b['today'] == [] and b['pending'] and not b['complete']


def test_r6_calendar_needs_results_within_seven_days(monkeypatch):
    import build_calendar as BC
    rd = dt.date.fromisoformat(RD)
    stale = [row('2026-10-17', kind='Bill', term='13-Week', hy='', cusip='OLD')]
    future = [row('2026-10-30', btc=None, cusip='F')]
    monkeypatch.setattr(A, 'fetch_results', lambda *a, **k: stale)
    monkeypatch.setattr(A, 'fetch_announced', lambda *a, **k: future)
    # FiscalData 도 미래 공고만 있다 — 「가장 최근 행」이 미래라도 결과가 없으면 실패.
    monkeypatch.setattr(U, 'fetch_auctions', lambda *a, **k: [
        {'auction_date': '2026-10-30', 'bid_to_cover_ratio': 'null'}])
    with pytest.raises(RuntimeError):
        BC._auction_rows(rd, rd + dt.timedelta(days=10))


def test_r7_fiscaldata_fallback_drops_shares(monkeypatch):
    import build_calendar as BC
    rd = dt.date.fromisoformat(RD)
    monkeypatch.setattr(A, 'fetch_results', lambda *a, **k: (_ for _ in ()).throw(OSError('dns')))
    monkeypatch.setattr(U, 'fetch_auctions', lambda *a, **k: [{
        'auction_date': RD, 'security_type': 'Note', 'security_term': '5-Year',
        'original_security_term': '5-Year', 'bid_to_cover_ratio': '2.33',
        'indirect_bidder_accepted': '40', 'primary_dealer_accepted': '10', 'total_accepted': '70'}])
    res = U.auction_results(BC._auction_rows(rd, rd), rd)
    assert res[0]['bid_to_cover'] == 2.33
    assert res[0]['indirect_pct'] is None and res[0]['dealer_pct'] is None


# --- codex 재검토(IMPL NO: 4) ---------------------------------------------------

def test_rr2_section_wrapped_in_hidden_ancestor():
    b = _book()
    html = post(b)
    sec = G.section(html)
    assert G.check(html.replace(sec, f'<div hidden>{sec}</div>'), b, RD)


@pytest.mark.parametrize('extra', ['수요는 약했다.', '수요가 약하지 않았다.', '응찰은 엇갈렸다.',
                                   '수요는 부진했다.', '수요가 저조했다.', '입찰은 실망스러웠다.',
                                   '입찰 수요가 부실했다.', '응찰이 냉랭했다.', '응찰은 견조했다.'])
def test_rr3_verdict_words_outside_the_marker(extra):
    b = _book()
    assert any('data-demand' in e for e in
               G.check(post(b, block(b).replace('읽는다.', '읽는다. ' + extra)), b, RD))


def test_rr_respectively_is_refused_with_a_clear_message():
    b = _book()
    t = b['today'][0]
    body = (f'응찰배율은 {t["bid_to_cover"]:.2f}배, 딜러 비중은 {t["dealer_pct"]:.1f}%로 각각 '
            f'평균보다 높고 낮았다. <b data-demand>{t["demand_ko"]}</b>.')
    errs = G.check(post(b, f'<p data-auction="{t["key"]}">{body}</p>'), b, RD)
    assert errs and all('따로' in e for e in errs)


def test_rr_ordinary_phrasings_pass():
    b = _book()
    t = b['today'][0]
    body = (f'응찰배율은 {t["bid_to_cover"]:.2f}배로 평균(2.30배)을 웃돌았다. '
            f'딜러 비중은 {t["dealer_pct"]:.1f}%로 평균에 못 미쳤다. 간접 비중은 평균과 비슷했다. '
            f'<b data-demand>{t["demand_ko"]}</b>으로 읽는다.')
    assert G.check(post(b, f'<p data-auction="{t["key"]}">{body}</p>'), b, RD) == []


def test_rr_bond_selloff_wording_is_not_a_verdict():
    b = _book()
    blk = block(b).replace('5년물 금리는 2.0bp 내렸다.', '5년물은 2.0bp 내려 채권 강세로 마감했다.')
    assert G.check(post(b, blk), b, RD) == []


def test_rr_market_adjective_without_auction_subject_passes():
    b = _book()
    blk = block(b).replace('5년물 금리는 2.0bp 내렸다.', '국채시장은 견조했고 5년물 금리는 2.0bp 내렸다.')
    assert G.check(post(b, blk), b, RD) == []
