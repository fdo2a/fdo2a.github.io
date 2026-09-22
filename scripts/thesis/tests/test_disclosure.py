import pytest

from thesis import disclosure as D
from thesis import gate as G
from thesis import triggers as T


def item(report_nm, rcept_no='20260921000123', rcept_dt='20260921',
         corp_name='SK하이닉스', flr_nm='SK하이닉스'):
    return {'corp_code': '00164779', 'corp_name': corp_name, 'stock_code': '000660',
            'corp_cls': 'Y', 'report_nm': report_nm, 'rcept_no': rcept_no,
            'flr_nm': flr_nm, 'rcept_dt': rcept_dt, 'rm': ''}


def payload(items, status='000'):
    return {'status': status, 'message': '정상',
            'page_no': 1, 'page_count': 100, 'total_count': len(items),
            'total_page': 1, 'list': items}


# ── 분류: 화이트리스트가 confirmed 를 준다 ──

@pytest.mark.parametrize('report_nm, axis', [
    ('단일판매ㆍ공급계약체결', 'contract'),
    ('영업(잠정)실적(공정공시)', 'contract'),
    ('매출액또는손익구조30%(대규모법인은15%)이상변동', 'contract'),
    ('유상증자결정', 'capital'),
    ('전환사채권발행결정', 'capital'),
    ('주요사항보고서(자기주식취득결정)', 'capital'),
    ('주식등의대량보유상황보고서(약식)', 'ownership'),
    ('분기보고서 (2026.06)', 'financials'),
    ('반기보고서 (2026.06)', 'financials'),
    ('사업보고서 (2025.12)', 'financials'),
])
def test_whitelisted_reports_are_confirmed_with_an_axis(report_nm, axis):
    out = D.classify(report_nm)
    assert out is not None, report_nm
    assert out['axis'] == axis and out['confirmed'] is True


def test_middle_dot_variants_match_the_same_rule():
    """DART 는 같은 공시명을 ㆍ·・ 로 섞어 쓴다. 표기 차이로 놓치면 조용히 실패한다."""
    for dot in ('ㆍ', '·', '・'):
        assert D.classify(f'단일판매{dot}공급계약체결')['axis'] == 'contract'


# ── 분류: 침묵을 깨지 않는 것들 ──

def test_correction_filings_are_not_confirmed():
    """정정은 새 사건이 아니다. 원 공시가 이미 사건으로 잡혔다."""
    out = D.classify('[기재정정]단일판매ㆍ공급계약체결')
    assert out['confirmed'] is False and out['correction'] is True


def test_attachment_correction_is_not_confirmed():
    assert D.classify('[첨부정정]분기보고서 (2026.06)')['confirmed'] is False


def test_insider_ownership_reports_are_recorded_but_not_confirmed():
    """빈도가 높고 신호가 약하다 — 매일 울리면 침묵 게이트가 죽는다."""
    out = D.classify('임원ㆍ주요주주특정증권등소유상황보고서')
    assert out['confirmed'] is False and out['axis'] is None


def test_unlisted_report_names_are_not_confirmed():
    assert D.classify('기업설명회(IR)개최(안내공시)')['confirmed'] is False


def test_blank_report_name_classifies_without_raising():
    assert D.classify('')['confirmed'] is False


# ── 응답 파싱 ──

def test_parse_list_returns_items_on_success():
    assert len(D.parse_list(payload([item('유상증자결정')]))) == 1


def test_no_data_status_is_an_empty_day_not_an_error():
    """013 은 «조회 데이터 없음» 이다. 오류로 다루면 조용한 날마다 수집이 실패한다."""
    assert D.parse_list({'status': '013', 'message': '조회된 데이터가 없습니다.'}) == []


def test_real_error_status_raises():
    with pytest.raises(RuntimeError):
        D.parse_list({'status': '020', 'message': '요청 제한을 초과하였습니다.'})


def test_error_message_is_scrubbed_of_the_key(monkeypatch):
    monkeypatch.setenv('DART_API_KEY', 'sekret0123456789')
    with pytest.raises(RuntimeError) as e:
        D.parse_list({'status': '100', 'message': 'crtfc_key=sekret0123456789 잘못됨'})
    assert 'sekret0123456789' not in str(e.value)


