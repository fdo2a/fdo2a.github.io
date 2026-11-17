"""1a 구현 검토 2회차(codex IMPL NO, 2026-11-17)의 지적을 재현하는 시험 — 검사 쪽.

F1 대상 목록 칸의 부재·잘못된 형식 ≠ 빈 배열 · F4 옛 종목 근거는 고유 종목·유한한 측정값 · F5 재검사 날짜 판정은
정규 파일 이름 하나로 · F6 항목 단위 기한부 승인 예외(기구만 — 실제 정책에는 등록하지 않는다). 수집 쪽(F2 장중 창의
완결성, F3 같은 날 재수집 실패)은 `scripts/kr/tests/test_session_window.py`·`scripts/common/tests/test_stamp_run.py`.
"""
import json
import os
import subprocess
import sys

import pytest

from verification import inputs as I
from verification import record as R
from verification.tests.test_inputs import STAMPED, ctx, put, policy, D

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
REAL = I.load(os.path.join(ROOT, 'config', 'prepub_inputs.json'))
GATES = json.load(open(os.path.join(ROOT, 'config', 'prepub_gates.json'), encoding='utf-8'))


def target_entries():
    """실제 정책의 대상 목록(target) 칸 전부 — (시장, 항목)."""
    out = []
    for market in REAL['markets']:
        files, _ = I.entries(REAL, market)
        out += [(market, e) for e in files if e['class'] == 'gate' and e.get('target')]
    return out


def _rel(e):
    return {'<tg>': 'tg.json'}.get(e['path'], e['path'].split('>/', 1)[-1])


def _assess(tmp_path, market, e, obj):
    pol = policy([e], market=market)
    p = put(tmp_path, _rel(e), obj)
    c = ctx(tmp_path, tg=p) if e['path'] == '<tg>' else ctx(tmp_path)
    key = e['path']
    return I.assess(pol, market, c)['files'][key]


def _body(e, **kw):
    d = {'report_date': D, 'ok': True}
    if e.get('status_ok'):
        d['status'] = e['status_ok'][0]
    d.update(kw)
    return d


# ── F1. 대상 목록 칸이 없거나 목록이 아니면 빈 배열이 아니다 ─────────────────────────────────

def test_f1_policy_has_the_target_files_we_think():
    names = sorted((m, e['path']) for m, e in target_entries())
    assert ('us', '<datadir>/auctions.json') in names and ('us', '<datadir>/fed/events.json') in names
    assert ('us', '<datadir>/releases/index.json') in names and ('us', '<datadir>/movers.json') in names
    assert ('kr', '<datadir>/kr_movers.json') in names and ('kr', '<datadir>/kr_index_etf.json') in names
    assert len(names) >= 10


@pytest.mark.parametrize('market,e', target_entries(), ids=lambda x: x if isinstance(x, str) else x['path'])
def test_f1_absent_or_non_list_target_blocks_before_effective(tmp_path, monkeypatch, market, e):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    t = e['target']
    if t == '<items>':
        bads = [{'report_date': D}, '"text"', '3', 'null']                # 최상위가 목록이 아니다
        empty = []
    else:
        bads = [_body(e), _body(e, **{t: None}), _body(e, **{t: {}}), _body(e, **{t: 'x'}), _body(e, **{t: 0})]
        empty = _body(e, **{t: []})
    for bad in bads:
        f = _assess(tmp_path, market, e, bad)
        assert f['state'] == 'incomplete_fields' and f['blocking'], (e['path'], bad, f['state'], f['reason'])
        assert f.get('unconfirmed_empty') is False, (e['path'], bad)   # 「빈 목록 미확인」 조건으로 내려가지 않는다
        assert '대상 목록' in f['reason']
    # 표시 없는 **빈 배열**만 잠정 허용(조건) — require 에 든 일정(calendar)은 전부터 막는다
    f = _assess(tmp_path, market, e, empty)
    if t in (e.get('require') or []):
        assert f['blocking']
    else:
        assert not f['blocking'] and f['unconfirmed_empty'] is True, (e['path'], f)


@pytest.mark.parametrize('market,e', target_entries(), ids=lambda x: x if isinstance(x, str) else x['path'])
def test_f1_absent_target_blocks_even_with_a_confirmed_none_stamp(tmp_path, monkeypatch, market, e):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    t = e['target']
    if t == '<items>':
        pytest.skip('목록형 파일의 표시는 장부에 있다 — 아래 시험')
    f = _assess(tmp_path, market, e, _body(e, collect=dict(STAMPED, empty='confirmed_none')))
    assert f['state'] == 'incomplete_fields' and f['blocking'], (e['path'], f['reason'])


