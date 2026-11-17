"""발행 전 자료 상태 검사 — 검사기가 판정에 쓰는 자료가 있고, 읽히고, 오늘 것이고, 수집에 성공했는가 (2026-11-17).

1a 「자료 누락 차단」. 정책 파일 `config/prepub_inputs.json`(`prepub-inputs/1`)이 자료 폴더의 모든 파일을 넷으로 나눈다.
- `gate`: 검사기가 판정에 쓴다 — 없거나 비었거나 깨졌거나 낡았거나 수집 실패면 그 검사는 「미완료」(발행 보류).
- `writer`: 작성자만 쓴다 — 차단하지 않고 `risk`(어떤 미검증 정보가 들어올 수 있나)·`covered_by`(글에 실린 뒤 어느 검사기가
  다른 자료와 대조하나, 없으면 null)를 기록에 싣는다.
- `unused`: 작성·검사 모두 안 쓴다. 없어도 막지 않는다.
- `discontinued`: 의도적으로 수집을 멈춘 자료 — 사유·중단일·영향·승인 주체(`approved_by: "user"` 만)를 적는다.
  등록된 `missing_key` 는 시장 데이터의 `missing` 에서 결측으로 세지 않는다.
  **잔여 위험: 권한 분리 전에는 루틴이 이 정책 파일을 고쳐 수집 실패를 수집 중단으로 바꿀 수 있다.**
분류되지 않은 파일이 자료 폴더에 있으면 미완료다(새 파일은 반드시 분류된다).

판정(`state`): ok / missing / empty_file / unreadable / stale(자료 기준일 ≠ 발행일) / failed(수집 실패 표시) /
incomplete_fields(필수 항목·날짜 칸 빠짐, 대상 목록이 비었는데 없음 확인이 없음) / unstamped(수집 상태 표시 없음) /
changed_after_collect(`_collect_status.json` 의 해시와 다름).
- 수집 상태 표시 = 파일 최상위 `collect` 객체, 또는 `<datadir>/_collect_status.json` 의 `files[<상대경로>]`(목록형·JSON 이
  아닌 파일). 수집기(작업 2)가 쓴다. `empty: "confirmed_none"` 만 「조회가 끝까지 성공했고 대상이 0건」이다.
- `unstamped` 는 **적용일(`EFFECTIVE`) 전에는 경고, 적용일부터 미완료**. 초기값 None = 아직 강제하지 않는다 — 작업 2 가
  배포되고 첫 수집을 확인한 뒤 사람이 날짜를 넣는다. 옛 칸(`report_date`·`ok`·`error`·`status`·`complete`·`missing`·
  `pending`)으로 판정할 수 있는 조건은 적용일과 무관하게 지금부터 강제한다. 날짜 칸이 없는 자료(econ_indicators·intraday·
  kr_flows·kr_intraday·kr_econ·kr_top_value·kr_index_etf·kr_stance_eval·원문 txt)는 적용일 전에는 신선도를 확인할
  길이 없다 — 그 구멍을 닫는 것이 적용일이다.
- **`EFFECTIVE` 가 None 인 동안 1a 는 완료가 아니다** — 빈 대상 목록(표시 없이 비면 「대상 없음이 확인되지 않음」 조건으로
  남길 뿐 막지 않는다 — `unconfirmed_empty`), 날짜 칸 없는 자료의 신선도, 목록형·txt 자료의 수집 실패를 막지 못한다.
- 적용일부터 수집 잡이 쓰는 gate 파일(produced_by collector·reference)은 `_collect_status.json` 에 항목과 sha256 이
  있어야 한다(없으면 unstamped).
- 판정할 수 없는 것은 정상으로 추정하지 않는다. 이 검사는 루틴이 자료·규칙을 직접 고치는 우회를 막지 않는다(권한 분리 단계).
설계 docs/superpowers/specs/2026-11-17-input-health.md
"""
import fnmatch
import hashlib
import json
import math
import os
import re

FORMAT = 'prepub-inputs/1'
EFFECTIVE = None
# 1a 의 「자료 없음 = 미완료(2)」가 적용되는 첫 글 날짜. 발행 뒤 재검사(정정기·윤문기·매일 알림)의 `--recheck`(옛 판정)과
# 「원본도 2 면 기존 실패로 허용」은 이 날짜 **전** 글에만 쓴다(1a 구현 검토 #9). **배포일과 같아야 한다** — 이 날짜부터
# 배포 전까지 발행된 글은 옛 규칙으로 쓰였는데 새 규칙으로 재검사된다. 사본: `review/corrector.py`·`review/style_pass.py`
# (레포 밖 사본에서도 돈다 — 시험이 같게 묶는다).
STRICT_FROM = '2026-11-17'