# ── 키 마스킹 ──

def test_scrub_masks_the_key_in_a_query_string():
    url = 'https://opendart.fss.or.kr/api/list.json?crtfc_key=abcdef123456&corp_code=001'
    out = D.scrub(url)
    assert 'abcdef123456' not in out and 'corp_code=001' in out


def test_scrub_masks_the_env_value_even_outside_a_url(monkeypatch):
    monkeypatch.setenv('DART_API_KEY', 'abcdef123456')
    assert 'abcdef123456' not in D.scrub('열쇠는 abcdef123456 였다')


def test_scrub_without_a_key_set_still_masks_the_query_pattern(monkeypatch):
    monkeypatch.delenv('DART_API_KEY', raising=False)
    assert 'zzz' not in D.scrub('?crtfc_key=zzz&x=1')


# ── 조회 창 ──

def test_window_spans_the_last_history_row_to_today():
    rows = [{'date': '2026-09-17'}, {'date': '2026-09-18'}]
    assert D.window(rows, '2026-09-21') == ('20260918', '20260921')


def test_window_covers_a_gap_so_a_failed_day_is_filled():
    rows = [{'date': '2026-09-08'}]
    assert D.window(rows, '2026-09-21')[0] == '20260908'


def test_window_is_capped_so_a_long_gap_cannot_blow_up_the_query():
    rows = [{'date': '2025-01-02'}]
    bgn, end = D.window(rows, '2026-09-21', max_days=30)
    assert bgn == '20260822' and end == '20260921'


def test_window_with_no_history_falls_back_to_the_cap():
    bgn, end = D.window([], '2026-09-21', max_days=7)
    assert bgn == '20260914' and end == '20260921'


# ── 사건 변환 ──

def test_to_event_carries_the_receipt_url_as_the_primary_source():
    ev = D.to_event(item('유상증자결정', rcept_no='20260921000123'))
    assert ev['url'] == 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260921000123'
    assert ev['date'] == '2026-09-21' and ev['confirmed'] is True
    assert ev['axis'] == 'capital' and ev['title'] == '유상증자결정'


def test_to_event_keeps_the_filer_so_a_5pct_report_is_attributable():
    ev = D.to_event(item('주식등의대량보유상황보고서', flr_nm='국민연금공단'))
    assert ev['filer'] == '국민연금공단'


# ── 축 공급 (kill 은 여기서 자동으로 나지 않는다) ──

def test_event_axes_only_counts_confirmed_events():
    events = [D.to_event(item('단일판매ㆍ공급계약체결')),
              D.to_event(item('[기재정정]유상증자결정'))]
    assert D.event_axes(events) == ('contract',)


def test_dart_contract_event_supplies_the_axis_numbers_never_could():
    """수치 트리거는 price 축만 만든다. contract 축은 공시에서만 온다."""
    hits = [{'key': 'bear_proximity', 'severity': 'watch'}]
    events = [D.to_event(item('단일판매ㆍ공급계약체결'))]
    assert T.kill_axes(hits, D.event_axes(events)) == ('contract', 'price')


def test_capital_and_ownership_axes_do_not_reach_the_kill_gate():
    """kill 은 price+contract 둘뿐이다. 증자·지분 공시가 kill 을 열어선 안 된다."""
    events = [D.to_event(item('유상증자결정')),
              D.to_event(item('주식등의대량보유상황보고서'))]
    axes = T.kill_axes([{'key': 'bear_proximity'}], D.event_axes(events))
    assert 'contract' not in axes


# ── 침묵 게이트와의 계약 ──

def test_a_day_of_only_unconfirmed_filings_is_still_a_quiet_day():
    events = [D.to_event(item('임원ㆍ주요주주특정증권등소유상황보고서')),
              D.to_event(item('[첨부정정]분기보고서 (2026.06)'))]
    assert G.check_silence([], events, page_changed=True) is not None


