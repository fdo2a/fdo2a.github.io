"""같은 날 재수집 실패가 성공으로 다시 찍히지 않는다(2026-11-17, 1a 구현 검토 2회차 F3).

전에는: 그날 정상 `kr_session.json` 이 있는데 둘째 실행의 세션 수집이 예외로 죽으면(수집기가 삼킨다) 옛 파일이 남고,
`stamp_collect.py` 가 그 파일의 `collect`(ok)와 해시를 이번 실행의 장부에 다시 적었다 — 이번 수집 실패가 사라졌다.
지금은 잡 시작의 `--begin` 이 시각을 적고, 끝의 stamp 가 그 뒤에 쓰이지 않은 파일을 `status: failed`·`run: failed`
(옛 바이트는 `stale_copy`)로 적는다. 정당하게 다시 쓰지 않는 길(US 둘째 슬롯의 건너뜀, 동결된 텔레그램)은 단계 결과
(`COLLECT_STEPS`)로 가른다. 워크플로 쪽 정적 확인은 `scripts/us/tests/test_stamp_workflow.py`(PyYAML 이 필요하다 —
이 폴더는 PyYAML 없는 CI 잡에서도 돈다).
"""
import datetime as dt
import json
import os

import stamp_collect as S
from common import collect_status as C

RD = '2026-11-16'
KST = dt.timezone(dt.timedelta(hours=9))
T0 = dt.datetime(2026, 11, 16, 17, 0, 0, tzinfo=KST)       # 첫 실행
T1 = dt.datetime(2026, 11, 16, 17, 30, 0, tzinfo=KST)      # 둘째 실행 시작
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def w(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding='utf-8')


def col(at, status='ok', **kw):
    return C.build(status, RD, 'x', empty=kw.pop('empty', 'has_data'), collected_at=C.now_iso(at), **kw)


def kr_first_run(d):
    w(d / 'kr_market_data.json', {'report_date': RD, 'collect': col(T0)})
    w(d / 'kr_session.json', {'report_date': RD, 'collect': col(T0)})
    S.begin(str(d), now=T0 - dt.timedelta(minutes=1))
    return S.stamp(str(d), steps={'collect': {'outcome': 'success', 'outputs': {}}})


def test_first_run_is_written(tmp_path):
    book = kr_first_run(tmp_path)
    e = book['files']['kr_session.json']
    assert e['run'] == 'written' and e['status'] == 'ok' and e['sha256']
    assert book['run'] == {'started_at': C.now_iso(T0 - dt.timedelta(minutes=1)), 'open': False, 'checked': True,
                           'steps_known': True}


def test_same_day_rerun_failure_is_stamped_failed_not_ok(tmp_path):
    first = kr_first_run(tmp_path)['files']['kr_session.json']
    # 둘째 실행: 시장 자료는 다시 썼고 세션은 예외로 못 썼다(옛 파일이 남는다)
    S.begin(str(tmp_path), now=T1)
    w(tmp_path / 'kr_market_data.json', {'report_date': RD, 'collect': col(T1 + dt.timedelta(minutes=2))})
    assert C.note_run_failure(str(tmp_path), 'kr_session.json', RuntimeError('yfinance timeout')) is True
    book = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success', 'outputs': {}}})
    e = book['files']['kr_session.json']
    assert e['status'] == 'failed' and e['run'] == 'failed'                 # 재현: 전에는 status ok + 옛 해시
    assert 'sha256' not in e and e['stale_copy']['sha256'] == first['sha256']
    assert e['stale_copy']['status'] == 'ok' and 'yfinance timeout' in e['response']
    assert book['files']['kr_market_data.json']['run'] == 'written'
    assert book['files']['kr_market_data.json']['status'] == 'ok'


def test_failure_without_a_note_is_still_caught(tmp_path):
    kr_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    e = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_session.json']
    assert e['run'] == 'failed' and 'collect' in e['response']


def test_normal_rerun_gets_the_new_hash_and_passes(tmp_path):
    first = kr_first_run(tmp_path)['files']['kr_session.json']
    S.begin(str(tmp_path), now=T1)
    for n in ('kr_market_data.json', 'kr_session.json'):
        w(tmp_path / n, {'report_date': RD, 'v': 2, 'collect': col(T1 + dt.timedelta(minutes=2))})
    e = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_session.json']
    assert e['run'] == 'written' and e['status'] == 'ok' and e['sha256'] != first['sha256'] and 'stale_copy' not in e


