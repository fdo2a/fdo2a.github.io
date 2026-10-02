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
- 일본은 **도쿄 금요일분**이 있어야 한다. 토요일 새벽 스냅샷은 JGB·닛케이 금요일분이 비어 있다
  (2026-09-26 실측). 종료일 +2일(일요일) 이후에 받은 스냅샷인데도 없으면 도쿄 휴장으로 보고 사흘까지
  봐준다.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from japan.core import _japan_source  # noqa: E402

TOKYO_SERIES = (('JGB 10년', lambda s: [r['date'] for r in s.get('jgb') or [] if r.get('10Y') is not None]),
                ('닛케이', lambda s: [d for d, _ in ((s.get('prices') or {}).get('Nikkei 225') or {})
                                      .get('daily') or []]))


def _japan_only(src):
    """US 주간이 쓰지 않는 소스 — 재무성·JGB·도쿄 상장 가격."""
    return src.startswith(('mof:', 'jgb', 'price:^N225', 'price:1306', 'price:1615',
                           'price:1343', 'price:1622'))


def verdict(market, snap, key, end):
    if not snap:
        return 'STALE', '스냅샷 없음'
    if snap.get('key') != key or snap.get('end_date') != end:
        return 'STALE', f'키·종료일 불일치 ({snap.get("key")} {snap.get("end_date")})'
    status = snap.get('fetch_status') or {}
    mine = (lambda s: _japan_source(s)) if market == 'japan' else (lambda s: not _japan_only(s))
    bad = sorted(k for k, v in status.items() if v != 'ok' and mine(k))
    if bad:
        return 'STALE', '실패 소스: ' + ', '.join(bad)
    if market == 'japan':
        gen = datetime.fromisoformat(snap['generated']).date() if snap.get('generated') else None
        sunday = date.fromisoformat(end) + timedelta(days=2)
        floor = (date.fromisoformat(end) - timedelta(days=3)) if gen and gen >= sunday \
            else date.fromisoformat(end)
        for label, dates in TOKYO_SERIES:
            last = max(dates(snap), default=None)
            if last is None or date.fromisoformat(last) < floor:
                return 'STALE', f'{label} 마지막 관측 {last} < {floor.isoformat()}'
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
