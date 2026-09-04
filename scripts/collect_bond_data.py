#!/usr/bin/env python3
"""글로벌 채권 EMP 리포트 데이터 수집 — GitHub Actions 에서 돈다.

  python scripts/collect_bond_data.py [--outdir bond/data] [--backfill-days 520]

산출:
  bond/data/bond_market.json           오늘의 6축 원자료 (행마다 date·source)
  bond/data/bond_metrics.json          파생 계산 — 「어제 대비」와 트리거 재료
  bond/data/history/bond_market.jsonl  append-only 원장
  bond/data/yield_curves.png           US·DE·JP 커브

기준일이 소스마다 다르다는 것이 이 수집의 상수다. report_date 는 **미국 국채 커브의
마지막 관측일**로 잡고, 다른 축은 자기 날짜를 달고 따라온다. 하나로 뭉개면 「금리
-10bp 인데 HY +40bp」 같은 비교가 하루 어긋난 채 조용히 틀린다.
"""

import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bond import history as ledger          # noqa: E402
from bond import metrics as metrics_mod     # noqa: E402
from bond import sources as src             # noqa: E402

FX_TICKERS = {'DXY': 'DX-Y.NYB', 'EURUSD': 'EURUSD=X',
              'USDJPY': 'USDJPY=X', 'USDKRW': 'USDKRW=X'}


def retry(fn, tries=3, wait=2, label=''):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:                       # noqa: BLE001
            if i == tries - 1:
                print(f'  ! {label}: {type(e).__name__} {e}')
                return None
            time.sleep(wait * (i + 1))


def _row(pairs, name, source):
    if not pairs:
        return None
    d, v = pairs[-1]
    return {'level': v, 'date': d, 'source': source, 'tenor': name}


# 원장 그룹 -> (bond_market.json 노드 이름, 출처 표기)
GROUPS = {
    'us': ('us_curve', 'FRED'), 'us_spot': ('us_curve', 'Yahoo'),
    'us_fred': ('us_curve_fred', 'FRED'),
    'real': ('real_yields', 'FRED'),
    'bei': ('breakeven', 'FRED'), 'de': ('de_curve', 'Bundesbank'),
    'ea': ('ea_curve', 'ECB'), 'jp': ('jp_curve', 'MOF Japan'),
    'gb': ('gb_curve', 'BOE'), 'kr': ('kr_curve', 'ECOS 한국은행'),
    'us_naver': ('us_curve', 'Naver'), 'gb_naver': ('gb_curve', 'Naver'),
    'kr_naver': ('kr_curve', 'Naver'),
    'misc': ('misc', 'FRED'),
}


# 같은 날짜를 두 소스가 줄 때 누가 이기는지 못 박는다. 사전 순서에 맡기면 만기마다
# 출처가 갈려 「전 만기 동일 기준일」이 무의미해진다. 숫자가 클수록 우선.
SOURCE_PRIORITY = {'Naver': 3, 'Yahoo': 2}


def rows_at(hist, cutoff, groups=None, priority=None):
    """각 계열에서 cutoff 이하의 마지막 관측으로 행을 만든다.

    소스마다 게시 시차가 달라(분데스방크 T-0, ECB·FRED BAML T-1) 기준일 뒤의 값을
    가진 계열이 섞인다. 잘라 버리면 그 축이 통째로 사라지고(2026-08-31 실측: 독일
    커브가 08-28 이라 전부 탈락했다), 그대로 두면 하루 어긋난 값이 실린다.
    답은 **기준일 이하의 마지막 값**이고, 그 값의 실제 날짜를 행에 남기는 것이다.
    """
    groups = GROUPS if groups is None else groups
    priority = SOURCE_PRIORITY if priority is None else priority
    out = {}
    for group, series_by_tenor in hist.items():
        node_key, source = groups.get(group, (group, ''))
        node = out.setdefault(node_key, {})
        for tenor, pairs in series_by_tenor.items():
            # 소스가 오름차순으로 준다고 믿지 않는다. 내림차순이 한 번 섞이면
            # 첫 행에서 break 해 그 축이 통째로 비어 버린다.
            pick = None
            for d, v in sorted(pairs, key=lambda x: x[0]):
                if cutoff is None or d <= cutoff:
                    pick = (d, v)
                else:
                    break
            if pick:
                # 같은 만기를 두 소스가 주면 **더 최신 관측이 이긴다.** 야후 스팟이
                # FRED 보다 하루 이상 앞서므로 실무상 야후가 FRED 를 이긴다.
                # 날짜가 같으면 SOURCE_PRIORITY 로 가른다 — 신선도가 먼저고,
                # 우선순위는 동률을 깨는 데만 쓴다.
                cur = node.get(tenor)
                if cur:
                    if cur['date'] > pick[0]:
                        continue
                    if cur['date'] == pick[0] and \
                            priority.get(cur['source'], 0) >= priority.get(source, 0):
                        continue
                node[tenor] = {'level': pick[1], 'date': pick[0],
                               'source': source, 'tenor': tenor}
    return out


