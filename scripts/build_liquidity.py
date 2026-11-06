#!/usr/bin/env python3
"""연준 H.4.1·재무부 분기조달계획 → `data/liquidity/` (US 아침 브리프 「유동성·수급」).

  python3 scripts/build_liquidity.py --datadir data --repo .
  python3 scripts/build_liquidity.py --datadir data --sanitize          # always() 단계
  python3 scripts/build_liquidity.py --datadir <workspace> --repo <repo> --recompute   # 원장 변경 뒤(네트워크 없음)
  python3 scripts/build_liquidity.py --datadir data --backfill <dir>    # 최초 1회: 아카이브 HTML 로 이력 채우기

비-코어다. 계약(설계 docs/superpowers/specs/2026-11-07-us-liquidity-section.md):

* **이 실행의 산출물만.** 시작하자마자 `table.html`·`qra/*.txt` 를 지우고 책을 `status: running` 으로 쓴다.
  끝까지 돌면 원천의 pending·실패와 무관하게 `complete`. `--sanitize` 가 이 실행·complete 가 아니면 다시 비운다.
* **state 는 파일 하나**(`state.json`) — 임시 파일 → rename 한 번, 그다음 책 complete.
* **늦은 회차는 버리지 않는다.** 기대 회차(EFFECTIVE 직전 목요일부터)를 매번 전부 다시 찾고,
  실렸는지는 커밋된 발행본이 정한다(`liquidity.ledger_from_posts`).
"""

import argparse
import datetime as dt
import glob
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import liquidity as L  # noqa: E402
from us.fred import _ssl_context  # noqa: E402

UA = 'Mozilla/5.0 (compatible; fdo2a-brief/1.0)'