def test_f1_auction_book_without_today_is_not_publishable(tmp_path, monkeypatch):
    # codex 재현: {"report_date": D, "ok": true} — today 부재가 「대상 없음 미확인」 조건으로 발행 가능했다
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    e = next(x for m, x in target_entries() if x['path'] == '<datadir>/auctions.json')
    pol = policy([e])
    put(tmp_path, 'auctions.json', {'report_date': D, 'ok': True})
    h = I.assess(pol, 'us', ctx(tmp_path))
    s = R.summarize([], health=h)
    assert not s['publish_ok'] and s['status'] == 'incomplete'
    assert I.unconfirmed_empty(h) == []


# 둘째 겹 — 검사기를 직접 돌린다(실행기는 입력이 막히면 검사기를 돌리지 않는다)

def _run(script, tmp_path, *args, html='<html><body><main><h2>주식</h2><p>본문</p></main></body></html>'):
    h = tmp_path / f'{D}.html'
    h.write_text(html, encoding='utf-8')
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), '--html', str(h), *args],
                          capture_output=True, text=True, cwd=ROOT)


AUCTION = {'report_date': D, 'ok': True, 'error': None, 'pending': [], 'today': [], 'recent': [], 'next': []}


@pytest.mark.parametrize('bad', [{k: v for k, v in AUCTION.items() if k != 'today'}, dict(AUCTION, today=None),
                                 dict(AUCTION, today={}), dict(AUCTION, today='x'), ['list'], '"text"'])
def test_f1_check_auction_exits_2_on_absent_or_non_list_today(tmp_path, bad):
    d = tmp_path / 'data'
    put(d, 'market_data.json', {'report_date': D})
    put(d, 'auctions.json', bad)
    r = _run('check_auction.py', tmp_path, '--datadir', str(d))
    assert r.returncode == 2 and '미완료' in r.stderr, (bad, r.returncode, r.stdout, r.stderr)
    put(d, 'auctions.json', AUCTION)
    assert _run('check_auction.py', tmp_path, '--datadir', str(d)).returncode == 0


def test_f1_auction_gate_check_does_not_read_a_missing_today_as_empty():
    from us import auction_gate
    with pytest.raises(auction_gate.BadBook):
        auction_gate.check('<html></html>', {'report_date': D, 'ok': True}, D)


@pytest.mark.parametrize('bad', [{'report_date': D}, {'report_date': D, 'events': None},
                                 {'report_date': D, 'events': {}}, {'report_date': D, 'events': 'x'}, ['x']])
def test_f1_check_fed_exits_2_on_absent_or_non_list_events(tmp_path, bad):
    d = tmp_path / 'data'
    put(d, 'market_data.json', {'report_date': D})
    put(d, 'intraday.json', {})
    put(d, 'econ_indicators.json', {})
    put(d, 'fed/events.json', bad)
    r = _run('check_fed.py', tmp_path, '--datadir', str(d))
    assert r.returncode == 2, (bad, r.returncode, r.stdout, r.stderr)
    put(d, 'fed/events.json', {'report_date': D, 'events': []})
    assert _run('check_fed.py', tmp_path, '--datadir', str(d)).returncode == 0


@pytest.mark.parametrize('bad', [{'report_date': D}, {'report_date': D, 'groups': None},
                                 {'report_date': D, 'groups': {}}, ['x']])
def test_f1_check_movers_exits_2_on_absent_or_non_list_groups(tmp_path, bad):
    d = tmp_path / 'data'
    put(d, 'market_data.json', {'report_date': D})
    put(d, 'movers.json', bad)
    assert _run('check_movers.py', tmp_path, '--datadir', str(d)).returncode == 2


# ── F4. 옛 종목 근거 — 고유 종목·유한한 측정값만 센다 ─────────────────────────────────────────

KR_MOVERS = {'path': '<datadir>/kr_movers.json', 'class': 'gate', 'name': 'KR 움직인 종목', 'date': 'report_date',
             'target': 'groups'}
