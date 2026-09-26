"""주간 스냅샷의 원천 — 파서(순수)와 가져오기(네트워크)를 나눠 둔다.

US 주간 인사이트와 일본 주간이 같이 쓴다. **매일 수집하지 않는다** — 여기 소스는 전부
과거 이력을 통째로 준다(MOF JGB 커브 1974년~, CFTC 엔 1,058주, MOF 증권투자 2005년~).
그래서 주간 글을 쓰기 직전에 한 번 받아 스냅샷으로 커밋하고, 게이트는 그 스냅샷과 숫자를
대조한다.

실측 함정(2026-09-26):
- `ZQ=F`(연방기금금리 선물 연속월물)는 쓰지 않는다. 9/25 에 9월물 96.2525 에서 11월물
  값 95.965 로 **조용히** 롤했다. 월물을 명시한다 — `fed_funds_contracts()`.
- MOF `week.csv` 는 cp932 이고 각주에 cp932 전용 바이트가 섞여 있다(iconv SHIFT_JIS 는
  「Illegal byte sequence」로 죽는다). 연말 주는 끝 날짜에도 연도가 붙는다.
- 부호: MOF 순취득 = 취득 − 처분. **+ 는 순매수**다. 거주자의 해외채권 + 는 자금 유출이다.

설계: 프로젝트 루트 plan.md 「2026-09-26 US 주간 재구성 + 일본 주간 리포트」.
"""
import csv
import io
import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import date

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128 Safari/537.36')

MOF_WEEK = ('https://www.mof.go.jp/policy/international_policy/reference/'
            'itn_transactions_in_securities/week.csv')
JGB_MONTH = 'https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv'
JGB_ALL = ('https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/'
           'historical/jgbcme_all.csv')
CFTC_TFF = 'https://publicreporting.cftc.gov/resource/gpe5-46if.json'
CFTC_LEGACY = 'https://publicreporting.cftc.gov/resource/6dca-aqww.json'

# CFTC 계약 코드. 이름은 표에 찍는 한국어 라벨이다.
CFTC_CONTRACTS = {
    '097741': '엔 선물',
    '042601': '미 2년물 선물',
    '043602': '미 10년물 선물',
    '020601': '미 장기채 선물',
    '13874A': 'S&P500 E-mini',
}

_MONTH_CODES = 'FGHJKMNQUVXZ'


# ── 파서 (순수) ───────────────────────────────────────────────────────────────

def decode_cp932(raw):
    return raw.decode('cp932', errors='replace')


# 「2005．1．2〜 1．8」「2026．9．6〜9．12」「2025．12．28〜2026．1．3」. 물결표는 디코더마다
# 다르다 — Python cp932 는 ～(U+FF5E), iconv SHIFT_JIS 는 〜(U+301C). 둘 다 받는다.
_MOF_PERIOD = re.compile(
    r'^(\d{4})．(\d{1,2})．(\d{1,2})[〜～~]\s*(?:(\d{4})．)?(\d{1,2})．(\d{1,2})')

# 기간 뒤 22열: 거주자(대외) 11열 + 비거주자(대내) 11열. 각 11열의 순서는
# 주식(취득·처분·순) · 중장기채(취득·처분·순) · 소계 · 단기채(취득·처분·순) · 합계.
_MOF_FIELDS = {
    'res_foreign_equity_net': 2, 'res_foreign_ltdebt_net': 5,
    'nonres_jp_equity_net': 13, 'nonres_jp_ltdebt_net': 16,
}


def _int(cell):
    s = (cell or '').replace(',', '').strip()
    if not s or s in ('-', '―'):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_mof_week(text):
    """-> [{week_start, week_end, <필드>…}] 원문 순서(오래된→최신). 단위 억 엔."""
    out = []
    for rec in csv.reader(io.StringIO(text)):
        if not rec:
            continue
        m = _MOF_PERIOD.match(rec[0].strip())
        if not m:
            continue
        y1, m1, d1, y2, m2, d2 = m.groups()
        y1, m1, d1, m2, d2 = int(y1), int(m1), int(d1), int(m2), int(d2)
        if y2:
            y2 = int(y2)
        else:
            y2 = y1 + 1 if m2 < m1 else y1
        vals = rec[1:]
        row = {'week_start': date(y1, m1, d1).isoformat(),
               'week_end': date(y2, m2, d2).isoformat()}
        for key, idx in _MOF_FIELDS.items():
            row[key] = _int(vals[idx]) if idx < len(vals) else None
        out.append(row)
    return out


def parse_jgb_csv(text):
    """MOF 커브 CSV -> [{date, '1Y': …, '40Y': …}] 오래된→최신. 빈 칸은 키 자체가 없다."""
    rows, header = [], None
    for rec in csv.reader(io.StringIO(text)):
        if not rec:
            continue
        if rec[0].strip() == 'Date':
            header = [h.strip() for h in rec]
            continue
        if header is None:
            continue
        m = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})$', rec[0].strip())
        if not m:
            continue
        row = {'date': date(*map(int, m.groups())).isoformat()}
        for name, cell in zip(header[1:], rec[1:]):
            try:
                row[name] = float(cell)
            except ValueError:
                continue
        rows.append(row)
    return rows