_POST_NAME = re.compile(r'(\d{4}-\d{2}-\d{2})\.html')


def post_date(html_path):
    """글 파일 이름이 **정확히 `YYYY-MM-DD.html`** 일 때만 그 날짜, 아니면 None(1a 구현 검토 2회차 F5 — 전에는 이름의
    첫 날짜를 읽어 `2026-11-16-2026-11-17.html` 이 11/16 글로 통했고, 정정기는 끝 날짜, 윤문기는 정규 경로만 봤다)."""
    m = _POST_NAME.fullmatch(os.path.basename(str(html_path or '')))
    if not m:
        return None
    try:
        import datetime
        datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return m.group(1)


def legacy_post(html_path):
    """이 글이 옛 판정(1a 적용 전)을 받을 수 있는가 — 정규 이름의 날짜가 STRICT_FROM 전일 때만. 날짜를 모르면 아니다.
    **재검사 날짜 판정은 이 함수 하나다** — 검사기(`legacy_recheck`)·정정기·윤문기가 모두 부른다."""
    d = post_date(html_path)
    return bool(d and d < STRICT_FROM)


def legacy_recheck(flag, html_path, date=None):
    """재검사 플래그(`--recheck`·`--legacy-releases`)가 옛 판정을 줄 수 있는가 — `legacy_post` 가 참일 때만.
    `--date` 를 함께 받은 검사기는 그 날짜가 파일 이름의 날짜와 같아야 한다(다르면 옛 판정 없음)."""
    if not flag or not legacy_post(html_path):
        return False
    return date is None or date == post_date(html_path)
CLASSES = ('gate', 'writer', 'unused', 'discontinued')
STATES = ('ok', 'missing', 'empty_file', 'unreadable', 'stale', 'failed', 'incomplete_fields', 'unstamped',
          'changed_after_collect')
STATE_KO = {'ok': '정상', 'missing': '파일 없음', 'empty_file': '빈 파일', 'unreadable': '읽지 못함',
            'stale': '날짜가 발행일과 다름', 'failed': '수집 실패', 'incomplete_fields': '필수 항목 빠짐',
            'unstamped': '수집 상태 표시 없음', 'changed_after_collect': '수집 뒤 바뀜'}
_ORDER = ('failed', 'stale', 'incomplete_fields', 'changed_after_collect', 'unstamped')
COLLECT_STATUS = ('ok', 'failed', 'partial')
EMPTY = ('has_data', 'confirmed_none', 'unknown')
STATUS_FILE = '_collect_status.json'
ROOTS = ('datadir', 'tg', 'stance_next')
FILE_ROOTS = ('tg', 'stance_next')
PRODUCERS = ('collector', 'reference', 'writer', 'ledger', 'meta')
# 적용일부터 `_collect_status.json` 에 항목·해시가 있어야 하는 생산자 — 수집 잡이 쓰는 파일(stamp_collect 등록표).
# reference = 수집기가 쓰지만 수집 상태 칸을 쓰지 않는 참고 파일(검사기가 날짜를 직접 본다 — scorecard.json).
LEDGER_PRODUCERS = ('collector', 'reference')
# 장부 항목의 `run`(stamp_collect.RUN_OK 와 같다 — 시험이 묶는다): 이번 실행이 썼다 / 단계가 건너뛰었다 / 동결
RUN_OK = ('written', 'skipped', 'kept')
_SHA = re.compile(r'^[0-9a-f]{64}$')
_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')


class PolicyError(Exception):
    pass


def _root_of(path):
    m = re.match(r'^<([a-z_]+)>(/.*)?$', path or '')
    return m.group(1) if m and m.group(1) in ROOTS else None


