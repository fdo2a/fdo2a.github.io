#!/usr/bin/env python3
"""발행 게이트 — 「연준 이벤트」 섹션.

  python3 scripts/check_fed.py --html morning_brief_2026-09-17.html --datadir .

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩 출력 — writer 에게 그대로 돌려준다.

이 게이트가 서 있는 자리는 **인용문**이다. 지어낸 수치는 데이터와 맞대면 걸리지만
지어낸 발언은 그럴듯할수록 안 걸리므로, 발행본의 인용이 수집해 둔 원문에 글자 그대로
있는지를 본다. 원문을 못 받았으면 인용을 금지한다.

Exit 2 = 미완료(2026-11-17): `fed/events.json` 이 없거나 읽히지 않거나 오늘 것이 아니거나,
기준일·장중·지표 자료가 없거나, 원문을 받았다고 한 사건의 원문 파일이 없다 — 섹션을 빼고 발행하지 않는다.
사건 책이 오늘 것이고 이벤트가 있는 날 섹션이 없으면, 없는 날 섹션이 있으면 위반(1).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verification.inputs import enforcing  # noqa: E402 — 1a 를 켰는가(꺼져 있으면 1a 전 판정 그대로)
from us.fed_gate import check, section  # noqa: E402


class Corrupt(Exception):
    pass


def load(path, strict=False):
    """없는 것과 깨진 것은 다르다 — 깨진 파일을 None 으로 돌려주면 비-코어 면제가
    사고를 덮는다(2026-09-01 codex 검토에서 포트폴리오 게이트가 겪은 것)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        if strict:
            raise Corrupt(f'{path} 를 읽을 수 없다: {e}')
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def attach_texts(book, datadir):
    """`events.json` 은 원문을 담지 않는다(수십만 자다). 대조 직전에 붙인다."""
    for e in (book or {}).get('events') or []:
        path = os.path.join(datadir, 'fed', f'{e.get("key")}.txt')
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            text = ''
        for s in e.get('sources') or []:
            # 원문 파일은 이벤트 단위로 하나다. 받아 둔 문서가 여럿이면 이어 붙인 것이라
            # 어느 문서에서 나온 인용인지까지는 가르지 않는다 — 그건 캡션이 밝힌다.
            if s.get('ok'):
                s['text'] = text
    return book


def _main_1a():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    def incomplete(why):
        # 섹션 없이 발행하지 않는다 — 수집을 다시 돌리고, 그래도 그러면 보류(2026-11-17 사용자 결정)
        print(f'FATAL: {why} — 미완료, 수집을 다시 돌린다', file=sys.stderr)
        sys.exit(2)

    try:
        book = load(os.path.join(args.datadir, 'fed', 'events.json'), strict=True)
        market = load(os.path.join(args.datadir, 'market_data.json'), strict=True)
        intraday = load(os.path.join(args.datadir, 'intraday.json'), strict=True)
        econ = load(os.path.join(args.datadir, 'econ_indicators.json'), strict=True)
    except Corrupt as e:
        incomplete(str(e))
    if book is None:
        incomplete('fed/events.json 이 없다')
    if not isinstance(book, dict) or not isinstance(book.get('events'), list):
        # 칸이 없거나 목록이 아니면 「연준 이벤트 없는 날」이 아니다(1a 구현 검토 2회차 F1)
        incomplete('fed/events.json 의 events 칸이 없거나 목록이 아니다')
    today = (market or {}).get('report_date')
    if not today:
        incomplete('market_data.json 에서 기준일을 읽을 수 없어 연준 책이 오늘 것인지 확인할 수 없다')
    if book.get('report_date') != today:
        incomplete(f'연준 이벤트 책이 {book.get("report_date")} 자인데 오늘은 {today} 다')
    if intraday is None or econ is None:
        incomplete('intraday.json 또는 econ_indicators.json 이 없다')
    for e in book.get('events') or []:
        if any(s.get('ok') for s in e.get('sources') or []) and \
                not os.path.isfile(os.path.join(args.datadir, 'fed', f'{e.get("key")}.txt')):
            incomplete(f'원문을 받았다고 한 사건 {e.get("key")} 의 원문 파일이 없다')

    attach_texts(book, args.datadir)

    errs = check(html, book, market, intraday, econ)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)

    fresh = [e for e in book.get('events') or [] if e.get('fresh')]
    if not fresh:
        print('연준 이벤트 없음 — 섹션 없이 발행 (OK)')
    else:
        print('연준 이벤트 OK — ' + ' · '.join(
            f'{e.get("kind_ko")}({e.get("date")})' for e in fresh))

def _main_pre1a():
    """1a 를 켜기 전의 판정 — 1a 전 `main()` 그대로."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    try:
        book = load(os.path.join(args.datadir, 'fed', 'events.json'), strict=True)
    except Corrupt as e:
        print(str(e))
        sys.exit(1)

    if book is None:
        if section(html):
            print('fed/events.json 이 없는데 「연준 이벤트」 섹션이 실렸다 — '
                  '대조할 원문이 없는 발언은 발행할 수 없다')
            sys.exit(1)
        print('fed/events.json 없음 — 섹션 없이 발행한다 (비-코어)', file=sys.stderr)
        return

    market = load(os.path.join(args.datadir, 'market_data.json')) or {}
    today = market.get('report_date')
    if not today:
        # 오늘이 언제인지 모르면 책이 오늘 것인지도 모른다. 섹션이 실려 있으면
        # **막는다** — 확인할 수 없는 것을 통과시키는 것이 게이트가 열린 채
        # 실패하는 방식이다(2026-09-02 codex 검토).
        if section(html):
            print('market_data.json 에서 기준일을 읽을 수 없어 연준 책이 오늘 것인지 '
                  '확인할 수 없다 — 섹션을 실은 채로는 발행할 수 없다')
            sys.exit(1)
        print('기준일 불명 — 섹션 없이 발행한다', file=sys.stderr)
        return
    if book.get('report_date') != today:
        # 어제 책으로 오늘 섹션을 세우지 않는다. 다만 리포트 전체를 세우지도 않는다.
        if section(html):
            print(f'연준 이벤트 책이 {book.get("report_date")} 자인데 오늘은 {today} 다 — '
                  '지난 이벤트를 오늘 날짜로 실을 수 없다')
            sys.exit(1)
        print(f'fed/events.json 이 {book.get("report_date")} 에서 멈춰 있다 — '
              '섹션 없이 발행한다 (비-코어)', file=sys.stderr)
        return

    attach_texts(book, args.datadir)
    intraday = load(os.path.join(args.datadir, 'intraday.json')) or {}
    econ = load(os.path.join(args.datadir, 'econ_indicators.json')) or {}

    errs = check(html, book, market, intraday, econ)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)

    fresh = [e for e in book.get('events') or [] if e.get('fresh')]
    if not fresh:
        print('연준 이벤트 없음 — 섹션 없이 발행 (OK)')
    else:
        print('연준 이벤트 OK — ' + ' · '.join(
            f'{e.get("kind_ko")}({e.get("date")})' for e in fresh))



def main():
    return _main_1a() if enforcing() else _main_pre1a()


if __name__ == '__main__':
    main()
