"""자료 상태 검사(`verification.inputs`) — 2026-11-17 1a 「자료 누락 차단」.

지키는 것: 없거나 비었거나 낡았거나 수집에 실패한 gate 자료는 「정상」이 아니다. 「없음 확인」(confirmed_none)은
수집기가 조회를 끝까지 마친 경우만. 분류되지 않은 파일은 미완료. 수집 상태 표시가 없는 것(unstamped)은 적용일
전에는 경고, 적용일부터 미완료.
"""
import hashlib
import json
import os

import pytest

from verification import inputs as I

D = '2026-11-16'


def policy(files, discontinued=None, market='us'):
    return I.validate({'format': I.FORMAT, 'markets': {market: {'files': files,
                                                                'discontinued': discontinued or []}}})


GATE_MD = {'path': '<datadir>/market_data.json', 'class': 'gate', 'name': '시장 데이터', 'date': 'report_date',
           'require': ['indices']}
GATE_MOV = {'path': '<datadir>/movers.json', 'class': 'gate', 'name': '움직인 종목', 'date': 'report_date',
            'target': 'groups'}
GATE_TXT = {'path': '<datadir>/fed/*.txt', 'class': 'gate', 'name': '연준 원문',
            'when': {'file': '<datadir>/fed/events.json', 'each': 'events', 'any_ok': 'sources',
                     'template': '<datadir>/fed/{key}.txt'},
            'else_class': 'unused', 'else_note': '오늘 책에 없는 사건의 원문'}
GATE_EV = {'path': '<datadir>/fed/events.json', 'class': 'gate', 'name': '연준 사건', 'date': 'report_date',
           'target': 'events'}
WRITER = {'path': '<datadir>/research_notes.md', 'class': 'writer', 'name': '웹 조사 노트',
          'risk': '작성자 웹 조사', 'covered_by': None}
UNUSED = {'path': '<datadir>/news/*.json', 'class': 'unused', 'name': '뉴스', 'note': '시황 브리프 입력 아님'}
STAMPED = {'status': 'ok', 'as_of': D, 'collected_at': '2026-11-17T08:18:00+09:00', 'source': 't',
           'response': 'ok', 'required_ok': True, 'missing': [], 'empty': 'has_data'}


def put(root, rel, obj):
    p = os.path.join(str(root), rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))
    return p


def ctx(root, **kw):
    c = {'datadir': str(root), 'date': D}
    c.update(kw)
    return c


def md(**kw):
    d = {'report_date': D, 'indices': {'x': 1}, 'complete': True, 'missing': []}
    d.update(kw)
    return d


def st(res, rel='<datadir>/market_data.json'):
    return res['files'][rel]['state']


# ── state 각각 ────────────────────────────────────────────────────────────

def test_ok_and_missing_and_empty_and_unreadable(tmp_path):
    pol = policy([GATE_MD])
    assert st(I.assess(pol, 'us', ctx(tmp_path))) == 'missing'
    put(tmp_path, 'market_data.json', '')
    assert st(I.assess(pol, 'us', ctx(tmp_path))) == 'empty_file'
    put(tmp_path, 'market_data.json', '{"report_date": ')
    assert st(I.assess(pol, 'us', ctx(tmp_path))) == 'unreadable'
    put(tmp_path, 'market_data.json', md())
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert st(r) == 'unstamped' and not I.blocks(r['files']['<datadir>/market_data.json'])   # 적용일 전 = 경고
    put(tmp_path, 'market_data.json', md(collect=STAMPED))
    r = I.assess(pol, 'us', ctx(tmp_path))
    f = r['files']['<datadir>/market_data.json']
    assert f['state'] == 'ok' and f['as_of'] == D and f['class'] == 'gate' and len(f['sha256']) == 64


def test_legacy_fields_are_enforced_before_effective(tmp_path):
    pol = policy([GATE_MD])
    for bad, want in ((md(report_date='2026-11-13'), 'stale'), (md(ok=False), 'failed'),
                      (md(error='HTTP 500'), 'failed'), (md(status='failed'), 'failed'),
                      (md(complete=False), 'incomplete_fields'), (md(missing=['yields/2Y']), 'incomplete_fields'),
                      (md(indices={}), 'incomplete_fields'), (md(pending=['x']), 'incomplete_fields')):
        put(tmp_path, 'market_data.json', bad)
        r = I.assess(pol, 'us', ctx(tmp_path))
        assert st(r) == want, bad
        assert I.blocks(r['files']['<datadir>/market_data.json'])


