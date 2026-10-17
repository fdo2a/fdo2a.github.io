"""SEC EDGAR — Micron 공시를 DART 와 같은 사건 계약으로.

설계: docs/superpowers/specs/2026-10-17-sec-edgar-micron-feed.md
"""
import urllib.error

import pytest

from thesis import edgar as E
from thesis import gate as G
from thesis import triggers as T

CIK = '0000723125'


def submissions(rows, tickers=('MU',), name='MICRON TECHNOLOGY INC'):
    """Parallel arrays, the way data.sec.gov serves `filings.recent`."""
    keys = ('accessionNumber', 'filingDate', 'reportDate', 'acceptanceDateTime', 'form',
            'items', 'primaryDocument', 'primaryDocDescription')
    recent = {k: [r.get(k, '') for r in rows] for k in keys}
    return {'cik': CIK.lstrip('0'), 'name': name, 'tickers': list(tickers),
            'filings': {'recent': recent, 'files': []}}


def row(form='8-K', items='2.02,9.01', accepted='2026-10-01T00:02:22.000Z',
        acc='0000723125-26-000018', filed='2026-09-30', doc='mu-20260930.htm'):
    return {'accessionNumber': acc, 'filingDate': filed, 'reportDate': filed,
            'acceptanceDateTime': accepted, 'form': form, 'items': items,
            'primaryDocument': doc, 'primaryDocDescription': form}


# ── 분류: 좁은 confirmed, 넓은 notable ──

@pytest.mark.parametrize('form, items, axis', [
    ('8-K', '2.02,9.01', 'contract'),
    ('8-K', '2.03,9.01', 'capital'),
    ('8-K', '3.02', 'capital'),
    ('8-K', '2.06', 'financials'),
    ('8-K', '4.02', 'financials'),
    ('10-K', '', 'financials'),
    ('10-Q', '', 'financials'),
    ('SCHEDULE 13D', '', 'ownership'),
    ('SC 13D', '', 'ownership'),
])
def test_whitelisted_filings_are_confirmed_with_an_axis(form, items, axis):
    verdict = E.classify(form, items)
    assert verdict['confirmed'] is True and verdict['notable'] is False
    assert verdict['axis'] == axis


def test_a_multi_item_8k_takes_the_strongest_axis():
    assert E.classify('8-K', '2.03,2.02')['axis'] == 'contract'
    assert E.classify('8-K', '5.02,2.06,9.01')['axis'] == 'financials'


@pytest.mark.parametrize('form, items', [
    ('8-K', '1.01,9.01'),       # Micron 의 1.01 은 사채·신용계약이 많다 — kill 축을 주면 안 된다
    ('8-K', '1.02'),
    ('8-K', '1.05'),            # cybersecurity incident
    ('8-K', '5.02,9.01'),       # officers — DART 도 확정하지 않는다
    ('8-K', '7.01,9.01'),       # 2025-08-11 guidance update, 2023-05-22 CAC ruling
    ('8-K', '8.01,9.01'),       # 2025-06-12 CHIPS
    ('8-K/A', '2.02,9.01'),     # 실적 정정 — 숫자가 바뀔 수 있다
    ('NT 10-Q', ''),
])
def test_notable_filings_break_the_quiet_without_an_axis(form, items):
    verdict = E.classify(form, items)
    assert verdict['notable'] is True and verdict['confirmed'] is False
    assert E.event_axes([{**verdict}]) == ()


@pytest.mark.parametrize('form, items', [
    ('8-K', '9.01'),            # exhibits only
    ('8-K', '5.07'),            # shareholder vote
    ('8-K', '5.03'),            # bylaws
    ('4', ''), ('3', ''), ('144', ''),
    ('SCHEDULE 13G/A', ''), ('SCHEDULE 13G', ''),
    ('S-8', ''), ('424B2', ''), ('FWP', ''), ('DEF 14A', ''), ('SD', ''),
    ('10-K/A', ''), ('', ''),
])
def test_everything_else_is_recorded_silently(form, items):
    verdict = E.classify(form, items)
    assert verdict['confirmed'] is False and verdict['notable'] is False


