#!/usr/bin/env python3
"""일본 일간 발행 게이트 CLI (2026-10-27). 순수 로직 `japan/daily_gate.py`.

    python3 scripts/check_japan_daily.py --session 2026-10-26 [--html japan/daily/2026-10-26.html]

스냅샷은 발행 스냅샷이 있으면 그것, 없으면 수집 후보. 뉴스 파일은 숫자 원천(움직인 종목 문단)으로만 쓰고,
뉴스 절 자체는 `check_news.py --market jp-daily` 가 본다. 위반이 하나라도 있으면 1.
「증권사 견해·시장 의견」 절(2026-11-15)의 근거는 `build_japan_daily.telegram_path` — 발행 전이면 수집기 파일,
발행 뒤면 발행 단계가 고정한 사본. `usable: true` 가 아니면 없는 것으로 본다. 통과하면 문단과 요약을
나란히 찍는다 — 뜻이 같은지는 루틴이 읽는다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_japan_daily import load_telegram, news_path, snapshot_path  # noqa: E402
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
    tg, why = load_telegram(args.root, args.session)
    if why:
        print(f'경고: 견해·의견 파일을 없는 것으로 본다 — {why}')
    pairs = []
    v = daily_gate.check(html, snap, args.session, filename=os.path.basename(path), news=news, tg=tg, pairs=pairs)
    if v:
        print(f'일본 일간 게이트 위반 {len(v)}건 ({path}):', file=sys.stderr)
        for m in v:
            print(f'  - {m}', file=sys.stderr)
        return 1
    print(f'일본 일간 게이트 통과 — {path}')
    if pairs:
        print(f'견해·의견 다시 읽기 {len(pairs)}건 — 문단이 요약과 같은 뜻인지, 요약에 없는 평가·전망을 덧붙이지 않았는지 읽는다.')
        for tid, text, summ in pairs:
            print(f'  [{tid}]\n    문단: {text}\n    요약: {summ}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
