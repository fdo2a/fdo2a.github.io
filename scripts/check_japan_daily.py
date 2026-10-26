#!/usr/bin/env python3
"""일본 일간 발행 게이트 CLI (2026-10-27). 순수 로직 `japan/daily_gate.py`.

    python3 scripts/check_japan_daily.py --session 2026-10-26 [--html japan/daily/2026-10-26.html]

스냅샷은 발행 스냅샷이 있으면 그것, 없으면 수집 후보. 뉴스 파일은 숫자 원천(움직인 종목 문단)으로만 쓰고,
뉴스 절 자체는 `check_news.py --market jp-daily` 가 본다. 위반이 하나라도 있으면 1.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_japan_daily import news_path, snapshot_path  # noqa: E402
from japan import daily_gate  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--html', default=None)
    ap.add_argument('--root', default='.')
    args = ap.parse_args(argv)
    path = args.html or os.path.join(args.root, 'japan', 'daily', f'{args.session}.html')
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    with open(snapshot_path(args.root, args.session), encoding='utf-8') as fh:
        snap = json.load(fh)
    np = news_path(args.root, args.session)
    news = json.loads(np.read_text(encoding='utf-8')) if np.exists() else None
    v = daily_gate.check(html, snap, args.session, filename=os.path.basename(path), news=news)
    if v:
        print(f'일본 일간 게이트 위반 {len(v)}건 ({path}):', file=sys.stderr)
        for m in v:
            print(f'  - {m}', file=sys.stderr)
        return 1
    print(f'일본 일간 게이트 통과 — {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
