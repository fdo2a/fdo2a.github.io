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
# MLCC (2026-09-19 사용자 지시 「mlcc 산업분석을 메모리처럼 뒤에 붙이는걸로」).
# 종목은 thesis 파이프라인의 mlcc 그룹과 **같은 여덟 개**다(CCML ETF 보유 기준,
# `docs/superpowers/specs/2026-09-17-mlcc-thesis-group-design.md`). 삼성전자는 거기서
# memory 그룹이라 빠져 있고 여기서도 그대로 둔다 — 한 종목이 두 자리에서 다르게 불리면
# 독자가 같은 회사를 둘로 읽는다.
#
# **여덟 개가 전부 해외장이다.** 미국장 마감 시점에는 전부 전일 종가이고, 그중 일본·한국·
# 대만·중국이 서로 다른 날짜일 수 있다. 억지로 같은 날로 맞추지 않는다 — 메모리 표가
# 삼성전자·SK하이닉스를 캡션으로 처리하는 것과 같다.
MLCC = [('Murata', '6981.T'), ('Samsung E-M', '009150.KS'), ('Taiyo Yuden', '6976.T'),
        ('Yageo', '2327.TW'), ('Walsin', '2492.TW'), ('Holy Stone', '3026.TW'),
        ('Sanhuan', '300408.SZ'), ('Fenghua', '000636.SZ')]
GROUPS = [('indices', INDICES), ('sectors', SECTORS), ('fx', FX), ('commodities', CMDTY),
          ('memory', MEMORY), ('ai_infra', AI_INFRA), ('mlcc', MLCC)]
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


def _bars30(sym, period='10d'):
    import yfinance as yf
    h = yf.Ticker(sym).history(period=period, interval='30m')
    if h is None or not len(h):
        return None
    return [(i.isoformat(), r['Close']) for i, r in h.iterrows()]


def futures_contracts():
    """원자재 선물의 그 시점 월물 티커(CLX26.NYM 등). 못 받으면 연속 티커 그대로.

    `info` 는 Ticker 객체에 캐시되므로 티커마다 새 객체를 쓴다.
    """
    import yfinance as yf
    out = {}
    for name, t in CMDTY:
        try:
            out[name] = (yf.Ticker(t).info or {}).get('underlyingSymbol') or t
        except Exception:
            out[name] = t
    return out


def collect_cut_rows(anchor, contracts=None):
    """환율·원자재 행 = 그날 주식 마감 시각(평소 16:00 ET) 30분봉 종가 vs 직전 주식 세션의 같은 값.

    세션 달력과 마감 시각은 S&P 500 30분봉에서 잡는다(`us/close_cut.session_ends`) — 단축장도
    따라가고, 어느 종목의 직전 세션 봉이 빠졌으면 그 행은 None 이 된다. 일봉으로 폴백하지
    않는다. 실패한 행은 `missing` 이 되고 발행이 멈춘다 — 시간외 거래가를 결제가 대비로
    싣던 기준 혼합이 고치려는 바로 그 결함이다.
    """
    import yfinance as yf
    from us.close_cut import bar_ends, cut_row, session_ends
    contracts = contracts or {}

    def spx_daily():
        h = yf.Ticker(ANCHOR_TICKER).history(period='15d')['Close'].dropna()
        return {str(i.date()): float(v) for i, v in h.items()} or None

    # 세션 달력 = S&P 500 일봉(30분봉과 따로 받은 근거). 30분봉은 그 세션이 마감까지 다 있는지만
    # 검증한다 — 잘리거나 빠진 날은 세션에서 빠지고 그 날을 쓰는 행은 None 이 된다.
    daily = retry(spx_daily, attempts=3) or {}
    spx = retry(lambda: _bars30(ANCHOR_TICKER), attempts=3)
    sessions = session_ends(spx or [], daily)
    calendar = sorted(daily)
    out = {}
    for group, pairs in (('fx', FX), ('commodities', CMDTY)):
        out[group] = {}
        for name, t in pairs:
            sym = contracts.get(name) or t

            def one(sym=sym):
                b = _bars30(sym)
                return cut_row(bar_ends(b), sessions, anchor, calendar=calendar,
                               contract=sym if sym != t else None) if b else None

            row = retry(one, attempts=2)
            if row is None and sym != t:
                # 월물 티커를 못 받으면 연속 티커로 — 롤 주간이 아니면 같은 월물이다.
                row = retry(lambda: one(t), attempts=2)
            out[group][name] = row
            time.sleep(1)
    return out


def apply_cut_to_histories(closes, dates, cut):
    """이력의 오늘·전일 값을 표 값으로(`close_cut.override_history`). 이력에 있는 티커만."""
    from us.close_cut import override_history
    for group, pairs in (('fx', FX), ('commodities', CMDTY)):
        for name, t in pairs:
            row = (cut.get(group) or {}).get(name)
            if row and closes.get(t) and dates.get(t):
                closes[t], dates[t] = override_history(closes[t], dates[t], row)
    return closes, dates


TAPE_TICKERS = ('^GSPC', '^IXIC', '^RUT')


def base_history_tickers():
    """The history download set before the FF3 trial — the board's inputs come from it."""
    from us.price_context import HISTORY_TICKERS as PC_TICKERS
    from us.scorecard import HISTORY_TICKERS as SCORECARD_TICKERS
    # 「오늘의 장」의 글로벌 지수·참여도 다리도 여기서 함께 받는다. GROUPS에 넣으면
    # completeness()가 코어로 취급해 도쿄·홍콩 휴장일에 발행이 멈춘다.
    from us.session import HISTORY_TICKERS as SESSION_TICKERS
    # 트렌드 유닛 점검판의 참조 ETF 도 같은 다운로드에 얹는다(티커별 요청은 늘어난다).
    from fund.universe import tickers as fund_tickers
    return (set(SCORECARD_TICKERS) | set(PC_TICKERS) | set(SESSION_TICKERS)
            | {t for _, t in SECTORS} | set(fund_tickers()))


def history_tickers():
    """Download set = pre-trial set ∪ the factor legs. The legs only the factor model
    reads (`fund.factor_legs.FACTOR_ONLY`) are filtered out again before the board sees
    them (`fund.pipeline.board_inputs`). If the leg list cannot be imported the set is the
    pre-trial one — a factor-module failure never reaches the price download."""
    base = base_history_tickers()
    try:
        from fund.factor_legs import FACTOR_TICKERS
    except Exception as e:
        print(f'  factor legs unavailable, pre-trial download set: {e}', file=sys.stderr)
        return sorted(base)
    return sorted(base | set(FACTOR_TICKERS))


def collect_histories():
    """Close-price histories for the scorecard and the price-context readings.

    3y rather than the 6mo the scorecard alone needs: the two-year percentile
    and the 252-session weight regression both read further back, and one longer
    batched download is cheaper than a second request.

    Returns (closes, dates, as_of). `dates` carries each series' own session dates,
    which the price-context readings need: FX trades ~26 more sessions over three
    years than the equity indices (2026-08-28 measured), so anything that lines two
    series up by list position is comparing different days. as_of is the S&P 500's
    last bar date — the caller checks it against the report date, because judging
    today's judgments against a history that stops short would quietly score them
    on stale prices.
    """
    import yfinance as yf
    tickers = history_tickers()

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
    # 발행본에서 표는 09-02 인데 price_context 는 09-03 봉으로
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
        # 종목마다 마지막 봉 날짜를 남긴다. 2026-10-12 재수집에서 XLC·XLRE 만 10-09 에
        # 멈췄는데 as_of 는 첫 종목 날짜라 「1일」이 10-09 하루 수익률인 채 통과했다.
        last_date = str(closes.index[-1].date())
        as_of = max(as_of or last_date, last_date)
        row = {'date': last_date}
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
# report prints. An optional sixth element: `role` ('anatomy' = on the page and dissected,
# never scored; default scored) and `scale` (FRED value x scale = the printed value).
# Not here, so a table line only until stage B (2026-11-08): ISM, S&P Global PMI, CB
# Confidence, NY Fed inflation expectations. ADP and the Philadelphia Fed are on FRED;
# ADP stays out of stage A (its release text is not ours to read, so no components).
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
    # 2026-11-08 (A단계) — Census 4 join the Activity axis. The trade balance is printed in
    # $ billions (FRED: millions) — history, table, trend and the release check all see the
    # scaled value. Its +1 polarity reads nominal trade-balance momentum: a smaller deficit.
    ('Activity', 'Housing Starts', 'HOUST', 'level', 'K'),
    ('Activity', 'Trade Balance', 'BOPGSTB', 'level', '$B', {'scale': 1e-3}),
    ('Activity', 'Construction Spending MoM', 'TTLCONS', 'mom_pct', '%'),
    ('Activity', 'Factory Orders MoM', 'AMTMNO', 'mom_pct', '%'),
    # Dissected, not scored: a regional survey must not move the national regime.
    ('Activity', 'Philly Fed Manufacturing', 'GACDFSA066MSFRBPHI', 'level', '',
     {'role': 'anatomy'}),
]


