"""일본 일간 뉴스의 국내/해외 필터 — Jev conf ≥ 0.9 우선, 실패 시 정규식 (2026-10-27, codex 설계 검토 #1-#9)."""
import json
import os
import threading
import time

import pytest

from japan import region_filter as F
from japan import region_shadow as R

S = '2026-10-27'


def _row(guid, title, cat='macro'):
    return {'guid': guid, 'title': title, 'category': cat, 'source': 'ロイター', 'feed': 'bus_all'}


def _ans(label='foreign', conf=1.0, model='jev-1.14.0'):
    probs = {'domestic': 0.0, 'foreign_impact': 0.0, 'foreign': 0.0}
    probs[label] = 1.0
    return {'model': model, 'answers': {'region': {'type': 'choice', 'choice': label, 'confidence': conf,
                                                   'probabilities': probs}}}


def _poster(table):
    """제목 → 응답(dict) 또는 예외. 받은 제목을 기록한다."""
    seen = []

    def post(body, key, timeout=None):
        seen.append(body['state'])
        got = table.get(body['state'], _ans('domestic'))
        if isinstance(got, BaseException):
            raise got
        return got
    post.seen = seen
    return post


ROWS = [_row('a', '日銀、金融政策を維持'), _row('b', 'カナダ中銀、利上げ'), _row('c', '米関税で日本車に打撃', 'industry'),
        _row('d', '米大手行、AI遮断'), _row('e', 'カナダ中銀、利上げ')]


# ── 억제 규칙 ─────────────────────────────────────────────────────────────
def test_drops_only_foreign_at_or_above_threshold_and_keeps_order():
    post = _poster({'カナダ中銀、利上げ': _ans('foreign', 0.9), '米関税で日本車に打撃': _ans('foreign_impact', 1.0),
                    '米大手行、AI遮断': _ans('foreign', 0.89)})
    kept, meta = F.run(list(ROWS), {'TYPESAFE_API_KEY': 'k'}, post=post)
    assert [r['guid'] for r in kept] == ['a', 'c', 'd']            # 0.89 는 정규식대로 남는다
    assert [d['guid'] for d in meta['dropped']] == ['b', 'e']
    assert meta['mode'] == 'jev' and meta['stopped'] == 'complete' and meta['threshold'] == 0.9
    assert post.seen.count('カナダ中銀、利上げ') == 1                # 같은 제목은 한 번
    assert meta['asked'] == 4 and meta['answered'] == 4


def test_input_rows_are_not_mutated():
    rows = [dict(r) for r in ROWS]
    before = json.dumps(rows, sort_keys=True)
    F.run(rows, {'TYPESAFE_API_KEY': 'k'}, post=_poster({'カナダ中銀、利上げ': _ans()}))
    assert json.dumps(rows, sort_keys=True) == before


def test_no_key_is_todays_regex_result_without_calls():
    kept, meta = F.run(list(ROWS), {}, post=lambda *a, **k: pytest.fail('network'))
    assert kept == ROWS and meta['mode'] == 'regex' and meta['stopped'] == 'no_key' and meta['dropped'] == []


def test_model_mismatch_falls_back_for_that_row():
    """#8 — 평가한 고정 버전이 아닌 응답으로는 빼지 않는다."""
    post = _poster({'カナダ中銀、利上げ': _ans('foreign', 1.0, model='jev-1.15.0')})
    kept, meta = F.run(list(ROWS), {'TYPESAFE_API_KEY': 'k'}, post=post)
    assert 'b' in [r['guid'] for r in kept] and meta['errors'] == {'model:jev-1.15.0': 1}


def test_auth_failure_keeps_earlier_verdicts_and_regex_for_the_rest():
    """#2 — 예상된 실패는 행 단위: 받은 판정은 쓰고 나머지는 정규식."""
    from japan.jev_client import JevHTTPError
    rows = [_row('x', 'カナダ中銀、利上げ'), _row('y', '米大手行、AI遮断'), _row('z', 'ドアダッシュ買収')]
    post = _poster({'カナダ中銀、利上げ': _ans('foreign'), '米大手行、AI遮断': JevHTTPError(401)})
    kept, meta = F.run(rows, {'TYPESAFE_API_KEY': 'k'}, post=post)
    assert [r['guid'] for r in kept] == ['y', 'z'] and meta['stopped'] == 'auth'
    assert post.seen == ['カナダ中銀、利上げ', '米大手行、AI遮断']


def test_schema_error_row_falls_back():
    post = _poster({'カナダ中銀、利上げ': {'model': 'jev-1.14.0', 'answers': {}}})
    kept, meta = F.run(list(ROWS), {'TYPESAFE_API_KEY': 'k'}, post=post)
    assert 'b' in [r['guid'] for r in kept] and meta['errors'] == {'schema:shape': 1}


def test_hanging_request_cannot_hold_the_collector():
    """#1 — 응답이 끝나지 않아도 마감에 돌아온다. 그때까지 받은 판정은 쓴다."""
    gate = threading.Event()

    def post(body, key, timeout=None):
        if body['state'] == '米大手行、AI遮断':
            gate.wait(30)                       # 끝나지 않는 응답
        return _ans('foreign') if body['state'] == 'カナダ中銀、利上げ' else _ans('domestic')
    t0 = time.monotonic()
    kept, meta = F.run(list(ROWS), {'TYPESAFE_API_KEY': 'k'}, post=post, deadline=0.3)
    gate.set()
    assert time.monotonic() - t0 < 2
    assert meta['stopped'] == 'deadline'
    assert [r['guid'] for r in kept] == ['a', 'c', 'd']       # b·e 는 빠졌고(받은 판정), d 는 정규식


