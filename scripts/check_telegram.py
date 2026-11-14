#!/usr/bin/env python3
"""Gate: Telegram-sourced sentences in a US/KR daily brief (rules: scripts/common/telegram_gate.py).

  python3 scripts/check_telegram.py --html morning_brief_2026-11-10.html --tg <workspace>/telegram.json --date 2026-11-09

No file and no data-tg in the post passes. A file whose report_date is not --date counts as
no file (a stale snapshot must not authorise anything).

News posts (`/news/`, `/kr/news/`, 2026-11-12) add `--layout news --news <the news file the writer used>`:
  python3 scripts/check_telegram.py --html news_industry_2026-11-11.html --tg <workspace>/telegram_news.json \\
      --news <workspace>/news/2026-11-11.json --date 2026-11-11 --layout news
On success it prints the section's paragraphs in order, then each marker next to its summary — the
routine reads both (meaning, and who a sentence reads as the words of, are not something this gate
can check). Rules: scripts/common/telegram_gate.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.telegram_gate import check, dates_only_in  # noqa: E402


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
    warns, pairs, paras = [], [], []
    v = check(html, data, warnings=warns, layout=a.layout, news=news, pairs=pairs, paras=paras)
    for w in warns:
        print(f'경고: {w}')
    if not v:
        print(f'텔레그램 인용 이상 없음 — {a.html}')
        if a.layout == 'news' and pairs:
            print(f'다시 읽기 {len(pairs)}건, 문단 {len(paras)}개 — 두 가지를 읽는다.')
            print('① 문단(글 순서 그대로, [id] 뒤가 그 항목의 문장, 나머지는 잇는 말): 문장마다 누구의 말로 읽히는지 — '
                  '이름·「같은 보도는」·「시장에서는」이 가리키는 범위, 앞 문장 안에 다른 화자가 있을 때 — 와 '
                  '「반면」·「같은 흐름」 같은 관계어가 맞는지, 잇는 말이 요약에 없는 사실·평가·전망을 말하지 않는지.')
            for n, parts in enumerate(paras, 1):
                # spaces as written: a marker glued to the text before it prints glued
                line = ''.join(x[1] if x[0] == 'text' else f'[{x[1]}] {x[2]}' for x in parts)
                print(f'  문단 {n}: {line.strip()}')
            print('② 항목: 문장이 요약과 같은 뜻인지, 요약에 없는 평가·날짜·기간을 덧붙이지 않았는지.')
            for tid, text, summ in pairs:
                print(f'  [{tid}]\n    문장: {text}\n    요약: {summ}')
                extra = dates_only_in(text, summ)
                if extra:
                    print(f'    날짜: {", ".join(extra)} — 요약에는 이 표기가 없다(표기만 바꾼 것인지 본다)')
        return 0
    for x in v:
        print(f'FAIL {x}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
