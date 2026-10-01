#!/usr/bin/env python3
"""연준 공표 FOMC 일정 → `data/fomc_dates.json`.

  python3 scripts/update_fomc_dates.py --datadir data

Actions 가 달력 생성 직전에 돌린다. 받기·파싱에 실패하거나 `fomc_official.problems()`
가 덜 읽힌 원문으로 보면 **파일을 건드리지 않고** 0 이 아닌 코드로 끝난다 — 어제 표가
남고, 그 표가 45일을 넘기면 `fomc_official.load()` 가 읽기를 거부한다.

파싱은 `scripts/us/fomc_official.py` 다.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import fomc_official as F  # noqa: E402

KST = dt.timezone(dt.timedelta(hours=9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--allow-removal', action='append', default=[], metavar='YYYY-MM-DD',
                    help='어제 표에 있던 이 회의가 빠져도 바꾼다 — 연준이 실제로 옮긴 것을 '
                         '사람이 확인한 날짜만. 여러 번 줄 수 있다')
    ap.add_argument('--bootstrap', action='store_true',
                    help='어제 표 없이 처음 만든다 — 누락 대조가 꺼지므로 사람이 결과를 확인할 것')
    args = ap.parse_args()

    today = dt.datetime.now(KST).date()
    path = os.path.join(args.datadir, 'fomc_dates.json')
    try:
        book = F.book(F.fetch(), verified_at=today.isoformat())
    except Exception as exc:
        print(f'FOMC 공식 일정을 받지 못했다 — 파일 유지: {exc}', file=sys.stderr)
        return 1
    try:
        with open(path, encoding='utf-8') as fh:
            previous = json.load(fh)
        previous = previous if isinstance(previous, dict) else None
    except Exception:
        previous = None
    bad = F.problems(book, previous=previous, today=today,
                     require_previous=not args.bootstrap,
                     allowed_removals=set(args.allow_removal))
    if bad:
        print('FOMC 공식 일정이 온전히 읽히지 않았다 — 파일 유지: ' + ' / '.join(bad),
              file=sys.stderr)
        return 1

    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')
    os.replace(tmp, path)
    print(f"FOMC 일정 {len(book['meetings'])}회 (SEP {len(book['sep_meetings'])}) "
          f'— 공식 확인 {today.isoformat()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