def test_failure_stays_until_the_file_is_really_rewritten(tmp_path):
    kr_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    assert S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_session.json']['run'] == 'failed'
    # 셋째 실행이 통째로 건너뛰어도(US 둘째 슬롯 같은 길) 앞선 실패는 지워지지 않는다
    t2 = T1 + dt.timedelta(hours=1)
    S.begin(str(tmp_path), now=t2)
    e = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success', 'outputs': {'skipped': 'true'}}})
    assert e['files']['kr_session.json']['run'] == 'failed' and e['files']['kr_session.json']['stale_copy']['sha256']
    # 다시 쓰이면 풀린다
    t3 = t2 + dt.timedelta(hours=1)
    S.begin(str(tmp_path), now=t3)
    w(tmp_path / 'kr_session.json', {'report_date': RD, 'collect': col(t3 + dt.timedelta(minutes=1))})
    e = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_session.json']
    assert e['run'] == 'written' and e['status'] == 'ok' and e['sha256']


def us_first_run(d):
    for n in ('market_data.json', 'macro_metrics.json', 'auctions.json'):
        w(d / n, {'report_date': RD, 'collect': col(T0)})
    w(d / 'liquidity' / 'liquidity.json', {'report_date': RD, 'collect': col(T0)})
    w(d / 'telegram' / f'{RD}.json', {'report_date': RD, 'items': [], 'collect': col(T0)})
    w(d / 'auction_table.html', '<table></table>')
    S.begin(str(d), now=T0 - dt.timedelta(minutes=1))
    return S.stamp(str(d), steps={k: {'outcome': 'success', 'outputs': {}} for k in
                                  ('collect', 'auctions', 'liquidity', 'telegram')})


def test_us_skipped_second_slot_is_not_a_failure(tmp_path):
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    w(tmp_path / 'liquidity' / 'liquidity.json', {'report_date': RD, 'collect': col(T1 + dt.timedelta(minutes=1))})
    steps = {'collect': {'outcome': 'success', 'outputs': {'skipped': 'true'}}, 'auctions': {'outcome': 'skipped'},
             'telegram': {'outcome': 'skipped'}, 'liquidity': {'outcome': 'success'}}
    f = S.stamp(str(tmp_path), steps=steps)['files']
    assert f['market_data.json']['run'] == 'skipped' and f['market_data.json']['status'] == 'ok'
    assert f['market_data.json']['sha256'] and f['auctions.json']['run'] == 'skipped'
    assert f['auction_table.html']['run'] == 'skipped'                       # 생산자를 따른다
    assert f['liquidity/liquidity.json']['run'] == 'written'
    assert not [k for k, e in f.items() if e.get('run') == 'failed']


def test_us_step_crash_before_writing_is_failed(tmp_path):
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    fresh = col(T1 + dt.timedelta(minutes=1))
    for n in ('market_data.json', 'macro_metrics.json'):
        w(tmp_path / n, {'report_date': RD, 'collect': fresh})
    w(tmp_path / 'liquidity' / 'liquidity.json', {'report_date': RD, 'collect': fresh})
    steps = {'collect': {'outcome': 'success', 'outputs': {}}, 'auctions': {'outcome': 'failure'},
             'liquidity': {'outcome': 'success'}, 'telegram': {'outcome': 'success'}}
    f = S.stamp(str(tmp_path), steps=steps)['files']
    assert f['auctions.json']['run'] == 'failed' and f['auctions.json']['status'] == 'failed'
    assert f['auction_table.html']['run'] == 'failed' and 'sha256' not in f['auction_table.html']
    assert f[f'telegram/{RD}.json']['run'] == 'kept'                         # 동결 — 단계는 성공, 파일은 그대로
    assert f['market_data.json']['run'] == 'written'


def test_us_swallowed_exception_inside_collect_is_failed(tmp_path):
    # collect_market_data 가 macro_metrics 블록의 예외를 삼키면 단계는 성공이고 파일은 옛 판이다
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    w(tmp_path / 'market_data.json', {'report_date': RD, 'collect': col(T1 + dt.timedelta(minutes=1))})
    C.note_run_failure(str(tmp_path), 'macro_metrics.json', 'KeyError: CPI')
    steps = {k: {'outcome': 'success', 'outputs': {}} for k in ('collect', 'auctions', 'liquidity', 'telegram')}
    f = S.stamp(str(tmp_path), steps=steps)['files']
    assert f['macro_metrics.json']['run'] == 'failed' and 'KeyError' in f['macro_metrics.json']['response']


def test_telegram_step_failure_is_not_kept(tmp_path):
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    steps = {'collect': {'outcome': 'success', 'outputs': {'skipped': 'true'}}, 'telegram': {'outcome': 'failure'}}
    assert S.stamp(str(tmp_path), steps=steps)['files'][f'telegram/{RD}.json']['run'] == 'failed'
    S.begin(str(tmp_path), now=T1)
    f = S.stamp(str(tmp_path), steps=None)['files'][f'telegram/{RD}.json']
    assert f['run'] == 'failed'                                              # 앞선 실패는 남는다


