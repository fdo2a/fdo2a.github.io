"""1a 구현 검토 1회차(codex IMPL NO, 2026-11-17)의 지적을 재현하는 시험 — 검사 쪽.

지적 번호는 검토 원문의 번호다. 수집 쪽 지적(3·4·5)은 `scripts/kr/tests/test_collect_freshness.py`·
`scripts/us/tests/test_econ_collect_required.py`, 발행 뒤 재검사(9 의 정정기·윤문기)와 알림(11)은
`scripts/review/tests/test_impl_review_r1_review.py` 에 있다.
"""
import fnmatch
import hashlib
import inspect
import json
import math
import os
import subprocess
import sys

import pytest

from verification import inputs as I
from verification import record as R
from verification.tests.test_inputs import STAMPED, ctx, put, st, policy, D

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
REAL = I.load(os.path.join(ROOT, 'config', 'prepub_inputs.json'))
GATES = json.load(open(os.path.join(ROOT, 'config', 'prepub_gates.json'), encoding='utf-8'))
META = {'path': '<datadir>/_collect_status.json', 'class': 'gate', 'name': '수집 상태 기록', 'optional': True,
        'required_when_enforced': True, 'produced_by': 'meta'}


def real_entry(market, path):
    files, _ = I.entries(REAL, market)
    return next(e for e in files if e['path'] == path)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


# ── 1. KR 옛 방식 「해당 없음」 — 한 종목만 재도 정상 조회로 인정했다 ─────────────────────────

KR_MOVERS = {'path': '<datadir>/kr_movers.json', 'class': 'gate', 'name': 'KR 움직인 종목', 'date': 'report_date',
             'target': 'groups'}
KR_MOVES = {'path': '<datadir>/kr_stock_moves.json', 'class': 'writer', 'name': 'KR 개별주 등락', 'risk': 'x',
            'covered_by': None}


def kr_na():
    return next(g for g in GATES['markets']['kr']['gates'] if g['name'] == 'check_movers')['na_when']


def test_1_one_measured_stock_is_not_legacy_na(tmp_path):
    from common import movers as M
    pol = policy([KR_MOVERS, KR_MOVES], market='kr')
    put(tmp_path, 'kr_movers.json', {'report_date': D, 'groups': []})
    put(tmp_path, 'kr_stock_moves.json', [{'name': '한 종목', 'change_pct': 1.0}])
    assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), kr_na()) == (False, None)       # 재현: 전에는 (True, legacy)
    # 모집단의 90% 를 쟀어도 자료에 그날 날짜가 없으면 입증할 수 없다(지금 kr_stock_moves.json 의 모양)
    rows = [{'name': f's{i}', 'change_pct': 0.1} for i in range(M.LEGACY_MIN_ITEMS)]
    put(tmp_path, 'kr_stock_moves.json', rows)
    assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), kr_na()) == (False, None)
    put(tmp_path, 'kr_stock_moves.json', [dict(r, date=D) for r in rows])
    assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), kr_na()) == (True, 'legacy')
    put(tmp_path, 'kr_stock_moves.json', [dict(r, date=D) for r in rows[:-1]])           # 한 종목 모자라다
    assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), kr_na()) == (False, None)
    put(tmp_path, 'kr_stock_moves.json', [dict(r, date=D) for r in rows[1:]] + [dict(rows[0], date='2026-11-13')])
    assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), kr_na()) == (False, None)       # 다른 날 행이 섞였다


def test_1_collect_na_needs_the_same_coverage(tmp_path):
    from common import movers as M
    pol = policy([KR_MOVERS, KR_MOVES], market='kr')
    ok = dict(STAMPED, empty='confirmed_none', checked=58, expected=58)
    need = math.ceil(M.MIN_COVERAGE * 58)
    for c, want in ((ok, True), (dict(ok, checked=need), True), (dict(ok, checked=need - 1), False),
                    (dict(ok, checked=1), False), ({k: v for k, v in ok.items() if k != 'expected'}, False),
                    (dict(ok, expected=0), False)):
        put(tmp_path, 'kr_movers.json', {'report_date': D, 'groups': [], 'collect': c})
        assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), kr_na())[0] is want, c


