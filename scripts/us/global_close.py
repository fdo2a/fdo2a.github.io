"""세계 지수의 「그 세션의 확정 종가」 — 날짜가 붙은 네이버 종가를 야후와 맞춰 본 것만 싣는다.

**왜 있나.** 야후는 거래소 현지 자정이 지나면 마지막 일봉의 종가를 비우고 몇 시간 뒤 다시 채운다
(2026-11-19 실측: 02:00 CET 전부터 비었다가 03:25 CET 에 같은 값으로 채워짐). yfinance 는 빈 행을
버리므로 「report_date 이하 마지막 행」은 전 세션이 되고, 그 값이 그날 마감처럼 실렸다 — 미국 수집
시각에는 아시아가 늘, 유럽이 18:00 ET 뒤 재수집에서, 한국 수집은 자정 뒤 재수집에서 그랬다.

**규칙.** 값과 날짜가 함께 오는 네이버 세계 지수 일별 종가를 쓰고, 야후가 ① 같은 세션을 최신으로
말하고 ② 그 종가와 ③ 직전 세션 종가가 0.01% 안에서 같을 때만 싣는다. 하나라도 아니면 그 지수는
그날 「없음」이고 이유를 남긴다. **전 세션으로 내려가지 않는다.**

`settle_close` 는 순수하다. 네트워크는 `collect` 에만 있고, 미국 수집기와 한국 수집기가 함께 쓴다.
설계·실측·검토 기록: `../plans/2026-11-19-us-collect-wait.md` (B 절).
"""
import datetime as _dt
import json
import math
import sys
import threading
import urllib.parse
import urllib.request

NAVER_INDEX = 'https://api.stock.naver.com/index'
NAVER_CODES = {'^N225': '.N225', '^HSI': '.HSI', '000001.SS': '.SSEC', '^TWII': '.TWII',
               '^GDAXI': '.GDAXI', '^FTSE': '.FTSE', '^STOXX50E': '.STOXX50E'}

# 그 지수의 공식 종가가 찍히는 현지 시각. 네이버 행의 시각이 이보다 이르면 종가 경매 전 값일 수 있어
# 싣지 않는다. 실측(11/13-11/19) 네이버 시각: 15:45:03 · 16:08:28-36 · 15:00 · 13:33 · 17:35 · 16:35 · 18:00.
# 항셍 16:08 은 종가 경매의 무작위 마감(16:08-16:10)이 시작하는 시각이다 — 16:10 으로 올리면 항셍이
# 매일 빠진다(사용자 결정 2026-11-19: 16:08). 반일장에는 종가 시각이 이르므로 그날 그 지수는 빠진다.
CLOSE_PRINT_LOCAL = {'^N225': (15, 30), '^HSI': (16, 8), '000001.SS': (15, 0), '^TWII': (13, 30),
                     '^GDAXI': (17, 35), '^FTSE': (16, 35), '^STOXX50E': (18, 0)}

MATCH_TOL = 1e-4            # 0.01% — 야후는 FTSE 일봉을 소수 첫째 자리로 준다(10551.2 대 10551.17 = 0.0003%)
UNPARSEABLE = 'unparseable'
FETCH_WALL_S = 120          # 지수 전체를 받는 벽시계 상한
REQUEST_TIMEOUT_S = 10

NOTE_KO = {
    'fetch_timeout': '두 원천을 제한 시간 안에 받지 못했다',
    'naver_fetch_failed': '네이버 종가를 받지 못했다',
    'yahoo_fetch_failed': '대조할 야후 자료를 받지 못했다',
    'naver_unparseable': '네이버 응답에 읽지 못한 행이 있다',
    'naver_unordered': '네이버 응답의 날짜 순서가 어긋났다',
    'naver_no_previous': '네이버에 직전 세션 종가가 없다',
    'naver_session_open': '그 세션이 끝났는지 확인하지 못했다',
    'naver_stamp_before_close': '네이버 값의 시각이 그 지수의 종가 시각보다 이르다',
    'naver_stamp_future': '네이버 값의 시각이 수집 시각보다 뒤다',
    'latest_session_disagree': '두 원천이 말하는 최신 세션이 다르다',
    'yahoo_no_value': '야후에 그 세션의 값이 없어 대조하지 못했다',
    'value_disagree': '두 원천의 종가가 다르다',
    'previous_disagree': '직전 세션이 두 원천에서 맞지 않는다',
    'unknown_index': '종가 시각을 모르는 지수다',
}


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _missing(reason, date=None):
    return {'status': 'missing', 'reason': reason, 'date': date}