def validate(pol):
    """형식이 다르면 PolicyError — 정책을 못 읽은 채 검사를 돌리지 않는다(실행기는 미완료 exit 2)."""
    if not isinstance(pol, dict) or pol.get('format') != FORMAT or not isinstance(pol.get('markets'), dict):
        raise PolicyError('자료 분류 정책 형식이 다르다')
    for market, m in pol['markets'].items():
        if not isinstance(m, dict) or not isinstance(m.get('files'), list) \
                or not isinstance(m.get('discontinued', []), list):
            raise PolicyError(f'{market} 분류 목록이 없다')
        for e in m['files']:
            if not isinstance(e, dict) or not isinstance(e.get('name'), str) or not e['name']:
                raise PolicyError(f'{market} 분류 항목에 이름이 없다: {e!r}'[:200])
            if e.get('class') not in ('gate', 'writer', 'unused'):
                raise PolicyError(f'{market} {e.get("path")} 분류가 gate·writer·unused 가 아니다')
            if _root_of(e.get('path')) is None:
                raise PolicyError(f'{market} {e.get("path")} 경로가 <datadir>/·<tg>·<stance_next> 로 시작하지 않는다')
            if e['class'] == 'writer' and ('risk' not in e or 'covered_by' not in e):
                raise PolicyError(f'{market} {e["path"]} writer 분류에 risk·covered_by 가 없다')
            if e.get('produced_by', 'collector') not in PRODUCERS:
                raise PolicyError(f'{market} {e["path"]} produced_by 가 다르다')
            w = e.get('when')
            if w is not None and (not isinstance(w, dict) or e.get('else_class') not in ('writer', 'unused')
                                  or not all(isinstance(w.get(k), str) for k in ('file', 'each', 'any_ok', 'template'))):
                raise PolicyError(f'{market} {e["path"]} 조건부 입력(when)의 형식이 다르다')
        for d in m.get('discontinued', []):
            if not isinstance(d, dict) or _root_of(d.get('path')) is None:
                raise PolicyError(f'{market} 수집 중단 항목의 경로가 없다')
            if d.get('approved_by') != 'user':
                # 수집 중단은 사람이 승인한 것만 — 루틴이 실패를 중단으로 바꾸지 못하게(권한 분리 전에는 파일 수정으로 가능)
                raise PolicyError(f'{market} {d.get("path")} 수집 중단 등록에 approved_by: "user" 가 없다')
            for k in ('name', 'reason', 'since', 'approved_at'):
                if not isinstance(d.get(k), str) or not d[k]:
                    raise PolicyError(f'{market} {d.get("path")} 수집 중단 등록에 {k} 가 없다')
            if not isinstance(d.get('affects'), dict):
                raise PolicyError(f'{market} {d.get("path")} 수집 중단 등록에 영향(affects)이 없다')
    return pol


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            pol = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PolicyError(f'자료 분류 정책을 읽지 못했다: {exc}') from exc
    return validate(pol)


def entries(pol, market):
    m = (pol.get('markets') or {}).get(market)
    if not isinstance(m, dict):
        raise PolicyError(f'{market} 자료 분류가 없다')
    return m['files'], m.get('discontinued', [])


def paths_of(pol, market):
    files, disc = entries(pol, market)
    return [e['path'] for e in files] + [d['path'] for d in disc]


def enforced(date):
    return bool(EFFECTIVE) and bool(date) and date >= EFFECTIVE


def _present(ctx):
    """{정책 경로: 실제 파일} — 정책 경로는 `<datadir>/상대경로`, 파일 뿌리는 `<tg>`·`<stance_next>` 그대로."""
    out = {}
    root = ctx.get('datadir')
    if root and os.path.isdir(root):
        for d, dirs, names in os.walk(root):
            dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
            for n in sorted(names):
                if not n.startswith('.'):
                    full = os.path.join(d, n)
                    out['<datadir>/' + os.path.relpath(full, root).replace(os.sep, '/')] = full
    for k in FILE_ROOTS:
        p = ctx.get(k)
        if p and os.path.isfile(p):
            out[f'<{k}>'] = p
    return out


def _display(key, full):
    if key in ('<tg>', '<stance_next>'):
        return f'{key}/{os.path.basename(full)}' if full else key
    return key


def _pat(p, date):
    """정책 경로의 `{date}` 를 발행일로 — 그날 파일만 다른 분류를 받는다(예: KR `news/{date}.json` 만 작성자 입력)."""
    return p.replace('{date}', date or '')


def _is_glob(p):
    return any(c in p for c in '*?[')


def _read_json(full):
    try:
        with open(full, encoding='utf-8') as fh:
            return json.load(fh), None
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return None, type(exc).__name__


def _conditional(e, present):
    """조건부 입력이 오늘 필수인 경로들 — 다른 gate 자료의 값에 묶는다(예: 연준 사건 책이 원문을 받았다고 한 사건)."""
    w = e['when']
    full = present.get(w['file'])
    if not full:
        return set()                      # 묶인 자료가 없으면 그 자료가 이미 미완료다 — 여기서 추정하지 않는다
    obj, err = _read_json(full)
    if err or not isinstance(obj, dict) or not isinstance(obj.get(w['each']), list):
        return set()
    out = set()
    for ev in obj[w['each']]:
        if not isinstance(ev, dict):
            continue
        srcs = ev.get(w['any_ok'])
        if isinstance(srcs, list) and any(isinstance(s, dict) and s.get('ok') for s in srcs):
            key = ev.get('key')
            # 이상한 키(경로 문자)는 그대로 「없는 파일」로 남긴다 — 고치지 않는다
            out.add(w['template'].format(key=key if isinstance(key, str) and _KEY.match(key) else '<잘못된 키>'))
    return out


def _ref(e, present):
    r = e.get('date_ref')
    if not isinstance(r, dict) or not present.get(r.get('file')):
        return None
    obj, err = _read_json(present[r['file']])
    return obj.get(r.get('field')) if not err and isinstance(obj, dict) else None