def test_1_thresholds_come_from_common_movers():
    """수치를 정책에 다시 적지 않는다 — 수집 쪽 기준(모집단 × MIN_COVERAGE)을 한 곳에서 읽는다."""
    from common import movers as M
    from kr import etf_normalize
    from us import movers_data
    assert M.LEGACY_MIN_ITEMS == math.ceil(M.MIN_COVERAGE * M.UNIVERSE_TOP_N)
    assert inspect.signature(etf_normalize.stock_moves).parameters['top_n'].default == M.UNIVERSE_TOP_N
    assert movers_data.TOP_N == M.UNIVERSE_TOP_N
    for market in ('us', 'kr'):
        na = next(g for g in GATES['markets'][market]['gates'] if g['name'] == 'check_movers')['na_when']
        assert na['min_coverage'] == {'module': 'common.movers', 'attr': 'MIN_COVERAGE'}, market
    ev = kr_na()['legacy_evidence']
    assert ev['min_items'] == {'module': 'common.movers', 'attr': 'LEGACY_MIN_ITEMS'} and ev['date_field'] == 'date'


def test_1_unresolvable_threshold_is_not_na(tmp_path):
    pol = policy([KR_MOVERS, KR_MOVES], market='kr')
    put(tmp_path, 'kr_movers.json', {'report_date': D, 'groups': [],
                                     'collect': dict(STAMPED, empty='confirmed_none', checked=58, expected=58)})
    bad = dict(kr_na(), min_coverage={'module': 'common.nope', 'attr': 'X'})
    assert I.na_when(I.assess(pol, 'kr', ctx(tmp_path)), bad) == (False, None)


# ── 2. 적용일 전, 정상 조회 확인 없는 빈 대상 목록 ────────────────────────────────────────────

def test_2_empty_target_without_stamp_is_flagged_not_hidden(tmp_path):
    ev = real_entry('us', '<datadir>/fed/events.json')
    pol = policy([ev])
    rel = '<datadir>/fed/events.json'
    put(tmp_path, 'fed/events.json', {'report_date': D, 'events': []})
    r = I.assess(pol, 'us', ctx(tmp_path))
    f = r['files'][rel]
    assert f['state'] == 'unstamped' and not f['blocking'] and f['unconfirmed_empty'] is True
    assert I.unconfirmed_empty(r) == [rel]
    s = R.summarize([], health=r)
    assert s['publish_ok'] and s['status'] == 'conditional'
    assert {'kind': 'unconfirmed_empty', 'file': rel} in s['conditions']
    assert s['inputs']['unconfirmed_empty'] == [I.describe_empty(f)]
    # 대상이 「fresh 사건」이면 fresh 가 아닌 것만 있어도 빈 대상이다
    put(tmp_path, 'fed/events.json', {'report_date': D, 'events': [{'key': 'old', 'fresh': False}]})
    assert I.assess(pol, 'us', ctx(tmp_path))['files'][rel]['unconfirmed_empty'] is True
    put(tmp_path, 'fed/events.json', {'report_date': D, 'events': [{'key': 'new', 'fresh': True}]})
    assert I.assess(pol, 'us', ctx(tmp_path))['files'][rel]['unconfirmed_empty'] is False
    put(tmp_path, 'fed/events.json', {'report_date': D, 'events': [],
                                      'collect': dict(STAMPED, empty='confirmed_none')})
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert r['files'][rel]['state'] == 'ok' and r['files'][rel]['unconfirmed_empty'] is False
    assert I.unconfirmed_empty(r) == []


def test_2_list_file_and_effective(tmp_path, monkeypatch):
    etf = real_entry('kr', '<datadir>/kr_index_etf.json')
    pol = policy([etf], market='kr')
    rel = '<datadir>/kr_index_etf.json'
    put(tmp_path, 'kr_index_etf.json', [])
    assert I.assess(pol, 'kr', ctx(tmp_path))['files'][rel]['unconfirmed_empty'] is True
    monkeypatch.setattr(I, 'EFFECTIVE', D)              # 적용일부터는 표시 없음 자체가 막는다
    f = I.assess(pol, 'kr', ctx(tmp_path))['files'][rel]
    assert f['state'] == 'unstamped' and f['blocking']


