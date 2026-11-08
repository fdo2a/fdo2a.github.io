"""새 발표 원장 — 매일 「오늘 처음 본 숫자」를 덧붙이기만 하는 기록 (2026-11-08).

`data/history/releases.jsonl` 한 줄이 한 사건이다. 주간 레짐 점검
(`period_scorecard.regime_check`)이 기간 전체를 이 원장으로 읽는다.

**왜 따로 두나.** 일간 `macro_metrics.new_releases` 는 어제 책(`macro.json.last_seen`)과
견준다. 그래서 같은 날 재실행하면 신규가 사라지고(11/05 를 11/06 09:13 에 다시 돌리자 0건),
같은 기준월 값이 고쳐져도 신규로 센다(11/03 내구재 1.84→1.91). 원장은 **자기 마지막
상태**와 견주므로 책 승격·재실행과 무관하다.

행 종류(`kind`):

* `scan` — 한 실행이 무엇을 봤는가. 실행마다 한 줄(`scan|날짜|run_id`)이라 재시도가 앞
  기록을 덮지 않는다. `observed` 는 그 실행에서 실제로 받은 지표 — 계열 하나만 빠진 날을
  주간이 알아보는 근거다.
* `release` — 기준기간이 원장의 마지막 상태보다 앞으로 갔다. `(이름, 기준기간)` 마다 한
  줄, 첫 기록이 이긴다.
* `revision` — 같은 기준기간인데 값이 바뀌었다. 채점하지 않는다. GDP 2·3차 추정이 여기에
  든다(속보만 새 발표다 — 몇 차 추정인지 알려 주는 원천이 없다).
* `baseline` — 원장이 처음 보는 이름. 그날 실제로 발표가 있었는지 알 수 없으니 채점하지
  않는다.

**When changing this**: read `docs/superpowers/specs/2026-11-08-weekly-regime-ledger.md`.
"""

import datetime as dt
import json
import os
import tempfile

from us.macro_metrics import INDICATOR_RELEASE, polarity_for

LEDGER = os.path.join('history', 'releases.jsonl')
PRINT_KINDS = ('release', 'revision', 'baseline')


def load(path):
    """원장 전체. **손상된 줄이 있으면 ValueError** — `history.read_jsonl` 처럼 건너뛰면
    다음 쓰기가 그 줄을 영영 지우고, 주간은 빠진 scan 을 「정상」으로 읽을 수 있다."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as e:
                raise ValueError(f'{path}:{n} 손상된 줄: {e}') from None
            problem = check_row(row)
            if problem:
                raise ValueError(f'{path}:{n} {problem}')
            rows.append(row)
    return rows


def check_row(row):
    """-> 문제 설명 또는 None. JSON 으로는 맞아도 모양이 틀린 줄을 읽을 때 막는다 —
    주간이 그 줄을 조용히 건너뛰면 빠진 관측이 「발표 없음」으로 읽힌다(codex 구현 #1)."""
    if not isinstance(row, dict):
        return '객체가 아닌 줄'
    kind = row.get('kind')
    if not isinstance(row.get('id'), str) or kind not in ('scan',) + PRINT_KINDS:
        return f'id·kind 가 없다: {row.get("id")!r} {kind!r}'
    if kind == 'scan':
        if _day(row.get('report_date')) is None or not isinstance(row.get('observed'), list):
            return 'scan 에 report_date·observed 가 없다'
        if not isinstance(row.get('baseline', False), bool):
            return 'scan.baseline 이 참·거짓이 아니다'
        for o in row['observed']:
            if not (isinstance(o, list) and len(o) >= 3 and isinstance(o[0], str) and o[0]
                    and all(x is None or isinstance(x, str) for x in o[1:3])):
                return f'scan.observed 항목 모양이 틀렸다: {o!r}'
        return None
    if not isinstance(row.get('name'), str) or not row['name']:
        return 'name 이 없다'
    if not all(row.get(k) is None or isinstance(row.get(k), str) for k in ('axis', 'role', 'trend')):
        return 'axis·role·trend 가 문자열이 아니다'
    for k in ('official_date', 'since'):
        if row.get(k) is not None and _day(row.get(k)) is None:
            return f'{k} 가 날짜가 아니다: {row.get(k)!r}'
    if row.get('gap') is not None and not isinstance(row.get('gap'), bool):
        return 'gap 이 참·거짓이 아니다'
    if _day(row.get('ref_period')) is None or _day(row.get('detected_on')) is None:
        return 'ref_period·detected_on 이 날짜가 아니다'
    return None


def _day(s):
    # 문자열만 날짜로 본다 — 정수 20261106 을 받아 주면 뒤의 문자열 비교에서 TypeError(codex 구현 4회 #1).
    if not isinstance(s, str):
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def latest_state(rows):
    """{name: (ref_period, actual)} — 원장이 마지막으로 인정한 값."""
    out = {}
    for r in rows:
        if r.get('kind') in PRINT_KINDS and r.get('name'):
            out[r['name']] = (r.get('ref_period'), r.get('actual'))
    return out


def last_observed(rows, before):
    """{name: date} — `before` 보다 앞선 scan 에서 그 이름이 마지막으로 보인 날."""
    out = {}
    for r in rows:
        if r.get('kind') != 'scan':
            continue
        d = r.get('report_date') or ''
        if d >= before:
            continue
        for name, *_ in r.get('observed') or []:
            if d > out.get(name, ''):
                out[name] = d
    return out


def _same(a, b):
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError, OverflowError):
        return a == b