def _empty(v):
    return v is None or v == '' or v == [] or v == {}


def _raw_target(e, obj):
    """정책의 대상 목록 칸 그대로(거르기 전) — `<items>` 는 파일 최상위. 칸이 없으면 None."""
    t = e.get('target')
    if not t:
        return None
    return obj if t == '<items>' else (obj.get(t) if isinstance(obj, dict) else None)


def _target_list(e, obj):
    """정책의 대상 목록(`target`, `target_where` 로 거른 것) — 없거나 목록이 아니면 None."""
    if not e.get('target'):
        return None
    lst = _raw_target(e, obj)
    where = e.get('target_where')
    if isinstance(lst, list) and isinstance(where, dict):
        # 「대상」이 목록의 일부일 때(예: 연준 사건 책의 fresh 사건만) — 수집기의 empty 와 같은 뜻으로 센다
        lst = [x for x in lst if isinstance(x, dict) and all(x.get(k) == v for k, v in where.items())]
    return lst if isinstance(lst, list) else None


def _stamp_ok_shape(c):
    return (isinstance(c, dict) and c.get('status') in COLLECT_STATUS and isinstance(c.get('as_of'), str)
            and isinstance(c.get('required_ok'), bool) and isinstance(c.get('missing'), list)
            and c.get('empty') in EMPTY)


