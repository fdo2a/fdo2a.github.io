#!/usr/bin/env python3
"""US Morning Brief — canonical market data collector.

Runs in GitHub Actions (network-open environment) after the US close and
commits data/market_data.json, data/intraday.json, data/yield_curve.png so the
cloud routine (network-restricted) can consume them without fetching anything.

Schema is identical to the inline scripts in .claude/agents/brief-data-collector.md,
plus top-level report_date / complete / missing / source fields used by the
orchestrator's completeness gate.
"""
import argparse, datetime, json, os, ssl, sys, time, urllib.request, warnings

warnings.filterwarnings('ignore')


def _ssl_context():
    """Prefer certifi's CA bundle; some minimal Pythons (e.g. python.org macOS 3.13)
    ship no system roots and fail FRED's HTTPS verify without it."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()

INDICES = [('Nasdaq', '^IXIC'), ('S&P 500', '^GSPC'), ('Dow', '^DJI'), ('Russell 2000', '^RUT'),
           ('S&P 500 Growth', 'IVW'), ('S&P 500 Value', 'IVE')]
SECTORS = [('Technology', 'XLK'), ('Energy', 'XLE'), ('Communication Services', 'XLC'),
           ('Consumer Discretionary', 'XLY'), ('Utilities', 'XLU'), ('Consumer Staples', 'XLP'),
           ('Health Care', 'XLV'), ('Industrials', 'XLI'), ('Financials', 'XLF'), ('Materials', 'XLB'),
           ('Real Estate', 'XLRE')]
FX = [('DXY', 'DX-Y.NYB'), ('USD/KRW', 'KRW=X'), ('USD/JPY', 'JPY=X'), ('EUR/USD', 'EURUSD=X')]
CMDTY = [('WTI', 'CL=F'), ('Brent', 'BZ=F'), ('Natural Gas', 'NG=F'), ('Gold', 'GC=F')]
MEMORY = [('Micron', 'MU'), ('Western Digital', 'WDC'), ('Seagate', 'STX'), ('Nvidia', 'NVDA'),
          ('Samsung Elec', '005930.KS'), ('SK hynix', '000660.KS')]
AI_INFRA = [('Marvell', 'MRVL'), ('Coherent', 'COHR'), ('Lumentum', 'LITE'),
            ('GE Vernova', 'GEV'), ('Vertiv', 'VRT')]
GROUPS = [('indices', INDICES), ('sectors', SECTORS), ('fx', FX), ('commodities', CMDTY),
          ('memory', MEMORY), ('ai_infra', AI_INFRA)]
INTRADAY_KEY = [('Nasdaq', '^IXIC'), ('S&P 500', '^GSPC'), ('Russell 2000', '^RUT'),
                ('Nvidia', 'NVDA'), ('WTI', 'CL=F'), ('Gold', 'GC=F'), ('USD/JPY', 'JPY=X')]


def retry(fn, attempts=3, base_sleep=3):
    last = None
    for i in range(attempts):
        try:
            out = fn()
            if out is not None:
                return out
        except Exception as e:
            last = e
        time.sleep(base_sleep * (i + 1))
    if last:
        print(f'  retry exhausted: {last}', file=sys.stderr)
    return None


ANCHOR_TICKER = '^GSPC'


def collect_daily():
    """One batched download for every daily ticker; returns ({group: {name: row|None}}, anchor).

    모든 행이 **S&P 500 이 닫힌 날 이하**의 마지막 봉을 쓴다. 종목마다 마지막 봉을
    각자 집으면 24시간 도는 통화쌍이 다음 날짜 봉을 이미 열어 둔 채 표에 섞인다 —
    2026-09-02 발행본에서 DXY 만 09-02 이고 통화쌍 셋은 09-03 이었다.
    """
    import yfinance as yf
    from us.daily_row import anchor_date, row_from_closes
    tickers = [t for _, pairs in GROUPS for _, t in pairs]

    def dl():
        df = yf.download(tickers, period='7d', interval='1d', group_by='ticker',
                         auto_adjust=True, progress=False, threads=False)
        return df if df is not None and len(df) else None

    df = retry(dl)
    closes = {}
    for _, pairs in GROUPS:
        for _, t in pairs:
            try:
                s = df[t]['Close'].dropna()
                closes[t] = ([str(i.date()) for i in s.index], [float(v) for v in s.values])
            except Exception:
                closes[t] = ([], [])
    anchor = anchor_date({t: d for t, (d, _) in closes.items()}, ANCHOR_TICKER)
    if anchor is None:
        # 배치에서 앵커 종목이 빠지면 나머지가 전부 「마지막 봉」으로 떨어져 통화쌍이
        # 다음 날짜를 물고 들어온다. 행을 만들기 **전에** 앵커부터 따로 받아 온다
        # (codex 검토 2026-09-04 — fill_daily_gaps 는 앵커를 되돌려 주지 않는다).
        def anchor_only():
            h = yf.Ticker(ANCHOR_TICKER).history(period='7d')['Close'].dropna()
            return str(h.index[-1].date()) if len(h) else None

        anchor = retry(anchor_only, attempts=2)
        if anchor:
            print(f'  anchor recovered separately: {anchor}', file=sys.stderr)
    out = {}
    for group, pairs in GROUPS:
        out[group] = {}
        for name, t in pairs:
            d, v = closes.get(t, ([], []))
            out[group][name] = row_from_closes(d, v, as_of=anchor)
    return out, anchor


def fill_daily_gaps(daily, anchor=None):
    """Per-ticker fallback for anything the batch download missed.

    폴백도 앵커를 지킨다 — 여기서만 마지막 봉을 집으면 배치가 실패한 종목만 하루
    앞선 날짜를 달고 표에 들어간다.
    """
    import yfinance as yf
    from us.daily_row import row_from_closes
    for group, pairs in GROUPS:
        for name, t in pairs:
            if daily[group][name] is not None:
                continue

            def one():
                h = yf.Ticker(t).history(period='7d')['Close'].dropna()
                return row_from_closes([str(i.date()) for i in h.index],
                                       [float(v) for v in h.values], as_of=anchor)

            daily[group][name] = retry(one)
            time.sleep(1)
    return daily


TAPE_TICKERS = ('^GSPC', '^IXIC', '^RUT')


def collect_histories():
    """Close-price histories for the stance triggers and the price-context readings.

    3y rather than the 6mo the stance triggers alone needed: the two-year percentile
    and the 252-session weight regression both read further back, and one longer
    batched download is cheaper than a second request.

    Returns (closes, dates, as_of). `dates` carries each series' own session dates,
    which the price-context readings need: FX trades ~26 more sessions over three
    years than the equity indices (2026-08-28 measured), so anything that lines two
    series up by list position is comparing different days. as_of is the S&P 500's
    last bar date — the caller checks it against the report date, because judging
    today's triggers against a history that stops short would quietly decide the
    stance on stale prices.
    """
    import yfinance as yf
    from us.price_context import HISTORY_TICKERS as PC_TICKERS
    from us.stance_metrics import HISTORY_TICKERS as STANCE_TICKERS
    # 「오늘의 장」의 글로벌 지수·참여도 다리도 여기서 함께 받는다. GROUPS에 넣으면
    # completeness()가 코어로 취급해 도쿄·홍콩 휴장일에 발행이 멈춘다.
    from us.session import HISTORY_TICKERS as SESSION_TICKERS
    # 모의 포트폴리오가 담는 상품들. 같은 배치에 얹으므로 요청이 늘지 않는다.
    from us.portfolio import HISTORY_TICKERS as PORTFOLIO_TICKERS

    tickers = sorted(set(STANCE_TICKERS) | set(PC_TICKERS) | set(SESSION_TICKERS)
                     | set(PORTFOLIO_TICKERS) | {t for _, t in SECTORS})

    def dl():
        df = yf.download(tickers, period='3y', interval='1d', group_by='ticker',
                         auto_adjust=True, progress=False, threads=False)
        return df if df is not None and len(df) else None

    df = retry(dl)
    out, idx, as_of, ohlc = {}, {}, None, {}
    for t in tickers:
        try:
            closes = df[t]['Close'].dropna()
            if len(closes):
                out[t] = [float(x) for x in closes]
                idx[t] = [str(d.date()) for d in closes.index]
            else:
                out[t], idx[t] = None, None
            if t == '^GSPC' and len(closes):
                as_of = str(closes.index[-1].date())
            # 마감 위치 경계를 이력에서 잡기 위한 일간 OHLC. 같은 다운로드에서
            # 꺼내므로 요청이 늘지 않는다.
            if t in TAPE_TICKERS:
                bars = df[t][['High', 'Low', 'Close']].dropna()
                ohlc[t] = [{'high': float(r['High']), 'low': float(r['Low']),
                            'close': float(r['Close'])} for _, r in bars.iterrows()]
        except Exception:
            out[t], idx[t] = None, None
    # 이력도 기준일까지만 남긴다. 표(fx)만 앵커로 자르고 이력을 안 자르면 같은
    # 발행본에서 표는 09-02 인데 stance_metrics·price_context 는 09-03 봉으로
    # 계산된다 — 통화쌍은 주식 지수보다 세션이 더 열리므로 상시 조건이다
    # (codex 검토 2026-09-04).
    if as_of:
        from us.daily_row import clip_series
        for t in list(out):
            out[t], idx[t] = clip_series(out[t], idx[t], as_of)
    return out, idx, as_of, ohlc


def daily_headlines(repo_root):
    """posts.json 에서 (date, headline) 회수 — 그 주의 촉매는 일간이 이미 확정했다."""
    p = os.path.join(repo_root, 'posts.json')
    if not os.path.exists(p):
        return []
    try:
        posts = json.load(open(p, encoding='utf-8'))
    except Exception:
        return []
    return [{'date': x['date'], 'headline': x.get('headline', '')} for x in posts if x.get('date')]


PERF_HORIZONS = [('1D', 1), ('1W', 7), ('1M', 30), ('6M', 182), ('1Y', 365)]
PERF_LABELS = {'1D': '1일', '1W': '1주', '1M': '1개월', '6M': '6개월', '1Y': '1년'}
PERF_SHORT = {'Communication Services': 'Comm. Svcs', 'Consumer Discretionary': 'Consumer Disc.'}


def collect_sector_performance():
    """Multi-horizon sector returns from one 1y batched download.
    1D = previous trading-day close; others = closest close on/before calendar offset."""
    import yfinance as yf
    import pandas as pd
    tickers = [t for _, t in SECTORS]

    def dl():
        # 2y so the 1Y lookback always has a close on/before last_date - 365d
        df = yf.download(tickers, period='2y', interval='1d', group_by='ticker',
                         auto_adjust=True, progress=False, threads=False)
        return df if df is not None and len(df) else None

    df = retry(dl)
    out = {}
    as_of = None
    for name, t in SECTORS:
        try:
            closes = df[t]['Close'].dropna()
        except Exception:
            out[name] = None
            continue
        if len(closes) < 2:
            out[name] = None
            continue
        last = float(closes.iloc[-1])
        as_of = as_of or str(closes.index[-1].date())
        row = {}
        for key, days in PERF_HORIZONS:
            if key == '1D':
                base = float(closes.iloc[-2])
            else:
                prior = closes[closes.index <= closes.index[-1] - pd.Timedelta(days=days)]
                base = float(prior.iloc[-1]) if len(prior) else None
            row[key] = round((last / base - 1) * 100, 2) if base else None
        out[name] = row
    return out, as_of


def render_sector_perf_html(perf, as_of, path):
    """Self-contained Toss-styled horizontal-bar section the report writer inserts verbatim.
    All numbers are computed here — the writer must not edit them."""
    style = (
        '<style>\n'
        '.spf-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }\n'
        '.spf-block { background: #fff; border: 1px solid #F2F4F6; border-radius: 14px;'
        ' padding: 13px 16px; page-break-inside: avoid; }\n'
        '.spf-title { font-size: 13.5px; font-weight: 800; color: #0050D9;'
        ' letter-spacing: 0.03em; margin: 0 0 8px; }\n'
        '.spf-row { display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }\n'
        '.spf-name { flex: 0 0 116px; font-size: 12.5px; font-weight: 600; color: #4E5968;'
        ' text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n'
        '.spf-track { flex: 1 1 auto; height: 13px; }\n'
        '.spf-bar { height: 13px; border-radius: 4px; min-width: 2px; }\n'
        '.spf-bar.p { background: #00A85A; } .spf-bar.n { background: #FF4040; }\n'
        '.spf-val { flex: 0 0 58px; font-size: 12.5px; font-weight: 700; white-space: nowrap; }\n'
        '.spf-val.p { color: #00A85A; } .spf-val.n { color: #FF4040; } .spf-val.z { color: #8B95A1; }\n'
        '@media (max-width: 560px) {\n'
        '  .spf-grid { grid-template-columns: 1fr; }\n'
        '  .spf-name { flex-basis: 96px; font-size: 12px; }\n'
        '}\n'
        '</style>\n')
    blocks = []
    for key, _ in PERF_HORIZONS:
        vals = [(n, v[key]) for n, v in perf.items() if v and v.get(key) is not None]
        if not vals:
            continue
        vals.sort(key=lambda x: x[1], reverse=True)
        maxabs = max(abs(v) for _, v in vals) or 1
        rows = []
        for n, v in vals:
            w = max(round(abs(v) / maxabs * 100), 1)
            cls = 'p' if v > 0 else ('n' if v < 0 else 'z')
            bar = '' if v == 0 else f'<div class="spf-bar {cls}" style="width:{w}%"></div>'
            rows.append(f'<div class="spf-row"><span class="spf-name">{PERF_SHORT.get(n, n)}</span>'
                        f'<div class="spf-track">{bar}</div>'
                        f'<span class="spf-val {cls}">{v:+.2f}%</span></div>')
        blocks.append(f'<div class="spf-block"><div class="spf-title">{PERF_LABELS[key]} 수익률</div>'
                      + '\n'.join(rows) + '</div>')
    html = ('<section class="sec">\n<h2>섹터 기간별 수익률</h2>\n' + style
            + '<div class="spf-grid">\n' + '\n'.join(blocks) + '\n</div>\n'
            + f'<div style="font-size:12.5px; color:#8B95A1; font-weight:600; margin:6px 2px 0;">'
              f'※ SPDR 섹터 ETF 종가 기준(배당·분할 조정), {as_of} 마감 · 각 기간 시점 대비 등락률</div>\n'
            + '</section>\n')
    open(path, 'w').write(html)


_FRED = None


def fred_client():
    """이 실행의 FRED 클라이언트. `main()` 이 미리 세우고, 그 밖의 진입점(테스트·
    직접 import)에서는 여기서 처음 만들어진다. 전역이 아니라 «실행당 하나» 인 이유는
    한 번 열화한 전역은 인터프리터가 끝날 때까지 열화한 채로 남기 때문이다."""
    global _FRED
    if _FRED is None:
        from us.fred import FredClient
        _FRED = FredClient(ssl_ctx=_SSL)
    return _FRED


def set_fred_client(client):
    """실행·테스트가 클라이언트를 주입한다(None 이면 리셋)."""
    global _FRED
    _FRED = client
    return client


def fred_series(sid):
    """(date, value) pairs, oldest→newest, '.' rows dropped.

    2026-09-05 이래 전송은 `us.fred` 가 고른다 — 키가 있으면 공식 API, 없거나
    거부당하면 예전 graph CSV. **계약은 그대로다**(전체 이력·오름차순·결측 제거).
    """
    return fred_client().series(sid)


def fred_yields():
    """DGS constant-maturity yields. Published with a 1-business-day lag, so these trail
    the equity close date — they are the 2Y source and the fallback for every tenor."""
    out = {}
    for name, sid in [('2Y', 'DGS2'), ('5Y', 'DGS5'), ('10Y', 'DGS10'), ('30Y', 'DGS30')]:
        def one(sid=sid):
            vals = fred_series(sid)
            d2, d1 = vals[-2], vals[-1]
            wk = vals[-6] if len(vals) >= 6 else None
            return {'level': d1[1], 'date': d1[0], 'bp': (d1[1] - d2[1]) * 100,
                    'week_ago': wk[1] if wk else None, 'week_ago_date': wk[0] if wk else None,
                    'source': 'FRED'}
        out[name] = retry(one)
        time.sleep(1)
    return out


# 4-axis economic dashboard indicators available on FRED (Actual/Previous/ref-period,
# deterministic). transform: level | mom_pct | yoy_pct | mom_diff. units label is what the
# report prints. Series NOT on FRED (ISM, S&P Global PMI, ADP, CB Confidence, Philly Fed,
# NY Fed inflation exp) stay web-sourced — the agent only needs consensus/forecast anyway.
ECON = [
    ('Labor', 'JOLTS Job Openings', 'JTSJOL', 'level', 'K'),
    ('Labor', 'Initial Jobless Claims', 'ICSA', 'level', ''),
    ('Labor', 'Initial Claims 4-wk MA', 'IC4WSA', 'level', ''),
    ('Labor', 'Continuing Jobless Claims', 'CCSA', 'level', ''),
    ('Labor', 'Nonfarm Payrolls (chg)', 'PAYEMS', 'mom_diff', 'K'),
    ('Labor', 'Unemployment Rate', 'UNRATE', 'level', '%'),
    ('Labor', 'Avg Hourly Earnings MoM', 'CES0500000003', 'mom_pct', '%'),
    ('Activity', 'Industrial Production MoM', 'INDPRO', 'mom_pct', '%'),
    ('Activity', 'Durable Goods Orders MoM', 'DGORDER', 'mom_pct', '%'),
    ('Activity', 'New Home Sales', 'HSN1F', 'level', 'K'),
    ('Activity', 'Existing Home Sales', 'EXHOSLUSM495S', 'level', ''),
    ('Activity', 'Real GDP Growth QoQ (ann.)', 'A191RL1Q225SBEA', 'level', '%'),
    ('Consumption', 'Retail Sales MoM', 'RSAFS', 'mom_pct', '%'),
    ('Consumption', 'Michigan Consumer Sentiment', 'UMCSENT', 'level', ''),
    ('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%'),
    ('Inflation', 'CPI MoM', 'CPIAUCSL', 'mom_pct', '%'),
    ('Inflation', 'Core CPI YoY', 'CPILFESL', 'yoy_pct', '%'),
    ('Inflation', 'Core CPI MoM', 'CPILFESL', 'mom_pct', '%'),
    ('Inflation', 'PPI Final Demand MoM', 'PPIFIS', 'mom_pct', '%'),
    ('Inflation', 'PCE Price Index YoY', 'PCEPI', 'yoy_pct', '%'),
    ('Inflation', 'Core PCE YoY', 'PCEPILFE', 'yoy_pct', '%'),
    ('Inflation', 'Michigan 1-Yr Inflation Exp', 'MICH', 'level', '%'),
]


def _apply(vals, i, tf):
    """transform value at index i (must be negative index into vals)."""
    if tf == 'level':
        return vals[i][1]
    if tf == 'mom_pct':
        return (vals[i][1] / vals[i - 1][1] - 1) * 100
    if tf == 'mom_diff':
        return vals[i][1] - vals[i - 1][1]
    if tf == 'yoy_pct':
        return (vals[i][1] / vals[i - 12][1] - 1) * 100
    raise ValueError(tf)


def collect_econ():
    """FRED-sourced Actual/Previous/ref-period for the dashboard. Never fabricates —
    a series that fails to fetch is simply omitted (agent falls back to web for it).

    Returns (rows, series_by_id). The raw histories cost nothing extra — fred_series()
    already downloads the whole CSV — and the macro regime scores are computed from
    them, so throwing them away here would mean paying for the same data twice.
    """
    out = []
    seen = {}
    for axis, name, sid, tf, units in ECON:
        vals = seen.get(sid)
        if vals is None:
            vals = retry(lambda sid=sid: fred_series(sid), attempts=3, base_sleep=2)
            seen[sid] = vals
            time.sleep(0.6)
        if not vals:
            continue
        need = 13 if tf == 'yoy_pct' else 2
        if len(vals) < need:
            continue
        try:
            actual = _apply(vals, -1, tf)
            previous = _apply(vals, -2, tf)
        except Exception:
            continue
        out.append({
            'axis': axis, 'name': name, 'fred_id': sid, 'transform': tf, 'units': units,
            'actual': round(actual, 2), 'previous': round(previous, 2),
            'ref_period': vals[-1][0],  # observation month (reference period), not release date
        })
    return out, seen


def yahoo_spot_yields():
    """Same-day CBOE spot yield indices — the PRIMARY source for 5Y/10Y/30Y (2026-07-28
    사용자 지시). These settle on the same date as the equity close, unlike FRED's T-1 DGS
    series. Shape matches fred_yields() so either can fill a tenor slot.

    There is no 2Y index on Yahoo: ^UST2Y does not exist and 2YY=F (2-Year Yield futures)
    is both a day staler than ^TNX and ~20bp off DGS2 — verified 2026-07-28, do not use it
    as a spot proxy. 2Y therefore stays on FRED; see merge_yields()."""
    import yfinance as yf
    out = {}
    for name, t in [('5Y', '^FVX'), ('10Y', '^TNX'), ('30Y', '^TYX')]:
        def one(t=t):
            h = yf.Ticker(t).history(period='1mo')['Close'].dropna()
            if len(h) < 2:
                return None
            cur, prev = float(h.iloc[-1]), float(h.iloc[-2])
            wk = float(h.iloc[-6]) if len(h) >= 6 else None
            return {'level': round(cur, 3), 'date': str(h.index[-1].date()),
                    'bp': (cur - prev) * 100,
                    'week_ago': round(wk, 3) if wk is not None else None,
                    'week_ago_date': str(h.index[-6].date()) if len(h) >= 6 else None,
                    'ticker': t, 'source': 'Yahoo'}
        out[name] = retry(one, attempts=3)
        time.sleep(1)
    return out


NAVER_PRICES = 'https://m.stock.naver.com/front-api/marketIndex/prices'
NAVER_TENORS = {'2Y': 'US2YT=RR', '5Y': 'US5YT=RR', '10Y': 'US10YT=RR', '30Y': 'US30YT=RR'}


def naver_spot_yields(pages=2, page_size=60, expected_date=None):
    """전 만기 **동일자** 종가 커브 — 발행용 1순위 (2026-09-04).

    야후에 2년 스팟 지수가 없어서 2Y 만 FRED DGS2(T-1) 를 쓰던 우회를 걷어낸다.
    그 우회 탓에 2s10s 두 다리의 날짜가 갈렸고, 90영업일 실측으로 날짜 차이만으로
    중앙 3.4bp·최대 11.8bp 오차가 났다(40bp 스프레드에서 무시 못 할 크기).

    네이버는 SIFMA 국채 현물 마감(17:05 ET) 종가를 전 만기 한 날짜로 준다. 실측
    120/120 영업일 전 만기 정렬·결측 0, FRED CMT 대비 중앙 0.1~0.4bp.

    `pageSize` 는 10 미만을 거부한다(`too_small`).
    """
    from us.naver_yields import parse_prices, build_curve
    series = {}
    for tenor, code in NAVER_TENORS.items():
        rows = []
        for page in range(1, pages + 1):
            url = (f'{NAVER_PRICES}?category=bond'
                   f'&reutersCode={urllib.parse.quote(code, safe="")}'
                   f'&page={page}&pageSize={page_size}')

            def one(u=url):
                raw = urllib.request.urlopen(u, timeout=25, context=_SSL).read()
                return json.loads(raw.decode('utf-8', 'replace'))

            payload = retry(one, attempts=3, base_sleep=2)
            got = parse_prices(payload) if payload else []
            if not got:
                break
            rows += got
        series[tenor] = rows
        time.sleep(0.5)
    if any(not rows for rows in series.values()):
        return None, None
    from us.naver_yields import common_date
    latest = common_date(series)
    return build_curve(series, expected_date=expected_date), latest


def merge_yields(fred, yahoo, naver=None):
    """우선순위 네이버 -> 야후 -> FRED. 각 행은 자기 `source`/`date` 를 계속 단다.

    네이버가 통째로 돌아오면 전 만기가 한 날짜라 2s10s 의 두 다리가 갈리지 않는다.
    **네이버는 전부-아니면-전무로 쓴다** — 일부 만기만 네이버로 채우면 남은 만기가
    야후·FRED 날짜를 달고 들어와, 고치려던 어긋남이 그대로 재현된다.
    """
    out = {}
    # `bp` 까지 요구한다 — 비교 구간이 늘어나 전일比를 못 만든 커브를 실으면 표의
    # 「전일比」 칸이 통째로 빈다. 그런 날 폴백 사슬은 정상적인 전일 대비를 갖고 있다.
    use_naver = bool(naver) and all(
        (naver.get(t) or {}).get(f) is not None
        for t in ('2Y', '5Y', '10Y', '30Y') for f in ('level', 'bp'))
    for t in ('2Y', '5Y', '10Y', '30Y'):
        row = (naver or {}).get(t) if use_naver else None
        if not (row and row.get('level') is not None):
            row = (yahoo or {}).get(t)
        if not (row and row.get('level') is not None):
            row = (fred or {}).get(t)
        out[t] = dict(row) if row else None
    return out


def collect_intraday(target):
    import yfinance as yf
    out = {}
    for n, t in INTRADAY_KEY:
        def one(t=t):
            h = yf.Ticker(t).history(period='7d', interval='30m')
            d = h[[i.date() == target for i in h.index]]
            if len(d) < 3:
                return None
            o, c = float(d['Open'].iloc[0]), float(d['Close'].iloc[-1])
            return {'open': o, 'close': c,
                    'low': float(d['Low'].min()), 'low_t': d['Low'].idxmin().strftime('%H:%M'),
                    'high': float(d['High'].max()), 'high_t': d['High'].idxmax().strftime('%H:%M'),
                    'open_to_low_pct': (float(d['Low'].min()) / o - 1) * 100,
                    'open_to_high_pct': (float(d['High'].max()) / o - 1) * 100}
        out[n] = retry(one, attempts=2)
        time.sleep(1)
    return out


def collect_futures_bars():
    """야간 선물 봉. 야후 인덱스를 ET로 변환해 ISO 문자열로 넘긴다 — 창이 ET
    달력 경계를 넘으므로 순수 함수 쪽에서 naive 날짜로는 자를 수 없다."""
    import yfinance as yf
    from us.session import FUTURES
    out = {}
    for _, t in FUTURES:
        def one(t=t):
            h = yf.Ticker(t).history(period='5d', interval='30m')
            if h is None or not len(h):
                return None
            h.index = h.index.tz_convert('America/New_York')
            return [{'t': i.isoformat(), 'high': float(r['High']), 'low': float(r['Low'])}
                    for i, r in h.iterrows()]
        out[t] = retry(one, attempts=2) or []
        time.sleep(1)
    return out


def render_curve(yields, path):
    """Toss-style curve chart. Palette #0064FF/#D97706 is CVD-validated; dashes are the
    secondary encoding — do not change colors."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ['Noto Sans CJK KR', 'NanumGothic', 'Pretendard', 'Apple SD Gothic Neo']:
        if any(f.lower() in x.name.lower() for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams['axes.unicode_minus'] = False
    INK, INK2, MUTED, GRID = '#191F28', '#4E5968', '#8B95A1', '#F2F4F6'
    BLUE, AMBER = '#0064FF', '#D97706'
    labels = ['2Y', '5Y', '10Y', '30Y']
    today = [yields[t]['level'] for t in labels]
    week_ago = [yields[t]['week_ago'] for t in labels]
    t_date, w_date = yields['10Y']['date'], yields['10Y']['week_ago_date']
    # 2Y comes from FRED (T-1) while 5Y/10Y/30Y are same-day Yahoo spot, so a point on this
    # curve can be as of a different date than its neighbours. Star it rather than hide it.
    odd = [t for t in labels if yields[t].get('date') != t_date]
    x = range(4)
    fig, ax = plt.subplots(figsize=(7.4, 3.4), dpi=200)
    fig.patch.set_facecolor('white'); ax.set_facecolor('white')
    ax.plot(x, week_ago, '--', color=AMBER, linewidth=2, marker='o', markersize=7,
            markerfacecolor='white', markeredgecolor=AMBER, markeredgewidth=2, zorder=2)
    ax.plot(x, today, '-', color=BLUE, linewidth=2.4, marker='o', markersize=8,
            markerfacecolor=BLUE, markeredgecolor='white', markeredgewidth=2, zorder=3)
    for i, (t, w) in enumerate(zip(today, week_ago)):
        ax.annotate(f'{t:.2f}%', (i, t), textcoords='offset points', xytext=(0, 11),
                    ha='center', fontsize=10.5, fontweight='bold', color=INK)
        d = (t - w) * 100
        ax.annotate(f"{'+' if d > 0 else ''}{d:.0f}bp", (i, min(t, w)), textcoords='offset points',
                    xytext=(0, -20), ha='center', fontsize=9, color=MUTED)
    ax.annotate(f'오늘 ({t_date})', (3, today[3]), textcoords='offset points',
                xytext=(14, 4), fontsize=9.5, color=INK2, fontweight='bold')
    ax.annotate(f'1주 전 ({w_date})', (3, week_ago[3]), textcoords='offset points',
                xytext=(14, -12), fontsize=9.5, color=MUTED)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f'{t}*' if t in odd else t for t in labels], fontsize=11, color=INK2)
    if odd:
        note = ' · '.join(f"{t} {yields[t].get('source', '?')} {yields[t]['date']}" for t in odd)
        ax.text(0, -0.19, f'* {note} 기준 (그 외 Yahoo 스팟 {t_date})', transform=ax.transAxes,
                fontsize=8.5, color=MUTED)
    ax.tick_params(axis='y', labelsize=9.5, colors=MUTED, length=0)
    ax.tick_params(axis='x', length=0, pad=8)
    lo, hi = min(today + week_ago), max(today + week_ago)
    ax.set_ylim(lo - 0.22, hi + 0.22); ax.set_xlim(-0.35, 3.55)
    ax.yaxis.set_major_formatter(lambda v, _: f'{v:.1f}%')
    ax.grid(axis='y', color=GRID, linewidth=1); ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    plt.subplots_adjust(left=0.07, right=0.82, top=0.93, bottom=0.12)
    plt.savefig(path, facecolor='white', bbox_inches='tight')
    plt.close(fig)


