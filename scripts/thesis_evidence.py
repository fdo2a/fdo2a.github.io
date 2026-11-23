#!/usr/bin/env python3
"""Thesis evidence as the gate will see it — STEP 1 and STEP 3 of the routine call this.

    python3 scripts/thesis_evidence.py [--today YYYY-MM-DD] [--events /tmp/run.json]

Prints, per ticker: today's numeric triggers (or 「보류」), licensing filings, accepted
research events, price/contract axis days and kill_evidence, plus run.json problems.
`check_thesis.py` calls `assess_today()` here too, so STEP 3 and the gate read one T.

Collector files are read from **git HEAD**, never the working tree, and a version counts
only if the commit that brought it was authored by the collector bot (a drift guard, not
authentication — a deliberately forged commit is out of scope). Logic:
scripts/thesis/evidence.py.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thesis import evidence as E          # noqa: E402

KST = timezone(timedelta(hours=9))
TICKERS = ('005930.KS', '000660.KS', 'MU')
DATA = 'thesis/data'
COLLECTOR = tuple(f'{DATA}/{n}' for n in
                  ('watch.json', 'history.jsonl', 'disclosures.json', 'events.json'))
BOT = 'github-actions[bot]@users.noreply.github.com'


def kst_today():
    return datetime.now(KST).date().isoformat()


def _git(*args):
    out = subprocess.run(['git', *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def _shallow():
    """Commits at a shallow-clone boundary. `git log -- file` there names whoever made the
    boundary commit, not who changed the file, so their author is unreadable."""
    path = _git('rev-parse', '--git-path', 'shallow')
    try:
        return set(Path(path.strip()).read_text().split()) if path else set()
    except OSError:
        return set()


def provenance(path, shallow):
    """(sha, None) when HEAD's version of `path` came from a collector-bot commit, else
    (sha or None, reason)."""
    out = _git('log', '-1', '--format=%H %ae', 'HEAD', '--', path)
    if not out or not out.strip():
        return None, f'{path} 의 커밋을 읽지 못했다'
    sha, _, author = out.strip().partition(' ')
    if sha in shallow:
        return sha, f'{path} 의 커밋이 얕은 복제 경계라 작성자를 알 수 없다'
    if author != BOT:
        return sha, f'{path} 의 마지막 커밋이 수집 봇이 아니다'
    return sha, None


def _show(ref, path):
    return _git('show', f'{ref}:{path}')


def _json(text):
    try:
        return json.loads(text) if text is not None else None
    except ValueError:
        return None


def disclosure_snapshots(today, shallow, notes):
    """disclosures.json versions committed in the window by the collector bot."""
    path = f'{DATA}/disclosures.json'
    since = f'{E.window_start(today)}T00:00:00+09:00'
    out = _git('log', f'--since={since}', '--format=%H %ae', 'HEAD', '--', path)
    if out is None:
        notes.append('git 기록을 읽지 못했다 — HEAD 의 disclosures.json 만 쓴다')
        return None
    snaps = []
    for line in out.split('\n'):
        sha, _, author = line.strip().partition(' ')
        if not sha or author != BOT or sha in shallow:
            continue
        payload = _json(_show(sha, path))
        if isinstance(payload, dict):
            snaps.append(payload)
    return snaps


def load_inputs(today):
    """Collector inputs at HEAD, each refused (→ nothing) unless the bot committed it."""
    notes, shallow = [], _shallow()
    if shallow:
        notes.append('얕은 복제다 — 경계 커밋의 자료는 근거로 쓰지 않는다')

    def take(path):
        _, why = provenance(path, shallow)
        if why:
            notes.append(why)
            return None, why
        return _show('HEAD', path), None

    watch_text, _ = take(f'{DATA}/watch.json')
    history_text, history_problem = take(f'{DATA}/history.jsonl')
    disc_text, _ = take(f'{DATA}/disclosures.json')
    disclosures = _json(disc_text)

    snaps = disclosure_snapshots(today, shallow, notes)
    if snaps is None:
        snaps = []
    if isinstance(disclosures, dict):
        snaps.append(disclosures)
    return {'watch': _json(watch_text), 'history_text': history_text,
            'history_problem': history_problem, 'disclosures': disclosures,
            'snapshots': snaps, 'notes': notes}


def load_run(path):
    """run.json — research events only. A file that does not parse is a problem, not {}."""
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return {'_error': f'run.json 을 읽지 못했다: {e}'}


def assess_today(today=None, run_path=None, tickers=TICKERS):
    today = today or kst_today()
    inputs = load_inputs(today)
    return E.assess(today, list(tickers), run=load_run(run_path), **inputs)


def render(result):
    lines = [f'THESIS_EVIDENCE {result["today"]}']
    lines += [f'  참고: {n}' for n in result['notes']]
    for sym, t in result['tickers'].items():
        numeric = '보류' if t['numeric'] is None else (', '.join(t['numeric']) or '없음')
        lines.append(f'{sym}')
        lines.append(f'  수치 트리거: {numeric}')
        lines += [f'    - {h.get("message") or h["key"]}' for h in t['numeric_hits']]
        lines.append(f'  오늘 확정 공시: {len(t["filings"])}건')
        lines += [f'    - {f["date"]} {f["title"]} {f["url"]}' for f in t['filings']]
        lines.append(f'  인정한 리서치 사건: {len(t["events"])}건')
        lines += [f'    - {e["title"]} {e["source"]}' for e in t['events']]
        lines.append(f'  T(허용 근거): {t["licences"] or "없음 — 이 종목은 손대지 않는다"}')
        lines.append(f'  가격 축 날짜: {t["price_days"] or "없음"} / '
                     f'계약 축 날짜: {t["contract_days"] or "없음"}')
        lines.append(f'  kill_evidence: {list(t["kill_evidence"])}')
    for sym, check, message in result['problems']:
        lines.append(f'문제 [{sym}] {check}: {message}')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--today', default=None)
    ap.add_argument('--events', default=None, help='STEP 3 에서 쓴 /tmp/run.json')
    ap.add_argument('--json', action='store_true', help='사람용 대신 JSON 으로')
    args = ap.parse_args(argv)
    result = assess_today(args.today, args.events)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 1 if result['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
