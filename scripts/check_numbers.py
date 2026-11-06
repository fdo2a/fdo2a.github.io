#!/usr/bin/env python3
"""US 발행 게이트 — 본문 수치 전수 대조(자리 단위).

  python3 scripts/check_numbers.py --html morning_brief_DATE.html --datadir <workspace>

시장 표 칸은 행·열이 가리키는 데이터 값과, 문장 수치는 자산·단위로 정해지는 필드와 맞춘다.
문장 층의 차단 여부는 `config/number_audit.json` 의 `prose`(warn|block), `--prose` 로 덮는다.
Exit 0 = 발행 가능(경고는 0), 1 = 위반(한 줄에 하나), 2 = 입력을 읽지 못함(통과로 치지 않는다).
로직 `scripts/us/number_audit.py`.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from us import number_audit as N  # noqa: E402

CONFIG = os.path.join(os.path.dirname(HERE), 'config', 'number_audit.json')
OPTIONAL = ('econ_indicators', 'macro_metrics', 'fund_board')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _mode(arg):
    if arg:
        return arg
    try:
        return _read(CONFIG).get('prose', 'warn')
    except (OSError, ValueError, AttributeError):
        return 'warn'       # 설정이 없으면 막지 않는 쪽 — 표 층은 늘 막는다


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--prose', choices=('warn', 'block'))
    args = ap.parse_args(argv)
    # 적용일 전 글은 입력을 읽기 전에 끝낸다 — 정정기가 옛 글에 다시 돌릴 때 판정 불가(2)로 막지 않게
    m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(args.html))
    if m and m.group(0) < N.EFFECTIVE:
        print(f'number audit: 적용일({N.EFFECTIVE}) 전 글이라 검사하지 않는다')
        return 0
    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
        data = {'market_data': _read(os.path.join(args.datadir, 'market_data.json'))}
    except (OSError, ValueError) as e:
        print(f'FATAL: 입력을 읽지 못했다: {e}', file=sys.stderr)
        return 2
    for k in OPTIONAL:
        p = os.path.join(args.datadir, f'{k}.json')
        try:
            data[k] = _read(p)
        except OSError:
            pass                     # 없으면 그 위임이 성립하지 않아 해당 수치는 미검증으로 센다
        except ValueError as e:
            print(f'FATAL: {k}.json 을 읽지 못했다: {e}', file=sys.stderr)
            return 2
    try:
        data['liquidity'] = _read(os.path.join(args.datadir, 'liquidity', 'liquidity.json'))
    except OSError:
        pass
    except ValueError as e:
        print(f'FATAL: liquidity.json 을 읽지 못했다: {e}', file=sys.stderr)
        return 2
    # 글 날짜와 데이터 날짜가 다르면 다른 날 값으로 대조하게 된다 — 판정할 수 없다(발행 커밋의 data 가
    # 다음 세션인 경우가 있다: 10/15 글 → 10/16 data)
    rd = (data['market_data'] or {}).get('report_date') if isinstance(data['market_data'], dict) else None
    if m and rd and rd != m.group(0):
        print(f'FATAL: 데이터 report_date {rd} 가 글 날짜 {m.group(0)} 와 다르다 — 그 날 판으로 다시 돌린다',
              file=sys.stderr)
        return 2
    try:
        r = N.audit(html, data, prose=_mode(args.prose))
    except N.InputError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    if r.skipped:
        print(f'number audit: 적용일({N.EFFECTIVE}) 전 글이라 검사하지 않는다')
        return 0
    for w in r.warnings:
        print(w)
    for v in r.violations:
        print(v)
    print(r.summary())
    return 1 if r.violations else 0


if __name__ == '__main__':
    sys.exit(main())