def test_a_confirmed_filing_licenses_the_page_edit():
    events = [D.to_event(item('영업(잠정)실적(공정공시)'))]
    assert G.check_silence([], events, page_changed=True) is None


# ── BVPS ──

def test_bvps_divides_equity_by_shares_net_of_treasury():
    assert D.bvps(1000.0, shares_issued=100, treasury=20) == pytest.approx(12.5)


def test_bvps_without_treasury_uses_the_issued_count():
    assert D.bvps(1000.0, shares_issued=100) == pytest.approx(10.0)


def test_bvps_refuses_to_guess_when_an_input_is_missing():
    assert D.bvps(None, shares_issued=100) is None
    assert D.bvps(1000.0, shares_issued=None) is None


def test_bvps_refuses_a_non_positive_share_count():
    assert D.bvps(1000.0, shares_issued=20, treasury=20) is None


# ── 재무제표 파싱 ──

def test_controlling_equity_is_preferred_over_total_equity():
    """P/B 분자는 지배주주 몫이다. 비지배지분을 섞으면 조용히 낮아진다."""
    rows = [{'account_nm': '자본총계', 'thstrm_amount': '1,000'},
            {'account_nm': '지배기업 소유주지분', 'thstrm_amount': '900'}]
    assert D.parse_equity({'status': '000', 'list': rows}) == 900.0


def test_total_equity_is_used_when_no_controlling_line_exists():
    rows = [{'account_nm': '자본총계', 'thstrm_amount': '1,000'}]
    assert D.parse_equity({'status': '000', 'list': rows}) == 1000.0


def test_negative_amounts_in_parentheses_parse_as_negative():
    rows = [{'account_nm': '자본총계', 'thstrm_amount': '(1,000)'}]
    assert D.parse_equity({'status': '000', 'list': rows}) == -1000.0


def test_parse_equity_returns_none_when_the_statement_is_absent():
    assert D.parse_equity({'status': '013', 'message': '없음'}) is None


def test_parse_share_counts_nets_out_treasury():
    rows = [{'se': '보통주', 'istc_totqy': '728,002,365', 'tesstk_co': '20,000,000'}]
    out = D.parse_share_counts({'status': '000', 'list': rows})
    assert out == (728002365, 20000000)


def test_parse_share_counts_skips_the_合計_row_and_preferred_stock():
    rows = [{'se': '우선주', 'istc_totqy': '1,000', 'tesstk_co': '0'},
            {'se': '보통주', 'istc_totqy': '500', 'tesstk_co': '10'}]
    assert D.parse_share_counts({'status': '000', 'list': rows}) == (500, 10)


def test_parse_share_counts_returns_none_when_missing():
    assert D.parse_share_counts({'status': '013'}) is None


# ── corp_code 검증 ──

def test_corp_code_is_verified_against_the_stock_code():
    """고유번호를 상수로 박는 대신 종목코드로 대조한다 — 조용한 오조회를 막는다."""
    company = {'status': '000', 'corp_code': '00164779', 'stock_code': '000660',
               'corp_name': 'SK하이닉스'}
    assert D.verify_corp(company, '000660') is True


def test_a_mismatched_stock_code_fails_verification():
    company = {'status': '000', 'corp_code': '00126380', 'stock_code': '005930'}
    assert D.verify_corp(company, '000660') is False


def test_an_error_payload_fails_verification():
    assert D.verify_corp({'status': '101', 'message': '부적절한 키'}, '000660') is False


# ── 보고서 후보 ──

def test_recent_reports_walks_back_across_the_year_boundary():
    out = D.recent_reports('2026-02-10', back=3)
    assert [label for _, _, label in out] == ['2026-Q1', '2025-Q4', '2025-Q3']


def test_recent_reports_maps_the_annual_report_code():
    (year, code, label) = D.recent_reports('2026-11-30', back=1)[0]
    assert (year, code, label) == (2026, '11011', '2026-Q4')


def test_recent_reports_starts_at_the_current_quarter():
    """최신 분기는 대개 아직 접수 전이다 — 탐침이 뒤로 물러나는 것이 정상이다."""
    assert D.recent_reports('2026-09-21', back=1)[0][2] == '2026-Q3'