def _health(e, key, full, date, status_files, excuse, ref=None, on=False):
    """gate 파일 하나 → (state, reasons, sha, as_of, obj, stamp, unconfirmed_empty).

    unconfirmed_empty = 수집 상태 표시가 없는데 대상 목록이 비었다(적용일 전) — 「대상 0건」과 「수집 실패로 빈 목록」을
    가를 수 없다. 막지 않되 기록·알림에 조건으로 남긴다(1a 구현 검토 #2)."""
    reasons = []
    try:
        size = os.path.getsize(full)
        with open(full, 'rb') as fh:
            raw = fh.read()
    except OSError as exc:
        return 'unreadable', [f'읽지 못했다({type(exc).__name__})'], None, None, None, None, False, {}
    sha = hashlib.sha256(raw).hexdigest()
    if size == 0 or not raw:
        return 'empty_file', ['0바이트'], sha, None, None, None, False, {}
    produced = e.get('produced_by', 'collector')
    obj = None
    if key.endswith('.json') or full.endswith('.json'):
        try:
            obj = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            return 'unreadable', [f'JSON 이 깨졌다({type(exc).__name__})'], sha, None, None, None, False, {}
    else:
        try:
            if not raw.decode('utf-8').strip():
                return 'empty_file', ['내용이 비었다'], sha, None, None, None, False, {}
        except UnicodeDecodeError:
            return 'unreadable', ['UTF-8 로 읽지 못했다'], sha, None, None, None, False, {}
    if produced == 'meta':
        if not isinstance(obj, dict) or not isinstance(obj.get('files'), dict):
            return 'unreadable', ['수집 상태 파일 형식이 다르다'], sha, None, obj, None, False, {}
        return 'ok', [], sha, None, obj, None, False, {}

    def bad(state, why):
        reasons.append((state, why))

    d = obj if isinstance(obj, dict) else {}
    as_of = None
    # 옛 칸 — 적용일과 무관하게 지금부터
    if isinstance(obj, dict):
        if 'ok' in d and d['ok'] is not True:
            bad('failed', f'ok={d["ok"]!r}')
        if d.get('error'):
            bad('failed', 'error 가 있다')
        if 'status' in d and d['status'] not in (e.get('status_ok') or ('ok', 'complete')):
            bad('failed', f'status={str(d["status"])[:40]}')
        if 'complete' in d and d['complete'] is not True:
            bad('incomplete_fields', 'complete 가 참이 아니다')
        if 'missing' in d:
            miss = d['missing'] if isinstance(d['missing'], list) else ['<형식이 다르다>']
            left = [m for m in miss if m not in excuse]
            if left:
                bad('incomplete_fields', 'missing: ' + ', '.join(str(x) for x in left[:5]))
        if d.get('pending'):
            bad('incomplete_fields', '결과 미확정(pending)이 있다')
    if e.get('date'):
        v = d.get(e['date'])
        if not isinstance(v, str):
            bad('incomplete_fields', f'날짜 칸 {e["date"]} 이 없다')
        else:
            as_of = v
            if e.get('date_rule') == 'ref':
                # 다른 gate 자료가 말하는 날짜와 같아야 한다(예: 직전 매크로 책 = macro_eval.macro_date)
                if not isinstance(ref, str):
                    bad('incomplete_fields', f'기준 날짜({e["date_ref"]["field"]})를 읽지 못해 날짜를 확인할 수 없다')
                elif v != ref:
                    bad('stale', f'{e["date"]}={v} ≠ {e["date_ref"]["field"]}={ref}')
            elif v != date:
                bad('stale', f'{e["date"]}={v} ≠ 발행일 {date}')
    # 수집 상태 표시
    skey = (e.get('stamp_key') or key.split('>/', 1)[-1]).format(date=date)
    entry = status_files.get(skey) if isinstance(status_files, dict) else None
    # 이번 수집 실행이 이 파일을 다시 쓰지 못했다(`stamp_collect.py` 의 run: failed) — 남아 있는 옛 파일이 「성공」이라
    # 말해도 이번 실행의 결과가 아니다(1a 구현 검토 2회차 F3). 옛 판의 표시는 `stale_copy` 에 있다.
    run_failed = isinstance(entry, dict) and entry.get('run') == 'failed'
    if run_failed:
        entry_stamp = entry.get('stale_copy') if isinstance(entry.get('stale_copy'), dict) else {}
    else:
        entry_stamp = entry
    # 수집 상태 파일의 항목은 해시만 담기도 한다(collect 칸이 파일 안에 있는 자료) — 상태 칸이 있어야 표시로 본다
    side = entry_stamp if isinstance(entry_stamp, dict) and 'status' in entry_stamp else None
    stamp = d.get('collect') if isinstance(obj, dict) and 'collect' in d else side
    confirmed = (produced == 'collector' and _stamp_ok_shape(stamp) and stamp['status'] == 'ok'
                 and stamp['empty'] == 'confirmed_none')
    for k in e.get('require') or []:
        if k == '<items>':
            if not isinstance(obj, list) or not obj:
                bad('incomplete_fields', '목록이 비었다')
        elif not isinstance(obj, dict) or _empty(obj.get(k)):
            if k == e.get('target') and confirmed and isinstance(obj, dict) and isinstance(obj.get(k), list):
                continue       # 대상 목록이 정상 조회 뒤 0건(confirmed_none) — 빈 일정이 정상인 날(1a 구현 검토 #7)
            bad('incomplete_fields', f'필수 칸 {k} 가 비었다')
    if e.get('target') and not isinstance(_raw_target(e, obj), list):
        # 칸이 없거나 목록이 아니면 「빈 목록」이 아니다 — 깨진 자료다. 적용일·수집 상태 표시와 무관하게 막는다
        # (1a 구현 검토 2회차 F1: `{"report_date": D, "ok": true}` 인 입찰 책이 「대상 없음 미확인」 조건으로 발행 가능했다)
        bad('incomplete_fields', f'대상 목록 {e["target"]} 칸이 없거나 목록이 아니다')
    if isinstance(entry, dict) and isinstance(entry.get('sha256'), str) and entry['sha256'] != sha:
        if e.get('rewritten_by'):
            # 수집 뒤 루틴이 정해진 명령으로 다시 쓰는 파일(예: build_liquidity --recompute) — 해시는 다를 수 있다.
            # 수집 상태 칸의 건강 조건과 아래 항목 요구는 그대로 본다.
            pass
        else:
            bad('changed_after_collect', '수집 상태 파일의 해시와 다르다')
    recollect = None
    if run_failed:
        old = entry.get('stale_copy') if isinstance(entry.get('stale_copy'), dict) else {}
        recollect = ('이번 수집에서 이 파일을 다시 쓰지 못했다 — 옛 판 있음'
                     + (f'({old["collected_at"]} 수집)' if isinstance(old.get('collected_at'), str) else '')
                     + (f': {str(entry.get("response"))[:120]}' if entry.get('response') else ''))
        if on:
            bad('failed', recollect)          # 적용일부터 막는다(재수집 1회 뒤 보류와 같은 길). 그 전에는 조건으로 남긴다
            recollect = None
    elif on and produced in LEDGER_PRODUCERS:
        # 적용일부터 수집 잡이 쓰는 파일마다 장부 항목·유효한 해시가 있어야 한다 — 없으면 해시 대조가 조용히 꺼진다
        # (1a 구현 검토 #6: `{"files": {}}` 로 모든 대조가 빠졌다)
        if not isinstance(status_files, dict):
            bad('unstamped', '수집 상태 기록(_collect_status.json)을 읽지 못해 해시를 대조할 수 없다')
        elif not (isinstance(entry, dict) and isinstance(entry.get('sha256'), str) and _SHA.match(entry['sha256'])):
            bad('unstamped', f'수집 상태 기록에 이 파일({skey})의 항목·해시가 없다')
        elif entry.get('run') not in RUN_OK:
            # 이번 실행이 이 파일을 다시 썼는지(또는 정당하게 건너뛰었는지) 장부가 말하지 못한다 — 성공으로 추정하지 않는다
            bad('unstamped', f'수집 상태 기록이 이 파일을 이번 실행이 썼는지 말하지 못한다(run={entry.get("run")!r})')
    if stamp is not None and produced == 'collector':
        if not _stamp_ok_shape(stamp):
            bad('incomplete_fields', '수집 상태 칸(collect) 형식이 다르다')
        else:
            if stamp['status'] != 'ok':
                bad('failed', f'collect.status={stamp["status"]}')
            if stamp['as_of'] != date:
                bad('stale', f'collect.as_of={stamp["as_of"]} ≠ 발행일 {date}')
            as_of = stamp['as_of'] if as_of is None else as_of
            if not stamp['required_ok'] or [m for m in stamp['missing'] if m not in excuse]:
                bad('incomplete_fields', '수집기가 필수 항목을 다 채우지 못했다고 적었다')
            if stamp['empty'] == 'unknown':
                bad('incomplete_fields', '대상이 있는지 모른다(collect.empty=unknown)')
            t = e.get('target')
            if t and stamp['empty'] != 'unknown':
                lst = _target_list(e, obj)
                if isinstance(lst, list):
                    if not lst and stamp['empty'] != 'confirmed_none':
                        bad('incomplete_fields', f'{t} 가 비었는데 「없음 확인」이 없다')
                    if lst and stamp['empty'] == 'confirmed_none':
                        bad('incomplete_fields', f'{t} 가 있는데 「없음 확인」이라고 적었다')
    elif stamp is None and produced == 'collector':
        bad('unstamped', '수집 상태 표시(collect·_collect_status)가 없다')
    # 「표시 없는 빈 배열」만 조건으로 남는다 — 칸의 부재·잘못된 형식은 위에서 막았다
    unconfirmed = bool(stamp is None and produced == 'collector' and e.get('target')
                       and _target_list(e, obj) == [])
    extra = {'recollect_failed': recollect}
    if not reasons:
        return 'ok', [], sha, as_of, obj, stamp, unconfirmed, extra
    states = {s for s, _ in reasons}
    state = next(s for s in _ORDER if s in states)
    return state, [w for _, w in reasons], sha, as_of, obj, stamp, unconfirmed, extra


