#!/usr/bin/env python3
"""Collect the deterministic numbers behind the thesis watch.

Runs in GitHub Actions, not in the cloud routine: routine environments get 403 from every
financial host (Yahoo, FRED), which is why market data collection was moved here for the
US brief in 2026-07-15 and the KR brief in 2026-07-22. Same reason, same shape.

Writes three files under thesis/data/:
  watch.json      today's snapshot per ticker
  history.jsonl   one row appended per day — the only way a 30-day consensus change is
                  ever knowable, since yfinance serves today's estimate and nothing else
  (thesis_state.json is the routine's to write, never this script's)

Usage:  python3 scripts/collect_thesis_data.py [--force] [--out thesis/data]

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

import argparse
import datetime
import json
import os
import ssl
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings('ignore')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from thesis import disclosure as D  # noqa: E402
from thesis import newsroom as NR  # noqa: E402
from thesis import history as H  # noqa: E402
from thesis import valuation as V  # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL = _ssl_context()

TICKERS = [
    ('005930.KS', '삼성전자', 'KRW'),
    ('000660.KS', 'SK하이닉스', 'KRW'),
    ('MU', 'Micron', 'USD'),
]

# DART 고유번호 -> (corp_code, 종목코드). 매핑표 전체는 20MB 짜리 zip 이라 두 종목은
# 상수로 두되, 매 수집마다 company.json 의 stock_code 와 대조한다(disclosure.verify_corp).
# 틀린 고유번호는 오류가 아니라 «조회 결과 없음» 으로 돌아와 조용한 날과 구분되지 않는다 —
# ECOS 항목 코드가 INFO-200 으로 조용히 실패하던 것과 같은 함정이다.
# Micron 은 미국 상장사라 DART 에 없다.
DART_CORPS = {
    '005930.KS': ('00126380', '005930'),
    '000660.KS': ('00164779', '000660'),
}

# Fields recorded to history.jsonl. Kept deliberately small — this file is appended
# forever, and every field here is one we actually difference over time.
HISTORY_FIELDS = ('eps_fy1', 'eps_fy1_low', 'eps_fy1_high', 'price', 'pb', 'price_date')

# The valuation lines as they stood that day, recorded alongside. They move daily with
# estimates, so "did the price cross the line?" is unanswerable later unless we keep the
# line we drew at the time — without these, a line sliding under a flat price and a price
# falling through a fixed line look identical.
HISTORY_FV_FIELDS = ('band1', 'band2', 'bear')


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


def _num(value):
    """Coerce to a plain float, or None. yfinance hands back numpy scalars and NaN."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out  # NaN


def _estimates(tk):
    """Consensus FY0/FY1 EPS with dispersion, from yfinance's earnings_estimate table."""
    out = {}
    try:
        table = tk.earnings_estimate
    except Exception:
        return out
    if table is None or getattr(table, 'empty', True):
        return out
    for period, prefix in (('0y', 'eps_fy0'), ('+1y', 'eps_fy1')):
        if period not in table.index:
            continue
        row = table.loc[period]
        out[prefix] = _num(row.get('avg'))
        if prefix == 'eps_fy1':
            out['eps_fy1_low'] = _num(row.get('low'))
            out['eps_fy1_high'] = _num(row.get('high'))
            out['eps_fy1_analysts'] = _num(row.get('numberOfAnalysts'))
    return out


def _book_value_per_share(tk, info):
    """(BVPS, balance-sheet date) from the latest *reported* quarterly statement.

    yfinance has no `bookValue` for either Korean name, so it is computed from equity and
    share count. The date matters and is returned with it: yfinance lags a quarter behind
    the press release, and in a cycle where equity compounds 30-50% a quarter that lag is
    a large, one-directional understatement. The page must show the basis rather than let
    anyone quietly patch a fresher number in — a hand-adjusted book value is exactly the
    kind of invented figure this pipeline exists to prevent.
    """
    bvps = _num(info.get('bookValue'))
    try:
        bs = tk.quarterly_balance_sheet
        if bs is None or getattr(bs, 'empty', True):
            return bvps, None
        equity = shares = None
        for row in ('Stockholders Equity', 'Total Equity Gross Minority Interest'):
            if row in bs.index:
                equity = _num(bs.loc[row].iloc[0])
                break
        if 'Ordinary Shares Number' in bs.index:
            shares = _num(bs.loc['Ordinary Shares Number'].iloc[0])
        as_of = str(bs.columns[0].date())
        if equity and shares:
            return equity / shares, as_of
        return bvps, as_of if bvps else None
    except Exception:
        return bvps, None


