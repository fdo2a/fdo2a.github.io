"""오류 주입 영구 시험 — 실제 발행일 자료의 gate 자료를 하나씩 망가뜨리면 발행 전 검사(run_gates)가 발행 불가여야 한다
(2026-11-17 1a 「자료 누락 차단」, 명세 작업 1 §9).

날짜 넷(`realday.DAYS`): US 11/12(입찰·유동성 발표·지표 원문) · US 11/16(연준 의장 연설) · KR 11/12·11/13.
KR 11/16 은 원본이 아니라 사고 회귀다 — 그날 종목을 하나도 재지 못했다(`kr_stock_moves.json` 0행). 정상적인 0건은
수집 계약대로 손으로 만든 자료(`collect` ok·confirmed_none·checked)로 시험한다. 두 방식으로 돈다.
- `stamped`: 작업 2 의 수집 상태 표시(`collect`·`_collect_status.json`)를 손으로 붙이고 적용일(`inputs.EFFECTIVE`)을
  발행일로 둔 상태 — 배포 뒤의 모습. **발행 가능한 변이 0건**이어야 한다.
- `legacy`: 지금 실제로 배포되는 상태(표시 없음, 적용일 None). 옛 칸으로 알아낼 수 없는 변이는 `LEGACY_UNDETECTABLE`
  에 이유와 함께 적는다 — 몰래 빼지 않는다. 목록 밖의 변이가 발행 가능하면 구멍이다(시험을 약하게 고치지 않는다).
변이마다 「발행 불가」만 보지 않고 그 파일의 판정(state)까지 맞춘다 — 해시 불일치가 다른 변이를 가리지 않게 표시
모드에서는 변이 뒤 해시를 다시 적는다. **자료 바이트를 하나도 바꾸지 못한 변이는 세지 않는다**(날짜 칸이 없는 옛
자료의 「날짜 하루 전」, 칸이 없는 목록형·txt 의 「수집 실패 표시」 — 1a 구현 검토 1회차, 행렬 수치가 부풀지 않게).

**이 시험이 증명하지 못하는 것**(1a 구현 검토 1회차 「시험과 호환성」): 표시 모드의 `collect` 는 손으로 붙인 것
(`realday.stamp`)이다 — 실제 수집기를 돌리지 않는다. 그래서 **수집기가 틀린 성공 표시를 쓰는 오류, 틀린
`confirmed_none`, 오래된 원천을 오늘 날짜로 찍는 오류는 이 시험이 증명하지 못한다.** 그 몫은 수집 쪽 단위 시험이다
(`scripts/kr/tests/test_collect_freshness.py` — 지난 날 분봉·수급·세션, `scripts/common/tests/test_movers.py` — 일부만
잰 움직인 종목, `scripts/us/tests/test_econ_collect_required.py` — 계산 재료 결측). 정의된 변이에서 부적절한 발행
허용이 0건이라는 것뿐이고, 발행이 안전하다는 증명이 아니다.
"""
import copy
import fnmatch
import json
import os
import shutil
from datetime import date as _date, timedelta

import pytest

from verification import inputs as I
from verification import record as R
from verification.tests import realday as RD

EXPECT = {'delete': 'missing', 'zero': 'empty_file', 'broken': 'unreadable', 'date_back': 'stale',
          'fail_ok': 'failed', 'fail_status': 'failed', 'fail_error': 'failed', 'fail_collect': 'failed',
          'missing_filled': 'incomplete_fields', 'require_emptied': 'incomplete_fields',
          'target_unknown': 'incomplete_fields', 'target_emptied': 'incomplete_fields', 'unstamp': 'unstamped',
          # 대상 목록 칸의 부재·잘못된 형식은 빈 배열이 아니다 — 두 방식 모두 막혀야 한다(1a 구현 검토 2회차 F1,
          # LEGACY_UNDETECTABLE 에 넣지 않는다)
          'drop_target_field': 'incomplete_fields', 'target_not_list': 'incomplete_fields',
          # 같은 날 재수집 실패 — 장부가 run: failed 라 적었다(옛 판의 바이트·표시는 그대로 정상). 표시 모드만(2회차 F3)
          'rerun_failed': 'failed'}

