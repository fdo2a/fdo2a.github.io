#!/usr/bin/env python3
"""일본 주간 — 진단 계산과 조립.

    python3 scripts/build_japan_weekly.py diag --key 2026-W39
        → japan/data/<KEY>.json  (스냅샷 data/weekly_ext/<KEY>.json + japan/data/calendar.json)
        + japan/data/<KEY>.news.json (일본 전용 수집분 `digest` 행 = 「이번 주 뉴스」 후보,
          US/KR region=japan 행 = BOJ 절 근거. 둘 다 게이트의 수치 허용 원천)
    python3 scripts/build_japan_weekly.py assemble --key 2026-W39 \
        --body japan_<KEY>.body.html --meta japan_<KEY>.meta.json --out japan_<KEY>.html

스냅샷은 `scripts/collect_weekly_data.py` 가 만든다(US 주간과 공용).
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from japan import core as C  # noqa: E402
from japan import news as JN  # noqa: E402
from japan import render as R  # noqa: E402
from us.news_expand import expand  # noqa: E402

NEWS_DIRS = ('data/news', 'kr/data/news')
JAPAN_NEWS_DIR = 'japan/data/news'


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest_rows(key, base=JAPAN_NEWS_DIR):
    """그 주(월-금, JST) 일본 전용 수집분 가운데 요약까지 끝난 기사 — 「이번 주 뉴스」 후보.

    `digest: True` 가 게재 자격이다(codex 2026-10-18 #1·#2). US/KR 수집분의 region=japan 행은
    BOJ 절의 근거로만 남고 이 절에 실을 수 없다. 범위는 파일 이름이 아니라 기사면 발행 시각(JST)으로 본다(#4).
    """
    start, end = C.week_bounds(key)
    d0, out = date.fromisoformat(start), []
    for i in range(5):
        p = Path(base) / f'{(d0 + timedelta(days=i)).isoformat()}.json'
        if not p.exists():
            continue
        for r in _load(p).get('items') or []:
            day = (r.get('published') or '')[:10]
            if not r.get('summary_ko') or r.get('category') not in JN.DIGEST_CATEGORIES:
                continue
            if not (start <= day <= end):
                continue
            out.append({'date': day, 'guid': r.get('guid'), 'title': r.get('title'),
                        'source': r.get('source'), 'url': r.get('url'),
                        'published': r.get('published'), 'category': r.get('category'),
                        'summary_ko': r.get('summary_ko'), 'digest': True})
    return out


def week_news(key, dirs=NEWS_DIRS, japan_dir=JAPAN_NEWS_DIR):
    """일본 전용 수집분(게재 후보) + 그 주(월-일) US/KR 수집분의 region=japan 행(근거). 같은 guid 는 한 번."""
    start, _ = C.week_bounds(key)
    d0 = date.fromisoformat(start)
    out = digest_rows(key, japan_dir)
    seen = {r['guid'] for r in out}
    for i in range(7):
        day = (d0 + timedelta(days=i)).isoformat()
        for base in dirs:
            p = Path(base) / f'{day}.json'
            if not p.exists():
                continue
            for r in _load(p).get('items') or []:
                if r.get('region') != 'japan' or r.get('guid') in seen:
                    continue
                seen.add(r.get('guid'))
                out.append({'date': day, 'title': r.get('title'), 'source': r.get('source'),
                            'url': r.get('url'), 'summary_ko': r.get('summary_ko')})
    return out


def cmd_diag(args):
    snap = _load(f'data/weekly_ext/{args.key}.json')
    cal = _load('japan/data/calendar.json')
    agg_path = Path(f'data/weekly/{args.key}.json')
    us_agg = _load(agg_path) if agg_path.exists() else None
    d = C.build(snap, cal, args.key, us_agg)
    Path('japan/data').mkdir(parents=True, exist_ok=True)
    Path(f'japan/data/{args.key}.json').write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                                    encoding='utf-8')
    news = week_news(args.key)
    Path(f'japan/data/{args.key}.news.json').write_text(json.dumps(news, ensure_ascii=False, indent=1),
                                                         encoding='utf-8')
    t = d['signals']['tally']
    print(f'japan/data/{args.key}.json — 신호 인상 지속 {t["A"]} · 인상 중단 {t["B"]} · 중립 {t["중립"]} '
          f'· 일정 {len(d["next_events"])} · 일본 뉴스 {len(news)}'
          f'(이번 주 뉴스 후보 {sum(1 for r in news if r.get("digest"))})')
    for k, v in d['fetch_status'].items():
        print(f'  ! 스냅샷 실패 {k}: {v}')
    return 0


def cmd_assemble(args):
    body = Path(args.body).read_text(encoding='utf-8')
    meta = _load(args.meta)
    errs = R.validate_body(body)
    for k in ('title', 'summary'):
        if not str(meta.get(k, '')).strip():
            errs.append(f'meta.json 에 {k} 가 없다')
    if errs:
        for e in errs:
            print(f'  - {e}')
        return 1
    d = _load(f'japan/data/{args.key}.json')
    news_path = Path(f'japan/data/{args.key}.news.json')
    rows = _load(news_path) if news_path.exists() else []
    # 「이번 주 뉴스」 자리표시를 수집 요약으로 채운다 — 후보는 게재 자격(digest) 행만
    body, errs = expand(body, {'items': [r for r in rows if r.get('digest')]})
    if errs:
        for e in errs:
            print(f'  - {e}')
        return 1
    Path(args.out).write_text(R.assemble(body, meta, d), encoding='utf-8')
    print(f'{args.out} 조립 완료')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('diag').add_argument('--key', required=True)
    a = sub.add_parser('assemble')
    for k in ('--key', '--body', '--meta', '--out'):
        a.add_argument(k, required=True)
    args = ap.parse_args(argv)
    return {'diag': cmd_diag, 'assemble': cmd_assemble}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
