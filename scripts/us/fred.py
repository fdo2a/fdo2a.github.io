"""FRED 전송 계층 — 공식 API 우선, 비공식 graph CSV 폴백.

2026-09-05 이전까지 이 레포의 FRED 접근은 `fred.stlouisfed.org/graph/fredgraph.csv?id=…`
하나였다. 키가 없어 그냥 되지만 그것은 **그래프 서비스의 출력**이지 문서화된 API 가
아니다. Yahoo(2026-07-15)·BLS/DOL(2026-08-18)이 조용히 403 으로 돌아선 전례가 둘 있고,
FRED 는 수익률·경제지표·금리 분해·해부 구성항목의 유일한 출처라 여기가 막히면 브리프의
절반이 빈다. 사용자가 API 키를 발급받아 공식 엔드포인트로 옮긴다.

**바꾸는 것은 파이프뿐이다.** `series()` 의 계약은 예전 `fred_series()` 그대로다 —
오래된→최신 `(date, float)`, `.`·빈 값 제거, **전체 이력**. 구간을 자르지 않는 이유는
`macro_metrics` 가 60포인트 모멘텀과 12포인트 YoY 를 이력에서 계산하기 때문이다.

설계·검토 이력은 프로젝트 루트 `plan.md`(2026-09-05).
"""
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.stlouisfed.org/fred/series/observations'
CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv'

# 응답이 잘렸는지 셀 수 있게 상한을 명시로 보낸다. FRED 기본값도 같은 수지만
# 기본값은 약속이 아니다 — 계약이 기본값에 기대면 조용히 짧아진 이력을 받는다.
LIMIT = 100000
# 오름차순·현재 vintage·원계열·전 구간. 여섯 개 전부 지금의 기본값과 같고, 그래서
# 명시하는 값이 있다: 기본값이 바뀌어도 우리 숫자는 안 바뀐다.
PINS = (('file_type', 'json'), ('sort_order', 'asc'),
        ('observation_start', '1776-07-04'), ('observation_end', '9999-12-31'),
        ('units', 'lin'), ('output_type', '1'), ('limit', str(LIMIT)))

_KEY_IN_URL = re.compile(r'(?i)(api_key=)[^&\s\'"]+')
TRANSIENT = (408, 425, 429, 500, 502, 503, 504)
PREFLIGHT_SID = 'DGS10'


def scrub(text, key=None):
    """키를 마스킹한다. 로그·예외로 나가는 모든 문자열에 적용.

    셋을 다 지운다 — 쿼리 패턴 · 생성자가 받은 키 · 환경변수. 어느 하나만으로는
    구멍이 남는다(생성자 키가 환경변수와 다를 수 있고, 패턴만으로는 키가 본문에
    맨몸으로 실려 온 경우를 놓친다). ECOS `scripts/kr/econ.py` 와 같은 규율.
    """
    s = _KEY_IN_URL.sub(r'\1***', str(text))
    for k in (key, os.environ.get('FRED_API_KEY')):
        if k:
            s = s.replace(k, '***')
    return s


