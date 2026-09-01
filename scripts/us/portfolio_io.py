"""모의 포트폴리오의 파일 입출력 — 굴리기 로직(`portfolio.py`)과 분리한다.

파일이 셋인 이유가 있다.

  `portfolio.json`       발행본이 읽는 것. 메타 + 성과. **좌수·종가는 담지 않는다** —
                         게이트가 이 파일로 허용 수치 집합을 만들기 때문에, 굴리기용
                         내부 수치가 섞이면 허용 집합이 부풀어 게이트가 헐거워진다.
  `portfolio_state.json` 굴리기용 기계 상태(좌수·직전 종가). 사람이 읽을 것이 아니다.
  `history/portfolio.jsonl`  원장. append-only, 다시 굴리지 않는다.
"""

import json
import os

from .portfolio import (BASE_NAV, NEUTRAL_GRADES, reanchor, replay,  # noqa: F401
                        summarize)


def load(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(path, blob):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(blob, fh, indent=2, ensure_ascii=False, default=str)


def grades_of(stance, strict=False):
    """stance.json / 이력 한 행 → 등급만.

    `strict=True` 면 **한 자산군이라도 읽을 수 없을 때 ValueError**. 조용히 중립으로
    메우면 사고가 판단으로 둔갑한다 — 책이 반쯤 깨진 날 금 비중이 중립으로 내려가고
    그 이유가 어디에도 남지 않는다(2026-09-01 codex 검토).
    """
    assets = (stance or {}).get('assets') or {}
    out, bad = dict(NEUTRAL_GRADES), []
    for key in out:
        row = assets.get(key)
        if not isinstance(row, dict) or row.get('grade') is None:
            bad.append(key)
            continue
        try:
            out[key] = int(row['grade'])
        except (TypeError, ValueError):
            bad.append(key)
    if strict and bad:
        raise ValueError('등급을 읽을 수 없는 자산군: ' + ', '.join(sorted(bad)))
    return out


def book_lookup(stance_rows):
    """날짜 → 그날 종가에 **적용되는** 스탠스 책(행 자체).

    하루 시차가 여기 있다. D일 종가에 담는 비중은 D−1일에 발행된 책에서 나온다 —
    마감 뒤에 결정한 것을 그날 종가에 사는 것이 룩어헤드이기 때문이다. 설정일만
    예외로 그날 책을 쓴다(첫 손익은 다음 세션부터라 앞을 보지 않는다).
    """
    rows = sorted((r for r in stance_rows if r.get('report_date')),
                  key=lambda r: r['report_date'])

    def lookup(date):
        prior = [r for r in rows if r['report_date'] < date]
        if prior:
            return prior[-1]
        return next((r for r in reversed(rows) if r['report_date'] <= date), None)

    return lookup


def grades_lookup(stance_rows):
    """날짜 → 그날 적용될 등급. 출처 책이 필요하면 `book_lookup`."""
    book = book_lookup(stance_rows)
    return lambda date: grades_of(book(date))


def state_blob(state, grades_from=None, stance_frozen=False):
    """굴리기용 기계 상태 + **어느 책을 적용했는지**.

    출처를 상태에 함께 남기지 않으면, 같은 날 두 번째 실행이 굴리기를 건너뛰면서도
    메타데이터만 새 책으로 갈아 끼운다 — 비중은 옛 등급인데 발행본은 새 등급을
    적용했다고 주장하게 된다(2026-09-01 codex 2차).
    """
    def book(b):
        return {'date': b['date'], 'nav': b['nav'], 'units': b['units'],
                'prices': b['prices'], 'grades': b['grades'],
                'weights': b['weights'], 'rebalanced': b['rebalanced']}
    return {'inception': state['inception'], 'active': book(state['active']),
            'bench': book(state['bench']), 'grades_from': grades_from,
            'stance_frozen': bool(stance_frozen)}


def publishable(state, rows, report_date, gaps, grades_from, generated=None,
                stance_frozen=False):
    """발행본과 게이트가 읽는 책.

    성과는 **원장에서만** 나오고, 그 원장의 마지막 행이 상태와 같은 날인지 여기서
    확인한다. 둘이 갈리면 발행본이 어제 성과에 오늘 날짜를 붙이게 된다
    (2026-09-01 codex 검토).
    """
    gaps = sorted(set(gaps or ()))
    perf = summarize(rows, BASE_NAV, inception=state['inception'], gaps=gaps)
    as_of = state['active']['date']
    if rows and rows[-1].get('report_date') != as_of:
        raise ValueError(f'원장 마지막 행({rows[-1].get("report_date")})과 '
                         f'책의 기준일({as_of})이 다르다')
    if rows and abs(rows[-1].get('nav', 0) - state['active']['nav']) > 1e-6:
        raise ValueError('원장 마지막 행의 기준가가 책과 다르다')
    if rows and abs((rows[-1].get('bench_nav') or 0) - state['bench']['nav']) > 1e-6:
        raise ValueError('원장 마지막 행의 벤치마크 기준가가 책과 다르다')
    return {'generated': generated, 'report_date': report_date,
            'as_of': as_of, 'inception': state['inception'],
            'grades_from': grades_from, 'gaps': gaps,
            'stance_frozen': bool(stance_frozen),
            'base_nav': BASE_NAV, 'performance': perf}


def advance_one(state, rows, date, prices, grades):
    """하루치. 가격이 모자라면 상태를 그대로 두고 그 날을 건너뛴 것으로 돌려준다."""
    new_state, new_rows, gaps = replay([date], {date: prices},
                                       lambda _d: grades, state=state)
    return new_state, rows + new_rows, gaps


def read_ledger(path):
    """원장을 **엄격하게** 읽는다 — 깨진 줄 하나를 조용히 건너뛰면 성과가 조용히 바뀐다.

    `history.read_jsonl` 은 손상된 줄을 건너뛰어 이력 전체가 못 읽히는 것을 막는다.
    판단 이력에는 맞는 규칙이지만 성과 원장에는 아니다 — 여기서는 한 줄이 빠지면
    수익률이 달라지고, 아무도 그 사실을 모른다(2026-09-01 codex 검토).
    """
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f'{path}:{n} 원장을 읽을 수 없다 — {e}')
    return rows


