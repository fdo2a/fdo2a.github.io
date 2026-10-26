#!/usr/bin/env python3
"""일본 일간 수집 — 수집 후보 스냅샷 `japan/data/daily/candidate/<session>.json` (2026-10-27).

**Actions 에서만 돈다**(`collect-japan-daily.yml`) — 루틴 환경은 금융 호스트에 닿지 못한다. 루틴은
세션을 정해 이 워크플로를 dispatch 하고 결과를 기다린다(AGENTS.md 규칙 10②).

- 닛케이: 일경 공식 CSV 의 세션 행 = 종가, yfinance `fast_info.lastPrice` 와 0.01% 안이어야 `complete`.
  분모도 공식 CSV 의 직전 세션 행이다. CSV 는 복제·재배포 금지 문구가 있어 **커밋하지 않는다**.
- ETF·개별주: 5분봉 마지막 봉 날짜가 세션일 때만 `lastPrice`. 분모는 발행 이력 → yfinance 일봉의
  **정확히 직전 세션 행**뿐. ±15% 는 분할 검증 트리거.
- 엔: 5분봉의 16:30 JST 에 끝난 봉. 직전 세션도 같은 컷이 있어야 등락을 낸다.
- JGB: MOF 커브(T+1) — 직전 세션 행만. BOJ: 콜 O/N·매크로 시리즈(키 없음, 실행당 10회 이내).
- **발행된 세션은 덮지 않는다**(`AlreadyPublished`) — 발행 스냅샷은 발행 단계(`publish_japan_daily.py`)의 것이다.
- 실패한 원천은 `fetch_status` 에 사유로 남는다. 닛케이만 코어이고, 나머지는 그 블록만 빠진다.

순수 로직은 `japan/daily_*.py`. 설계 docs/superpowers/specs/2026-10-27-japan-daily-design.md §13.

  python3 scripts/collect_japan_daily.py --session 2026-10-26 --prev 2026-10-23
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import weekly_sources as WS  # noqa: E402
from japan import daily_calendar as CAL  # noqa: E402
from japan import daily_macro as MAC  # noqa: E402
from japan import daily_movers as MOV  # noqa: E402
from japan import daily_prices as PR  # noqa: E402
from japan import daily_rates as RT  # noqa: E402

DAILY_DIR = os.path.join('japan', 'data', 'daily')
HISTORY = os.path.join('japan', 'data', 'history', 'jp_daily.jsonl')
NIKKEI_CSV = 'https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_daily_en.csv'
BOJ_API = 'https://www.stat-search.boj.or.jp/api/v1'
BOJ_SERIES_CACHE = os.path.join(DAILY_DIR, 'boj_series.json')
FX = (('usdjpy', 'JPY=X', 'USD/JPY'), ('eurjpy', 'EURJPY=X', 'EUR/JPY'),
      ('krw_per_100jpy', 'JPYKRW=X', '100엔당 원'))
TOPIX_ETF = ('1306', 'TOPIX ETF(1306)')
CUT = '16:30'
MISMATCH_PCT = 0.05


class AlreadyPublished(Exception):
    pass


def _why(e):
    return f'{type(e).__name__}: {str(e)[:160]}'


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def jgb_text(raw):
    """MOF CSV 는 바이트로 온다(cp932). 문자열이면 그대로."""
    return WS.decode_cp932(raw) if isinstance(raw, bytes) else raw


def _published_history(root):
    """발행 이력 {세션: 스냅샷 요약}. 분모의 첫 원천이다 — 발행 당시 숫자가 다음 날의 기준이다."""
    out = {}
    path = os.path.join(root, HISTORY)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    out[row['session']] = row
    return out


def _prev_snapshot(root, prev):
    for sub in ('', 'candidate'):
        path = os.path.join(root, DAILY_DIR, sub, f'{prev}.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as fh:
                return json.load(fh)
    return None


def _instrument(fetch, ticker, session, prev, hist_value, status, key):
    """ETF·개별주 한 종목 → {value, chg_pct, denom, ok, why}."""
    try:
        q = fetch.quote(ticker)
        value = PR.same_session_price(q.get('last'), q.get('bar_date'), session)
    except Exception as e:
        status[key] = _why(e)
        return {'value': None, 'chg_pct': None, 'denom': None, 'ok': False, 'why': '시세 수집 실패'}
    if value is None:
        return {'value': None, 'chg_pct': None, 'denom': None, 'ok': False,
                'why': f'세션 {session} 봉 없음 — 전날 값일 수 있다'}
    denom = {'date': prev, 'value': hist_value, 'source': 'published'} if _finite(hist_value) else None
    if denom is None:
        try:
            denom = PR.denominator(fetch.daily_closes(ticker), prev)
        except Exception as e:
            status[key] = _why(e)
    if denom is None:
        return {'value': value, 'chg_pct': None, 'denom': None, 'ok': True, 'why': '직전 세션 분모 없음'}
    raw = PR.change(value, denom)
    if raw is not None and abs(raw) > PR.JUMP_PCT:
        try:
            splits = fetch.splits(ticker)
        except Exception as e:
            status[key] = _why(e)
            splits = []
        jump = PR.verify_jump(value, denom, splits, session)
        if not jump['ok']:
            return {'value': None, 'chg_pct': None, 'denom': denom, 'ok': False, 'why': jump['why']}
        denom = dict(denom, value=jump['adjusted_denom'])
    return {'value': value, 'chg_pct': PR.change(value, denom), 'denom': denom, 'ok': True, 'why': None}


def _nikkei(fetch, session, prev, status):
    try:
        text = fetch.nikkei_csv()
        status['nikkei_csv'] = 'ok'
    except Exception as e:
        status['nikkei_csv'] = _why(e)
        status['nikkei'] = '공식 CSV 수집 실패'
        return {'value': None, 'ok': False, 'why': '공식 CSV 수집 실패', 'chg_pct': None, 'denom': None}
    official = PR.nikkei_official(text, session)
    try:
        q = fetch.quote('^N225')
        fast = q.get('last')
    except Exception as e:
        status['nikkei_quote'] = _why(e)
        fast = None
    got = PR.nikkei_close(official, fast)
    status['nikkei'] = 'ok' if got['ok'] else got['why']
    prev_v = PR.nikkei_official(text, prev)
    denom = {'date': prev, 'value': prev_v, 'source': 'nikkei_official'} if prev_v else None
    got.update(denom=denom, chg_pct=PR.change(got['value'], denom) if got['ok'] else None,
               source='Nikkei Inc. official close')
    return got


def _fx(fetch, session, prev, status):
    out = {}
    for key, ticker, label in FX:
        try:
            bars = fetch.fx_bars(ticker)
        except Exception as e:
            status['fx'] = _why(e)
            return {}
        now, before = PR.fx_cut(bars, session, CUT), PR.fx_cut(bars, prev, CUT)
        if now is None:
            continue
        mult = 100 if key == 'krw_per_100jpy' else 1
        value = round(now['value'] * mult, 4)
        prev_v = round(before['value'] * mult, 4) if before else None
        out[key] = dict(now, label=label, value=value, multiplier=mult, prev_value=prev_v,
                        prev_period=prev if before else None,
                        chg_pct=PR.change(value, {'value': prev_v}) if prev_v else None)
    status.setdefault('fx', 'ok')
    return out


def _rates(fetch, session, prev, status):
    try:
        jgb = RT.jgb_block(WS.parse_jgb_csv(jgb_text(fetch.jgb_csv())), prev)
        status['jgb'] = 'ok' if 'why' not in jgb else jgb['why']
    except Exception as e:
        status['jgb'] = _why(e)
        jgb = {}
    try:
        call = RT.call_rate(fetch.boj('FM01', 'STRDCLUCON'), session)
        status['call_rate'] = 'ok' if call else '최신 관측이 3거래일보다 오래됐다'
    except Exception as e:
        status['call_rate'] = _why(e)
        call = None
    return jgb, call


def _macro(fetch, events_today, prev_snap, status):
    values = {}
    try:
        codes = fetch.boj_codes()
    except Exception as e:
        status['macro'] = _why(e)
        return [], {}
    for key, (db, code) in codes.items():
        try:
            got = RT.boj_values(fetch.boj(db, code))
            if got:
                values[key] = got[0]
        except Exception as e:
            status[f'macro_{key}'] = _why(e)
    status.setdefault('macro', 'ok')
    prev_periods = (prev_snap or {}).get('macro_periods') or {}
    items = MAC.macro_items(events_today, values, events_today[0]['date'] if events_today else None,
                            prev_periods) if events_today else []
    periods = dict(prev_periods)
    periods.update(MAC.latest_periods(values))
    return items, periods


def collect(session, prev, fetch, now, root='.', calendar=None, scheduled_at=None):
    if os.path.exists(os.path.join(root, DAILY_DIR, f'{session}.json')):
        raise AlreadyPublished(f'{session} 은 이미 발행됐다 — 수집 후보를 덮지 않는다')
    cal = calendar if calendar is not None else CAL.load(os.path.join(root, CAL.PATH))
    status = {}
    hist = _published_history(root).get(prev) or {}
    hist_prices = hist.get('prices') or {}
    prev_snap = _prev_snapshot(root, prev)

    nikkei = _nikkei(fetch, session, prev, status)
    topix = _instrument(fetch, f'{TOPIX_ETF[0]}.T', session, prev, hist_prices.get(TOPIX_ETF[0]),
                        status, 'topix_etf')
    sectors = []
    for code, name in MOV.SECTOR17.items():
        row = _instrument(fetch, f'{code}.T', session, prev, hist_prices.get(code), status, f'sector_{code}')
        sectors.append(dict(row, code=code, name_ko=name))
    rows = []
    for code, name, sector in MOV.UNIVERSE:
        r = _instrument(fetch, f'{code}.T', session, prev, hist_prices.get(code), status, f'stock_{code}')
        if r['ok'] and r['chg_pct'] is not None:
            rows.append({'code': code, 'name': name, 'change_pct': r['chg_pct'], 'close': r['value']})
    jgb, call = _rates(fetch, session, prev, status)
    today = CAL.today_events(cal, session)
    macro, periods = _macro(fetch, today, prev_snap, status)
    snap = {
        'session': session, 'prev_session': prev, 'cut': CUT,
        'scheduled_at': scheduled_at, 'ran_at': now.astimezone(timezone.utc).isoformat(),
        'complete': bool(nikkei['ok']), 'fetch_status': status,
        'indices': {'nikkei': nikkei, 'topix_etf': dict(topix, label=TOPIX_ETF[1])},
        'sectors': sectors, 'movers': MOV.build(session, rows),
        'jgb': jgb, 'call_rate': call, 'fx': _fx(fetch, session, prev, status),
        'macro': macro, 'macro_periods': periods,
        'calendar': {'version': CAL.version(cal), 'today': today,
                     'event_day': CAL.event_day(cal, session), 'upcoming': CAL.upcoming(cal, session)},
        'news_file': f'japan/data/news/daily/{session}.json',
    }
    path = os.path.join(root, DAILY_DIR, 'candidate', f'{session}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    return snap


def reconcile(prev_published, later_closes):
    """발행된 어제 숫자 ↔ 나중에 채워진 일봉. 발행 스냅샷은 고치지 않는다 — 기록만 남긴다."""
    out = []
    s = prev_published.get('session')
    pairs = [('indices.nikkei', '^N225', (prev_published.get('indices') or {}).get('nikkei', {}).get('value'))]
    for row in prev_published.get('sectors') or []:
        pairs.append((f'sectors.{row["code"]}', f'{row["code"]}.T', row.get('value')))
    for field, ticker, published in pairs:
        later = next((v for d, v in later_closes.get(ticker) or [] if d == s), None)
        if not _finite(published) or not _finite(later):
            continue
        diff = abs(later / published - 1) * 100
        if diff == 0:
            continue
        out.append({'session': s, 'field': field, 'published': published, 'later': later,
                    'diff_pct': round(diff, 4), 'kind': 'rounding' if diff <= MISMATCH_PCT else 'mismatch'})
    return out


class Live:
    """실제 네트워크. Actions 에서만 쓴다."""

    def __init__(self, root='.'):
        self.ctx = WS.ssl_context()
        self.root = root
        self.calls = 0

    def nikkei_csv(self):
        return WS.http_get(NIKKEI_CSV, self.ctx)

    def quote(self, ticker):
        import yfinance as yf
        t = yf.Ticker(ticker)
        last = t.fast_info['lastPrice']
        bars = t.history(period='1d', interval='5m')
        bar_date = bars.index[-1].tz_convert('Asia/Tokyo').date().isoformat() if len(bars) else None
        return {'last': float(last) if last is not None else None, 'bar_date': bar_date}

    def daily_closes(self, ticker):
        return WS.fetch_closes(ticker, period='1mo')

    def splits(self, ticker):
        import yfinance as yf
        s = yf.Ticker(ticker).splits
        return [[i.date().isoformat(), float(v)] for i, v in s.items()] if s is not None else []

    def fx_bars(self, ticker):
        import yfinance as yf
        h = yf.Ticker(ticker).history(period='5d', interval='5m')
        return [(i.isoformat(), float(v)) for i, v in h['Close'].items()]

    def jgb_csv(self):
        return WS.http_get(WS.JGB_MONTH, self.ctx)

    def _boj_get(self, path):
        self.calls += 1
        if self.calls > 10:
            raise RuntimeError('BOJ API 호출 상한(실행당 10회) 초과')
        return json.loads(WS.http_get(f'{BOJ_API}/{path}', self.ctx))

    def boj(self, db, code):
        start = (datetime.now(timezone.utc) - timedelta(days=430)).strftime('%Y%m')
        return self._boj_get(f'getDataCode?format=json&lang=en&db={db}&code={code}&startDate={start}')

    def boj_codes(self):
        """시리즈 코드는 이름으로 찾되 7일 동안 캐시한다 — 메타데이터는 DB 하나에 수만 행이다."""
        path = os.path.join(self.root, BOJ_SERIES_CACHE)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as fh:
                cache = json.load(fh)
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cache['resolved_at'])
            if age < timedelta(days=7) and set(cache['codes']) == set(MAC.SERIES):
                return {k: tuple(v) for k, v in cache['codes'].items()}
        codes = {}
        for key, spec in MAC.SERIES.items():
            meta = self._boj_get(f'getMetadata?format=json&lang=en&db={spec["db"]}')
            code = MAC.resolve_latest_base(meta, spec['pattern'])
            if code:
                codes[key] = (spec['db'], code)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'resolved_at': datetime.now(timezone.utc).isoformat(), 'codes': codes}, fh,
                      ensure_ascii=False, indent=1)
        return codes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--prev', required=True)
    ap.add_argument('--root', default='.')
    ap.add_argument('--scheduled-at', default=None)
    args = ap.parse_args(argv)
    try:
        snap = collect(args.session, args.prev, Live(args.root), datetime.now(timezone.utc),
                       root=args.root, scheduled_at=args.scheduled_at)
    except AlreadyPublished as e:
        print(e)
        return 0
    bad = {k: v for k, v in snap['fetch_status'].items() if v != 'ok'}
    print(f'{args.session} complete={snap["complete"]} 닛케이={snap["indices"]["nikkei"]["value"]} '
          f'실패 {len(bad)}건')
    for k, v in bad.items():
        print(f'  {k}: {v}', file=sys.stderr)
    prev = os.path.join(args.root, DAILY_DIR, f'{args.prev}.json')
    if os.path.exists(prev):
        with open(prev, encoding='utf-8') as fh:
            pub = json.load(fh)
        later = {'^N225': [[args.prev, PR.nikkei_official(Live(args.root).nikkei_csv(), args.prev)]]}
        for row in pub.get('sectors') or []:
            try:
                later[f'{row["code"]}.T'] = WS.fetch_closes(f'{row["code"]}.T', period='1mo')
            except Exception:
                pass
        checks = reconcile(pub, later)
        if checks:
            with open(os.path.join(args.root, DAILY_DIR, 'checks.jsonl'), 'a', encoding='utf-8') as fh:
                for c in checks:
                    fh.write(json.dumps(c, ensure_ascii=False) + '\n')
    return 0 if snap['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
