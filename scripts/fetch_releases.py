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

Non-core by design: every failure is reported and skipped. A missing release means the
brief says so, never that it invents the composition.

  python scripts/fetch_releases.py --datadir data
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.release_text import to_text  # noqa: E402

# Ordered by how often each disguise gets through; the first success wins.
IMPERSONATE = ('safari', 'chrome131', 'chrome119', 'safari_ios', 'firefox')
TIMEOUT = 30


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def fetch(url):
    """-> (text, note). Plain requests first; impersonation only if that is refused."""
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
        if r.status_code == 200 and len(r.content or b'') > 3000:
            return r, f'impersonate={imp}'
        last = f'{imp}: HTTP {r.status_code}, {len(r.content or b"")}B'
    return None, last or 'unknown'


def body(resp, url):
    """Response -> readable text. PDFs go through pypdf, everything else through to_text."""
    if url.lower().endswith('.pdf') or 'pdf' in (resp.headers.get('content-type') or ''):
        try:
            import io

            from pypdf import PdfReader
            pages = PdfReader(io.BytesIO(resp.content)).pages
            return to_text('<p>' + '</p><p>'.join(p.extract_text() or '' for p in pages) + '</p>')
        except Exception as e:
            return f'[PDF 추출 실패: {e}]'
    return to_text(resp.text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()

    metrics = load(os.path.join(args.datadir, 'macro_metrics.json')) or {}
    releases = metrics.get('headline_releases') or []
    if not releases:
        print('오늘 해부할 신규 발표 없음 — 건너뜀')
        return

    outdir = os.path.join(args.datadir, 'releases')
    os.makedirs(outdir, exist_ok=True)
    index = []

    for rel in releases:
        key, url = rel.get('key'), rel.get('url')
        if not url:
            print(f'  {key}: 원문 URL 없음 — 건너뜀')
            continue
        resp, note = fetch(url)
        if resp is None:
            print(f'  {key}: 실패 ({note})', file=sys.stderr)
            index.append({'key': key, 'url': url, 'ok': False, 'note': note})
            continue
        text = body(resp, url)
        path = os.path.join(outdir, f'{key}.txt')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(f'# {rel.get("label") or key} · {rel.get("agency") or ""}\n'
                     f'# 원문: {url}\n'
                     f'# 수집: {metrics.get("generated", "")} ({note})\n\n{text}\n')
        print(f'  {key}: {len(text):,}자 ({note})')
        index.append({'key': key, 'url': url, 'ok': True, 'note': note,
                      'chars': len(text), 'path': f'releases/{key}.txt'})

    with open(os.path.join(outdir, 'index.json'), 'w', encoding='utf-8') as fh:
        json.dump({'report_date': metrics.get('report_date'), 'releases': index},
                  fh, indent=2, ensure_ascii=False)
    got = sum(1 for r in index if r['ok'])
    print(f'원문 {got}/{len(index)}건 확보')


if __name__ == '__main__':
    main()
