"""US 움직인 종목 — S&P 500 중 달러 거래대금(종가 × 거래량) 상위 60 을 모집단으로 삼는다.

KR 은 코스피 거래대금 상위 60 개별주(`collect_kr_data.py`)다. 선정·묶기 규칙은 두 시장이
같고 `scripts/common/movers.py` 에 있다 — 여기는 모집단과 업종(GICS Sub-Industry)만 만든다.
구성 종목표는 위키피디아 「List of S&P 500 companies」(`id="constituents"`)에서 받는다.
비-코어: 실패하면 `collect()` 가 `groups: []` 와 `error`, `collect.status: failed` 를 돌려주고 수집은 계속된다.
묶음 0개가 「없음 확인」(`collect.empty: confirmed_none`)인 것은 모집단을 거의 다 잰 날뿐이다(`common.movers.stamp`).

설계: docs/superpowers/specs/2026-09-24-movers-design.md
"""
import io
import sys
import urllib.request

from common import movers as M

WIKI = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
TOP_N = 60


def parse_constituents(html):
    """구성 종목표 → [{symbol, yf, name, sub_industry}]. yfinance 는 BRK.B 를 BRK-B 로 쓴다."""
    import pandas as pd
    table = pd.read_html(io.StringIO(html), attrs={'id': 'constituents'})[0]
    out = []
    for _, r in table.iterrows():
        sym = str(r['Symbol']).strip()
        out.append({'symbol': sym, 'yf': sym.replace('.', '-'), 'name': str(r['Security']).strip(),
                    'sub_industry': str(r['GICS Sub-Industry']).strip()})
    return out


def universe(series, names, report_date, top_n=TOP_N):
    """{yf 심볼: [(ISO 날짜, 종가, 거래량), …] 오름차순} → 그날 달러 거래대금 상위 top_n.

    report_date 봉을 찾아 쓴다(재실행하면 다음 날 장중 봉이 끝에 붙는다). 그 봉이나 전일 종가가 없으면
    뺀다 — 추정하지 않는다."""
    rows = []
    for sym, bars in series.items():
        dates = [b[0] for b in bars]
        if report_date not in dates:
            continue
        i = dates.index(report_date)
        if i == 0 or not bars[i - 1][1]:
            continue
        prev, (_, close, volume) = bars[i - 1][1], bars[i]
        rows.append({'name': names.get(sym, sym), 'yf': sym,
                     'change_pct': round((close / prev - 1) * 100, 2),
                     'close': round(close, 2), 'value': round(close * volume, 2)})
    rows.sort(key=lambda r: -r['value'])
    return rows[:top_n]


SOURCE = 'Wikipedia S&P 500 constituents + yfinance'


def assemble(report_date, cons, series, cap_of):
    """구성 종목·일봉·시총 조회 함수 → movers 책(`collect` 칸 포함). 네트워크 없음.

    `checked` = 구성 종목 중 그날 봉과 전일 종가가 다 있는 종목 수 — 모집단을 얼마나 쟀는가.
    시총 조회 실패는 0 으로 두고(기여 계산에서 빠진다) 세어 둔다."""
    names = {c['yf']: f"{c['name']} ({c['symbol']})" for c in cons}
    rows = universe(series, names, report_date)
    checked = len(universe(series, names, report_date, top_n=len(series) or 1)) if series else 0
    failed = []
    for r in rows:
        try:
            r['cap'] = float(cap_of(r['yf']) or 0)
        except Exception:
            r['cap'] = 0
            failed.append(r['yf'])
    industries = {names[c['yf']]: c['sub_industry'] for c in cons}
    book = M.build(report_date, 'S&P 500 중 달러 거래대금 상위 60', rows, industries)
    return M.stamp(book, source=SOURCE, checked=checked, expected=len(cons),
                   lookup_failed=failed, lookup_total=len(rows))


def failed(report_date, error):
    """예외 경로 — 묶음 0개가 「없음」으로 읽히지 않게 `error` 와 collect failed 를 함께 적는다."""
    return M.stamp({'report_date': report_date, 'groups': [], 'error': str(error)[:200]},
                   source=SOURCE, checked=0, expected=0)


def collect(report_date, ssl_context=None):  # pragma: no cover - 네트워크
    import yfinance as yf
    try:
        req = urllib.request.Request(WIKI, headers={'User-Agent': 'Mozilla/5.0 (market brief bot)'})
        html = urllib.request.urlopen(req, timeout=30, context=ssl_context).read().decode('utf-8')
        cons = parse_constituents(html)
        tickers = [c['yf'] for c in cons]
        df = yf.download(tickers, period='7d', progress=False, auto_adjust=False, threads=True)
        series = {}
        for c in cons:
            t = c['yf']
            if t not in getattr(df['Close'], 'columns', []):
                continue
            sub = df[['Close', 'Volume']].xs(t, axis=1, level=1).dropna()
            series[t] = [(i.date().isoformat(), float(r['Close']), float(r['Volume']))
                         for i, r in sub.iterrows()]
        return assemble(report_date, cons, series, lambda t: yf.Ticker(t).fast_info['marketCap'])
    except Exception as e:
        print(f'movers failed: {e}', file=sys.stderr)
        return failed(report_date, e)