def _close_to(a, b):
    return _finite(a) and _finite(b) and b > 0 and abs(a / b - 1) <= MATCH_TOL


def parse_naver_rows(payload):
    """`/index/<코드>/price` 응답 → [{'date','close','epoch','hm'}] (응답 순서 그대로) 또는 UNPARSEABLE.

    **행을 버리지 않는다.** 값을 못 읽은 행은 close=None 으로 남긴다 — 버리면 최신 세션이나 두 세션
    사이의 세션이 가려져, 뒤에 있는 행이 최신·직전인 것처럼 읽힌다(codex 설계 검토 1회 G1·G3).
    시각을 못 읽은 행이 하나라도 있으면 목록 전체를 못 쓴다.
    """
    if not isinstance(payload, list) or not payload:
        return None
    out = []
    for row in payload:
        if not isinstance(row, dict):
            return UNPARSEABLE
        try:
            ts = _dt.datetime.fromisoformat(str(row.get('localTradedAt')))
        except ValueError:
            return UNPARSEABLE
        if ts.tzinfo is None:
            return UNPARSEABLE
        try:
            close = float(str(row.get('closePrice')).replace(',', ''))
        except ValueError:
            close = None
        if not (_finite(close) and close > 0):
            close = None
        out.append({'date': ts.date().isoformat(), 'close': close, 'epoch': ts.timestamp(),
                    'hm': (ts.hour, ts.minute)})
    return out


def parse_naver_live(payload):
    """`/index/<코드>/basic` 응답 → {'status','date'} 또는 None."""
    if not isinstance(payload, dict):
        return None
    try:
        ts = _dt.datetime.fromisoformat(str(payload.get('localTradedAt')))
    except ValueError:
        return None
    status = payload.get('marketStatus')
    if ts.tzinfo is None or not isinstance(status, str):
        return None
    return {'status': status, 'date': ts.date().isoformat()}


