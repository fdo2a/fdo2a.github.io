"""국내/해외 판정 섀도 (2026-10-27) — codex 설계 검토 #1-#13 의 수용 조건."""
import json
import os

import pytest

from japan import news as N
from japan import region_shadow as R

S = '2026-10-27'
REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')


def _list_row(guid, title, feed='bus_all', source='ロイター', created='15:00', paid=False):
    return {'guid': guid, 'url': f'https://finance.yahoo.co.jp/news/detail/{guid}', 'title': title,
            'source': source, 'created': created, 'paid': paid, 'feed': feed}


# ── 정규식 재현 (#7) ────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,feed,want', [
    ('ＩＭＦ、財政政策を検討', 'bus_all', 'foreign'),          # 전각 — NFKC 뒤에야 걸린다
    ('ＥＣＢ、金利を据え置き', 'bus_all', 'foreign'),
    ('〔ＮＹ株〕大幅上昇', 'market', 'foreign'),                # 해외 증시 마감
    ('消費者心理が改善', 'world', 'foreign'),                   # world 피드
    ('日銀、米関税の影響を注視', 'bus_all', 'domestic'),         # 일본 표지가 이긴다
    ('米卸大手、業績を上方修正', 'bus_all', 'domestic'),         # 쌀 도매
    ('カナダ中銀、28日に利上げの見通し エネルギー高の波及阻止へ', 'bus_all', 'domestic'),   # 정규식의 맹점(10/27)
    ('ドアダッシュ、食品宅配インスタカート買収へ最終交渉 28日合意も', 'bus_all', 'domestic'),
])
def test_regex_region_matches_production_normalisation(title, feed, want):
    assert R.regex_region(title, feed) == want


def test_regex_region_agrees_with_classify_global():
    for title in ('ＩＭＦ、財政政策を検討', '米国の消費者物価、3.2%上昇', '中国人民銀行、金利を引き下げ'):
        if N.classify(title, 'bus_all') == 'global':
            assert R.regex_region(title, 'bus_all') == 'foreign'


# ── 입력 (#7·#9·#13) ──────────────────────────────────────────────────────
def test_build_input_order_filters_and_immutability():
    rows = [_list_row('a', '日経平均は反発', feed='bus_all'),
            _list_row('a', '日経平均は反発', feed='world'),          # 같은 guid — 첫 피드가 남는다(운영 dedupe)
            _list_row('p', '有料記事', paid=True),
            _list_row('m', 'ビットコイン急騰', source='CoinPost'),
            _list_row('c', 'カナダ中銀、利上げ')]
    before = json.dumps(rows, sort_keys=True)
    got = R.build_input(S, rows, ['c'], commit='abc', captured_at='t')
    assert json.dumps(rows, sort_keys=True) == before
    assert [(r['guid'], r['feed'], r['collector_chosen']) for r in got['rows']] == \
        [('a', 'bus_all', False), ('c', 'bus_all', True)]
    assert got['cohort'] == 'full' and got['commit'] == 'abc'
    assert got['rows'][0]['regex_category'] == N.classify('日経平均は反発', 'bus_all')
    assert got['rows'][1]['key'] == R.title_key('カナダ中銀、利上げ')


def test_bootstrap_is_chosen_only_cohort():
    with open(os.path.join(REPO, 'japan', 'data', 'news', 'daily', f'{S}.json'), encoding='utf-8') as fh:
        daily = json.load(fh)
    got = R.bootstrap_input(S, daily)
    assert got['cohort'] == 'chosen_only'
    assert len(got['rows']) == 12 and all(r['collector_chosen'] for r in got['rows'])


