"""쟁점 분석 — 스키마·렌더·게이트·수집 대조. 실제 발행 체인(셸 → 가독성 → 색)을 통과시켜 본다."""

import copy
import json
import os
import sys
import urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, ROOT)

from common import contested as C  # noqa: E402
import fetch_contested as F  # noqa: E402
import render_contested as R  # noqa: E402
import check_contested as G  # noqa: E402
from scripts.common import post_shell  # noqa: E402

DATE = '2026-10-20'
U = ['https://www.theguardian.com/world/2026/oct/19/france-protests',
     'https://www.cnbc.com/2026/10/19/france-unrest.html',
     'https://www.koreatimes.co.kr/world/2026/10/france-turmoil']


def payload(**over):
    arts = [{'article_id': C.article_id(u), 'url': C.canonical_url(u), 'title': f'기사 {i}',
             'source': s, 'wire': '', 'published_at': '2026-10-19T10:00:00+00:00', 'seen_at': None,
             'origin_group': C.article_id(u)}
            for i, (u, s) in enumerate(zip(U, ['The Guardian', 'CNBC', 'The Korea Times']))]
    a0, a1, a2 = (a['article_id'] for a in arts)
    claims = [
        {'claim_id': 'c1', 'article_id': a0, 'issue_id': 'i1',
         'proposition_ko': '시위 참가자는 55만 명이었다', 'modality': 'fact', 'speaker_role': '정치',
         'speaker_name': '프랑스 내무부',
         'evidence': {'kind': 'official_doc', 'origin': '내무부 발표', 'desc_ko': '내무부 집계 발표'},
         'market_supported': False},
        {'claim_id': 'c2', 'article_id': a1, 'issue_id': 'i1',
         'proposition_ko': '시위 참가자는 100만 명을 넘었다', 'modality': 'fact', 'speaker_role': '기타',
         'speaker_name': '노조 연합',
         'evidence': {'kind': 'anecdote', 'origin': '노조 주장', 'desc_ko': '노조 자체 추산'},
         'market_supported': False},
    ]
    for c in claims:
        c['credibility'], c['credibility_reason_ko'] = C.credibility(c)
    obs = [{'obs_id': 'o1', 'kind': 'market', 'registry_key': 'indices.S&P 500.pct',
            'indicator_ko': 'S&P 500 일간 등락률', 'entity': 'S&P 500', 'value': -1.25, 'unit': '%',
            'as_of': DATE},
           {'obs_id': 'o2', 'kind': 'article', 'article_id': a2, 'indicator_ko': '체포 인원',
            'entity': '프랑스', 'value': '2,400', 'unit': '명', 'as_of': '2026-10-19'}]
    an = {'structure': {'text_ko': '재정 긴축이 거리 시위로 번지는 속도가 프랑스 국채 위험을 정한다.',
                        'support': ['c1', 'c2']},
          'variables': [{'var_id': 'v1', 'name_ko': '시위 규모', 'obs': ['o2']},
                        {'var_id': 'v2', 'name_ko': '위험 선호', 'obs': ['o1']}],
          'edges': [{'from_var': 'v1', 'to_var': 'v2', 'condition_ko': '체포 인원이 다시 늘면',
                     'direction_ko': '위험 선호가 줄어드는 쪽', 'support': ['o2']}],
          'memo': [{'text_ko': '참가 인원 집계 차이는 정부와 노조의 협상 재료다.', 'support': ['c1', 'c2']},
                   {'text_ko': '체포 인원이 늘면 정책 후퇴 압력이 커진다.', 'support': ['o2']},
                   {'text_ko': '지수 하락은 시위보다 금리에 먼저 반응했다.', 'support': ['o1']}],
          'worry': {'most': [{'text_ko': '긴축안 철회 압력', 'condition_ko': '시위가 주말을 넘기면',
                              'support': ['c2'], 'counter_obs': []}],
                    'moderate': [{'text_ko': '유럽 증시 동반 약세', 'condition_ko': '지수가 이틀 더 밀리면',
                                  'support': ['o1'], 'counter_obs': []}],
                    'unlikely': [{'text_ko': '정부 붕괴', 'condition_ko': '불신임 표결이 필요하다',
                                  'support': ['c1'], 'counter_obs': ['o2']}]}}
    p = {'schema_version': 1, 'market': 'us', 'span': 'daily', 'report_date': DATE, 'status': 'ok',
         'reason': '', 'retryable': False, 'attempts': 1, 'collected_at': 'x', 'cutoff_at': 'x',
         'model': {'extract': 'm', 'verify': 'm'}, 'prompt_version': C.PROMPT_VERSION,
         'market_snapshot': {'path': 'data/market_data.json', 'commit': 'abc', 'sha256': 'def'},
         'counts': {}, 'diagnostics': {},
         'event': {'topic_ko': '프랑스 긴축 반대 시위', 'query': 'france protests', 'trigger': ['attention']},
         'articles': arts,
         'issues': [{'issue_id': 'i1', 'issue_ko': '시위 규모'}],
         'claims': claims,
         'pairs': [{'pair_id': 'p1', 'a': 'c1', 'b': 'c2', 'why_ko': '같은 날 참가 인원이 두 배 차이 난다'}],
         'observations': obs, 'analysis': an}
    p.update(over)
    p['content_hash'] = C.content_hash(p)
    return p


