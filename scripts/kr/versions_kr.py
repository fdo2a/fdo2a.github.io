"""KR 수집 자료 판 관리 — 발행된 날의 동결 병합(1단계, 2026-11-10).

수집 실행이 발행된 거래일 D 를 다시 모아도 D 에 딸린 값(주간 세션의 업종·거래대금, 원장 D 행,
news/telegram/차트 D 파일)은 **발행 커밋 P 트리의 값**으로 둔다. 빈 곳은 빈 채로 둔다 —
새로 모은 값이 검증된 값을 자동으로 대체하지 않는다(사용자 결정 2026-11-09). 다음 거래일 관측
수급(extra_flows, D 이전 날짜)은 동결과 별개의 선택 정책이라 오늘처럼 반영한다. 사람이 부른
승격(promotions)은 맨 마지막에 덮는다.

이 파일은 순수 함수만 둔다. git·push 는 `scripts/common/versions.py`.
spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md
"""
import copy
import os

from kr.history import index_record, index_series, merge_index_record
from kr.period import finalize, merge_session, session_from
from us.period import week_key

MARKET = 'kr'
POST = 'kr/posts/{date}.html'
RECORD = 'verification/kr/{date}.json'
DATA = 'kr/data'
LEDGER = 'kr/data/history/kr_market.jsonl'
WEEKLY = 'kr/data/weekly/{key}.json'
MARKET_DATA = 'kr/data/kr_market_data.json'

# 워크플로의 옛 Commit data 단계가 돌리던 add 줄 그대로 — 오늘과 같은 커밋 O 를 만든다(bash -e 로,
# 첫 줄이 실패하면 오늘처럼 그 단계가 실패한다).
STAGE_SH = """git add kr/data/*.json kr/data/kr_sector.html
git add -A kr/data/kr_fund_view.html 2>/dev/null || true
git add kr/assets/*.png 2>/dev/null || true
git add kr/data/history 2>/dev/null || true
git add kr/data/weekly 2>/dev/null || true
git add kr/data/news 2>/dev/null || true
git add kr/data/telegram 2>/dev/null || true
"""

SESSION_INPUTS = ('kr/data/kr_market_data.json', 'kr/data/kr_flows.json',
                  'kr/data/kr_industry.json', 'kr/data/kr_top_value.json')
PUBLISHED_PART = ('industry', 'top_value', 'leading_industries', 'leading_all', 'leading_undecided')


def dated_paths(date):
    """D 에 딸린 대표 날짜 파일(없어도 P 트리에서 확인한다)."""
    return (f'kr/data/news/{date}.json', f'kr/data/telegram/{date}.json', f'kr/assets/kr_charts_{date}.png')


def is_dated(path, date):
    """이름에 D 가 든 kr/data·kr/assets 파일 — 발행됐으면 P 트리 그대로(없으면 없음).
    kr_flows_intraday_<D>.png 처럼 목록에 없던 산출물도 잡는다(codex 구현 검토 1회 #3)."""
    return path.startswith(('kr/data/', 'kr/assets/')) and date in os.path.basename(path)


def is_dateless(path):
    """다음 거래일 실행이 갈아끼우는 날짜 없는 고정 경로(발행된 날의 실행은 건드리지 않는다)."""
    if not path.startswith('kr/data/'):
        return False
    rest = path[len('kr/data/'):]
    return '/' not in rest


def is_frozen(path, date, key):
    """발행된 D 의 실행이 이번 실행 값으로 바꾸지 않는 경로(원장·주간은 따로 병합)."""
    return is_dateless(path) or is_dated(path, date) or path in (LEDGER, WEEKLY.format(key=key))


def _session(files):
    if not files:
        return None
    g = files.get
    return session_from(g('kr/data/kr_market_data.json'), g('kr/data/kr_flows.json'),
                        g('kr/data/kr_industry.json'), g('kr/data/kr_top_value.json'))


def ledger_row(files):
    if not files or not files.get(MARKET_DATA):
        return None
    return index_record(files[MARKET_DATA])