@pytest.mark.parametrize('form', ['8-K/A', '10-K/A', '10-Q/A', 'SCHEDULE 13D/A'])
def test_amendments_are_corrections_and_not_confirmed(form):
    """원 공시가 이미 사건으로 잡혔다 — DART 기재정정과 같은 이유로 두 번 세지 않는다."""
    verdict = E.classify(form, '2.02')
    assert verdict['correction'] is True and verdict['confirmed'] is False


def test_items_parse_tolerates_spaces_and_blanks():
    assert E.parse_items(' 2.02, 9.01 ') == ['2.02', '9.01']
    assert E.parse_items('') == [] and E.parse_items(None) == []


# ── 응답 파싱 ──

def test_filings_zips_the_parallel_arrays():
    out = E.filings(submissions([row(), row(form='4', items='', acc='a2')]))
    assert [f['form'] for f in out] == ['8-K', '4']
    assert out[0]['accessionNumber'] == '0000723125-26-000018'


def test_filings_of_a_malformed_payload_raise():
    """빈 목록과 깨진 응답은 다르다 — 깨진 응답이 조용한 날로 읽히면 안 된다."""
    with pytest.raises(RuntimeError):
        E.filings({'name': 'x'})


def test_cik_is_verified_against_the_ticker():
    assert E.verify(submissions([]), 'MU') is True
    assert E.verify(submissions([], tickers=('AAPL',)), 'MU') is False
    assert E.verify({}, 'MU') is False


def test_to_event_matches_the_dart_event_keys():
    ev = E.to_event(row(), CIK, 'MICRON TECHNOLOGY INC')
    for key in ('rcept_no', 'date', 'title', 'corp', 'filer', 'url', 'axis', 'kind',
                'correction', 'confirmed'):
        assert key in ev
    assert ev['rcept_no'] == '0000723125-26-000018'
    assert ev['date'] == '2026-09-30'
    assert ev['accepted_et'] == '2026-09-30 16:02:22 ET'
    assert ev['form'] == '8-K' and ev['items'] == ['2.02', '9.01']
    assert ev['axis'] == 'contract' and ev['confirmed'] is True


def test_to_event_url_is_the_primary_document_under_the_archive():
    ev = E.to_event(row(), CIK, 'MICRON TECHNOLOGY INC')
    assert ev['url'] == ('https://www.sec.gov/Archives/edgar/data/723125/'
                         '000072312526000018/mu-20260930.htm')


def test_to_event_without_a_primary_document_falls_back_to_the_index():
    ev = E.to_event(row(doc=''), CIK, 'MICRON TECHNOLOGY INC')
    assert ev['url'] == ('https://www.sec.gov/Archives/edgar/data/723125/'
                         '000072312526000018/0000723125-26-000018-index.htm')


# ── 접수 시각: SEC 의 `Z` 는 UTC 가 아니다 ──

def test_accepted_et_undoes_the_doubled_offset_in_summer():
    """EDGAR 색인 페이지: 2026-09-30 16:02:22 (EDT). JSON: 2026-10-01T00:02:22Z."""
    assert E.accepted_et(row(accepted='2026-10-01T00:02:22.000Z')) == '2026-09-30 16:02:22 ET'
    assert E.accepted_et(row(accepted='2026-10-09T16:21:00.000Z')) == '2026-10-09 08:21:00 ET'


def test_accepted_et_undoes_the_doubled_offset_in_winter():
    """EDGAR 색인 페이지: 2025-12-17 16:03:26 (EST). JSON: 2025-12-18T02:03:26Z."""
    assert E.accepted_et(row(accepted='2025-12-18T02:03:26.000Z')) == '2025-12-17 16:03:26 ET'
    assert E.accepted_et(row(accepted='2025-12-18T04:47:44.000Z')) == '2025-12-17 18:47:44 ET'


def test_accepted_et_of_garbage_is_none():
    assert E.accepted_et(row(accepted='')) is None
    assert E.accepted_et(row(accepted='soon')) is None