def align_decomposition(rates, hist, cutoff):
    """명목·실질·기대인플레를 **만기별 공통 날짜**로 다시 맞춘다.

    FRED 가 DGS·DFII·T10YIE 를 서로 다른 시차로 게시해서(2026-09-01 실측: 명목·실질은
    08-27, 기대인플레는 08-28), 각 계열의 마지막 값을 그냥 쓰면 항등식이 안 닫힌다.
    US 브리프가 2026-08-18 에 겪은 것과 같은 문제이고, 답도 같다 —
    **세 계열이 모두 값을 가진 가장 최근 날짜**로 내린다. 공통 날짜가 없으면 비운다.
    """
    for tenor in ('5Y', '10Y', '30Y'):
        legs = {'us_curve_fred': hist['us_fred'].get(tenor),
                'real_yields': hist['real'].get(tenor),
                'breakeven': hist['bei'].get(tenor)}
        if not all(legs.values()):
            for node in ('us_curve_fred', 'real_yields', 'breakeven'):
                (rates.get(node) or {}).pop(tenor, None)
            continue
        maps = {k: {d: v for d, v in s if d <= cutoff} for k, s in legs.items()}
        common = set.intersection(*(set(m) for m in maps.values()))
        if not common:
            for node in ('us_curve_fred', 'real_yields', 'breakeven'):
                (rates.get(node) or {}).pop(tenor, None)
            continue
        # **공통 날짜를 둘** 뽑는다. 하나만 뽑으면 수준은 정렬되지만 변화량은 각 계열의
        # 직전 관측에서 따로 빼게 되고, 그러면 명목 +0.0 = 실질 +0.0 + 기대 +2.0 처럼
        # 항등식이 안 닫힌다(2026-09-01 codex 검토에서 실증).
        ordered = sorted(common, reverse=True)
        d = ordered[0]
        d_prev = ordered[1] if len(ordered) > 1 else None
        for node, mm in maps.items():
            row = {'level': mm[d], 'date': d, 'source': 'FRED', 'tenor': tenor}
            if d_prev is not None:
                row['prev_level'] = mm[d_prev]
                row['prev_date'] = d_prev
            rates.setdefault(node, {})[tenor] = row


