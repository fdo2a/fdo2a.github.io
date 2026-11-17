#!/usr/bin/env python3
"""Fetch the primary press release behind each of today's promoted indicators.

Runs in the GitHub Actions collector job and commits data/releases/<key>.txt, so the
cloud routine reads the actual document instead of paraphrasing a dashboard row.

Why this exists at all: FRED redistributes the *series*, never the release prose, and
the prose is where the interpretation lives — "shelter … accounting for roughly
two-thirds of the monthly all items increase" has no series equivalent.

Why it runs here rather than in the routine: bls.gov and dol.gov answer 403 to ordinary
clients (verified 2026-08-18 from a residential IP with a real browser UA), so reaching
them needs TLS-fingerprint impersonation. Doing that once in Actions and committing the
result keeps the routine deterministic — the same reasoning that moved market data here
on 2026-07-15.

Contract (2026-11-06 — spec docs/superpowers/specs/2026-11-07-release-fetch-contract.md):

- The directory is **this run's** and nothing else. The first thing a run does is delete
  every `<key>.txt` and write `index.json` = {report_date, run_id, status: "running"}.
  Only at the end does status become "complete". `--sanitize` (an always() step after
  this one) wipes the directory again unless the index is this run's and complete, so a
  crash or a skipped step never leaves yesterday's release looking like today's.
- A file is written only for a document that `us.release_verify` recognised as the
  release of this print (identity sentence, period = ref_period, value). A failure
  writes no text anywhere — the index row says `ok: false` and why.
- `url` in a row is the document actually read and verified (after redirects, same
  registrable domain only); `landing_url` is where we started. `source_gate` authorises
  `url` of ok rows only.

2026-11-08 (A단계): the whole verified text also goes to `_workspace/releases/<key>.txt`
(gitignored), where `xcheck_components.py` reads it in the same job to confirm each
component against the agency's own sentence. A release in `anatomy.PRIVATE_TEXT` (the
Philadelphia Fed: 「All rights reserved」) gets only that private copy — nothing is
committed and the index row says `published: false`.

Non-core by design: every failure is reported and skipped. A missing release means the
brief writes the block from the structured figures, never that it invents the
composition.

  python scripts/fetch_releases.py --datadir data
  python scripts/fetch_releases.py --datadir data --sanitize
"""

import argparse
import datetime
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import release_resolve as rr  # noqa: E402
from us.anatomy import PRIVATE_TEXT  # noqa: E402
from us.release_text import to_text  # noqa: E402
from us.release_verify import verify  # noqa: E402

# Ordered by how often each disguise gets through; the first success wins.
IMPERSONATE = ('safari', 'chrome131', 'chrome119', 'safari_ios', 'firefox')
TIMEOUT = 30


def fulldir_for(datadir):
    """`<repo>/_workspace/releases` next to `<repo>/data` — gitignored, this job only."""
    return os.path.join(os.path.dirname(os.path.abspath(datadir)), '_workspace', 'releases')
MIN_BYTES = 1000      # an empty shell; real decisions are release_verify's


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def run_id():
    rid = os.environ.get('GITHUB_RUN_ID')
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f'local-{os.getpid()}-{int(time.time())}'


