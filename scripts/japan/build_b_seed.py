#!/usr/bin/env python3
"""일본 일간 B 씨앗 `japan/data/history/jp_b_seed.json` 을 한 번 만든다 (로컬, 네트워크, 2026-11-28).

B(N거래일 수익률·평소 대비·JGB N일 변화)는 과거 값을 레포 파일에서만 읽는다. v2 이전 발행본에는 TOPIX 가 없고
(ETF 뿐) JGB 도 MOF 폴백 날이 있어, 2026-08-20 ~ 2026-11-18 구간만 원천에서 받아 고정한다 — 씨앗은 굴러가지
않는다(그 뒤는 발행본·후보가 채운다).

원천: TOPIX 네이버 `.TOPX` 일봉(JPX 발행값과 6+58일 차 0), 닛케이 공식 CSV, JGB 네이버 지표물 일봉(발행값 68칸 일치).
쓰기 전에 거래일 달력과 맞추고 레포의 발행값·후보·다음 세션 분모와 겹치는 날을 전부 대조한다 — **하나라도 다르거나
거래일이 빠지면 파일을 쓰지 않는다.** 비교는 씨앗 구간 밖(11/19 이후)의 레포 값까지 한다.

    python3 scripts/japan/build_b_seed.py [--check-only]
"""
import argparse
import csv
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import weekly_sources as WS  # noqa: E402
from japan import daily_b as B  # noqa: E402
from japan import daily_rates as RT  # noqa: E402

START, END = '2026-08-20', '2026-11-18'
NIKKEI_CSV = 'https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_daily_en.csv'
NAVER_TOPIX = 'https://api.stock.naver.com/chart/foreign/index/.TOPX/day?startDateTime={s}0000&endDateTime={e}0000'
NAVER_PRICES = 'https://m.stock.naver.com/front-api/marketIndex/prices'


def trading_days(start, end, hol):
    d, out = date.fromisoformat(start), []
    while d.isoformat() <= end:
        if B.is_trading(d, hol):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def parse_topix(payload):
    out = {}
    for r in payload:
        d = str(r['localDate'])
        out[f'{d[:4]}-{d[4:6]}-{d[6:]}'] = float(r['closePrice'])
    return out


def parse_nikkei(text):
    out = {}
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) >= 2 and len(rec[0].strip()) == 10 and rec[0][4] == '/':
            try:
                out[rec[0].strip().replace('/', '-')] = float(rec[1])
            except ValueError:
                pass
    return out


def parse_jgb(pages):
    """일봉 `localTradedAt` 의 도쿄 날짜 → 종가(float, 발행값과 같은 변환 `float(closePrice)`)."""
    out = {}
    for page in pages:
        for r in page.get('result') or []:
            day = datetime.fromisoformat(str(r['localTradedAt'])).date().isoformat()
            out.setdefault(day, float(str(r['closePrice']).replace(',', '')))
    return out


def fetch(ctx):
    end = (date.fromisoformat('2026-11-28')).strftime('%Y%m%d')
    topix = parse_topix(json.loads(WS.http_get(NAVER_TOPIX.format(s='20260801', e=end), ctx)))
    raw = WS.http_get(NIKKEI_CSV, ctx)
    nikkei = parse_nikkei(raw.decode('cp932', 'replace') if isinstance(raw, bytes) else raw)
    jgb = {}
    for tenor, code in RT.NAVER_CODES.items():
        pages = [json.loads(WS.http_get(f'{NAVER_PRICES}?category=bond&reutersCode={quote(code, safe="")}'
                                        f'&page={p}&pageSize=60', ctx)) for p in (1, 2)]
        jgb[tenor] = parse_jgb(pages)
    return topix, nikkei, jgb


def repo_values(root, hol, days):
    """레포가 아는 값 {(세션, 필드): 값} — 발행본·적격 후보·다음 세션 분모. History 와 같은 읽기 규칙."""
    h = B.History(root, '9999-12-31', None, hol, seed={})
    out = {}
    fields = ['topix', 'nikkei'] + [f'jgb.{t}' for t in RT.TENORS]
    for s in days:
        for f in fields:
            v, src = h.value(s, f)
            if v is not None:
                out[(s, f)] = (v, src)
    return out, h.mismatch


def build(root, topix, nikkei, jgb, hol, today_iso):
    errs = []
    seed_days = trading_days(START, END, hol)
    for name, series in (('topix', topix), ('nikkei', nikkei)):
        miss = [d for d in seed_days if d not in series]
        if miss:
            errs.append(f'{name}: 거래일 {len(miss)}개 없음 — {miss[:5]}')
    for t, series in jgb.items():
        miss = [d for d in seed_days if d not in series]
        if miss:
            errs.append(f'jgb.{t}: 거래일 {len(miss)}개 없음 — {miss[:5]}')
    check_days = trading_days('2026-10-01', today_iso, hol)
    known, mism = repo_values(root, hol, check_days)
    errs += mism
    n = 0
    for (s, f), (v, src) in sorted(known.items()):
        got = topix.get(s) if f == 'topix' else nikkei.get(s) if f == 'nikkei' else jgb[f[4:]].get(s)
        if got is None:
            continue
        n += 1
        if B._round_cmp(f, got) != B._round_cmp(f, v):
            errs.append(f'{s} {f}: 레포({src}) {v} ≠ 원천 {got}')
    seed = {'version': 1, 'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'range': [START, END],
            'sources': {'topix': 'naver .TOPX day (matches JPX)', 'nikkei': 'Nikkei official daily CSV',
                        'jgb': 'naver JP{2,5,10,30}YT=RR daily close'},
            'topix': {d: topix[d] for d in seed_days if d in topix},
            'nikkei': {d: nikkei[d] for d in seed_days if d in nikkei},
            'jgb': {t: {d: s[d] for d in seed_days if d in s} for t, s in jgb.items()}}
    return seed, errs, n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args(argv)
    with open(os.path.join(args.root, 'data', 'market_holidays.json'), encoding='utf-8') as fh:
        hol, _ = B.calendar(json.load(fh))
    topix, nikkei, jgb = fetch(WS.ssl_context())
    seed, errs, n = build(args.root, topix, nikkei, jgb, hol, date.today().isoformat())
    print(f'겹치는 레포 값 {n}개 대조, 문제 {len(errs)}건')
    for e in errs:
        print(f'  ! {e}')
    if errs:
        return 1
    if not args.check_only:
        path = os.path.join(args.root, B.SEED)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(seed, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write('\n')
        print(f'{path} — TOPIX {len(seed["topix"])} · 닛케이 {len(seed["nikkei"])} · '
              + ' · '.join(f'{t} {len(v)}' for t, v in seed['jgb'].items()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
