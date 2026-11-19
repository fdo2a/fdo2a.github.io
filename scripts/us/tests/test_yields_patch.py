"""수익률만 고치는 재실행 — 네이버 국채 종가만 빠진 당일 판을 전부 다시 모으지 않는다.

세 갈래: 쓸 수 있는 네이버 커브 → 고치기, 네이버가 아직 전 거래일 → 기다림(아무것도 안 씀),
그 밖 전부 → None(지금의 전체 수집). 설계: docs 가 아니라 plans/2026-11-19-us-collect-wait.md.
"""
import datetime as dt
import importlib
import json
import os
import types
import zoneinfo

import pytest

cmd = importlib.import_module('collect_market_data')

RD = '2026-11-18'
NY = zoneinfo.ZoneInfo('America/New_York')
GEN = '2026-11-19 07:41 KST'
RUN = '777-1'
STARTED = dt.datetime(2026, 11, 18, 17, 35, tzinfo=NY)
NOW = dt.datetime(2026, 11, 18, 18, 20, tzinfo=NY)


def _row(level, date, source, bp=1.0, wk=None):
    return {'level': level, 'date': date, 'source': source, 'bp': bp,
            'week_ago': level - 0.1 if wk is None else wk, 'week_ago_date': '2026-11-11'}


def naver_curve(date=RD):
    return {t: _row(lv, date, 'Naver', bp=-2.0)
            for t, lv in (('2Y', 3.5), ('5Y', 3.7), ('10Y', 4.1), ('30Y', 4.7))}


def base_market():
    data = {'generated': GEN, 'source': cmd.SOURCE, 'report_date': RD,
            'collection_started': STARTED.astimezone(dt.timezone.utc).isoformat(),
            'collection_run': RUN,
            'yields': {'2Y': _row(3.55, '2026-11-17', 'FRED'), '5Y': _row(3.72, RD, 'Yahoo'),
                       '10Y': _row(4.12, RD, 'Yahoo'), '30Y': _row(4.71, RD, 'Yahoo')},
            'yields_fred': {t: _row(3.9, '2026-11-17', 'FRED') for t in ('2Y', '5Y', '10Y', '30Y')},
            'sector_performance': {n: {'1D': 0.1, '1W': 0.2, '1M': 0.3, 'date': RD}
                                   for n, _ in cmd.SECTORS},
            'complete': False, 'missing': ['yields/naver_close_not_posted'],
            'session': {'marker': 'frozen'}, 'price_context': {'marker': 'frozen'}}
    for group, pairs in cmd.GROUPS:
        data[group] = {}
        for name, _ in pairs:
            row = {'last': 100.0, 'chg': 1.0, 'pct': 1.0, 'date': RD}
            if group in cmd.CUT_GROUPS:
                from us.close_cut import BASIS
                row.update({'basis': BASIS, 'prev': 99.0, 'prev_date': '2026-11-17'})
            data[group][name] = row
    cmd.apply_spreads(data, data['yields_fred'])
    return data


@pytest.fixture
def outdir(tmp_path, monkeypatch):
    d = tmp_path / 'data'
    (d / 'history').mkdir(parents=True)
    (d / 'releases').mkdir()
    (d / 'weekly').mkdir()
    md = base_market()
    # completeness 가 이 판을 「네이버만 빠짐」으로 읽는지부터 확인한다(시험 자료가 실제 계약과 맞는가).
    intraday = {'Nasdaq': {'open': 1}, 'S&P 500': {'open': 1}}
    assert cmd.completeness(md, intraday, naver_stale=True, report_date=RD) == \
        ['yields/naver_close_not_posted']
    w = lambda name, obj: (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    w('market_data.json', md)
    w('intraday.json', intraday)
    w('econ_indicators.json', {'generated': GEN, 'indicators': []})
    w('macro_metrics.json', {'generated': GEN, 'report_date': RD})
    w('macro_eval.json', {'report_date': RD, 'collection_run': RUN})
    w('releases/index.json', {'report_date': RD, 'run_id': RUN, 'status': 'complete',
                              'releases': [{'key': 'cpi', 'ok': True}]})
    (d / 'history' / 'releases.jsonl').write_text(
        json.dumps({'id': f'scan|{RD}|{RUN}', 'kind': 'scan', 'report_date': RD}) + '\n')
    (d / 'history' / 'market.jsonl').write_text(
        json.dumps({'report_date': '2026-11-17', 'indices': {'S&P 500': 99.0},
                    'yields': {'10Y': 4.2}}) + '\n'
        + json.dumps({'report_date': RD, 'indices': {'S&P 500': 100.0},
                      'yields': {'10Y': 4.12}}) + '\n')
    (d / 'yield_curve.png').write_bytes(b'OLDPNG')
    monkeypatch.setattr(cmd, 'render_curve', lambda y, path, **kw: open(path, 'wb').write(
        b'PNG:' + str(y['10Y']['level']).encode()))
    monkeypatch.setattr(cmd, 'daily_headlines', lambda root: {})
    monkeypatch.setenv('GITHUB_RUN_ID', '888')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')
    monkeypatch.delenv('GITHUB_OUTPUT', raising=False)
    return d


def args(outdir, no_patch=False):
    return types.SimpleNamespace(outdir=str(outdir), no_patch=no_patch)


def use_naver(monkeypatch, curve, latest):
    calls = []

    def fake(pages=2, page_size=60, expected_date=None, **kw):
        calls.append({'pages': pages, 'expected_date': expected_date, **kw})
        return (curve if (curve and latest == expected_date) else None), latest
    monkeypatch.setattr(cmd, 'naver_spot_yields', fake)
    return calls


def snapshot(d):
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, d)] = open(p, 'rb').read()
    return out