def cftc_tff_row(raw):
    def n(key):
        v = raw.get(key)
        return int(float(v)) if v not in (None, '') else None
    return {'date': raw['report_date_as_yyyy_mm_dd'][:10],
            'lev_long': n('lev_money_positions_long'),
            'lev_short': n('lev_money_positions_short'),
            'am_long': n('asset_mgr_positions_long'),
            'am_short': n('asset_mgr_positions_short'),
            'oi': n('open_interest_all')}


def cftc_legacy_row(raw):
    def n(key):
        v = raw.get(key)
        return int(float(v)) if v not in (None, '') else None
    return {'date': raw['report_date_as_yyyy_mm_dd'][:10],
            'nc_long': n('noncomm_positions_long_all'),
            'nc_short': n('noncomm_positions_short_all')}


def fed_funds_contracts(today, months=6):
    """이번 달부터 `months` 개 월물 -> [('YYYY-MM', 'ZQ<코드><YY>.CBT')]."""
    out, y, m = [], today.year, today.month
    for _ in range(months):
        out.append((f'{y:04d}-{m:02d}', f'ZQ{_MONTH_CODES[m - 1]}{y % 100:02d}.CBT'))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def implied_rate(price):
    return round(100.0 - float(price), 4)


# ── 가져오기 (네트워크) ─────────────────────────────────────────────────────

def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def http_get(url, ctx=None, timeout=40):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, context=ctx or ssl_context(), timeout=timeout) as r:
        return r.read()


def fetch_mof_week(ctx=None):
    return parse_mof_week(decode_cp932(http_get(MOF_WEEK, ctx)))


def fetch_jgb(ctx=None, keep=420):
    """이력 파일 + 이번 달 파일. 이력 파일은 전월까지라 이번 달을 따로 붙인다."""
    hist = parse_jgb_csv(http_get(JGB_ALL, ctx, timeout=90).decode('utf-8', errors='replace'))
    month = parse_jgb_csv(http_get(JGB_MONTH, ctx).decode('utf-8', errors='replace'))
    by_date = {r['date']: r for r in hist}
    by_date.update({r['date']: r for r in month})
    return [by_date[d] for d in sorted(by_date)][-keep:]


def fetch_cftc(code, ctx=None, weeks=160):
    where = f"cftc_contract_market_code='{code}'"
    q = {'$where': where, '$order': 'report_date_as_yyyy_mm_dd DESC', '$limit': str(weeks)}
    tff = json.loads(http_get(CFTC_TFF + '?' + urllib.parse.urlencode(q), ctx))
    leg = json.loads(http_get(CFTC_LEGACY + '?' + urllib.parse.urlencode(q), ctx))
    legacy = {r['date']: r for r in map(cftc_legacy_row, leg)}
    rows = []
    for r in sorted(map(cftc_tff_row, tff), key=lambda x: x['date']):
        r.update({k: v for k, v in legacy.get(r['date'], {}).items() if k != 'date'})
        rows.append(r)
    return rows


def fetch_closes(ticker, period='2y'):
    """yfinance 종가 -> [[date, close]] 오래된→최신. NaN 행은 버린다."""
    import math
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    out = []
    for idx, v in hist['Close'].items():
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        out.append([idx.date().isoformat(), round(float(v), 4)])
    return out


def drop_copied_rows(rows):
    """[[date, close, volume]] -> 전일과 종가·거래량이 **둘 다** 같은 행을 버린다.

    야후의 연방기금금리 선물 이연 월물은 전일 행을 그대로 복사해 둘 때가 있다 —
    2026-09-24 ZQX26 이 9/23 과 종가 95.95·거래량 221,008 까지 같았다. 복사 행을 쓰면
    「1주 변화」가 실제보다 작게 나온다. 반환: (남은 [[date, close]], 버린 날짜들).
    """
    kept, dropped, prev = [], [], None
    for d, c, v in rows:
        if prev is not None and c == prev[0] and v == prev[1]:
            dropped.append(d)
            continue
        kept.append([d, c])
        prev = (c, v)
    return kept, dropped


def fetch_closes_volume(ticker, period='1mo'):
    import math
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    out = []
    for idx, c, v in zip(hist.index, hist['Close'], hist['Volume']):
        if c is None or (isinstance(c, float) and math.isnan(c)):
            continue
        out.append([idx.date().isoformat(), round(float(c), 4), int(v or 0)])
    return out


def fetch_fred(sid, keep=520, client=None):
    if client is None:
        from us.fred import FredClient
        client = FredClient(ssl_ctx=ssl_context())
    return [[d.isoformat() if hasattr(d, 'isoformat') else str(d), v]
            for d, v in client.series(sid)][-keep:]