def _econ_pair(vals, tf):
    """(Actual, Previous | None) — 최신 관측월의 변환값과 그 직전 변환값. 날짜로 맞춘
    `transform_pairs` 를 쓴다(2025-10 CPI 결측 탓에 행 위치 계산이 13개월 YoY 를 냈다).

    * 최신 관측월을 변환할 수 없으면 None — 지어내지 않고 행을 뺀다(수집 상태에 no_value).
    * 최신값은 계산되는데 **바로 앞 달**의 변환값이 없으면 (Actual, None) — 행은 만들고 직전 칸은 비운다. 더 오래된 달을
      「직전」으로 찍지 않고, 추정치로 채우지도 않는다(2026-11-18, 1a 구현 검토 3회차 G5: 2026-11 CPI 전년 대비는 2025-11 이
      있어 계산되지만 2026-10 전년 대비가 없어 행이 통째로 빠졌다). 표의 Previous·직전 대비는 「—」, 축 점수는 이 칸이
      아니라 변환된 이력(`macro_metrics.transform_series`)으로 낸다."""
    from us.macro_metrics import _month, transform_pairs
    pairs = transform_pairs(vals, tf)
    if not pairs or pairs[-1][0] != vals[-1][0]:
        return None
    if len(pairs) < 2 or (tf != 'level' and _month(pairs[-1][0]) - _month(pairs[-2][0]) != 1):
        # 직전 칸이 빈 행을 새로 만드는 것은 1a 를 켠 뒤다(2026-11-20) — 그 전에는 1a 전처럼 행을 뺀다: 지표 목록에 행이
        # 늘면 표·작성 입력이 달라지고, 그 행의 「— (사유)」 표기를 검사하는 규칙도 켠 뒤에만 돈다. 수집 상태에는
        # 꺼져 있어도 no_value 로 남는다.
        from verification.inputs import enforcing
        return (pairs[-1][1], None) if enforcing() else None
    return pairs[-1][1], pairs[-2][1]


def _lacking(vals, tf):
    """최신 관측월을 변환하는 데 필요한 **비교 관측 달** 가운데 원천에 없는 것 → `['YYYY-MM', …]`(3회차 G1).
    전년 대비는 12개월 전, 전월 대비·차분은 한 달 전. 그 달이 원천에 있는데도 변환이 안 됐으면(값 0 등) 빈 목록 —
    「그 달이 발표되지 않았다」와 다른 원인이다."""
    from us.macro_metrics import _month
    have = {_month(d) for d, _ in vals or []}
    if not have:
        return []
    last = _month(vals[-1][0])
    need = {'yoy_pct': [last - 12], 'mom_pct': [last - 1], 'mom_diff': [last - 1]}.get(tf, [])
    return [f'{m // 12:04d}-{m % 12 + 1:02d}' for m in need if m not in have]


def fred_blanks(sid):
    """원천 응답에 행은 있는데 값이 빈 날짜들 | None(모른다) — `us.fred.FredClient.blank_dates`."""
    try:
        got = fred_client().blank_dates.get(sid)
    except Exception:  # noqa: BLE001 — 모르면 모른다(추정하지 않는다)
        return None
    return list(got) if isinstance(got, list) else None


def fred_unclear(sid):
    """원천 응답에서 값 필드가 없거나 형식을 모르는 행의 날짜들 | None(모른다) — `FredClient.unclear_dates`.
    이런 달은 「미발표」의 근거가 없다(4회차 H1)."""
    try:
        got = fred_client().unclear_dates.get(sid)
    except Exception:  # noqa: BLE001
        return None
    return list(got) if isinstance(got, list) else None


def _month_state(vals, blanks, m, unclear=()):
    """원천에 값이 없는 달 `m`(연·월 일련번호)의 상태 — 행이 있고 값이 빈칸이면 not_published, 행 자체가 없으면
    not_collected, 빈칸 정보가 없으면 unknown(`us.macro_metrics.MISSING_STATES`)."""
    from us.macro_metrics import _month
    if blanks is None or unclear is None:
        return 'unknown'
    if any(_month(d) == m for d in unclear):
        return 'unknown'                  # 그 달 행의 값 칸이 없거나 형식을 모른다 — 빈칸이라는 근거가 없다
    return 'not_published' if any(_month(d) == m for d in blanks) else 'not_collected'


def _ym(m):
    return f'{m // 12:04d}-{m % 12 + 1:02d}'


def _lacking_why(vals, tf, blanks, unclear=()):
    """`_lacking` 의 달마다 상태 → `{'YYYY-MM': 상태}`."""
    from us.macro_metrics import _month
    by = {_ym(_month(f'{k}-01')): _month(f'{k}-01') for k in _lacking(vals, tf)}
    return {k: _month_state(vals, blanks, m, unclear) for k, m in by.items()}


def _previous_lacking(vals, tf, blanks, unclear=()):
    """직전 변환값을 만드는 데 필요한 달 가운데 원천에 없는 것 → `{'YYYY-MM': 상태}`. 최신 달이 변환되지 않는 경우나
    level 은 빈 사전(이 함수의 몫이 아니다)."""
    from us.macro_metrics import _month, transform_pairs
    if tf == 'level' or not vals:
        return {}
    pairs = transform_pairs(vals, tf)
    if not pairs or pairs[-1][0] != vals[-1][0]:
        return {}
    have = {_month(d) for d, _ in vals}
    last = _month(vals[-1][0])
    need = {'yoy_pct': [last - 1, last - 13], 'mom_pct': [last - 1, last - 2], 'mom_diff': [last - 1, last - 2]}[tf]
    return {_ym(m): _month_state(vals, blanks, m, unclear) for m in need if m not in have}


def _previous_why(vals, tf, blanks, unclear=()):
    """직전 변환값을 만들지 못한 까닭 — 그것을 만드는 데 필요한 달 가운데 원천에 없는 것들의 상태(여럿이면 보수적으로).
    필요한 달이 다 있는데도 못 만들었으면(값 0 등) unknown."""
    from us.macro_metrics import _month, worst_state
    if tf == 'level' or not vals:
        return 'not_collected' if blanks is not None and unclear is not None else 'unknown'   # 직전 관측이 원천에 없다
    have = {_month(d) for d, _ in vals}
    last = _month(vals[-1][0])
    need = {'yoy_pct': [last - 1, last - 13], 'mom_pct': [last - 1, last - 2], 'mom_diff': [last - 1, last - 2]}[tf]
    absent = [m for m in need if m not in have]
    if not absent:
        return 'unknown'
    return worst_state({_month_state(vals, blanks, m, unclear) for m in absent})


def collect_econ(reasons=None, refs=None):
    """FRED-sourced Actual/Previous/ref-period for the dashboard. Never fabricates —
    a series that fails to fetch is simply omitted (agent falls back to web for it).

    Returns (rows, series_by_id). The raw histories cost nothing extra — fred_series()
    already downloads the whole CSV — and the macro regime scores are computed from
    them, so throwing them away here would mean paying for the same data twice.
    """
    out = []
    seen = {}
    reasons = {} if reasons is None else reasons     # name -> fetch_failed | transform_error | no_value
    refs = {} if refs is None else refs              # name -> no_value 인 지표의 식별자·기준월(아래)
    for axis, name, sid, tf, units, *rest in ECON:
        opts = rest[0] if rest else {}
        vals = seen.get(sid)
        if vals is None:
            vals = retry(lambda sid=sid: fred_series(sid), attempts=3, base_sleep=2)
            if vals and opts.get('scale'):
                vals = [(d, v * opts['scale']) for d, v in vals]
            seen[sid] = vals
            time.sleep(0.6)
        if not vals:
            reasons[name] = 'fetch_failed'
            continue
        try:
            pair = _econ_pair(vals, tf)
        except Exception:
            reasons[name] = 'transform_error'
            continue
        if pair is None:
            # 받았지만 최신 달을 변환할 수 없다(결측 달 — 2025-10 CPI). 수집 실패가 아니다.
            reasons[name] = 'no_value'
            # 어느 지표의 어느 달을 만들지 못했는가 — 승인 예외는 식별자(FRED id·변환)와 기준월이 모두 같을 때만 걸린다
            # `lacking` = 그 달을 변환하는 데 필요한 비교 달 가운데 원천에 없는 것(3회차 G1 — 식별자·기준월이 같아도
            # 「2025-10 미발표」가 아닌 다른 원인이면 승인된 미발표가 아니다)
            # `lacking_why` = 그 달이 왜 없나(미발표·미수집·모름) — 승인 예외는 미발표일 때만(2026-11-18)
            blanks = fred_blanks(sid)
            refs[name] = {'axis': axis, 'fred_id': sid, 'transform': tf, 'ref_period': str(vals[-1][0])[:7],
                          'lacking': _lacking(vals, tf),
                          'lacking_why': _lacking_why(vals, tf, blanks, fred_unclear(sid))}
            if not refs[name]['lacking']:
                # 1a 를 켜기 전에만 생기는 경우(2026-11-20): 최신 달은 변환되는데 **직전 변환값**을 만들 달이 없어 1a 전처럼
                # 행을 뺐다. 그 까닭을 「최신 달의 비교 달」로 찾으면 비어 「상태 확인 불가」로 읽힌다 — 직전 값을 만드는
                # 데 없는 달과 그 상태를 적는다(산출 범위 문장 `coverage_ko` 가 이 값으로 쓰인다).
                prev_lack = _previous_lacking(vals, tf, blanks, fred_unclear(sid))
                if prev_lack:
                    refs[name]['lacking'] = sorted(prev_lack)
                    refs[name]['lacking_why'] = prev_lack
            continue
        actual, previous = pair
        row = {
            'axis': axis, 'name': name, 'fred_id': sid, 'transform': tf, 'units': units,
            'actual': round(actual, 2), 'previous': None if previous is None else round(previous, 2),
            'ref_period': vals[-1][0],  # observation month (reference period), not release date
        }
        if previous is None:
            # 직전 칸이 왜 비었나 — 「미발표」로 뭉뚱그리지 않는다(2026-11-18). 표의 「—」 옆에 이 사유가 실린다
            row['previous_why'] = _previous_why(vals, tf, fred_blanks(sid), fred_unclear(sid))
        if opts.get('role'):
            row['role'] = opts['role']
        out.append(row)
    return out, seen



def _release_date(client, sid, report_date, cache):
    """-> the latest release date (≤ report_date) of the FRED release `sid` belongs to."""
    if sid in cache:
        return cache[sid]
    out = None
    try:
        if client.transport == 'api':
            rid, _ = client.series_release(sid)
            out = client.last_release_date(rid, report_date)
    except Exception as e:
        print(f'  release date for {sid} failed: {e}', file=sys.stderr)
    cache[sid] = out
    return out


