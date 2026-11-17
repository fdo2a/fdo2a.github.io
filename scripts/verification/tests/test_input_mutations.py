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
모드에서는 변이 뒤 해시를 다시 적는다.
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
          'target_unknown': 'incomplete_fields', 'target_emptied': 'incomplete_fields', 'unstamp': 'unstamped'}

# 지금 배포 상태(수집 상태 표시 없음)에서 옛 칸으로 알아낼 수 없는 변이 — 작업 2 배포 뒤 적용일을 넣으면 닫힌다.
# (파일 종류, 변이) → 이유. 파일 종류는 정책 경로.
_NO_DATE = '날짜 칸이 없는 자료 — 적용일 전에는 신선도를 확인할 길이 없다(collect.as_of 로 닫힌다)'
_NO_FLAG = '목록형·txt 자료 — 실패 표시를 담을 칸이 없다(_collect_status.json 으로 닫힌다)'
_TARGET = '수집 성공 표시가 없어 「대상 0건」과 「수집 실패로 빈 목록」을 가를 수 없다(collect.empty 로 닫힌다)'
LEGACY_UNDETECTABLE = {
    **{(p, 'date_back'): _NO_DATE for p in (
        '<datadir>/econ_indicators.json', '<datadir>/intraday.json', '<datadir>/kr_flows.json',
        '<datadir>/kr_intraday.json', '<datadir>/kr_econ.json', '<datadir>/kr_top_value.json',
        '<datadir>/kr_index_etf.json', '<datadir>/kr_stance_eval.json', '<datadir>/fed/*.txt')},
    **{(p, 'fail_collect'): _NO_FLAG for p in ('<datadir>/kr_top_value.json', '<datadir>/kr_index_etf.json',
                                               '<datadir>/fed/*.txt')},
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
            out += ['target_unknown'] + ([] if stamped else ['target_emptied'])
        if stamped:
            out += ['unstamp']
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
        if not apply(c, key, entry, full, kind, stamped):
            return None
        if stamped and entry.get('produced_by') != 'meta':
            RD.restamp_hashes(c)
        cfg, pol = _policy(c)
        res = R.run_gates(cfg, m, c, policy=pol)
        states = {k: res['health']['files'].get(k, {}).get('state') for k in _keys_for(c, full)}
        shutil.rmtree(dest, ignore_errors=True)
        return {'market': m, 'date': d, 'key': key, 'policy': entry['path'], 'kind': kind,
                'publish_ok': res['summary']['publish_ok'], 'states': states, 'status': res['summary']['status'],
                'incomplete_gates': res['summary']['incomplete'], 'blocking': res['summary']['blocking']}

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


def _write_matrix(mode, rows):
    """보고용 — 변이 행렬 요약을 시험 임시 폴더 밖 환경 변수 경로에 남긴다(설정했을 때만)."""
    out = os.environ.get('INPUT_MUTATION_MATRIX')
    if not out:
        return
    keep = [{k: v for k, v in r.items() if k != 'res'} for r in rows]
    path = f'{out}.{mode}.json'
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(keep, fh, ensure_ascii=False, indent=1)