def completeness(data, intraday, naver_stale=False):
    missing = []
    if naver_stale:
        # 국채 현물 마감 전에 뜬 회차. 이 판을 complete 로 커밋하면 마감 뒤 회차가
        # 멱등 가드에 막혀 그날 커브가 영영 전일치로 남는다.
        missing.append('yields/naver_close_not_posted')
    for group, pairs in GROUPS:
        for name, _ in pairs:
            if data[group].get(name) is None:
                missing.append(f'{group}/{name}')
    for t in ['2Y', '5Y', '10Y', '30Y']:
        y = data['yields'].get(t)
        if y is None or y.get('level') is None:
            missing.append(f'yields/{t}')
        elif y.get('week_ago') is None:
            missing.append(f'yields/{t}/week_ago')
    for n in ('Nasdaq', 'S&P 500'):
        if intraday.get(n) is None:
            missing.append(f'intraday/{n}')
    perf = data.get('sector_performance', {})
    for name, _ in SECTORS:
        row = perf.get(name)
        # 6M/1Y may legitimately be short for a young ETF; gate only through 1M.
        if row is None or any(row.get(k) is None for k in ('1D', '1W', '1M')):
            missing.append(f'sector_performance/{name}')
    return missing


def production_sids():
    """한 실행이 실제로 받는 FRED 시리즈 전부 — 수익률 4 + 대시보드 22 + 금리 분해."""
    sids = ['DGS2', 'DGS5', 'DGS10', 'DGS30'] + [row[2] for row in ECON]
    try:
        from us.yield_drivers import ROWS as YD_ROWS
        sids += [r[1] for r in YD_ROWS]
    except Exception as e:
        print(f'  (yield driver ids unavailable: {e})', file=sys.stderr)
    out = []
    for sid in sids:
        if sid not in out:
            out.append(sid)
    return out


