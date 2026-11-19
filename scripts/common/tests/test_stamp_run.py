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


import pytest


@pytest.fixture(autouse=True)
def _run_id(monkeypatch):
    # 시작 기록은 같은 실행 ID 의 stamp 만 쓴다(3회차 G4) — 시험의 --begin·stamp 는 한 실행으로 둔다
    monkeypatch.setenv(S.RUN_ID_ENV, 'test-run')
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)


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
                           'run_id': 'test-run', 'steps_known': True}


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


# ── 3회차 G4 — 시작 기록은 그것을 연 실행의 것일 때만 쓴다 ──────────────────────────────────

def test_g4_open_begin_record_of_another_run_is_not_reused(tmp_path, monkeypatch):
    # codex 재현: 첫 실행이 --begin 뒤 파일을 쓰고 최종 stamp 전에 죽었다. 다음 실행이 --begin 없이 stamp 하면
    # 앞 실행의 open: true·시작 시각으로 그 파일을 written 이라 했다.
    monkeypatch.setenv(S.RUN_ID_ENV, 'run-1')
    S.begin(str(tmp_path), now=T0 - dt.timedelta(minutes=1))
    w(tmp_path / 'kr_market_data.json', {'report_date': RD, 'collect': col(T0)})
    w(tmp_path / 'kr_session.json', {'report_date': RD, 'collect': col(T0)})
    monkeypatch.setenv(S.RUN_ID_ENV, 'run-2')                                  # 다음 실행 — --begin 을 건너뛰었다
    book = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})
    assert book['files']['kr_session.json']['run'] == 'unknown'                # 재현: 전에는 written
    assert book['run']['checked'] is False


def test_g4_same_run_id_is_checked_and_missing_id_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv(S.RUN_ID_ENV, 'run-7')
    run = S.begin(str(tmp_path), now=T0 - dt.timedelta(minutes=1))
    assert run['run_id'] == 'run-7' and run['open'] is True
    w(tmp_path / 'kr_market_data.json', {'report_date': RD, 'collect': col(T0)})
    w(tmp_path / 'kr_session.json', {'report_date': RD, 'collect': col(T0)})
    book = S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})
    assert book['files']['kr_session.json']['run'] == 'written' and book['run']['checked'] is True
    assert book['run']['run_id'] == 'run-7'
    # 실행 ID 를 모르는 stamp 는 어느 시작 기록도 자기 것이라 할 수 없다
    S.begin(str(tmp_path), now=T1)
    monkeypatch.delenv(S.RUN_ID_ENV)
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
    assert S.stamp(str(tmp_path), steps={'collect': {'outcome': 'success'}})['files']['kr_session.json']['run'] == 'unknown'


def test_g4_run_id_sources(tmp_path, monkeypatch):
    monkeypatch.delenv(S.RUN_ID_ENV, raising=False)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    assert S.current_run_id() == '123-2'
    monkeypatch.setenv(S.RUN_ID_ENV, 'explicit')
    assert S.current_run_id() == 'explicit'
    monkeypatch.delenv(S.RUN_ID_ENV)
    monkeypatch.delenv('GITHUB_RUN_ID')
    assert S.current_run_id() is None
    # 로컬: --begin 이 ID 를 만들어 적는다 — 끝의 stamp 에 그 값을 넘겨야 같은 실행이다
    run = S.begin(str(tmp_path), now=T0)
    assert run['run_id'] and run['generated'] is True
    w(tmp_path / 'kr_market_data.json', {'report_date': RD, 'collect': col(T0 + dt.timedelta(minutes=1))})
    assert S.stamp(str(tmp_path), run_id=run['run_id'])['run']['checked'] is True


def test_us_yields_patch_run_keeps_the_base_files_and_stamps_only_what_it_rewrote(tmp_path):
    """수익률만 고치는 재실행(2026-11-19, main 의 us-collect-wait)과 1a 를 합친 자리 — 병합 때 찾은 틈.

    고치기 실행은 `collect` 단계가 성공하고 `patched=true` 를 내지만 market_data.json 외의 파일은 다시 쓰지 않는다.
    전에는 그 파일들이 「단계는 돌았는데 다시 쓰이지 않음」 = failed 로 찍혀, 1a 를 켜면 네이버 종가를 기다린 날마다
    멀쩡한 판이 막혔다. 그 파일들은 첫 실행의 판이 그대로 유효하다 — 건너뜀과 같다."""
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    w(tmp_path / 'market_data.json', {'report_date': RD, 'collect': col(T1 + dt.timedelta(minutes=2))})
    w(tmp_path / 'liquidity' / 'liquidity.json', {'report_date': RD, 'collect': col(T1 + dt.timedelta(minutes=1))})
    steps = {'collect': {'outcome': 'success', 'outputs': {'patched': 'true'}},
             'auctions': {'outcome': 'success', 'outputs': {}}, 'telegram': {'outcome': 'success', 'outputs': {}},
             'liquidity': {'outcome': 'success', 'outputs': {}}}
    f = S.stamp(str(tmp_path), steps=steps)['files']
    assert f['market_data.json']['run'] == 'written'
    assert f['macro_metrics.json']['run'] == 'skipped' and f['macro_metrics.json']['status'] == 'ok'
    assert not [k for k, e in f.items() if e.get('run') == 'failed' and k != 'auctions.json'
                and not k.startswith('telegram/') and k != 'auction_table.html']


def test_us_yields_patch_does_not_excuse_market_data_itself(tmp_path):
    """고치기 실행이 market_data.json 을 다시 쓰지 못했으면(고친 판이 없다) 그것은 실패다 — 건너뜀으로 덮지 않는다."""
    us_first_run(tmp_path)
    S.begin(str(tmp_path), now=T1)
    steps = {'collect': {'outcome': 'success', 'outputs': {'patched': 'true'}}}
    f = S.stamp(str(tmp_path), steps=steps)['files']
    assert f['market_data.json']['run'] == 'failed'
