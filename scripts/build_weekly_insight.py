#!/usr/bin/env python3
"""US 주간 인사이트 — 진단을 계산하고, 작성자의 본문에 표를 채워 한 편으로 조립한다.

    python3 scripts/build_weekly_insight.py diag --key 2026-W39
        → data/weekly_ext/2026-W39.insight.json  (집계 + 스냅샷 + 일정 + FOMC)
    python3 scripts/build_weekly_insight.py assemble --key 2026-W39 \
        --body weekly_2026-W39.body.html --meta weekly_2026-W39.meta.json --out weekly_2026-W39.html

body 계약·절 순서·표 자리: scripts/us/weekly_insight.py 머리말. 계약 위반이면 exit 1 로
전부 나열하고 아무것도 쓰지 않는다.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from us import weekly_insight as I  # noqa: E402


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def cmd_diag(args):
    agg = _load(f'data/weekly/{args.key}.json')
    snap = _load(f'data/weekly_ext/{args.key}.json')
    cal = _load('data/calendar.json') if Path('data/calendar.json').exists() else {}
    fomc = _load('data/fomc_dates.json').get('meetings', []) if Path('data/fomc_dates.json').exists() else []
    if snap.get('end_date') and snap['end_date'] < agg['end_date']:
        print(f'스냅샷 기준일({snap["end_date"]})이 집계 종료일({agg["end_date"]})보다 이르다 — 다시 수집한다')
        return 1
    diag = I.build(agg, snap, cal, fomc)
    out = Path(f'data/weekly_ext/{args.key}.insight.json')
    out.write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding='utf-8')
    flagged = [a['label'] for a in diag['anomalies'] if a['flagged']]
    print(f'{out} — 이례적 움직임 {len(flagged)}개: {", ".join(flagged) or "없음"} · '
          f'포지션 {len(diag["positioning"])} · 다음 주 일정 {len(diag["next_week"])}')
    for k, v in diag['fetch_status'].items():
        print(f'  ! 스냅샷 실패 {k}: {v}')
    return 0


def cmd_assemble(args):
    body = Path(args.body).read_text(encoding='utf-8')
    meta = _load(args.meta)
    errs = I.validate_body(body)
    for k in ('title', 'summary'):
        if not str(meta.get(k, '')).strip():
            errs.append(f'meta.json 에 {k} 가 없다')
    if errs:
        for e in errs:
            print(f'  - {e}')
        return 1
    agg = _load(f'data/weekly/{args.key}.json')
    diag = _load(f'data/weekly_ext/{args.key}.insight.json')
    Path(args.out).write_text(I.assemble(body, meta, diag, agg), encoding='utf-8')
    print(f'{args.out} 조립 완료')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('diag')
    d.add_argument('--key', required=True)
    a = sub.add_parser('assemble')
    a.add_argument('--key', required=True)
    a.add_argument('--body', required=True)
    a.add_argument('--meta', required=True)
    a.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    return {'diag': cmd_diag, 'assemble': cmd_assemble}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