def test_missing_date_field_is_incomplete(tmp_path):
    d = md()
    del d['report_date']
    put(tmp_path, 'market_data.json', d)
    assert st(I.assess(policy([GATE_MD]), 'us', ctx(tmp_path))) == 'incomplete_fields'


def test_collect_stamp_conditions(tmp_path):
    pol = policy([GATE_MD])
    for c, want in ((dict(STAMPED, status='failed'), 'failed'), (dict(STAMPED, status='partial'), 'failed'),
                    (dict(STAMPED, as_of='2026-11-13'), 'stale'), (dict(STAMPED, required_ok=False), 'incomplete_fields'),
                    (dict(STAMPED, missing=['x']), 'incomplete_fields'), (dict(STAMPED, empty='unknown'), 'incomplete_fields'),
                    ('ok', 'incomplete_fields'), ({'status': 'ok'}, 'incomplete_fields')):
        put(tmp_path, 'market_data.json', md(collect=c))
        assert st(I.assess(pol, 'us', ctx(tmp_path))) == want, c


def test_unstamped_blocks_from_effective(tmp_path, monkeypatch):
    put(tmp_path, 'market_data.json', md())
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    r = I.assess(policy([GATE_MD]), 'us', ctx(tmp_path))
    assert st(r) == 'unstamped' and I.blocks(r['files']['<datadir>/market_data.json'])
    monkeypatch.setattr(I, 'EFFECTIVE', '2026-11-17')         # 글 날짜가 적용일 전이면 경고
    r = I.assess(policy([GATE_MD]), 'us', ctx(tmp_path))
    assert not I.blocks(r['files']['<datadir>/market_data.json'])


def test_status_file_stamps_list_files_and_hash(tmp_path):
    rows = [{'label': 'a'}]
    p = put(tmp_path, 'kr_top_value.json', rows)
    sha = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    ent = {'path': '<datadir>/kr_top_value.json', 'class': 'gate', 'name': '거래대금 상위', 'require': ['<items>']}
    pol = policy([ent, {'path': '<datadir>/_collect_status.json', 'class': 'gate', 'name': '수집 상태',
                        'optional': True, 'produced_by': 'meta'}], market='kr')
    put(tmp_path, '_collect_status.json', {'files': {'kr_top_value.json': dict(STAMPED, sha256=sha, bytes=12)}})
    assert st(I.assess(pol, 'kr', ctx(tmp_path)), '<datadir>/kr_top_value.json') == 'ok'
    put(tmp_path, 'kr_top_value.json', [{'label': 'b'}])
    assert st(I.assess(pol, 'kr', ctx(tmp_path)), '<datadir>/kr_top_value.json') == 'changed_after_collect'
    put(tmp_path, 'kr_top_value.json', [])
    put(tmp_path, '_collect_status.json', {'files': {'kr_top_value.json': STAMPED}})
    assert st(I.assess(pol, 'kr', ctx(tmp_path)), '<datadir>/kr_top_value.json') == 'incomplete_fields'
    put(tmp_path, '_collect_status.json', '{')                 # 깨진 상태 파일은 그 자체로 막는다
    r = I.assess(pol, 'kr', ctx(tmp_path))
    assert r['files']['<datadir>/_collect_status.json']['state'] == 'unreadable'
    assert I.blocks(r['files']['<datadir>/_collect_status.json'])


def test_target_list_needs_confirmed_none(tmp_path):
    pol = policy([GATE_MOV])
    rel = '<datadir>/movers.json'
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': [], 'collect': dict(STAMPED, empty='confirmed_none')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': [], 'collect': dict(STAMPED, empty='has_data')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': [1], 'collect': dict(STAMPED, empty='confirmed_none')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': []})         # 옛 방식 — 적용일 전 허용
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert st(r, rel) == 'unstamped' and not I.blocks(r['files'][rel])