def _diff_series(a, b):
    """두 이력의 차이. 마지막 30포인트가 아니라 **전체 맵**을 본다 — 매크로 모멘텀이
    60포인트를, YoY 변환이 12포인트를 더 거슬러 올라가 읽기 때문이다."""
    ma, mb = dict(a), dict(b)
    notes = []
    if len(ma) != len(a):
        notes.append(f'api has {len(a) - len(ma)} duplicate dates')
    if len(mb) != len(b):
        notes.append(f'csv has {len(b) - len(mb)} duplicate dates')
    if len(a) != len(b):
        notes.append(f'count {len(a)} vs {len(b)}')
    if a and b and a[0][0] != b[0][0]:
        notes.append(f'first {a[0][0]} vs {b[0][0]}')
    if a and b and a[-1][0] != b[-1][0]:
        notes.append(f'last {a[-1][0]} vs {b[-1][0]}')
    off = sorted(d for d in set(ma) | set(mb) if ma.get(d) != mb.get(d))
    return off, notes


def fred_check():
    """공식 API 와 graph CSV 가 **같은 숫자**를 주는지 전 생산 시리즈로 대조한다.

    키를 넣은 직후 한 번 돌린다. 아무 파일도 쓰지 않고, 불일치가 남으면 비영으로
    끝난다. 이 레포에서 가장 비싼 실패가 「데이터가 조용히 달라지는 것」이라 전송을
    바꾸는 패치에는 이 대조가 딸려야 한다.
    """
    from us.fred import FredClient
    if not os.environ.get('FRED_API_KEY'):
        print('FRED_API_KEY is not set — nothing to compare', file=sys.stderr)
        return 2
    sids = production_sids()
    print(f'comparing {len(sids)} series: official API vs graph CSV')
    bad = 0
    for sid in sids:
        # fallback=False 가 핵심이다 — 켜 두면 키가 틀렸을 때 API 클라이언트가 조용히
        # CSV 로 내려가 CSV 끼리 비교하고 「identical」을 인쇄한다.
        api = FredClient(ssl_ctx=_SSL, transport='api', fallback=False)
        raw = FredClient(key=None, ssl_ctx=_SSL, transport='csv')
        try:
            a, b = api.series(sid), raw.series(sid)
        except Exception as e:
            print(f'  {sid}: FETCH FAILED — {e}')
            bad += 1
            continue
        off, notes = _diff_series(a, b)
        # 마지막 한 점만 어긋나면 갱신 레이스일 수 있다 — 한 번만 다시 받아 본다.
        if off and set(off) <= {a[-1][0] if a else None, b[-1][0] if b else None}:
            a = FredClient(ssl_ctx=_SSL, transport='api', fallback=False).series(sid)
            b = FredClient(key=None, ssl_ctx=_SSL, transport='csv').series(sid)
            off, notes = _diff_series(a, b)
        if off or notes:
            bad += 1
            detail = ', '.join(notes + [f'{d}: {dict(a).get(d)} vs {dict(b).get(d)}'
                                        for d in off[:5]])
            print(f'  {sid}: MISMATCH — {detail}'
                  + (f' (+{len(off) - 5} more dates)' if len(off) > 5 else ''))
        else:
            print(f'  {sid}: {len(a)} obs {a[0][0]}..{a[-1][0]} identical' if a
                  else f'  {sid}: empty on both paths')
    print(f'{len(sids) - bad}/{len(sids)} series identical')
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='data')
    ap.add_argument('--force', action='store_true',
                    help='regenerate even if a complete dataset for the same report date exists')
    ap.add_argument('--fred-check', action='store_true',
                    help='공식 API 와 graph CSV 를 전 생산 시리즈에 대해 대조하고 끝낸다 '
                         '(아무 파일도 쓰지 않는다)')
    args = ap.parse_args()
    # 진단은 정상 경로에 얹지 않는다 — makedirs 앞에서 갈라져야 산출물을 안 건드린다.
    if args.fred_check:
        sys.exit(fred_check())

    set_fred_client(None)          # 재진입 실행이 지난 열화 상태를 물려받지 않게
    fredc = fred_client()
    print(f'FRED transport: {fredc.preflight()}'
          + (f' ({fredc.reason})' if fredc.reason else ''))
    if fredc.telemetry()['degraded']:
        print(f'::warning::FRED API key is configured but unusable ({fredc.reason}) — '
              f'falling back to the unofficial graph CSV', file=sys.stderr)

    os.makedirs(args.outdir, exist_ok=True)
    md_path = os.path.join(args.outdir, 'market_data.json')

    print('collecting daily closes (batched)...')
    daily, anchor = collect_daily()
    daily = fill_daily_gaps(daily, anchor)
    report_date = None
    spx = daily['indices'].get('S&P 500')
    if spx:
        report_date = spx['date']
    if report_date is None:
        print('FATAL: could not establish report date (S&P 500 fetch failed)', file=sys.stderr)
        sys.exit(1)
    print(f'report date: {report_date}')

    # Second cron slot is a retry: skip if a complete dataset for this date is already committed.
    if not args.force and os.path.exists(md_path):
        try:
            prev = json.load(open(md_path))
            if prev.get('report_date') == report_date and prev.get('complete'):
                print('complete dataset for this report date already exists — skipping')
                return
        except Exception:
            pass

    print('collecting Naver same-date curve (primary: 2Y/5Y/10Y/30Y)...')
    yields_naver, naver_latest = naver_spot_yields(expected_date=report_date)
    # 「아직 안 나왔다」와 「못 받았다」는 다르게 다뤄야 한다. 전자는 다음 회차가 메울
    # 수 있으므로 incomplete 로 남겨 멱등 가드가 재시도를 막지 않게 하고, 후자는
    # 야후·FRED 폴백으로 발행한다 — 네이버 장애로 발행이 멈추면 안 된다.
    naver_stale = bool(naver_latest) and yields_naver is None and naver_latest < report_date
    if naver_stale:
        print(f'  Naver curve is still {naver_latest} (< {report_date}) — 국채 마감 전 회차로 본다',
              file=sys.stderr)
    print('collecting Yahoo spot yields (fallback: 5Y/10Y/30Y)...')
    yields_yahoo = yahoo_spot_yields()
    print('collecting FRED yields (fallback + cross-check)...')
    yields_fred = fred_yields()
    yields = merge_yields(yields_fred, yields_yahoo, yields_naver)
    for t, row in yields.items():
        print(f'  {t}: ' + (f"{row['level']}% ({row.get('source')} {row['date']})" if row else 'MISSING'))
    print('collecting yield drivers (real / breakeven / spreads)...')
    try:
        from us.yield_drivers import ROWS as YD_ROWS, build as build_yield_drivers
        yd_series = {}
        for _, sid, _ in YD_ROWS:
            if sid in yd_series:
                continue
            got = retry(lambda sid=sid: fred_series(sid), attempts=2)
            if got:
                yd_series[sid] = got
            time.sleep(0.3)
        drivers = build_yield_drivers(yd_series)
        for tenor, d in drivers['decomposition'].items():
            print(f"  {tenor}: {d['nominal_chg_1d_bp']:+.1f}bp = 실질 {d['real_chg_1d_bp']:+.1f} "
                  f"+ 기대 {d['breakeven_chg_1d_bp']:+.1f} -> {d['driver_ko']}")
    except Exception as e:
        print(f'yield drivers failed: {e}', file=sys.stderr)
        drivers = {'rows': {}, 'decomposition': {}}

    print('collecting FRED economic indicators...')
    econ, econ_series = collect_econ()
    print(f'  econ indicators: {len(econ)}/{len(ECON)}')
    print('collecting sector multi-horizon performance...')
    sector_perf, perf_as_of = collect_sector_performance()
    print(f'  sector perf: {sum(1 for v in sector_perf.values() if v)}/{len(SECTORS)} (as of {perf_as_of})')
    print('collecting 30m intraday bars...')
    intraday = collect_intraday(datetime.date.fromisoformat(report_date))

    data = {
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'source': 'github-actions/collect_market_data.py',
        'report_date': report_date,
        'indices': daily['indices'],
        'sectors': daily['sectors'],
        'fx': daily['fx'],
        'commodities': daily['commodities'],
        'memory': daily['memory'],
        'ai_infra': daily['ai_infra'],
        'yields': yields,
        'yields_fred': yields_fred,
        'yields_note': 'yields = 발행용 기준값. 1순위는 네이버 국채 종가(SIFMA 국채 현물 '
                       '마감 17:05 ET)로 **전 만기가 동일 기준일**이다. 네이버가 비면 '
                       'Yahoo 스팟(^FVX/^TNX/^TYX) -> FRED 순으로 메우는데, 그때는 만기별 '
                       'date가 갈릴 수 있으므로 각 행의 source/date를 표·차트·캡션에 표기할 것. '
                       'yields_fred는 전 만기 FRED 동일자 대조용.',
        'yield_drivers': drivers,
        'sector_performance': sector_perf,
        'sector_performance_as_of': perf_as_of,
    }
    y = data['yields']
    # 발행값. 네이버로 채워진 날은 두 다리가 같은 날짜라 basis 가 「동일 기준일」로 나온다.
    if y.get('2Y') and y.get('10Y'):
        data['spread_2s10s_bp'] = (y['10Y']['level'] - y['2Y']['level']) * 100
        same = y['2Y']['date'] == y['10Y']['date']
        data['spread_2s10s_aligned'] = same
        data['spread_2s10s_basis'] = (
            f"2Y·10Y 모두 {y['10Y'].get('source')} {y['10Y']['date']} 동일 기준일" if same
            else f"2Y {y['2Y'].get('source')} {y['2Y']['date']} vs "
                 f"10Y {y['10Y'].get('source')} {y['10Y']['date']}")
    # Single-date cross-checks: both legs FRED (T-1), and both legs Yahoo same-day.
    if yields_fred.get('2Y') and yields_fred.get('10Y'):
        data['spread_2s10s_fred_bp'] = (yields_fred['10Y']['level'] - yields_fred['2Y']['level']) * 100
    if y.get('5Y') and y.get('30Y'):
        data['spread_5s30s_bp'] = (y['30Y']['level'] - y['5Y']['level']) * 100

    missing = completeness(data, intraday, naver_stale=naver_stale)
    data['complete'] = not missing
    data['missing'] = missing

    chart_path = os.path.join(args.outdir, 'yield_curve.png')
    if all(y.get(t) and y[t].get('week_ago') is not None for t in ['2Y', '5Y', '10Y', '30Y']):
        print('rendering yield curve chart...')
        render_curve(y, chart_path)
    else:
        print('week-ago yields incomplete — skipping chart', file=sys.stderr)
        if os.path.exists(chart_path):
            os.remove(chart_path)

    render_sector_perf_html(sector_perf, perf_as_of, os.path.join(args.outdir, 'sector_performance.html'))

    # Non-core, and shared: one batched download feeds both the stance triggers and the
    # price-context readings. A failure here must not cost us the dataset —
    # eval_stance_triggers.py degrades every affected trigger to UNKNOWN, which freezes
    # the grade rather than inventing a move.
    print('collecting close-price histories (batched)...')
    try:
        closes, hist_dates, hist_as_of, hist_ohlc = collect_histories()
        print(f'  histories: {sum(1 for v in closes.values() if v)}/{len(closes)} '
              f'(as of {hist_as_of})')
    except Exception as e:
        print(f'histories failed: {e}', file=sys.stderr)
        closes, hist_dates, hist_as_of, hist_ohlc = {}, {}, None, {}

    # 모의 포트폴리오가 오늘 담을 종가. **기준일에 정확히 있는 값만** 담는다 —
    # 마지막 값으로 대신하면 원장이 지난 종가로 굴려지고, 그 사실이 어디에도 남지
    # 않는다. 없는 종목은 missing 으로 넘겨 build_portfolio.py 가 그 날을 건너뛴다.
    print('pricing the paper portfolio...')
    try:
        from us.portfolio import HISTORY_TICKERS as PF_TICKERS
        PF_WINDOW = 15
        pf_closes, pf_missing, pf_recent = {}, [], {}
        for t in PF_TICKERS:
            series, dates_ = closes.get(t), hist_dates.get(t)
            if series and dates_ and report_date in dates_:
                i = dates_.index(report_date)
                pf_closes[t] = series[i]
                # 최근 창의 **오늘 기준** 종가들. auto_adjust 는 배당·분할 때 과거를
                # 소급 조정하므로, 어제 저장해 둔 값과 이 값이 다르면 기준이 바뀐
                # 것이다. build_portfolio.py 가 좌수를 다시 맞춘다. 직전 한 세션만
                # 넘기면 중간에 한 세션을 건너뛴 날 조정이 통째로 샌다.
                lo = max(0, i - PF_WINDOW)
                pf_recent[t] = {d: v for d, v in zip(dates_[lo:i], series[lo:i])}
            else:
                pf_missing.append(t)
        # 시장 달력 — 원장이 어느 세션을 통째로 빠뜨렸는지는 이것으로만 알 수 있다.
        # 수집이 하루 아예 돌지 않으면 «결측» 기록조차 남지 않기 때문이다.
        spx_dates = hist_dates.get('^GSPC') or []
        pf_sessions = spx_dates[-(PF_WINDOW + 1):]
        # 「왜 이 비중인가」 — 변동성·위험 몫·한 칸의 크기. 같은 이력에서 나오므로
        # 네트워크 호출이 늘지 않는다.
        from us.portfolio_risk import compute as compute_rationale
        pf_rationale = compute_rationale(closes, hist_dates)
        if pf_rationale:
            print(f"  구성 근거: 주식 위험 몫 {pf_rationale['equity_risk_share_pct']}%"
                  + (f" · 재보정 필요 {pf_rationale['recalibrate']}"
                     if pf_rationale['recalibrate'] else ''))
        json.dump({'generated': data['generated'], 'report_date': report_date,
                   'as_of': report_date if not pf_missing else None,
                   'closes': pf_closes, 'recent': pf_recent,
                   'sessions': pf_sessions, 'missing': pf_missing,
                   'rationale': pf_rationale},
                  open(os.path.join(args.outdir, 'portfolio_prices.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
        print(f'  portfolio prices: {len(pf_closes)}/{len(PF_TICKERS)}'
              + (f' missing {pf_missing}' if pf_missing else ''))
    except Exception as e:
        print(f'portfolio prices failed: {e}', file=sys.stderr)

    print('computing stance trigger metrics...')
    try:
        from us.stance_metrics import compute as compute_stance_metrics
        # No provable history end date means no provable freshness. Writing the file
        # anyway would replace yesterday's committed metrics — whose stale report_date
        # is exactly what makes the evaluator fall through to UNKNOWN — with a fresh
        # -looking file built on whatever partial prices survived.
        if hist_as_of is None:
            raise RuntimeError('history has no end date; leaving yesterday\'s metrics in place')
        metrics = compute_stance_metrics(closes, data)
        have = sum(1 for v in metrics.values() if v is not None)
        print(f'  stance metrics: {have}/{len(metrics)} (history as of {hist_as_of})')
        if hist_as_of != report_date:
            print(f'  WARN: history ends {hist_as_of}, report date is {report_date} — '
                  'triggers will fall through to UNKNOWN', file=sys.stderr)
        json.dump({'generated': data['generated'], 'report_date': report_date,
                   'as_of': hist_as_of, 'metrics': metrics},
                  open(os.path.join(args.outdir, 'stance_metrics.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f'stance metrics failed: {e}', file=sys.stderr)

    # Non-core, same contract as above: the macro regime's axis scores. `last_seen`
    # comes from yesterday's committed book — without it every indicator reads as newly
    # released and the regime would be free to move every single day.
    print('computing macro axis scores...')
    try:
        from us.macro_metrics import compute as compute_macro_metrics
        last_seen = None
        try:
            last_seen = json.load(open(os.path.join(args.outdir, 'macro.json'))).get('last_seen')
        except Exception:
            print('  no committed macro.json — treating every indicator as new', file=sys.stderr)
        mm = compute_macro_metrics(econ_series, econ, last_seen)
        print(f"  growth {mm['growth_score']} / inflation {mm['inflation_score']} · "
              f"신규 발표 {len(mm['new_releases'])}건")

        # Only the promoted releases pull their breakdown, so a quiet day costs nothing
        # and a CPI day costs six extra CSVs. The issuing agencies 403 their own press
        # releases to non-browser clients; FRED redistributes the same components.
        from us.macro_metrics import attach_components, component_specs
        specs = component_specs(mm['headline_releases'])
        comp_series = {}
        for spec in specs:
            sid = spec['fred_id']
            if sid in comp_series or sid in econ_series:
                continue
            try:
                comp_series[sid] = retry(lambda sid=sid: fred_series(sid), attempts=2)
            except Exception as e:
                print(f'  component {sid} failed: {e}', file=sys.stderr)
            time.sleep(0.4)
        comp_series.update(econ_series)
        attach_components(mm['headline_releases'], comp_series)
        for rel in mm['headline_releases']:
            print(f"    해부 {rel['key']}: {rel['label']} "
                  f"({len(rel.get('components') or [])}개 구성 항목)")
        json.dump({'generated': data['generated'], 'report_date': report_date, **mm},
                  open(os.path.join(args.outdir, 'macro_metrics.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f'macro metrics failed: {e}', file=sys.stderr)

    # Non-core, same contract as the blocks above: the statistical context for the
    # price side — is today's move large for this asset, where does the level sit in
    # its own history, are the standing cross-asset relationships still holding. A
    # failure here costs the readings, never the dataset.
    print('computing price context...')
    try:
        from us.price_context import compute as compute_price_context
        pc = compute_price_context(closes, data, sectors=SECTORS, dates=hist_dates)
        data['price_context'] = pc
        big = [n for n, m in pc['moves'].items() if m and m.get('band') in ('큼', '매우 큼')]
        flips = [c['label_ko'] for c in pc['correlations'] if c['flipped']]
        unknown = [c['label_ko'] for c in pc['correlations'] if c['flipped'] is None]
        if unknown:
            print(f"  관계 판정 불가: {', '.join(unknown)}", file=sys.stderr)
        coh = pc['cohesion']
        print(f"  이례적 움직임: {', '.join(big) if big else '없음'}")
        print(f"  관계 전환: {', '.join(flips) if flips else '없음'}")
        if coh:
            print(f"  시장 응집도: 상위 1개 요인 {coh['top1_pct']}% / 상위 3개 {coh['top3_pct']}%")
        sc = pc['sector_contribution']
        if sc and sc['rows']:
            top = sc['rows'][0]
            print(f"  지수 {sc['index_change']:+.2f}% 중 {top['name']} "
                  f"{top['contribution']:+.2f}%p (설명력 R²={sc['fit_r2']})")
    except Exception as e:
        print(f'price context failed: {e}', file=sys.stderr)

    # 같은 계약: 비-코어라 실패해도 데이터셋은 산다. 「오늘의 장」이 읽을 재료 —
    # 세계장이 어디서 끝났나, 밤사이 선물이 무엇을 했나, 평균적인 종목이 따라갔나,
    # 어디서 끝났나.
    print('computing session context...')
    try:
        from us.session import compute as compute_session
        sess = compute_session(closes, hist_dates, data, intraday,
                               collect_futures_bars(), report_date, ohlc=hist_ohlc)
        data['session'] = sess
        for key, ko in (('asia', '아시아'), ('europe', '유럽')):
            al = sess['global_close'][key]['alignment']
            if al:
                print(f"  {ko}: 미국과 {al['label']} (평균 {al['avg_pct']:+.2f}%)"
                      f"{' · 지역 내 혼조' if al['mixed'] else ''}")
            else:
                print(f"  {ko}: 판정 불가(지수 부족)")
        par = sess['participation']
        print(f"  참여도: {par['band']} ({par['gap_pp']:+.2f}%p)" if par
              else '  참여도: 판정 불가')
        cal = sess.get('tape_calibration')
        print(f"  마감 위치 경계: {cal['high']}/{cal['low']} ({cal['sessions']}세션 실측)"
              if cal else '  마감 위치 경계: 초안값 75/25 (표본 부족)')
        print(f"  출발: {sess['futures']['direction'] or '판정 불가'} / "
              f"야간 선물 {len(sess['futures']['contracts'])}종")
    except Exception as e:
        print(f'session context failed: {e}', file=sys.stderr)

    # Non-core: the §9 track record. Mostly it says "not enough decisions yet" — that
    # is the point. It accumulates now so a retrospective is possible later, and the
    # publication gate blocks any claim made before the sample is there.
    print('scoring the stance record...')
    try:
        from us.scorecard import build as build_scorecard
        prev = {}
        try:
            prev = json.load(open(os.path.join(args.outdir, 'stance.json')))
        except Exception:
            print('  no committed stance.json — nothing to score', file=sys.stderr)
        card = build_scorecard(prev.get('history') or [], closes, hist_dates)
        print(f"  채점 {card['scored']}건 / 필요 {card['min_sample']}건"
              + (f" · 적중률 {card['hit_rate']}%" if card['sufficient'] else ' · 표본 부족'))
        json.dump({'generated': data['generated'], 'report_date': report_date, **card},
                  open(os.path.join(args.outdir, 'scorecard.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f'scorecard failed: {e}', file=sys.stderr)

    # FRED 텔레메트리는 **마지막 FRED 호출 뒤**에 굳힌다 — 구성항목 수집이 위에서
    # 끝나므로 여기 값이 그 실행의 전부다. 죽은 키로 몇 주가 조용히 지나는 것을
    # 이 필드 하나로 잡는다.
    data['fred'] = fred_client().telemetry()
    ft = data['fred']
    print(f"FRED: transport={ft['transport']} requests={ft['requests']} "
          f"series={ft['series_ok']}"
          + (f" failed={','.join(ft['failed'])}" if ft['failed'] else '')
          + (f" csv_rescued={','.join(ft['csv_rescued'])}" if ft['csv_rescued'] else ''))

    json.dump(data, open(md_path, 'w'), indent=2, default=str, ensure_ascii=False)

    # 승계 책 이력 — 오늘 커밋돼 있는 stance/macro 를 로그에 밀어 넣는다.
    # 어제까지의 판단이 대상이다 (오늘 것은 아직 writer 가 만들지 않았다).
    try:
        from us.history import append_jsonl, macro_record, market_record, stance_record
        hdir = os.path.join(args.outdir, 'history')
        # 시세 원장이 먼저다 — 기간 집계가 이 행을 읽는다.
        if append_jsonl(os.path.join(hdir, 'market.jsonl'), market_record(data),
                        upsert=True):
            print(f"history: appended {report_date} to market.jsonl")
        for name, fn, out in (('stance.json', stance_record, 'stance.jsonl'),
                              ('macro.json', macro_record, 'macro.jsonl')):
            src = os.path.join(args.outdir, name)
            if not os.path.exists(src):
                continue
            book = json.load(open(src, encoding='utf-8'))
            if append_jsonl(os.path.join(hdir, out), fn(book)):
                print(f"history: appended {book.get('report_date')} to {out}")
    except Exception as e:
        print(f'history append failed: {e}', file=sys.stderr)

    # 기간 집계 — 기간 키로 나눠 쓰므로 주/달이 넘어가면 지난 파일이 곧 확정본이다.
    try:
        from us.history import read_jsonl
        from us.period import build as period_build, month_key, series_from, week_key
        # 시세를 다시 받지 않는다 — 발행본이 인쇄한 스냅샷 원장만 굴린다.
        dated, yh = series_from(read_jsonl(os.path.join(args.outdir, 'history',
                                                        'market.jsonl')))
        # posts.json 은 레포 루트에 있다 — outdir 는 'data' 하위 상대/절대/중첩 어느 값도
        # 될 수 있으므로 outdir 기준 역산 대신 이 스크립트 파일 위치(scripts/ 의 부모)로
        # 레포 루트를 고정한다. Actions 는 항상 레포 루트에서 이 스크립트를 실행한다.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        heads = daily_headlines(repo_root)
        for span, keyer, sub in (('weekly', week_key, 'weekly'), ('monthly', month_key, 'monthly')):
            k = keyer(report_date)
            agg = period_build(span, k, dated, yh, heads)
            d = os.path.join(args.outdir, sub)
            os.makedirs(d, exist_ok=True)
            json.dump(agg, open(os.path.join(d, f'{k}.json'), 'w'),
                      indent=2, default=str, ensure_ascii=False)
            print(f"{span} {k}: {agg['sessions']} sessions, "
                  f"complete={agg['complete']}")
    except Exception as e:
        print(f'period aggregation failed: {e}', file=sys.stderr)

    json.dump(intraday, open(os.path.join(args.outdir, 'intraday.json'), 'w'),
              indent=2, default=str, ensure_ascii=False)
    json.dump({'generated': data['generated'], 'source': 'FRED via collect_market_data.py',
               'note': 'Actual/Previous/ref_period are authoritative FRED values. '
                       'Forecast/consensus and release dates are NOT here — the agent adds '
                       'those from web only for recently-released indicators. '
                       'Indicators absent from this list (ISM, S&P Global PMI, ADP, CB '
                       'Confidence, Philly Fed, NY Fed inflation exp) are web-sourced.',
               'indicators': econ},
              open(os.path.join(args.outdir, 'econ_indicators.json'), 'w'),
              indent=2, default=str, ensure_ascii=False)

    if missing:
        print(f'INCOMPLETE ({len(missing)}): {", ".join(missing)}', file=sys.stderr)
    else:
        print('dataset COMPLETE')
    # Exit 0 even when partially incomplete: a partial canonical dataset is still far better
    # than none — the routine's own gate decides whether to publish. Only a total failure
    # (no report date) exits non-zero, above.


if __name__ == '__main__':
    main()