# ── 판정 식별·빠진 판정 (#3·#5) ─────────────────────────────────────────────
def test_missing_follows_title_and_config():
    inp = R.build_input(S, [_list_row('a', '日銀会合'), _list_row('b', '米雇用統計'),
                            _list_row('c', '米雇用統計')], [])      # 같은 제목은 한 번만 묻는다
    cfg = R.config_id('haiku', R.HAIKU_MODEL)
    res = R.empty_result(S)
    R.record(res, 'haiku', cfg, R.title_key('日銀会合'), {'label': 'domestic'})
    assert [r['guid'] for r in R.missing(inp, res, 'haiku', cfg)] == ['b']
    # 제목이 바뀌면 옛 판정은 쓰이지 않는다
    inp2 = R.build_input(S, [_list_row('a', '日銀会合、据え置き')], [])
    assert [r['guid'] for r in R.missing(inp2, res, 'haiku', cfg)] == ['a']
    # 설정이 바뀌면 다른 실험이다
    assert len(R.missing(inp, res, 'haiku', R.config_id('haiku', 'claude-sonnet-5-5'))) == 2


def test_config_id_differs_by_provider_and_model():
    assert R.config_id('haiku', 'x') != R.config_id('jev', 'x') != R.config_id('jev', 'y')


# ── 응답 검증 (#4) ─────────────────────────────────────────────────────────
ROWS = [{'key': 'k0', 'title': 't0'}, {'key': 'k1', 'title': 't1'}]


def test_parse_haiku_ok_and_partial():
    assert R.parse_haiku('{"items":[{"id":"0","label":"foreign"}]}', ROWS) == {'k0': 'foreign'}


@pytest.mark.parametrize('text', [
    'not json', '{"items":{}}', '{"items":[{"id":"7","label":"foreign"}]}',
    '{"items":[{"id":"0","label":"foreign"},{"id":"0","label":"domestic"}]}',
    '{"items":[{"id":"0","label":"japan"}]}', '{"items":[{"id":"x","label":"foreign"}]}'])
def test_parse_haiku_rejects(text):
    with pytest.raises(R.SchemaError):
        R.parse_haiku(text, ROWS)


def _jev(choice='foreign', probs=None, model='jev-1.14.0'):
    probs = probs or {'domestic': 0.1, 'foreign_impact': 0.1, 'foreign': 0.8}
    return {'model': model, 'answers': {'region': {'type': 'choice', 'choice': choice,
                                                   'confidence': 0.7, 'probabilities': probs}}}


def test_parse_jev_ok():
    label, probs, conf, model = R.parse_jev(_jev())
    assert (label, probs['foreign'], conf, model) == ('foreign', 0.8, 0.7, 'jev-1.14.0')


@pytest.mark.parametrize('resp', [
    {}, _jev(choice='japan'), _jev(probs={'domestic': 0.5, 'foreign': 0.5}),
    _jev(probs={'domestic': 0.5, 'foreign_impact': 0.5, 'foreign': 0.5}),
    _jev(probs={'domestic': float('nan'), 'foreign_impact': 0.5, 'foreign': 0.5})])
def test_parse_jev_rejects(resp):
    with pytest.raises(R.SchemaError):
        R.parse_jev(resp)


def test_jev_body_uses_pinned_model_and_same_definitions():
    body = R.jev_body('日銀')
    assert body['model'] == 'jev-1.14.0'
    assert body['questions']['region']['criteria'] == R.DEFINITIONS
    assert all(v in R.HAIKU_SYSTEM for v in R.DEFINITIONS.values())


def test_compare_drops_missing_from_denominator():
    assert R.compare([('a', 'a'), ('a', 'b'), ('a', None), (None, None)]) == \
        {'agree': 1, 'n': 2, 'eligible': 4}