def test_na_when(tmp_path, monkeypatch):
    moves = {'path': '<datadir>/kr_stock_moves.json', 'class': 'writer', 'name': '개별주 등락', 'risk': 'x',
             'covered_by': None}
    pol = policy([GATE_MOV, moves])
    na = {'file': '<datadir>/movers.json', 'list': 'groups', 'min_checked': 1,
          'legacy_evidence': {'file': '<datadir>/kr_stock_moves.json', 'min_items': 1}}
    ok_collect = dict(STAMPED, empty='confirmed_none', checked=60, expected=60)
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': [], 'collect': ok_collect})
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na) == (True, 'collect')
    for bad in (dict(ok_collect, checked=0), {k: v for k, v in ok_collect.items() if k != 'checked'},
                dict(ok_collect, empty='unknown'), dict(ok_collect, status='partial')):
        put(tmp_path, 'movers.json', {'report_date': D, 'groups': [], 'collect': bad})
        assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False, bad
    # 옛 방식 — 독립 근거(잰 종목)가 있어야만
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': []})
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False          # 근거 파일 없음
    put(tmp_path, 'kr_stock_moves.json', [])
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False          # 하나도 못 쟀다(KR 11/16)
    put(tmp_path, 'kr_stock_moves.json', [{'name': 'a', 'change_pct': 1.0}])
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na) == (True, 'legacy')
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), {'file': na['file'], 'list': 'groups'})[0] is False
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False      # 적용일부터 옛 방식은 안 된다
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': [], 'error': 'x'})
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False
    put(tmp_path, 'movers.json', {'report_date': D, 'groups': [1]})
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False
    os.unlink(os.path.join(str(tmp_path), 'movers.json'))
    assert I.na_when(I.assess(pol, 'us', ctx(tmp_path)), na)[0] is False


