#!/usr/bin/env python3
"""일본 일간 — 작성자 입력 진단과 조립 (2026-10-27).

    python3 scripts/build_japan_daily.py diag --session 2026-10-26
        → 절 순서(이벤트일이면 매크로가 둘째), complete, 기준일이 다른 값들, 뉴스 후보 수, 직전 일간 경로
    python3 scripts/build_japan_daily.py assemble --session 2026-10-26 \
        --body jpd.body.html --meta jpd.meta.json --out japan/daily/2026-10-26.html

스냅샷은 발행 전이면 `japan/data/daily/candidate/<s>.json`, 발행 뒤면 `japan/data/daily/<s>.json`.
`complete` 가 거짓이면 진단이 1 로 끝난다 — 오케스트레이터는 발행하지 않는다.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from japan import daily_render as R  # noqa: E402
from us.news_expand import expand  # noqa: E402


def snapshot_path(root, session):
    pub = Path(root) / 'japan' / 'data' / 'daily' / f'{session}.json'
    return pub if pub.exists() else Path(root) / 'japan' / 'data' / 'daily' / 'candidate' / f'{session}.json'


def news_path(root, session):
    return Path(root) / 'japan' / 'data' / 'news' / 'daily' / f'{session}.json'


def _load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def cmd_diag(args):
    d = _load(snapshot_path(args.root, args.session))
    want = R.order(d['calendar'].get('event_day'))
    news = _load(news_path(args.root, args.session)) if news_path(args.root, args.session).exists() else {}
    print(f'{args.session} complete={d["complete"]} 직전 세션={d["prev_session"]}')
    print('절 순서: ' + ' → '.join(want))
    if d['calendar'].get('event_day'):
        print('이벤트일: ' + ', '.join(e['name_ko'] for e in d['calendar']['event_day']))
    jgb = [f'{t} {r["period"]}' for t, r in (d.get('jgb') or {}).items() if isinstance(r, dict) and r]
    print(f'기준일 — JGB {", ".join(jgb) or "없음"} · 콜 {(d.get("call_rate") or {}).get("period")} · 엔 16:30 JST')
    print(f'뉴스 후보 {len(news.get("items") or [])}건 · 움직인 종목 묶음 {len(d["movers"]["groups"])}개')
    bad = {k: v for k, v in d.get('fetch_status', {}).items() if v != 'ok'}
    for k, v in bad.items():
        print(f'  ! {k}: {v}')
    prev = Path(args.root) / 'japan' / 'daily' / f'{d["prev_session"]}.html'
    print(f'직전 일간: {prev if prev.exists() else "없음(첫 회)"}')
    return 0 if d['complete'] else 1


def cmd_assemble(args):
    body = Path(args.body).read_text(encoding='utf-8')
    meta = _load(args.meta)
    d = _load(snapshot_path(args.root, args.session))
    errs = R.validate_body(body, R.order(d['calendar'].get('event_day')))
    for k in ('title', 'summary'):
        if not str(meta.get(k, '')).strip():
            errs.append(f'meta.json 에 {k} 가 없다')
    if not errs:
        np = news_path(args.root, args.session)
        body, errs = expand(body, _load(np) if np.exists() else {'items': []})
    if errs:
        for e in errs:
            print(f'  - {e}')
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(R.assemble(body, meta, d), encoding='utf-8')
    print(f'{args.out} 조립 완료')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    dg = sub.add_parser('diag')
    a = sub.add_parser('assemble')
    for p in (dg, a):
        p.add_argument('--session', required=True)
        p.add_argument('--root', default='.')
    for k in ('--body', '--meta', '--out'):
        a.add_argument(k, required=True)
    args = ap.parse_args(argv)
    return {'diag': cmd_diag, 'assemble': cmd_assemble}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