def test_2_every_target_entry_is_covered():
    """정책에서 대상 목록(target)을 가진 gate 항목 전부가 이 표시를 받는다 — 빠진 항목이 없게."""
    for market in ('us', 'kr'):
        files, _ = I.entries(REAL, market)
        for e in files:
            if e['class'] == 'gate' and e.get('target'):
                assert e.get('produced_by', 'collector') == 'collector', e['path']


# ── 6. 적용일 뒤 수집 상태 기록에 항목·해시가 없어도 통과했다 ──────────────────────────────────

def test_6_ledger_entry_and_hash_required_from_effective(tmp_path, monkeypatch):
    md = real_entry('us', '<datadir>/market_data.json')
    pol = policy([META, md])
    rel = '<datadir>/market_data.json'
    p = put(tmp_path, 'market_data.json', {'report_date': D, 'indices': {'x': 1}, 'sectors': {'a': 1},
                                           'yields': {'a': 1}, 'fx': {'a': 1}, 'commodities': {'a': 1},
                                           'complete': True, 'missing': [], 'collect': STAMPED})
    put(tmp_path, '_collect_status.json', {'files': {}})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'                    # 적용일 전 — 그대로
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    f = I.assess(pol, 'us', ctx(tmp_path))['files'][rel]
    assert f['state'] == 'unstamped' and f['blocking'] and '해시' in f['reason']   # 재현: 전에는 ok
    put(tmp_path, '_collect_status.json', {'files': {'market_data.json': {'sha256': 'abc', 'bytes': 1}}})
    f = I.assess(pol, 'us', ctx(tmp_path))['files'][rel]
    assert f['blocking'] and '해시' in f['reason']
    put(tmp_path, '_collect_status.json', {'files': {'market_data.json': {'sha256': sha(p), 'bytes': 1}}})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'


def test_6_non_collector_files_need_no_entry(tmp_path, monkeypatch):
    nxt = real_entry('us', '<datadir>/macro_next.json')
    book = dict(real_entry('us', '<datadir>/macro.json'), date_rule=None)
    book.pop('date_ref')
    pol = policy([META, nxt, book])
    put(tmp_path, 'macro_next.json', {'report_date': D})
    put(tmp_path, 'macro.json', {'report_date': D})
    put(tmp_path, '_collect_status.json', {'files': {}})
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert st(r, '<datadir>/macro_next.json') == 'ok' and st(r, '<datadir>/macro.json') == 'ok'


def test_6_rewritten_file_needs_the_entry_but_not_the_hash(tmp_path, monkeypatch):
    liq = real_entry('us', '<datadir>/liquidity/liquidity.json')
    pol = policy([META, liq])
    rel = '<datadir>/liquidity/liquidity.json'
    put(tmp_path, 'liquidity/liquidity.json', {'report_date': D, 'status': 'complete', 'collect': STAMPED})
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    put(tmp_path, '_collect_status.json', {'files': {}})
    assert I.assess(pol, 'us', ctx(tmp_path))['files'][rel]['blocking']
    put(tmp_path, '_collect_status.json', {'files': {'liquidity/liquidity.json': {'sha256': '0' * 64}}})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'


def test_6_every_collector_gate_file_is_in_the_stamp_registry():
    """적용일부터 항목을 요구하므로, 정책의 수집기 산출 gate 파일은 모두 stamp_collect 등록표에 있어야 한다."""
    sys.path.insert(0, SCRIPTS)
    import stamp_collect as SC
    for market in ('us', 'kr'):
        files, _ = I.entries(REAL, market)
        reg = [p.replace('{D}', '2026-11-16') for p in SC.REGISTRY[market]]
        for e in files:
            if e['class'] != 'gate' or e.get('produced_by', 'collector') not in I.LEDGER_PRODUCERS:
                continue
            skey = (e.get('stamp_key') or e['path'].split('>/', 1)[-1]).replace('{date}', '2026-11-16')
            assert any(fnmatch.fnmatchcase(skey, p) or skey == p for p in reg), (market, e['path'], skey)