def collect_rates():
    hist = {'us': {}, 'us_spot': {}, 'us_fred': {}, 'real': {}, 'bei': {},
            'de': {}, 'ea': {}, 'jp': {}, 'gb': {}, 'kr': {}, 'misc': {},
            'us_naver': {}, 'gb_naver': {}, 'kr_naver': {}}

    print('· FRED 미국 커브·실질·기대인플레')
    for tenor, sid in src.FRED_US_CURVE.items():
        s = retry(lambda sid=sid: src.fred_series(sid), label=sid)
        if s:
            hist['us'][tenor] = s
            # 야후 스팟이 발행값을 덮어쓰므로, 분해용 FRED 원본을 따로 남긴다
            hist['us_fred'][tenor] = s
    for tenor, sid in src.FRED_REAL.items():
        s = retry(lambda sid=sid: src.fred_series(sid), label=sid)
        if s:
            hist['real'][tenor] = s
    for tenor, sid in src.FRED_BEI.items():
        s = retry(lambda sid=sid: src.fred_series(sid), label=sid)
        if s:
            hist['bei'][tenor] = s
    for name, sid in src.FRED_MISC.items():
        s = retry(lambda sid=sid: src.fred_series(sid), label=sid)
        if s:
            hist['misc'][name] = s

    print('· 야후 스팟 국채지수 (발행용 확정값)')
    spot = retry(src.yahoo_yield_series, label='Yahoo yields') or {}
    for tenor, series in spot.items():
        hist['us_spot'][tenor] = series

    print('· Bundesbank 독일 커브')
    for tenor, key in src.BBK_DE.items():
        s = retry(lambda key=key: src.bundesbank_series(key), label=f'BBK {tenor}')
        if s:
            hist['de'][tenor] = s

    print('· ECB 유로존 AAA 커브')
    for tenor in ('2Y', '5Y', '10Y', '30Y'):
        s = retry(lambda t=tenor: src.ecb_curve(t, 520), label=f'ECB {tenor}')
        if s:
            hist['ea'][tenor] = s

    print('· 일본 MOF JGB')
    jgb = retry(src.mof_jgb, label='MOF') or []
    for tenor in ('2Y', '5Y', '10Y', '20Y', '30Y', '40Y'):
        s = [(dd, vv[tenor]) for dd, vv in jgb if tenor in vv]
        if s:
            hist['jp'][tenor] = s

    print('· BOE 길트 (T-1 게시)')
    # BOE IADB 는 하루 늦게 게시한다(FRED 크레딧과 같다). 「들쭉날쭉」이 아니라
    # 구조적 시차이므로 stale 로 나가는 것이 정상이고, 실패는 재시도로 흡수한다.
    gilts = retry(src.boe_gilts, tries=4, wait=3, label='BOE') or []
    for tenor in ('5Y', '10Y', '20Y'):
        s = [(dd, vv[tenor]) for dd, vv in gilts if tenor in vv]
        if s:
            hist['gb'][tenor] = s

    print('· ECOS 국고채')
    for tenor, item in src.ECOS_KTB.items():
        s = src.ecos_series(item)
        if s:
            hist['kr'][tenor] = s

    # 네이버 국채 종가 — 미국 2Y(FRED T-1), 길트(BOE T-5), 한국(ECOS 두 점)이
    # 목적이다. 비-코어라 실패해도 그 만기만 빠지고 기존 소스가 그대로 남는다.
    for nation, codes in src.NAVER_BOND.items():
        print(f'· 네이버 국채 종가 ({nation})')
        for tenor, code in codes.items():
            s = retry(lambda c=code: src.naver_bond_series(c), label=f'Naver {code}')
            if s:
                hist[f'{nation}_naver'][tenor] = s
    return hist


def collect_credit():
    hist = {}
    print('· FRED BAML 크레딧 OAS')
    for name, sid in src.FRED_CREDIT.items():
        s = retry(lambda sid=sid: src.fred_series(sid), label=sid)
        if s:
            hist[name] = s
    return hist


def collect_market_side():
    import yfinance as yf
    tickers = src.UNIVERSE + list(FX_TICKERS.values()) + ['^MOVE']
    df = yf.download(tickers, period='2y', progress=False, auto_adjust=False,
                     threads=False)['Close']
    return df.dropna(how='all')


