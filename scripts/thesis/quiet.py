"""Is today provably quiet? — answered from committed files before any model is called.

The routine's expected outcome on most days is "no change" (THESIS_ORCHESTRATOR.md), yet
each evening it paid for a full read of the runbook and a web sweep to reach it. This is
the arithmetic version of that sweep for what the collectors already record:

    numeric triggers  triggers.evaluate() over watch.json + history.jsonl
    filings           disclosures.json `confirmed_count` (DART whitelist)
    announcements     events.json newsroom items since the previous collection
    earnings          any ticker within [-1, +2] days of `next_earnings_date`

and two things no feed covers, which force the full sweep: Friday (customer newsrooms,
Micron) and any input that is stale, incomplete or missing. **Anything that cannot be
proven quiet is not quiet** — a false "quiet" skips a real event; a false "not quiet"
only costs one ordinary run.

Pure. The CLI is `scripts/thesis_quiet.py`.

Design: docs/superpowers/specs/2026-09-24-thesis-quiet-prefilter.md
"""

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
EARNINGS_BEFORE = 1
EARNINGS_AFTER = 2
FULL_SWEEP_WEEKDAY = 4      # Friday


def _kst_date(stamp):
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    return when.astimezone(KST).date()


def decide(today, watch, triggers, disclosures, events):
    """(quiet, reasons). `reasons` names every signal that broke the quiet."""
    reasons = []
    if today.weekday() == FULL_SWEEP_WEEKDAY:
        reasons.append('금요일 전체 점검 — 고객사 발표·Micron 은 피드로 기계화되지 않았다')

    if not isinstance(watch, dict) or watch.get('as_of') != today.isoformat():
        reasons.append(f'watch.json 이 오늘 것이 아니다 ({(watch or {}).get("as_of")})')
    elif not watch.get('complete'):
        reasons.append(f'watch.json 불완전 — missing={watch.get("missing")}')

    if not isinstance(disclosures, dict):
        reasons.append('disclosures.json 없음 — 공시를 확인하지 못했다')
    elif disclosures.get('as_of') != today.isoformat():
        reasons.append(f'disclosures.json 이 오늘 것이 아니다 ({disclosures.get("as_of")})')
    elif disclosures.get('missing') or disclosures.get('pending'):
        reasons.append(f'공시 수집 불완전 — {disclosures.get("missing") or "키 미설정"}')
    else:
        for sym, row in (disclosures.get('tickers') or {}).items():
            if (row or {}).get('confirmed_count'):
                reasons.append(f'{sym} 확정 공시 {row["confirmed_count"]}건')

    if not isinstance(events, dict):
        reasons.append('events.json 없음 — 뉴스룸을 확인하지 못했다')
    elif _kst_date(events.get('collected_at')) != today:
        reasons.append(f'events.json 이 오늘 것이 아니다 ({events.get("collected_at")})')
    elif events.get('missing'):
        reasons.append(f'뉴스룸 수집 불완전 — {events["missing"]}')
    else:
        for item in events.get('items') or []:
            reasons.append(f'{item.get("ticker")} 뉴스룸: {item.get("title")}')

    for sym, hits in (triggers or {}).items():
        for hit in hits or []:
            reasons.append(f'{sym} 수치 트리거: {hit.get("message") or hit.get("kind")}')

    for sym, row in ((watch or {}).get('tickers') or {}).items():
        raw = (row or {}).get('next_earnings_date')
        try:
            when = date.fromisoformat(raw) if raw else None
        except ValueError:
            when = None
        if when and when - timedelta(days=EARNINGS_BEFORE) <= today <= when + timedelta(
                days=EARNINGS_AFTER):
            reasons.append(f'{sym} 실적 발표 창 ({raw})')

    return not reasons, reasons