def assess(pol, market, ctx):
    """→ {files: {정책 경로: {...}}, unclassified: [...], discontinued: [...], enforced, effective, _objs}.

    정책 경로 = `<datadir>/상대경로` 또는 파일 뿌리 `<tg>`·`<stance_next>`(실제 파일 이름은 `file`)."""
    files, disc = entries(pol, market)
    date = ctx.get('date')
    present = _present(ctx)
    excuse = {d['missing_key'] for d in disc if isinstance(d.get('missing_key'), str)}
    status_files = None
    sf = present.get('<datadir>/' + STATUS_FILE)
    if sf:
        obj, err = _read_json(sf)
        status_files = obj.get('files') if not err and isinstance(obj, dict) and isinstance(obj.get('files'), dict) \
            else None
    cond = {i: _conditional(e, present) for i, e in enumerate(files) if e.get('when')}
    out, objs, unclassified = {}, {}, []
    on = enforced(date)

    def put(key, e, full, cls=None):
        cls = cls or e['class']
        rec = {'class': cls, 'name': e['name'], 'file': _display(key, full), 'state': 'ok', 'reason': '',
               'sha256': None, 'as_of': None, 'blocking': False, 'stamped': False}
        if cls == 'gate':
            if full is None:
                rec['state'] = 'missing'
                rec['reason'] = '파일이 없다'
                # 적용일부터 필수가 되는 파일(수집 상태 기록 — 없으면 해시 대조가 조용히 꺼진다)
                rec['blocking'] = not e.get('optional') or bool(e.get('required_when_enforced') and on)
            else:
                state, why, sha, as_of, obj, stamp, unconfirmed, extra = _health(
                    e, key, full, date, status_files, excuse, _ref(e, present), on)
                rec.update(state=state, reason='; '.join(why)[:300], sha256=sha, as_of=as_of,
                           stamped=stamp is not None, unconfirmed_empty=unconfirmed)
                if extra.get('recollect_failed'):
                    rec['recollect_failed'] = extra['recollect_failed'][:300]
                rec['blocking'] = state != 'ok' and not (state == 'unstamped' and not on)
                objs[key] = obj
            if e.get('optional'):
                rec['optional'] = True
        else:
            if full is not None:
                try:
                    with open(full, 'rb') as fh:
                        rec['sha256'] = hashlib.sha256(fh.read()).hexdigest()
                except OSError:
                    rec['state'] = 'unreadable'
            else:
                rec['state'] = 'missing'
            if cls == 'writer':
                rec['risk'], rec['covered_by'] = e.get('risk'), e.get('covered_by')
            elif cls == 'discontinued':
                for k in ('reason', 'since', 'affects', 'approved_by', 'approved_at'):
                    rec[k] = e.get(k)
            if e.get('note') or e.get('else_note'):
                rec['note'] = e.get('note') if cls == e.get('class') else e.get('else_note')
        out[key] = rec

    for key in sorted(present):
        hit = None
        for i, e in enumerate(files):
            if fnmatch.fnmatchcase(key, _pat(e['path'], date)):
                hit = (i, e)
                break
        if hit is None:
            d = next((x for x in disc if fnmatch.fnmatchcase(key, _pat(x['path'], date))), None)
            if d is not None:
                put(key, dict(d, **{'class': 'discontinued'}), present[key])
            else:
                unclassified.append(_display(key, present[key]))
            continue
        i, e = hit
        if e.get('when'):
            put(key, e, present[key], 'gate' if key in cond[i] else e['else_class'])
        else:
            put(key, e, present[key])
    # 있어야 하는데 없는 gate 자료
    for i, e in enumerate(files):
        if e['class'] != 'gate':
            continue
        if e.get('when'):
            for key in sorted(cond[i] - set(present)):
                put(key, e, None)
        elif not _is_glob(e['path']) and _pat(e['path'], date) not in present \
                and (not e.get('optional') or (e.get('required_when_enforced') and on)):
            put(_pat(e['path'], date), e, None)
    return {'files': out, 'unclassified': unclassified, 'effective': EFFECTIVE, 'enforced': on, 'date': date,
            'discontinued': [{k: d.get(k) for k in ('path', 'name', 'reason', 'since', 'affects', 'approved_by',
                                                     'approved_at', 'missing_key')} for d in disc],
            '_objs': objs, '_present': present}