def _next_earnings(tk):
    try:
        cal = tk.calendar
    except Exception:
        return None
    if not cal:
        return None
    value = cal.get('Earnings Date') if isinstance(cal, dict) else None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime('%Y-%m-%d')
    return None


def collect_ticker(symbol, name, currency):
    import yfinance as yf

    tk = yf.Ticker(symbol)
    hist = retry(lambda: tk.history(period='1y'))
    if hist is None or hist.empty:
        return None

    closes = hist['Close'].dropna()
    price = _num(closes.iloc[-1])
    price_date = str(closes.index[-1].date())
    high_52w = _num(closes.max())
    chg_20d = None
    if len(closes) > 20:
        prior = _num(closes.iloc[-21])
        if prior:
            chg_20d = round((price / prior - 1) * 100, 2)

    info = retry(lambda: tk.info) or {}
    row = {
        'name': name,
        'currency': currency,
        'price': round(price, 2) if price else None,
        'price_date': price_date,
        'chg_20d_pct': chg_20d,
        'pct_from_52w_high': round((price / high_52w - 1) * 100, 2) if high_52w else None,
        'market_cap': _num(info.get('marketCap')),
    }
    row.update(_estimates(tk))

    bvps, bvps_as_of = _book_value_per_share(tk, info)
    row['bvps'] = round(bvps, 2) if bvps else None
    row['bvps_as_of'] = bvps_as_of
    row['bvps_source'] = 'yfinance' if bvps else None
    if price and bvps:
        row['pb'] = round(price / bvps, 2)
    if price and row.get('eps_fy1'):
        row['pe_fy1'] = round(price / row['eps_fy1'], 2)
    row['next_earnings_date'] = _next_earnings(tk)
    return row


REQUIRED = ('price', 'eps_fy1')