def edit(d, name, fn):
    p = d / name
    obj = json.loads(p.read_text(encoding='utf-8'))
    fn(obj)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')


# ── 고치기 ────────────────────────────────────────────────────────────────

def test_usable_naver_curve_patches_yields_and_derivatives(outdir, monkeypatch):
    calls = use_naver(monkeypatch, naver_curve(), RD)
    assert cmd.yields_patch_step(args(outdir), now=NOW) == 'patched'
    md = json.loads((outdir / 'market_data.json').read_text())
    assert md['complete'] is True and md['missing'] == []
    assert {r['source'] for r in md['yields'].values()} == {'Naver'}
    assert md['spread_2s10s_bp'] == pytest.approx(60.0)
    assert md['spread_2s10s_aligned'] is True
    assert md['spread_5s30s_bp'] == pytest.approx(100.0)
    # 첫 수집의 표시는 그대로다 — 원장·원문 index 가 그 실행에 묶여 있다.
    assert (md['generated'], md['collection_run']) == (GEN, RUN)
    assert md['yields_patched']['run'] == '888-1' and md['yields_patched']['date'] == RD
    assert md['session'] == {'marker': 'frozen'}
    assert (outdir / 'yield_curve.png').read_bytes() == b'PNG:4.1'
    rows = [json.loads(x) for x in (outdir / 'history' / 'market.jsonl').read_text().splitlines()]
    assert [r['report_date'] for r in rows] == ['2026-11-17', RD]
    assert rows[-1]['yields']['10Y'] == 4.1
    wk = json.loads((outdir / 'weekly' / '2026-W47.json').read_text())
    assert wk['sessions'] == 2
    # 시간 예산: 요청당 10초·1회·전체 상한.
    assert calls == [{'pages': 1, 'expected_date': RD, 'timeout': cmd.PATCH_PROBE_TIMEOUT_S, 'attempts': 1,
                      'budget_s': cmd.PATCH_PROBE_BUDGET_S}]
    assert not [f for f in snapshot(outdir) if '.patch-' in f]


def test_patch_emits_patched_output(outdir, monkeypatch, tmp_path):
    use_naver(monkeypatch, naver_curve(), RD)
    out = tmp_path / 'gh_out'
    monkeypatch.setenv('GITHUB_OUTPUT', str(out))
    assert cmd.yields_patch_step(args(outdir), now=NOW) == 'patched'
    assert out.read_text() == 'patched=true\n'


# ── 기다림 ────────────────────────────────────────────────────────────────

def test_stale_naver_waits_and_writes_nothing(outdir, monkeypatch, tmp_path):
    use_naver(monkeypatch, None, '2026-11-17')
    out = tmp_path / 'gh_out'
    monkeypatch.setenv('GITHUB_OUTPUT', str(out))
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) == 'waiting'
    assert snapshot(outdir) == before
    assert out.read_text() == 'skipped=true\nwaiting=true\n'


# ── 전체 경로로 넘어가는 경우 ───────────────────────────────────────────────

