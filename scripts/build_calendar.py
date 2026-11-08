#!/usr/bin/env python3
"""다음 열흘 일정을 `data/calendar.json` 으로 만든다.

  python3 scripts/build_calendar.py --datadir data
  python3 scripts/build_calendar.py --datadir data --date 2026-09-11

네 가지를 싣는다 — 지수 만기(셋째 금요일 규칙)와 연준 블랙아웃은 **계산**이고, 경제지표
일정(FRED)과 국채 입찰(TreasuryDirect TA_WS, FiscalData 폴백)은 **수집**이다. 수집이 실패하면 그 항목을
빼고 `missing` 에 적는다. `--offline` 은 수집을 아예 건너뛴다.

**키가 없는 날 경제지표 일정은 빈다.** FRED 폴백(graph CSV)에는 릴리스 일정표가 없다.
어제 받은 일정을 오늘 것처럼 인쇄하는 대신 없다고 적는다 — 낡은 일정은 없는 일정보다
나쁘고, 같은 이유로 낡은 FOMC 표도 쓰지 않는다.

**FOMC 회의일은 이 스크립트가 만들지 않는다.** `data/fomc_dates.json`
(`update_fomc_dates.py` 가 연준 원문으로 갱신)을 `fomc_official.load()` 로 읽고, 없거나
공식 확인이 45일을 넘겼으면 그 항목을 빼고 `missing` 에 적는다. 레포가 아는 FOMC 날짜는 웹서치 산문 한
줄뿐이라 나머지를 채우면 수집이 아니라 창작이다 — 이 파이프라인에서 삭제는 언제나
창작보다 낫다.

`fomc_dates.json` 형식:

    {"source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
     "verified_at": "2026-09-14",
     "meetings": ["2026-09-16", "2026-10-28"]}

`verified_at`(연준 원문 확인일, KST)이 없거나 45일을 넘겼으면 읽지 않는다.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import fomc_official as F  # noqa: E402
from us import auctions as A  # noqa: E402
from us import census_calendar as CC  # noqa: E402
from us import upcoming as U  # noqa: E402
from us.calendar import HORIZON_DAYS, build  # noqa: E402
from us.fred import FredClient, FredError, annotation, scrub  # noqa: E402
from us.macro_metrics import RELEASES  # noqa: E402


def _warn_unresolved(reasons, key):
    """이유에는 FRED 응답의 이름이 들어간다 — 응답은 무엇이든 담을 수 있다. 키를 가리고
    (codex 11/07 구현 #2), 개행 뒤 `::warning::` 이 Actions 명령으로 읽히지 않게 한 줄로
    만든다(구현 2회 #1)."""
    for slug, why in sorted(reasons.items()):
        print(f'경고: {slug} 일정을 비웠다 — {annotation(scrub(why, key))}', file=sys.stderr)


def _add_reason(info, slug, why):
    """비운 이유를 **덧붙인다** — FRED 쪽과 Census 쪽 이유가 둘 다 남아야 원인을 찾는다
    (codex 11/08 구현 #5)."""
    old = info['unresolved'].get(slug)
    if old and why not in old:
        info['unresolved'][slug] = f'{old}; {why}'
    elif not old:
        info['unresolved'][slug] = why


def _census_get(url):
    """Census 목록 페이지 본문. 원문 수집기와 같은 브라우저 흉내 GET 을 쓴다(census.gov 는 봇을 막는다)."""
    from fetch_releases import http_get
    resp, note = http_get(url)
    if resp is None:
        raise CC.CensusError(note)
    return resp.text


def _collect(report_date, start, end):
    """-> (events, auctions, missing, info). 비-코어: 실패는 기록하고 건너뛴다.

    `info` = {'release_ids': {slug: id}, 'unresolved': {slug: 이유}} — 확인하지 못해 일정표에서
    **비운** 지표와 그 이유. `missing` 의 `releases` 는 FRED 일정 수집 전체가, `census` 는 Census
    일정표 전체가 실패한 경우다.

    Census 지표(소매·신규주택·내구재·주택착공·무역수지·건설지출·공장주문)는 Census 날짜를 FRED
    로 확인해 싣는다(`upcoming.census_events`). 둘 중 하나라도 못 읽으면 그 지표는 빈다.
    """
    events, auctions, missing = [], [], []
    info = {'release_ids': {}, 'unresolved': {}}

    census = CC.collect(_census_get, start, end)
    if all(slot['why'] for slot in census.values()):
        missing.append('census')

    try:
        client = FredClient()
        client.preflight()
        resolved, unresolved = U.resolve_releases(client.series_release)
        info['release_ids'] = {slug: rid for slug, (rid, _n) in resolved.items()}
        # 빈 결과 가드보다 먼저 남긴다 — 전부 실패해 0건이면 그 이유가 사라진다(codex 2026-10-17 #10).
        info['unresolved'].update(unresolved)
        # 일정 조회 **전에** 찍는다 — 그 조회가 죽으면 실제 릴리스 이름이 로그에서 사라진다
        # (codex 11/07 구현 2회 #2).
        _warn_unresolved(unresolved, client.key)
        rows = client.release_dates(start, end)
        got, held = U.release_events(rows, RELEASES, resolved)
        c_got, c_held, c_notes = U.census_events(census, rows, resolved, RELEASES)
        for slug, why in sorted(c_notes.items()):
            print(f'경고: {slug} 시각을 비웠다 — {annotation(scrub(why, client.key))}', file=sys.stderr)
        held = {**held, **c_held}
        for slug, why in held.items():
            _add_reason(info, slug, why)
            info['release_ids'].pop(slug, None)
        _warn_unresolved(held, client.key)
        if not (got or c_got):
            # 조용히 0건이 되는 경로가 있다(FRED 가 시리즈를 옮기거나 키가 거부되면).
            # 빈 결과를 성공으로 적으면 그 침묵이 영원히 안 들린다.
            raise FredError('release calendar matched nothing in the window')
        events += got + c_got
    except Exception as e:
        missing.append('releases')
        # FRED 가 죽으면 Census 지표도 확인할 수 없다 — 비-Census 와 따로, 이유를 남긴다.
        # Census 쪽 이유도 로그에 남긴다 — calendar.json 에는 지표 이름만 간다(codex 11/08 구현 2회 #2).
        _warn_unresolved({k: v['why'] for k, v in census.items() if v['why']}, None)
        for slug in CC.CENSUS_NAMES:
            if census[slug]['why']:
                _add_reason(info, slug, census[slug]['why'])
            _add_reason(info, slug, f'FRED 일정 확인 실패: {scrub(str(e))}')
            info['release_ids'].pop(slug, None)
        # 예외 문자열에도 응답 조각이 들어 있을 수 있다 — 키를 가리고 한 줄로(codex 11/08 구현 #6).
        print(f'경제지표 일정 실패: {annotation(scrub(str(e)))}', file=sys.stderr)

    try:
        rows = _auction_rows(report_date, end)
        events += U.auction_events(rows, start, end)
        auctions = U.auction_results(rows, report_date)
    except Exception as e:
        missing.append('auctions')
        print(f'국채 입찰 실패: {annotation(scrub(str(e)))}', file=sys.stderr)

    return events, auctions, missing, info


def _fresh(rows, report_date, date_of, btc_of):
    """기준일까지 7일 안에 **결과가 붙은** 행이 있는가. 공고 행의 미래 날짜나 8일 넘은
    결과로는 신선하다고 보지 않는다(codex 구현 검토 #6)."""
    floor = (report_date - dt.timedelta(days=7)).isoformat()
    top = report_date.isoformat()
    return any(floor <= (date_of(r) or '') <= top and A._num(btc_of(r)) for r in rows)


def _auction_rows(report_date, end):
    """입찰 행(FiscalData 모양). 정본은 TreasuryDirect TA_WS 다.

    FiscalData `auctions_query` 는 2026-10-22 입찰 뒤로 행이 끊겼고, 빈 목록이 예외가
    아니라서 일정표와 `recent_auctions` 가 2주 동안 조용히 비었다. 그래서 두 원천 모두
    **기준일까지 7일 안에 결과가 붙은 행이 없으면 실패로 센다.**
    """
    try:
        span = max((dt.date.today() - report_date).days, 0) + 14
        rows = A.fetch_results(span) + A.fetch_announced(span + 10)
        if not _fresh(rows, report_date,
                      lambda r: (r.get('competitiveAuctionCloseDate') or '')[:10],
                      lambda r: r.get('bidToCoverRatio')):
            raise RuntimeError('TA_WS 에 기준일까지 7일 안의 결과가 없다')
        # 결과 목록과 공고 목록이 같은 입찰을 둘 다 담는다 — 결과가 붙은 행을 남긴다.
        best = {}
        for r in rows:
            k = (r.get('cusip'), (r.get('competitiveAuctionCloseDate') or '')[:10])
            if k not in best or (A._num(r.get('bidToCoverRatio'))
                                 and not A._num(best[k].get('bidToCoverRatio'))):
                best[k] = r
        return [A.to_fiscal(r) for r in best.values()]
    except Exception as e:
        print(f'TA_WS 입찰 실패 — FiscalData 로 물러선다: {e}', file=sys.stderr)
    rows = U.fetch_auctions(report_date - dt.timedelta(days=7), end)
    if not _fresh(rows, report_date, lambda r: r.get('auction_date'),
                  lambda r: r.get('bid_to_cover_ratio')):
        raise RuntimeError('FiscalData 에 기준일까지 7일 안의 결과가 없다 — 원천이 멈췄다')
    # FiscalData 의 `total_accepted` 는 비경쟁·SOMA 를 포함한다. 작성자에게 넘기는 비중은
    # 경쟁입찰 낙찰액 기준이므로, 분모가 다른 폴백에서는 비중을 싣지 않는다(#7).
    for r in rows:
        r['indirect_bidder_accepted'] = r['primary_dealer_accepted'] = None
    return rows


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
    # 신선도는 **실행일(KST)** 로 잰다. 확인일은 KST 로 찍히는데 report_date 는 그
    # 전날 미국 세션이라, report_date 로 재면 오늘 받은 표가 「미래 확인」으로 거부된다.
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    meetings, note = F.load(os.path.join(args.datadir, 'fomc_dates.json'), as_of=today)
    print(f'FOMC 일정표: {note}', file=sys.stderr)

    start = report_date + dt.timedelta(days=1)
    end = report_date + dt.timedelta(days=args.horizon)
    offline_info = {'release_ids': {}, 'unresolved': {}}
    extra, auctions, missing, info = (([], [], ['releases', 'auctions'], offline_info) if args.offline
                                      else _collect(report_date, start, end))
    book = build(report_date, meetings=meetings, horizon_days=args.horizon,
                 extra=extra, missing=missing, auctions=auctions)
    # `missing`·`complete` 와 따로 둔다 — 일간 게이트의 완성도 판정은 바꾸지 않고 손실만 드러낸다.
    # `unresolved` = 발표 번호를 못 얻어 비운 지표(「일정 없음」이 아니라 「확인 못 함」).
    # 2026-11-07 전 파일의 `ambiguous`(이름이 모호해 뺀 지표)를 대신한다.
    book['unresolved'] = sorted(info['unresolved'])
    book['release_ids'] = dict(sorted(info['release_ids'].items()))
    out = args.out or os.path.join(args.datadir, 'calendar.json')
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, indent=2, ensure_ascii=False)

    kinds = {}
    for e in book['events']:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
    print(f"{out} — {len(book['events'])}건 " + (str(kinds) if kinds else '')
          + (f" · 빠짐 {book['missing']}" if book['missing'] else '')
          + (f" · 확인 못 해 비운 지표 {book['unresolved']}" if book['unresolved'] else ''))
    if book['recent_auctions']:
        top = book['recent_auctions'][0]
        print(f"직전 입찰 {top['date']} {top['term']} — 응찰 {top['bid_to_cover']}"
              f" · 간접 {top['indirect_pct']}%")
    if book['blackout']['active']:
        print(f"연준 블랙아웃 중 — {book['blackout']['until']}까지")


if __name__ == '__main__':
    main()
