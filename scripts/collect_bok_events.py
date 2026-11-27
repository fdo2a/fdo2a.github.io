#!/usr/bin/env python3
"""한국은행 금통위 문서를 찾아 **원문을 통째로 받아 커밋한다** (2026-11-27).

  python scripts/collect_bok_events.py --datadir kr/data [--report-date YYYY-MM-DD]

KR 수집 잡(`collect-kr-data.yml`)의 비-코어 단계. 미국 `collect_fed_events.py` 와 같은 갈래다 — 파싱은 최소, 원문
덤프가 일이다. 이 스크립트가 책임지는 것은 「총재·금통위가 실제로 쓴 글이 레포 안에 글자 그대로 있는 것」 하나다.
robots.txt 가 허용하는 `/portal/` 아래(RSS·view.do·`/portal/cmmn/file/fileDown.do`)만 연다 — `/fileSrc/` 직링크 금지.

창은 발행일 D 로부터 10일. 결정문(RSS)·기자간담회(listYear.do 그날 행 — 모두발언 PDF + 자막)·의사록(RSS → 첨부 PDF).
의사록은 통화정책방향 결정회의의 것만(같은 RSS 에 다른 정기회의 의사록이 섞여 있다).
산출: kr/data/bok/{events.json, <key>.txt, seen.json, statements.json} — 일정 파일 schedule.json 은 손으로 채운다.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import cb_collect as CC  # noqa: E402
from common import cb_events as CE  # noqa: E402
from kr import bok_events as B  # noqa: E402

SOURCE = 'bok.or.kr RSS·listYear'


def _in_window(date, d):
    try:
        x = dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        return False
    return x <= d and (d - x).days <= CE.WINDOW_DAYS


def collect(report_date, outdir, fetch=CC.fetch):
    d = dt.date.fromisoformat(report_date)
    schedule = CC.load(os.path.join(outdir, 'schedule.json'))
    if not isinstance(schedule, dict):
        raise SystemExit(f'{outdir}/schedule.json 이 없다 — 일정 파일 없이 수집하지 않는다')
    sched_meetings = {m['meeting'] for m in schedule.get('meetings') or []}
    seen = CC.load(os.path.join(outdir, 'seen.json'), {}) or {}
    statements = CC.load(os.path.join(outdir, 'statements.json'), []) or []
    rows, extra, failed = [], {}, []

    body, note = fetch(B.DECISION_RSS)
    decisions = B.decision_items(CC.text_of(body)) if body else []
    if not decisions:
        failed.append('rss:decision')
        print(f'  결정문 RSS: 실패 ({note})', file=sys.stderr)
    decided = {x['meeting_date'] for x in decisions} | sched_meetings
    inside = [x for x in decisions if _in_window(x['meeting_date'], d)]
    for item in decisions:
        key = CE.event_key('bok_decision', item['meeting_date'])
        text = item['text'] if B.paragraphs(item['text']) or len(item['text']) > 500 else None
        if not _in_window(item['meeting_date'], d):
            # 창 밖 결정문은 창 안 결정문의 「직전 결정문」일 때만 남긴다 — 비교용(이벤트 아님)
            prev_of = [x for x in inside
                       if max((y['meeting_date'] for y in decisions if y['meeting_date'] < x['meeting_date']),
                              default=None) == item['meeting_date']]
            if text and prev_of:
                statements.append(key)
                if not os.path.exists(os.path.join(outdir, f'{key}.txt')):
                    extra[key] = f'# 통화정책방향 결정문\n# 원문: {item["link"]}\n\n{text}'
            continue
        if text:
            statements.append(key)
        rows.append(CC.event_row('bok_decision', item['meeting_date'], item['meeting_date'], item['title'],
                                 item['link'], [CC.source('statement', '통화정책방향 결정문', item['link'], text,
                                                          'rss')], seen, report_date))

    meetings = sorted(m for m in decided if _in_window(m, d))
    pages = {}
    for meeting in meetings:
        year = meeting[:4]
        if year not in pages:
            page, note = fetch(B.LIST_YEAR.format(year=year), min_bytes=5000)
            pages[year] = CC.text_of(page) if page else None
            if page is None:
                failed.append(f'listYear:{year}')
        view, pdf = B.presser_row(pages[year], meeting)
        if not view and not pdf:
            continue                       # 행이 아직 없다 — 일정표 대조 알림이 따로 본다
        sources = []
        if pdf:
            b, note = fetch(pdf, min_bytes=1000)
            sources.append(CC.source('opening', '기자간담회 모두발언', pdf, CC.pdf_text(b), note))
        if view:
            b, note = fetch(view, min_bytes=5000)
            sources.append(CC.source('subtitle', '기자간담회 질의응답 자막', view,
                                     B.subtitle_text(CC.text_of(b)) if b else None, note))
        for s in sources:
            if not s['ok']:
                failed.append(f'presser:{meeting}:{s["role"]}')
        rows.append(CC.event_row('bok_presser', meeting, meeting, f'통화정책방향 관련 총재 기자간담회({meeting})',
                                 view or pdf, sources, seen, report_date))

    body, note = fetch(B.MINUTES_RSS)
    minutes = B.minutes_items(CC.text_of(body)) if body else []
    if not minutes:
        failed.append('rss:minutes')
    for item in minutes:
        if not _in_window(item['published'], d) or item['meeting_date'] not in decided:
            continue
        page, note = fetch(item['link'], min_bytes=5000)
        pdf = B.minutes_pdf(CC.text_of(page)) if page else None
        text = None
        if pdf:
            b, note = fetch(pdf, min_bytes=1000)
            text = CC.pdf_text(b)
        if not text:
            failed.append(f'minutes:{item["meeting_date"]}')
        rows.append(CC.event_row('bok_minutes', item['meeting_date'], item['published'], item['title'],
                                 item['link'], [CC.source('minutes', '금통위 의사록', pdf or item['link'], text, note)],
                                 seen, report_date))

    diff = None
    current = [r for r in rows if r['kind'] == 'bok_decision' and r['sources'][0]['ok']]
    if current:
        cur = max(current, key=lambda r: r['meeting_date'])
        prev = [x for x in decisions if x['meeting_date'] < cur['meeting_date']]
        if prev:
            p = max(prev, key=lambda x: x['meeting_date'])
            diff = B.paragraph_diff(p['text'], cur['sources'][0]['text'])
            if diff is not None:
                diff.update({'key': cur['key'], 'previous': p['meeting_date']})
    return CC.write_all(outdir, report_date, rows, extra, seen, statements, diff, failed, SOURCE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='kr/data')
    ap.add_argument('--report-date', default=None)
    args = ap.parse_args(argv)
    rd = args.report_date
    if not rd:
        with open(os.path.join(args.datadir, 'kr_market_data.json'), encoding='utf-8') as fh:
            rd = json.load(fh)['report_date']
    book = collect(rd, os.path.join(args.datadir, 'bok'))
    print(f'한국은행 금통위 문서 — {rd}')
    CC.report(book)
    return 0


if __name__ == '__main__':
    sys.exit(main())
