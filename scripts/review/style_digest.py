#!/usr/bin/env python3
"""발행 뒤 codex 문체 지적의 주간 묶음 — 사람이 보고 STYLE_EXEMPLARS 에 넣을지 정한다.

  python3 scripts/review/style_digest.py [--since 7d] [--root .]

`reviews/style_findings/*.json`(git 제외, 발행 뒤 러너가 쓴다)과 `reviews/prepublish/*/*.json`(발행 전 검토,
발행 커밋에 함께 들어간다)의 `style_findings` 를 읽는다. 분류별 건수와 예시(인용·방향)를 찍는다. **아무것도 고치지 않는다** — 지시문을 자동으로 바꾸는 경로는 없다(2026-11-06 C안).
"""

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

FOLDER = 'reviews/style_findings'
PREPUB = 'reviews/prepublish'


def _since(spec):
    spec = spec.strip().lower()
    if spec.endswith('d') and spec[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(spec[:-1]))
    return datetime.fromisoformat(spec).replace(tzinfo=timezone.utc)


def _at(text):
    try:
        t = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def collect(root, since):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, FOLDER, '*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        at = _at(rec.get('at'))
        if at is None or at < since:
            continue
        for f in rec.get('findings') or ():
            if isinstance(f, dict):
                rows.append(dict(f, path=rec.get('path', ''), at=rec.get('at')))
    for path in sorted(glob.glob(os.path.join(root, PREPUB, '*', '*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        at = _at(rec.get('recorded_at'))
        if at is None or at < since:
            continue
        where = f"{rec.get('section', '')} {rec.get('date', '')} (발행 전)"
        for f in rec.get('style_findings') or ():
            if isinstance(f, dict):
                rows.append(dict(f, path=where, at=rec.get('recorded_at')))
    return rows


def digest(rows, examples=3):
    by = defaultdict(list)
    for r in rows:
        by[r.get('kind') or '기타'].append(r)
    posts = len({r['path'] for r in rows})
    out = ['문체 지적 묶음 — %d건, 글 %d편' % (len(rows), posts)]
    for kind, items in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append('\n[%s] %d건' % (kind, len(items)))
        for r in items[:examples]:
            out.append('  - %s 「%s」 — %s' % (r['path'], r.get('quote', ''), r.get('note', '')))
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='7d')
    ap.add_argument('--root', default='.')
    ap.add_argument('--examples', type=int, default=3)
    args = ap.parse_args(argv)
    print(digest(collect(args.root, _since(args.since)), args.examples))
    return 0


if __name__ == '__main__':
    sys.exit(main())
