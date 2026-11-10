"""다음 거래일 텔레그램 커서 = 발행판 D 파일과 D 의 실행 원본 중 채널별 가장 앞선 ok 커서(2026-11-10).

발행된 날의 telegram/<D>.json 은 발행판 그대로 동결된다. 발행 뒤 재수집이 받아 둔 구간의 커서는
versions/<market>/<D>/runs/*/files/<datadir>/telegram/<D>.json 에만 있다.
spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md 「무엇을 하나」 7.
"""
import json
import os

import fetch_telegram as F


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f)


def test_run_cursor_ahead_wins_per_channel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    D = '2026-11-06'
    pub = {'report_date': D, 'channels': {'a': {'status': 'ok', 'last_id': 10, 'last_dt': '2026-11-06T09:00:00+00:00'},
                        'b': {'status': 'ok', 'last_id': 50, 'last_dt': '2026-11-06T09:00:00+00:00'}}}
    _w(f'kr/data/telegram/{D}.json', pub)
    run = {'channels': {'a': {'status': 'ok', 'last_id': 12, 'last_dt': '2026-11-06T16:00:00+00:00'},
                        'b': {'status': 'failed', 'last_id': 99, 'last_dt': '2026-11-06T16:00:00+00:00'}}}
    _w(f'versions/kr/{D}/runs/r1/files/kr/data/telegram/{D}.json', run)
    prev = F.previous_file('kr/data/telegram', '2026-11-09')
    out = F.with_run_cursors(prev, 'kr/data', 'kr')
    assert out['channels']['a']['last_id'] == 12        # 실행 원본이 더 앞섰다
    assert out['channels']['b']['last_id'] == 50        # 실패한 채널 커서는 쓰지 않는다


def test_no_runs_returns_prev_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prev = {'report_date': '2026-11-06', 'channels': {'a': {'status': 'ok', 'last_id': 1}}}
    assert F.with_run_cursors(prev, 'kr/data', 'kr') == prev
    assert F.with_run_cursors(None, 'kr/data', 'kr') is None
