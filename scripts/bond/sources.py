"""글로벌 채권 데이터 수집 — 무료·공식 소스만.

루틴 환경이 금융 호스트를 403 차단하므로 수집은 전부 GitHub Actions 에서 돈다
(US 시장데이터를 2026-07-15 에 이관한 것과 같은 이유). 여기 있는 것은 그 러너에서
도는 코드다.

소스마다 **기준일이 다르다**는 사실이 이 모듈의 핵심 제약이다.

  Bundesbank(독일) · MOF(일본) · Yahoo(ETF/FX) · iShares(NAV)  -> T-0
  ECB(유로존 커브) · FRED BAML(크레딧 OAS)                     -> T-1 고정
  FRED DGS/DFII/BEI                                            -> 대개 T-0, 때로 T-1

그래서 모든 행이 `date` 와 `source` 를 달고 나간다. 이걸 뭉개면 「금리 -10bp 인데
HY +40bp」 같은 비교가 하루 어긋난 채 조용히 틀린다.
"""

import csv
import io
import json
import ssl
import urllib.request
from datetime import datetime

_MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}


def norm_date(raw):
    """소스마다 다른 날짜 표기를 ISO 로 —  MOF '2026-8-27', BOE '26 Aug 2026'.

    날짜가 소스별로 다르게 생겼다는 것이 이 파이프라인의 상수라서, 파싱을 각
    수집 함수에 흩지 않고 여기 한 곳에 모은다.
    """
    if not raw:
        return None
    t = str(raw).strip().replace('/', '-')
    parts = t.split('-')
    if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) == 4:
        y, m, d = parts
        return f'{int(y):04d}-{int(m):02d}-{int(d):02d}'
    for fmt in ('%d %b %Y', '%d %B %Y'):
        try:
            return datetime.strptime(t.replace('-', ' '), fmt).date().isoformat()
        except ValueError:
            continue
    return t

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:                                              # pragma: no cover
    _SSL = ssl.create_default_context()

_UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
TIMEOUT = 30


def _get(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL).read()


def _text(url, encoding='utf-8', **kw):
    return _get(url, **kw).decode(encoding, 'replace')


# --- FRED ------------------------------------------------------------------

FRED_US_CURVE = {'3M': 'DGS3MO', '6M': 'DGS6MO', '1Y': 'DGS1', '2Y': 'DGS2',
                 '3Y': 'DGS3', '5Y': 'DGS5', '7Y': 'DGS7', '10Y': 'DGS10',
                 '20Y': 'DGS20', '30Y': 'DGS30'}
FRED_REAL = {'5Y': 'DFII5', '10Y': 'DFII10', '30Y': 'DFII30'}
FRED_BEI = {'5Y': 'T5YIE', '10Y': 'T10YIE', '5y5y': 'T5YIFR'}
FRED_CREDIT = {
    'us_ig': 'BAMLC0A0CM', 'us_hy': 'BAMLH0A0HYM2',
    'us_ig_bbb': 'BAMLC0A4CBBB', 'us_hy_ccc': 'BAMLH0A3HYC',
    'em_sov': 'BAMLEMPBPUBSICRPIOAS', 'em_corp': 'BAMLEMCBPIOAS',
    'em_hy': 'BAMLEMHBHYCRPIOAS', 'euro_hy': 'BAMLHE00EHYIOAS',
}

# 한국어 이름은 발행본이 그대로 쓴다 — 내부 키가 지면에 새는 것을 게이트가 막는다.
CREDIT_KO = {
    'us_ig': '미국 IG', 'us_hy': '미국 HY', 'us_ig_bbb': '미국 IG BBB',
    'us_hy_ccc': '미국 HY CCC 이하', 'em_sov': 'EM 국공채', 'em_corp': 'EM 회사채',
    'em_hy': 'EM HY', 'euro_hy': '유럽 HY',
}
FRED_MISC = {'term_premium_10y': 'THREEFYTP10', 'sofr': 'SOFR',
             'tbill_3m': 'DTB3', 'fed_funds': 'DFF'}


def fred_series(sid):
    """(date, value) 쌍, 오래된 것 -> 최신. '.' 행은 버린다.

    fredgraph.csv 는 브라우저 UA 를 보내면 응답을 안 준다(2026-08-31 실측: Mozilla UA
    로 60초 타임아웃, 기본 python-urllib UA 로는 즉시 200). 그래서 여기만 UA 를 안 붙인다.
    """
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}'
    text = urllib.request.urlopen(url, timeout=TIMEOUT,
                                  context=_SSL).read().decode('utf-8', 'replace')
    rows = list(csv.reader(io.StringIO(text)))[1:]
    return [(r[0], float(r[1])) for r in rows if len(r) > 1 and r[1] not in ('.', '')]


# --- Bundesbank (독일) ------------------------------------------------------
# 일별 현물 커브. 한 만기당 한 시리즈이고 T-0 로 나온다.
BBK_DE = {
    '1Y': 'BBSIS.D.I.ZAR.ZI.EUR.S1311.B.A604.R01XX.R.A.A._Z._Z.A',
    '2Y': 'BBSIS.D.I.ZAR.ZI.EUR.S1311.B.A604.R02XX.R.A.A._Z._Z.A',
    '5Y': 'BBSIS.D.I.ZAR.ZI.EUR.S1311.B.A604.R05XX.R.A.A._Z._Z.A',
    '10Y': 'BBSIS.D.I.ZAR.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A',
    '30Y': 'BBSIS.D.I.ZAR.ZI.EUR.S1311.B.A604.R30XX.R.A.A._Z._Z.A',
}