def settle_close(ticker, naver, naver_live, yahoo_bars, yahoo_quote, report_date, now):
    """한 지수의 판정. -> {'status': 'ok', close, prev_close, date, basis, xcheck} 또는
    {'status': 'missing', reason, date}.

    naver: `parse_naver_rows` 결과 · naver_live: `parse_naver_live` 결과 ·
    yahoo_bars: [(현지 날짜, 종가|None)] 응답의 **모든** 행(빈 종가 포함, report_date 로 자르지 않은 것) ·
    yahoo_quote: {'price', 'date'(시세 시각의 현지 날짜)} 또는 None · now: epoch 초.
    """
    rd = str(report_date)
    floor = CLOSE_PRINT_LOCAL.get(ticker)
    if floor is None:
        return _missing('unknown_index')
    if naver == UNPARSEABLE:
        return _missing('naver_unparseable')
    if not naver:
        return _missing('naver_fetch_failed')
    if not yahoo_bars:
        return _missing('yahoo_fetch_failed')
    dates = [r['date'] for r in naver]
    if any(a <= b for a, b in zip(dates, dates[1:])):
        return _missing('naver_unordered')

    # S = report_date 이하 첫 행, P = 응답에서 그 바로 다음 행. 두 행은 붙어 있다.
    i = next((k for k, d in enumerate(dates) if d <= rd), None)
    if i is None or i + 1 >= len(naver):
        return _missing('naver_no_previous', dates[i] if i is not None else None)
    s_row, p_row = naver[i], naver[i + 1]
    S, P = s_row['date'], p_row['date']
    if s_row['close'] is None or p_row['close'] is None:
        return _missing('naver_unparseable', S)

    # S 가 끝난 세션인가: 실시간 시세가 더 뒤 날짜이거나, 같은 날이고 장이 닫혔다.
    live_ok = bool(naver_live) and (naver_live['date'] > S or (
        naver_live['date'] == S and naver_live['status'] == 'CLOSE'))
    if not live_ok:
        return _missing('naver_session_open', S)
    # 그 행 자신이 종가 시각의 값인가 — 종가 경매 전 값은 마감 전 시각을 달고 있다.
    if s_row['hm'] < floor:
        return _missing('naver_stamp_before_close', S)
    if not _finite(now) or s_row['epoch'] > now:
        return _missing('naver_stamp_future', S)

    # 두 원천이 같은 세션을 최신으로 말하는가. 야후의 빈 행·시세 날짜도 「그 세션이 있었다」는 증거다.
    bars = [(str(d), c) for d, c in yahoo_bars]
    q_date = str(yahoo_quote['date']) if yahoo_quote and yahoo_quote.get('date') else None
    seen = [d for d, _ in bars if d <= rd] + ([q_date] if q_date and q_date <= rd else [])
    if not seen or max(seen) != S:
        return _missing('latest_session_disagree', S)

    by_date = {}
    for d, c in bars:
        by_date.setdefault(d, []).append(c if _finite(c) and c > 0 else None)
    if any(len(v) > 1 for v in by_date.values()):
        return _missing('yahoo_fetch_failed', S)          # 같은 날짜가 두 번 — 믿을 수 없는 응답

    # S 의 값: 일봉이 있으면 일봉, 비었으면 시세(시세 날짜가 S 일 때만).
    y_s, y_src = (by_date.get(S) or [None])[0], 'bar'
    if y_s is None and q_date == S and _finite(yahoo_quote.get('price')) and yahoo_quote['price'] > 0:
        y_s, y_src = float(yahoo_quote['price']), 'quote'
    if y_s is None:
        return _missing('yahoo_no_value', S)
    if not _close_to(s_row['close'], y_s):
        return _missing('value_disagree', S)

    # P 가 두 원천 모두에서 S 의 바로 앞 세션인가.
    y_p = (by_date.get(P) or [None])[0]
    if y_p is None or not _close_to(p_row['close'], y_p) or any(P < d < S for d in by_date):
        return _missing('previous_disagree', S)

    return {'status': 'ok', 'date': S, 'close': s_row['close'], 'prev_close': p_row['close'],
            'basis': 'naver_close',
            'xcheck': {'yahoo_close': y_s, 'yahoo_source': y_src, 'yahoo_prev': y_p, 'prev_date': P}}


def pct_of(result):
    return round((result['close'] / result['prev_close'] - 1) * 100, 2)


def rows_and_missing(settle, pairs):
    """지역 하나의 (rows, missing). `pairs` = ((이름, 티커), ...). 판정이 없는 티커는 「못 받음」이다."""
    rows, missing = [], []
    for name, ticker in pairs:
        r = (settle or {}).get(ticker) or _missing('naver_fetch_failed')
        if r.get('status') == 'ok':
            rows.append({'name': name, 'ticker': ticker, 'close': round(float(r['close']), 2),
                         'pct': pct_of(r), 'date': r['date'], 'basis': r['basis'],
                         'xcheck': r.get('xcheck')})
        else:
            reason = r.get('reason') or 'naver_fetch_failed'
            missing.append({'name': name, 'ticker': ticker, 'date': r.get('date'), 'reason': reason,
                            'note_ko': NOTE_KO.get(reason, reason)})
    return rows, missing


# ── 네트워크 ──────────────────────────────────────────────────────────────