# ── 수집 훅: 캡처는 일간 결과를 바꾸지 않는다 (#13) ─────────────────────────
def _collect(tmp_path, monkeypatch, capture):
    import fetch_japan_news as F
    rows = [_list_row('a', '日経平均は4日ぶり反発、ＡＩ株に買い戻し', created='16:10'),
            _list_row('b', 'カナダ中銀、28日に利上げの見通し', created='15:00'),
            _list_row('c', '日経平均は続伸', created='16:31')]
    monkeypatch.setattr(F, 'harvest', lambda *a, **k: ([dict(r) for r in rows], [], {}))
    monkeypatch.setattr(F, 'harvest_official', lambda *a, **k: ([], [], True))

    def bodies(chosen, *a, **k):
        for it in chosen:
            it['body_chars'], it['published'] = 900, f'{S}T15:00:00+09:00'
        return chosen
    monkeypatch.setattr(F, 'fetch_bodies', bodies)
    monkeypatch.setattr(F, 'summarize_chosen', lambda *a, **k: None)
    monkeypatch.setattr(F, 'capture_shadow', capture)
    return F.collect_daily(S, S, str(tmp_path / 'b'), None, datadir=str(tmp_path))


def test_capture_failure_leaves_daily_payload_identical(tmp_path, monkeypatch):
    import fetch_japan_news as F
    real = F.capture_shadow
    ok = _collect(tmp_path / 'on', monkeypatch, real)

    def boom(*a, **k):
        raise RuntimeError('capture broke')
    broken = _collect(tmp_path / 'off', monkeypatch, boom)
    assert ok['items'] == broken['items'] and ok['complete'] == broken['complete']
    assert ok['notes'] == broken['notes']                  # 섀도 실패는 일간 notes 에도 안 남는다
    path = tmp_path / 'on' / 'news' / 'region_shadow' / 'input' / f'{S}.json'
    inp = json.loads(path.read_text(encoding='utf-8'))
    assert [r['guid'] for r in inp['rows']] == ['a', 'b']   # 16:31 은 컷 밖
    assert [r['collector_chosen'] for r in inp['rows']] == [True, True]
    assert not (tmp_path / 'off' / 'news' / 'region_shadow' / 'input' / f'{S}.json').exists()


# ── CLI: 판정 실행 (#2·#4·#11·#12) ─────────────────────────────────────────
import japan_region_shadow as C  # noqa: E402


def _seed(tmp_path, titles, session=S):
    rows = [_list_row(f'g{i}', t) for i, t in enumerate(titles)]
    inp = R.build_input(session, rows, [])
    p = tmp_path / 'news' / 'region_shadow' / 'input'
    p.mkdir(parents=True, exist_ok=True)
    (p / f'{session}.json').write_text(json.dumps(inp, ensure_ascii=False), encoding='utf-8')
    return inp


class _Block:
    def __init__(self, text):
        self.type, self.text = 'text', text


class _Resp:
    def __init__(self, text, stop='end_turn'):
        self.content, self.stop_reason = [_Block(text)], stop


class FakeHaiku:
    """요청마다 정해진 응답을 낸다. 받은 요청을 기록한다."""

    def __init__(self, answer=None, fail=None):
        self.calls, self.answer, self.fail = [], answer, fail
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        items = json.loads(kw['messages'][0]['content'])
        label = self.answer or 'domestic'
        return _Resp(json.dumps({'items': [{'id': it['id'], 'label': label} for it in items]}))


def test_classify_haiku_records_and_resumes(tmp_path):
    _seed(tmp_path, [f'記事{i}' for i in range(30)])
    fake = FakeHaiku(answer='foreign')
    out = C.classify(str(tmp_path), providers=('haiku',), env={}, haiku_client=fake, now=lambda: 0.0)
    assert out['haiku']['done'] == 30 and len(fake.calls) == 2          # 25 + 5
    kw = fake.calls[0]
    assert kw['output_config']['format']['type'] == 'json_schema'
    assert kw['output_config']['effort'] == 'low' and kw['model'] == R.HAIKU_MODEL
    res = json.loads((tmp_path / 'news' / 'region_shadow' / 'result' / f'{S}.json').read_text())
    cfg = R.config_id('haiku', R.HAIKU_MODEL)
    assert len(res['results']['haiku'][cfg]) == 30
    again = FakeHaiku()
    C.classify(str(tmp_path), providers=('haiku',), env={}, haiku_client=again, now=lambda: 0.0)
    assert again.calls == []                                              # 다 했으면 다시 묻지 않는다


