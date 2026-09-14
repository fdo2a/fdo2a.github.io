#!/usr/bin/env python3
"""다음 열흘 일정을 `data/calendar.json` 으로 만든다.

  python3 scripts/build_calendar.py --datadir data
  python3 scripts/build_calendar.py --datadir data --date 2026-09-11

네 가지를 싣는다 — 지수 만기(셋째 금요일 규칙)와 연준 블랙아웃은 **계산**이고, 경제지표
일정(FRED)과 국채 입찰(Treasury FiscalData)은 **수집**이다. 수집이 실패하면 그 항목을
빼고 `missing` 에 적는다. `--offline` 은 수집을 아예 건너뛴다.

**키가 없는 날 경제지표 일정은 빈다.** FRED 폴백(graph CSV)에는 릴리스 일정표가 없다.
어제 받은 일정을 오늘 것처럼 인쇄하는 대신 없다고 적는다 — 낡은 일정은 없는 일정보다
나쁘고, 같은 이유로 낡은 FOMC 표도 쓰지 않는다.

**FOMC 회의일은 이 스크립트가 만들지 않는다.** `data/fomc_dates.json` 을 읽고, 없거나
낡았으면 그 항목을 빼고 `missing` 에 적는다. 레포가 아는 FOMC 날짜는 웹서치 산문 한
줄뿐이라 나머지를 채우면 수집이 아니라 창작이다 — 이 파이프라인에서 삭제는 언제나
창작보다 낫다.

`fomc_dates.json` 형식:

    {"source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
     "checked_at": "2026-09-14",
     "meetings": ["2026-09-16", "2026-10-28"]}
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import upcoming as U  # noqa: E402
from us.calendar import HORIZON_DAYS, build  # noqa: E402
from us.fred import FredClient, FredError  # noqa: E402
from us.macro_metrics import RELEASES  # noqa: E402


def _collect(report_date, start, end):
    """-> (events, auctions, missing). 비-코어: 실패는 기록하고 건너뛴다."""
    events, auctions, missing = [], [], []

    try:
        client = FredClient()
        client.preflight()
        got, dropped = U.release_events(client.release_dates(start, end), RELEASES)
        if not got:
            # 이름 매칭이 조용히 0건이 되는 경로가 있다(FRED 가 표기를 바꾸면).
            # 빈 결과를 성공으로 적으면 그 침묵이 영원히 안 들린다.
            raise FredError('release calendar matched nothing in the window')
        events += got
        for slug, names in dropped:
            print(f'경고: {slug} 이(가) 여러 릴리스에 걸려 버렸다 — {names}', file=sys.stderr)
    except Exception as e:
        missing.append('releases')
        print(f'경제지표 일정 실패: {e}', file=sys.stderr)

    try:
        rows = U.fetch_auctions(report_date - dt.timedelta(days=7), end)
        events += U.auction_events(rows, start, end)
        auctions = U.auction_results(rows, report_date)
    except Exception as e:
        missing.append('auctions')
        print(f'국채 입찰 실패: {e}', file=sys.stderr)

    return events, auctions, missing


def _load_meetings(path):
    """-> (dates, note). 못 읽으면 빈 목록 — 없는 일정을 지어내지 않는다."""
    try:
        with open(path, encoding='utf-8') as fh:
            book = json.load(fh)
    except FileNotFoundError:
        return [], f'{path} 없음'
    except Exception as e:
        return [], f'{path} 읽기 실패: {e}'
    out = []
    for raw in book.get('meetings') or []:
        try:
            out.append(dt.date.fromisoformat(raw))
        except Exception:
            return [], f'{path} 의 날짜 형식이 잘못됐다: {raw!r}'
    return out, f"{len(out)}건 (확인 {book.get('checked_at') or '미상'})"


def _report_date(datadir, override):
    if override:
        return dt.date.fromisoformat(override)
    # 시장 데이터의 report_date 가 그 리포트의 거래일이다 (US 계약).
    try:
        with open(os.path.join(datadir, 'market_data.json'), encoding='utf-8') as fh:
            got = json.load(fh).get('report_date')
        if got:
            return dt.date.fromisoformat(got)
    except Exception:
        pass
    return dt.date.today()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--date', help='보고서 거래일 (기본: market_data.json 의 report_date)')
    ap.add_argument('--horizon', type=int, default=HORIZON_DAYS)
    ap.add_argument('--out', help='기본: <datadir>/calendar.json')
    ap.add_argument('--offline', action='store_true',
                    help='수집을 건너뛴다 — 계산으로 아는 것만 싣는다')
    args = ap.parse_args()

    report_date = _report_date(args.datadir, args.date)
    meetings, note = _load_meetings(os.path.join(args.datadir, 'fomc_dates.json'))
    print(f'FOMC 일정표: {note}', file=sys.stderr)

    start = report_date + dt.timedelta(days=1)
    end = report_date + dt.timedelta(days=args.horizon)
    extra, auctions, missing = (([], [], ['releases', 'auctions']) if args.offline
                                else _collect(report_date, start, end))
    book = build(report_date, meetings=meetings, horizon_days=args.horizon,
                 extra=extra, missing=missing, auctions=auctions)
    out = args.out or os.path.join(args.datadir, 'calendar.json')
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, indent=2, ensure_ascii=False)

    kinds = {}
    for e in book['events']:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
    print(f"{out} — {len(book['events'])}건 " + (str(kinds) if kinds else '')
          + (f" · 빠짐 {book['missing']}" if book['missing'] else ''))
    if book['recent_auctions']:
        top = book['recent_auctions'][0]
        print(f"직전 입찰 {top['date']} {top['term']} — 응찰 {top['bid_to_cover']}"
              f" · 간접 {top['indirect_pct']}%")
    if book['blackout']['active']:
        print(f"연준 블랙아웃 중 — {book['blackout']['until']}까지")


if __name__ == '__main__':
    main()
