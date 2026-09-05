#!/usr/bin/env python3
"""중국 학습 리포트의 수집기 — 릴리스 원문·헤드라인 manifest·시세.

  python3 scripts/collect_china_data.py --outdir china/data

세 가지를 남긴다.

  releases/<key>.txt   기관 릴리스 **원문 덤프**. 파싱하지 않는다 — 읽는 일은 에이전트 몫.
  releases/index.json  발견·성공·실패 원장. 실패를 버리지 않는 것이 핵심이다.
  manifest.json        헤드라인 지표만 뽑은 것. 발행 게이트가 수치를 여기 묶는다.
  markets.json         시세. 시황 상한 안에서만 쓰인다.

**이 수집기는 `curriculum_state.json` 을 건드리지 않는다.** 상태는 발행이 소유한다 —
수집과 발행이 같은 파일을 쓰면 실패한 발행 뒤에 진도만 앞서 나간다(thesis 와 같은 규율).

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from china import manifest as M      # noqa: E402
from china import releases as R      # noqa: E402

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:                    # pragma: no cover - 러너에 certifi 가 있다
    _SSL = ssl.create_default_context()

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

MARKET_TICKERS = {
    '000001.SS': '상해종합', '000300.SS': 'CSI 300', '399001.SZ': '심천성분',
    '^HSI': '항셍', '^HSCE': '항셍중국기업', 'CNY=X': '달러/위안(역내)',
    'CNH=X': '달러/위안(역외)', 'FXI': 'iShares China Large-Cap',
    'KWEB': 'KraneShares China Internet', 'ASHR': 'Xtrackers CSI 300 A주',
    'HG=F': '구리 선물(근월)', 'TIO=F': '철광석 62% CFR',
}

# FRED 는 중국 월간 지표의 주 소스가 못 된다(CPI 2025-04 중단, GDP 2023-07). 구조
# 지표와 교차검증용으로만 쓴다 — 2026-09-05 생존 확인분.
FRED_SERIES = {
    'QCNPAM770A': 'BIS 민간비금융 신용/GDP',
    'RBCNBIS': 'BIS 실질실효환율',
    'TRESEGCNM052N': '외환보유액(금 제외)',
    'CCRETT01CNM661N': 'CPI 기반 실질실효환율',
    'FORTREASPOS41408': '중국의 미 국채 보유액',
}


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        raw = r.read()
    for enc in ('utf-8', 'gb18030', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace')


def fetch_with_impersonation(url, timeout=25):
    """WAF 가 평범한 요청을 막을 때. US `fetch_releases.py` 와 같은 도구."""
    from curl_cffi import requests as creq
    r = creq.get(url, impersonate='safari', timeout=timeout)
    r.raise_for_status()
    return r.text


def collect_releases(outdir, prev_index):
    reldir = os.path.join(outdir, 'releases')
    os.makedirs(reldir, exist_ok=True)

    try:
        index_html = fetch(R.NBS_INDEX_URL)
    except Exception as exc:
        print(f'  NBS 인덱스 실패: {exc}', file=sys.stderr)
        try:
            index_html = fetch_with_impersonation(R.NBS_INDEX_URL)
        except Exception as exc2:
            print(f'  위장 요청도 실패: {exc2}', file=sys.stderr)
            broken = R.ledger([], {}, {},
                              generated=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            broken['index_ok'] = False
            return broken, {}

    discovered = R.parse_nbs_index(index_html)
    index_ok = not R.index_looks_broken(discovered)
    if not index_ok:
        # 인덱스는 늘 최근 릴리스 십여 건을 싣는다. 0건이면 「조용한 주」가 아니라
        # 인덱스를 못 읽은 것이다 — **경고로 끝내지 않고 원장에 남겨** 게이트가 막는다.
        print('  인덱스에서 릴리스를 하나도 찾지 못했다 — 인덱스가 깨졌다고 본다',
              file=sys.stderr)
    print(f'  발견 {len(discovered)}건')

    fetched, errors, texts = {}, {}, {}
    for rel in discovered:
        key = rel['key']
        path = os.path.join(reldir, f'{key}.txt')
        lang = 'en'
        if not R.should_refetch(prev_index, key, lang):
            if os.path.exists(path):
                texts[key] = open(path, encoding='utf-8').read()
                fetched[key] = (texts[key], lang)
                continue
        try:
            text = R.extract_text(fetch(rel['url']))
        except urllib.error.HTTPError as exc:
            try:
                text = R.extract_text(fetch_with_impersonation(rel['url']))
            except Exception as exc2:
                errors[key] = (getattr(exc, 'code', None), f'{exc}; 위장 실패 {exc2}')
                print(f'  {key}: 실패 ({exc})', file=sys.stderr)
                continue
        except Exception as exc:
            errors[key] = (None, str(exc))
            print(f'  {key}: 실패 ({exc})', file=sys.stderr)
            continue
        open(path, 'w', encoding='utf-8').write(text)
        texts[key] = text
        fetched[key] = (text, lang)
        time.sleep(1)

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    index = R.ledger(discovered, fetched, errors, generated=now)
    index['index_ok'] = index_ok
    return index, texts


def build_manifest(index, texts):
    rels = []
    for row in index['releases']:
        if row['fetch_status'] != 'ok':
            continue
        if row['kind'] not in M.KINDS:
            continue            # 아직 헤드라인을 정의하지 않은 릴리스 — 덤프만 남는다
        rels.append({'key': row['key'], 'kind': row['kind'],
                     'period': row['period'], 'text': texts.get(row['key'], '')})
    return M.build(rels)


def collect_markets():
    import yfinance as yf
    out = {}
    data = yf.download(list(MARKET_TICKERS), period='1y', interval='1d',
                       progress=False, auto_adjust=False, group_by='ticker',
                       threads=True)
    for ticker, label in MARKET_TICKERS.items():
        try:
            close = data[ticker]['Close'].dropna()
            if close.empty:
                continue
            last = float(close.iloc[-1])
            row = {'label': label, 'last': round(last, 4),
                   'date': str(close.index[-1].date())}
            for name, back in (('d1', 1), ('w1', 5), ('m1', 21), ('ytd', None)):
                if back is None:
                    # 연초 대비는 **전년 마지막 종가** 기준이다. 올해 첫 종가를 쓰면
                    # 1월 1거래일의 등락이 통째로 빠져 과소 계산된다.
                    year = close.index[-1].year
                    prior = close[close.index.year < year]
                    prev = float(prior.iloc[-1]) if len(prior) else None
                elif len(close) > back:
                    prev = float(close.iloc[-1 - back])
                else:
                    prev = None
                row[f'{name}_pct'] = (round((last / prev - 1) * 100, 2)
                                      if prev else None)
            out[ticker] = row
        except Exception as exc:
            print(f'  {ticker}: {exc}', file=sys.stderr)
    return out


def collect_fred():
    import csv
    import io
    out = {}
    for sid, label in FRED_SERIES.items():
        try:
            body = fetch(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}')
            rows = [r for r in list(csv.reader(io.StringIO(body)))[1:]
                    if r and len(r) > 1 and r[1] not in ('.', '')]
            if rows:
                out[sid] = {'label': label, 'date': rows[-1][0],
                            'value': float(rows[-1][1])}
        except Exception as exc:
            print(f'  {sid}: {exc}', file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='china/data')
    ap.add_argument('--force', action='store_true',
                    help='이미 받은 릴리스도 다시 받는다')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    idx_path = os.path.join(args.outdir, 'releases', 'index.json')
    prev = json.load(open(idx_path)) if os.path.exists(idx_path) else {'releases': []}

    print('릴리스 수집...')
    index, texts = collect_releases(args.outdir,
                                    {'releases': []} if args.force else prev)
    os.makedirs(os.path.dirname(idx_path), exist_ok=True)
    json.dump(index, open(idx_path, 'w'), ensure_ascii=False, indent=1)

    print('헤드라인 manifest...')
    man = build_manifest(index, texts)
    json.dump(man, open(os.path.join(args.outdir, 'manifest.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'  지표 {len(man)}종')

    print('시세...')
    markets = {'generated': index['generated'], 'quotes': collect_markets(),
               'structural': collect_fred()}
    json.dump(markets, open(os.path.join(args.outdir, 'markets.json'), 'w'),
              ensure_ascii=False, indent=1)

    failed = [f'{r["key"]}({r["fetch_status"]})' for r in index['releases']
              if r['tier'] == 1 and r['fetch_status'] != 'ok']
    if failed:
        print(f'경고: tier 1 릴리스 실패 {len(failed)}건 — {", ".join(failed)}',
              file=sys.stderr)
    print('완료.')


if __name__ == '__main__':
    main()