def test_secret_never_in_meta():
    from japan.jev_client import JevHTTPError
    _, meta = F.run(list(ROWS), {'TYPESAFE_API_KEY': 'TEST_ONLY_SECRET'},
                    post=_poster({'日銀、金融政策を維持': JevHTTPError(500)}))
    assert 'TEST_ONLY_SECRET' not in json.dumps(meta)


def test_uses_the_evaluated_configuration():
    assert F.JEV_MIN_CONF == 0.9 and R.JEV_MODEL == 'jev-1.14.0'
    seen = []

    def post(body, key, timeout=None):
        seen.append(body)
        return _ans('domestic')
    F.run([_row('a', '日銀')], {'TYPESAFE_API_KEY': 'k'}, post=post)
    assert seen == [R.jev_body('日銀')]


# ── 수집 흐름 ─────────────────────────────────────────────────────────────
def _list_row(guid, title, created='15:00'):
    return {'guid': guid, 'url': f'https://finance.yahoo.co.jp/news/detail/{guid}', 'title': title,
            'source': 'ロイター', 'created': created, 'paid': False, 'feed': 'bus_all'}


DAILY = [_list_row('n1', '日経平均は4日ぶり反発、ＡＩ株に買い戻し', '16:10'),
         _list_row('c1', 'カナダ中銀、28日に利上げの見通し エネルギー高の波及阻止へ'),
         _list_row('d1', 'ドアダッシュ、食品宅配インスタカート買収へ最終交渉 28日合意も'),
         _list_row('y1', 'ヤマダＨＤ、中間期予想を上方修正 基準改定に向けエアコン特需'),
         _list_row('m1', '特殊要因除くＣＰＩ、9月は伸び急加速 日銀の基調2％判断後押しか')]
FOREIGN = {'カナダ中銀、28日に利上げの見通し エネルギー高の波及阻止へ': _ans('foreign', 1.0),
           'ドアダッシュ、食品宅配インスタカート買収へ最終交渉 28日合意も': _ans('foreign', 1.0)}


def _collect(tmp_path, monkeypatch, env, post=None, summarize=None):
    import fetch_japan_news as FJ
    monkeypatch.setattr(FJ, 'harvest', lambda *a, **k: ([dict(r) for r in DAILY], [], {}))
    monkeypatch.setattr(FJ, 'harvest_official', lambda *a, **k: ([], [], True))

    def bodies(chosen, *a, **k):
        for it in chosen:
            it['body_chars'], it['published'] = 900, f'{S}T15:00:00+09:00'
        return chosen
    monkeypatch.setattr(FJ, 'fetch_bodies', bodies)
    monkeypatch.setattr(FJ, 'summarize_chosen', summarize or (lambda *a, **k: None))
    for k in list(os.environ):
        if k == 'TYPESAFE_API_KEY':
            monkeypatch.delenv(k)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    payload = FJ.collect_daily(S, S, str(tmp_path / 'b'), None, datadir=str(tmp_path), region_post=post)
    disk = json.loads((tmp_path / 'news' / 'daily' / f'{S}.json').read_text(encoding='utf-8'))
    return payload, disk


def test_collect_daily_drops_foreign_and_records_it(tmp_path, monkeypatch):
    payload, disk = _collect(tmp_path, monkeypatch, {'TYPESAFE_API_KEY': 'k'}, post=_poster(FOREIGN))
    guids = [i['guid'] for i in disk['items']]
    assert 'c1' not in guids and 'd1' not in guids and {'n1', 'y1', 'm1'} <= set(guids)
    rf = disk['region_filter']
    assert rf['mode'] == 'jev' and sorted(d['guid'] for d in rf['dropped']) == ['c1', 'd1']


def test_collect_daily_region_filter_survives_failed_summary(tmp_path, monkeypatch):
    """#9 — 두 번째 저장(요약 실패 경로 포함)에도 감사 기록이 남는다."""
    def boom(*a, **k):
        raise RuntimeError('summary broke')
    _, disk = _collect(tmp_path, monkeypatch, {'TYPESAFE_API_KEY': 'k'}, post=_poster(FOREIGN), summarize=boom)
    assert disk['region_filter']['mode'] == 'jev' and any('요약 단계 실패' in n for n in disk['notes'])


def test_collect_daily_without_key_matches_regex_baseline(tmp_path, monkeypatch):
    base, _ = _collect(tmp_path / 'a', monkeypatch, {})
    assert {'c1', 'd1'} <= {i['guid'] for i in base['items']}          # 오늘의 정규식은 해외를 남긴다
    assert base['region_filter'] == {**base['region_filter'], 'mode': 'regex', 'stopped': 'no_key'}


def test_collect_daily_filter_crash_rolls_back_to_regex(tmp_path, monkeypatch):
    """#2 — 필터 코드의 예상 못 한 예외는 전체 되돌림: 키가 없을 때와 items 가 같다."""
    base, _ = _collect(tmp_path / 'a', monkeypatch, {})
    monkeypatch.setattr(F, 'apply', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('bug')))
    crashed, disk = _collect(tmp_path / 'b', monkeypatch, {'TYPESAFE_API_KEY': 'k'}, post=_poster(FOREIGN))
    assert crashed['items'] == base['items']
    assert disk['region_filter']['mode'] == 'regex' and disk['region_filter']['stopped'] == 'crash:RuntimeError'