def rehash(p):
    p['content_hash'] = C.content_hash(p)
    return p


def page(section='<!--CONTESTED-->'):
    body = ('<section><div class="card headline-card"><h1>제목</h1><p>본문이다.</p></div></section>\n'
            '<section><h2>오늘의 뉴스</h2><div class="card"><p>뉴스다.</p></div></section>\n'
            f'{section}\n'
            '<section><h2>메모리</h2><div class="card"><p>메모리다.</p></div></section>')
    return post_shell.render('news', DATE, {'title': 't', 'summary': 's'}, body)


def published(p):
    html = R.apply(page(), p)
    return G.transforms()[2](html)


# ── 스키마 ───────────────────────────────────────────────────────────────
def test_fixture_valid():
    assert C.validate(payload(), 'us', DATE) == []


@pytest.mark.parametrize('mut, needle', [
    (lambda p: p.update(report_date='2026-10-19'), 'report_date'),
    (lambda p: p['claims'][0].update(credibility='높음'), '루브릭'),
    (lambda p: p['analysis'].update(memo=p['analysis']['memo'][:2]), 'memo'),
    (lambda p: p['analysis']['structure'].update(text_ko='한 문장이다. 두 문장이다.'), '한 문장'),
    (lambda p: p['analysis']['worry']['unlikely'][0].update(counter_obs=[]), 'counter_obs'),
    (lambda p: p['analysis']['memo'][0].update(support=['zz']), '없는 근거'),
    (lambda p: p['pairs'].append(dict(p['pairs'][0], pair_id='p2')), '중복 쌍'),
    (lambda p: p['articles'].pop(), '독립 출처'),
    (lambda p: p['claims'][0].update(speaker_role='정부'), 'speaker_role'),
])
def test_validate_rejects(mut, needle):
    p = payload()
    mut(p)
    rehash(p)
    assert any(needle in x for x in C.validate(p, 'us', DATE)), C.validate(p, 'us', DATE)


def test_hash_mismatch():
    p = payload()
    p['claims'][0]['proposition_ko'] = '바뀐 주장이다'
    assert any('content_hash' in x for x in C.validate(p, 'us', DATE))


def test_credibility_rubric_caps_article_evidence():
    c = {'evidence': {'kind': 'named_data', 'origin': '통계청'}, 'modality': 'fact', 'speaker_name': 'x'}
    assert C.credibility(c)[0] == '중간'
    assert C.credibility(dict(c, market_supported=True))[0] == '높음'
    assert C.credibility({'evidence': {'kind': 'none'}, 'modality': 'fact'})[0] == '낮음'


