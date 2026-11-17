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