# ── 7·8. 정상적인 0건 일정, 성적표의 생산자 계약 ─────────────────────────────────────────────

def calendar(events, collect=None):
    d = {'report_date': D, 'events': events, 'missing': [], 'complete': True}
    if collect is not None:
        d['collect'] = collect
    return d


def test_7_confirmed_empty_calendar_passes(tmp_path):
    pol = policy([real_entry('us', '<datadir>/calendar.json')])
    rel = '<datadir>/calendar.json'
    put(tmp_path, 'calendar.json', calendar([], dict(STAMPED, empty='confirmed_none')))
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'                       # 재현: 전에는 incomplete_fields
    put(tmp_path, 'calendar.json', calendar([], dict(STAMPED, empty='has_data')))
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'
    put(tmp_path, 'calendar.json', calendar([]))                                        # 표시 없는 빈 일정은 그대로 막는다
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'
    put(tmp_path, 'calendar.json', calendar([{'x': 1}], dict(STAMPED, empty='confirmed_none')))
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'
    put(tmp_path, 'calendar.json', calendar([{'x': 1}], STAMPED))
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'


def test_7_confirmed_none_only_excuses_the_target_key(tmp_path):
    e = {'path': '<datadir>/x.json', 'class': 'gate', 'name': 'x', 'date': 'report_date',
         'require': ['a', 'b'], 'target': 'a'}
    pol = policy([e])
    put(tmp_path, 'x.json', {'report_date': D, 'a': [], 'b': [], 'collect': dict(STAMPED, empty='confirmed_none')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), '<datadir>/x.json') == 'incomplete_fields'   # b 는 비면 안 된다
    put(tmp_path, 'x.json', {'report_date': D, 'a': [], 'b': [1], 'collect': dict(STAMPED, empty='confirmed_none')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), '<datadir>/x.json') == 'ok'


def test_7_sweep_confirmed_none_emitters_have_a_target():
    """수집기가 confirmed_none 을 쓰는 gate 자료는 정책에 target 이 있거나(빈 목록 ↔ 없음 확인을 대조) 비울 수
    있는 필수 칸이 없다. 빈 목록이 정상일 수 있는 require 칸은 target 과 같아야 한다."""
    emitters = {('us', '<datadir>/calendar.json'): 'events', ('us', '<datadir>/fed/events.json'): 'events',
                ('us', '<datadir>/auctions.json'): 'today', ('us', '<datadir>/movers.json'): 'groups',
                ('us', '<datadir>/releases/index.json'): 'releases', ('us', '<tg>'): 'items',
                ('kr', '<datadir>/kr_movers.json'): 'groups', ('kr', '<datadir>/kr_index_etf.json'): '<items>',
                ('kr', '<tg>'): 'items'}
    for (m, p), t in emitters.items():
        e = real_entry(m, p)
        assert e.get('target') == t, (m, p)


def test_8_scorecard_is_a_reference_file(tmp_path, monkeypatch):
    e = real_entry('us', '<datadir>/scorecard.json')
    assert e.get('produced_by') == 'reference'
    pol = policy([META, e])
    rel = '<datadir>/scorecard.json'
    p = put(tmp_path, 'scorecard.json', {'report_date': '2026-11-13', 'sufficient': True})   # 검사기가 날짜를 직접 본다
    put(tmp_path, '_collect_status.json', {'files': {'scorecard.json': {'sha256': sha(p), 'bytes': 1,
                                                                        'collect_in': 'none'}}})
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'                       # 재현: 전에는 unstamped
    put(tmp_path, '_collect_status.json', {'files': {}})
    assert I.assess(pol, 'us', ctx(tmp_path))['files'][rel]['blocking']                # 해시 항목은 요구한다
    put(tmp_path, 'scorecard.json', '{')
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'unreadable'


# ── 9. 발행 뒤 재검사의 --recheck 는 적용일 전 글에만 ─────────────────────────────────────────

PAGE = '<html><body><main><h2>주식</h2><p>본문</p></main></body></html>'