def test_rewritten_by_skips_only_the_hash(tmp_path):
    liq = {'path': '<datadir>/liquidity/liquidity.json', 'class': 'gate', 'name': '유동성 책', 'date': 'report_date',
           'status_ok': ['complete'], 'rewritten_by': 'build_liquidity --recompute'}
    pol = policy([liq])
    rel = '<datadir>/liquidity/liquidity.json'
    put(tmp_path, '_collect_status.json', {'files': {'liquidity/liquidity.json': {'sha256': '0' * 64}}})
    put(tmp_path, 'liquidity/liquidity.json', {'report_date': D, 'status': 'complete', 'collect': STAMPED})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'
    put(tmp_path, 'liquidity/liquidity.json', {'report_date': D, 'status': 'complete',
                                               'collect': dict(STAMPED, status='failed')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'failed'
    pol2 = policy([{k: v for k, v in liq.items() if k != 'rewritten_by'}])
    put(tmp_path, 'liquidity/liquidity.json', {'report_date': D, 'status': 'complete', 'collect': STAMPED})
    assert st(I.assess(pol2, 'us', ctx(tmp_path)), rel) == 'changed_after_collect'


def test_status_file_is_required_from_effective(tmp_path, monkeypatch):
    meta = {'path': '<datadir>/_collect_status.json', 'class': 'gate', 'name': '수집 상태 기록', 'optional': True,
            'required_when_enforced': True, 'produced_by': 'meta'}
    pol = policy([meta])
    assert not I.blocking(I.assess(pol, 'us', ctx(tmp_path)))['any']
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert r['files']['<datadir>/_collect_status.json']['state'] == 'missing' and I.blocking(r)['any']


def test_conditional_text_follows_events(tmp_path):
    pol = policy([GATE_EV, GATE_TXT])
    ev = {'report_date': D, 'events': [{'key': 'chair-1', 'sources': [{'ok': True}]},
                                       {'key': 'gov-2', 'sources': [{'ok': False}]}]}
    put(tmp_path, 'fed/events.json', ev)
    put(tmp_path, 'fed/old-0.txt', 'old')
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert r['files']['<datadir>/fed/chair-1.txt']['state'] == 'missing'
    assert '<datadir>/fed/gov-2.txt' not in r['files']
    assert r['files']['<datadir>/fed/old-0.txt']['class'] == 'unused'
    put(tmp_path, 'fed/chair-1.txt', '원문')
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert r['files']['<datadir>/fed/chair-1.txt']['class'] == 'gate'
    assert r['files']['<datadir>/fed/chair-1.txt']['state'] in ('ok', 'unstamped')
    put(tmp_path, 'fed/chair-1.txt', '')
    assert I.assess(pol, 'us', ctx(tmp_path))['files']['<datadir>/fed/chair-1.txt']['state'] == 'empty_file'


def test_unclassified_and_classes(tmp_path):
    pol = policy([GATE_MD, WRITER, UNUSED])
    put(tmp_path, 'market_data.json', md(collect=STAMPED))
    put(tmp_path, 'research_notes.md', '# x')
    put(tmp_path, 'news/2026-11-16.json', {})
    put(tmp_path, 'surprise.json', {})
    r = I.assess(pol, 'us', ctx(tmp_path))
    assert r['unclassified'] == ['<datadir>/surprise.json']
    assert r['files']['<datadir>/research_notes.md']['class'] == 'writer'
    assert r['files']['<datadir>/news/2026-11-16.json']['class'] == 'unused'
    assert I.blocking(r)['unclassified'] == ['<datadir>/surprise.json']
    # writer·unused 파일이 없어도 막지 않는다
    os.unlink(os.path.join(str(tmp_path), 'research_notes.md'))
    os.unlink(os.path.join(str(tmp_path), 'surprise.json'))
    assert not I.blocking(I.assess(pol, 'us', ctx(tmp_path)))['any']


def test_file_roots(tmp_path):
    tg = {'path': '<tg>', 'class': 'gate', 'name': '텔레그램', 'date': 'report_date', 'target': 'items',
          'stamp_key': 'telegram/{date}.json'}
    pol = policy([tg])
    r = I.assess(pol, 'us', ctx(tmp_path))                     # --tg 를 안 줬다
    assert r['files']['<tg>']['state'] == 'missing'
    p = put(tmp_path, 'w/kr_telegram.json', {'report_date': D, 'items': [1]})
    r = I.assess(pol, 'us', ctx(tmp_path / 'd', tg=p))
    assert r['files']['<tg>']['state'] == 'unstamped' and r['files']['<tg>']['file'] == '<tg>/kr_telegram.json'


def test_discontinued_needs_user_approval_and_excuses_missing(tmp_path):
    ent = {'path': '<datadir>/kr_market_data.json', 'class': 'gate', 'name': 'KR 시장', 'date': 'report_date'}
    disc = {'path': '<datadir>/kr_flows_intraday.json', 'name': '장중 수급', 'missing_key': 'flows_intraday',
            'reason': 'Naver 레거시 페이지 폐지', 'since': '2026-09-17', 'affects': {'gates': [], 'sections': ['§6']},
            'approved_by': 'user', 'approved_at': '2026-11-17'}
    pol = policy([ent], [disc], market='kr')
    put(tmp_path, 'kr_market_data.json', {'report_date': D, 'complete': True, 'missing': ['flows_intraday']})
    put(tmp_path, 'kr_flows_intraday.json', {})
    r = I.assess(pol, 'kr', ctx(tmp_path))
    assert r['files']['<datadir>/kr_market_data.json']['state'] == 'unstamped'
    assert r['files']['<datadir>/kr_flows_intraday.json']['class'] == 'discontinued'
    assert r['discontinued'][0]['name'] == '장중 수급'
    put(tmp_path, 'kr_market_data.json', {'report_date': D, 'complete': True, 'missing': ['flows_intraday', 'econ']})
    assert I.assess(pol, 'kr', ctx(tmp_path))['files']['<datadir>/kr_market_data.json']['state'] == 'incomplete_fields'
    for bad in (dict(disc, approved_by='routine'), {k: v for k, v in disc.items() if k != 'approved_by'}):
        with pytest.raises(I.PolicyError):
            policy([ent], [bad], market='kr')
    # 등록이 없으면 flows_intraday 도 결측으로 센다
    pol2 = policy([ent], market='kr')
    put(tmp_path, 'kr_market_data.json', {'report_date': D, 'complete': True, 'missing': ['flows_intraday']})
    assert I.assess(pol2, 'kr', ctx(tmp_path))['files']['<datadir>/kr_market_data.json']['state'] == 'incomplete_fields'


def test_policy_validation():
    with pytest.raises(I.PolicyError):
        I.validate({'format': 'x', 'markets': {}})
    with pytest.raises(I.PolicyError):
        policy([{'path': '<datadir>/a.md', 'class': 'writer', 'name': 'a'}])        # risk·covered_by 없음
    with pytest.raises(I.PolicyError):
        policy([{'path': '<datadir>/a.json', 'class': 'mystery', 'name': 'a'}])
    with pytest.raises(I.PolicyError):
        policy([{'path': 'a.json', 'class': 'unused', 'name': 'a'}])                 # 뿌리 없음


def test_state_ko_covers_every_state():
    assert set(I.STATE_KO) == set(I.STATES)
    assert I.describe({'name': '시장 데이터', 'file': '<datadir>/market_data.json', 'state': 'stale'}) \
        == '시장 데이터(market_data.json) — 날짜가 발행일과 다름'


def test_date_ref_ties_a_book_to_another_file(tmp_path):
    book = {'path': '<datadir>/macro.json', 'class': 'gate', 'name': '매크로 책', 'date': 'report_date',
            'date_rule': 'ref', 'date_ref': {'file': '<datadir>/macro_eval.json', 'field': 'macro_date'},
            'produced_by': 'ledger'}
    pol = policy([book])
    rel = '<datadir>/macro.json'
    put(tmp_path, 'macro.json', {'report_date': '2026-11-13'})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'      # 기준 파일이 없다
    put(tmp_path, 'macro_eval.json', {'macro_date': '2026-11-13'})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'                       # 수집 표시 불필요(ledger)
    put(tmp_path, 'macro.json', {'report_date': '2026-11-12'})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'stale'


def test_hash_only_status_entry_is_not_a_stamp(tmp_path):
    # stamp_collect.py 는 collect 칸이 파일 안에 있는 자료에도 해시만 적는다 — 그것을 수집 표시로 읽지 않는다
    pol = policy([GATE_MD])
    p = put(tmp_path, 'market_data.json', md())
    import hashlib as H
    put(tmp_path, '_collect_status.json', {'files': {'market_data.json': {
        'sha256': H.sha256(open(p, 'rb').read()).hexdigest(), 'bytes': 1}}})
    assert st(I.assess(pol, 'us', ctx(tmp_path))) == 'unstamped'


def test_target_where_counts_only_matching_items(tmp_path):
    ev = dict(GATE_EV, target_where={'fresh': True})
    pol = policy([ev])
    rel = '<datadir>/fed/events.json'
    stale_only = {'report_date': D, 'events': [{'key': 'old', 'fresh': False}]}
    put(tmp_path, 'fed/events.json', dict(stale_only, collect=dict(STAMPED, empty='confirmed_none')))
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'ok'                 # fresh 0건 = 없음 확인
    put(tmp_path, 'fed/events.json', dict(stale_only, collect=dict(STAMPED, empty='has_data')))
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'
    put(tmp_path, 'fed/events.json', {'report_date': D, 'events': [{'key': 'x', 'fresh': True}],
                                      'collect': dict(STAMPED, empty='confirmed_none')})
    assert st(I.assess(pol, 'us', ctx(tmp_path)), rel) == 'incomplete_fields'


def test_list_file_target_items(tmp_path):
    ent = {'path': '<datadir>/kr_index_etf.json', 'class': 'gate', 'name': 'ETF', 'target': '<items>'}
    pol = policy([ent], market='kr')
    rel = '<datadir>/kr_index_etf.json'
    put(tmp_path, 'kr_index_etf.json', [])
    put(tmp_path, '_collect_status.json', {'files': {'kr_index_etf.json': dict(STAMPED, empty='confirmed_none')}})
    assert st(I.assess(pol, 'kr', ctx(tmp_path)), rel) == 'ok'
    put(tmp_path, '_collect_status.json', {'files': {'kr_index_etf.json': dict(STAMPED, empty='has_data')}})
    assert st(I.assess(pol, 'kr', ctx(tmp_path)), rel) == 'incomplete_fields'
