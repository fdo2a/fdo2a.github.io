"""US 뉴스 국내/해외 필터 (2026-10-28) — 경제·매크로·정치만, dedupe 전, 그날 파일의 기사는 빼지 않는다."""
import json

import fetch_news as FN
from common import region_filter as RF
from common import region_labels as L
from us import news as N


def _ans(label='foreign', conf=1.0):
    probs = {k: 0.0 for k in L.LABELS}
    probs[label] = 1.0
    return {'model': L.JEV_MODEL, 'answers': {'region': {'type': 'choice', 'choice': label, 'confidence': conf,
                                                          'probabilities': probs}}}


def _poster(foreign):
    seen = []

    def post(body, key, timeout=None):
        seen.append(body)
        return _ans('foreign') if body['state'] in foreign else _ans('domestic')
    post.seen = seen
    return post


def _row(guid, title, cat, published='2026-10-28T12:00:00+00:00'):
    return {'guid': guid, 'url': f'https://www.cnbc.com/{guid}', 'title': title, 'category': cat,
            'source': 'CNBC', 'published': published}


ROWS = [_row('m1', 'Bank of Canada hikes rates to curb energy inflation', 'macro'),
        _row('e1', "India's finance minister says market liquidity makes it easier for investors", 'economy'),
        _row('p1', 'Trump drops some Canada tariffs ahead of midterms', 'politics'),
        _row('a1', 'TSMC raises capex as AI chip demand surges', 'ai'),
        _row('i1', 'Samsung Electronics beats on HBM sales', 'industry'),
        _row('g1', 'Bank of Japan holds rates', 'global')]
FOREIGN = {'Bank of Canada hikes rates to curb energy inflation',
           "India's finance minister says market liquidity makes it easier for investors",
           'TSMC raises capex as AI chip demand surges', 'Samsung Electronics beats on HBM sales',
           'Bank of Japan holds rates'}


def test_only_economy_macro_politics_are_asked_and_dropped(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    post = _poster(FOREIGN)
    kept, meta = FN.apply_region_filter([dict(r) for r in ROWS], post=post)
    assert [r['guid'] for r in kept] == ['p1', 'a1', 'i1', 'g1']     # AI·산업·글로벌은 묻지도 빼지도 않는다
    assert {b['state'] for b in post.seen} == {r['title'] for r in ROWS[:3]}
    assert meta['market'] == 'us' and meta['categories'] == ['economy', 'macro', 'politics']
    assert all(b['questions']['region']['instructions'] == L.MARKETS['us']['instructions'] for b in post.seen)
    assert {c['guid'] for c in meta['candidates']} == {'m1', 'e1', 'p1'}


def test_us_definitions_spell_out_the_reader_scope():
    """설계 검토 #6 — 미국의 대외 정책은 국내, 미국을 말하지 않는 해외 중앙은행은 해외(빠진다)."""
    d = L.MARKETS['us']['definitions']
    assert 'US policy toward another country' in d['domestic']
    assert 'does not mention the United States' in d['foreign']


def test_already_saved_story_is_never_dropped(monkeypatch, tmp_path):
    """설계 검토 #1 — 부분 요약 뒤 재실행·--refresh 가 작성 중인 글의 근거를 지우지 않는다."""
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    path = tmp_path / '2026-10-28.json'
    path.write_text(json.dumps({'items': [{'guid': 'm1', 'title': ROWS[0]['title']}]}), encoding='utf-8')
    kept, meta = FN.apply_region_filter([dict(r) for r in ROWS], exempt=FN.guids_in(str(path)),
                                        post=_poster(FOREIGN))
    assert 'm1' in [r['guid'] for r in kept] and 'e1' not in [r['guid'] for r in kept]
    assert next(c for c in meta['candidates'] if c['guid'] == 'm1')['exempt'] is True


def test_no_key_and_crash_leave_todays_result(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    rows = [dict(r) for r in ROWS]
    kept, meta = FN.apply_region_filter(rows, post=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert kept == rows and meta['stopped'] == 'no_key'
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    monkeypatch.setattr(RF, 'run', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('bug')))
    kept, meta = FN.apply_region_filter(rows, post=_poster(FOREIGN))
    assert kept == rows and meta['stopped'] == 'crash:RuntimeError'


def test_global_copy_survives_when_domestic_copy_is_dropped(monkeypatch):
    """설계 검토 #2 — dedupe 전에 거르므로 같은 기사의 글로벌 사본이 남는다(한쪽에만 실린다)."""
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    t = 'Bank of Japan signals rate hike as yen slides'
    rows = [_row('x', t, 'macro'), dict(_row('x', t, 'global'), region='japan')]
    kept, _ = FN.apply_region_filter(rows, post=_poster({t}))
    out = N.dedupe(kept)
    assert [(r['guid'], r['category']) for r in out] == [('x', 'global')]


def test_newest_first_asking_under_deadline(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    old = _row('o', 'Old macro story', 'macro', '2026-10-27T01:00:00+00:00')
    new = _row('n', 'New macro story', 'macro', '2026-10-28T20:00:00+00:00')
    post = _poster(set())
    FN.apply_region_filter([old, new], post=post)
    assert [b['state'] for b in post.seen] == ['New macro story', 'Old macro story']


def test_real_deadline_keeps_received_verdicts(monkeypatch):
    import threading
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    monkeypatch.setattr(RF, 'DEADLINE_SHORT', 0.3)
    gate = threading.Event()
    new = _row('n', 'Bank of Canada hikes rates', 'macro', '2026-10-28T20:00:00+00:00')
    old = _row('o', 'Fed holds rates', 'macro', '2026-10-27T01:00:00+00:00')

    def post(body, key, timeout=None):
        if body['state'] == 'Fed holds rates':
            gate.wait(30)
        return _ans('foreign')
    kept, meta = FN.apply_region_filter([old, new], post=post)
    gate.set()
    assert [r['guid'] for r in kept] == ['o'] and meta['stopped'] == 'deadline'
    assert {c['guid']: c['status'] for c in meta['candidates']} == {'o': 'no_answer', 'n': 'judged'}


def test_saved_payload_guids_feed_the_exemption(tmp_path):
    """부분 요약 뒤 재실행·--refresh 경로가 읽는 그날 파일 모양 그대로."""
    p = tmp_path / 'd.json'
    p.write_text(json.dumps({'report_date': 'x', 'items': [{'guid': 'g1'}, {'guid': 'g2'}],
                             'region_filter': {'mode': 'jev'}}), encoding='utf-8')
    assert FN.guids_in(str(p)) == {'g1', 'g2'} and FN.guids_in(str(tmp_path / 'none.json')) == set()