def test_registry_fills_values_from_market_data():
    md = {'report_date': DATE, 'indices': {'S&P 500': {'pct': -1.2512, 'last': 6000.1, 'date': DATE}},
          'yields': {'10Y': {'level': 4.1234, 'bp': 3.21, 'date': DATE}}, 'spread_2s10s_bp': 37.5}
    reg = C.market_registry(md)
    assert reg['indices.S&P 500.pct']['value'] == -1.25
    assert reg['yields.10Y.bp'] == {'indicator_ko': '미 국채 10년 일간 변화', 'entity': '10Y',
                                    'value': 3.2, 'unit': 'bp', 'as_of': DATE}


# ── 렌더·게이트(실제 발행 체인) ─────────────────────────────────────────
def test_publish_chain_passes():
    p = payload()
    html = published(p)
    assert C.check(html, p, 'us', DATE, G.transforms()) == []


def test_render_escapes_and_is_idempotent():
    p = payload()
    p['claims'][0]['proposition_ko'] = '<script>x</script> 주장이다'
    p['claims'][0]['credibility'], p['claims'][0]['credibility_reason_ko'] = C.credibility(p['claims'][0])
    rehash(p)
    once = R.apply(page(), p)
    assert '<script>x' not in once and '&lt;script&gt;' in once
    assert R.apply(once, p) == once


@pytest.mark.parametrize('tamper, needle', [
    (lambda h: h.replace('노조 자체 추산', '노조 공식 집계'), '정규형'),
    (lambda h: h.replace('<tr data-claim="c1">', '<tr data-claim="c1"><td>x</td></tr><tr data-claim="c1">', 1), '정규형'),
    (lambda h: h.replace('https://theguardian.com', 'https://evil.example', 1), '정규형'),
    (lambda h: h.replace('<section id="contested"', '<template><section id="contested"', 1)
     .replace('</section>\n<section><h2>메모리', '</section></template>\n<section><h2>메모리', 1), '보이지 않는'),
    (lambda h: h.replace('<section id="contested"', '<div hidden><section id="contested"', 1)
     .replace('</section>\n<section><h2>메모리', '</section></div>\n<section><h2>메모리', 1), '보이지 않는'),
    (lambda h: h.replace('<section id="contested"', '<section id="contested" class="a" class="b"', 1), '중복 속성'),
])
def test_gate_catches_tampering(tamper, needle):
    p = payload()
    html = tamper(published(p))
    errs = C.check(html, p, 'us', DATE, G.transforms())
    assert any(needle in x for x in errs), errs


def test_gate_status_none_forbids_section():
    ok = payload()
    html = published(ok)
    none = rehash({k: ok[k] for k in ('schema_version', 'market', 'span', 'report_date')} |
                  {'status': 'none', 'reason': 'no_conflict'})
    assert any('섹션이 있다' in x for x in C.check(html, none, 'us', DATE))
    clean = R.apply(page(), none)
    assert C.MARKER not in clean and C.check(clean, none, 'us', DATE) == []
    assert C.check(R.apply(page(), None), None, 'us', DATE) == []


def test_gate_leftover_marker_and_missing_section():
    p = payload()
    assert any('표식' in x for x in C.check(page(), p, 'us', DATE))
    stripped = R.apply(page(), None)
    assert any('정확히 하나' in x for x in C.check(stripped, p, 'us', DATE))


def test_explicit_omission_passes_and_is_unique():
    p = payload()
    html = R.apply(published(p), None, omit='gate_failed')
    assert C.check(html, p, 'us', DATE) == []
    with pytest.raises(SystemExit):
        R.apply(html, p)