def _default_context():
    """인증서 묶음 — certifi 가 있으면 그것을 쓴다(로컬 파이썬은 시스템 묶음을 못 찾을 때가 있다)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get_json(url, context=None, attempts=2, timeout=REQUEST_TIMEOUT_S):
    context = context or _default_context()
    last = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode('utf-8', 'replace'))
        except Exception as e:               # 다음 시도로 — 끝까지 안 되면 None
            last = e
    print(f'  naver {url.rsplit("/", 2)[-2]}: {last}', file=sys.stderr)
    return None


def fetch_naver(ticker, context=None):
    """-> (rows|UNPARSEABLE|None, live|None)."""
    code = urllib.parse.quote(NAVER_CODES[ticker], safe='.')
    rows = parse_naver_rows(_get_json(f'{NAVER_INDEX}/{code}/price?page=1&pageSize=10', context))
    live = parse_naver_live(_get_json(f'{NAVER_INDEX}/{code}/basic', context))
    return rows, live


def yahoo_frame_to_bars(index_dates, closes):
    return [(str(d), (float(c) if c == c and c is not None else None))
            for d, c in zip(index_dates, closes)]


def fetch_yahoo(ticker):
    """-> (bars, quote|None). 빈 종가 행을 버리지 않고(keepna) 그대로 받는다."""
    import zoneinfo
    import yfinance as yf
    tk = yf.Ticker(ticker)
    h = tk.history(period='10d', interval='1d', keepna=True, auto_adjust=True,
                   timeout=REQUEST_TIMEOUT_S)
    if h is None or not len(h):
        return None, None
    bars = yahoo_frame_to_bars([i.date() for i in h.index], list(h['Close']))
    quote = None
    try:
        meta = tk.history_metadata or {}
        tz = zoneinfo.ZoneInfo(meta['exchangeTimezoneName'])
        when = _dt.datetime.fromtimestamp(float(meta['regularMarketTime']), tz)
        quote = {'price': meta.get('regularMarketPrice'), 'date': when.date().isoformat()}
    except Exception as e:
        print(f'  yahoo quote {ticker}: {e}', file=sys.stderr)
    return bars, quote


def _within(seconds, fn):
    """벽시계로 `seconds` 초 안에 끝난 결과만 돌려준다 — 넘기면 TimeoutError(일은 데몬 스레드에 버린다)."""
    box = {}

    def run():
        try:
            box['value'] = fn()
        except BaseException as e:
            box['error'] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f'not finished within {seconds}s')
    if 'error' in box:
        raise box['error']
    return box['value']


def collect(tickers, report_date, now=None, context=None, wall_s=None,
            naver=fetch_naver, yahoo=fetch_yahoo):
    """{티커: 판정}. 어떤 실패도 예외로 나가지 않는다 — 못 받은 지수는 이유가 붙은 「없음」이다."""
    import time
    tickers = list(tickers)

    def gather():
        raw = {}
        for t in tickers:
            item = {}
            try:
                item['naver'] = naver(t, context) if t in NAVER_CODES else (None, None)
            except Exception as e:
                print(f'  naver {t}: {e}', file=sys.stderr)
                item['naver'] = (None, None)
            try:
                item['yahoo'] = yahoo(t)
            except Exception as e:
                print(f'  yahoo {t}: {e}', file=sys.stderr)
                item['yahoo'] = (None, None)
            raw[t] = item
        return raw

    try:
        raw = _within(FETCH_WALL_S if wall_s is None else wall_s, gather)
    except Exception as e:
        print(f'  global close fetch abandoned: {e}', file=sys.stderr)
        return {t: _missing('fetch_timeout') for t in tickers}
    stamp = time.time() if now is None else now
    out = {}
    for t in tickers:
        (rows, live), (bars, quote) = raw[t]['naver'], raw[t]['yahoo']
        try:
            out[t] = settle_close(t, rows, live, bars, quote, report_date, stamp)
        except Exception as e:
            print(f'  settle {t}: {e}', file=sys.stderr)
            out[t] = _missing('naver_unparseable')
    return out


def describe(name, result):
    if result.get('status') == 'ok':
        x = result.get('xcheck') or {}
        return (f"  {name}: {result['date']} {result['close']:,.2f} ({pct_of(result):+.2f}%) "
                f"네이버 = 야후 {x.get('yahoo_source')} {x.get('yahoo_close')}")
    return f"  {name}: 없음 — {NOTE_KO.get(result.get('reason'), result.get('reason'))}" \
           + (f" ({result['date']})" if result.get('date') else '')