# 지금 배포 상태(수집 상태 표시 없음)에서 옛 칸으로 알아낼 수 없는 변이 — 작업 2 배포 뒤 적용일을 넣으면 닫힌다.
# (파일 종류, 변이) → 이유. 파일 종류는 정책 경로. 발행은 막지 않지만 글 판정은 조건부(conditional)이고 조건에
# unconfirmed_empty 가 있어야 한다 — 숨기지 않는다(1a 구현 검토 #2).
# 적용일 전에 바이트를 바꿀 칸이 없는 변이(날짜 칸 없는 자료의 날짜, 목록형·txt 의 실패 표시)는 아예 변이로 세지
# 않는다 — 그 자료들의 신선도·실패는 적용일 전에는 알 수 없다(잔여 위험, 명세 「잔여 위험」).
_TARGET = '수집 성공 표시가 없어 「대상 0건」과 「수집 실패로 빈 목록」을 가를 수 없다(collect.empty 로 닫힌다)'
LEGACY_UNDETECTABLE = {
    **{(p, 'target_emptied'): _TARGET for p in (
        '<datadir>/fed/events.json', '<datadir>/auctions.json', '<datadir>/releases/index.json',
        '<datadir>/kr_movers.json', '<datadir>/movers.json', '<tg>', '<datadir>/telegram.json')},
}


def _prev(d):
    return (_date.fromisoformat(d) - timedelta(days=1)).isoformat()


@pytest.fixture(scope='module')
def days(tmp_path_factory):
    out = {}
    for m, d in RD.DAYS:
        base = str(tmp_path_factory.mktemp(f'{m}-{d}'))
        ctx = RD.restore(base, m, d)
        out[(m, d)] = (base, ctx)
    return out


def _policy(ctx):
    cfgp = os.path.join(ctx['repo'], 'config', 'prepub_gates.json')
    cfg = R.load_config(cfgp)
    return cfg, R.load_policy(cfg, cfgp)


def _fresh(base, ctx, dest, stamped):
    """작업 공간 사본 — 레포(코드·원장)는 같이 쓴다(검사기는 고치지 않는다)."""
    c = {k: v for k, v in ctx.items() if k != 'record'}
    for key in ('ws', 'side'):
        src = os.path.join(base, key)
        shutil.copytree(src, os.path.join(dest, key))
    c['datadir'] = os.path.join(dest, 'ws')
    for k in ('tg', 'stance_next'):
        if ctx.get(k):
            c[k] = ctx[k].replace(base, dest, 1)
    if stamped:
        _, pol = _policy(c)
        RD.stamp(c, _market(c), pol)
    return c


def _market(ctx):
    return 'kr' if '/kr/posts/' in ctx['html'] else 'us'


