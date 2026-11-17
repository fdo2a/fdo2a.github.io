#!/usr/bin/env python3
"""수집이 끝난 자료 폴더의 파일마다 해시·크기·수집 상태를 `<datadir>/_collect_status.json` 에 적는다(2026-11-17).

    python3 scripts/stamp_collect.py --datadir data        # US 수집 잡, 커밋 직전
    python3 scripts/stamp_collect.py --datadir kr/data     # KR 수집 잡, versions.py commit 직전

명세 「공통 계약 A」의 마지막 고리다. 수집기는 자기가 쓴 JSON 객체에 `collect` 칸을 넣고, 목록형 파일
(`kr_top_value.json`·`kr_index_etf.json`)은 `common.collect_status.record_sidecar()` 로 이 파일에 적는다.
여기서는 **이 수집 잡이 쓰는 파일**(아래 등록표)마다

    files["<datadir 기준 상대경로>"] = {"present": bool, "sha256": "...", "bytes": N,
                                       "collect_in": "file"|"sidecar"|"producer:<rel>"|"none",
                                       <collect 칸과 같은 모양: status·as_of·…·empty>}

을 만든다. 해시는 「수집 뒤 바뀜」을 가리는 근거다 — 그래서 루틴이 정당하게 고치는 상태 파일
(`macro.json`·`kr_stance.json`·`kr_stance_next.json`)과 매일 쌓이는 원장(`history/`·`weekly/`)은 등록하지 않는다.

* `collect_in: file` — JSON 안의 `collect` 칸을 그대로 옮긴다(두 곳이 다르면 해시가 이미 다르다).
* `sidecar` — 수집기가 이 파일에 직접 적은 상태(목록형). 지난 실행의 기록은 그 파일이 이번에 다시 쓰이지
  않았으면 그대로 그 바이트를 설명한다.
* `producer:<rel>` — 비 JSON 산출물(표 HTML·차트·원문 txt)은 그것을 만든 JSON 의 칸을 옮긴다.
* `none` — 칸이 없다(옛 형식이거나 수집기가 칸을 쓰기 전에 죽었다). 검사 쪽이 「상태 없음」으로 본다.

판정하지 않는다 — 기록만 한다. exit 0(쓰기 실패만 1).
"""
import argparse
import glob
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import collect_status as C  # noqa: E402

COLLECT_KEYS = ('status', 'as_of', 'collected_at', 'source', 'response', 'required_ok', 'missing', 'empty',
                'checked', 'expected', 'detail')

# 이 잡이 쓰는 파일. {D} = 그날 report_date. 값 = 비 JSON 파일의 생산자(JSON) — None 이면 JSON 자체.
REGISTRY = {
    'us': {
        'market_data.json': None, 'econ_indicators.json': None, 'intraday.json': None,
        'macro_eval.json': None, 'macro_metrics.json': None, 'movers.json': None,
        'fund_board.json': None, 'calendar.json': None, 'auctions.json': None,
        'fed/events.json': None, 'liquidity/liquidity.json': None, 'releases/index.json': None,
        'telegram/{D}.json': None,
        # 작성 재료·참고(검사기가 직접 안 읽거나 짝 JSON 으로 대조) — 해시만 남긴다.
        'news/{D}.json': None, 'scorecard.json': None, 'fund_factors.json': None,
        'fomc_dates.json': None, 'fed/seen.json': None, 'fed/statements.json': None,
        'liquidity/state.json': None,
        'sector_performance.html': 'market_data.json', 'yield_curve.png': 'market_data.json',
        'fund_board.html': 'fund_board.json', 'auction_table.html': 'auctions.json',
        'liquidity/table.html': 'liquidity/liquidity.json',
        'liquidity/qra/*.txt': 'liquidity/liquidity.json',
        'releases/*.txt': 'releases/index.json',
        'fed/*.txt': 'fed/events.json',
    },
    'kr': {
        'kr_market_data.json': None, 'kr_session.json': None, 'kr_movers.json': None,
        'kr_fund_view.json': None, 'kr_stance_eval.json': None, 'kr_flows.json': None,
        'kr_intraday.json': None, 'kr_econ.json': None, 'telegram/{D}.json': None,
        'kr_top_value.json': None, 'kr_index_etf.json': None,
        'news/{D}.json': None, 'kr_program.json': None, 'kr_technical.json': None,
        'kr_stock_moves.json': None, 'kr_industry.json': None, 'kr_theme.json': None,
        'kr_flows_intraday.json': None, 'kr_charts_manifest.json': None,
        'kr_sector.html': 'kr_market_data.json', 'kr_fund_view.html': 'kr_fund_view.json',
    },
}
MARKET_FILE = {'us': 'market_data.json', 'kr': 'kr_market_data.json'}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