def _anatomy_round(mm, econ, econ_series, last_seen, book_state, book_date, report_date,
                   compute):
    """Introduced rows that released after the book was written, then FRED's side of
    every promoted release's components (us.anatomy.produce)."""
    from us import anatomy
    client = fred_client()
    if not client.transport:
        client.preflight()
    sids = {e['name']: e['fred_id'] for e in econ}
    cache = {}
    if mm.get('introduced'):
        fresh, unknown = set(), set()
        for n in mm['introduced']:
            since = (mm.get('introduced_since') or {}).get(n) or book_date
            day = _release_date(client, sids.get(n), report_date, cache)
            if day is None or not since:
                unknown.add(n)          # judged again tomorrow — never seeded blind
            elif day > since:
                fresh.add(n)
        if fresh:
            print(f"  도입일 신규 발표: {', '.join(sorted(fresh))}")
        if unknown:
            print(f"  도입일 발표일 미확인(내일 다시 본다): {', '.join(sorted(unknown))}",
                  file=sys.stderr)
        if fresh or unknown:
            mm = compute(econ_series, econ, last_seen, book_state=book_state,
                         introduced_new=fresh, introduced_unknown=unknown,
                         book_date=book_date)
    for rel in mm['headline_releases']:
        primary = next((i for i in rel.get('indicators') or []
                        if i.get('name') == rel.get('primary')), {}) or {}
        sid = primary.get('fred_id') or sids.get(rel.get('primary'))
        day = _release_date(client, sid, report_date, cache) if sid else None
        head = None
        if day and primary.get('ref_period'):
            try:
                ref = str(primary['ref_period'])[:10]
                head = client.vintage(sid, ref, ref, day)
            except Exception as e:
                print(f'  headline vintage {sid} failed: {e}', file=sys.stderr)
                head = []
        anatomy.produce(rel, lambda fid, a, b, day=day: client.vintage(fid, a, b, day),
                        day, head if day else None)
    return mm

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


def naver_spot_yields(pages=2, page_size=60, expected_date=None, timeout=25, attempts=3,
                      budget_s=None):
    """전 만기 **동일자** 종가 커브 — 발행용 1순위 (2026-09-04).

    야후에 2년 스팟 지수가 없어서 2Y 만 FRED DGS2(T-1) 를 쓰던 우회를 걷어낸다.
    그 우회 탓에 2s10s 두 다리의 날짜가 갈렸고, 90영업일 실측으로 날짜 차이만으로
    중앙 3.4bp·최대 11.8bp 오차가 났다(40bp 스프레드에서 무시 못 할 크기).

    네이버는 SIFMA 국채 현물 마감(17:05 ET) 종가를 전 만기 한 날짜로 준다. 실측
    120/120 영업일 전 만기 정렬·결측 0, FRED CMT 대비 중앙 0.1~0.4bp.

    `pageSize` 는 10 미만을 거부한다(`too_small`).

    `timeout`·`attempts`·`budget_s` 는 수익률만 고치는 재실행의 탐침용이다 — 요청당 시간과 재시도를
    줄이고, 전체가 `budget_s` 초를 넘기면 그 자리에서 (None, None) 으로 끝낸다(루틴이 실행 하나를
    540초만 기다린다). 시한은 요청 사이와 응답을 읽는 조각 사이에서 보므로 탐침은 늦어도
    `budget_s + timeout` 초에 끝난다(정상적인 응답일 때 — 벽시계 상한은 부르는 쪽 `_within` 이
    따로 건다). 기본값은 전체 수집이 쓰던 그대로다.
    """
    from us.naver_yields import parse_prices, build_curve
    deadline = None if budget_s is None else time.monotonic() + budget_s
    series = {}
    for tenor, code in NAVER_TENORS.items():
        rows = []
        for page in range(1, pages + 1):
            if deadline is not None and time.monotonic() >= deadline:
                print(f'  Naver probe over its {budget_s}s budget — giving up', file=sys.stderr)
                return None, None
            url = (f'{NAVER_PRICES}?category=bond'
                   f'&reutersCode={urllib.parse.quote(code, safe="")}'
                   f'&page={page}&pageSize={page_size}')

            def one(u=url):
                resp = urllib.request.urlopen(u, timeout=timeout, context=_SSL)
                if deadline is None:
                    raw = resp.read()
                else:
                    # 조금씩 흘려 보내는 응답이 소켓 timeout 을 계속 갱신하며 예산을 넘기지 못하게
                    # 조각마다 시한을 본다 — 탐침 전체는 budget_s + timeout 초 안에 끝난다.
                    parts = []
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f'over the {budget_s}s budget while reading')
                        chunk = resp.read1(65536) if hasattr(resp, 'read1') else resp.read(65536)
                        if not chunk:
                            break
                        parts.append(chunk)
                    raw = b''.join(parts)
                return json.loads(raw.decode('utf-8', 'replace'))

            if attempts <= 1:
                try:                       # 재시도도 그 사이 잠도 없다 — 탐침은 한 번만 본다
                    payload = one()
                except Exception as e:
                    print(f'  Naver {tenor} p{page}: {e}', file=sys.stderr)
                    payload = None
            else:
                payload = retry(one, attempts=attempts, base_sleep=2)
            got = parse_prices(payload) if payload else []
            if not got:
                break
            rows += got
        series[tenor] = rows
        if deadline is None:
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


def collect_intraday(target, symbols=None, cut_minutes=16 * 60):
    """주요 종목의 30분봉 장중 궤적. 뉴욕 날짜·그날 주식 마감 시각까지만 — 표와 같은 구간이다.

    `symbols` 로 표와 같은 월물 티커를 넘긴다(WTI → CLX26.NYM). 연속 티커를 따로 받으면
    롤 주간에 장중 「끝」과 표의 종가가 다른 월물을 말한다(codex 구현 검토 P2). 통화쌍은
    런던 시각으로 오고 선물은 마감 뒤에도 거래해, 전에는 「끝났다」가 표와 다른 가격이었다.
    """
    import yfinance as yf
    symbols = symbols or {}
    out = {}
    for n, t in INTRADAY_KEY:
        sym = symbols.get(n) or t

        def one(sym=sym):
            h = yf.Ticker(sym).history(period='7d', interval='30m')
            h.index = h.index.tz_convert('America/New_York')
            d = h[[i.date() == target and i.hour * 60 + i.minute + 30 <= cut_minutes
                   for i in h.index]]
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


# Every word drawn inside the curve chart. The Japanese edition passes its own table
# (`scripts/ja/chart.py`); the default is the Korean chart, byte for byte.
CURVE_LABELS_KO = {
    'today': '오늘 ({date})',
    'week_ago': '1주 전 ({date})',
    'note': '* {note} 기준 (그 외 Yahoo 스팟 {date})',
}
CURVE_FONTS_KO = ('Noto Sans CJK KR', 'NanumGothic', 'Pretendard', 'Apple SD Gothic Neo')