@pytest.mark.parametrize('curve, latest', [
    (None, None),                                   # 네이버를 못 받았다
    (None, '2026-11-19'),                           # 날짜가 앞서 있다
])
def test_unusable_probe_falls_through(outdir, monkeypatch, curve, latest):
    use_naver(monkeypatch, curve, latest)
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert snapshot(outdir) == before


def test_curve_without_bp_falls_through(outdir, monkeypatch):
    curve = naver_curve()
    curve['5Y']['bp'] = None
    use_naver(monkeypatch, curve, RD)
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert snapshot(outdir) == before


def test_curve_that_leaves_the_edition_incomplete_falls_through(outdir, monkeypatch):
    curve = naver_curve()
    curve['30Y']['week_ago'] = None
    use_naver(monkeypatch, curve, RD)
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert snapshot(outdir) == before


def _never(*a, **k):
    raise AssertionError('네이버를 부르면 안 된다')


INELIGIBLE = {
    'complete edition': lambda d: edit(d, 'market_data.json', lambda m: m.update(complete=True, missing=[])),
    'other gaps too': lambda d: edit(d, 'market_data.json', lambda m: m['missing'].append('fx/DXY')),
    'other source': lambda d: edit(d, 'market_data.json', lambda m: m.update(source='local')),
    'no start stamp': lambda d: edit(d, 'market_data.json', lambda m: m.pop('collection_started')),
    'no run stamp': lambda d: edit(d, 'market_data.json', lambda m: m.pop('collection_run')),
    'collected before the close': lambda d: edit(d, 'market_data.json', lambda m: m.update(
        collection_started=dt.datetime(2026, 11, 18, 16, 20, tzinfo=NY).astimezone(dt.timezone.utc).isoformat())),
    'collected on another day': lambda d: edit(d, 'market_data.json', lambda m: m.update(
        collection_started=dt.datetime(2026, 11, 17, 17, 35, tzinfo=NY).astimezone(dt.timezone.utc).isoformat())),
    'no intraday': lambda d: (d / 'intraday.json').unlink(),
    'econ from another run': lambda d: edit(d, 'econ_indicators.json', lambda m: m.update(generated='x')),
    'metrics from another run': lambda d: edit(d, 'macro_metrics.json', lambda m: m.update(generated='x')),
    'metrics of another day': lambda d: edit(d, 'macro_metrics.json', lambda m: m.update(report_date='2026-11-17')),
    'release index of another run': lambda d: edit(d, 'releases/index.json', lambda m: m.update(run_id='1-1')),
    'release index aborted': lambda d: edit(d, 'releases/index.json', lambda m: m.update(status='aborted')),
    'release index of another day': lambda d: edit(d, 'releases/index.json', lambda m: m.update(report_date='2026-11-17')),
    'a release row failed': lambda d: edit(d, 'releases/index.json', lambda m: m['releases'].append({'key': 'ppi', 'ok': False})),
    'no release index': lambda d: (d / 'releases' / 'index.json').unlink(),
    'macro_eval of another run': lambda d: edit(d, 'macro_eval.json', lambda m: m.update(collection_run='1-1')),
    'macro_eval without run': lambda d: edit(d, 'macro_eval.json', lambda m: m.pop('collection_run')),
    'macro_eval of another day': lambda d: edit(d, 'macro_eval.json', lambda m: m.update(report_date='2026-11-17')),
    'no macro_eval': lambda d: (d / 'macro_eval.json').unlink(),
    'ledger has no scan of the base run': lambda d: (d / 'history' / 'releases.jsonl').write_text(
        json.dumps({'id': f'scan|{RD}|1-1', 'kind': 'scan', 'report_date': RD}) + '\n'),
    'no ledger': lambda d: (d / 'history' / 'releases.jsonl').unlink(),
    'holiday key without a bond holiday': lambda d: edit(d, 'market_data.json', lambda m: m.update(
        yields_bond_holiday={'closed': RD, 'curve_date': '2026-11-17'})),
    'broken market_data': lambda d: (d / 'market_data.json').write_text('{'),
    'no market_data': lambda d: (d / 'market_data.json').unlink(),
}


@pytest.mark.parametrize('case', sorted(INELIGIBLE))
def test_ineligible_edition_goes_to_the_full_path(outdir, monkeypatch, case):
    INELIGIBLE[case](outdir)
    monkeypatch.setattr(cmd, 'naver_spot_yields', _never)
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert snapshot(outdir) == before