KR_MOVES = {'path': '<datadir>/kr_stock_moves.json', 'class': 'writer', 'name': 'KR 개별주 등락', 'risk': 'x',
            'covered_by': None}


def kr_na():
    return next(g for g in GATES['markets']['kr']['gates'] if g['name'] == 'check_movers')['na_when']


def _legacy_na(tmp_path, rows, spec=None):
    pol = policy([KR_MOVERS, KR_MOVES], market='kr')
    put(tmp_path, 'kr_movers.json', {'report_date': D, 'groups': []})
    put(tmp_path, 'kr_stock_moves.json', rows if isinstance(rows, str) else json.dumps(rows))
    return I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), spec or kr_na())


def test_f4_legacy_evidence_counts_unique_measured_stocks_only(tmp_path, monkeypatch):
    from common import movers as M
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    n = M.LEGACY_MIN_ITEMS
    good = [{'name': f's{i}', 'change_pct': 0.1 * i, 'date': D} for i in range(n)]
    assert _legacy_na(tmp_path, good) == (True, 'legacy')
    # codex 재현: 그날 날짜만 든 같은 객체 n 개 — 전에는 (True, 'legacy')
    assert _legacy_na(tmp_path, [{'date': D}] * n) == (False, None)
    assert _legacy_na(tmp_path, [{'name': 's0', 'change_pct': 1.0, 'date': D}] * n) == (False, None)   # 같은 종목
    assert _legacy_na(tmp_path, good[:-1] + [dict(good[0])]) == (False, None)            # 고유 종목이 하나 모자라다
    assert _legacy_na(tmp_path, good + [dict(good[0])]) == (True, 'legacy')              # 중복은 한 번만 센다
    for badv in (None, 'x', True, '1.0'):
        assert _legacy_na(tmp_path, good[:-1] + [dict(good[-1], change_pct=badv)]) == (False, None), badv
    assert _legacy_na(tmp_path, good[:-1] + [{'change_pct': 1.0, 'date': D}]) == (False, None)        # 이름 없음
    assert _legacy_na(tmp_path, good[:-1] + [dict(good[-1], name='')]) == (False, None)
    # NaN·무한대 — json 은 읽지만 측정값이 아니다
    raw = json.dumps(good[:-1])[:-1] + ', {"name": "nan", "change_pct": NaN, "date": "%s"}]' % D
    assert _legacy_na(tmp_path, raw) == (False, None)
    raw = json.dumps(good[:-1])[:-1] + ', {"name": "inf", "change_pct": Infinity, "date": "%s"}]' % D
    assert _legacy_na(tmp_path, raw) == (False, None)


def test_f4_legacy_evidence_spec_must_name_the_id_and_value_fields(tmp_path, monkeypatch):
    from common import movers as M
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    ev = kr_na()['legacy_evidence']
    assert ev['id_field'] == 'name' and ev['value_field'] == 'change_pct'      # kr.etf_normalize.krx_changes 의 행
    good = [{'name': f's{i}', 'change_pct': 0.1, 'date': D} for i in range(M.LEGACY_MIN_ITEMS)]
    for drop in ('id_field', 'value_field'):
        spec = dict(kr_na(), legacy_evidence={k: v for k, v in ev.items() if k != drop})
        assert _legacy_na(tmp_path, good, spec) == (False, None), drop


def test_f4_krx_changes_rows_carry_the_fields_the_policy_names():
    from kr import etf_normalize as E
    rows = E.krx_changes([{'name': '삼성전자', 'code': '005930', 'value': 1}],
                         {'005930': [('2026-11-13', 100.0), (D, 101.0)]}, D)
    ev = kr_na()['legacy_evidence']
    assert rows and all(ev['id_field'] in r and ev['value_field'] in r for r in rows)


# ── F3. 같은 날 재수집 실패 — 장부의 run: failed 는 파일 안의 「성공」보다 앞선다 ─────────────────────

KR_SESSION = {'path': '<datadir>/kr_session.json', 'class': 'gate', 'name': 'KR 장중 세션', 'date': 'report_date'}
META = {'path': '<datadir>/_collect_status.json', 'class': 'gate', 'name': '수집 상태 기록', 'optional': True,
        'required_when_enforced': True, 'produced_by': 'meta'}


