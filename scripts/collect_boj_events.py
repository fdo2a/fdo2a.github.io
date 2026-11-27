#!/usr/bin/env python3
"""일본은행 금융정책결정회의 문서를 찾아 **일본어 원문을 통째로 받아 커밋한다** (2026-11-27).

  python scripts/collect_boj_events.py --session YYYY-MM-DD [--datadir japan/data]

일본 일간 수집 잡(`collect-japan-daily.yml`)의 비-코어 단계. 미국 `collect_fed_events.py` 와 같은 갈래 — 원문 덤프가
일이다. 무엇을 찾을지는 손으로 채운 일정 파일(`japan/data/boj/schedule.json`)이 정한다: 세션 S 로부터 10일 창 안에
공개 예정일이 든 문서만 목록 페이지에서 찾아 받는다. 목록의 「（参考）」 부속 문서는 거른다. 영문판은 쓰지 않는다
(회견 기록은 영문이 없고, 원문 우선).

산출: japan/data/boj/{events.json, <key>.txt, seen.json, statements.json}. KEY 는 회의 마지막 날 기준, `date` 는 공개일
(회견은 목록의 실제 파일 날짜, 주요 의견·의사요지는 일정표의 공개일).
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import cb_collect as CC  # noqa: E402
from common import cb_events as CE  # noqa: E402
from japan import boj_events as B  # noqa: E402

SOURCE = 'boj.or.jp 결정회의 자료'


def collect(session, outdir, fetch=CC.fetch):
    d = dt.date.fromisoformat(session)
    schedule = CC.load(os.path.join(outdir, 'schedule.json'))
    if not isinstance(schedule, dict):
        raise SystemExit(f'{outdir}/schedule.json 이 없다 — 일정 파일 없이 수집하지 않는다')
    docs = [x for x in CE.schedule_docs(schedule)
            if dt.date.fromisoformat(x['date']) <= d and (d - dt.date.fromisoformat(x['date'])).days <= CE.WINDOW_DAYS]
    seen = CC.load(os.path.join(outdir, 'seen.json'), {}) or {}
    statements = CC.load(os.path.join(outdir, 'statements.json'), []) or []
    rows, extra, failed, pages = [], {}, [], {}

    def page(url):
        if url not in pages:
            body, note = fetch(url, min_bytes=3000)
            pages[url] = CC.text_of(body) if body else None
            if body is None:
                failed.append(f'index:{url.rsplit("/", 2)[-2]}')
        return pages[url]

    def pdf(url):
        body, note = fetch(url, min_bytes=1000)
        return CC.pdf_text(body), note

    diff = outlook_diff = None
    for doc in docs:
        kind, meeting = doc['kind'], doc['meeting_date']
        year = meeting[:4]
        sources, url, date = [], None, doc['date']
        if kind == 'boj_statement':
            listing = page(B.STATE_INDEX.format(year=year))
            for i, u in enumerate(B.statement_links(listing, meeting)):
                text, note = pdf(u)
                sources.append(CC.source('statement' if i == 0 else 'statement_extra', '금융정책 결정 공표문', u, text,
                                         note))
            url = sources[0]['url'] if sources else None
        elif kind == 'boj_outlook':
            listing = page(B.OUTLOOK_INDEX)
            got = [u for ym, u in B.outlook_links(listing) if ym == meeting[:7]]
            if got:
                text, note = pdf(got[0])
                sources.append(CC.source('outlook', '경제·물가 정세의 전망(기본 견해)', got[0], text, note))
                url = got[0]
        elif kind == 'boj_presser':
            for y in sorted({year, doc['date'][:4]}):
                pub, u = B.presser_link(page(B.KAIKEN_INDEX.format(year=y)), meeting)
                if u:
                    text, note = pdf(u)
                    sources.append(CC.source('presser', '총재 정례 기자회견 기록', u, text, note))
                    url, date = u, pub
                    break
        else:
            index, prefix = ((B.OPINION_INDEX, 'opi') if kind == 'boj_opinions' else (B.MINUTES_INDEX, 'g'))
            for y in sorted({year, doc['date'][:4]}):
                u = B.doc_link(page(index.format(year=y)), prefix, meeting)
                if u:
                    text, note = pdf(u)
                    sources.append(CC.source(kind.split('_')[1], CE.label(kind), u, text, note))
                    url = u
                    break
        if not sources:
            continue                       # 아직 목록에 없다 — 일정표 대조 알림(missing_scheduled)이 본다
        for s in sources:
            if not s['ok']:
                failed.append(f'{kind}:{meeting}')
        row = CC.event_row(kind, meeting, date, CE.label(kind), url, sources, seen, session)
        rows.append(row)
        if kind == 'boj_statement' and sources[0]['ok']:
            statements.append(row['key'])
            diff = _statement_diff(row, outdir, page(B.STATE_INDEX.format(year=year)), pdf, extra, statements) or diff
        if kind == 'boj_outlook' and sources[0]['ok']:
            outlook_diff = _outlook_diff(row, page(B.OUTLOOK_INDEX), pdf) or outlook_diff
    return CC.write_all(outdir, session, rows, extra, seen, statements, diff, failed, SOURCE, outlook_diff=outlook_diff)


def _statement_diff(row, outdir, listing, pdf, extra, statements):
    prev = [m for m in B.statement_meetings(listing) if m < row['meeting_date']]
    if not prev:
        return None
    pm = prev[-1]
    key = CE.event_key('boj_statement', pm)
    path = os.path.join(outdir, f'{key}.txt')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            prev_text = fh.read()
    else:
        urls = B.statement_links(listing, pm)
        prev_text, _note = pdf(urls[0]) if urls else (None, None)
        if not prev_text:
            return None
        extra[key] = f'# 금융정책 결정 공표문\n# 원문: {urls[0]}\n\n{prev_text}'
        statements.append(key)
    diff = B.statement_diff(prev_text, row['sources'][0]['text'])
    if diff is not None:
        diff.update({'key': row['key'], 'previous': pm})
    return diff


def _outlook_diff(row, listing, pdf):
    ym = row['meeting_date'][:7]
    prev = [(m, u) for m, u in B.outlook_links(listing) if m < ym]
    if not prev:
        return None
    prev_text, _note = pdf(prev[-1][1])
    if not prev_text:
        return None
    diff = B.outlook_redline(prev_text, row['sources'][0]['text'])
    if diff is not None:
        diff.update({'key': row['key'], 'previous': prev[-1][0]})
    return diff


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True)
    ap.add_argument('--datadir', default='japan/data')
    args = ap.parse_args(argv)
    book = collect(args.session, os.path.join(args.datadir, 'boj'))
    print(f'일본은행 결정회의 문서 — {args.session}')
    CC.report(book)
    return 0


if __name__ == '__main__':
    sys.exit(main())
