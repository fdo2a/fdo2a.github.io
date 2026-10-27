"""TypeSafe Jev 전송 — 섀도 CLI(`japan_region_shadow.py`)와 일간 필터(`japan/region_filter.py`)가 같이 쓴다.

공식 HTTPS 호스트 고정, 리다이렉트 거부, 키는 헤더에만(codex 설계 검토 #11 — urllib 은 리다이렉트 때
Authorization 을 새 호스트로 그대로 옮긴다). 오류는 HTTP 코드만 남긴다.
"""
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
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise JevHTTPError(e.code) from None