def step_ok(name, prev_ref, new_ref):
    """기준기간이 정확히 한 칸 앞으로 갔나. 주간 7일·분기 3개월·월간 1개월."""
    a, b = _day(prev_ref), _day(new_ref)
    if a is None or b is None:
        return False
    window = polarity_for(name)[1]
    if window == 4:                                   # 주간(실업수당 청구)
        return (b - a).days == 7
    months = (b.year - a.year) * 12 + (b.month - a.month)
    return months == (3 if window == 1 else 1)


def official_date(name, since, detected_on, calendar):
    """-> (날짜 또는 None, 일정 파일의 report_date).

    일정은 **이번 실행이 덮어쓰기 전**의 `calendar.json` 이다 — 그 창이 report_date+1 부터라
    어제 파일에 오늘 일정이 있다. 오늘 쓴 파일(같은 날 재실행)이나 오늘을 덮지 못하는 오래된
    파일은 믿지 않는다. 창 (since, detected_on] 안의 confirmed 일정이 **정확히 하나**일 때만.
    """
    slug = INDICATOR_RELEASE.get(name)
    if not slug or not since or not isinstance(calendar, dict):
        return None, None
    crd = calendar.get('report_date')
    c, d = _day(crd), _day(detected_on)
    try:
        horizon = int(calendar.get('horizon_days') or 0)
    except (TypeError, ValueError):
        horizon = 0
    if c is None or d is None or not (c < d <= c + dt.timedelta(days=horizon)):
        return None, crd
    prefix = f'release-{slug}-'
    hits = [e.get('date') for e in calendar.get('events') or []
            if isinstance(e, dict) and e.get('kind') == 'release'
            and e.get('status') == 'confirmed'
            # 앞머리 일치가 아니라 전체 일치 — `employment` 가 다른 슬러그의 앞머리일 수 있다.
            and e.get('key') == prefix + str(e.get('date') or '').replace('-', '')
            and since < (e.get('date') or '') <= detected_on]
    if len(hits) != 1:
        return None, crd
    return hits[0], crd


def _role(row, econ_roles):
    return row.get('role') or econ_roles.get(row.get('name')) or 'scored'