def rebase(state, recent):
    """소급 조정된 종가에 두 책을 함께 다시 맞춘다.

    `recent` 는 `{ticker: {날짜: 종가}}`. **이 책의 기준일에 해당하는 값**을 찾아
    저장해 둔 종가와 비교한다. 「직전 세션」으로 비교하면 중간에 한 세션을 건너뛴
    날 조정이 통째로 새고, 벤치마크만 담은 종목(BIL)도 놓친다(2026-09-01 codex 2차).
    """
    date = state['active']['date']
    held = dict(state['bench']['prices'])
    held.update(state['active']['prices'])
    fresh, blind = {}, []
    for t, stored in held.items():
        got = (recent or {}).get(t)
        px = got.get(date) if isinstance(got, dict) else None
        if px is None:
            blind.append(t)         # 이 책의 기준일 값이 없으면 확인할 방법이 없다
            continue
        if stored and abs(px / stored - 1.0) > 1e-6:
            fresh[t] = px
    if blind:
        # **확인할 수 없으면 굴리지 않는다.** 조용히 건너뛰면 그날 있었던 분할이
        # 그대로 손실로 인쇄된다(2026-09-01 codex 3차, 합성 2:1 로 −21% 재현).
        raise ValueError('기준 확인 불가 — ' + ', '.join(sorted(blind)[:8]))
    if not fresh:
        return state, []
    return (dict(state, active=reanchor(state['active'], fresh),
                 bench=reanchor(state['bench'], fresh)), sorted(fresh))


def missing_sessions(calendar, since, until, have):
    """시장 달력에서 원장이 빠뜨린 세션. 달력을 확인할 수 없으면 ValueError.

    수집이 하루 아예 돌지 않으면 「굴리기 실패」 기록조차 남지 않는다. 그 구멍은
    달력과 원장을 맞대야만 드러나고, **달력이 비었을 때 «빠진 것 없음»으로 읽는
    것이 정확히 그 구멍이다**(2026-09-01 codex 3차).
    """
    dates = sorted(d for d in (calendar or []) if d)
    # 양 끝이 모두 달력 안에 있어야 그 사이를 셀 수 있다. 원장이 창보다 오래됐으면
    # 무엇이 빠졌는지 알 방법이 없고, 그때 «빠진 것 없음»으로 읽으면 안 된다.
    if not dates or until not in dates or since not in dates:
        raise ValueError(f'시장 달력을 확인할 수 없다 (기준 {since} → {until})')
    return [d for d in dates if since < d < until and d not in (have or set())]
