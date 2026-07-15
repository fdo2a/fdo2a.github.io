#!/usr/bin/env python3
"""US Morning Brief — canonical market data collector.

Runs in GitHub Actions (network-open environment) after the US close and
commits data/market_data.json, data/intraday.json, data/yield_curve.png so the
cloud routine (network-restricted) can consume them without fetching anything.

Schema is identical to the inline scripts in .claude/agents/brief-data-collector.md,
plus top-level report_date / complete / missing / source fields used by the
orchestrator's completeness gate.
"""
import argparse, csv, datetime, io, json, os, ssl, sys, time, urllib.request, warnings

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
           ('Health Care', 'XLV'), ('Industrials', 'XLI'), ('Financials', 'XLF'), ('Materials', 'XLB')]
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


def collect_daily():
    """One batched download for every daily ticker; returns {group: {name: row|None}}."""
    import yfinance as yf
    tickers = [t for _, pairs in GROUPS for _, t in pairs]

    def dl():
        df = yf.download(tickers, period='7d', interval='1d', group_by='ticker',
                         auto_adjust=True, progress=False, threads=False)
        return df if df is not None and len(df) else None

    df = retry(dl)
    out = {}
    for group, pairs in GROUPS:
        out[group] = {}
        for name, t in pairs:
            row = None
            try:
                closes = df[t]['Close'].dropna()
                if len(closes) >= 2:
                    prev, cur = float(closes.iloc[-2]), float(closes.iloc[-1])
                    row = {'last': cur, 'chg': cur - prev, 'pct': (cur / prev - 1) * 100,
                           'date': str(closes.index[-1].date())}
            except Exception:
                row = None
            out[group][name] = row
    return out


def fill_daily_gaps(daily):
    """Per-ticker fallback for anything the batch download missed."""
    import yfinance as yf
    for group, pairs in GROUPS:
        for name, t in pairs:
            if daily[group][name] is not None:
                continue

            def one():
                h = yf.Ticker(t).history(period='7d')['Close'].dropna()
                if len(h) < 2:
                    return None
                prev, cur = float(h.iloc[-2]), float(h.iloc[-1])
                return {'last': cur, 'chg': cur - prev, 'pct': (cur / prev - 1) * 100,
                        'date': str(h.index[-1].date())}

            daily[group][name] = retry(one)
            time.sleep(1)
    return daily


def fred_series(sid):
    """(date, value) pairs, oldest→newest, '.' rows dropped."""
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}'
    data = urllib.request.urlopen(url, timeout=25, context=_SSL).read().decode()
    rows = list(csv.reader(io.StringIO(data)))[1:]
    return [(r[0], float(r[1])) for r in rows if r[1] not in ('.', '')]


def fred_yields():
    out = {}
    for name, sid in [('2Y', 'DGS2'), ('5Y', 'DGS5'), ('10Y', 'DGS10'), ('30Y', 'DGS30')]:
        def one(sid=sid):
            vals = fred_series(sid)
            d2, d1 = vals[-2], vals[-1]
            wk = vals[-6] if len(vals) >= 6 else None
            return {'level': d1[1], 'date': d1[0], 'bp': (d1[1] - d2[1]) * 100,
                    'week_ago': wk[1] if wk else None, 'week_ago_date': wk[0] if wk else None}
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
    a series that fails to fetch is simply omitted (agent falls back to web for it)."""
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
    return out


def yahoo_yields_supplement():
    """Same-day CBOE yield indices (5Y/10Y/30Y) to cross-check FRED's 1-business-day lag."""
    import yfinance as yf
    out = {}
    for name, t in [('5Y', '^FVX'), ('10Y', '^TNX'), ('30Y', '^TYX')]:
        def one(t=t):
            h = yf.Ticker(t).history(period='7d')['Close'].dropna()
            if not len(h):
                return None
            return {'level': float(h.iloc[-1]) / 1.0, 'date': str(h.index[-1].date())}
        out[name] = retry(one, attempts=2)
        time.sleep(1)
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
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=11, color=INK2)
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


def completeness(data, intraday):
    missing = []
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
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='data')
    ap.add_argument('--force', action='store_true',
                    help='regenerate even if a complete dataset for the same report date exists')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    md_path = os.path.join(args.outdir, 'market_data.json')

    print('collecting daily closes (batched)...')
    daily = fill_daily_gaps(collect_daily())
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

    print('collecting FRED yields...')
    yields = fred_yields()
    print('collecting Yahoo yield supplement...')
    yields_yahoo = yahoo_yields_supplement()
    print('collecting FRED economic indicators...')
    econ = collect_econ()
    print(f'  econ indicators: {len(econ)}/{len(ECON)}')
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
        'yields_yahoo_sameday': yields_yahoo,
    }
    y = data['yields']
    if y.get('2Y') and y.get('10Y'):
        data['spread_2s10s_bp'] = (y['10Y']['level'] - y['2Y']['level']) * 100

    missing = completeness(data, intraday)
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

    json.dump(data, open(md_path, 'w'), indent=2, default=str, ensure_ascii=False)
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