def run_checks(files):
    """그 실행의 `kr_market_data.json.checks` 전체 사본 — manifest 에 기록만 한다(2026-11-12).
    manifest 는 실행마다 추가만 되므로, 같은 날 뒤의 정상 재수집이 고정 경로를 덮어도 이 기록은 남는다.
    알림과 `kr/index_check.py --report` 는 이것만 읽는다. 없거나 깨졌으면 {"error": "unreadable"}."""
    import json
    try:
        md = json.loads((files or {}).get(MARKET_DATA) or b'')
    except (ValueError, TypeError):
        md = None
    ck = md.get('checks') if isinstance(md, dict) else None
    return copy.deepcopy(ck) if isinstance(ck, dict) else {'error': 'unreadable'}


def checks_field_status(checks):
    """manifest field_status 에 얹는 요약 — 세부는 manifest['checks'] 에."""
    if not isinstance(checks, dict) or 'error' in checks:
        return {'checks': 'unreadable'}
    out = {}
    ip = checks.get('index_pct') if isinstance(checks.get('index_pct'), dict) else {}
    for name in ('KOSPI', 'KOSDAQ'):
        if isinstance(ip.get(name), dict):
            out[f'index_pct.{name}'] = ip[name].get('status')
    if ip:
        out['index_pct.mode'] = f"{ip.get('mode')}/{ip.get('config_status')}"
    fl = checks.get('flows') if isinstance(checks.get('flows'), dict) else {}
    for mkt in ('KOSPI', 'KOSDAQ'):
        if isinstance(fl.get(mkt), dict):
            out[f'flows.{mkt}'] = fl[mkt].get('state')
    tv = checks.get('top_value')
    if isinstance(tv, dict):
        out['top_value'] = 'error' if 'error' in tv else \
            f"rows={tv.get('rows')}/dash={tv.get('dash')}/bad={tv.get('bad')}"
    return out


def _nonempty(v):
    return v not in (None, {}, [], '')


def _apply_promotions(sessions, prov, promotions, key):
    for date, plist in sorted((promotions or {}).items()):
        if week_key(date) != key:
            continue
        for p in plist:
            f = p.get('field') or ''
            if not f.startswith('session.'):
                continue
            part = f[len('session.'):]
            s = sessions.setdefault(date, {})
            if part.startswith('flows.'):
                s.setdefault('flows', {})[part.split('.', 1)[1]] = copy.deepcopy(p['value'])
            else:
                s[part] = copy.deepcopy(p['value'])
            prov.setdefault(date, {})[part] = 'promotion'


def merge_week(remote_agg, run_files, p_files, date, published, promotions, ledger_rows, key,
               published_dates=None):
    """원격 주간 파일 + 이번 실행 → 새 주간 파일(finalize 결과 + `_sessions` + `_provenance`).

    `published` = 원격에 D 의 일간 글이 있다. `p_files` = 발행 커밋 P 트리의 세션 입력(없으면 None).
    """
    sessions = copy.deepcopy((remote_agg or {}).get('_sessions') or {})
    prov = copy.deepcopy((remote_agg or {}).get('_provenance') or {})
    run = _session(run_files)

    if run is not None and week_key(date) == key:
        body = {k: v for k, v in run.items() if k != 'date'}
        # 미발행일도 같은 날 재수집이 있던 값을 지우지 않는다(collect_kr_data 의 upsert_session 과 같은 규칙, 2026-11-12)
        if not published:
            sessions[date] = merge_session(sessions.get(date), body)
            prov[date] = {'industry': 'run', 'top_value': 'run', 'flows': 'run'}
        elif p_files is None:
            sessions[date] = merge_session(sessions.get(date), body)   # P 를 못 찾음 — 오늘처럼(「같음」)
            prov[date] = {'industry': 'run_no_publish_commit', 'top_value': 'run_no_publish_commit',
                          'flows': 'run_no_publish_commit'}
    if published and p_files is not None and week_key(date) == key:
        ps = _session(p_files)
        cur = sessions.get(date) or {}
        new = {k: v for k, v in ps.items() if k not in ('date', 'flows')}
        flows = {}
        for mkt in sorted(set((cur.get('flows') or {})) | set(ps.get('flows') or {})):
            have = (cur.get('flows') or {}).get(mkt)
            flows[mkt] = have if _nonempty(have) else ps['flows'].get(mkt)
            flows = {m: v for m, v in flows.items() if _nonempty(v)}
        new['flows'] = flows
        if not flows and 'flows_note' not in new:
            new['flows_note'] = '잠정치 제외'
        sessions[date] = new
        p = prov.setdefault(date, {})
        p.update({'industry': 'published', 'top_value': 'published'})
        p.setdefault('flows', 'published_or_remote')

    # 다음 거래일 관측 수급 — 이전 날짜(같은 주)만. 동결과 별개의 선택 정책(collect_kr_data 와 같은 코드 모양).
    for ed, mkts in sorted(((run or {}).get('extra_flows') or {}).items()):
        if week_key(ed) != key or ed == date:
            continue
        prior = dict(sessions.get(ed) or {})
        pf = dict(prior.get('flows') or {})
        pf.update(mkts)
        prior['flows'] = pf
        sessions[ed] = prior
        for m in mkts:
            prov.setdefault(ed, {})[f'flows.{m}'] = 'next_session_observed'

    _apply_promotions(sessions, prov, promotions, key)

    final = finalize({'span': 'weekly', 'key': key, 'sessions': sessions}, index_series(ledger_rows))
    hold_published_gaps(final, published_dates if published_dates is not None else ([date] if published else []))
    final['_sessions'] = sessions
    final['_provenance'] = prov
    return final