def _sha(p):
    import hashlib
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def _session_day(tmp_path, entry):
    pol = policy([META, KR_SESSION], market='kr')
    p = put(tmp_path, 'kr_session.json', {'report_date': D, 'collect': STAMPED})
    put(tmp_path, '_collect_status.json', {'files': {'kr_session.json': entry(p)}})
    return I.assess(pol, 'kr', ctx(tmp_path))


def _failed(p):
    return {'present': True, 'collect_in': 'file', 'status': 'failed', 'run': 'failed',
            'response': '이번 수집 실행에서 다시 쓰이지 않았다 — RuntimeError: yfinance timeout',
            'stale_copy': dict(STAMPED, sha256=_sha(p), bytes=1, collect_in='file')}


def test_f3_rerun_failure_blocks_from_effective_even_if_the_old_copy_says_ok(tmp_path, monkeypatch):
    rel = '<datadir>/kr_session.json'
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    f = _session_day(tmp_path, _failed)['files'][rel]
    assert f['state'] == 'failed' and f['blocking']                         # 재현: 전에는 장부를 보지 않고 ok
    assert '옛 판 있음' in f['reason'] and 'yfinance timeout' in f['reason']
    # 정상 재실행 — 새 해시·run written
    f = _session_day(tmp_path, lambda p: {'sha256': _sha(p), 'bytes': 1, 'run': 'written'})['files'][rel]
    assert f['state'] == 'ok' and not f['blocking']
    for ok in I.RUN_OK:
        assert _session_day(tmp_path, lambda p: {'sha256': _sha(p), 'run': ok})['files'][rel]['state'] == 'ok'


def test_f3_before_effective_it_is_a_visible_condition_not_hidden(tmp_path, monkeypatch):
    rel = '<datadir>/kr_session.json'
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    h = _session_day(tmp_path, _failed)
    f = h['files'][rel]
    assert f['state'] == 'ok' and not f['blocking'] and '옛 판 있음' in f['recollect_failed']
    assert I.recollect_failed(h) == [rel]
    s = R.summarize([], health=h)
    assert s['publish_ok'] and s['status'] == 'conditional'
    assert {'kind': 'recollect_failed', 'file': rel} in s['conditions']
    assert s['inputs']['recollect_failed'] == [I.describe_recollect(f)]


def test_f3_ledger_must_say_how_the_file_got_there_from_effective(tmp_path, monkeypatch):
    rel = '<datadir>/kr_session.json'
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    for run in (None, 'unknown', 'untracked', 'nonsense'):
        e = {'sha256': None, 'bytes': 1}
        f = _session_day(tmp_path, lambda p: dict(e, sha256=_sha(p), **({'run': run} if run else {})))['files'][rel]
        assert f['state'] == 'unstamped' and f['blocking'] and 'run=' in f['reason'], run


def test_f3_run_ok_states_match_the_stamper():
    sys.path.insert(0, SCRIPTS)
    import stamp_collect as SC
    assert I.RUN_OK == SC.RUN_OK


def test_f3_failed_sidecar_list_file(tmp_path, monkeypatch):
    # 목록형 파일(표시가 장부에 있다) — 옛 판의 표시는 stale_copy 에서 읽고, 적용일부터는 막는다
    e = next(x for m, x in target_entries() if x['path'] == '<datadir>/kr_index_etf.json')
    pol = policy([META, e], market='kr')
    p = put(tmp_path, 'kr_index_etf.json', [{'name': 'KODEX 200'}])
    put(tmp_path, '_collect_status.json', {'files': {'kr_index_etf.json': {
        'present': True, 'collect_in': 'sidecar', 'status': 'failed', 'run': 'failed', 'response': 'x',
        'stale_copy': dict(STAMPED, sha256=_sha(p), collect_in='sidecar')}}})
    rel = '<datadir>/kr_index_etf.json'
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    h = I.assess(pol, 'kr', ctx(tmp_path))
    assert not h['files'][rel]['blocking'] and I.recollect_failed(h) == [rel]
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    f = I.assess(pol, 'kr', ctx(tmp_path))['files'][rel]
    assert f['state'] == 'failed' and f['blocking']