@pytest.mark.parametrize('now', [
    dt.datetime(2026, 11, 19, 0, 5, tzinfo=NY),     # 뉴욕 날짜가 넘어갔다 — 다른 세션일 수 있다
    dt.datetime(2026, 11, 18, 17, 30, tzinfo=NY),   # 첫 수집 시작보다 이르다(시계가 어긋남)
])
def test_wrong_clock_goes_to_the_full_path(outdir, monkeypatch, now):
    monkeypatch.setattr(cmd, 'naver_spot_yields', _never)
    assert cmd.yields_patch_step(args(outdir), now=now) is None


def test_no_patch_flag_skips_the_step(outdir, monkeypatch):
    monkeypatch.setattr(cmd, 'naver_spot_yields', _never)
    assert cmd.yields_patch_step(args(outdir, no_patch=True), now=NOW) is None


def test_bond_holiday_edition_is_patched_with_the_prior_bond_session(outdir, monkeypatch):
    (outdir / 'market_holidays.json').write_text(json.dumps({'us_bond': {'dates': [RD]}, 'dates': []}))
    edit(outdir, 'market_data.json', lambda m: m.update(
        yields_bond_holiday={'closed': RD, 'curve_date': '2026-11-17'}))
    calls = use_naver(monkeypatch, naver_curve('2026-11-17'), '2026-11-17')
    assert cmd.yields_patch_step(args(outdir), now=NOW) == 'patched'
    assert calls[0]['expected_date'] == '2026-11-17'
    md = json.loads((outdir / 'market_data.json').read_text())
    assert md['yields_bond_holiday'] == {'closed': RD, 'curve_date': '2026-11-17'}


def test_bond_holiday_without_the_key_goes_to_the_full_path(outdir, monkeypatch):
    (outdir / 'market_holidays.json').write_text(json.dumps({'us_bond': {'dates': [RD]}, 'dates': []}))
    monkeypatch.setattr(cmd, 'naver_spot_yields', _never)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None


# ── 쓰기 경계 ─────────────────────────────────────────────────────────────

def test_render_failure_installs_nothing(outdir, monkeypatch):
    use_naver(monkeypatch, naver_curve(), RD)

    def boom(*a, **k):
        raise RuntimeError('no font')
    monkeypatch.setattr(cmd, 'render_curve', boom)
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert snapshot(outdir) == before


def _failing_replace(fail_on, real=os.replace, also=()):
    def replace(src, dst):
        name = os.path.basename(dst)
        if name == fail_on and str(src).find('.patch-') >= 0:
            raise OSError('disk full')
        if name in also:
            raise OSError('restore failed')
        return real(src, dst)
    return replace


@pytest.mark.parametrize('fail_on', ['yield_curve.png', 'market.jsonl', '2026-W47.json',
                                     'market_data.json'])
def test_install_failure_restores_everything_and_fails_the_run(outdir, monkeypatch, fail_on):
    # 되돌린 뒤에도 전체 수집으로 넘어가지 않는다 — 쓰기가 실패한 디스크에서 전체 수집의 이력 쓰기
    # 실패는 삼켜져 섞인 판이 커밋될 수 있다. 실행이 실패로 끝나면 아무것도 커밋되지 않는다.
    use_naver(monkeypatch, naver_curve(), RD)
    before = snapshot(outdir)
    monkeypatch.setattr(cmd.os, 'replace', _failing_replace(fail_on))
    with pytest.raises(SystemExit) as e:
        cmd.yields_patch_step(args(outdir), now=NOW)
    assert e.value.code == 1
    assert snapshot(outdir) == before          # 임시 파일도 남지 않는다


def test_market_data_is_installed_last(outdir, monkeypatch):
    use_naver(monkeypatch, naver_curve(), RD)
    order, real = [], os.replace

    def replace(src, dst):
        order.append(os.path.basename(dst))
        return real(src, dst)
    monkeypatch.setattr(cmd.os, 'replace', replace)
    assert cmd.yields_patch_step(args(outdir), now=NOW) == 'patched'
    assert order == ['yield_curve.png', 'market.jsonl', '2026-W47.json', 'market_data.json']


