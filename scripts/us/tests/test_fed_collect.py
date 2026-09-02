"""수집기가 «못 받은 것을 받았다고 하지 않는지»만 본다.

네트워크는 건드리지 않는다 — 가짜 응답과 가짜 피드를 넣고, 실패가 실패로 남는지,
그리고 실패한 날이 이벤트를 소진하지 않는지를 본다.
"""
import importlib
import json
import sys
import types

import pytest

collect = importlib.import_module('collect_fed_events')


class Resp:
    def __init__(self, body=b'', text='', ctype='text/html'):
        self.content = body
        self.text = text
        self.headers = {'content-type': ctype}
        self.status_code = 200


def test_pdf_extraction_failure_is_not_a_body(monkeypatch):
    """실패 문구가 원문으로 기록되면 그 문구가 인용 대조의 «원문»이 된다."""
    broken = types.ModuleType('pypdf')

    class PdfReader:
        def __init__(self, *a, **k):
            raise ValueError('xref broken')
    broken.PdfReader = PdfReader
    monkeypatch.setitem(sys.modules, 'pypdf', broken)

    out = collect.body(Resp(body=b'%PDF-1.4 broken', ctype='application/pdf'),
                       'https://x/FOMCpresconf20260917.pdf')
    assert out is None
    assert not bool(out)          # 호출부의 ok=bool(text) 가 False 로 읽는다


def test_html_body_still_extracts():
    out = collect.body(Resp(text='<p>Chairman said <b>this</b>.</p>'), 'https://x/a.htm')
    assert 'Chairman said this' in out


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / 'market_data.json').write_text(
        json.dumps({'report_date': '2026-09-17'}), encoding='utf-8')
    monkeypatch.setattr(collect, 'discover', lambda rd: [{
        'kind': 'fomc_statement', 'date8': '20260917', 'speaker': None, 'role': None,
        'item': {'title': 'Federal Reserve issues FOMC statement',
                 'link': 'https://www.federalreserve.gov/newsevents/pressreleases/'
                         'monetary20260917a.htm', 'published': '2026-09-17'}}])
    monkeypatch.setattr(sys, 'argv', ['x', '--datadir', str(tmp_path)])
    return tmp_path


def test_a_day_that_fetched_nothing_does_not_burn_the_event(workspace, monkeypatch):
    """수집이 실패한 날 이벤트를 소진하면, 정작 원문을 받은 날 섹션이 안 열린다."""
    monkeypatch.setattr(collect, 'fetch', lambda url: (None, 'HTTP 403'))
    collect.main()

    book = json.loads((workspace / 'fed' / 'events.json').read_text(encoding='utf-8'))
    assert book['events'][0]['fresh'] is False
    assert book['events'][0]['first_seen'] is None
    assert json.loads((workspace / 'fed' / 'seen.json').read_text(encoding='utf-8')) == {}

    # 다음 날 원문이 열리면 그날이 첫날이 된다.
    monkeypatch.setattr(collect, 'fetch',
                        lambda url: (Resp(text='<p>The Committee decided to hold.</p>'), 'ok'))
    collect.main()
    book = json.loads((workspace / 'fed' / 'events.json').read_text(encoding='utf-8'))
    fresh = [e for e in book['events'] if e['fresh']]
    assert len(fresh) == 1 and fresh[0]['first_seen'] == '2026-09-17'


def test_a_successful_day_marks_the_event_seen(workspace, monkeypatch):
    monkeypatch.setattr(collect, 'fetch',
                        lambda url: (Resp(text='<p>The Committee decided to hold.</p>'), 'ok'))
    collect.main()
    seen = json.loads((workspace / 'fed' / 'seen.json').read_text(encoding='utf-8'))
    assert 'fomc-statement-20260917' in seen
    assert (workspace / 'fed' / 'fomc-statement-20260917.txt').exists()


def test_events_json_is_written_even_on_a_quiet_day(tmp_path, monkeypatch):
    """파일이 아예 없는 것과 「오늘은 이벤트가 없다」는 다르다."""
    (tmp_path / 'market_data.json').write_text(
        json.dumps({'report_date': '2026-09-17'}), encoding='utf-8')
    monkeypatch.setattr(collect, 'discover', lambda rd: [])
    monkeypatch.setattr(sys, 'argv', ['x', '--datadir', str(tmp_path)])
    collect.main()
    book = json.loads((tmp_path / 'fed' / 'events.json').read_text(encoding='utf-8'))
    assert book == {'report_date': '2026-09-17', 'events': [], 'diff': None}


# ── CLI 게이트의 «닫히면서 실패하기» ─────────────────────────────────────────

check_fed = importlib.import_module('check_fed')

SECTION_PAGE = ('<html><body><main><h2>연준 이벤트 — 발언록과 해석</h2>'
                '<p>본문</p><h2>다음</h2></main></body></html>')


def _run(tmp_path, html, monkeypatch):
    page = tmp_path / 'brief.html'
    page.write_text(html, encoding='utf-8')
    monkeypatch.setattr(sys, 'argv',
                        ['x', '--html', str(page), '--datadir', str(tmp_path)])
    try:
        check_fed.main()
    except SystemExit as e:
        return e.code or 0
    return 0


def test_unknown_report_date_blocks_a_published_section(tmp_path, monkeypatch):
    """오늘이 언제인지 모르면 책이 오늘 것인지도 모른다 — 통과시키지 않는다."""
    (tmp_path / 'fed').mkdir()
    (tmp_path / 'fed' / 'events.json').write_text(
        json.dumps({'report_date': '2026-01-01', 'events': [], 'diff': None}),
        encoding='utf-8')
    assert _run(tmp_path, SECTION_PAGE, monkeypatch) == 1


def test_unknown_report_date_without_a_section_passes(tmp_path, monkeypatch):
    (tmp_path / 'fed').mkdir()
    (tmp_path / 'fed' / 'events.json').write_text(
        json.dumps({'report_date': '2026-01-01', 'events': [], 'diff': None}),
        encoding='utf-8')
    assert _run(tmp_path, '<html><body><main><h2>주식</h2></main></body></html>',
                monkeypatch) == 0


def test_corrupt_events_json_fails_rather_than_being_excused(tmp_path, monkeypatch):
    (tmp_path / 'fed').mkdir()
    (tmp_path / 'fed' / 'events.json').write_text('{ not json', encoding='utf-8')
    assert _run(tmp_path, SECTION_PAGE, monkeypatch) == 1