def test_f3_end_to_end_stamper_to_gate(tmp_path, monkeypatch):
    """수집기 → stamp → 검사: 둘째 실행의 세션 실패가 적용일부터 발행을 막고, 정상 재실행은 통과한다."""
    import datetime as dt
    sys.path.insert(0, SCRIPTS)
    import stamp_collect as SC
    from common import collect_status as C
    kst = dt.timezone(dt.timedelta(hours=9))
    t0, t1 = dt.datetime(2026, 11, 16, 17, 0, tzinfo=kst), dt.datetime(2026, 11, 16, 17, 30, tzinfo=kst)
    pol = policy([META, KR_SESSION, {'path': '<datadir>/kr_market_data.json', 'class': 'gate', 'name': 'KR 시장',
                                     'date': 'report_date'}], market='kr')

    def write(name, at):
        put(tmp_path, name, {'report_date': D, 'collect': C.build('ok', D, 'x', empty='has_data',
                                                                 collected_at=C.now_iso(at))})
    steps = {'collect': {'outcome': 'success'}}
    SC.begin(str(tmp_path), now=t0)
    write('kr_market_data.json', t0)
    write('kr_session.json', t0)
    SC.stamp(str(tmp_path), market='kr', steps=steps)
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    assert not I.blocking(I.assess(pol, 'kr', ctx(tmp_path)))['any']
    SC.begin(str(tmp_path), now=t1)                                        # 둘째 실행 — 세션만 실패
    write('kr_market_data.json', t1)
    C.note_run_failure(str(tmp_path), 'kr_session.json', 'RuntimeError: boom')
    SC.stamp(str(tmp_path), market='kr', steps=steps)
    b = I.blocking(I.assess(pol, 'kr', ctx(tmp_path)))
    assert b['files'] == ['<datadir>/kr_session.json']
    t2 = t1 + dt.timedelta(minutes=30)
    SC.begin(str(tmp_path), now=t2)                                        # 셋째 실행 — 둘 다 성공
    write('kr_market_data.json', t2)
    write('kr_session.json', t2)
    SC.stamp(str(tmp_path), market='kr', steps=steps)
    assert not I.blocking(I.assess(pol, 'kr', ctx(tmp_path)))['any']


# ── F6. 항목 단위 기한부 승인 예외(accepted_missing) — 기구만, 실제 정책에는 등록하지 않는다 ─────────────

ECON = {'path': '<datadir>/econ_indicators.json', 'class': 'gate', 'name': '경제 지표', 'require': ['indicators']}
MM = {'path': '<datadir>/macro_metrics.json', 'class': 'gate', 'name': '매크로 지표', 'date': 'report_date',
      'require': ['indicators']}
K1, K2, REF = 'no_value:CPI YoY', 'no_value:Core CPI YoY', '2026-10-01'


def acc(key, expires='2026-12-10', ref=REF, **kw):
    d = {'key': key, 'ref_period': ref, 'reason': 'FRED CPIAUCSL 2025-10 값이 원천에 비어 있다',
         'approved_by': 'user', 'approved_on': '2026-11-10', 'expires': expires}
    d.update(kw)
    return d


def partial(missing, refs=None, **kw):
    c = dict(STAMPED, status='partial', required_ok=False, missing=list(missing),
             missing_ref=refs if refs is not None else {m: REF for m in missing})
    c.update(kw)
    return c


def _econ(tmp_path, collect, accepted, date=D):
    pol = policy([dict(ECON, accepted_missing=accepted)])
    put(tmp_path, 'econ_indicators.json', {'indicators': [{'name': 'x'}], 'collect': dict(collect, as_of=date)})
    h = I.assess(pol, 'us', ctx(tmp_path, date=date))
    return h, h['files']['<datadir>/econ_indicators.json']


def test_f6_registered_keys_make_the_file_conditional_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    _, f = _econ(tmp_path, partial([K1, K2]), [])
    assert f['state'] == 'failed' and f['blocking']                          # 등록이 없으면 막힌다(지금 상태)
    h, f = _econ(tmp_path, partial([K1, K2]), [acc(K1), acc(K2)])
    assert f['state'] == 'ok' and not f['blocking']
    assert [a['key'] for a in f['accepted_missing']] == [K1, K2]
    assert f['accepted_missing'][0]['approved_by'] == 'user' and f['accepted_missing'][0]['expires'] == '2026-12-10'
    s = R.summarize([], health=h)
    assert s['publish_ok'] and s['status'] == 'conditional' and not s['verified']
    cond = [c for c in s['conditions'] if c['kind'] == 'accepted_missing']
    assert cond == [{'kind': 'accepted_missing', 'file': '<datadir>/econ_indicators.json', 'keys': [K1, K2],
                     'approved_by': 'user', 'expires': '2026-12-10'}]
    assert s['inputs']['accepted_missing'] == [I.describe_accepted(f)]
    assert '승인된 결측 2건(만료 2026-12-10)' in s['inputs']['accepted_missing'][0]