def merge_ledger(remote_rows, run_row, p_row, date, published, promotions):
    """원장 D 행: 발행됐으면 P 트리 값(빈 지수는 빈 채), 아니면 이번 실행 값을 기존 행에 지수별로 합친 것
    (재수집이 못 읽은 지수를 지우지 않는다 — 2026-11-12). 승격이 맨 마지막."""
    rows = [dict(r) for r in (remote_rows or []) if r.get('report_date') != date]
    existing = next((r for r in (remote_rows or []) if r.get('report_date') == date), None)
    if not published:
        row = merge_index_record(existing, run_row)
    elif p_row is not None:
        row = p_row
    else:
        row = merge_index_record(existing, run_row)
    row = copy.deepcopy(row) if row else None
    for p in (promotions or {}).get(date) or []:
        f = p.get('field') or ''
        if f.startswith('ledger.indices.'):
            row = row or {'report_date': date, 'indices': {}}
            row.setdefault('indices', {})[f.rsplit('.', 1)[1]] = float(p['value'])
    if row:
        rows.append(row)
    rows.sort(key=lambda r: r.get('report_date') or '')
    return rows


def hold_published_gaps(agg, published_dates, ledger_rows=None):
    """발행된 날의 지수 빈 칸이 있으면 주간을 보류한다(complete=false) — 자동 보완하지 않고 수동 정정
    (사용자 결정 2026-11-10, 의도한 무결성 통제). 미발행일의 빈 칸은 건드리지 않는다.
    ledger_rows 를 주면 missing 표식이 없어도 원장과 세션 날짜로 직접 계산한다(구현 검토 4회 #3)."""
    from kr.period import INDEX_NAMES
    pub = set(published_dates or ())
    gaps = {m for m in (agg or {}).get('missing') or []
            if m.count('.') == 2 and m.startswith('indices.') and m.rsplit('.', 1)[1] in pub}
    if ledger_rows is not None:
        have = {r.get('report_date'): (r.get('indices') or {}) for r in ledger_rows}
        for d in sorted(set(((agg or {}).get('_sessions') or {})) & pub):
            for name in INDEX_NAMES:
                if have.get(d, {}).get(name) is None:
                    gaps.add(f'indices.{name}.{d}')
    if gaps:
        agg['complete'] = False
        agg.setdefault('missing', [])
        for g in sorted(gaps):
            if g not in agg['missing']:
                agg['missing'].append(g)
        note = 'held: 발행된 날의 지수 누락 — 원자료 확인·글 정정 뒤 versions.py promote'
        if note not in agg['missing']:
            agg['missing'].append(note)
    return agg
