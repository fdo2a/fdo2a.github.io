#!/usr/bin/env python3
"""§10 등급을 하루 굴린다 -> data/portfolio.json · portfolio_state.json · 원장.

수집 워크플로에서 collect_market_data.py 바로 뒤에 돈다. 루틴(에이전트)은 이 결과를
렌더할 뿐 산술을 하지 않는다.

하루 시차가 설계다 — 이 시점의 `stance.json` 은 **어제 발행된 책**이고, 그 등급을
오늘 종가에 담는다. 마감 뒤에 정한 것을 그날 종가에 사면 룩어헤드다.

  python scripts/build_portfolio.py --datadir data
"""

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import portfolio_io as IO  # noqa: E402
from us.history import append_jsonl  # noqa: E402
from us.portfolio import BASE_NAV, open_state  # noqa: E402


def as_date(value):
    """ISO 날짜만 날짜로 인정한다. 아니면 None — 문자열 비교로 넘어가지 못하게."""
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def calendar_gaps(prices_file, since, until, ledger_dates):
    """시장 달력과 원장을 맞대 «수집이 아예 돌지 않은 세션»을 찾는다.

    그런 날은 굴리기 실패로도 남지 않아서, 다음 실행이 이틀치를 하루로 인쇄한다.
    달력을 확인할 수 없으면 «빠진 것 없음»이 아니라 **중단**이다 — 그것이 정확히
    이 구멍이다(2026-09-01 codex 3차). 수집 산출물이 아예 없는 실행(로컬 재생성)만
    예외로 두고, 그 경우 오늘은 이미 결측으로 적혀 있다.
    """
    try:
        # 창은 **이번 실행 전** 원장의 마지막 날부터 오늘까지다. 그보다 앞은 지난
        # 실행들이 이미 봤다. 굴린 뒤 날짜로 재면 창이 비어 아무것도 못 잡는다.
        return IO.missing_sessions(prices_file.get('sessions'), since, until,
                                   ledger_dates)
    except ValueError as e:
        print(f'FATAL: {e} — 달력을 확인하지 못한 채로는 책을 내지 않는다',
              file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()
    d = args.datadir

    market = IO.load(os.path.join(d, 'market_data.json'))
    if not market or not market.get('report_date'):
        print('FATAL: market_data.json missing or has no report_date', file=sys.stderr)
        sys.exit(1)
    report_date = market['report_date']

    prices_file = IO.load(os.path.join(d, 'portfolio_prices.json')) or {}
    if not prices_file:
        # 없거나 깨져 {} 로 읽힌 파일을 «가격 없는 날»로 흘려보내면 달력 검사가
        # 통째로 우회된다. 상태가 있든 없든 여기서 멈춘다(2026-09-01 codex 4차).
        print('FATAL: portfolio_prices.json 이 없거나 읽을 수 없다 — 책을 내지 않는다',
              file=sys.stderr)
        sys.exit(1)
    prices = prices_file.get('closes') or {}
    priced = prices_file.get('report_date') == report_date and not prices_file.get('missing')

    stance = IO.load(os.path.join(d, 'stance.json')) or {}
    try:
        stance_grades = IO.grades_of(stance, strict=True)
    except ValueError as e:
        print(f'WARN: 등급 책을 온전히 읽지 못했다 — {e}', file=sys.stderr)
        stance_grades = None
    # 날짜가 없거나 날짜가 아닌 책은 출처를 세울 수 없다 — 등급이 온전해도 적용하지
    # 않는다. 문자열로 견주면 「09/05/2026」이 「2026-08-31」보다 작다고 나와 미래
    # 책이 그대로 적용된다(2026-09-01 codex 5차).
    if stance_grades is not None and as_date(stance.get('report_date')) is None:
        print(f'WARN: 등급 책의 기준일을 읽을 수 없다({stance.get("report_date")!r}) — '
              f'출처를 세울 수 없어 적용하지 않는다', file=sys.stderr)
        stance_grades = None
    have_stance = stance_grades is not None
    grades_from = stance.get('report_date') if have_stance else None

    ledger_path = os.path.join(d, 'history', 'portfolio.jsonl')
    try:
        rows = IO.read_ledger(ledger_path)
    except ValueError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        sys.exit(1)
    state_blob = IO.load(os.path.join(d, 'portfolio_state.json'))
    generated = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    gaps = (IO.load(os.path.join(d, 'portfolio.json')) or {}).get('gaps') or []
    state = None
    if state_blob:
        state = {'inception': state_blob['inception'],
                 'active': state_blob['active'], 'bench': state_blob['bench']}

    # 등급 책이 없으면 **중립으로 되돌리지 않는다**. 빈 dict 를 등급으로 읽으면
    # 전 자산군이 0으로 리밸런싱되고, 그것이 진짜 판단인지 사고인지 아무 데도 남지
    # 않는다(2026-09-01 codex 검토). 없으면 어제 비중을 그대로 얼린다.
    # **하루 시차를 기계로 강제한다.** 오늘 날짜로 찍힌 책(또는 미래 날짜)을 오늘
    # 종가에 적용하면 마감 뒤에 정한 것을 그날 종가에 사는 룩어헤드가 된다.
    # 설정일만 예외다 — 첫 손익이 다음 세션부터라 앞을 보지 않는다(2026-09-01 codex 4차).
    applied_on, today = as_date(grades_from), as_date(report_date)
    if today is None:
        print(f'FATAL: 기준일을 읽을 수 없다: {report_date!r}', file=sys.stderr)
        sys.exit(1)
    lookahead = applied_on is not None and (
        applied_on > today or (bool(state) and applied_on == today))
    if have_stance and lookahead:
        print(f'WARN: 등급 책이 {grades_from} 자로 오늘({report_date}) 이후다 — '
              f'룩어헤드를 막기 위해 적용하지 않는다', file=sys.stderr)
        stance_grades, have_stance, grades_from = None, False, None

    frozen = not have_stance
    if have_stance:
        grades = stance_grades
    elif state:
        grades = dict(state['active']['grades'])
        # 동결할 때 출처를 지우면 «어느 책에서 나온 비중인가»가 사라진다.
        grades_from = (state_blob or {}).get('grades_from')
        print('WARN: stance.json 을 쓸 수 없다 — 어제 비중과 그 출처를 동결한다',
              file=sys.stderr)
    else:
        print('FATAL: 등급 책도 상태도 없다 — 중립으로 시작하지 않는다', file=sys.stderr)
        sys.exit(1)

    ledger_end_before = state['active']['date'] if state else None

    if state and state['active']['date'] == report_date:
        # 같은 날 두 번째 실행. 굴리기를 건너뛰므로 **출처도 그대로 둔다** —
        # 여기서 새 책 날짜로 갈아 끼우면 비중은 옛 등급인데 발행본은 새 등급을
        # 적용했다고 주장하게 된다(2026-09-01 codex 2차).
        grades_from = (state_blob or {}).get('grades_from', grades_from)
        frozen = bool((state_blob or {}).get('stance_frozen', frozen))
        print(f'already rolled to {report_date} — nothing to do')
    elif not priced:
        # 값이 없는 날을 앞의 값으로 메우지 않는다. 좌수가 그대로이므로 다음 성공한
        # 날의 수익률이 이 구간을 정확히 덮고, 건너뛴 사실은 발행본이 고지한다.
        if report_date not in gaps:
            gaps.append(report_date)
        print(f'WARN: {report_date} 종가 결측 — 원장을 굴리지 않는다 '
              f'(missing={prices_file.get("missing")})', file=sys.stderr)
    elif state is None:
        state = open_state(report_date, prices, grades, BASE_NAV)
        print(f'bootstrapped at {report_date} (기준가 {BASE_NAV:.2f})')
    else:
        try:
            state, moved = IO.rebase(state, prices_file.get('recent'))
            if moved:
                print(f'기준 재조정(배당·분할): {", ".join(moved)}')
            state, rows, new_gaps = IO.advance_one(state, rows, report_date,
                                                   prices, grades)
        except ValueError as e:
            # 확인할 수 없는 기준 위에서 굴리지 않는다. 하루 쉬고 다음 실행이 메운다.
            print(f'WARN: {report_date} 굴리지 않는다 — {e}', file=sys.stderr)
            new_gaps = [report_date]
        for g in new_gaps:
            if g not in gaps:
                gaps.append(g)
        if new_gaps:
            print(f'WARN: {report_date} 굴리기 실패 — {new_gaps}', file=sys.stderr)
        elif report_date in gaps:
            # 앞선 실행이 결측으로 적어 둔 날을 나중 실행이 메웠다. 지우지 않으면
            # 되살아난 데이터를 두고 발행본이 계속 결측을 주장한다.
            gaps.remove(report_date)
            print(f'{report_date} 결측 표시를 지웠다 — 이번 실행이 메웠다')

    if state is None:
        print('no state and nothing priced — leaving the book untouched')
        return

    # 수집이 아예 돌지 않은 세션은 «굴리기 실패»로도 남지 않는다. 시장 달력과
    # 원장을 맞대야만 드러나고, **달력이 비었을 때 «빠진 것 없음»으로 읽는 것이
    # 정확히 그 구멍이다**(2026-09-01 codex 2·3차).
    ledger_dates = {r.get('report_date') for r in rows}
    for session in calendar_gaps(prices_file, ledger_end_before or state['inception'],
                                 report_date, ledger_dates):
        if session not in gaps:
            gaps.append(session)
            print(f'WARN: {session} 세션이 원장에 없다 — 결측으로 기록한다',
                  file=sys.stderr)

    for row in rows:
        append_jsonl(ledger_path, row)
    rows = IO.read_ledger(ledger_path)

    try:
        book = IO.publishable(state, rows, report_date, sorted(gaps), grades_from,
                              generated, stance_frozen=frozen,
                              rationale=prices_file.get('rationale'))
    except ValueError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        sys.exit(1)
    IO.write(os.path.join(d, 'portfolio_state.json'),
             IO.state_blob(state, grades_from, frozen))
    IO.write(os.path.join(d, 'portfolio.json'), book)

    perf = book['performance']
    itd = (perf['returns'] or {}).get('itd')
    print(f"기준가 {perf['nav']:.2f} · 벤치마크 {perf['bench_nav']:.2f} · "
          f"{perf['sessions']}거래일" + (f" · 설정 이후 {itd['portfolio']:+.2f}% "
                                      f"(초과 {itd['active']:+.2f}%p)" if itd else ''))
    if book['as_of'] != report_date:
        print(f"WARN: 원장은 {book['as_of']}에서 멈춰 있다", file=sys.stderr)


if __name__ == '__main__':
    main()
