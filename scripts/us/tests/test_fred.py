"""FRED 전송 계층 — 공식 API 로 옮기되 숫자가 한 자리도 달라지면 안 된다.

2026-09-05 이전까지 FRED 접근은 `fredgraph.csv?id=…` — 그래프 서비스의 **비공식**
CSV 출력이었다. 키를 발급받아 공식 API 로 옮기는데, 이 레포에서 가장 비싼 실패는
「데이터가 조용히 달라지는 것」이므로 여기 검사는 전부 그 한 가지를 막는다:
전체 이력을 자르지 않았나 · 정렬이 뒤집히지 않았나 · 키가 거부됐는데 초록불로
지나가지 않나 · 키가 로그로 새지 않나.
"""
import email.message
import io
import json
import urllib.error

import pytest

from scripts.us import fred


def _http_error(code, body='', headers=None):
    hdrs = email.message.Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    return urllib.error.HTTPError(
        url='https://api.stlouisfed.org/fred/series/observations?series_id=X&api_key=SECRETKEY',
        code=code, msg='Bad Request', hdrs=hdrs, fp=io.BytesIO(body.encode()))


class FakeOpener:
    """(url) -> bytes. 스크립트대로 응답하거나 예외를 던진다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        r = self.responses.pop(0) if self.responses else b''
        if isinstance(r, Exception):
            raise r
        return r


def _obs(*pairs, count=None):
    rows = [{'date': d, 'value': v} for d, v in pairs]
    return json.dumps({'count': count if count is not None else len(rows),
                       'observations': rows}).encode()


def _client(opener, **kw):
    kw.setdefault('key', 'SECRETKEY')
    kw.setdefault('min_interval', 0)
    return fred.FredClient(opener=opener, **kw)


# ---------------------------------------------------------------- URL 선택

def test_no_key_uses_the_graph_csv_endpoint():
    op = FakeOpener(b'observation_date,DGS10\n2026-09-01,4.79\n')
    c = fred.FredClient(key=None, opener=op, min_interval=0)
    assert c.series('DGS10') == [('2026-09-01', 4.79)]
    assert op.urls == ['https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10']
    assert c.transport == 'csv' and c.reason == 'no_key'


def test_key_present_uses_the_official_api_with_the_key():
    op = FakeOpener(_obs(('2026-09-01', '4.79')), _obs(('2026-09-01', '4.79')))
    c = _client(op)
    c.series('DGS10')
    assert all(u.startswith(fred.API) for u in op.urls)
    assert 'api_key=SECRETKEY' in op.urls[-1]
    assert c.transport == 'api'


def test_api_request_pins_every_default_that_the_contract_depends_on():
    """FRED 기본값이 지금은 계약에 맞지만 문서화된 약속이 아니다 — 전부 명시한다."""
    op = FakeOpener(_obs(('2026-09-01', '4.79')), _obs(('2026-09-01', '4.79')))
    c = _client(op)
    c.series('DGS10')
    url = op.urls[-1]
    for pin in ('file_type=json', 'sort_order=asc', 'observation_start=1776-07-04',
                'observation_end=9999-12-31', 'units=lin', 'output_type=1',
                f'limit={fred.LIMIT}'):
        assert pin in url, pin


# ---------------------------------------------------------------- 파싱 동치

def test_json_and_csv_paths_parse_to_the_same_rows():
    pairs = [('2026-08-31', '4.75'), ('2026-09-01', '.'), ('2026-09-02', '4.79')]
    api = _client(FakeOpener(_obs(('2000-01-01', '1.0')), _obs(*pairs))).series('X')
    csv_body = b'observation_date,X\n' + b''.join(
        f'{d},{v}\n'.encode() for d, v in pairs)
    csvc = fred.FredClient(key=None, opener=FakeOpener(csv_body), min_interval=0)
    assert api == csvc.series('X') == [('2026-08-31', 4.75), ('2026-09-02', 4.79)]


def test_blank_values_are_dropped_like_dots():
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')),
                           _obs(('2026-09-01', ''), ('2026-09-02', '4.79'))))
    assert c.series('X') == [('2026-09-02', 4.79)]


# ------------------------------------------------- 잘린·뒤집힌 응답은 거부한다

def test_truncated_response_is_rejected_not_silently_shortened():
    body = json.dumps({'count': fred.LIMIT + 5,
                       'observations': [{'date': '2026-09-01', 'value': '1'}]}).encode()
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')), body, _http_error(500)))
    with pytest.raises(fred.FredError):
        c.series('X')


def test_out_of_order_response_is_rejected():
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')),
                           _obs(('2026-09-02', '2'), ('2026-09-01', '1')),
                           _http_error(500)))
    with pytest.raises(fred.FredError):
        c.series('X')


# ---------------------------------------------------------------- 자격증명

def _auth_error():
    return _http_error(400, '{"error_code":400,"error_message":"Bad Request.  '
                            'The value for variable api_key is not registered."}')


def test_rejected_key_degrades_to_csv_once_and_stays_there():
    """400 을 통째로 «키 불량» 으로 읽지 않는다 — 본문이 api_key 를 지목할 때만."""
    csv_body = b'observation_date,X\n2026-09-01,4.79\n'
    op = FakeOpener(_auth_error(), csv_body, csv_body)
    c = _client(op)
    assert c.series('A') == [('2026-09-01', 4.79)]
    assert c.transport == 'csv' and c.reason == 'api_key_rejected'
    c.series('B')
    # 거부는 결정론적이다 — 재시도하지 않고, 남은 호출은 API 를 다시 두드리지 않는다
    assert sum(1 for u in op.urls if u.startswith(fred.API)) == 1


def test_a_bad_series_id_does_not_look_like_a_bad_key():
    bad = _http_error(400, '{"error_code":400,"error_message":'
                           '"Bad Request.  The series does not exist."}')
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')), bad, bad))
    with pytest.raises(fred.FredError):
        c.series('NOSUCH')
    assert c.transport == 'api'          # 전송은 그대로
    assert 'NOSUCH' in c.telemetry()['failed']


def test_rate_limit_does_not_degrade_the_transport():
    csv_body = b'observation_date,X\n2026-09-01,4.79\n'
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')), _http_error(429), csv_body))
    assert c.series('X') == [('2026-09-01', 4.79)]   # CSV 로 구제
    assert c.transport == 'api'
    assert c.telemetry()['csv_rescued'] == ['X']


def test_transient_failure_on_both_paths_raises_rather_than_dropping_the_series():
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')), _http_error(503),
                           _http_error(503)))
    with pytest.raises(fred.FredError):
        c.series('X')
    assert c.telemetry()['failed'] == ['X']


def test_preflight_failure_falls_back_to_csv_without_claiming_the_api():
    csv_body = b'observation_date,X\n2026-09-01,4.79\n'
    c = _client(FakeOpener(_http_error(503), _http_error(503), csv_body))
    assert c.series('X') == [('2026-09-01', 4.79)]
    assert c.transport == 'csv' and c.reason.startswith('preflight_failed')


# ---------------------------------------------------------------- 키 유출

def test_scrub_masks_the_query_pattern_the_constructor_key_and_the_environment(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'ENVKEY')
    text = ('https://api.stlouisfed.org/x?series_id=A&api_key=SECRETKEY&file_type=json '
            'ENVKEY')
    out = fred.scrub(text, key='SECRETKEY')
    assert 'SECRETKEY' not in out and 'ENVKEY' not in out
    assert 'api_key=***' in out and 'file_type=json' in out


def test_scrub_is_case_insensitive_about_the_parameter_name():
    assert 'abc' not in fred.scrub('?API_KEY=abc&x=1')


def test_http_error_url_carries_the_key_so_it_must_not_escape_the_client():
    """실측: HTTPError.url 에는 키가 그대로 들어 있다(str(e) 에는 없다)."""
    raw = _http_error(500)
    assert 'SECRETKEY' in raw.url
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')), raw, _http_error(500)))
    with pytest.raises(fred.FredError) as ei:
        c.series('X')
    assert 'SECRETKEY' not in str(ei.value)
    # 체인 어디에도 원본 HTTPError 가 없어야 한다 — 있으면 traceback 한 줄로 샌다
    e = ei.value
    seen = []
    while e is not None and e not in seen:
        seen.append(e)
        assert not isinstance(e, urllib.error.HTTPError)
        assert 'SECRETKEY' not in str(e)
        e = e.__cause__ or e.__context__


def test_error_body_reaches_the_message_scrubbed():
    err = _http_error(400, '{"error_code":400,"error_message":"Bad Request.  '
                           'The series does not exist."}')
    c = _client(FakeOpener(_obs(('2000-01-01', '1.0')), err, err))
    with pytest.raises(fred.FredError) as ei:
        c.series('X')
    assert 'does not exist' in str(ei.value)
    assert 'SECRETKEY' not in str(ei.value)


# ---------------------------------------------------------------- 실행 위생

def test_a_series_is_fetched_once_per_run():
    op = FakeOpener(_obs(('2000-01-01', '1.0')), _obs(('2026-09-01', '4.79')))
    c = _client(op)
    assert c.series('DGS10') == c.series('DGS10')
    assert len(op.urls) == 2          # 예비검사 + 1회


def test_min_interval_paces_requests():
    slept = []
    now = [0.0]

    def sleep(s):
        slept.append(s)
        now[0] += s

    op = FakeOpener(_obs(('2000-01-01', '1.0')), _obs(('2026-09-01', '1')),
                    _obs(('2026-09-01', '1')))
    c = fred.FredClient(key='K', opener=op, min_interval=0.5,
                        sleep=sleep, clock=lambda: now[0])
    c.series('A')
    c.series('B')
    assert slept and all(0 < s <= 0.5 for s in slept)


def test_retry_after_pushes_the_next_request_out():
    slept = []
    now = [0.0]

    def sleep(s):
        slept.append(s)
        now[0] += s

    csv_body = b'observation_date,X\n2026-09-01,4.79\n'
    op = FakeOpener(_obs(('2000-01-01', '1.0')),
                    _http_error(429, '', {'Retry-After': '7'}), csv_body,
                    _obs(('2026-09-01', '1')))
    c = fred.FredClient(key='K', opener=op, min_interval=0.0,
                        sleep=sleep, clock=lambda: now[0])
    c.series('X')
    c.series('Y')
    assert max(slept) >= 7


def test_forced_transport_skips_the_preflight():
    op = FakeOpener(b'observation_date,X\n2026-09-01,4.79\n')
    c = fred.FredClient(key='K', opener=op, min_interval=0, transport='csv')
    c.series('X')
    assert op.urls == ['https://fred.stlouisfed.org/graph/fredgraph.csv?id=X']


def test_telemetry_reports_the_transport_and_whether_a_key_was_wasted():
    c = _client(FakeOpener(_auth_error(),
                           b'observation_date,X\n2026-09-01,4.79\n'))
    c.series('X')
    t = c.telemetry()
    assert t['transport'] == 'csv' and t['key_configured'] is True
    assert t['degraded'] is True and t['reason'] == 'api_key_rejected'
    assert t['series_ok'] == 1


def test_telemetry_is_not_degraded_when_no_key_is_configured():
    c = fred.FredClient(key=None, opener=FakeOpener(b'observation_date,X\n2026-09-01,1\n'),
                        min_interval=0)
    c.series('X')
    assert c.telemetry()['degraded'] is False


def test_fallback_off_never_silently_serves_csv():
    """진단이 쓰는 모드. 폴백이 켜져 있으면 잘못된 키로도 «identical» 이 나온다 —
    두 클라이언트가 둘 다 CSV 를 읽기 때문이다(2026-09-05 실측으로 잡은 거짓 초록)."""
    csv_body = b'observation_date,X\n2026-09-01,4.79\n'
    op = FakeOpener(_auth_error(), csv_body)
    c = fred.FredClient(key='K', opener=op, min_interval=0, transport='api',
                        fallback=False)
    with pytest.raises(fred.FredError):
        c.series('X')
    assert c.transport == 'api'
    assert not any(u.startswith(fred.CSV) for u in op.urls)


def test_fallback_off_also_refuses_to_degrade_in_preflight():
    c = fred.FredClient(key='K', opener=FakeOpener(_auth_error()), min_interval=0,
                        fallback=False)
    with pytest.raises(fred.FredError):
        c.preflight()
    assert c.transport is None
