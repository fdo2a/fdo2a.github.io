#!/usr/bin/env python3
"""KR 발행 게이트 — 「한국은행 금통위」 칸 (2026-11-27).

  python3 scripts/check_bok.py --html <글> --date D --datadir kr/data --repo .
  python3 scripts/check_bok.py --diag --date D --datadir kr/data --repo .     # 작성 전 — 오늘 실을 이벤트

의무는 `common/cb_events.due_events` 가 정한다: 수집기가 커밋한 `<datadir>/bok/events.json`(없어도 된다),
손으로 채운 `<datadir>/bok/schedule.json`(없으면 멈춘다), 그리고 **`--repo` 의 HEAD 에 커밋된** `kr/posts/*.html`
가운데 날짜가 D 보다 앞선 글의 `data-cb-event` 표식(발행본 장부). 수집이 실패했다고 브리프를 세우지 않는다 —
결정일에 원문이 없으면 칸은 열되 인용·수치 없이 쓴다.

Exit 0 = 발행 가능 / 1 = 위반(한 줄씩) / 2 = 미완료(일정 파일 없음·깨짐, 원문을 받았다는 이벤트의 원문 파일 없음,
발행본 장부를 읽지 못함).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import cb_events as CE  # noqa: E402
from common import cb_gate as G  # noqa: E402
from kr import bok_gate  # noqa: E402

POSTS = 'kr/posts'
DATA_BLOBS = ('kr_market_data.json', 'kr_econ.json')


def fatal(why):
    print(f'FATAL: {why} — 미완료', file=sys.stderr)
    sys.exit(2)


def _load(path, required):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        if required:
            fatal(f'{path} 이 없다')
        return None
    except ValueError as e:
        fatal(f'{path} 를 읽을 수 없다: {e}')


def book_and_due(datadir, repo, date):
    """-> (events.json 내용 | None, 일정, due 행(원문 글이 붙은 것), 발행본 장부)."""
    bokdir = os.path.join(datadir, 'bok')
    schedule = _load(os.path.join(bokdir, 'schedule.json'), required=True)
    book = _load(os.path.join(bokdir, 'events.json'), required=False)
    if book is not None and not isinstance((book or {}).get('events'), list):
        fatal(f'{bokdir}/events.json 의 events 칸이 목록이 아니다')
    try:
        covered = CE.covered_from_posts(repo, POSTS, date)
    except RuntimeError as e:
        fatal(f'발행본 장부를 읽지 못했다: {e}')
    try:
        due = CE.due_events((book or {}).get('events'), schedule, covered, date)
    except CE.ScheduleError as e:
        fatal(str(e))
    for e in due:
        if not CE.has_text(e):
            continue
        path = os.path.join(bokdir, f'{e["key"]}.txt')
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            fatal(f'원문을 받았다고 한 이벤트 {e["key"]} 의 원문 파일이 없다')
        e['sources'] = [dict(s, text=text) if s.get('ok') else s for s in e.get('sources') or []]
    return book, schedule, due, covered


def diff_for(book, due):
    diff = (book or {}).get('diff')
    keys = {e['key'] for e in due}
    return diff if diff and diff.get('key') in keys else None


def _before_feature(args):
    """켜기 전 날짜이고 자료 폴더에 일정 파일이 없다(발행 커밋 재연) — 일정 파일이 있으면 그 start 가 정한다."""
    return args.date < bok_gate.START and not os.path.exists(os.path.join(args.datadir, 'bok', 'schedule.json'))


def diag(args):
    if _before_feature(args):
        print(f'한국은행 금통위: {bok_gate.START} 전 날짜 — 칸을 쓰지 않는다')
        return 0
    book, schedule, due, covered = book_and_due(args.datadir, args.repo, args.date)
    bokdir = os.path.join(args.datadir, 'bok')
    if not due:
        print(f'한국은행 금통위: {args.date} 에 실을 이벤트 없음 — 「한국은행 금통위」 칸을 쓰지 않는다')
    else:
        print(f'한국은행 금통위: {args.date} 에 실을 이벤트 {len(due)}건 — <section data-section="bok"> 칸을 연다')
        for e in due:
            where = '원문 없음 — 인용·수치·아이디어 금지, 결정 사실만 기사 귀속으로' if not CE.has_text(e) \
                else f'원문 {os.path.join(bokdir, e["key"] + ".txt")}'
            print(f'  - {e["key"]} · {e["kind_ko"]} · 공개 {e["date"]} · {where}')
        d = diff_for(book, due)
        if d:
            names = ', '.join(f'{c["para"]}.{c["name"]}' for c in d['changed'])
            print(f'  결정문 변경점(직전 {d.get("previous")}): 바뀐 문단 {names or "없음"} — '
                  f'{os.path.join(bokdir, "events.json")} 의 diff')
        else:
            print('  결정문 변경점: 없음(계산하지 않았다)')
    try:
        missing = CE.missing_scheduled(schedule, (book or {}).get('events'), args.date)
    except CE.ScheduleError as e:
        fatal(str(e))
    for m in missing:
        print(f'  ! 예정된 {m["kind_ko"]}({m["date"]}) 원문을 못 받았다 — 칸을 요구하지 않는다(알림)')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html')
    ap.add_argument('--date', required=True)
    ap.add_argument('--datadir', default='kr/data')
    ap.add_argument('--repo', default='.')
    ap.add_argument('--diag', action='store_true')
    args = ap.parse_args(argv)
    if args.diag:
        return diag(args)
    if not args.html:
        ap.error('--html 이 필요하다(작성 전 진단은 --diag)')
    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        fatal(f'{args.html} 을 읽을 수 없다: {e}')
    if _before_feature(args):
        # 켜기 전 날짜의 재연(일정 파일이 아직 없던 커밋) — 그날 글에는 이 칸이 없었다. 칸이 있으면 막는다
        if G.sections(html, bok_gate.SECTION):
            print(f'{bok_gate.START} 전 날짜인데 「{bok_gate.TITLE}」 칸이 실렸다')
            return 1
        print(f'한국은행 금통위: {bok_gate.START} 전 날짜 — 해당 없음 (OK)')
        return 0
    book, _schedule, due, _covered = book_and_due(args.datadir, args.repo, args.date)
    blobs = [b for b in (_load(os.path.join(args.datadir, n), required=False) for n in DATA_BLOBS) if b]
    errs = bok_gate.check(html, due, args.date, diff=diff_for(book, due), data_blobs=blobs)
    if errs:
        for e in errs:
            print(e)
        return 1
    if due:
        print('한국은행 금통위 OK — ' + ' · '.join(f'{e["kind_ko"]}({e["date"]})' for e in due))
    else:
        print('한국은행 금통위 이벤트 없음 — 칸 없이 발행 (OK)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