def record(rows, macro_metrics, econ, market, calendar, run_id):
    """-> (새 행 목록, 경고 목록). 순수 함수 — 쓰기는 `append_rows`.

    세 파일(`market_data`·`econ_indicators`·`macro_metrics`)은 수집기 한 프로세스가 같은
    `generated` 로 쓴다. 셋이 다르면 같은 실행의 결과라는 보장이 없어 아무것도 쓰지 않는다 —
    그날은 주간에서 수집 누락일로 보인다.
    """
    mm, econ, market = macro_metrics or {}, econ or {}, market or {}
    rd = mm.get('report_date')
    gens = {mm.get('generated'), econ.get('generated'), market.get('generated')}
    if not rd or market.get('report_date') != rd:
        return [], [f'report_date 불일치: macro_metrics={rd} market_data={market.get("report_date")}']
    if len(gens) != 1 or None in gens:
        return [], [f'generated 불일치 — 같은 실행의 파일이 아니다: {sorted(map(str, gens))}']
    if not any(isinstance(r, dict) and r.get('name') and r.get('ref_period')
               for r in mm.get('indicators') or []):
        # 지표가 하나도 없는 수집을 정상 scan 으로 남기면 주간이 「새 발표 없음」으로 읽는다(codex 구현 4회 #2).
        return [], [f'{rd}: macro_metrics 에 지표가 없다 — 수집 누락으로 둔다']
    scans = [r for r in rows if r.get('kind') == 'scan']
    newest = max((r.get('report_date') or '' for r in scans), default='')
    if newest > rd:
        return [], [f'{rd} 는 원장의 마지막 수집일 {newest} 보다 앞이다 — 쓰지 않는다']
    scan_id = f'scan|{rd}|{run_id}'
    if any(r.get('id') == scan_id for r in scans):
        return [], []

    econ_roles = {i.get('name'): i.get('role') for i in econ.get('indicators') or []
                  if isinstance(i, dict) and i.get('role')}
    state = latest_state(rows)
    seen = last_observed(rows, rd)
    ids = {r.get('id') for r in rows}
    out, warnings, observed = [], [], []

    for r in mm.get('indicators') or []:
        name, ref, actual = r.get('name'), r.get('ref_period'), r.get('actual')
        if not name or not ref:
            continue
        role = _role(r, econ_roles)
        observed.append([name, r.get('axis'), role])
        base = {'name': name, 'label_ko': r.get('label_ko') or name, 'axis': r.get('axis'),
                'role': role, 'ref_period': ref, 'actual': actual, 'detected_on': rd,
                'run_id': run_id}
        prev = state.get(name)
        if prev is None:
            rid = f'{name}|{ref}|baseline'
            if rid not in ids:
                out.append({'id': rid, 'kind': 'baseline', **base})
            continue
        prev_ref, prev_actual = prev
        if ref > (prev_ref or ''):
            rid = f'{name}|{ref}'
            if rid in ids:
                continue
            since = seen.get(name)
            gap = not step_ok(name, prev_ref, ref)
            od, crd = (None, None) if gap else official_date(name, since, rd, calendar)
            out.append({'id': rid, 'kind': 'release', **base,
                        'trend': r.get('direction'), 'vs_prev': r.get('vs_prev'),
                        'prior_ref_period': prev_ref, 'since': since, 'gap': gap,
                        'official_date': od, 'date_source': 'calendar' if od else None,
                        'calendar_report_date': crd})
        elif ref == prev_ref:
            if not _same(actual, prev_actual):
                out.append({'id': f'{name}|{ref}|rev|{rd}|{run_id}', 'kind': 'revision',
                            **base, 'prior_actual': prev_actual})
        else:
            warnings.append(f'{name}: 기준기간이 {prev_ref} → {ref} 로 뒤로 갔다 — 기록하지 않는다')

    scan = {'id': scan_id, 'kind': 'scan', 'report_date': rd, 'run_id': run_id,
            'generated': mm.get('generated'), 'baseline': not state,
            'observed': observed}
    return [scan] + out, warnings


def append_rows(path, new_rows):
    """기존 행 뒤에 한 실행의 행을 **한 번에** 붙인다(임시 파일 + os.replace).

    중간에 죽으면 scan 만 남고 release 가 빠지는 일이 없다. 같은 id 는 거부한다 —
    덮어쓰기가 아니라 덧붙이기만 하는 원장이다.
    """
    if not new_rows:
        return 0
    rows = load(path)
    have = {r.get('id') for r in rows}
    dup = [r.get('id') for r in new_rows if r.get('id') in have]
    if dup or len({r.get('id') for r in new_rows}) != len(new_rows):
        raise ValueError(f'원장에 이미 있는 id: {dup}')
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.releases-', suffix='.tmp')
    os.close(fd)
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            for r in rows + list(new_rows):
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
        os.chmod(tmp, 0o644)        # mkstemp 는 0600 — 레포 파일 권한을 바꾸지 않는다
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return len(new_rows)
