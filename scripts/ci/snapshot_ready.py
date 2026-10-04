#!/usr/bin/env python3
"""주간 스냅샷(data/weekly_ext/<KEY>.json)을 그대로 써도 되는가 (2026-10-02).

    python3 scripts/ci/snapshot_ready.py us|japan --key 2026-W40 --end 2026-10-02
        → 한 줄 `READY` 또는 `STALE <이유>`. exit 0 = READY, 1 = STALE.

루틴 환경은 금융 호스트에 닿지 못한다(2026-10-02 실측 — Yahoo·MOF·CFTC·FRED 전부 연결 실패,
yfinance 없음). 그래서 스냅샷은 `collect-weekly-data.yml`(Actions)만 받고, 루틴은 이 판정이
STALE 일 때 그 워크플로를 띄운다.

- 키·종료일이 다르면 STALE.
- 그 시장이 쓰는 소스만 본다 — US 는 일본 전용 소스의 실패를, 일본은 US 전용 소스의 실패를
  무시한다(일본 판별은 `japan.core._japan_source` 그대로).
- US 는 **모든** 소스가 ok 여야 한다 — US 진단은 실패 소스를 전부 게이트로 넘긴다(일본 전용 포함).
- 일본은 일본이 쓰는 소스만(`japan.core._japan_source`) 보고, **종료일 이하의 마지막 도쿄 거래일**
  닛케이가 있어야 한다. JGB 10년은 MOF 가 다음 영업일에 올리므로 **그 전 도쿄 거래일**이면 된다
  (2026-10-04 — 일요일엔 금요일분이 없다. 본문 표는 행마다 기준일을 밝힌다).
  도쿄 휴장은 추정하지 않고 달력(`data/market_holidays.json` 의 `jp`, JPX 공식)으로만 본다 —
  「일요일에 받았는데 없으면 휴장」은 반영이 늦은 거래일을 휴장으로 오판한다(구현 검토 #3).
  종료일 뒤의 관측은 세지 않는다 — 다음 주 자료가 대상 주 금요일의 누락을 가리지 않게(#4).
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from japan.core import _japan_source  # noqa: E402

# (라벨, 관측일, 공표 지연 영업일). MOF 커브는 다음 도쿄 영업일에 올라온다 — 금요일분은 월요일에야
# 나온다(2026-10-04 실측: 토 15시~일 22시 스냅샷 6개가 전부 목요일에서 끝났다). 일요일 루틴이
# 금요일분을 기다리면 영원히 STALE 이다.
TOKYO_SERIES = (('JGB 10년', lambda s: [r['date'] for r in s.get('jgb') or [] if r.get('10Y') is not None], 1),
                ('닛케이', lambda s: [d for d, _ in ((s.get('prices') or {}).get('Nikkei 225') or {})
                                      .get('daily') or []], 0))


def _jp_holidays():
    try:
        cal = json.loads((ROOT / 'data' / 'market_holidays.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ()
    return tuple((cal.get('jp') or {}).get('dates') or ())


def last_tokyo_day(end, holidays=()):
    d, hol = date.fromisoformat(end), set(holidays)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= timedelta(days=1)
    return d


def verdict(market, snap, key, end, jp_holidays=None):
    if not snap:
        return 'STALE', '스냅샷 없음'
    if snap.get('key') != key or snap.get('end_date') != end:
        return 'STALE', f'키·종료일 불일치 ({snap.get("key")} {snap.get("end_date")})'
    status = snap.get('fetch_status') or {}
    mine = _japan_source if market == 'japan' else (lambda s: True)
    bad = sorted(k for k, v in status.items() if v != 'ok' and mine(k))
    if bad:
        return 'STALE', '실패 소스: ' + ', '.join(bad)
    if market == 'japan':
        hol = _jp_holidays() if jp_holidays is None else jp_holidays
        for label, dates, lag in TOKYO_SERIES:
            want = last_tokyo_day(end, hol)
            for _ in range(lag):
                want = last_tokyo_day((want - timedelta(days=1)).isoformat(), hol)
            last = max((d for d in dates(snap) if d <= end), default=None)
            if last is None or date.fromisoformat(last) < want:
                return 'STALE', f'{label} 마지막 관측 {last} < 도쿄 마지막 거래일 {want.isoformat()}'
    return 'READY', ''


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('market', choices=['us', 'japan'])
    ap.add_argument('--key', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--path')
    a = ap.parse_args(argv)
    path = Path(a.path or ROOT / 'data' / 'weekly_ext' / f'{a.key}.json')
    try:
        snap = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        snap = None
    v, why = verdict(a.market, snap, a.key, a.end)
    print(f'{v} {why}'.strip())
    return 0 if v == 'READY' else 1


if __name__ == '__main__':
    sys.exit(main())