def build(outdir, backfill_days, forced_date=None):
    os.makedirs(os.path.join(outdir, 'history'), exist_ok=True)
    ledger_path = os.path.join(outdir, 'history', 'bond_market.jsonl')

    rate_hist = collect_rates()
    credit_hist = collect_credit()

    print('· Yahoo ETF·FX·MOVE')
    px = collect_market_side()

    print('· iShares 상품 특성')
    chars = retry(src.ishares_characteristics, label='iShares') or {}

    # 기준일 = **미국 채권 세션이 실제로 닫힌 마지막 날**. 최댓값을 쓰면 FX 가 만든
    # 주말 행이나 종가가 아직 안 채워진 빈 봉이 기준일이 된다(2026-08-31 실측: 야후가
    # 08-28 봉을 만들어 두고 종가는 전 종목 null 로 냈다). 앵커는 AGG 다 — 미국 종합
    # 채권 ETF 라 이게 닫혔으면 그날 채권시장은 닫힌 것이다.
    anchor = 'AGG' if 'AGG' in px.columns else (src.UNIVERSE[0])
    anchor_s = px[anchor].dropna() if anchor in px.columns else px.iloc[0:0]
    session = str(anchor_s.index[-1].date()) if len(anchor_s) else None
    report_date = forced_date or session
    if report_date and session and report_date > session:
        print(f'  ! 지정한 {report_date} 는 마지막 세션 {session} 보다 뒤다')

    # **기준일은 뒤로 가지 않는다.** 야후가 갓 끝난 세션의 종가를 줬다 뺏었다 하는 일이
    # 실제로 있다(2026-08-31·09-01 실측: 같은 종목의 같은 날 봉이 값 있음 -> null 로 뒤집혔다).
    # 그때 더 낡은 스냅샷으로 덮어쓰면 이미 만든 발행용 데이터가 퇴행한다.
    prev_path = os.path.join(outdir, 'bond_market.json')
    if os.path.exists(prev_path) and not forced_date:
        try:
            prior = json.load(open(prev_path)).get('report_date')
        except Exception:                                  # noqa: BLE001
            prior = None
        if prior and report_date and report_date < prior:
            print(f'  ! 소스가 퇴행했다 — 계산된 기준일 {report_date} < 기존 {prior}. '
                  f'덮어쓰지 않고 종료한다.')
            return None, None
    if report_date:
        px = px[px.index <= report_date]

    rates = rows_at(rate_hist, report_date)
    align_decomposition(rates, rate_hist, report_date)
    credit = {}
    for name, pairs in credit_hist.items():
        pick = None
        for d, v in sorted(pairs, key=lambda x: x[0]):
            if d <= report_date:
                pick = (d, v)
            else:
                break
        if pick:
            credit[name] = {'value': pick[1], 'date': pick[0], 'name_ko':
                            src.CREDIT_KO.get(name, name), 'source': 'FRED (ICE BofA)'}

    etf = {}
    for t in src.UNIVERSE:
        row = dict(chars.get(t) or {'ticker': t})
        if t in px.columns:
            s = px[t].dropna()
            if len(s):
                row['close'] = round(float(s.iloc[-1]), 4)
                row['close_date'] = str(s.index[-1].date())
        etf[t] = row

    fx = {}
    for name, tk in FX_TICKERS.items():
        if tk in px.columns:
            s = px[tk].dropna()
            if len(s):
                fx[name] = {'level': round(float(s.iloc[-1]), 4),
                            'date': str(s.index[-1].date()), 'source': 'Yahoo',
                            'ticker': tk}
    move, move_date = None, None
    if '^MOVE' in px.columns:
        s = px['^MOVE'].dropna()
        if len(s):
            move = round(float(s.iloc[-1]), 2)
            move_date = str(s.index[-1].date())

    missing = [label for label, node in (('us_curve', rates['us_curve']),
                                         ('credit', credit), ('etf', etf), ('fx', fx))
               if not node]
    if not rates['de_curve'] and not rates['jp_curve']:
        missing.append('global_curves')

    market = {
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'report_date': report_date,
        'base_currency': 'USD',
        **rates,
        'credit': credit,
        'fx': fx,
        'vol': {'move': move, 'date': move_date, 'source': 'Yahoo (^MOVE)',
                'stale': bool(move_date) and move_date != report_date},
        'etf': etf,
        'universe': src.UNIVERSE,
        'complete': not missing,
        'missing': missing,
        'notes': {
            'credit_lag': 'ICE BofA OAS 는 FRED 게시가 하루 늦어 주식 종가일보다 T-1 이다',
            'ea_lag': 'ECB 유로존 커브도 T-1 이다',
            'forward_approx': '내재선도금리는 현물 커브 무이표채 근사(연복리)다',
            'flow_est': 'ETF 순유입은 AUM 변화에서 NAV 수익분을 뺀 추정치다',
        },
    }

    print('· 원장 백필')
    dates = set()
    for group in rate_hist.values():
        for s in group.values():
            dates |= {d for d, _ in s}
    for s in credit_hist.values():
        dates |= {d for d, _ in s}
    dates |= {str(d.date()) for d in px.index}
    def _is_weekday(d):
        from datetime import date as _date
        return _date.fromisoformat(d).weekday() < 5

    # 주말은 세션이 아니다. FX 가 토·일 행을 만들고, 나머지 축은 직전 값이 그대로
    # 밀려들어와 「하루 종일 안 움직인 날」로 위장한다 — 기간 집계의 시작·끝이
    # 그 가짜 행에 걸리면 구간 커버리지 계산까지 음수가 된다(2026-08-31 실측).
    dates = sorted(d for d in dates
                   if d and d <= report_date and _is_weekday(d))[-backfill_days:]

    def at(series, d):
        v = None
        for dd, vv in series:
            if dd <= d:
                v = vv
            else:
                break
        return v

    px_map = {str(d.date()): i for i, d in enumerate(px.index)}
    existing = {r.get('report_date') for r in ledger.read(ledger_path)}
    rows_out = [r for r in ledger.read(ledger_path)]
    for d in dates:
        rec = {'report_date': d}
        for grp, node in rate_hist.items():
            got = {t: at(s, d) for t, s in node.items()}
            got = {t: v for t, v in got.items() if v is not None}
            if got:
                rec[grp] = got
        cr = {k: at(s, d) for k, s in credit_hist.items()}
        cr = {k: v for k, v in cr.items() if v is not None}
        if cr:
            rec['credit'] = cr
        if d in px_map:
            rowpx = px.iloc[px_map[d]]
            f = {}
            for name, tk in FX_TICKERS.items():
                if tk in px.columns and rowpx[tk] == rowpx[tk]:
                    f[name] = round(float(rowpx[tk]), 4)
            if f:
                rec['fx'] = f
            if '^MOVE' in px.columns and rowpx['^MOVE'] == rowpx['^MOVE']:
                rec['move'] = round(float(rowpx['^MOVE']), 2)
            e = {t: {'close': round(float(rowpx[t]), 4)} for t in src.UNIVERSE
                 if t in px.columns and rowpx[t] == rowpx[t]}
            if e:
                rec['etf'] = e
        if d not in existing:
            rows_out.append(rec)
    rows_out = [r for r in rows_out if r.get('report_date') != report_date]
    rows_out.append(ledger.market_record(market))
    rows_out.sort(key=lambda r: r['report_date'])
    seen, dedup = set(), []
    for r in rows_out:
        if r['report_date'] in seen:
            continue
        seen.add(r['report_date'])
        dedup.append(r)
    with open(ledger_path, 'w') as f:
        for r in dedup:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    rows = ledger.read(ledger_path)
    print(f'  원장 총 {len(rows)}행 ({rows[0]["report_date"]} ~ {rows[-1]["report_date"]})')

    econ = None
    econ_path = os.path.join('data', 'econ_indicators.json')
    if os.path.exists(econ_path):
        econ = json.load(open(econ_path))
    m = metrics_mod.compute(market, [r for r in rows
                                     if r.get('report_date') != report_date], econ)
    json.dump(market, open(os.path.join(outdir, 'bond_market.json'), 'w'),
              ensure_ascii=False, indent=1)
    json.dump(m, open(os.path.join(outdir, 'bond_metrics.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'✓ report_date={report_date} complete={market["complete"]} missing={missing}')
    return market, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='bond/data')
    ap.add_argument('--backfill-days', type=int, default=520)
    ap.add_argument('--report-date', default=None,
                    help='기준일 고정. 생략하면 AGG 가 닫힌 마지막 세션.')
    a = ap.parse_args()
    try:
        build(a.outdir, a.backfill_days, a.report_date)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