# ── 창: filingDate, DART 처럼 하루 겹친다 ──

HIST = [{'date': '2026-09-29'}, {'date': '2026-09-30'}]


def test_window_starts_the_day_before_the_last_collection():
    assert E.window(HIST, '2026-10-01') == ('2026-09-29', '2026-10-01')


def test_window_covers_a_gap_so_a_missed_day_is_filled():
    assert E.window([{'date': '2026-09-25'}], '2026-10-01') == ('2026-09-24', '2026-10-01')


def test_window_is_capped():
    assert E.window([{'date': '2026-06-01'}], '2026-10-01') == ('2026-09-01', '2026-10-01')
    assert E.window([], '2026-10-01') == ('2026-09-01', '2026-10-01')


def test_two_collections_on_one_day_do_not_lose_the_first_ones_filings():
    """10/14 01:24·22:59 KST 처럼 하루 두 번 돌면, 두 번째도 앞 실행이 본 공시를 다시 담는다."""
    first_run = E.window(HIST, '2026-10-01')
    second_run = E.window(HIST + [{'date': '2026-10-01'}], '2026-10-01')
    assert second_run[0] <= '2026-09-30' and first_run[1] == second_run[1]


def test_in_window_is_inclusive_on_filing_date():
    assert E.in_window(row(filed='2026-09-29'), '2026-09-29', '2026-10-01')
    assert E.in_window(row(filed='2026-10-01'), '2026-09-29', '2026-10-01')
    assert not E.in_window(row(filed='2026-09-28'), '2026-09-29', '2026-10-01')
    assert not E.in_window(row(filed=''), '2026-09-29', '2026-10-01')


# ── 사건 계약: DART 와 같은 자리에 꽂힌다 ──

def test_an_earnings_8k_supplies_the_contract_axis():
    events = [E.to_event(row(), CIK, 'MICRON TECHNOLOGY INC')]
    assert T.kill_axes([{'key': 'bear_proximity'}], E.event_axes(events)) == (
        'contract', 'price')


def test_a_debt_indenture_1_01_never_reaches_the_kill_gate():
    events = [E.to_event(row(items='1.01,2.03,9.01'), CIK, 'MICRON TECHNOLOGY INC')]
    assert 'contract' not in T.kill_axes([{'key': 'bear_proximity'}], E.event_axes(events))


def test_a_day_of_only_form_4s_is_still_a_quiet_day():
    events = [E.to_event(row(form='4', items=''), CIK, 'MICRON TECHNOLOGY INC')]
    assert G.check_silence([], events, page_changed=True) is not None


# ── 네트워크: UA 를 밝힌다 ──

def test_user_agent_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv('SEC_USER_AGENT', 'Someone research someone@example.com')
    assert E.user_agent() == 'Someone research someone@example.com'


def test_user_agent_default_is_declared_never_urllibs(monkeypatch):
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    ua = E.user_agent()
    assert ua and 'urllib' not in ua.lower() and 'github' not in ua.lower()


def test_blank_user_agent_variable_falls_back_to_the_default(monkeypatch):
    """Actions 는 정의되지 않은 vars 를 빈 문자열로 넘긴다."""
    monkeypatch.setenv('SEC_USER_AGENT', '  ')
    assert E.user_agent() == E.DEFAULT_USER_AGENT


# ── 수집 ──

def test_collect_reports_only_filings_inside_the_window():
    payload = submissions([
        row(),                                                           # 09-30 — in
        row(form='8-K', items='7.01', acc='a-fd', filed='2026-09-29'),   # in, notable
        row(form='4', items='', acc='a-old', filed='2026-09-28'),        # before
    ])
    out = E.collect({'MU': CIK}, HIST, '2026-10-01', fetch=lambda cik: payload)
    mu = out['tickers']['MU']
    assert [e['rcept_no'] for e in mu['events']] == ['0000723125-26-000018', 'a-fd']
    assert mu['confirmed_count'] == 1 and mu['notable_count'] == 1
    assert mu['axes'] == ['contract'] and mu['cik'] == CIK
    assert out['missing'] == []
    assert out['sec']['window'] == {'first': '2026-09-29', 'last': '2026-10-01'}


