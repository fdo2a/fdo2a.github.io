"""TypeSafe Jev 전송 — 섀도 CLI(`japan_region_shadow.py`)와 국내/해외 필터(`common/region_filter.py`, 일본·US·KR)가 같이 쓴다.

공식 HTTPS 호스트 고정, 리다이렉트 거부, 키는 헤더에만(codex 설계 검토 #11 — urllib 은 리다이렉트 때
Authorization 을 새 호스트로 그대로 옮긴다). 오류는 HTTP 코드만 남긴다.
"""
import http.client
import json
import ssl
import urllib.error
import urllib.request

JEV_URL = 'https://api.typesafe.ai/v1/systemone'
JEV_TIMEOUT = 20


class JevHTTPError(Exception):
    """HTTP 코드만 담는다 — urllib 의 HTTPError 는 헤더·본문을 끌고 다닌다."""

    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.code = code


class JevTransportError(Exception):
    """연결·타임아웃·잘린 응답·해독 실패 — 예외 이름만 담는다. 호출자는 이것과 JevHTTPError 만 「전송 실패」로 본다:
    그 밖의 예외(ValueError 포함)는 호출자 코드의 결함이다(codex 재검토 #1)."""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise JevHTTPError(code)


def post(body, key, timeout=JEV_TIMEOUT):
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(JEV_URL, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                                 headers={'Authorization': f'Bearer {key}',
                                          'Content-Type': 'application/json'}, method='POST')
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise JevHTTPError(e.code) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise JevTransportError(type(e).__name__) from None
    try:                       # ValueError 는 해독에서만 전송 실패다 — open() 의 ValueError 는 결함(재검토 2차 #2)
        return json.loads(raw.decode('utf-8'))
    except ValueError as e:
        raise JevTransportError(type(e).__name__) from None