# ── 수집 대조 ────────────────────────────────────────────────────────────
BODY = ('PARIS — The interior ministry said 550,000 people joined protests on Saturday across France. '
        'Unions said more than one million marched. Police arrested 2,400 people after looting.')


def arts3(distinct=False):
    out = []
    for i, (u, s) in enumerate(zip(U, ['The Guardian', 'CNBC', 'The Korea Times'])):
        tail = f' {s} reporter {i} wrote a different story {i * 7} ' * 30 if distinct else f' {s} extra text ' * 30
        out.append({'article_id': C.article_id(u), 'url': C.canonical_url(u), 'title': 't', 'source': s,
                    '_body': (f'Story {i}: ' if distinct else '') + BODY + tail})
    return F.origin_groups(out)


def test_ground_drops_invented_spans_and_fills_market_values():
    arts = arts3()
    a0, a1 = arts[0]['article_id'], arts[1]['article_id']
    reg = {'indices.S&P 500.pct': {'indicator_ko': 'S&P', 'entity': 'S&P 500', 'value': -1.0,
                                   'unit': '%', 'as_of': DATE}}
    x = {'relevant_articles': [a['article_id'] for a in arts],
         'claims': [
             {'claim_id': 'c1', 'article_id': a0, 'issue_id': 'i1', 'evidence_kind': 'official_doc',
              'claim_span': '550,000 people joined protests', 'evidence_span': 'The interior ministry said'},
             {'claim_id': 'c2', 'article_id': a1, 'issue_id': 'i1', 'evidence_kind': 'anecdote',
              'claim_span': 'satellite images confirmed two million', 'evidence_span': 'Unions said'}],
         'pairs': [{'pair_id': 'p1', 'a': 'c1', 'b': 'c2'}],
         'observations': [
             {'obs_id': 'o1', 'kind': 'market', 'registry_key': 'indices.S&P 500.pct', 'value_text': '99'},
             {'obs_id': 'o2', 'kind': 'article', 'article_id': a0, 'value_text': '2,400', 'as_of': '2026-10-19',
              'span': 'Police arrested 2,400 people'},
             {'obs_id': 'o3', 'kind': 'article', 'article_id': a0, 'value_text': '9', 'as_of': '2026-10-19',
              'span': 'ships pass the strait normally'}]}
    claims, pairs, obs = F.ground(x, arts, reg)
    assert set(claims) == {'c1'} and pairs == []
    assert obs['o1']['value'] == -1.0                 # 모델이 쓴 99 가 아니라 레지스트리 값
    assert 'o2' in obs and 'o3' not in obs


def test_prune_removes_failed_pairs_and_unverified_analysis():
    arts = arts3(distinct=True)
    a0, a1 = arts[0]['article_id'], arts[1]['article_id']
    claims = {'c1': {'claim_id': 'c1', 'article_id': a0, 'issue_id': 'i1', 'proposition_ko': 'x'},
              'c2': {'claim_id': 'c2', 'article_id': a1, 'issue_id': 'i1', 'proposition_ko': 'y'}}
    pairs = [{'pair_id': 'p1', 'a': 'c1', 'b': 'c2'}]
    an = {'structure': {'text_ko': 's', 'support': ['c1']}, 'variables': [], 'edges': [], 'memo': [],
          'worry': {}}
    good = {'pairs': [{'pair_id': 'p1', 'supported_a': True, 'supported_b': True, 'incompatible': True}],
            'claims': [{'claim_id': 'c1', 'evidence_supported': True},
                       {'claim_id': 'c2', 'evidence_supported': True}],
            'analysis_items': [{'path': 'structure', 'grounded': True, 'conditional': True,
                                'no_advice': True}]}
    c, q, o, a, probs = F.prune(dict(claims), pairs, {}, good, an, arts)
    assert q and a is an and not probs
    bad = copy.deepcopy(good)
    bad['pairs'][0]['incompatible'] = False
    c, q, o, a, probs = F.prune(dict(claims), pairs, {}, bad, an, arts)
    assert q == [] and c == {} and a is None      # 쌍이 지워지면 그 근거를 쓰던 분석도 버린다