def test_failed_restore_exits_nonzero(outdir, monkeypatch):
    use_naver(monkeypatch, naver_curve(), RD)
    monkeypatch.setattr(cmd, '_restore_file', lambda path, data: (_ for _ in ()).throw(OSError('ro')))
    monkeypatch.setattr(cmd.os, 'replace', _failing_replace('market.jsonl'))
    with pytest.raises(SystemExit) as e:
        cmd.yields_patch_step(args(outdir), now=NOW)
    assert e.value.code == 1


# ── 네이버 탐침의 시간 예산 ──────────────────────────────────────────────────

def _clock(monkeypatch):
    clock = {'t': 0.0}
    monkeypatch.setattr(cmd.time, 'monotonic', lambda: clock['t'])
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: clock.__setitem__('t', clock['t'] + s))
    return clock


def test_naver_probe_ends_within_budget_plus_one_timeout_when_every_request_times_out(monkeypatch):
    clock = _clock(monkeypatch)
    seen = []

    def urlopen(url, timeout=None, context=None):
        seen.append(timeout)
        clock['t'] += timeout                    # 요청마다 소켓 timeout 을 다 쓴다(최악)
        raise OSError('timeout')
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    out = cmd.naver_spot_yields(expected_date=RD, timeout=cmd.PATCH_PROBE_TIMEOUT_S, attempts=1,
                                budget_s=cmd.PATCH_PROBE_BUDGET_S)
    assert out == (None, None)
    assert set(seen) == {cmd.PATCH_PROBE_TIMEOUT_S}
    assert clock['t'] <= cmd.PATCH_PROBE_BUDGET_S + cmd.PATCH_PROBE_TIMEOUT_S == 90


def test_naver_probe_budget_is_enforced_between_requests(monkeypatch):
    clock = _clock(monkeypatch)
    calls = []

    def urlopen(url, timeout=None, context=None):
        calls.append(clock['t'])
        clock['t'] += 9.0
        return types.SimpleNamespace(read=lambda n=-1: b'')     # 빈 응답 → 그 만기는 행이 없다
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    assert cmd.naver_spot_yields(expected_date=RD, timeout=10, attempts=1, budget_s=20) == (None, None)
    assert calls == [0.0, 9.0, 18.0]             # 27초에는 시한을 넘겼으므로 넷째 요청이 없다


def test_naver_probe_cuts_off_a_response_that_drips_forever(monkeypatch):
    # 조각이 돌아오는 응답이면 조각 사이 시한이 끊는다. 읽기가 아예 돌아오지 않는 경우는 `_within`
    # (벽시계) 이 맡는다 — 아래 test_within_* 가 실제 시간으로 본다.
    clock = _clock(monkeypatch)

    def urlopen(url, timeout=None, context=None):
        def read(n=-1):
            assert n and n > 0, '시한을 보려면 조각으로 읽어야 한다'
            clock['t'] += 5.0
            return b' '
        return types.SimpleNamespace(read=read)
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    out = cmd.naver_spot_yields(expected_date=RD, timeout=cmd.PATCH_PROBE_TIMEOUT_S, attempts=1,
                                budget_s=cmd.PATCH_PROBE_BUDGET_S)
    assert out == (None, None)
    assert clock['t'] <= cmd.PATCH_PROBE_BUDGET_S + cmd.PATCH_PROBE_TIMEOUT_S


def test_naver_probe_reads_a_normal_chunked_response(monkeypatch):
    _clock(monkeypatch)
    day = lambda d, v: {'localTradedAt': f'{d}T17:05:00-05:00', 'closePrice': str(v)}
    days = ['2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-16', '2026-11-17', RD]
    body = json.dumps({'result': [day(d, 4.0 + i / 100) for i, d in enumerate(days)]}).encode()

    def urlopen(url, timeout=None, context=None):
        buf = [body[:40], body[40:], b'']
        return types.SimpleNamespace(read=lambda n=-1: buf.pop(0))
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    curve, latest = cmd.naver_spot_yields(pages=1, expected_date=RD, timeout=10, attempts=1, budget_s=80)
    assert latest == RD and curve['10Y']['level'] == 4.06 and curve['10Y']['bp'] == pytest.approx(1.0)


def test_naver_default_call_keeps_the_old_retries(monkeypatch):
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    seen = []

    def urlopen(url, timeout=None, context=None):
        seen.append(timeout)
        raise OSError('down')
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    assert cmd.naver_spot_yields(expected_date=RD) == (None, None)
    assert set(seen) == {25} and len(seen) == 12  # 만기 4 × 3회 (첫 쪽에서 끊긴다)


