#!/usr/bin/env python3
"""Gate: Telegram-sourced sentences in a US/KR daily brief (rules: scripts/common/telegram_gate.py).

  python3 scripts/check_telegram.py --html morning_brief_2026-11-10.html --tg <workspace>/telegram.json --date 2026-11-09

No file and no data-tg in the post passes. A file whose report_date is not --date counts as
no file (a stale snapshot must not authorise anything).

News posts (`/news/`, `/kr/news/`, 2026-11-12) add `--layout news --news <the news file the writer used>`:
  python3 scripts/check_telegram.py --html news_industry_2026-11-11.html --tg <workspace>/telegram_news.json \\
      --news <workspace>/news/2026-11-11.json --date 2026-11-11 --layout news
On success it prints each paragraph next to its summary — the routine reads them (meaning is not
something this gate can check). Rules: scripts/common/telegram_gate.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.telegram_gate import check  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--tg', required=True, help='telegram.json snapshot the writer was given')
    ap.add_argument('--date', required=True, help='report_date')
    ap.add_argument('--layout', choices=['brief', 'news'], default='brief')
    ap.add_argument('--news', help='news layout: the news file the writer and check_news.py used')
    a = ap.parse_args(argv)
    if a.layout == 'news' and not a.news:
        ap.error('--layout news 에는 --news <뉴스 수집분 json> 이 필요하다')
    with open(a.html, encoding='utf-8') as f:
        html = f.read()
    data = None
    try:
        with open(a.tg, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if data and data.get('report_date') != a.date:
        print(f'경고: {a.tg} 의 report_date {data.get("report_date")} ≠ {a.date} — 없는 것으로 본다')
        data = None
    news = None
    if a.layout == 'news':
        if not os.path.exists(a.news):
            print(f'뉴스 수집분 없음 — {a.news} (뉴스 블록의 요약도 표식 밖 문장으로 견준다)')
        else:
            try:
                with open(a.news, encoding='utf-8') as f:
                    news = json.load(f)
            except (OSError, ValueError):
                print(f'경고: {a.news} 를 읽지 못했다 — 뉴스 블록의 요약도 표식 밖 문장으로 견준다')
    warns, pairs = [], []
    v = check(html, data, warnings=warns, layout=a.layout, news=news, pairs=pairs)
    for w in warns:
        print(f'경고: {w}')
    if not v:
        print(f'텔레그램 인용 이상 없음 — {a.html}')
        if a.layout == 'news' and pairs:
            print(f'다시 읽기 {len(pairs)}건 — 문단이 요약과 같은 뜻인지, 요약에 없는 평가를 덧붙이지 않았는지 본다:')
            for tid, text, summ in pairs:
                print(f'  [{tid}]\n    문단: {text}\n    요약: {summ}')
        return 0
    for x in v:
        print(f'FAIL {x}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