def test_f6_any_other_miss_or_failure_or_wrong_period_still_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    both = [acc(K1), acc(K2)]
    cases = {
        '다른 결측이 섞였다': partial([K1, K2, 'JOLTS Job Openings'], refs={K1: REF, K2: REF}),
        '등록 안 된 no_value': partial([K1, 'no_value:PCE Price Index YoY']),
        '수집 실패': partial([K1, K2], status='failed', empty='unknown'),
        '다른 기준월': partial([K1, K2], refs={K1: '2026-11-01', K2: '2026-11-01'}),
        '한 키만 기준월이 다르다': partial([K1, K2], refs={K1: REF, K2: '2026-11-01'}),
        '자료가 기준월을 말하지 않는다': partial([K1, K2], refs={}),
        'missing_ref 칸이 없다': {k: v for k, v in partial([K1, K2]).items() if k != 'missing_ref'},
        '대상을 모른다': partial([K1, K2], empty='unknown'),
    }
    for name, c in cases.items():
        _, f = _econ(tmp_path, c, both)
        assert f['blocking'] and 'accepted_missing' not in f, name
    _, f = _econ(tmp_path, partial([K1, K2]), [acc(K1)])                      # 한 키만 등록
    assert f['blocking']
    # 낡은 자료(as_of ≠ 발행일)는 예외와 무관하게 막힌다
    pol = policy([dict(ECON, accepted_missing=both)])
    put(tmp_path, 'econ_indicators.json', {'indicators': [{'name': 'x'}],
                                           'collect': dict(partial([K1, K2]), as_of='2026-11-13')})
    f = I.assess(pol, 'us', ctx(tmp_path))['files']['<datadir>/econ_indicators.json']
    assert f['state'] == 'stale' and f['blocking']