def run(script, tmp_path, *args, name):
    h = tmp_path / name
    h.write_text(PAGE, encoding='utf-8')
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), '--html', str(h), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_9_recheck_does_not_relax_new_posts(tmp_path):
    new = I.STRICT_FROM
    old = '2026-11-16'
    assert old < new
    for day in (old, new):
        d = tmp_path / f'us-{day}'
        d.mkdir()
        (d / 'market_data.json').write_text(json.dumps({'report_date': day}))
        (d / 'fund_board.json').write_text(json.dumps({'report_date': day, 'status': 'unavailable'}))
        code = run('check_fund.py', tmp_path, '--datadir', str(d), '--market', 'us', '--recheck',
                   name=f'{day}.html').returncode
        assert code == (0 if day == old else 2), (day, code)           # 재현: 새 글도 0 이었다


def test_9_numbers_recheck_only_before_strict_from(tmp_path):
    for day, want_missing_is_fatal in (('2026-11-16', False), (I.STRICT_FROM, True)):
        k = tmp_path / f'kr-{day}'
        k.mkdir()
        (k / 'kr_market_data.json').write_text(json.dumps({'report_date': day}))
        (k / 'kr_flows.json').write_text('{}')
        (k / 'kr_top_value.json').write_text('[]')
        r = run('check_numbers.py', tmp_path, '--datadir', str(k), '--market', 'kr', '--date', day, '--recheck',
                name=f'{day}.html')
        assert ('kr_intraday.json' in r.stderr and r.returncode == 2) is want_missing_is_fatal, (day, r.stderr)


def test_9_legacy_releases_does_not_relax_new_posts(tmp_path):
    """--legacy-releases(정정기·윤문기가 check_macro·check_sources 에 늘 붙인다)도 같은 완화다 — 적용일 전 글에만."""
    for day in ('2026-11-16', I.STRICT_FROM):
        d = tmp_path / f'm-{day}'
        d.mkdir()
        (d / 'market_data.json').write_text(json.dumps({'report_date': day}))
        for script in ('check_macro.py', 'check_sources.py'):
            r = run(script, tmp_path, '--datadir', str(d), '--legacy-releases', name=f'{day}.html')
            assert (r.returncode == 2) is (day >= I.STRICT_FROM), (script, day, r.returncode, r.stderr[-300:])


def test_9_legacy_recheck_needs_a_known_date():
    assert I.legacy_recheck(True, 'posts/2026-11-16.html') is True
    assert I.legacy_recheck(True, f'posts/{I.STRICT_FROM}.html') is False
    assert I.legacy_recheck(False, 'posts/2026-11-16.html') is False
    assert I.legacy_recheck(True, 'posts/unknown.html') is False


def test_7_list_object_with_confirmed_sidecar_does_not_raise(tmp_path):
    e = {'path': '<datadir>/x.json', 'class': 'gate', 'name': 'x', 'require': ['events'], 'target': 'events'}
    pol = policy([e])
    put(tmp_path, 'x.json', [])
    put(tmp_path, '_collect_status.json', {'files': {'x.json': dict(STAMPED, empty='confirmed_none')}})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), '<datadir>/x.json') == 'incomplete_fields'


def test_8_real_scorecard_passes_as_reference(tmp_path, monkeypatch):
    """레포의 실제 data/scorecard.json(수집기 산출 그대로) — 적용일 뒤 해시 항목만 있으면 정상."""
    import shutil
    src = os.path.join(ROOT, 'data', 'scorecard.json')
    if not os.path.exists(src):
        pytest.fail('data/scorecard.json 이 없다 — 실제 생산자 산출로 확인할 수 없다')
    p = tmp_path / 'scorecard.json'
    shutil.copyfile(src, p)
    put(tmp_path, '_collect_status.json', {'files': {'scorecard.json': {'sha256': sha(str(p)), 'bytes': 1,
                                                                        'collect_in': 'none'}}})
    pol = policy([META, real_entry('us', '<datadir>/scorecard.json')])
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    f = I.assess(pol, 'us', ctx(tmp_path))['files']['<datadir>/scorecard.json']
    assert f['state'] == 'ok', f