def test_without_begin_nothing_is_assumed(tmp_path):
    w(tmp_path / 'kr_market_data.json', {'report_date': RD, 'collect': col(T0)})
    w(tmp_path / 'kr_session.json', {'report_date': RD, 'collect': col(T0)})
    book = S.stamp(str(tmp_path))
    assert book['run']['checked'] is False and book['files']['kr_session.json']['run'] == 'unknown'
    # 닫힌 기록은 다음 실행의 시작 기록이 아니다
    kr_first_run(tmp_path)
    book = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})
    assert book['run']['checked'] is False and book['files']['kr_session.json']['run'] == 'unknown'


def test_reference_file_without_collect_uses_mtime(tmp_path):
    w(tmp_path / 'market_data.json', {'report_date': RD, 'collect': col(T0)})
    w(tmp_path / 'scorecard.json', {'x': 1})
    old = (T1 - dt.timedelta(minutes=30)).timestamp()
    os.utime(tmp_path / 'scorecard.json', (old, old))
    S.begin(str(tmp_path), now=T1)
    steps = {'collect': {'outcome': 'success', 'outputs': {}}}
    assert S.stamp(str(tmp_path), steps=steps)['files']['scorecard.json']['run'] == 'failed'
    S.begin(str(tmp_path), now=T1)
    new = (T1 + dt.timedelta(minutes=1)).timestamp()
    os.utime(tmp_path / 'scorecard.json', (new, new))
    assert S.stamp(str(tmp_path), steps=steps)['files']['scorecard.json']['run'] == 'written'


def test_note_without_an_open_run_is_a_noop(tmp_path):
    assert C.note_run_failure(str(tmp_path), 'kr_session.json', 'x') is False
    assert not (tmp_path / C.STATUS_FILE).exists()


def test_sidecar_list_file_not_rewritten_is_failed_and_keeps_its_old_status(tmp_path):
    w(tmp_path / 'kr_market_data.json', {'report_date': RD, 'collect': col(T0)})
    w(tmp_path / 'kr_top_value.json', [{'name': 'a'}])
    S.begin(str(tmp_path), now=T0 - dt.timedelta(minutes=1))
    C.record_sidecar(str(tmp_path), 'kr_top_value.json', col(T0))
    assert S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_top_value.json']['run'] == 'written'
    S.begin(str(tmp_path), now=T1)
    e = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_top_value.json']
    assert e['run'] == 'failed' and e['stale_copy']['status'] == 'ok' and e['stale_copy']['collect_in'] == 'sidecar'
    S.begin(str(tmp_path), now=T1)
    C.record_sidecar(str(tmp_path), 'kr_top_value.json', col(T1 + dt.timedelta(minutes=1)))
    e = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_top_value.json']
    assert e['run'] == 'written' and e['status'] == 'ok' and e['collect_in'] == 'sidecar' and e['sha256']


def test_every_ledger_gate_file_is_run_tracked():
    """정책의 gate 자료 가운데 수집 잡이 쓰는 것(collector·reference)은 모두 이 판정의 대상이다 — 빠지면 적용일 뒤 막힌다."""
    import fnmatch
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    from verification import inputs as I
    pol = I.load(os.path.join(ROOT, 'config', 'prepub_inputs.json'))
    for market in ('us', 'kr'):
        files, _ = I.entries(pol, market)
        for e in files:
            if e['class'] != 'gate' or e.get('produced_by', 'collector') not in I.LEDGER_PRODUCERS:
                continue
            rel = (e.get('stamp_key') or e['path'].split('>/', 1)[-1]).replace('{date}', '{D}')
            if rel in S.STEP_OF[market]:
                continue
            producer = next((p for pat, p in S.REGISTRY[market].items() if p and fnmatch.fnmatchcase(rel, pat)), None)
            assert producer in S.STEP_OF[market], (market, e['path'])


def test_frozen_file_clears_a_carried_failure_when_its_step_runs_again(tmp_path):
    # 동결된 텔레그램 파일은 그날 다시 쓰이지 않는다 — 단계가 한 번 죽었다가 다음 실행에서 성공(동결)하면 풀려야 한다
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    skipped = {'collect': {'outcome': 'success', 'outputs': {'skipped': 'true'}}}
    key = f'telegram/{RD}.json'
    f = S.stamp(str(tmp_path), steps=dict(skipped, telegram={'outcome': 'failure'}))['files'][key]
    assert f['run'] == 'failed'
    first_response = f['response']
    S.begin(str(tmp_path), now=T1 + dt.timedelta(minutes=30))
    f = S.stamp(str(tmp_path), steps=dict(skipped, telegram={'outcome': 'skipped'}))['files'][key]
    assert f['run'] == 'failed' and f['response'] == first_response          # 건너뛴 실행은 지우지 못한다, 사유는 그대로
    S.begin(str(tmp_path), now=T1 + dt.timedelta(minutes=60))
    f = S.stamp(str(tmp_path), steps=dict(skipped, telegram={'outcome': 'success'}))['files'][key]
    assert f['run'] == 'kept' and f['status'] == 'ok' and f['sha256'] and 'stale_copy' not in f