def bundesbank_series(series_key):
    key = series_key.split('.', 1)[1] if series_key.startswith('BBSIS.') else series_key
    url = (f'https://api.statistiken.bundesbank.de/rest/download/BBSIS/{key}'
           f'?format=csv&lang=en')
    out = []
    for row in csv.reader(io.StringIO(_text(url))):
        if len(row) < 2 or not row[0][:4].isdigit():
            continue
        try:
            out.append((row[0], float(row[1])))
        except ValueError:
            continue
    return out


# --- ECB (유로존 AAA 커브) ---------------------------------------------------

def ecb_curve(tenor='10Y', last_n=520):
    key = f'YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_{tenor}'
    url = (f'https://data-api.ecb.europa.eu/service/data/YC/{key.split(".",1)[1]}'
           f'?lastNObservations={last_n}&format=csvdata')
    rows = list(csv.DictReader(io.StringIO(_text(url))))
    return [(r['TIME_PERIOD'], float(r['OBS_VALUE'])) for r in rows
            if r.get('OBS_VALUE') not in (None, '')]


# --- 일본 MOF (JGB 전만기) ---------------------------------------------------

def mof_jgb(last_n=520):
    """가장 최근 회계연도 CSV. 헤더에 만기, 각 행이 하루."""
    url = 'https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv'
    text = _text(url, encoding='shift_jis')
    rows = [r for r in csv.reader(io.StringIO(text)) if r and r[0].strip()]
    header = next((r for r in rows if r[0].strip().lower() == 'date'), None)
    if not header:
        return []
    tenors = [t.strip() for t in header[1:]]
    out = []
    for r in rows[rows.index(header) + 1:][-last_n:]:
        d = norm_date(r[0])
        vals = {}
        for t, v in zip(tenors, r[1:]):
            try:
                vals[t] = float(v)
            except (TypeError, ValueError):
                continue
        if vals:
            out.append((d, vals))
    return out


# --- 영국 BOE (best-effort) --------------------------------------------------
# IADB 는 봇 차단이 들쭉날쭉하다. 실패하면 길트 행을 통째로 빼고 간다 —
# 없는 값을 만들어 넣는 것보다 행이 비는 편이 낫다.
BOE_GILT = {'5Y': 'IUDSNPY', '10Y': 'IUDMNPY', '20Y': 'IUDLNPY'}


def boe_gilts(date_from='01/Jan/2024'):
    codes = ','.join(BOE_GILT.values())
    url = ('https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp'
           f'?csv.x=yes&Datefrom={date_from}&Dateto=now&SeriesCodes={codes}'
           '&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N')
    rows = list(csv.reader(io.StringIO(_text(url))))
    if len(rows) < 2:
        return []
    head = [c.strip() for c in rows[0]]
    inv = {v: k for k, v in BOE_GILT.items()}
    out = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        vals = {}
        for col, v in zip(head[1:], r[1:]):
            try:
                vals[inv.get(col, col)] = float(v)
            except (TypeError, ValueError):
                continue
        if vals:
            out.append((norm_date(r[0]), vals))
    return out


# --- iShares 상품 스크리너 (ETF 특성) -----------------------------------------
# 한 번의 호출로 524개 상품의 듀레이션·OAS·YTW·NAV·AUM 이 온다. 발행사를 하나로
# 묶는 이유는 방법론 때문이다 — 발행사가 다르면 듀레이션 산출 기준이 달라
# 나란히 놓는 순간 배우는 사람이 틀린 것을 배운다.
ISHARES_SCREENER = (
    'https://www.ishares.com/us/product-screener/product-screener-v3.1.jsn'
    '?dcrPath=/templatedata/config/product-screener-v3/data/en/us-ishares/'
    'ishares-product-screener-backend-config&siteEntryPassthrough=true')

UNIVERSE = ['AGG', 'GOVT', 'SHY', 'IEF', 'TLT', 'TIP', 'STIP',
            'LQD', 'IGIB', 'USIG', 'HYG', 'SHYG',
            'EMB', 'EMHY', 'IGOV', 'IAGG', 'FLOT']

_FIELDS = {
    'nav': 'navAmount', 'nav_as_of': 'navAmountAsOf', 'aum_usd': 'totalNetAssets',
    'duration': 'effectiveDuration', 'oas_bp': 'optionAdjustedSpread',
    'ytw_pct': 'yieldToWorst', 'ytm_pct': 'weightedAvgYieldToMaturity',
    'sec_yield_pct': 'thirtyDaySecYield',
}


def _raw(cell):
    if isinstance(cell, dict):
        return cell.get('r', cell.get('d'))
    return cell


def ishares_characteristics(tickers=UNIVERSE):
    import gzip
    req = urllib.request.Request(ISHARES_SCREENER,
                                 headers={**_UA, 'Accept-Encoding': 'gzip'})
    r = urllib.request.urlopen(req, timeout=60, context=_SSL)
    raw = r.read()
    if r.headers.get('Content-Encoding') == 'gzip':
        raw = gzip.decompress(raw)
    data = json.loads(raw.decode('utf-8', 'replace'))

    want = set(tickers)
    out = {}
    for p in data.values():
        t = p.get('localExchangeTicker')
        if t not in want:
            continue
        row = {'ticker': t, 'name': p.get('fundName')}
        for name, field in _FIELDS.items():
            row[name] = _raw(p.get(field))
        asof = row.get('nav_as_of')
        if isinstance(asof, (int, float)):
            s = str(int(asof))
            row['nav_as_of'] = f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) == 8 else None
        row['source'] = 'iShares'
        out[t] = row
    return out