def blocks(f):
    return bool(f.get('blocking'))


def blocking(health):
    bad = sorted(k for k, f in health['files'].items() if blocks(f))
    return {'files': bad, 'unclassified': list(health['unclassified']),
            'any': bool(bad or health['unclassified'])}


def unconfirmed_empty(health):
    """적용일 전, 수집 상태 표시 없이 대상 목록이 빈 gate 자료 — 막지 않지만 「대상 없음이 확인되지 않음」 조건.
    **`EFFECTIVE` 가 None 인 동안 1a 는 완료가 아니다**: 이 빈 목록(연준 사건·입찰·원문 목록·움직인 종목 등)이 정상
    0건인지 수집 실패인지 가를 수 없다(1a 구현 검토 #2)."""
    return sorted(k for k, f in health['files'].items()
                  if f['class'] == 'gate' and f.get('unconfirmed_empty') and not f['blocking'])


def recollect_failed(health):
    """적용일 전, 이번 수집 실행이 다시 쓰지 못해 같은 날 옛 판이 남은 gate 자료 — 막지 않지만 조건으로 남긴다
    (적용일부터는 failed 로 막는다, 1a 구현 검토 2회차 F3)."""
    return sorted(k for k, f in health['files'].items()
                  if f['class'] == 'gate' and f.get('recollect_failed') and not f['blocking'])


def describe_recollect(f):
    rel = str(f.get('file') or '').split('>/', 1)[-1]
    return f'{f.get("name")}({rel}) — 이번 수집 실패, 옛 판으로 검사함(적용일 전)'


def describe_empty(f):
    rel = str(f.get('file') or '').split('>/', 1)[-1]
    return f'{f.get("name")}({rel}) — 대상 없음이 확인되지 않음(적용일 전)'


def warnings(health):
    """막지 않지만 조건으로 남길 것 — 적용일 전의 unstamped."""
    return sorted(k for k, f in health['files'].items()
                  if f['class'] == 'gate' and f['state'] == 'unstamped' and not f['blocking'])


def for_gate(health, paths):
    """검사기의 입력 가운데 막는 것 → [정책 경로]. 조건부 패턴(`*`)은 오늘 필수인 것 전부."""
    out = []
    for p in paths or []:
        keys = [k for k in health['files'] if fnmatch.fnmatchcase(k, p)] if _is_glob(p) else [p]
        for k in keys:
            f = health['files'].get(k)
            if f is not None and blocks(f):
                out.append(k)
    return out