def _load(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def _write_atomic(path, obj, compact=False):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        if compact:
            json.dump(obj, fh, ensure_ascii=False, separators=(',', ':'))
        else:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def run_id():
    rid = os.environ.get('GITHUB_RUN_ID')
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f'local-{os.getpid()}-{int(time.time())}'


def http_get(url, timeout=30):
    """-> (status, text). 404 등은 예외가 아니라 상태로."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, ''


def announced_rows():
    """TreasuryDirect 공고(최근 30일) — 분기조달계획 발행 규모 대조용."""
    from us import auctions as A
    return A.fetch_announced(30)


def config(repo):
    """`config/liquidity.json` — `effective_session`(첫 적용 세션 날짜). 없으면 기능 꺼짐."""
    c = _load(os.path.join(repo, 'config', 'liquidity.json'), {}) or {}
    return c


def effective_at(cfg, holidays):
    s = cfg.get('effective_session')
    if not s:
        return None
    return L.window(dt.date.fromisoformat(s), holidays)[0]


def paths(datadir):
    root = os.path.join(datadir, 'liquidity')
    return {'root': root, 'book': os.path.join(root, 'liquidity.json'), 'table': os.path.join(root, 'table.html'),
            'qra': os.path.join(root, 'qra'), 'state': os.path.join(root, 'state.json')}


def wipe_outputs(p):
    if os.path.exists(p['table']):
        os.remove(p['table'])
    for f in glob.glob(os.path.join(p['qra'], '*.txt')):
        os.remove(f)


# ── H.4.1 ───────────────────────────────────────────────────────────────

def fetch_h41(history, effective, now, get, notes):
    """예정 발표일이 지났는데 아직 못 받은 주만 확인한다 → (history, pending, checked).

    확인할 주가 없으면 **요청을 하나도 보내지 않는다**(사용자 2026-11-07 「다음 발표일을 파악한 뒤 그 날만」).
    있으면 current 한 번 → 그래도 빈 주가 있으면 Fed 발표일 목록(`releaseDates.json`)에서 아직 없는 날짜의 아카이브만.
    목록을 못 읽으면 그 주 예정일부터 다음 주 예정일 전날까지의 영업일로 대신 찾는다.
    """
    due = L.h41_due(history, effective, now)
    if not due:
        return history, [], False
    status, text = get(L.H41_BASE + 'current/')
    if status == 200:
        try:
            history = L.upsert_history(history, L.parse_h41(text))
        except L.ParseError as e:
            notes.append(f'h41_current:{e.code}')
    else:
        notes.append(f'h41_current:http_{status}')
    pending = []
    due = L.h41_due(history, effective, now)
    if due:
        # 실제 발표일은 Fed 의 발표일 목록이 안다 — 짐작한 날짜 창으로 찾지 않는다
        listed = None
        status, text = get(L.H41_DATES)
        if status == 200:
            try:
                listed = L.parse_release_dates(text)
            except L.ParseError as e:
                notes.append(f'h41_dates:{e.code}')
        else:
            notes.append(f'h41_dates:http_{status}')
        have = {r['release_date'] for r in history}
        first = L.h41_scheduled(due[0][0])
        if listed is not None:
            tries = sorted(d for d in listed if d >= first and d.isoformat() not in have
                           and L.h41_release_at(d) <= now)
        else:
            tries = sorted({d for _, probes in due for d in probes if d.isoformat() not in have})
        for d in tries:
            status, text = get(L.h41_url(d))
            if status != 200 or 'H.4.1' not in text[:5000]:
                continue
            try:
                history = L.upsert_history(history, L.parse_h41(text))
            except L.ParseError as e:
                notes.append(f'h41_{d}:{e.code}')
        pending = [th.isoformat() for th, _ in L.h41_due(history, effective, now)]
    return history, pending, True


# ── QRA ─────────────────────────────────────────────────────────────────

PARSERS = {'borrowing': L.parse_borrowing, 'refunding': L.parse_refunding, 'tbac': L.parse_tbac}


def qra_due(rounds, schedule, now):
    """랜딩을 지금 확인해야 하나.

    - 다음 회차 발표일을 모르거나 그날이 됐다.
    - 최신 회차에서 발표 시각이 이미 지났는데 아직 검증하지 못한 문서가 있다(월요일에 확인한 뒤의 수요일 성명,
      검증 실패한 문서) — 받을 때까지, 다음 회차가 나올 때까지 매 실행 다시 본다(구현 검토: 기한·누락 금지).
    """
    nxt = (schedule or {}).get('qra_next') or {}
    dates = [nxt.get(k) for k in ('borrowing', 'refunding')]
    if not rounds or not all(dates):
        return True                        # 다음 발표일을 하나라도 모르면 확인한다(구현 재검토 #2)
    if now.date() >= min(dt.date.fromisoformat(d) for d in dates):
        return True
    latest = rounds[sorted(rounds)[-1]]
    docs = latest.get('docs') or {}
    for kind, at in (latest.get('times') or {}).items():
        if dt.datetime.fromisoformat(at) <= now and not (docs.get(kind) or {}).get('ok'):
            return True
    return False


def restore_qra_texts(rounds, rnd, qra_dir):
    """확인하지 않는 날에도 최신 회차의 검증 원문은 state 에서 이 실행의 산출물로 다시 쓴다."""
    texts = ((rounds.get(rnd) or {}).get('texts')) or {}
    if texts:
        os.makedirs(qra_dir, exist_ok=True)
    for kind, body in texts.items():
        with open(os.path.join(qra_dir, f'{rnd}_{kind}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(body + '\n')


def fetch_qra(rounds, now, get, qra_dir, notes, announced=None):
    """가장 최근 회차의 문서를 매 실행 다시 받아 검증 → (rounds, 이 실행이 확인한 최신 회차 키 또는 None).

    랜딩을 못 읽은 실행은 회차를 확인하지 못한 것이다 — None 을 돌려 그 실행에서는 QRA 를 싣지 않는다
    (구현 검토 #5: 새 회차 발표일에 랜딩이 실패하면 state 의 옛 회차가 「최신」으로 실렸다).
    `announced` = TA_WS 공고 행을 돌려주는 함수(발행 규모 대조)."""
    status, text = get(L.QRA_LANDING)
    if status != 200:
        notes.append(f'qra_landing:http_{status}')
        return rounds, None, None
    try:
        land = L.parse_landing(text)
    except L.ParseError as e:
        notes.append(f'qra_landing:{e.code}')
        return rounds, None, None
    rnd = land['round']
    entry = dict(rounds.get(rnd) or {}, round=rnd, round_name=land['round_name'],
                 times={k: v for k, v in land['times'].items() if k in land['links']})
    docs = dict(entry.get('docs') or {})
    texts = dict(entry.get('texts') or {})
    for kind, url in land['links'].items():
        at = dt.datetime.fromisoformat(land['times'][kind])
        if at > now:
            continue
        if (docs.get(kind) or {}).get('ok') and kind in texts:
            continue                       # 이미 검증한 문서는 다시 받지 않는다
        status, page = get(url)
        if status != 200:
            docs[kind] = {'ok': False, 'note': f'http_{status}', 'url': url, 'expected_at': at.isoformat()}
            continue
        try:
            parsed = PARSERS[kind](page, rnd)
            body = None
            if kind == 'tbac':
                parsed, body = parsed
            released = dt.datetime.fromisoformat(parsed['released_at'])
            if abs((released - at).total_seconds()) > 60:
                raise L.ParseError('time_mismatch', f'{released} vs {at}')
            if kind == 'refunding':
                try:
                    rows = announced() if announced else []
                except Exception as e:          # 공고 원천 장애는 대조 불가(unmatched)일 뿐이다
                    notes.append(f'ta_ws:{type(e).__name__}')
                    rows = []
                parsed['ta_ws'] = L.check_ta_ws(parsed, rnd, rows)
        except L.ParseError as e:
            docs[kind] = {'ok': False, 'note': e.code, 'url': url, 'expected_at': at.isoformat()}
            continue
        docs[kind] = dict(parsed, ok=True, url=url)
        texts[kind] = body if body is not None else L._press(page)[2]
    entry['docs'] = docs
    entry['texts'] = texts
    ref = docs.get('refunding') or {}
    if ref.get('ok'):
        entry['guidance'] = ref.get('guidance')
    # 원문은 최신 회차만 state 에 둔다(크기) — 옛 회차는 필드만
    rounds = {k: ({kk: vv for kk, vv in v.items() if kk != 'texts'} if k != rnd else v)
              for k, v in dict(rounds, **{rnd: entry}).items()}
    restore_qra_texts(rounds, rnd, qra_dir)
    return rounds, rnd, land.get('next')


# ── 책 ──────────────────────────────────────────────────────────────────

def assemble(state, report_date, holidays, effective, ledger, pending=(), notes=(), qra_confirmed=None):
    """state + 원장 → 책 본문(status·run_id 제외)."""
    history = state.get('h41_history') or []
    cands, overdue = L.h41_candidates(history, ledger[0], report_date, holidays, effective)
    end = L.cutoff(report_date)
    pool_all = [r['release_date'] for r in history
                if effective < L.h41_release_at(dt.date.fromisoformat(r['release_date'])) <= end]
    for c in cands:
        c['flags'] = L.flags(history, c['release_date'])
    rounds = state.get('qra_rounds') or {}
    latest = sorted(rounds)[-1] if rounds else None
    qra = {'round': latest, 'round_name': (rounds.get(latest) or {}).get('round_name'),
           'candidates': {}, 'guidance': None, 'superseded_unpublished': [], 'confirmed': qra_confirmed}
    if latest and qra_confirmed != latest:
        latest = None                     # 이 실행이 최신 회차를 확인하지 못했다 — QRA 는 다음 실행에
    if latest:
        qra['candidates'] = L.qra_candidates(rounds[latest], ledger[1], report_date, holidays, effective)
        prev = L.prior_round(rounds, latest)
        cur_g = rounds[latest].get('guidance')
        prev_g = (rounds.get(prev) or {}).get('guidance') if prev else None
        ch, words = L.guidance_change(prev_g, cur_g)
        qra['guidance'] = {'change': ch, 'words': words, 'prev': prev_g, 'cur': cur_g, 'prev_round': prev}
        for old in sorted(rounds)[:-1]:
            for kind, doc in (rounds[old].get('docs') or {}).items():
                if doc.get('ok') and kind in ('borrowing', 'refunding') and f'{old}:{kind}' not in ledger[1] \
                        and dt.datetime.fromisoformat(doc['released_at']) > effective:
                    qra['superseded_unpublished'].append(f'{old}:{kind}')
    book = {
        'report_date': report_date.isoformat(),
        'effective': effective.isoformat(),
        'h41': {'candidates': cands, 'pool': sorted(pool_all), 'pending': list(pending), 'overdue': overdue},
        'qra': qra,
        'ledger': {'h41': sorted(ledger[0]), 'qra': sorted(ledger[1])},
        'notes': list(notes),
    }
    book['today'] = bool(cands) or bool(qra['candidates'])
    return book


def write_outputs(p, book):
    if book['today']:
        with open(p['table'], 'w', encoding='utf-8') as fh:
            fh.write(L.render_tables(book))
    elif os.path.exists(p['table']):
        os.remove(p['table'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--repo', default='.')
    ap.add_argument('--date')
    ap.add_argument('--sanitize', action='store_true')
    ap.add_argument('--recompute', action='store_true')
    ap.add_argument('--backfill')
    args = ap.parse_args()
    p = paths(args.datadir)
    os.makedirs(p['root'], exist_ok=True)

    if args.sanitize:
        book = _load(p['book'])
        rid = os.environ.get('LIQ_RUN_ID') or (run_id() if os.environ.get('GITHUB_RUN_ID') else None)
        if not book or book.get('status') != 'complete' or (rid and book.get('run_id') != rid):
            wipe_outputs(p)
            _write_atomic(p['book'], dict(book or {}, status='aborted'))
            print('liquidity: sanitize — 이 실행의 완료 책이 아니다, 산출물을 비웠다')
        return

    holidays = _load(os.path.join(args.repo, 'data', 'market_holidays.json'), {}) or {}
    if args.date:
        report_date = dt.date.fromisoformat(args.date)
    else:
        md = _load(os.path.join(args.datadir, 'market_data.json'), {}) or {}
        report_date = dt.date.fromisoformat(md['report_date'])

    if args.backfill:
        state = _load(p['state'], {}) or {}
        hist = state.get('h41_history') or []
        n = 0
        for f in sorted(glob.glob(os.path.join(args.backfill, '*.html'))):
            try:
                hist = L.upsert_history(hist, L.parse_h41(open(f, encoding='utf-8', errors='ignore').read()))
                n += 1
            except L.ParseError as e:
                print(f'skip {os.path.basename(f)}: {e.code}', file=sys.stderr)
        state['h41_history'] = hist
        _write_atomic(p['state'], state, compact=True)
        print(f'backfill: {n} 회차, 이력 {len(hist)}')
        return

    cfg = config(args.repo)
    effective = effective_at(cfg, holidays)

    if args.recompute:
        book = _load(p['book'])
        state = _load(p['state'], {}) or {}
        if not book or book.get('status') != 'complete' or effective is None:
            print('liquidity: recompute — 완료 책이 없다', file=sys.stderr)
            sys.exit(1)
        ledger = L.ledger_from_posts(args.repo, report_date.isoformat())
        new = assemble(state, report_date, holidays, effective, ledger,
                       book['h41'].get('pending', []), book.get('notes', []),
                       qra_confirmed=(book.get('qra') or {}).get('confirmed'))
        new.update({'status': 'complete', 'run_id': book.get('run_id'), 'generated': book.get('generated'),
                    'recomputed': True})
        write_outputs(p, new)
        _write_atomic(p['book'], new)
        print(f'liquidity: recompute — H.4.1 {[c["release_date"] for c in new["h41"]["candidates"]]}, '
              f'QRA {sorted(new["qra"]["candidates"])}')
        return

    rid = os.environ.get('LIQ_RUN_ID') or run_id()
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
    wipe_outputs(p)
    _write_atomic(p['book'], {'report_date': report_date.isoformat(), 'run_id': rid, 'status': 'running'})
    if effective is None:
        _write_atomic(p['book'], {'report_date': report_date.isoformat(), 'run_id': rid, 'status': 'complete',
                                  'generated': stamp, 'today': False, 'disabled': True})
        print('liquidity: config/liquidity.json 의 effective_session 이 없다 — 꺼짐')
        return

    state = _load(p['state'], {}) or {}
    now = L.cutoff(report_date) if args.date else dt.datetime.now(L.ET)
    notes = []
    hist, pending, h41_checked = fetch_h41(state.get('h41_history') or [], effective, now, http_get, notes)
    schedule = dict(state.get('schedule') or {})
    rounds = state.get('qra_rounds') or {}
    if qra_due(rounds, schedule, now):
        rounds, confirmed, nexts = fetch_qra(rounds, now, http_get, p['qra'], notes, announced=announced_rows)
        if nexts:
            schedule['qra_next'] = nexts
        qra_checked = True
    else:
        # 다음 발표일 전 — 랜딩을 확인하지 않는다. 지난 실행이 확인한 최신 회차가 그대로 최신이다.
        confirmed = sorted(rounds)[-1] if rounds else None
        restore_qra_texts(rounds, confirmed, p['qra'])
        qra_checked = False
    for b in cfg.get('qra_bootstrap') or []:
        rounds.setdefault(b['round'], {'round': b['round'], 'round_name': b.get('round_name'),
                                       'guidance': b['guidance'], 'docs': {}, 'source': 'manual',
                                       'url': b.get('url')})
    schedule['h41_next'] = L.h41_next_release(now)
    state = {'generation': (state.get('generation') or 0) + 1, 'written_at': stamp,
             'h41_history': hist, 'qra_rounds': rounds, 'schedule': schedule}
    ledger = L.ledger_from_posts(args.repo, report_date.isoformat())
    book = assemble(state, report_date, holidays, effective, ledger, pending, notes, qra_confirmed=confirmed)
    book.update({'run_id': rid, 'generated': stamp,
                 'checked': {'h41': h41_checked, 'qra': qra_checked}, 'schedule': schedule})
    write_outputs(p, book)
    _write_atomic(p['state'], state, compact=True)
    book['status'] = 'complete'
    _write_atomic(p['book'], book)
    for w in pending:
        print(f'::warning::H.4.1 {w} 주 회차를 아직 못 받았다 — 다음 실행이 다시 찾는다')
    for w in book['h41']['overdue']:
        print(f'::warning::H.4.1 {w} 발표분이 {L.OVERDUE_DAYS}일 넘게 실리지 않았다')
    for w in book['qra']['superseded_unpublished']:
        print(f'::warning::QRA {w} 가 실리지 않은 채 새 회차로 대체됐다')
    print(f'liquidity {report_date}: today={book["today"]} H.4.1 {[c["release_date"] for c in book["h41"]["candidates"]]} '
          f'QRA {sorted(book["qra"]["candidates"])} notes={notes}')


if __name__ == '__main__':
    main()