def test_origin_groups_merge_syndicated_copies():
    arts = arts3()
    assert len({a['origin_group'] for a in arts}) == 1     # 같은 본문 = 한 출처


def test_admit_rejects_garbage_short_and_mismatch():
    long = '<title>France protests turn violent</title>' + '<p>' + 'France protests news. ' * 120 + '</p>'
    assert F.admit(long, 'France protests turn violent')[1] == 'ok'
    assert F.admit('<p>' + 'You are using an outdated browser. ' * 80 + '</p>', 'x y')[1] == 'garbage'
    assert F.admit('<p>short</p>', 'France protests')[1] == 'short'
    assert F.admit(long.replace('France protests', 'Gyeonggi budget'), 'France protests violence')[1] \
        == 'title_mismatch'


def test_gdelt_cools_down_once_then_gives_up():
    calls, slept = [], []

    def opener(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, 'x', {}, None)
    rows, st = F.gdelt('france protests', opener=opener, sleep=slept.append)
    assert rows == [] and st == 'gdelt_http_429' and len(calls) == 2 and slept == [F.GDELT_COOLDOWN]


def test_frozen_rules():
    assert F.frozen({'status': 'ok'})
    assert F.frozen({'status': 'none', 'reason': 'no_conflict'})
    assert not F.frozen({'status': 'none', 'reason': 'analysis_unverified'})
    assert not F.frozen({'status': 'error', 'reason': 'deadline:extract'})


def test_cluster_and_query():
    rows = [{'title': 'France protests turn violent as Macron faces pressure', 'source': 'CNBC'},
            {'title': 'Macron under pressure as France protests spread', 'source': 'Guardian'},
            {'title': 'France protests: Macron vows to keep budget plan', 'source': 'BBC'},
            {'title': 'Nvidia earnings beat estimates', 'source': 'CNBC'}]
    g = F.cluster(rows)[0]
    assert len(g) == 3
    q = F.query_of(g)
    assert 'france' in q and 'macron' in q


# ── 루틴 준비 도우미 ─────────────────────────────────────────────────────
import contested_ready as Rd  # noqa: E402


class _P:
    def __init__(self, rc=0, out='', err=''):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _runner(files, log, dispatched_file=None):
    state = {'dispatched': False}

    def run(args, check=False):
        log.append(args)
        if args[:2] == ['git', 'show']:
            body = files.get('after' if state['dispatched'] else 'before')
            return _P(0, json.dumps(body)) if body else _P(128, '', 'missing')
        if args[:3] == ['gh', 'workflow', 'run']:
            state['dispatched'] = True
            return _P(0)
        if args[:3] == ['gh', 'run', 'list']:
            return _P(0, '42' if state['dispatched'] and '--event' in args else '7')
        if args[0] == 'bash':
            return _P(0)
        return _P(0)
    return run


def test_ready_settled_file_is_copied_without_dispatch(tmp_path):
    log, out = [], tmp_path / 'c.json'
    Rd.main(['--date', DATE, '--out', str(out)], run=_runner({'before': payload()}, log), sleep=lambda s: 0)
    assert json.loads(out.read_text())['status'] == 'ok'
    assert not any(a[:3] == ['gh', 'workflow', 'run'] for a in log)


def test_ready_missing_dispatches_once_and_waits(tmp_path, capsys):
    log, out = [], tmp_path / 'c.json'
    Rd.main(['--date', DATE, '--out', str(out)],
            run=_runner({'before': None, 'after': payload()}, log), sleep=lambda s: 0)
    assert sum(a[:3] == ['gh', 'workflow', 'run'] for a in log) == 1
    assert any(a[0] == 'bash' and a[2] == '42' for a in log)
    assert 'contested: ok' in capsys.readouterr().out