def render_curve(yields, path, labels=None, fonts=None):
    """Toss-style curve chart. Palette #0064FF/#D97706 is CVD-validated; dashes are the
    secondary encoding — do not change colors.

    `labels` replaces the words in the chart (keys of CURVE_LABELS_KO), `fonts` the font
    preference list; both default to the Korean chart."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    words = CURVE_LABELS_KO if labels is None else labels
    for f in (CURVE_FONTS_KO if fonts is None else fonts):
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
    ax.annotate(words['today'].format(date=t_date), (3, today[3]), textcoords='offset points',
                xytext=(14, 4), fontsize=9.5, color=INK2, fontweight='bold')
    ax.annotate(words['week_ago'].format(date=w_date), (3, week_ago[3]), textcoords='offset points',
                xytext=(14, -12), fontsize=9.5, color=MUTED)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f'{t}*' if t in odd else t for t in labels], fontsize=11, color=INK2)
    if odd:
        note = ' · '.join(f"{t} {yields[t].get('source', '?')} {yields[t]['date']}" for t in odd)
        ax.text(0, -0.19, words['note'].format(note=note, date=t_date), transform=ax.transAxes,
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


from us.close_cut import CUT_GROUPS, row_problem as cut_row_problem  # noqa: E402

# 미국 상장 계열은 그날 세션 종가여야 한다. 2026-09-25 판이 섹터·스타일·메모리를 09-24
# 날짜로 싣고도 complete:true 였다 — 수집 시각에 야후에 금요일 종가가 아직 없었고, 이 검사는
# 행이 있는지만 봤다. 그 판이 멱등 가드에 걸리면 낡은 값이 그날의 정본으로 굳는다(codex 검토
# 2026-09-27 #14). 한국·일본 상장 종목은 날짜가 정상적으로 다르다. 환율·원자재는 2026-10-14
# 부터 그날 16:00 ET 컷 행이어야 한다(`us/close_cut.py`) — 기준과 날짜를 따로 검사한다.
DATE_CHECKED_GROUPS = ('indices', 'sectors', 'memory', 'ai_infra')


def _us_listed(ticker):
    return '.' not in ticker and '=' not in ticker


def completeness(data, intraday, naver_stale=False, report_date=None):
    missing = []
    report_date = report_date or data.get('report_date')
    if naver_stale:
        # 국채 현물 마감 전에 뜬 회차. 이 판을 complete 로 커밋하면 마감 뒤 회차가
        # 멱등 가드에 막혀 그날 커브가 영영 전일치로 남는다.
        missing.append('yields/naver_close_not_posted')
    for group, pairs in GROUPS:
        for name, ticker in pairs:
            row = data[group].get(name)
            if row is None:
                missing.append(f'{group}/{name}')
            elif group in CUT_GROUPS:
                problem = cut_row_problem(row, report_date)
                if problem:
                    missing.append(f'{group}/{name}/{problem}')
            elif (report_date and group in DATE_CHECKED_GROUPS and _us_listed(ticker)
                  and row.get('date') and row['date'] != report_date):
                missing.append(f'{group}/{name}/stale:{row["date"]}')
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
        elif report_date and row.get('date') and row['date'] != report_date:
            missing.append(f'sector_performance/{name}/stale:{row["date"]}')
    return missing


def production_sids():
    """한 실행이 실제로 받는 FRED 시리즈 전부 — 수익률 4 + DGS1MO(펀드 요인 시운전) + 대시보드 22 + 금리 분해."""
    # DGS1MO: the FF3 trial's risk-free leg (fund_rf_input). ECON and the yield drivers
    # do not carry it, so it is named here or --fred-check would never compare it.
    sids = ['DGS2', 'DGS5', 'DGS10', 'DGS30', 'DGS1MO'] + [row[2] for row in ECON]
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


def fund_rf_input():
    """The FF3 trial's risk-free leg (DGS1MO). Fetched after the board, inside the trial's
    try; a failure leaves an empty list (the trial then reports the RF gap)."""
    from fund.factor_legs import RF_SERIES
    try:
        return retry(lambda: fred_series(RF_SERIES), attempts=2) or []
    except Exception as e:
        print(f'  risk-free {RF_SERIES} failed: {e}', file=sys.stderr)
        return []


def fund_board_step(closes, hist_dates, data, report_date, outdir):
    """트렌드 유닛 점검판 — ed17327 의 main() 인라인 블록 그대로(codex impl review 1 #1·#2).

    FRED 유동성 준비, 휴장일 로딩, 조립이 **한 try 안**에 있어 어디서 터져도
    `publish.failed` 를 쓴다. 조립·렌더·발행만 `fund.pipeline.run` 으로 옮겼다(그 함수도
    같은 실패 처리를 한다). 요인 모듈은 여기서 import 하지 않는다. 반환: 보드가 읽은
    휴장일(시운전이 다시 쓴다) — 블록이 실패했으면 None."""
    print('building fund board...')
    from fund import publish as fund_publish
    try:
        from fund.liquidity import SERIES as LIQ_SERIES
        liq_series = {}
        for sid in LIQ_SERIES:
            try:
                got = retry(lambda sid=sid: fred_series(sid), attempts=2)
                if got:
                    liq_series[sid] = got
            except Exception as e:
                print(f'  liquidity {sid} failed: {e}', file=sys.stderr)
            time.sleep(0.3)
        from fund.calendar import load as load_holidays
        holidays = load_holidays(os.path.join(outdir, 'market_holidays.json'))
        from fund import pipeline as fund_pipeline
        fund_pipeline.run(closes, hist_dates, data, liq_series, report_date, data['generated'],
                          outdir, holidays, handle_errors=False)
        return holidays
    except Exception as e:
        print(f'fund board failed: {e}', file=sys.stderr)
        fund_publish.write(outdir, 'fund_board.json', 'fund_board.html',
                           fund_publish.failed(report_date, data['generated'], e, universe=True), None)
        return None


def fund_desk(closes, hist_dates, data, report_date, outdir):
    """Board, then the FF3 trial in its own try. Never raises past the board's own
    `fund_publish` import (as before the trial), so collection continues."""
    holidays = fund_board_step(closes, hist_dates, data, report_date, outdir)
    # FF3 시운전 — 보드가 다 쓰인 **뒤**, 자기 try 안에서 data/fund_factors.json 만 쓴다.
    # 여기서 무엇이 터져도 fund_board.* 는 이미 끝난 파일이다.
    try:
        from fund import factors_pipeline
        if holidays is None:
            from fund.calendar import load as load_holidays
            holidays = load_holidays(os.path.join(outdir, 'market_holidays.json'))
        factors_pipeline.run_trial(closes, hist_dates, fund_rf_input(), report_date,
                                   data['generated'], outdir, holidays)
    except Exception as e:
        print(f'fund factors trial failed: {e}', file=sys.stderr)


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
    from us.fred import FredClient, annotation
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
            print(f'  {sid}: FETCH FAILED — {annotation(e)}')
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


def ff_probe(url=None, max_time=60.0, connect_timeout=10.0):
    """French 요인 zip 을 이 러너에서 받을 수 있는가 — 받기만 하고 버린다.

    `curl -fsS --connect-timeout 10 --max-time 60 -A Mozilla/5.0` 과 같은 뜻: 2xx 가
    아니거나(4xx·5xx 실패) 전체 시간이 max_time 을 넘으면 1. **전체 마감은 벽시계로
    강제한다**(codex impl review 1 #5): 받기는 작업 스레드에서 돌고, 본체는 마감까지만
    기다린 뒤 응답을 닫고 1 로 끝낸다 — 한 바이트씩 흘려 보내는 서버(소켓 대기 시간
    제한에 걸리지 않는다)나 늦게 돌아오는 read() 도 max_time 을 넘기지 못한다. 작업
    스레드 안에서도 read1 청크마다 마감을 본다. 「code bytes seconds」를 한 줄 찍는다.
    아무 파일도 쓰지 않는다."""
    import socket
    import threading
    import urllib.error
    from fund.factors_check import FRENCH_URL
    url = url or FRENCH_URL
    t0 = time.monotonic()
    deadline = t0 + max_time
    st = {'code': 0, 'size': 0, 'err': None, 'resp': None}

    def fetch():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=min(connect_timeout, max_time),
                                        context=_SSL if url.startswith('https') else None) as resp:
                st['resp'] = resp
                st['code'] = resp.status
                read = getattr(resp, 'read1', None) or resp.read
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'max-time {max_time}s exceeded')
                    chunk = read(65536)
                    if not chunk:
                        break
                    st['size'] += len(chunk)
        except urllib.error.HTTPError as e:
            st['code'] = e.code
            e.close()
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError) as e:
            st['err'] = e

    worker = threading.Thread(target=fetch, daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        # 응답을 닫지 않는다: close() 가 작업 스레드의 읽기 잠금을 기다려 마감을 넘기고,
        # 읽기와 경합해 traceback 을 낸다(codex impl review 2 #1). 작업 스레드는 daemon 이라
        # 프로세스 종료를 막지 않는다.
        print(f"000 {st['size']} {time.monotonic() - t0:.3f} (max-time {max_time}s exceeded)")
        return 1
    elapsed = time.monotonic() - t0
    if st['err'] is not None:
        print(f"000 {st['size']} {elapsed:.3f} ({st['err']})")
        return 1
    print(f"{st['code']} {st['size']} {elapsed:.3f}")
    return 0 if 200 <= st['code'] < 300 and elapsed <= max_time else 1


# ── 수집 상태 칸(2026-11-17, 공통 계약 A) ──────────────────────────────────
# 비-코어 블록의 실패 경로가 「성공」 파일로 남지 않게, 쓰는 자리에서 칸을 만든다.

MARKET_SOURCE = 'yfinance + Naver 국채 + FRED'


# 같은 파일에 실리는 파생 블록. 셋 다 예외를 삼키고 기본값·빈 키로 넘어가므로 `complete` 에 잡히지 않는다
# (2026-09-22 사고 — 배선이 끊겨 price_context·session 이 빠진 날도 complete 였다). 검사기가 읽는 키다.
DERIVED_BLOCKS = ('yield_drivers', 'price_context', 'session')


def market_collect(data):
    """market_data.json — 필수 = 기존 `complete`(전 행·커브·장중 두 지수·섹터) **와** 파생 블록 셋.
    빠진 행은 `missing` 그대로, 실패한 파생 블록은 `block:<이름>`."""
    from common import collect_status as C
    missing = list(data.get('missing') or [])
    if not data.get('indices'):
        return C.failed(data.get('report_date'), MARKET_SOURCE, '지수 행이 없다', missing=missing)
    blocks = []
    if not ((data.get('yield_drivers') or {}).get('rows')):
        blocks.append('block:yield_drivers')
    for key in ('price_context', 'session'):
        if not isinstance(data.get(key), dict):
            blocks.append(f'block:{key}')
    ok = bool(data.get('complete')) and not blocks
    return C.build('ok' if ok else 'partial', data.get('report_date'), MARKET_SOURCE,
                   missing=missing + blocks, required_ok=ok, empty='has_data')


def intraday_collect(intraday, report_date):
    """intraday.json — 30분봉을 못 받은 자산이 `missing`. 그 파일에는 날짜 칸이 없어 as_of 가 유일한 기준일이다."""
    from common import collect_status as C
    names = [n for n, _ in INTRADAY_KEY]
    missing = [n for n in names if not (intraday or {}).get(n)]
    return C.by_counts(report_date, 'yfinance 30m', missing, len(names))


def econ_collect(econ, reasons, report_date, refs=None):
    """econ_indicators.json — 받지 못했거나 변환이 터진 지표가 `missing`.

    「아직 미발표」와 「계산 재료 결측」을 가른다(1a 구현 검토 #5). 새 달이 나오기 전에는 원천의 마지막 달이 그 전
    달이고 그 달로 행을 만든다 — 결측이 아니다. `no_value` 는 원천에 있는 최신 달을 변환할 재료(비교 달)가 원천에
    없다는 뜻이다(예: 2025-10 CPI 미발표로 2026-10 CPI YoY 를 만들 수 없다). 축 점수에 드는 지표(scored — `role` 이
    anatomy 가 아닌 것)의 no_value 는 `missing`(`no_value:<이름>`)·required_ok false, 해부 전용은 `detail` 에만."""
    from common import collect_status as C
    anatomy = {e[1] for e in ECON if len(e) > 5 and (e[5] or {}).get('role') == 'anatomy'}
    missing = sorted(n for n, why in (reasons or {}).items() if why in ('fetch_failed', 'transform_error'))
    missing += sorted(f'no_value:{n}' for n, why in (reasons or {}).items() if why == 'no_value' and n not in anatomy)
    none = sorted(n for n, why in (reasons or {}).items() if why == 'no_value' and n in anatomy)
    # 결측 키 → 그 지표의 식별자·기준월·원인(`missing_ref[키] = {fred_id, transform, ref_period(YYYY-MM), lacking}`) —
    # 항목 단위 승인 예외(`config/prepub_inputs.json` 의 accepted_missing)는 넷이 모두 등록과 같을 때만 적용된다
    # (`lacking` 은 정확히 등록된 그 달 하나). 모르는 키는 싣지 않는다.
    ref = {f'no_value:{n}': dict({k: v[k] for k in ('fred_id', 'transform', 'ref_period')},
                                 lacking=[str(x) for x in v['lacking']],
                                 lacking_why=dict(v.get('lacking_why') or {}))
           for n, v in sorted((refs or {}).items())
           if isinstance(v, dict) and all(v.get(k) for k in ('fred_id', 'transform', 'ref_period'))
           and isinstance(v.get('lacking'), list) and f'no_value:{n}' in missing}
    # 직전 칸이 비었는데 왜 비었는지 가를 근거가 없는 행 — 추정하지 않고 결측으로(보류 쪽)
    missing += sorted(f'previous_unknown:{r.get("name")}' for r in econ or []
                      if isinstance(r, dict) and r.get('previous') is None and r.get('previous_why') == 'unknown')
    st = C.by_counts(report_date, 'FRED', missing, len(ECON),
                     detail=('원천에 최신 값 없음(해부 전용): ' + ', '.join(none)) if none else None,
                     missing_ref=ref or None)
    if not econ and st['status'] != 'failed':
        st = C.failed(report_date, 'FRED', '지표 0건', missing=missing)
    return st


def expected_scored():
    """축 점수에 드는 것으로 **정의된** 지표 `[(축, 이름)]` — ECON 표에서 해부 전용을 뺀 것(산출 범위의 전체 수)."""
    return [(e[0], e[1]) for e in ECON if not (len(e) > 5 and (e[5] or {}).get('role') == 'anatomy')]


def excluded_scored(reasons, refs):
    """no_value 인 점수 대상 지표 → `[{name, axis, fred_id, transform, ref_period}]`(해부 전용은 뺀다)."""
    anatomy = {e[1] for e in ECON if len(e) > 5 and (e[5] or {}).get('role') == 'anatomy'}
    out = []
    for n, why in sorted((reasons or {}).items()):
        r = (refs or {}).get(n)
        if why == 'no_value' and n not in anatomy and isinstance(r, dict):
            out.append({'name': n, **{k: r.get(k) for k in ('axis', 'fred_id', 'transform', 'ref_period', 'lacking',
                                                            'lacking_why')}})
    return out


def _note_run_failure(outdir, rel, error):
    """예외를 삼키고 넘어가는 블록이 파일을 못 썼을 때 — 사유를 수집 상태 장부의 실행 기록에(`stamp_collect.py` 가 읽는다)."""
    try:
        from common import collect_status as C
        C.note_run_failure(outdir, rel, f'{type(error).__name__}: {error}')
    except Exception:  # noqa: BLE001 — 기록 실패가 수집을 막지 않는다(판정은 stamp 가 시각으로 한다)
        pass


def macro_metrics_collect(mm, econ_status, report_date):
    """macro_metrics.json — 축 점수의 재료(econ)가 일부 빠졌거나 어제 책(macro.json)이 깨졌으면 partial.

    econ 이 일부만 받았으면(partial) 그 결측 키를 `econ:<키>` 로 그대로 싣고 기준월(`missing_ref`)도 옮긴다 — 승인
    예외가 이 파일에도 **같은 키·기준월**로 걸리게(1a 구현 검토 2회차 F6). 무엇이 빠졌는지 모르면(실패·목록 없음)
    전처럼 `econ_indicators` 하나 — 그것은 등록할 수 없다."""
    from common import collect_status as C
    missing, ref = [], {}
    if econ_status.get('status') != 'ok':
        missing, ref = C.carry_upstream(econ_status, 'econ', 'econ_indicators')
    # 행은 있는데 축 점수에 쓰이지 않은 지표(점수를 낼 이력이 모자라거나 들인 날) — econ 쪽 결측에는 없으므로 여기서
    # 까닭을 가른 키로 적는다(3회차 G2). 이 키들은 승인 예외에 등록되지 않으니, 섞인 날은 예외가 걸리지 않는다.
    # 들인 날의 제외(introduced)는 자료 결측이 아니라 산출 규칙이다 — 결측에 넣지 않고 적어만 둔다(4회차 H3). 값이 있고
    # 점수가 계산된 행만 그렇게 분류된다(`unused_scored`); 판단을 바꿀 수 있는지·하루를 넘겼는지는 check_macro 가 본다.
    from us.macro_metrics import unused_scored
    unused = unused_scored(mm.get('indicators'))
    missing += [f'{why}:{name}' for name, _axis, why in unused if why != 'introduced']
    rule = [name for name, _axis, why in unused if why == 'introduced']
    if mm.get('book_state') == 'corrupt':
        missing.append('macro.json:corrupt')
    return C.build('partial' if missing else 'ok', report_date, 'FRED (macro_metrics)',
                   missing=missing, empty='has_data', missing_ref=ref or None,
                   detail=('들인 날이라 점수에서 뺀 지표(산출 규칙): ' + ', '.join(rule)) if rule else None)


SOURCE = 'github-actions/collect_market_data.py'


def global_close_settle(report_date):
    """세계 지수 6종의 그 세션 확정 종가 판정 — {티커: 판정}. 절대 예외를 내지 않는다.

    야후 이력의 마지막 행을 쓰지 않는다: 현지 자정 뒤에는 그 행이 전 세션이다. 네이버의 날짜 붙은
    종가를 야후와 맞춰 본 것만 싣고, 못 맞춘 지수는 이유가 붙은 「없음」이다(`us/global_close.py`).
    비-코어 — 여기서 무엇이 실패해도 그 지수 행이 빠질 뿐 수집·완결 판정은 그대로다.
    """
    try:
        from us import global_close
        from us.session import ASIA, EUROPE
        pairs = ASIA + EUROPE
        print('settling global closes (Naver dated close x Yahoo)...')
        out = global_close.collect([t for _, t in pairs], report_date, context=_SSL)
        for name, t in pairs:
            print(global_close.describe(name, out.get(t) or {}), file=sys.stderr
                  if (out.get(t) or {}).get('status') != 'ok' else sys.stdout)
        return out
    except Exception as e:
        print(f'global close settle failed: {e}', file=sys.stderr)
        return {}


def run_id():
    """이 실행의 표시 — 원문 index(`fetch_releases`)·새 발표 원장(`record_releases`)과 같은 꼴."""
    rid = os.environ.get('GITHUB_RUN_ID')
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f'local-{os.getpid()}-{int(time.time())}'


def apply_spreads(data, yields_fred):
    """커브에서 나오는 스프레드 칸. 전체 수집과 수익률만 고치는 재실행이 같은 식을 쓴다."""
    y = data['yields']
    for k in ('spread_2s10s_bp', 'spread_2s10s_aligned', 'spread_2s10s_basis',
              'spread_2s10s_fred_bp', 'spread_5s30s_bp'):
        data.pop(k, None)
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
    yields_fred = yields_fred or {}
    if yields_fred.get('2Y') and yields_fred.get('10Y'):
        data['spread_2s10s_fred_bp'] = (yields_fred['10Y']['level'] - yields_fred['2Y']['level']) * 100
    if y.get('5Y') and y.get('30Y'):
        data['spread_5s30s_bp'] = (y['30Y']['level'] - y['5Y']['level']) * 100


def weekly_aggregate(market_rows, report_date):
    """시세 원장 행 → (주 키, 그 주 집계). 전체 수집과 수익률만 고치는 재실행이 함께 쓴다."""
    from us.period import build as period_build, series_from, week_key
    dated, yh = series_from(market_rows, as_of=report_date)
    # posts.json 은 레포 루트에 있다 — outdir 는 'data' 하위 상대/절대/중첩 어느 값도
    # 될 수 있으므로 outdir 기준 역산 대신 이 스크립트 파일 위치(scripts/ 의 부모)로
    # 레포 루트를 고정한다. Actions 는 항상 레포 루트에서 이 스크립트를 실행한다.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    k = week_key(report_date)
    return k, period_build('weekly', k, dated, yh, daily_headlines(repo_root))


# ── 수익률만 고치는 재실행 (2026-11-19) ─────────────────────────────────────
# 루틴은 `missing` 이 `yields/naver_close_not_posted` 하나뿐인 동안 9분마다 수집을 다시 건다.
# 그 재실행이 전부 다시 모으면 러너 3-4분·커밋 하나가 매번 든다(하루 중앙 3회). 그 당일 판이
# 「네이버만 빠짐」이면 네이버만 한 번 보고: 종가가 왔으면 수익률과 거기서 나오는 것만 고치고,
# 아직 전 거래일이면 아무것도 쓰지 않고 끝낸다. 그 밖의 모든 경우는 None — 전체 수집 그대로다.
NAVER_ONLY_MISSING = ['yields/naver_close_not_posted']
PATCH_PROBE_TIMEOUT_S = 10
PATCH_PROBE_BUDGET_S = 80        # 요청 사이·조각 사이에서 보는 시한(정상적인 느린 응답은 여기서 끝난다)
PATCH_PROBE_WALL_S = 90          # 벽시계 상한 — 무슨 일이 있어도 탐침은 90초에 끊긴다(루틴은 540초 기다린다)
_NY = 'America/New_York'


def _load_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _emit(*lines):
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a') as fh:
            for line in lines:
                fh.write(line + '\n')


def patch_base(outdir, now, no_patch=False):
    """고칠 수 있는 판이면 (prev, intraday, bond_date), 아니면 (None, 이유).

    조건은 전부 「첫 수집이 그날 마감 뒤에 한 실행으로 끝냈고, 고치기가 다시 돌리지 않는 사슬
    (원문·요소 대조·레짐 평가·새 발표 원장)이 그 실행의 것으로 온전하다」를 확인한다. 하나라도
    아니면 전체 수집이 그것을 다시 만든다.
    """
    import zoneinfo
    from us.history import read_jsonl
    from us.naver_yields import bond_session, load_bond_closed
    from fund.calendar import load as load_holidays
    if no_patch:
        return None, '--no-patch'
    prev = _load_json(os.path.join(outdir, 'market_data.json'))
    if not isinstance(prev, dict):
        return None, 'market_data.json 없음·읽기 실패'
    rd, run, gen = prev.get('report_date'), prev.get('collection_run'), prev.get('generated')
    if prev.get('source') != SOURCE or prev.get('complete') is not False \
            or prev.get('missing') != NAVER_ONLY_MISSING:
        return None, '「네이버 종가만 빠진」 판이 아니다'
    if not (rd and run and gen and prev.get('collection_started')):
        return None, '수집 시작·실행 표시가 없는 판'
    try:
        ny = zoneinfo.ZoneInfo(_NY)
        started = datetime.datetime.fromisoformat(prev['collection_started']).astimezone(ny)
        now_ny = now.astimezone(ny)
        day = datetime.date.fromisoformat(rd)
    except (TypeError, ValueError):
        return None, '수집 시작 시각을 읽지 못했다'
    close = datetime.datetime.combine(day, datetime.time(16, 30), tzinfo=ny)
    if started.date() != day or started < close:
        return None, f'첫 수집이 {rd} 16:30 ET 뒤가 아니다({started.isoformat()})'
    if now_ny.date() != day or now_ny < started:
        return None, f'지금 뉴욕 날짜가 {rd} 가 아니거나 첫 수집보다 이르다'
    intraday = _load_json(os.path.join(outdir, 'intraday.json'))
    if not isinstance(intraday, dict):
        return None, 'intraday.json 없음'
    econ = _load_json(os.path.join(outdir, 'econ_indicators.json')) or {}
    mm = _load_json(os.path.join(outdir, 'macro_metrics.json')) or {}
    if econ.get('generated') != gen or mm.get('generated') != gen or mm.get('report_date') != rd:
        return None, 'econ·macro_metrics 가 같은 실행의 것이 아니다'
    index = _load_json(os.path.join(outdir, 'releases', 'index.json')) or {}
    rows = index.get('releases')
    if (index.get('status') != 'complete' or index.get('report_date') != rd
            or index.get('run_id') != run or not isinstance(rows, list)
            or not all(isinstance(r, dict) and r.get('ok') is True for r in rows)):
        return None, '원문 index 가 그 실행의 온전한 것이 아니다(실패한 원문 포함)'
    ev = _load_json(os.path.join(outdir, 'macro_eval.json')) or {}
    if ev.get('report_date') != rd or ev.get('collection_run') != run:
        return None, 'macro_eval 이 그 실행의 것이 아니다'
    scan = f'scan|{rd}|{run}'
    if not any(r.get('id') == scan for r in read_jsonl(os.path.join(outdir, 'history', 'releases.jsonl'))):
        return None, '새 발표 원장에 그 실행의 기록이 없다'
    cal = os.path.join(outdir, 'market_holidays.json')
    bond_date = bond_session(rd, load_bond_closed(cal), (load_holidays(cal) or {}).get('dates') or ())
    holiday = prev.get('yields_bond_holiday')
    if bond_date != rd:
        if not (isinstance(holiday, dict) and holiday.get('curve_date') == bond_date):
            return None, '채권 휴장 기준이 그 판과 다르다'
    elif holiday is not None:
        return None, '채권 휴장 기준이 그 판과 다르다'
    return (prev, intraday, bond_date), None


def _restore_file(path, data):
    """바꿔치기 전 상태로 — `data` 가 None 이면 원래 없던 파일이다."""
    if data is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, 'wb') as fh:
        fh.write(data)


def _install_patch(staged):
    """[(임시 파일, 목적지)] 를 순서대로 바꿔치기한다. market_data.json 이 맨 끝이어야 한다.

    중간에 실패하면 이미 바꾼 파일을 되돌리고(market_data.json 은 맨 끝이라 아직 옛 판이다)
    **exit 1** 로 실행을 실패시킨다 — 아무것도 커밋되지 않고 다음 재실행이 원격의 옛 판에서 다시
    시작한다. 같은 프로세스에서 전체 수집으로 넘어가지 않는다: 방금 쓰기가 실패한 디스크에서 전체
    수집의 이력·주간 쓰기는 실패해도 삼켜지므로(비-코어 try/except) 새 수익률과 옛 이력이 섞여
    커밋될 수 있다(codex 구현 검토 1회 I3).
    """
    backups = []
    for _, target in staged:
        try:
            with open(target, 'rb') as fh:
                backups.append(fh.read())
        except FileNotFoundError:
            backups.append(None)
    done = 0
    try:
        for tmp, target in staged:
            os.replace(tmp, target)
            done += 1
        return True
    except Exception as e:
        print(f'yields patch: install failed at {staged[done][1]} ({e}) — restoring', file=sys.stderr)
        try:
            for (_, target), data in list(zip(staged, backups))[:done]:
                _restore_file(target, data)
        except Exception as e2:
            print(f'yields patch: could not restore the files it replaced ({e2})', file=sys.stderr)
        print('FATAL: yields patch install failed — failing the run so nothing is committed',
              file=sys.stderr)
        sys.exit(1)


def _within(seconds, fn):
    """`fn()` 의 결과를, 벽시계로 `seconds` 초 안에 끝났을 때만 돌려준다. 넘기면 TimeoutError.

    소켓 timeout 은 바이트가 올 때마다 새로 시작하고 버퍼 읽기는 요청한 양이 찰 때까지 돌아오지
    않으므로, 읽기 안쪽에서 시한을 보는 것으로는 조금씩 흘려 보내는 응답을 못 끊는다(codex 구현
    검토 1·2회 I6). 그래서 일을 데몬 스레드에 맡기고 기다리는 쪽에서 끊는다 — 남은 스레드는
    프로세스가 끝날 때 함께 사라지고, 그 결과는 버린다.
    """
    import threading
    box = {}

    def run():
        try:
            box['value'] = fn()
        except BaseException as e:          # 스레드 안의 실패를 부른 쪽으로 옮긴다
            box['error'] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f'not finished within {seconds}s')
    if 'error' in box:
        raise box['error']
    return box['value']


def yields_patch_step(args, now=None):
    """-> 'patched' | 'waiting' | None(전체 수집으로 간다)."""
    import copy
    from us.history import market_record, read_jsonl
    outdir = args.outdir
    now = now or datetime.datetime.now(datetime.timezone.utc)
    base, why = patch_base(outdir, now, getattr(args, 'no_patch', False))
    if base is None:
        print(f'yields patch: not eligible ({why}) — full collection')
        return None
    prev, intraday, bond_date = base
    rd = prev['report_date']
    print(f'yields patch: {rd} lacks only the Naver close — probing Naver for {bond_date}')
    try:
        # 한 쪽(60거래일)만 받는다 — 커브에 필요한 것은 기준일·전일·5거래일 전뿐이다. 쪽이 하나라
        # 「앞쪽만 받고 뒤쪽은 실패한」 반쪽 응답이 생길 수 없다: 만기 하나라도 실패하면 커브가 없다.
        curve, latest = _within(PATCH_PROBE_WALL_S, lambda: naver_spot_yields(
            pages=1, expected_date=bond_date, timeout=PATCH_PROBE_TIMEOUT_S, attempts=1,
            budget_s=PATCH_PROBE_BUDGET_S))
    except Exception as e:
        print(f'yields patch: Naver probe failed ({e})', file=sys.stderr)
        curve, latest = None, None
    usable = bool(curve) and all((curve.get(t) or {}).get(f) is not None
                                 for t in ('2Y', '5Y', '10Y', '30Y') for f in ('level', 'bp'))
    if not usable:
        # 전체 수집의 naver_stale 과 같은 식 — 「아직 안 나왔다」일 때만 기다린다.
        if bool(latest) and curve is None and latest < bond_date:
            print(f'yields patch: Naver is still {latest} (< {bond_date}) — waiting, nothing written')
            _emit('skipped=true', 'waiting=true')
            return 'waiting'
        print('yields patch: no usable Naver curve — full collection', file=sys.stderr)
        return None

    new = copy.deepcopy(prev)
    new['yields'] = merge_yields(prev.get('yields_fred'), prev.get('yields'), curve)
    apply_spreads(new, prev.get('yields_fred'))
    missing = completeness(new, intraday, naver_stale=False, report_date=rd)
    if missing:
        print(f'yields patch: still incomplete after the patch ({", ".join(missing)}) — '
              'full collection', file=sys.stderr)
        return None
    new['complete'], new['missing'] = True, []
    # 수집 상태 칸도 고친 판으로 다시 만든다 — 첫 실행의 partial(네이버 종가 없음)을 물려받으면 1a 장부가 막는다.
    new['collect'] = market_collect(new)
    new['yields_patched'] = {
        'at': now.astimezone(datetime.timezone.utc).isoformat(timespec='seconds'),
        'run': run_id(), 'source': 'Naver', 'date': bond_date}

    hist = os.path.join(outdir, 'history', 'market.jsonl')
    md_path = os.path.join(outdir, 'market_data.json')
    png = os.path.join(outdir, 'yield_curve.png')
    staged = []
    try:
        record = market_record(new)
        rows = [r for r in read_jsonl(hist) if r.get('report_date') != rd] + [record]
        rows.sort(key=lambda r: r.get('report_date') or '')
        k, agg = weekly_aggregate(rows, rd)
        weekly = os.path.join(outdir, 'weekly', f'{k}.json')
        os.makedirs(os.path.dirname(weekly), exist_ok=True)
        os.makedirs(os.path.dirname(hist), exist_ok=True)

        def stage(target, write):
            tmp = os.path.join(os.path.dirname(target), '.patch-' + os.path.basename(target))
            staged.append((tmp, target))
            write(tmp)

        stage(png, lambda tmp: render_curve(new['yields'], tmp))

        def write_hist(tmp):
            with open(tmp, 'w', encoding='utf-8') as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
        stage(hist, write_hist)

        def dump(obj):
            def write(tmp):
                with open(tmp, 'w') as fh:
                    json.dump(obj, fh, indent=2, default=str, ensure_ascii=False)
            return write
        stage(weekly, dump(agg))
        stage(md_path, dump(new))            # 맨 끝 — 이것이 바뀌어야 판이 complete 가 된다
        _install_patch(staged)               # 실패하면 되돌리고 exit 1 — 여기로 돌아오지 않는다
    except Exception as e:
        print(f'yields patch: could not prepare the outputs ({e}) — full collection', file=sys.stderr)
        return None
    finally:
        for tmp, _ in staged:
            try:
                os.remove(tmp)
            except OSError:
                pass
    for t, row in new['yields'].items():
        print(f"  {t}: {row['level']}% ({row.get('source')} {row['date']})")
    print(f'yields patch: {rd} is now COMPLETE (curve {bond_date}, weekly {k})')
    _emit('patched=true')
    return 'patched'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='data')
    ap.add_argument('--force', action='store_true',
                    help='regenerate even if a complete dataset for the same report date exists')
    ap.add_argument('--no-patch', action='store_true',
                    help='네이버 종가만 빠진 당일 판도 수익률만 고치지 않고 전부 다시 모은다')
    ap.add_argument('--fred-check', action='store_true',
                    help='공식 API 와 graph CSV 를 전 생산 시리즈에 대해 대조하고 끝낸다 '
                         '(아무 파일도 쓰지 않는다)')
    ap.add_argument('--ff-probe', action='store_true',
                    help='French 요인 파일을 이 러너에서 받을 수 있는지만 보고 끝낸다 '
                         '(아무 파일도 쓰지 않는다)')
    ap.add_argument('--ff-probe-url', default=None, help=argparse.SUPPRESS)
    ap.add_argument('--max-time', type=float, default=60.0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    # 진단은 정상 경로에 얹지 않는다 — makedirs 앞에서 갈라져야 산출물을 안 건드린다.
    if args.fred_check:
        sys.exit(fred_check())
    if args.ff_probe:
        sys.exit(ff_probe(args.ff_probe_url, args.max_time))

    # 네이버 종가만 기다리는 재실행은 여기서 끝난다(고쳤거나, 아직이라 아무것도 안 썼거나).
    if yields_patch_step(args) is not None:
        return
    # 이 판이 언제·어느 실행에서 모이기 시작했나 — 고치기 경로가 「마감 뒤 한 실행의 판」인지 본다.
    collection_started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

    set_fred_client(None)          # 재진입 실행이 지난 열화 상태를 물려받지 않게
    fredc = fred_client()
    print(f'FRED transport: {fredc.preflight()}'
          + (f' ({fredc.reason})' if fredc.reason else ''))
    if fredc.telemetry()['degraded']:
        from us.fred import annotation
        print('::warning::FRED API key is configured but unusable '
              f'({annotation(f"{fredc.reason}: {fredc.error}")}) — '
              'falling back to the unofficial graph CSV', file=sys.stderr)

    os.makedirs(args.outdir, exist_ok=True)
    md_path = os.path.join(args.outdir, 'market_data.json')

    print('collecting daily closes (batched)...')
    daily, anchor = collect_daily()
    daily = fill_daily_gaps(daily, anchor)
    # 환율·원자재는 일봉 대신 16:00 ET 컷으로 덮는다 — 일봉 행이 남으면 completeness 가
    # basis 로 막는다.
    if anchor:
        print('collecting 16:00 ET cuts for fx and commodities...')
        contracts = futures_contracts()
        cut = collect_cut_rows(anchor, contracts)
        for group in ('fx', 'commodities'):
            daily[group] = cut[group]
    else:
        cut, contracts = {}, {}
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
                # 뒤 단계(뉴스·일정·연준·커밋)도 멈추게 알린다. 수집기만 건너뛰고 뒤 단계가 돌면
                # 뉴스가 다시 긁히고 커밋이 생겨, 그 push 가 루틴을 또 띄웠다(2026-09-26).
                out = os.environ.get('GITHUB_OUTPUT')
                if out:
                    with open(out, 'a') as fh:
                        fh.write('skipped=true\n')
                return
        except Exception:
            pass

    print('collecting Naver same-date curve (primary: 2Y/5Y/10Y/30Y)...')
    # 채권시장만 쉬는 날(콜럼버스 데이·재향군인의 날)은 그날 국채 종가가 영영 없다 —
    # 직전 국채 마감일 커브를 그 날짜 그대로 싣는다(2026-10-12 글이 이것 때문에 빠졌다).
    from us.naver_yields import bond_session, load_bond_closed
    from fund.calendar import load as load_holidays
    cal_path = os.path.join(args.outdir, 'market_holidays.json')
    bond_date = bond_session(report_date, load_bond_closed(cal_path),
                             (load_holidays(cal_path) or {}).get('dates') or ())
    if bond_date != report_date:
        print(f'  {report_date} is a US bond-market holiday — curve as of {bond_date}')
    yields_naver, naver_latest = naver_spot_yields(expected_date=bond_date)
    # 「아직 안 나왔다」와 「못 받았다」는 다르게 다뤄야 한다. 전자는 다음 회차가 메울
    # 수 있으므로 incomplete 로 남겨 멱등 가드가 재시도를 막지 않게 하고, 후자는
    # 야후·FRED 폴백으로 발행한다 — 네이버 장애로 발행이 멈추면 안 된다.
    naver_stale = bool(naver_latest) and yields_naver is None and naver_latest < bond_date
    if naver_stale:
        print(f'  Naver curve is still {naver_latest} (< {bond_date}) — 국채 마감 전 회차로 본다',
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
    econ_reasons, econ_refs = {}, {}
    econ, econ_series = collect_econ(econ_reasons, econ_refs)
    econ_status = econ_collect(econ, econ_reasons, report_date, econ_refs)
    # 「직전 대비」 칸의 정본(2026-09-23). macro_metrics.json 이 실패하거나 낡은 날에도
    # 표에 찍힌 두 수의 비교는 이 파일 하나로 끝나야 한다 — 게이트도 같은 함수로 잰다.
    from us.macro_metrics import TREND_NOTE_KO, vs_prev
    for e in econ:
        e['vs_prev'] = vs_prev(e.get('name'), e.get('axis'), e.get('actual'), e.get('previous'))
    print(f'  econ indicators: {len(econ)}/{len(ECON)}')
    print('collecting sector multi-horizon performance...')
    sector_perf, perf_as_of = collect_sector_performance()
    print(f'  sector perf: {sum(1 for v in sector_perf.values() if v)}/{len(SECTORS)} (as of {perf_as_of})')
    print('collecting 30m intraday bars...')
    # 표와 같은 월물·같은 마감 시각(단축장이면 13:00 ET)으로 자른다.
    cut_m = 16 * 60
    _w = (cut.get('commodities') or {}).get('WTI') or {}
    if _w.get('cut_et'):
        hh, mm = _w['cut_et'].split(':')
        cut_m = int(hh) * 60 + int(mm)
    intraday = collect_intraday(datetime.date.fromisoformat(report_date),
                                # 표 행을 실제로 만든 티커(월물 폴백 포함)를 넘긴다(codex 재검토 P2).
                                symbols={n: ((cut.get('commodities') or {}).get(n) or {}).get('contract')
                                         for n in ('WTI', 'Gold')},
                                cut_minutes=cut_m)

    data = {
        'generated': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST'),
        'source': SOURCE,
        'collection_started': collection_started,
        'collection_run': run_id(),
        'report_date': report_date,
        'indices': daily['indices'],
        'sectors': daily['sectors'],
        'fx': daily['fx'],
        'commodities': daily['commodities'],
        'memory': daily['memory'],
        'ai_infra': daily['ai_infra'],
        'mlcc': daily['mlcc'],
        'yields': yields,
        'yields_fred': yields_fred,
        'yields_note': 'yields = 발행용 기준값. 1순위는 네이버 국채 종가(SIFMA 국채 현물 '
                       '마감 17:05 ET)로 **전 만기가 동일 기준일**이다. 네이버가 비면 '
                       'Yahoo 스팟(^FVX/^TNX/^TYX) -> FRED 순으로 메우는데, 그때는 만기별 '
                       'date가 갈릴 수 있으므로 각 행의 source/date를 표·차트·캡션에 표기할 것. '
                       'yields_fred는 전 만기 FRED 동일자 대조용.',
        'yield_drivers': drivers,
        # 채권 휴장일에만 붙는다. 작성자는 커브를 「채권시장 휴장 — <curve_date> 종가」로 쓰고
        # 행의 bp 를 그날의 움직임으로 읽지 않는다(bp 는 curve_date 의 전일比다).
        **({'yields_bond_holiday': {'closed': report_date, 'curve_date': bond_date}}
           if bond_date != report_date else {}),
        'sector_performance': sector_perf,
        'sector_performance_as_of': perf_as_of,
    }
    y = data['yields']
    apply_spreads(data, yields_fred)

    missing = completeness(data, intraday, naver_stale=naver_stale, report_date=report_date)
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

    # Non-core, and shared: one batched download feeds both the scorecard and the
    # price-context readings. A failure here must not cost us the dataset — the
    # scorecard simply reports `sufficient: false` rather than inventing a score.
    print('collecting close-price histories (batched)...')
    try:
        closes, hist_dates, hist_as_of, hist_ohlc = collect_histories()
        closes, hist_dates = apply_cut_to_histories(closes, hist_dates, cut)
        print(f'  histories: {sum(1 for v in closes.values() if v)}/{len(closes)} '
              f'(as of {hist_as_of})')
    except Exception as e:
        print(f'histories failed: {e}', file=sys.stderr)
        closes, hist_dates, hist_as_of, hist_ohlc = {}, {}, None, {}

    # Non-core, same contract as above: the macro regime's axis scores. `last_seen`
    # comes from yesterday's committed book — without it every indicator reads as newly
    # released and the regime would be free to move every single day.
    print('computing macro axis scores...')
    try:
        from us.macro_metrics import compute as compute_macro_metrics
        last_seen, book_state, book_date = None, 'absent', None
        book_path = os.path.join(args.outdir, 'macro.json')
        if os.path.exists(book_path):
            try:
                book = json.load(open(book_path))
                last_seen = book.get('last_seen')
                book_date = book.get('report_date')
                book_state = 'ok' if last_seen else 'empty'
            except Exception:
                book_state = 'corrupt'
        if book_state != 'ok':
            print(f'  macro.json {book_state} — treating every indicator as new', file=sys.stderr)
        mm = compute_macro_metrics(econ_series, econ, last_seen, book_state=book_state,
                                   book_date=book_date)
        print(f"  growth {mm['growth_score']} / inflation {mm['inflation_score']} · "
              f"신규 발표 {len(mm['new_releases'])}건")

        # 2026-11-08 (A단계): a component is printed only when FRED as of the release
        # date and the agency's own text agree on it. Step one here — the FRED side;
        # step two (`xcheck_components.py`) runs after the release texts are fetched.
        # Without the official API there is no vintage history, so every component is
        # left out and the anatomy falls back to the text or the headline.
        mm = _anatomy_round(mm, econ, econ_series, last_seen, book_state, book_date,
                            report_date, compute_macro_metrics)
        # 원천에 재료가 없어 행을 만들지 못한 점수 대상 지표 — 축 점수가 몇 개 중 몇 개로 나왔는지와, 그 지표가 있었다면
        # 판단이 달라질 수 있는지를 함께 싣는다(추정치로 채우지 않는다). 2026-11-17 사용자 승인 조건 7·8.
        # **1a 를 켠 뒤에만 싣는다**(2026-11-20 사용자 결정): `coverage`·`axis_summary[축].coverage_ko` 는 작성자가 읽는
        # 파일에 새로 나타나는 칸이다 — 꺼진 동안 작성 입력은 1a 전과 같아야 한다(작성 지시문은 이 칸을 모른다).
        # 무엇이 빠졌는지는 꺼져 있어도 `collect.missing`·`missing_ref` 에 남는다.
        from us.macro_metrics import with_coverage
        from verification.inputs import enforcing
        if enforcing():
            mm = with_coverage(mm, excluded_scored(econ_reasons, econ_refs), expected_scored())
        for rel in mm['headline_releases']:
            anat = rel.get('anatomy') or {}
            ok = sum(1 for c in anat.get('candidates') or [] if c.get('round_ok'))
            print(f"    해부 {rel['key']}: {rel['label']} ({rel.get('role')}) "
                  f"발표일 {anat.get('release_date')} · FRED 회차 {anat.get('round')} · "
                  f"후보 {ok}/{len(anat.get('candidates') or [])}")
        # 실패하면 이 블록은 파일을 쓰지 않는다 — 어제 파일의 report_date·collect.as_of 가 그대로 남아 낡음으로 걸린다.
        json.dump({'generated': data['generated'], 'report_date': report_date, **mm,
                   'collect': macro_metrics_collect(mm, econ_status, report_date)},
                  open(os.path.join(args.outdir, 'macro_metrics.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f'macro metrics failed: {e}', file=sys.stderr)
        # 같은 날 앞선 실행의 파일이 남으면 날짜로는 안 걸린다 — 이번 실행의 실패를 장부에 남긴다(1a 구현 검토 2회차 F3)
        _note_run_failure(args.outdir, 'macro_metrics.json', e)

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
                               collect_futures_bars(), report_date, ohlc=hist_ohlc,
                               settle=global_close_settle(report_date))
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
        print(f"  마감 위치 경계: {cal['high']}/{cal['low']} (지수 {cal.get('indices', '?')}개 · 일간 관측값 {cal['sessions']}개 실측)"
              if cal else '  마감 위치 경계: 초안값 75/25 (표본 부족)')
        print(f"  출발: {sess['futures']['direction'] or '판정 불가'} / "
              f"야간 선물 {len(sess['futures']['contracts'])}종")
    except Exception as e:
        print(f'session context failed: {e}', file=sys.stderr)

    # 트렌드 유닛 점검판 — 비-코어. JSON 은 실패해도 쓰고(unavailable), HTML 은 그릴 수
    # 있을 때만 남긴다. 어제 블록이 오늘 것으로 읽히는 길을 막는다.
    fund_desk(closes, hist_dates, data, report_date, args.outdir)

    print('scoring the macro record...')
    try:
        from us.history import read_jsonl
        from us.scorecard import build as build_scorecard
        from us.scorecard import direction_changes
        # **원장에서 직접 전환을 뽑는다**(2026-09-19). 예전에는 stance.json 의 자기 보고
        # `history` 를 읽었는데, 그 책이 없어졌고 원장 쪽이 덜 거짓말한다 — 매일 그날
        # 책 전체가 남으므로 연속한 두 행을 견주면 전환이 나온다.
        macro_rows = read_jsonl(os.path.join(args.outdir, 'history', 'macro.jsonl'))
        if not macro_rows:
            print('  no macro ledger — nothing to score', file=sys.stderr)
        card = build_scorecard(direction_changes(macro_rows), closes, hist_dates)
        print(f"  채점 {card['scored']}건 / 필요 {card['min_sample']}건"
              + (f" · 적중률 {card['hit_rate']}%" if card['sufficient'] else ' · 표본 부족'))
        json.dump({'generated': data['generated'], 'report_date': report_date, **card},
                  open(os.path.join(args.outdir, 'scorecard.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f'scorecard failed: {e}', file=sys.stderr)
        _note_run_failure(args.outdir, 'scorecard.json', e)

    # FRED 텔레메트리는 **마지막 FRED 호출 뒤**에 굳힌다 — 구성항목 수집이 위에서
    # 끝나므로 여기 값이 그 실행의 전부다. 죽은 키로 몇 주가 조용히 지나는 것을
    # 이 필드 하나로 잡는다.
    data['fred'] = fred_client().telemetry()
    ft = data['fred']
    print(f"FRED: transport={ft['transport']} requests={ft['requests']} "
          f"series={ft['series_ok']}"
          + (f" failed={','.join(ft['failed'])}" if ft['failed'] else '')
          + (f" csv_rescued={','.join(ft['csv_rescued'])}" if ft['csv_rescued'] else ''))

    data['collect'] = market_collect(data)
    json.dump(data, open(md_path, 'w'), indent=2, default=str, ensure_ascii=False)

    # 움직인 종목 — S&P 500 중 달러 거래대금 상위 60 에서 지수 기여 상·하위 2 + |등락| ≥ 5% 를
    # GICS 하위 업종·방향으로 묶어 최대 5묶음. 리서치가 묶음마다 「왜」를 찾는다. 비-코어.
    try:
        from us.movers_data import collect as collect_movers
        movers = collect_movers(report_date, _SSL)
    except Exception as e:
        # 묶음 0개가 「움직인 종목 없음」으로 읽히면 안 된다 — error 와 collect failed 를 함께 적는다.
        from common.movers import stamp as stamp_movers
        movers = stamp_movers({'report_date': report_date, 'groups': [], 'error': str(e)[:200]},
                              source='Wikipedia S&P 500 constituents + yfinance', checked=0, expected=0)
    json.dump(movers, open(os.path.join(args.outdir, 'movers.json'), 'w'),
              indent=2, ensure_ascii=False)
    print(f"movers: {len(movers.get('groups', []))} groups" + (f" ({movers['error']})" if movers.get('error') else ''))

    # 승계 책 이력 — 오늘 커밋돼 있는 macro 를 로그에 밀어 넣는다.
    # 어제까지의 판단이 대상이다 (오늘 것은 아직 writer 가 만들지 않았다).
    try:
        from us.history import append_jsonl, macro_record, market_record
        hdir = os.path.join(args.outdir, 'history')
        # 시세 원장이 먼저다 — 기간 집계가 이 행을 읽는다.
        if append_jsonl(os.path.join(hdir, 'market.jsonl'), market_record(data),
                        upsert=True):
            print(f"history: appended {report_date} to market.jsonl")
        for name, fn, out in (('macro.json', macro_record, 'macro.jsonl'),):
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
        # 시세를 다시 받지 않는다 — 발행본이 인쇄한 스냅샷 원장만 굴린다.
        k, agg = weekly_aggregate(read_jsonl(os.path.join(args.outdir, 'history', 'market.jsonl')),
                                  report_date)
        d = os.path.join(args.outdir, 'weekly')
        os.makedirs(d, exist_ok=True)
        json.dump(agg, open(os.path.join(d, f'{k}.json'), 'w'),
                  indent=2, default=str, ensure_ascii=False)
        print(f"weekly {k}: {agg['sessions']} sessions, complete={agg['complete']}")
    except Exception as e:
        print(f'period aggregation failed: {e}', file=sys.stderr)

    json.dump({**intraday, 'collect': intraday_collect(intraday, report_date)},
              open(os.path.join(args.outdir, 'intraday.json'), 'w'),
              indent=2, default=str, ensure_ascii=False)
    json.dump({'generated': data['generated'], 'source': 'FRED via collect_market_data.py',
               'note': 'Actual/Previous/ref_period are authoritative FRED values. '
                       'Forecast/consensus and release dates are NOT here — the agent adds '
                       'those from web only for recently-released indicators. '
                       'Indicators absent from this list (ISM, S&P Global PMI, ADP, CB '
                       'Confidence, NY Fed inflation exp) are web-sourced. role=anatomy rows '
                       '(Philly Fed) are dissected but never scored.',
               'trend_note_ko': TREND_NOTE_KO,
               'indicators': econ,
               'collect': econ_status},
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