def test_classify_haiku_checkpoints_before_deadline(tmp_path):
    _seed(tmp_path, [f'記事{i}' for i in range(60)])
    t = iter([0.0, 0.0, 10.0])      # 시작 · 묶음1 · 묶음2 — 묶음3 앞에서 마감(999)
    out = C.classify(str(tmp_path), providers=('haiku',), env={}, haiku_client=FakeHaiku(),
                     now=lambda: next(t, 999.0), budgets={'haiku': 100, 'jev': 100})
    assert 0 < out['haiku']['done'] < 60 and out['haiku']['stopped'] == 'deadline'
    res = json.loads((tmp_path / 'news' / 'region_shadow' / 'result' / f'{S}.json').read_text())
    assert len(res['results']['haiku'][R.config_id('haiku', R.HAIKU_MODEL)]) == out['haiku']['done']


def test_classify_without_credentials_makes_no_call(tmp_path):
    _seed(tmp_path, ['日銀会合'])
    out = C.classify(str(tmp_path), providers=('haiku', 'jev'), env={}, haiku_client=None,
                     jev_post=lambda *a: pytest.fail('network'), now=lambda: 0.0)
    assert out['haiku']['stopped'] == 'no_credentials' and out['jev']['stopped'] == 'no_key'


class AuthError(Exception):
    status_code = 401


def test_haiku_auth_failure_does_not_stop_jev(tmp_path):
    _seed(tmp_path, ['日銀会合', '米雇用統計'])
    seen = []

    def post(body, key):
        seen.append(body['state'])
        return _jev(choice='domestic', probs={'domestic': 0.9, 'foreign_impact': 0.05, 'foreign': 0.05})
    out = C.classify(str(tmp_path), providers=('haiku', 'jev'), env={'TYPESAFE_API_KEY': 'TEST_ONLY'},
                     haiku_client=FakeHaiku(fail=AuthError()), jev_post=post, now=lambda: 0.0)
    assert out['haiku']['stopped'] == 'auth' and out['haiku']['done'] == 0
    assert out['jev']['done'] == 2 and seen == ['日銀会合', '米雇用統計']
    res = json.loads((tmp_path / 'news' / 'region_shadow' / 'result' / f'{S}.json').read_text())
    v = res['results']['jev'][R.config_id('jev', R.JEV_MODEL)][R.title_key('日銀会合')]
    assert v['label'] == 'domestic' and v['model'] == 'jev-1.14.0' and v['at']


def test_haiku_schema_error_skips_batch_and_continues(tmp_path):
    _seed(tmp_path, [f'記事{i}' for i in range(30)])

    class Half(FakeHaiku):
        def create(self, **kw):
            self.calls.append(kw)
            if len(self.calls) == 1:
                return _Resp('{"items":[{"id":"99","label":"foreign"}]}')
            return FakeHaiku.create(self, **kw)
    fake = Half()
    fake.calls = []
    out = C.classify(str(tmp_path), providers=('haiku',), env={}, haiku_client=fake, now=lambda: 0.0)
    assert out['haiku']['done'] == 5 and out['haiku']['errors'] == {'schema:id': 1}


def test_haiku_truncated_or_refused_is_an_error(tmp_path):
    _seed(tmp_path, ['日銀会合'])

    class Cut(FakeHaiku):
        def create(self, **kw):
            self.calls.append(kw)
            return _Resp('{"items":[', stop='max_tokens')
    fake = Cut()
    out = C.classify(str(tmp_path), providers=('haiku',), env={}, haiku_client=fake, now=lambda: 0.0)
    assert out['haiku']['done'] == 0 and out['haiku']['errors'] == {'stop:max_tokens': 1}