def http_get(url):
    """-> (response | None, note). curl_cffi with browser impersonation."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return None, 'curl_cffi 미설치'

    last = None
    for imp in IMPERSONATE:
        try:
            r = creq.get(url, impersonate=imp, timeout=TIMEOUT,
                         headers={'Referer': '/'.join(url.split('/')[:3]) + '/'})
        except Exception as e:
            last = f'{imp}: {type(e).__name__}'
            continue
        if r.status_code == 200 and len(r.content or b'') > MIN_BYTES:
            return r, f'impersonate={imp}'
        last = f'{imp}: HTTP {r.status_code}, {len(r.content or b"")}B'
    return None, last or 'unknown'


def _is_pdf(resp, url):
    return url.lower().endswith('.pdf') or 'pdf' in (resp.headers.get('content-type') or '')


def full_text(resp, url):
    """Response -> (whole flattened text, or None when a PDF would not extract)."""
    if _is_pdf(resp, url):
        try:
            import io

            from pypdf import PdfReader
            pages = PdfReader(io.BytesIO(resp.content)).pages
            html = '<p>' + '</p><p>'.join(p.extract_text() or '' for p in pages) + '</p>'
        except Exception:
            return None, None
    else:
        html = resp.text
    return to_text(html, max_chars=None, trim=False), html


def candidates(rel, get, today):
    """-> ([(url, resolver)], note). The documents to try, in order."""
    key, url = rel.get('key'), rel.get('url')
    kind, prefixes = rr.RESOLVERS.get(key, ('fixed', ()))
    if kind == 'bea_rss':
        resp, note = get(rr.BEA_RSS)
        if resp is None:
            return [], f'rss: {note}'
        html_url, pdf_url, _ = rr.bea_from_rss(resp.text, prefixes, today)
        out = [(u, 'bea_rss') for u in (html_url, pdf_url) if u]
        return out, 'rss: no fresh item' if not out else ''
    if kind == 'nar_page':
        resp, note = get(rr.NAR_PAGE)
        if resp is None:
            return [], f'nar page: {note}'
        found = rr.nar_from_page(resp.text)
        return ([(found, 'nar_page')], '') if found else ([], 'nar page: no release link')
    if kind == 'philly_month':
        primary = next((i for i in rel.get('indicators') or []
                        if i.get('name') == rel.get('primary')), {}) or {}
        found = rr.philly_url(primary.get('ref_period'))
        return ([(found, 'philly_month')], '') if found else ([], '기준월 없음')
    return ([(url, 'fixed')] if url else []), '' if url else '원문 URL 없음'


def fetch_one(rel, get, today):
    """-> (row, saved_text | None)."""
    key = rel.get('key')
    row = {'key': key, 'landing_url': rel.get('url'), 'ok': False}
    tries, note = candidates(rel, get, today)
    notes = [note] if note else []
    for url, resolver in tries:
        resp, how = get(url)
        if resp is None:
            notes.append(f'{url}: {how}')
            continue
        final = getattr(resp, 'url', None) or url
        if not rr.same_site(final, url):
            notes.append(f'{url}: redirected off-site')
            continue
        whole, html = full_text(resp, final)
        if whole is None:
            notes.append(f'{url}: pdf extract failed')
            continue
        checks = verify(whole, rel)
        if not checks['ok']:
            notes.append(f"{url}: {checks['note']}")
            continue
        row.update({'ok': True, 'url': final, 'resolver': resolver, 'verified': True,
                    'doc_kind': 'pdf' if _is_pdf(resp, final) else 'html',
                    'checks': checks, 'note': how})
        row['_full'] = whole
        return row, to_text(html)
    row['note'] = '; '.join(n for n in notes if n) or 'no candidate'
    return row, None


def _wipe(outdir):
    for p in glob.glob(os.path.join(outdir, '*.txt')):
        os.remove(p)


def _write_index(outdir, index):
    tmp = os.path.join(outdir, 'index.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(outdir, 'index.json'))


SOURCE = 'agency press releases (BLS·BEA·Census·DOL …)'


def index_collect(index, metrics_state, metrics_collect=None):
    """collect 칸(2026-11-17). `metrics_state` = fresh | stale | absent.

    오늘 받을 원문의 목록은 macro_metrics.json 이 정한다 — 그 파일이 없거나 이 세션 것이 아니면 「받을 것
    없음」을 확인한 것이 아니다(failed). 목록이 일부만 믿을 만하면(macro_metrics 의 collect 가 ok 가 아님)
    partial. 원문을 못 받은 지표가 missing.
    """
    from common import collect_status as C
    rd = index.get('report_date')
    if metrics_state != 'fresh':
        return C.failed(rd, SOURCE, f'macro_metrics.json {metrics_state} — 오늘 받을 원문 목록을 모른다')
    rows = index.get('releases') or []
    missing = [r.get('key') for r in rows if not r.get('ok')]
    # 목록을 정한 축 점수가 일부 지표 없이 나왔으면 무엇이 빠졌는지를 그대로 옮긴다(`metrics:<키>` + 식별자·기준월) —
    # 승인된 예외가 이 파일에도 같은 지표·같은 기준월로만 걸린다. 무엇이 빠졌는지 모르면 전처럼 macro_metrics.
    up, ref = C.carry_upstream(metrics_collect, 'metrics', 'macro_metrics')
    missing += up
    st = 'partial' if missing else 'ok'
    if rows and not any(r.get('ok') for r in rows):
        st = 'failed'
    return C.build(st, rd, SOURCE, missing=missing, empty='has_data' if rows else 'confirmed_none',
                   missing_ref=ref or None)


def run(datadir, rid, get=http_get, today=None, fulldir=None):
    fulldir = fulldir or fulldir_for(datadir)
    outdir = os.path.join(datadir, 'releases')
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(fulldir, exist_ok=True)
    _wipe(fulldir)
    market = load(os.path.join(datadir, 'market_data.json')) or {}
    from common import collect_status as C
    index = {'report_date': market.get('report_date'), 'run_id': rid,
             'status': 'running', 'releases': [],
             'collect': C.failed(market.get('report_date'), SOURCE, 'running — 실행이 끝나지 않았다')}
    _wipe(outdir)
    _write_index(outdir, index)

    raw = load(os.path.join(datadir, 'macro_metrics.json'))
    metrics = raw or {}
    releases = metrics.get('headline_releases') or []
    metrics_state = 'absent' if not raw else (
        'fresh' if metrics.get('report_date') == index['report_date'] else 'stale')
    if releases and metrics.get('report_date') != index['report_date']:
        # Yesterday's metrics left behind by a failed step would name yesterday's
        # releases under today's date (codex 구현 검토 2026-11-06 #1).
        print(f"원문 수집 건너뜀 — macro_metrics.json report_date={metrics.get('report_date')}, "
              f"세션 {index['report_date']}", file=sys.stderr)
        index['metrics'] = 'stale'
        releases = []
    today = today or rr.today_utc()
    for rel in releases:
        row, text = fetch_one(rel, get, today)
        full = row.pop('_full', None)
        if full is not None:
            with open(os.path.join(fulldir, f'{row["key"]}.txt'), 'w', encoding='utf-8') as fh:
                fh.write(full)
        if text is not None and row['key'] in PRIVATE_TEXT:
            row['published'] = False
            print(f'  {row["key"]}: 확인됨, 원문은 커밋하지 않는다(비공개 사본만)')
        elif text is not None:
            row['published'] = True
            path = os.path.join(outdir, f'{row["key"]}.txt')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(f'# {rel.get("label") or row["key"]} · {rel.get("agency") or ""}\n'
                         f'# 원문: {row["url"]}\n'
                         f'# 수집: {metrics.get("generated", "")} ({row.get("note")})\n\n{text}\n')
            row.update({'chars': len(text), 'path': f'releases/{row["key"]}.txt'})
            print(f'  {row["key"]}: {len(text):,}자 ({row["resolver"]}, {row["note"]})')
        else:
            print(f'  {row["key"]}: 실패 ({row["note"]})', file=sys.stderr)
        index['releases'].append(row)
        _write_index(outdir, index)
    index['status'] = 'complete'
    index['collect'] = index_collect(index, metrics_state, metrics.get('collect'))
    _write_index(outdir, index)
    got = sum(1 for r in index['releases'] if r['ok'])
    print(f'원문 {got}/{len(index["releases"])}건 확보' if releases else '오늘 해부할 신규 발표 없음')
    return index


def sanitize(datadir, rid):
    """Keep the directory only if this run wrote it and finished. -> True when kept."""
    outdir = os.path.join(datadir, 'releases')
    os.makedirs(outdir, exist_ok=True)
    index = load(os.path.join(outdir, 'index.json'))
    if index and index.get('run_id') == rid and index.get('status') == 'complete':
        return True
    market = load(os.path.join(datadir, 'market_data.json')) or {}
    _wipe(outdir)
    if os.path.isdir(fulldir_for(datadir)):
        _wipe(fulldir_for(datadir))
    from common import collect_status as C
    _write_index(outdir, {'report_date': market.get('report_date'), 'run_id': rid,
                          'status': 'aborted', 'releases': [],
                          'collect': C.failed(market.get('report_date'), SOURCE,
                                              'aborted — 이 실행의 완료된 index 가 아니다')})
    print('원문 디렉터리를 비웠다 — 이 실행의 완료된 index 가 아니다', file=sys.stderr)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--sanitize', action='store_true')
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--fulldir', default=None)
    args = ap.parse_args()
    rid = args.run_id or run_id()
    if args.sanitize:
        sanitize(args.datadir, rid)
    else:
        run(args.datadir, rid, fulldir=args.fulldir)


if __name__ == '__main__':
    main()
