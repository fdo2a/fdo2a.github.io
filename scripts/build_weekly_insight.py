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
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from us import fomc_official as F  # noqa: E402
from us import weekly_insight as I  # noqa: E402


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def cmd_diag(args):
    agg = _load(f'data/weekly/{args.key}.json')
    snap = _load(f'data/weekly_ext/{args.key}.json')
    cal = _load('data/calendar.json') if Path('data/calendar.json').exists() else {}
    # 신선도는 **실행일** 기준이다 — 집계 종료일로 재면 지난 주간본을 다시 진단할 때
    # 낡은 표가 나이 0 으로 통과한다. 어느 회의를 고를지는 `I.build` 가 end_date 로 정한다.
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    meetings, note = F.load('data/fomc_dates.json', as_of=today)
    if not meetings:
        print(f'FOMC 일정표: {note}', file=sys.stderr)
    fomc = [d.isoformat() for d in meetings]
    if snap.get('end_date') and snap['end_date'] < agg['end_date']:
        print(f'스냅샷 기준일({snap["end_date"]})이 집계 종료일({agg["end_date"]})보다 이르다 — 다시 수집한다')
        return 1
    diag = I.build(agg, snap, cal, fomc)
    # 일정 수집이 모호해서 뺀 지표(2026-10 CPI). 표에 없다는 사실을 작성자·게이트가 보게 한다.
    diag['calendar_ambiguous'] = cal.get('ambiguous') or []
    if diag['calendar_ambiguous']:
        print(f'  ! 일정표에서 빠진 지표(이름이 모호): {", ".join(diag["calendar_ambiguous"])}')
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
    agg = _load(f'data/weekly/{args.key}.json')
    diag_path = Path(f'data/weekly_ext/{args.key}.insight.json')
    diag = _load(diag_path)
    events = meta.get('next_events') or []
    if not isinstance(events, list):
        errs.append('meta.json next_events 는 목록이어야 한다')
        events = []
    errs += [f'meta.json {e}' for e in I.merge_next(diag.get('next_week') or [], events, diag['end_date'])[1]]
    if errs:
        for e in errs:
            print(f'  - {e}')
        return 1
    # 작성자 입력은 일정표(next_week)와 따로 진단 파일에 싣는다 — 게이트·발행 뒤 재검사가 같은 표를
    # 다시 그린다. 매번 통째로 바꿔 지운 일정이 남지 않게 한다. 이 파일은 발행 커밋에 들어간다.
    diag['next_events'] = events
    diag_path.write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding='utf-8')
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