def test_f6_expiry_is_judged_by_the_post_date_and_blocks_again_after(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    both = [acc(K1, expires='2026-12-10'), acc(K2, expires='2026-12-10')]
    assert not _econ(tmp_path, partial([K1, K2]), both, date='2026-12-10')[1]['blocking']      # 만료일 당일까지
    assert _econ(tmp_path, partial([K1, K2]), both, date='2026-12-11')[1]['blocking']          # 다음 날부터 다시 막힌다
    mixed = [acc(K1, expires='2026-12-10'), acc(K2, expires='2026-11-20')]
    assert _econ(tmp_path, partial([K1, K2]), mixed, date='2026-11-21')[1]['blocking']
    # 승인일은 기록용 — 보류된 글을 다음 날 승인해도(글 날짜 < 승인일) 그 글이 풀린다. 범위는 기준월·만료일이 정한다
    assert not _econ(tmp_path, partial([K1, K2]), both, date='2026-11-09')[1]['blocking']


def test_f6_original_collect_is_not_rewritten(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    before = partial([K1, K2])
    h, f = _econ(tmp_path, before, [acc(K1), acc(K2)])
    on_disk = json.load(open(os.path.join(str(tmp_path), 'econ_indicators.json'), encoding='utf-8'))['collect']
    assert on_disk['status'] == 'partial' and on_disk['required_ok'] is False and on_disk['missing'] == [K1, K2]
    assert h['_objs']['<datadir>/econ_indicators.json']['collect']['status'] == 'partial'


@pytest.mark.parametrize('bad', [
    acc(K1, approved_by='routine'), acc(K1, approved_by=None), {k: v for k, v in acc(K1).items() if k != 'expires'},
    acc(K1, expires='soon'), acc(K1, expires='2026-13-40'), acc(K1, ref=None), acc(K1, reason=''), acc('', ),
    acc(K1, approved_on='어제'), 'no_value:CPI YoY', {k: v for k, v in acc(K1).items() if k != 'approved_by'}])
def test_f6_config_errors(bad):
    with pytest.raises(I.PolicyError):
        policy([dict(ECON, accepted_missing=[bad])])


def test_f6_only_gate_files_and_only_a_list():
    with pytest.raises(I.PolicyError):
        policy([dict(ECON, accepted_missing=acc(K1))])
    w = {'path': '<datadir>/x.md', 'class': 'writer', 'name': 'x', 'risk': 'r', 'covered_by': None,
         'accepted_missing': [acc(K1)]}
    with pytest.raises(I.PolicyError):
        policy([w])


def test_f6_macro_metrics_follows_the_same_registration(tmp_path, monkeypatch):
    """macro_metrics 는 econ_indicators 의 결측을 `econ:<키>` 로 다시 싣는다 — 같은 키·기준월로 등록해야 풀린다."""
    sys.path.insert(0, SCRIPTS)
    import collect_market_data as cmd
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    econ = cmd.econ_collect([{'name': 'x'}], {'CPI YoY': 'no_value', 'Core CPI YoY': 'no_value'}, D,
                            refs={'CPI YoY': REF, 'Core CPI YoY': REF})
    assert econ['status'] == 'partial' and econ['missing'] == [K1, K2] and econ['missing_ref'] == {K1: REF, K2: REF}
    mm = cmd.macro_metrics_collect({'book_state': 'ok'}, econ, D)
    assert mm['status'] == 'partial' and mm['missing'] == [f'econ:{K1}', f'econ:{K2}']
    assert mm['missing_ref'] == {f'econ:{K1}': REF, f'econ:{K2}': REF}
    pol = policy([dict(ECON, accepted_missing=[acc(K1), acc(K2)]),
                  dict(MM, accepted_missing=[acc(f'econ:{K1}'), acc(f'econ:{K2}')])])
    put(tmp_path, 'econ_indicators.json', {'indicators': [{'name': 'x'}], 'collect': econ})
    put(tmp_path, 'macro_metrics.json', {'report_date': D, 'indicators': [{'name': 'x'}], 'collect': mm})
    h = I.assess(pol, 'us', ctx(tmp_path))
    assert not I.blocking(h)['any']
    assert sorted(c['file'] for c in R.summarize([], health=h)['conditions'] if c['kind'] == 'accepted_missing') == [
        '<datadir>/econ_indicators.json', '<datadir>/macro_metrics.json']
    # econ 쪽에 다른 결측이 섞이면 macro_metrics 도 풀리지 않는다
    econ2 = cmd.econ_collect([{'name': 'x'}], {'CPI YoY': 'no_value', 'Core CPI YoY': 'no_value',
                                               'JOLTS Job Openings': 'fetch_failed'}, D,
                             refs={'CPI YoY': REF, 'Core CPI YoY': REF})
    mm2 = cmd.macro_metrics_collect({'book_state': 'ok'}, econ2, D)
    put(tmp_path, 'econ_indicators.json', {'indicators': [{'name': 'x'}], 'collect': econ2})
    put(tmp_path, 'macro_metrics.json', {'report_date': D, 'indicators': [{'name': 'x'}], 'collect': mm2})
    assert sorted(I.blocking(I.assess(pol, 'us', ctx(tmp_path)))['files']) == [
        '<datadir>/econ_indicators.json', '<datadir>/macro_metrics.json']
    # 어제 책이 깨진 것(macro.json:corrupt)은 등록과 무관하게 막는다
    mm3 = cmd.macro_metrics_collect({'book_state': 'corrupt'}, econ, D)
    put(tmp_path, 'econ_indicators.json', {'indicators': [{'name': 'x'}], 'collect': econ})
    put(tmp_path, 'macro_metrics.json', {'report_date': D, 'indicators': [{'name': 'x'}], 'collect': mm3})
    assert I.blocking(I.assess(pol, 'us', ctx(tmp_path)))['files'] == ['<datadir>/macro_metrics.json']
    # econ 이 통째로 실패하면 키 없이 `econ_indicators` 하나 — 등록할 수 없다
    mm4 = cmd.macro_metrics_collect({'book_state': 'ok'}, {'status': 'failed', 'missing': []}, D)
    assert mm4['missing'] == ['econ_indicators']


def test_f6_real_policy_registers_nothing():
    """사용자 답 전 — 실제 정책에는 승인 예외가 없다(기구만 있다)."""
    for market in REAL['markets']:
        files, _ = I.entries(REAL, market)
        assert not [e['path'] for e in files if e.get('accepted_missing')], market
    raw = open(os.path.join(ROOT, 'config', 'prepub_inputs.json'), encoding='utf-8').read()
    assert 'accepted_missing' not in raw
    assert I.EFFECTIVE is None