def test_ready_still_missing_reports_and_removes_stale(tmp_path, capsys):
    out = tmp_path / 'c.json'
    out.write_text('{}')
    Rd.main(['--date', DATE, '--out', str(out)], run=_runner({}, []), sleep=lambda s: 0)
    assert not out.exists() and '미도착' in capsys.readouterr().out


def test_ready_retryable_error_triggers_retry():
    assert not Rd.settled({'status': 'error', 'retryable': True, 'attempts': 1})
    assert Rd.settled({'status': 'error', 'retryable': True, 'attempts': 3})
    assert Rd.settled({'status': 'none', 'reason': 'no_conflict'})


def test_pick_falls_back_without_client_and_validates_model_answer():
    g1 = [{'title': 'NatWest staff back to office', 'source': 'BBC'}] * 2
    g2 = [{'title': 'France protests Macron budget', 'source': 'CNBC'}] * 3
    run = F.Run(100)
    assert F.pick(None, [g1, g2], run)[0] is g1

    class Fake:
        def __init__(self, ans):
            self.ans = ans

    orig = F.call
    try:
        F.call = lambda *a, **k: {'choice': 1, 'query': 'France protests Macron', 'reason_ko': 'x'}
        assert F.pick(object(), [g1, g2], run) == (g2, 'France protests Macron')
        F.call = lambda *a, **k: {'choice': 9, 'query': 'x', 'reason_ko': 'x'}
        assert F.pick(object(), [g1, g2], run)[0] is g1 and run.diag['pick'] == 'fallback:invalid'
    finally:
        F.call = orig


def test_gate_rejects_canonical_section_hidden_in_comment():
    p = payload()
    good = published(p)
    import re as _re
    sec = _re.search(r'<section id="contested".*?</section>', good, _re.S).group(0)
    fake = sec.replace('노조 자체 추산', '위성사진으로 확인')
    html = good.replace(sec, f'<!--{sec}-->\n{fake}')
    errs = C.check(html, p, 'us', DATE, G.transforms())
    assert errs, '주석 속 정규형으로 통과하면 안 된다'


def test_duplicate_pair_ids_are_dropped_before_verification():
    arts = arts3(distinct=True)
    a0, a1 = arts[0]['article_id'], arts[1]['article_id']
    x = {'relevant_articles': [a0, a1],
         'claims': [{'claim_id': c, 'article_id': a, 'issue_id': 'i1', 'evidence_kind': 'none',
                     'claim_span': '550,000 people joined protests'} for c, a in (('c1', a0), ('c2', a1))],
         'pairs': [{'pair_id': 'p1', 'a': 'c1', 'b': 'c2'}, {'pair_id': 'p1', 'a': 'c2', 'b': 'c1'}],
         'observations': []}
    claims, pairs, obs = F.ground(x, arts, {})
    assert pairs == []


def test_duplicate_verdicts_count_as_unverified():
    arts = arts3(distinct=True)
    a0, a1 = arts[0]['article_id'], arts[1]['article_id']
    claims = {'c1': {'claim_id': 'c1', 'article_id': a0, 'issue_id': 'i1', 'proposition_ko': 'x'},
              'c2': {'claim_id': 'c2', 'article_id': a1, 'issue_id': 'i1', 'proposition_ko': 'y'}}
    ok = {'pair_id': 'p1', 'supported_a': True, 'supported_b': True, 'incompatible': True}
    bad = dict(ok, incompatible=False)
    v = {'pairs': [bad, ok], 'claims': [{'claim_id': 'c1', 'evidence_supported': True},
                                         {'claim_id': 'c2', 'evidence_supported': True}]}
    _, q, _, _, _ = F.prune(claims, [{'pair_id': 'p1', 'a': 'c1', 'b': 'c2'}], {}, v, {}, arts)
    assert q == []