def _run(ctx, stamped, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', ctx['date'] if stamped else None)
    cfg, pol = _policy(ctx)
    return R.run_gates(cfg, _market(ctx), ctx, policy=pol)


def _entry_of(pol, market, key, date):
    files, _ = I.entries(pol, market)
    return next(e for e in files if fnmatch.fnmatchcase(key, I._pat(e['path'], date)))


def _gate_files(ctx):
    """그날 있는 gate 분류 파일 — {정책 키: (정책 항목, 실제 경로)}."""
    _, pol = _policy(ctx)
    m = _market(ctx)
    h = I.assess(pol, m, ctx)
    out = {}
    for key, f in h['files'].items():
        if f['class'] == 'gate' and f['state'] != 'missing':
            out[key] = (_entry_of(pol, m, key, ctx['date']), RD.path_of(ctx, key))
    return out


def _mutations(entry, full, stamped):
    is_json = full.endswith('.json')
    produced = entry.get('produced_by', 'collector')
    out = ['delete', 'zero', 'broken', 'date_back', 'missing_filled']
    if is_json:
        out += ['fail_ok', 'fail_status', 'fail_error']
    if produced == 'collector':
        out += ['fail_collect']
        if entry.get('target'):
            # 표시 모드에서도 빈 대상 목록을 넣는다 — 표시는 has_data 그대로(confirmed_none 없이 비우면 미완료)
            out += ['target_unknown', 'target_emptied', 'drop_target_field', 'target_not_list']
        if stamped:
            out += ['unstamp', 'rerun_failed']
    for k in entry.get('require') or []:
        out.append('require_emptied')
        break
    if produced == 'meta':
        out = ['zero', 'broken'] + (['delete'] if stamped else [])
    if not is_json:
        out = [x for x in out if x not in ('missing_filled',)]
    return out


def _load(full):
    with open(full, encoding='utf-8') as fh:
        return json.load(fh)


def _dump(full, obj):
    with open(full, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False)


def _status_entry(ctx, key, entry):
    p = os.path.join(ctx['datadir'], I.STATUS_FILE)
    st = _load(p)
    skey = (entry.get('stamp_key') or key.split('>/', 1)[-1]).format(date=ctx['date'])
    return p, st, st['files'].get(skey), skey


def apply(ctx, key, entry, full, kind, stamped):
    """변이 하나. 반환값 = 그 변이를 적용했는가(적용할 수 없는 조합이면 False)."""
    d = ctx['date']
    if kind == 'delete':
        os.unlink(full)
        return True
    if kind == 'zero':
        open(full, 'wb').close()
        return True
    if kind == 'broken':
        with open(full, 'wb') as fh:
            fh.write(b'{"broken": ' if full.endswith('.json') else b'\xff\xfe\x00 not utf-8')
        return True
    obj = _load(full) if full.endswith('.json') else None
    has_collect = isinstance(obj, dict) and 'collect' in obj
    if kind == 'date_back':
        done = False
        if isinstance(obj, dict) and entry.get('date'):
            obj[entry['date']] = _prev(obj[entry['date']]) if entry.get('date_rule') == 'ref' else _prev(d)
            done = True
        if has_collect:
            obj['collect']['as_of'] = _prev(d)
            done = True
        if obj is not None and done:
            _dump(full, obj)
        if stamped and not has_collect and entry.get('produced_by', 'collector') == 'collector':
            p, st, ent, _ = _status_entry(ctx, key, entry)
            if ent is not None and 'as_of' in ent:
                ent['as_of'] = _prev(d)
                _dump(p, st)
                done = True
        return done or True                 # 적용할 칸이 없으면 바이트를 바꾸지 않은 변이(legacy 에서 못 잡는 것)
    if kind in ('fail_ok', 'fail_status', 'fail_error'):
        if not isinstance(obj, dict):
            return False
        obj.update({'fail_ok': {'ok': False}, 'fail_status': {'status': 'failed'},
                    'fail_error': {'error': 'HTTP 500 injected'}}[kind])
        _dump(full, obj)
        return True
    if kind == 'fail_collect':
        if isinstance(obj, dict) and not has_collect:
            # 적용일 전이라도 수집기(작업 2)가 실패를 적으면 그대로 막는다
            obj['collect'] = dict(RD.STAMP, as_of=d, empty='has_data', status='failed', response='HTTP 500 injected')
            _dump(full, obj)
        elif has_collect:
            obj['collect']['status'] = 'failed'
            obj['collect']['response'] = 'HTTP 500 injected'
            _dump(full, obj)
        elif stamped:
            p, st, ent, _ = _status_entry(ctx, key, entry)
            if ent is None or 'status' not in ent:
                return False
            ent['status'] = 'failed'
            _dump(p, st)
        return True
    if kind == 'missing_filled':
        if isinstance(obj, dict):
            obj['missing'] = list(obj.get('missing') or []) + ['injected/field']
            if has_collect:
                obj['collect']['missing'] = ['injected/field']
                obj['collect']['required_ok'] = False
            _dump(full, obj)
            return True
        return False
    if kind == 'require_emptied':
        k = (entry.get('require') or [None])[0]
        if k == '<items>':
            _dump(full, [])
        elif isinstance(obj, dict):
            obj[k] = type(obj.get(k))() if isinstance(obj.get(k), (dict, list, str)) else None
            _dump(full, obj)
        else:
            return False
        return True
    if kind in ('target_unknown', 'target_emptied'):
        t = entry['target']
        if not isinstance(obj, dict):
            return False
        obj[t] = []
        if kind == 'target_unknown':
            # 대상 목록을 비우고 「모름」 — 수집기가 조기 반환·예외 경로에서 쓰는 모양
            obj['collect'] = dict(obj.get('collect') or dict(RD.STAMP, as_of=d), empty='unknown')
        _dump(full, obj)
        return True
    if kind in ('drop_target_field', 'target_not_list'):
        # 수집 상태 표시는 그대로 둔다 — 칸만 빠지거나 목록이 아닌 손상
        t = entry['target']
        if t == '<items>':
            if kind == 'drop_target_field':
                return False                              # 최상위가 목록인 파일에는 뺄 칸이 없다
            _dump(full, {'items': obj})
            return True
        if not isinstance(obj, dict):
            return False
        if kind == 'drop_target_field':
            if t not in obj:
                return False
            del obj[t]
        else:
            obj[t] = {'0': obj.get(t)}
        _dump(full, obj)
        return True
    if kind == 'rerun_failed':
        # stamp_collect 가 「이번 실행은 이 파일을 다시 쓰지 못했다」고 적은 모양 — 파일 자체는 건드리지 않는다
        p, st, ent, skey = _status_entry(ctx, key, entry)
        if ent is None:
            return False
        st['files'][skey] = {'present': True, 'collect_in': ent.get('collect_in'), 'status': 'failed',
                             'run': 'failed', 'response': '이번 수집 실행에서 다시 쓰이지 않았다 — injected',
                             'stale_copy': {k: v for k, v in ent.items() if k != 'run'}}
        _dump(p, st)
        return True
    if kind == 'unstamp':
        if has_collect:
            del obj['collect']
            _dump(full, obj)
        p, st, ent, skey = _status_entry(ctx, key, entry)
        if ent is not None:
            for k in [k for k in ent if k not in ('sha256', 'bytes')]:
                del ent[k]
            if not has_collect:
                del st['files'][skey]
            _dump(p, st)
        return True
    raise AssertionError(kind)


def _snapshot(dest):
    """작업 공간(ws·side)의 모든 파일 바이트 해시 — 변이가 실제로 무엇을 바꿨는지."""
    import hashlib
    out = {}
    for d, _dirs, names in os.walk(dest):
        for n in names:
            p = os.path.join(d, n)
            with open(p, 'rb') as fh:
                out[os.path.relpath(p, dest)] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _keys_for(ctx, full):
    """같은 실제 파일을 가리키는 정책 키들(US 작업 공간 telegram.json = --tg)."""
    out = []
    for k in ('tg', 'stance_next'):
        if ctx.get(k) and os.path.abspath(ctx[k]) == os.path.abspath(full):
            out.append(f'<{k}>')
    rel = os.path.relpath(full, ctx['datadir'])
    if not rel.startswith('..'):
        out.append('<datadir>/' + rel)
    return out


def _matrix(days, stamped, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    tasks = []
    for (m, d), (base, ctx0) in days.items():
        probe = _fresh(base, ctx0, str(tmp_path / f'probe-{m}-{d}-{stamped}'), stamped)
        for key, (entry, _full) in sorted(_gate_files(probe).items()):
            for kind in _mutations(entry, _full, stamped):
                tasks.append((m, d, base, ctx0, key, entry, kind, str(tmp_path / f'{m}-{d}-{stamped}-{len(tasks)}')))

    def one(t):
        m, d, base, ctx0, key, entry, kind, dest = t
        c = _fresh(base, ctx0, dest, stamped)
        full = RD.path_of(c, key)
        before = _snapshot(dest)
        if not apply(c, key, entry, full, kind, stamped) or _snapshot(dest) == before:
            shutil.rmtree(dest, ignore_errors=True)
            return None                           # 적용할 칸이 없어 바이트가 그대로 — 변이로 세지 않는다
        if stamped and entry.get('produced_by') != 'meta':
            RD.restamp_hashes(c)
        cfg, pol = _policy(c)
        res = R.run_gates(cfg, m, c, policy=pol)
        states = {k: res['health']['files'].get(k, {}).get('state') for k in _keys_for(c, full)}
        shutil.rmtree(dest, ignore_errors=True)
        return {'market': m, 'date': d, 'key': key, 'policy': entry['path'], 'kind': kind,
                'publish_ok': res['summary']['publish_ok'], 'states': states, 'status': res['summary']['status'],
                'incomplete_gates': res['summary']['incomplete'], 'blocking': res['summary']['blocking'],
                'conditions': [x.get('kind') for x in res['summary']['conditions']]}

    # 적용일은 모듈 상수 — 방식마다 한 번 정하고(표시 모드 = 가장 이른 날, 모든 날에 강제) 병렬로 돌린다
    # (검사기는 하위 프로세스라 스레드로 충분하다)
    monkeypatch.setattr(I, 'EFFECTIVE', min(d for _m, d in days) if stamped else None)
    with ThreadPoolExecutor(max_workers=8) as ex:
        return [r for r in ex.map(one, tasks) if r is not None]


def test_unmutated_real_days_are_publishable(days, monkeypatch, tmp_path):
    for stamped in (False, True):
        for (m, d), (base, ctx0) in days.items():
            c = _fresh(base, ctx0, str(tmp_path / f'{m}-{d}-{stamped}'), stamped)
            res = _run(c, stamped, monkeypatch)
            s = res['summary']
            assert s['publish_ok'], (m, d, stamped, s['blocking'], s['inputs'])
            assert not s['inputs']['unclassified'] and not s['inputs']['blocking']
            # 기록 때 상태와 같다(이름이 바뀐 상태만 옮긴다 — 옛 not_run = 지금 na)
            old = {g['name']: {'not_run': 'na'}.get(g['status'], g['status']) for g in ctx0['record']['gates']}
            new = {g['name']: g['status'] for g in res['gates']}
            assert {k: v for k, v in new.items() if k in old} == old, (m, d)


def test_stamped_mutations_all_block(days, monkeypatch, tmp_path):
    rows = _matrix(days, True, monkeypatch, tmp_path)
    holes = [(r['market'], r['date'], r['key'], r['kind']) for r in rows if r['publish_ok']]
    assert not holes, holes
    wrong = [(r['market'], r['date'], r['key'], r['kind'], r['states']) for r in rows
             if EXPECT[r['kind']] not in r['states'].values()]
    assert not wrong, wrong
    assert len(rows) >= 200, len(rows)
    _write_matrix('stamped', rows)


def test_legacy_mutations_block_except_the_listed(days, monkeypatch, tmp_path):
    rows = _matrix(days, False, monkeypatch, tmp_path)
    passed = {(r['policy'], r['kind']) for r in rows if r['publish_ok']}
    unexpected = sorted((r['market'], r['date'], r['key'], r['kind']) for r in rows
                        if r['publish_ok'] and (r['policy'], r['kind']) not in LEGACY_UNDETECTABLE)
    assert not unexpected, unexpected
    for r in rows:
        if not r['publish_ok'] or (r['policy'], r['kind']) not in LEGACY_UNDETECTABLE:
            continue
        # 막지 못한 것은 숨기지 않는다 — 조건부 판정·「대상 없음 미확인」 조건(1a 구현 검토 #2)
        assert r['status'] == 'conditional' and 'unconfirmed_empty' in r['conditions'], r
    # 막힌 변이는 그 파일의 판정이 맞아야 한다(검사기가 우연히 막은 것과 가른다 — 둘 다 기록한다)
    by_state = [(r['market'], r['date'], r['key'], r['kind'], r['states']) for r in rows
                if not r['publish_ok'] and (r['policy'], r['kind']) not in LEGACY_UNDETECTABLE
                and EXPECT[r['kind']] not in r['states'].values()]
    assert not by_state, by_state
    _write_matrix('legacy', rows)
    assert passed <= set(LEGACY_UNDETECTABLE)


def test_writer_and_unused_files_can_be_deleted(days, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    tasks = []
    for (m, d), (base, ctx0) in days.items():
        c0 = _fresh(base, ctx0, str(tmp_path / f'p-{m}-{d}'), False)
        _, pol = _policy(c0)
        h = I.assess(pol, m, c0)
        targets = sorted(k for k, f in h['files'].items()
                         if f['class'] in ('writer', 'unused', 'discontinued') and f['state'] != 'missing')
        assert targets, (m, d)
        tasks += [(m, d, base, ctx0, key, str(tmp_path / f'w-{m}-{d}-{i}')) for i, key in enumerate(targets)]

    def one(t):
        m, d, base, ctx0, key, dest = t
        c = _fresh(base, ctx0, dest, False)
        os.unlink(RD.path_of(c, key))
        cfg, pol = _policy(c)
        res = R.run_gates(cfg, m, c, policy=pol)
        shutil.rmtree(dest, ignore_errors=True)
        return (m, d, key, res['summary']['publish_ok'], res['summary']['blocking'])

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, tasks))
    blocked = [r for r in rows if not r[3]]
    assert not blocked, blocked
    assert len(rows) >= 60, len(rows)


def test_unclassified_file_is_incomplete(days, monkeypatch, tmp_path):
    for (m, d), (base, ctx0) in days.items():
        c = _fresh(base, ctx0, str(tmp_path / f'u-{m}-{d}'), False)
        with open(os.path.join(c['datadir'], 'surprise_new_feed.json'), 'w') as fh:
            fh.write('{}')
        res = _run(c, False, monkeypatch)
        s = res['summary']
        assert not s['publish_ok'] and s['status'] == 'incomplete' and 'inputs' in s['blocking']
        assert s['inputs']['unclassified'] == ['<datadir>/surprise_new_feed.json']
        assert R.exit_code(s) == 2


# ── 과거 사고 회귀 ─────────────────────────────────────────────────────────

def test_kr_1116_unmeasured_day_is_incomplete_not_na(tmp_path, monkeypatch):
    # 11/16 KR 은 「움직인 종목 0건」으로 not_run 이 찍혀 발행됐다 — 실제로는 종목을 하나도 재지 못한 수집 실패
    # (kr_stock_moves.json 0행). 옛 방식(legacy)으로도 독립 근거가 없으면 na 를 주지 않는다.
    ((m, d),) = RD.INCIDENT
    ctx = RD.restore(str(tmp_path / 'r'), m, d)
    ctx.pop('record')
    with open(os.path.join(ctx['datadir'], 'kr_stock_moves.json'), encoding='utf-8') as fh:
        assert json.load(fh) == []
    res = _run(ctx, False, monkeypatch)
    g = next(x for x in res['gates'] if x['name'] == 'check_movers')
    assert g['status'] == 'incomplete' and 'na_basis' not in g
    assert not res['summary']['publish_ok'] and res['summary']['status'] == 'incomplete'
    assert R.exit_code(res['summary']) == 2


def _movers_only(ctx, market):
    cfg, pol = _policy(ctx)
    spec = next(g for g in cfg['markets'][market]['gates'] if g['name'] == 'check_movers')
    return {'format': R.CONFIG_FORMAT, 'markets': {market: {'post': cfg['markets'][market]['post'], 'gates': [spec]}}}, pol


def test_confirmed_zero_movers_is_na_by_collect(days, monkeypatch, tmp_path):
    # 정상적인 0건 — 손으로 만든 자료: 조회 성공(ok)·없음 확인(confirmed_none)·잰 종목 수(checked)
    base, ctx0 = days[('kr', '2026-11-13')]
    d = ctx0['date']
    ok = dict(RD.STAMP, as_of=d, empty='confirmed_none', checked=60, expected=60)
    html = tmp_path / f'{d}.html'
    html.write_text('<html><body><main><h2>특징주</h2><p>움직인 종목 묶음이 없는 날이다.</p></main></body></html>')
    for i, (collect, moves, effective, want, basis) in enumerate((
            (ok, None, d, 'na', 'collect'),
            (dict(ok, checked=0), None, d, 'incomplete', None),
            (dict(ok, empty='unknown'), None, d, 'incomplete', None),
            ({k: v for k, v in ok.items() if k != 'checked'}, None, d, 'incomplete', None),
            (dict(ok, checked=1, expected=58), None, d, 'incomplete', None),          # 한 종목만 쟀다(검토 #1)
            (None, [{'name': '삼성전자', 'change_pct': 0.5}], None, 'incomplete', None),  # 한 종목·날짜 없음(검토 #1)
            (None, [{'name': f's{k}', 'change_pct': 0.5} for k in range(60)], None, 'incomplete', None),
            (None, [{'name': f's{k}', 'change_pct': 0.5, 'date': d} for k in range(60)], None, 'na', 'legacy'),
            (None, [], None, 'incomplete', None))):
        c = _fresh(base, ctx0, str(tmp_path / f'z{i}'), effective is not None)
        p = os.path.join(c['datadir'], 'kr_movers.json')
        obj = _load(p)
        obj['groups'] = []
        obj.pop('collect', None)
        if collect is not None:
            obj['collect'] = collect
        _dump(p, obj)
        if moves is not None:
            _dump(os.path.join(c['datadir'], 'kr_stock_moves.json'), moves)
        RD.restamp_hashes(c)
        c['html'] = str(html)
        cfg, pol = _movers_only(c, 'kr')
        monkeypatch.setattr(I, 'EFFECTIVE', effective)
        res = R.run_gates(cfg, 'kr', c, policy=pol)
        g = res['gates'][0]
        assert g['status'] == want and g.get('na_basis') == basis, (i, g['status'], g['reason'])
def test_us_auctions_ok_false_is_incomplete(days, monkeypatch, tmp_path):
    # 전에는 「경고: 입찰 결과 수집 실패 — 섹션 없이 발행한다」로 발행됐다
    base, ctx0 = days[('us', '2026-11-12')]
    c = _fresh(base, ctx0, str(tmp_path / 'a'), False)
    p = os.path.join(c['datadir'], 'auctions.json')
    obj = _load(p)
    obj.update(ok=False, error='TA_WS 응답 없음')
    _dump(p, obj)
    res = _run(c, False, monkeypatch)
    g = next(x for x in res['gates'] if x['name'] == 'check_auction')
    assert not res['summary']['publish_ok'] and g['status'] == 'incomplete' and g['exit'] is None
    assert '국채 입찰(auctions.json) — 수집 실패' in g['reason']


# ── 승인된 결측(accepted_missing) — 실제 날 자료·실제 정책으로 끝에서 끝까지 ─────────────────────────────
# 2026-11-17 사용자 승인: US 2026-10 CPI 전년 대비 둘(BLS 미발표)을 검증 대상에서 조건부로 뺀다(만료 2026-12-09).
# 자료 층은 풀리지만, 그 둘이 있었다면 판단이 달라질 수 있는 날은 check_macro 가 보류한다 — 11/12 는 그런 날이다.

CPI = {'CPI YoY': 'CPIAUCSL', 'Core CPI YoY': 'CPILFESL'}


def _cpi_day(base, ctx0, dest, month='2026-10', extra=None, coverage=True):
    """US 11/12 자료에 「CPI 전년 대비 둘을 만들 수 없다」를 수집기가 적는 모양 그대로 넣는다(표시 모드).
    그날 실제 macro_metrics 에는 이미 두 행이 없다(원천에 2025-10 이 없어 수집기가 행을 만들지 않았다)."""
    import sys
    sys.path.insert(0, RD.SCRIPTS)
    import collect_market_data as cmd
    from us import macro_metrics as M
    c = _fresh(base, ctx0, dest, True)
    d = c['date']
    reasons = dict({n: 'no_value' for n in CPI}, **(extra or {}))
    refs = {n: {'axis': 'Inflation', 'fred_id': f, 'transform': 'yoy_pct', 'ref_period': month, 'lacking': ['2025-10']}
            for n, f in CPI.items()}
    econ = cmd.econ_collect([{'name': 'x'}], reasons, d, refs=refs)
    mmc = cmd.macro_metrics_collect({'book_state': 'ok'}, econ, d)
    p = os.path.join(c['datadir'], 'econ_indicators.json')
    obj = _load(p)
    assert not [r for r in obj['indicators'] if r['name'] in CPI]              # 그날 원자료에 두 행이 없다
    obj['collect'] = econ
    _dump(p, obj)
    p = os.path.join(c['datadir'], 'macro_metrics.json')
    obj = _load(p)
    if coverage:
        obj = M.with_coverage(obj, cmd.excluded_scored(reasons, refs))
    obj['collect'] = mmc
    _dump(p, obj)
    # 결측은 두 파일 더 옮겨 간다 — 축 점수로 레짐을 판정한 책과, 축 점수가 목록을 정한 지표 원문 목록
    import eval_macro_regime
    import fetch_releases
    p = os.path.join(c['datadir'], 'macro_eval.json')
    ev = _load(p)
    ev['collect'] = eval_macro_regime.eval_collect(d, 'fresh', obj, 'ok')
    _dump(p, ev)
    p = os.path.join(c['datadir'], 'releases', 'index.json')
    idx = _load(p)
    assert idx['releases']                                                     # 그날 받을 원문이 있었다
    # 그날 원문은 다 받은 것으로 둔다(옛 목록에는 행마다의 수집 결과 칸이 없다) — 여기서 보는 것은 옮겨 온 결측뿐이다
    idx['collect'] = fetch_releases.index_collect({'report_date': d, 'releases': [{'key': 'x', 'ok': True}]}, 'fresh', mmc)
    _dump(p, idx)
    RD.restamp_hashes(c)
    return c


def _macro(res):
    return next(g for g in res['gates'] if g['name'] == 'check_macro')


def test_approved_cpi_gap_real_policy_real_day(days, monkeypatch, tmp_path):
    base, ctx0 = days[('us', '2026-11-12')]
    c = _cpi_day(base, ctx0, str(tmp_path / 'cpi'))
    monkeypatch.setattr(I, 'EFFECTIVE', c['date'])
    cfg, pol = _policy(c)
    res = R.run_gates(cfg, 'us', c, policy=pol)
    s = res['summary']
    # ① 자료 층: 승인된 두 지표만 빠졌다 — 막지 않고 조건으로(예외 ID·만료일이 기록에)
    assert not s['inputs']['blocking'] and not s['inputs']['unclassified'], s['inputs']
    conds = [x for x in s['conditions'] if x['kind'] == 'accepted_missing']
    assert sorted(x['file'] for x in conds) == ['<datadir>/econ_indicators.json', '<datadir>/macro_eval.json',
                                                '<datadir>/macro_metrics.json', '<datadir>/releases/index.json']
    assert all(x['ids'] == ['us-2026-10-cpi-yoy-not-published'] and x['expires'] == '2026-12-09' for x in conds)
    assert len(s['inputs']['accepted_missing']) == 4 and '원천 미발표' in s['inputs']['accepted_missing'][0]
    assert _load(os.path.join(c['datadir'], 'econ_indicators.json'))['collect']['status'] == 'partial'   # 원본 그대로
    # 조건 8: 이 날은 빠진 둘이 판단을 바꿀 수 있다 — check_macro 가 보류(미완료), 발행하지 않는다
    g = _macro(res)
    assert g['status'] == 'incomplete' and g['exit'] == 2, g
    assert '승인된 결측이 판단을 바꿀 수 있음 — 사람 승인 필요' in g['reason']
    assert not s['publish_ok'] and s['status'] == 'incomplete' and R.exit_code(s) == 2
    assert s['blocking'] == ['check_macro'], s['blocking']                      # 그것 하나 때문이다
    # 산출 범위(coverage)가 자료에 없으면 그것도 보류다(몇 개 중 몇 개로 냈는지 모른다)
    c2 = _cpi_day(base, ctx0, str(tmp_path / 'nocov'), coverage=False)
    g = _macro(R.run_gates(cfg, 'us', c2, policy=pol))
    assert g['status'] == 'incomplete' and '산출 범위' in g['reason']


def test_approved_cpi_gap_does_not_cover_anything_else(days, monkeypatch, tmp_path):
    base, ctx0 = days[('us', '2026-11-12')]
    monkeypatch.setattr(I, 'EFFECTIVE', ctx0['date'])
    both = {'<datadir>/econ_indicators.json', '<datadir>/macro_metrics.json', '<datadir>/macro_eval.json',
            '<datadir>/releases/index.json'}
    # ② 세 번째 지표가 더 빠지면 차단
    c = _cpi_day(base, ctx0, str(tmp_path / 'third'), extra={'JOLTS Job Openings': 'fetch_failed'})
    cfg, pol = _policy(c)
    s = R.run_gates(cfg, 'us', c, policy=pol)['summary']
    assert not s['publish_ok'] and both <= set(s['inputs']['blocking_files']) and not s['inputs']['accepted_missing']
    # ③ 같은 두 지표라도 다른 기준월이면 차단
    c = _cpi_day(base, ctx0, str(tmp_path / 'month'), month='2026-11')
    s = R.run_gates(cfg, 'us', c, policy=pol)['summary']
    assert not s['publish_ok'] and both <= set(s['inputs']['blocking_files'])
    # ④ 만료 뒤(글 날짜 > expires) — 실제 정책의 만료일을 이 글 날짜 전날로 바꾼 변형으로 본다
    c = _cpi_day(base, ctx0, str(tmp_path / 'expired'))
    late = copy.deepcopy(pol)
    for e in late['markets']['us']['files']:
        for a in e.get('accepted_missing') or []:
            a['expires'] = _prev(c['date'])
    s = R.run_gates(cfg, 'us', c, policy=I.validate(late))['summary']
    assert not s['publish_ok'] and both <= set(s['inputs']['blocking_files'])
    # 등록이 없는 정책(변형)에서는 두 파일이 그대로 막힌다
    none = copy.deepcopy(pol)
    for e in none['markets']['us']['files']:
        e.pop('accepted_missing', None)
    s = R.run_gates(cfg, 'us', c, policy=I.validate(none))['summary']
    assert not s['publish_ok'] and both <= set(s['inputs']['blocking_files'])


def _write_matrix(mode, rows):
    """보고용 — 변이 행렬 요약을 시험 임시 폴더 밖 환경 변수 경로에 남긴다(설정했을 때만)."""
    out = os.environ.get('INPUT_MUTATION_MATRIX')
    if not out:
        return
    keep = [{k: v for k, v in r.items() if k != 'res'} for r in rows]
    path = f'{out}.{mode}.json'
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(keep, fh, ensure_ascii=False, indent=1)