def apply_dart_book_value(tickers, today):
    """Replace yfinance's book value with the latest *filed* one, where DART has it.

    yfinance lags the press release by about a quarter, and in a cycle where equity
    compounds 30-50% a quarter that lag understates book value in one direction — in
    2026-08 SK하이닉스 was still showing a Q1 basis. DART's statement is filed about 45 days
    after quarter end, so this shortens the lag by roughly one quarter. It does not make
    book value same-day, and `bvps_as_of` keeps saying which period it is.

    Non-core: any failure leaves the yfinance number in place rather than blocking
    collection, and `bvps_source` records which one the page is showing.

    Note this moves the asset leg of `fair_value`, so the switchover day can legitimately
    fire a bear-line trigger. `triggers.evaluate()` reports that as 「기준선이 이동」, which
    is what actually happened — the line moved, not the price.
    """
    for symbol, (corp_code, _) in DART_CORPS.items():
        row = tickers.get(symbol)
        if not row:
            continue
        try:
            value, period = D.book_value(corp_code, today)
        except Exception as e:  # noqa: BLE001 — 비-코어, 어떤 실패든 yfinance 값을 남긴다
            print(f'  DART 재무제표 {symbol}: {D.scrub(e)}', file=sys.stderr)
            continue
        if not value:
            continue
        row['bvps'] = round(value, 2)
        row['bvps_as_of'] = period
        row['bvps_source'] = 'dart'
        if row.get('price'):
            row['pb'] = round(row['price'] / value, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='thesis/data')
    ap.add_argument('--force', action='store_true',
                    help='주말·휴장에도 수집 (기본은 평일만)')
    args = ap.parse_args()

    # KST 고정. Actions 러너는 UTC라 같은 실행이 로컬(KST)과 하루 어긋난 날짜를 기록했다.
    # 스케줄 시각(17:40 KST)에는 두 날짜가 같지만, 수동 실행이나 스케줄 변경 때 갈라진다.
    # 한국 시각 기준 루틴이고 페이지도 한국어이므로 KST 하나로 못 박는다.
    today = datetime.datetime.now(KST).date()
    if today.weekday() >= 5 and not args.force:
        print(f'주말({today}) — 건너뜀. 강제하려면 --force')
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tickers, missing = {}, []
    for symbol, name, currency in TICKERS:
        print(f'수집 {symbol} ({name})…')
        row = collect_ticker(symbol, name, currency)
        if row is None:
            missing.append(symbol)
            continue
        gaps = [f for f in REQUIRED if row.get(f) is None]
        if gaps:
            missing.append(f'{symbol}:{",".join(gaps)}')
        tickers[symbol] = row

    # 공시 재무제표가 yfinance 보다 새 분기면 갈아끼운다. fair_value 계산 **전에** 해야
    # 자산법이 낡은 장부가로 굴러가지 않는다.
    apply_dart_book_value(tickers, today.isoformat())

    watch = {
        'as_of': today.isoformat(),
        'complete': not missing and len(tickers) == len(TICKERS),
        'missing': missing,
        'tickers': tickers,
    }

    # Fair value is computed here, not in the routine, so the numbers on the page are
    # reproducible from a committed file rather than from an agent's arithmetic.
    for symbol, row in tickers.items():
        fv = V.fair_value(symbol, row)
        if fv:
            row['fair_value'] = fv
            row['position'] = V.position_vs_scenarios(row.get('price'), fv)

    (out_dir / 'watch.json').write_text(
        json.dumps(watch, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # 공시 — 비-코어. **오늘 행을 append 하기 전에** 이력을 읽는다: 조회 창이 마지막
    # 기록일부터 시작해야 수집이 실패했던 날과 18:00 직전 공시가 다음 창에 걸린다.
    history_rows = H.load(out_dir / 'history.jsonl')
    try:
        disclosures = D.collect(DART_CORPS, history_rows, today.isoformat())
    except Exception as e:  # noqa: BLE001 — 공시 실패가 수집 전체를 죽이지 않는다
        disclosures = {'as_of': today.isoformat(), 'tickers': {},
                       'missing': [D.scrub(e)[:200]]}
    (out_dir / 'disclosures.json').write_text(
        json.dumps(disclosures, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    confirmed = sum(t.get('confirmed_count', 0) for t in disclosures['tickers'].values())
    print(f'공시 confirmed={confirmed} '
          f'missing={disclosures.get("missing") or "없음"}'
          f'{" (DART_API_KEY 미설정)" if disclosures.get("pending") else ""}')

    # 뉴스룸 — 비-코어. 창은 직전 수집 시각부터다(events.json 의 collected_at).
    # 실패한 피드는 missing 에 남고, 그러면 그날은 「조용함을 증명할 수 없는 날」이 된다.
    events_path = out_dir / 'events.json'
    try:
        prev_events = json.loads(events_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        prev_events = None
    try:
        events = NR.collect(prev_events, datetime.datetime.now(KST).replace(microsecond=0))
    except Exception as e:  # noqa: BLE001 — 뉴스룸 실패가 수집 전체를 죽이지 않는다
        events = {'collected_at': datetime.datetime.now(KST).replace(microsecond=0).isoformat(),
                  'items': [], 'missing': [f'{type(e).__name__}: {str(e)[:160]}']}
    events_path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    print(f'뉴스룸 새 항목={len(events["items"])} missing={events["missing"] or "없음"}')

    H.append(out_dir / 'history.jsonl', {
        'date': today.isoformat(),
        'tickers': {
            s: {**{f: r.get(f) for f in HISTORY_FIELDS},
                **{f: (r.get('fair_value') or {}).get(f) for f in HISTORY_FV_FIELDS}}
            for s, r in tickers.items()},
    })

    print(f'\nwatch.json complete={watch["complete"]} missing={missing or "없음"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