def test_a_failed_fetch_is_missing():
    def boom(cik):
        raise RuntimeError('SEC 403')
    out = E.collect({'MU': CIK}, HIST, '2026-10-01', fetch=boom)
    assert out['tickers'] == {} and out['missing'] == ['MU:SEC 403']


def test_a_mismatched_cik_is_missing_not_a_quiet_day():
    out = E.collect({'MU': CIK}, HIST, '2026-10-01',
                    fetch=lambda cik: submissions([row()], tickers=('AAPL',)))
    assert out['missing'] == ['MU:cik'] and 'MU' not in out['tickers']


def test_a_malformed_payload_is_missing_not_a_quiet_day():
    out = E.collect({'MU': CIK}, HIST, '2026-10-01', fetch=lambda cik: {'tickers': ['MU']})
    assert out['missing'] and 'MU' not in out['tickers']


def test_an_empty_window_is_a_row_with_zero_counts():
    out = E.collect({'MU': CIK}, HIST, '2026-10-01', fetch=lambda cik: submissions([]))
    assert out['tickers']['MU']['confirmed_count'] == 0
    assert out['tickers']['MU']['notable_count'] == 0


class _Resp:
    def __init__(self, body, headers=None):
        self._body, self.headers = body, headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_sends_the_declared_user_agent_and_reads_gzip(monkeypatch):
    import gzip
    import json
    seen = {}

    def fake(req, timeout, context):
        seen['ua'] = req.get_header('User-agent')
        return _Resp(gzip.compress(json.dumps({'ok': 1}).encode()),
                     {'Content-Encoding': 'gzip'})
    monkeypatch.delenv('SEC_USER_AGENT', raising=False)
    monkeypatch.setattr(E.urllib.request, 'urlopen', fake)
    assert E.fetch_submissions(CIK) == {'ok': 1}
    assert seen['ua'] == E.DEFAULT_USER_AGENT


def test_fetch_does_not_retry_a_403(monkeypatch):
    calls = []

    def fake(req, timeout, context):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(E.urllib.request, 'urlopen', fake)
    monkeypatch.setattr(E.time, 'sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='SEC 403'):
        E.fetch_submissions(CIK)
    assert len(calls) == 1


def test_fetch_retries_a_5xx_then_gives_up(monkeypatch):
    calls = []

    def fake(req, timeout, context):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 503, 'Busy', {}, None)
    monkeypatch.setattr(E.urllib.request, 'urlopen', fake)
    monkeypatch.setattr(E.time, 'sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='SEC 503'):
        E.fetch_submissions(CIK)
    assert len(calls) == 3


def test_merge_keeps_dart_rows_and_appends_missing():
    dart = {'as_of': '2026-10-01', 'missing': ['000660.KS:DART 020'],
            'tickers': {'005930.KS': {'confirmed_count': 1, 'events': []}}}
    sec = E.collect({'MU': CIK}, HIST, '2026-10-01', fetch=lambda cik: submissions([row()]))
    sec['missing'] = ['X:y']
    out = E.merge(dart, sec)
    assert set(out['tickers']) == {'005930.KS', 'MU'}
    assert out['missing'] == ['000660.KS:DART 020', 'X:y']
    assert out['sec']['window']['last'] == '2026-10-01'


def test_merge_into_a_pending_dart_payload_without_tickers():
    """DART 키가 없어도(pending) MU 는 수집된다 — DART 의 조기 반환이 MU 를 건너뛰면 안 된다."""
    dart = {'as_of': '2026-10-01', 'pending': True, 'tickers': {}, 'missing': []}
    out = E.merge(dart, E.collect({'MU': CIK}, HIST, '2026-10-01',
                                  fetch=lambda c: submissions([])))
    assert 'MU' in out['tickers'] and out['pending'] is True


def test_filer_is_unknown_rather_than_guessed():
    assert E.to_event(row(form='4', items=''), CIK, 'MICRON TECHNOLOGY INC')['filer'] is None