def na_when(health, spec):
    """(참인가, 근거) — 「해당 없음」은 정상 조회로 대상이 없음을 확인한 경우만.
    근거 'collect' = 수집 상태가 ok·confirmed_none 이고(`min_checked` 가 있으면 `collect.checked` 가 그 이상 —
    실제로 잰 종목이 있다, `min_coverage` 가 있으면 `checked ≥ ⌈min_coverage × expected⌉` — 수집기와 같은 기준),
    'legacy' = 적용일 전, 수집 상태 표시가 없고 옛 칸이 다 정상이며 지정 목록이 비었고 **독립 근거**
    (`legacy_evidence`)가 있는 경우: 근거 목록이 `min_items`(모집단 × MIN_COVERAGE, `common.movers.LEGACY_MIN_ITEMS`)
    행 이상이고 **행마다 `date_field` 가 발행일**이며, `id_field`(종목)가 있고 `value_field`(등락)가 유한한
    **고유 종목**이 `min_items` 이상이다(2회차 F4). 근거를 정하지 않았거나, 한 종목만 쟀거나, 날짜를 입증할 수
    없으면 legacy na 는 없다 — 미완료(2026-11-17, KR 11/16 은 종목을 하나도 재지 못한 날이었고, 1a 구현 검토 #1 은
    한 종목만 잰 날도 「해당 없음」이 되는 것을 찾았다). 지금 `kr_stock_moves.json` 의 행에는 날짜가 없어 KR 의
    옛 방식 na 는 나오지 않는다 — 적용일 뒤의 수집 상태(`collect`)로만 na 가 된다."""
    key = spec.get('file')
    f = health['files'].get(key)
    obj = health['_objs'].get(key)
    if not f or f['blocking'] or f['state'] not in ('ok', 'unstamped') or not isinstance(obj, dict):
        return False, None
    lst = obj.get(spec.get('list'))
    if not isinstance(lst, list) or lst:
        return False, None
    c = obj.get('collect')
    if f['stamped']:
        if not (isinstance(c, dict) and c.get('status') == 'ok' and c.get('empty') == 'confirmed_none'):
            return False, None
        need = spec.get('min_checked')
        got = c.get('checked')
        if need is not None and not (_int(got) and got >= need):
            return False, None
        if 'min_coverage' in spec:
            # 수집기가 「없음 확인」을 쓰는 기준(모집단 × MIN_COVERAGE)을 같은 곳에서 읽어 한 번 더 본다
            cov, exp = _resolve(spec['min_coverage']), c.get('expected')
            if not isinstance(cov, (int, float)) or not (_int(exp) and exp > 0 and _int(got)) \
                    or got < math.ceil(cov * exp):
                return False, None
        return True, 'collect'
    if health['enforced']:
        return False, None
    ev = spec.get('legacy_evidence')
    if not isinstance(ev, dict):
        return False, None
    full = health.get('_present', {}).get(ev.get('file'))
    proof, err = _read_json(full) if full else (None, 'missing')
    need = _resolve(ev.get('min_items'))
    if err or not isinstance(proof, list) or not _int(need) or len(proof) < need:
        return False, None
    # 그날 것임을 자료가 말해야 한다 — 날짜 칸이 없는 행(지금의 kr_stock_moves.json)으로는 입증할 수 없다
    df = ev.get('date_field')
    if not isinstance(df, str) or not all(isinstance(r, dict) and r.get(df) == health.get('date') for r in proof):
        return False, None
    # 「쟀다」는 것도 자료가 말해야 한다 — 종목 식별자가 있고 등락 수치가 유한한 행만, 같은 종목은 한 번만 센다
    # (1a 구현 검토 2회차 F4: 그날 날짜만 든 같은 객체 54개가 근거로 통했다). 칸 이름을 정하지 않았으면 근거가 없다.
    idf, vf = ev.get('id_field'), ev.get('value_field')
    if not isinstance(idf, str) or not isinstance(vf, str):
        return False, None
    measured = {r[idf] for r in proof if isinstance(r.get(idf), str) and r[idf].strip() and _finite(r.get(vf))}
    if len(measured) < need:
        return False, None
    return True, 'legacy'


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _resolve(v):
    """정책의 수치 — 수 그대로이거나 `{"module", "attr"}`(수집 쪽 상수를 한 곳에서 읽는다). 못 읽으면 None."""
    if isinstance(v, dict):
        try:
            import importlib
            return getattr(importlib.import_module(v['module']), v['attr'])
        except Exception:  # noqa: BLE001 — 못 읽은 기준으로 「해당 없음」을 주지 않는다
            return None
    return v


def describe(f):
    """「무엇이·왜」 — `시장 데이터(market_data.json) — 수집 실패`."""
    rel = str(f.get('file') or '').split('>/', 1)[-1]
    return f'{f.get("name")}({rel}) — {STATE_KO.get(f.get("state"), "판정 불가")}'


def public(health):
    """기록에 싣는 모양 — 원시 객체는 뺀다."""
    return {'files': {k: dict(v) for k, v in sorted(health['files'].items())},
            'unclassified': list(health['unclassified']), 'discontinued': list(health['discontinued']),
            'effective': health['effective'], 'enforced': health['enforced']}