def test_within_cuts_a_call_that_never_returns_by_the_wall_clock():
    """가짜 시계가 아니라 실제 스레드·실제 시간으로 본다 — 읽기가 돌아오지 않아도 끊기는가."""
    import threading
    import time as real_time
    gate = threading.Event()
    t0 = real_time.monotonic()
    with pytest.raises(TimeoutError):
        cmd._within(0.2, lambda: gate.wait(30))      # 30초 동안 돌아오지 않는 읽기
    assert real_time.monotonic() - t0 < 2.0
    gate.set()


def test_within_returns_the_value_and_reraises_errors():
    assert cmd._within(5, lambda: (1, 2)) == (1, 2)
    with pytest.raises(ValueError):
        cmd._within(5, lambda: (_ for _ in ()).throw(ValueError('x')))


def test_probe_that_hangs_falls_through_to_the_full_path_within_the_wall_limit(outdir, monkeypatch):
    import threading
    import time as real_time
    gate = threading.Event()
    monkeypatch.setattr(cmd, 'PATCH_PROBE_WALL_S', 0.2)
    monkeypatch.setattr(cmd, 'naver_spot_yields', lambda **kw: gate.wait(30))
    before = snapshot(outdir)
    t0 = real_time.monotonic()
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert real_time.monotonic() - t0 < 2.0
    assert snapshot(outdir) == before
    gate.set()


def _naver_body(days):
    return json.dumps({'result': [{'localTradedAt': f'{d}T17:05:00-05:00', 'closePrice': str(4.0 + i / 100)}
                                  for i, d in enumerate(days)]}).encode()


def test_probe_asks_one_page_per_tenor_and_one_failed_tenor_means_no_curve(outdir, monkeypatch):
    """실제 `naver_spot_yields` 로 본다 — 반쪽 응답으로는 고치지 않는다."""
    days = ['2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-16', '2026-11-17', RD]
    urls = []

    def urlopen(url, timeout=None, context=None):
        urls.append(url)
        if 'US30YT' in url:
            raise OSError('reset')
        buf = [_naver_body(days), b'']
        return types.SimpleNamespace(read=lambda n=-1: buf.pop(0))
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    before = snapshot(outdir)
    assert cmd.yields_patch_step(args(outdir), now=NOW) is None
    assert snapshot(outdir) == before
    assert len(urls) == 4 and all('page=1&' in u for u in urls)


def test_probe_with_all_four_tenors_patches_through_the_real_parser(outdir, monkeypatch):
    days = ['2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-16', '2026-11-17', RD]

    def urlopen(url, timeout=None, context=None):
        buf = [_naver_body(days), b'']
        return types.SimpleNamespace(read=lambda n=-1: buf.pop(0))
    monkeypatch.setattr(cmd.urllib.request, 'urlopen', urlopen)
    assert cmd.yields_patch_step(args(outdir), now=NOW) == 'patched'
    md = json.loads((outdir / 'market_data.json').read_text())
    assert {(r['source'], r['date'], r['level']) for r in md['yields'].values()} == {('Naver', RD, 4.06)}


# ── 전체 경로가 남기는 표시 ─────────────────────────────────────────────────

def test_run_id_matches_the_ledger_format(monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', '42')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '3')
    assert cmd.run_id() == '42-3'
    import record_releases
    assert record_releases.run_id() == '42-3'


def test_full_path_stamps_the_edition():
    import inspect
    src = inspect.getsource(cmd.main)
    assert "'collection_started': collection_started" in src
    assert "'collection_run': run_id()" in src
    assert src.index('yields_patch_step(args)') < src.index('collect_daily()')
    assert src.index('collection_started = ') < src.index('collect_daily()')


def test_macro_eval_is_stamped_with_the_collection_run(tmp_path, monkeypatch):
    """평가 파일이 어느 수집 실행의 것인지 남는다 — `generated`(분 단위)보다 강한 표시."""
    import sys
    ev_mod = importlib.import_module('eval_macro_regime')
    (tmp_path / 'market_data.json').write_text(json.dumps({'report_date': RD, 'collection_run': RUN}))
    monkeypatch.setattr(sys, 'argv', ['eval_macro_regime.py', '--datadir', str(tmp_path)])
    ev_mod.main()
    ev = json.loads((tmp_path / 'macro_eval.json').read_text())
    assert ev['collection_run'] == RUN and ev['report_date'] == RD