def _json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def infer_market(datadir):
    return 'kr' if os.path.exists(os.path.join(datadir, MARKET_FILE['kr'])) else 'us'


def expand(datadir, market, report_date):
    """등록표 → [(상대경로, 생산자)]. glob 은 지금 있는 파일로 펼친다(없으면 아무것도 안 남긴다)."""
    out = []
    for pat, producer in REGISTRY[market].items():
        if '{D}' in pat:
            if not report_date:
                continue
            pat = pat.replace('{D}', report_date)
        if '*' in pat:
            for p in sorted(glob.glob(os.path.join(datadir, pat))):
                out.append((os.path.relpath(p, datadir).replace(os.sep, '/'), producer))
        else:
            out.append((pat, producer))
    return out


def _collect_fields(c):
    return {k: c[k] for k in COLLECT_KEYS if isinstance(c, dict) and k in c}


def stamp(datadir, market=None, now=None):
    market = market or infer_market(datadir)
    md = _json(os.path.join(datadir, MARKET_FILE[market])) or {}
    report_date = md.get('report_date')
    old = C.load_status(datadir).get('files') or {}
    files = {}
    rows = expand(datadir, market, report_date)
    for rel, producer in rows:
        path = os.path.join(datadir, rel)
        if not os.path.isfile(path):
            files[rel] = {'present': False}
            continue
        entry = {'present': True, 'sha256': sha256(path), 'bytes': os.path.getsize(path)}
        if producer:
            pc = (_json(os.path.join(datadir, producer)) or {})
            pc = pc.get('collect') if isinstance(pc, dict) else None
            entry.update(_collect_fields(pc))
            entry['collect_in'] = f'producer:{producer}' if pc else 'none'
        elif rel.endswith('.json'):
            body = _json(path)
            if isinstance(body, dict) and isinstance(body.get('collect'), dict):
                entry.update(_collect_fields(body['collect']))
                entry['collect_in'] = 'file'
            elif (old.get(rel) or {}).get('collect_in') == 'sidecar':
                entry.update(_collect_fields(old[rel]))
                entry['collect_in'] = 'sidecar'
            else:
                entry['collect_in'] = 'none'
        else:
            entry['collect_in'] = 'none'
        files[rel] = entry
    book = {'format': C.FORMAT, 'market': market, 'report_date': report_date,
            'stamped_at': C.now_iso(now),
            'run_id': (f"{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
                       if os.environ.get('GITHUB_RUN_ID') else None),
            'files': files}
    C.write_status(datadir, book)
    return book


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', required=True)
    ap.add_argument('--market', choices=('us', 'kr'))
    a = ap.parse_args(argv)
    try:
        book = stamp(a.datadir, a.market)
    except OSError as e:
        print(f'stamp_collect: 쓰기 실패 — {e}', file=sys.stderr)
        return 1
    files = book['files']
    absent = sorted(r for r, e in files.items() if not e.get('present'))
    bare = sorted(r for r, e in files.items() if e.get('present') and e.get('collect_in') == 'none')
    bad = sorted(r for r, e in files.items() if e.get('status') in ('failed', 'partial'))
    print(f"{C.status_path(a.datadir)} — {book['market']} {book['report_date']} · 파일 {len(files)}개"
          + (f" · 없음 {absent}" if absent else '')
          + (f" · 상태 칸 없음 {bare}" if bare else '')
          + (f" · 수집 실패·일부 {bad}" if bad else ''))
    for r in bad:
        print(f"::warning::수집 상태 {files[r]['status']}: {r} — {files[r].get('response')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