class FredError(Exception):
    """살균된 메시지만 든다. 원본 HTTPError 는 이 경계를 넘지 않는다 —
    `HTTPError.url` 에 키가 그대로 들어 있기 때문이다(실측 2026-09-05)."""

    def __init__(self, message, status=None, auth=False, transient=False):
        super().__init__(message)
        self.status = status
        self.auth = auth
        self.transient = transient


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class FredClient:
    """한 실행에 하나. 전송을 예비검사로 **불변** 결정하고 그 뒤로는 안 바꾼다.

    전역이 아니라 인스턴스에 상태를 두는 이유는 테스트·재진입 때문이다. 한 번
    열화한 전역은 그 인터프리터가 끝날 때까지 열화한 채로 남는다.
    """

    def __init__(self, key=None, ssl_ctx=None, min_interval=0.35, timeout=25,
                 opener=None, sleep=None, clock=None, transport=None, fallback=True):
        self.key = (key if key is not None else os.environ.get('FRED_API_KEY')) or None
        self._ssl = ssl_ctx
        self._timeout = timeout
        self._opener = opener
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._min_interval = min_interval
        # 폴백을 끄면 API 가 실패해도 CSV 로 안 내려간다. 진단(`--fred-check`)이
        # 쓴다 — 켜져 있으면 API 클라이언트가 조용히 CSV 로 내려가 **CSV 끼리**
        # 비교하고 「identical」을 인쇄한다(2026-09-05 실측으로 잡은 거짓 초록).
        self.fallback = fallback
        self._last = None
        self._earliest = None
        self.transport = transport
        self.reason = None if transport else ('no_key' if not self.key else None)
        if transport is None and not self.key:
            self.transport = 'csv'
        self._cache = {}
        self.requests = 0
        self.series_ok = 0
        self.failed = []
        self.csv_rescued = []

    # ------------------------------------------------------------ 네트워크

    def _throttle(self):
        now = self._clock()
        floor = self._earliest
        if self._last is not None:
            floor = max(floor or 0, self._last + self._min_interval)
        if floor is not None and now < floor:
            self._sleep(floor - now)
        self._last = self._clock()

    def _open(self, url):
        self._throttle()
        self.requests += 1
        if self._opener is not None:
            return self._opener(url, self._timeout)
        ctx = self._ssl if self._ssl is not None else _ssl_context()
        return urllib.request.urlopen(url, timeout=self._timeout, context=ctx).read()

    def _get(self, url):
        """살균된 예외만 던진다.

        `raise … from None` 으로는 모자란다 — except 블록 **안에서** 던지면
        `__context__` 에 원본 `HTTPError` 가 그대로 매달리고, 그 객체의 `.url` 에는
        키가 들어 있다. 그래서 예외를 만들어 두고 블록 **밖에서** 던진다.
        """
        err = None
        try:
            return self._open(url)
        except urllib.error.HTTPError as e:
            err = self._as_error(e)
        except Exception as e:
            err = FredError(scrub(f'{type(e).__name__}: {e}', self.key), transient=True)
        raise err

    def _as_error(self, e):
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:500]
        except Exception:
            pass
        msg = body
        try:
            msg = json.loads(body).get('error_message') or body
        except Exception:
            pass
        if e.code == 429:
            self._honor_retry_after(e)
        return FredError(scrub(f'HTTP {e.code}: {msg or e.reason}', self.key),
                         status=e.code, auth='api_key' in (msg or '').lower(),
                         transient=e.code in TRANSIENT)

    def _honor_retry_after(self, e):
        try:
            wait = float((e.headers or {}).get('Retry-After') or 0)
        except (TypeError, ValueError):
            return
        if wait > 0:
            self._earliest = self._clock() + min(wait, 60)

    # ------------------------------------------------------------ 파싱

    def _api_url(self, sid, limit=None):
        q = [('series_id', sid), ('api_key', self.key or '')]
        q += [(k, str(limit) if k == 'limit' and limit else v) for k, v in PINS]
        return API + '?' + urllib.parse.urlencode(q)

    def _api(self, sid):
        payload = json.loads(self._get(self._api_url(sid)).decode('utf-8'))
        obs = payload.get('observations') or []
        count = payload.get('count')
        if isinstance(count, int) and count > LIMIT:
            raise FredError(f'{sid}: truncated response ({count} > limit {LIMIT})')
        rows = _pairs((o.get('date'), o.get('value')) for o in obs)
        _assert_ascending(sid, rows)
        return rows

    def _csv(self, sid):
        body = self._get(f'{CSV}?id={sid}').decode('utf-8')
        rows = _pairs(tuple(line.split(',')[:2])
                      for line in body.splitlines()[1:] if ',' in line)
        _assert_ascending(sid, rows)
        return rows

    # ------------------------------------------------------------ 공개 API

    def preflight(self):
        """생산 호출 **전에** 전송을 한 번 정한다. 실행 중간에 안 바꾸는 이유는
        섞인 실행을 하나로 이름 붙이면 텔레메트리가 거짓말이 되기 때문이다."""
        if self.transport:
            return self.transport
        last = None
        for _ in range(2):
            try:
                self._api_probe()
                self.transport = 'api'
                return self.transport
            except FredError as e:
                last = e
                if not self.fallback:
                    raise
                if e.auth:
                    self._degrade('api_key_rejected')
                    return self.transport
        self._degrade(f'preflight_failed:{last.status or "error"}' if last
                      else 'preflight_failed')
        return self.transport

    def _api_probe(self):
        json.loads(self._get(self._api_url(PREFLIGHT_SID, limit=1)).decode('utf-8'))

    def _degrade(self, reason):
        self.transport = 'csv'
        self.reason = reason

    def series(self, sid):
        """오래된→최신 `(date, float)`. 실패는 예외 — 호출부 `retry()` 가 받는다."""
        if sid in self._cache:
            return self._cache[sid]
        if not self.transport:
            self.preflight()
        try:
            rows = self._fetch(sid)
        except FredError:
            if sid not in self.failed:
                self.failed.append(sid)
            raise
        self._cache[sid] = rows
        self.series_ok += 1
        return rows

    def _fetch(self, sid):
        if self.transport != 'api':
            return self._csv(sid)
        try:
            return self._api(sid)
        except FredError as e:
            if not self.fallback:
                raise
            if e.auth:
                # 키가 실행 도중 거부됐다 — 남은 수십 회를 같은 벽에 던지지 않는다.
                self._degrade('api_key_rejected')
                return self._csv(sid)
            # 일시 실패. 시리즈를 통째로 잃는 것이 더 비싸다 — 무키 시절 경로로
            # 한 번 구제한다. 둘 다 실패하면 원래 예외를 올린다.
            rescued = None
            try:
                rows = self._csv(sid)
                rescued = rows
            except FredError:
                pass
            if rescued is None:
                raise e
            if sid not in self.csv_rescued:
                self.csv_rescued.append(sid)
            return rows

    def telemetry(self):
        return {'transport': self.transport or 'unknown',
                'reason': self.reason,
                'key_configured': bool(self.key),
                'degraded': bool(self.key) and self.transport != 'api',
                'requests': self.requests,
                'series_ok': self.series_ok,
                'failed': sorted(self.failed),
                'csv_rescued': sorted(self.csv_rescued)}


def _pairs(rows):
    out = []
    for d, v in rows:
        if not d or v in ('.', '', None):
            continue
        try:
            out.append((d.strip(), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def _assert_ascending(sid, rows):
    for a, b in zip(rows, rows[1:]):
        if a[0] > b[0]:
            raise FredError(f'{sid}: observations are not in ascending date order')