def test_jev_secret_never_reaches_disk_or_log(tmp_path, capsys):
    _seed(tmp_path, ['日銀会合'])

    def post(body, key):
        raise C.JevHTTPError(500)
    C.classify(str(tmp_path), providers=('jev',), env={'TYPESAFE_API_KEY': 'TEST_ONLY_SECRET'},
               jev_post=post, now=lambda: 0.0)
    out = capsys.readouterr()
    assert 'TEST_ONLY_SECRET' not in out.out + out.err
    for root, _, files in os.walk(tmp_path):
        for f in files:
            assert 'TEST_ONLY_SECRET' not in open(os.path.join(root, f), encoding='utf-8').read()


def test_jev_redirect_is_refused_and_bearer_not_forwarded():
    import urllib.request
    handler = C._NoRedirect()
    req = urllib.request.Request('https://api.typesafe.ai/v1/systemone',
                                 headers={'Authorization': 'Bearer TEST_ONLY'})
    with pytest.raises(C.JevHTTPError) as e:
        handler.redirect_request(req, None, 302, 'Found', {}, 'https://elsewhere.invalid/x')
    assert e.value.code == 302


def test_jev_url_is_fixed_https():
    assert C.JEV_URL == 'https://api.typesafe.ai/v1/systemone'


def test_jev_auth_stops_provider(tmp_path):
    _seed(tmp_path, ['a', 'b', 'c'])
    calls = []

    def post(body, key):
        calls.append(1)
        raise C.JevHTTPError(401)
    out = C.classify(str(tmp_path), providers=('jev',), env={'TYPESAFE_API_KEY': 'k'},
                     jev_post=post, now=lambda: 0.0)
    assert out['jev']['stopped'] == 'auth' and len(calls) == 1


def test_corrupt_input_is_skipped_not_fatal(tmp_path):
    _seed(tmp_path, ['日銀会合'], session='2026-10-28')
    bad = tmp_path / 'news' / 'region_shadow' / 'input' / '2026-10-27.json'
    bad.write_text('{not json', encoding='utf-8')
    out = C.classify(str(tmp_path), providers=('haiku',), env={}, haiku_client=FakeHaiku(), now=lambda: 0.0)
    assert out['haiku']['done'] == 1 and out['bad_inputs'] == ['2026-10-27']


# ── 보고 (#9·#10) ──────────────────────────────────────────────────────────
def test_report_stages_on_real_1027(tmp_path):
    with open(os.path.join(REPO, 'japan', 'data', 'news', 'daily', f'{S}.json'), encoding='utf-8') as fh:
        daily = json.load(fh)
    (tmp_path / 'news' / 'daily').mkdir(parents=True)
    (tmp_path / 'news' / 'daily' / f'{S}.json').write_text(json.dumps(daily, ensure_ascii=False))
    inp = R.bootstrap_input(S, daily)
    (tmp_path / 'news' / 'region_shadow' / 'input').mkdir(parents=True)
    (tmp_path / 'news' / 'region_shadow' / 'input' / f'{S}.json').write_text(json.dumps(inp, ensure_ascii=False))
    html_dir = tmp_path / 'site' / 'japan' / 'daily'
    html_dir.mkdir(parents=True)
    with open(os.path.join(REPO, 'japan', 'daily', f'{S}.html'), encoding='utf-8') as fh:
        (html_dir / f'{S}.html').write_text(fh.read(), encoding='utf-8')
    rep = C.build_report(str(tmp_path), html_root=str(tmp_path / 'site'))
    st = rep['stages']
    assert (st['collector_chosen'], st['summary_usable'], st['published']) == (12, 6, 5)
    assert rep['coverage']['haiku']['done'] == 0 and rep['coverage']['haiku']['missing'] == 12
    assert rep['cohorts'] == {'chosen_only': 1}
