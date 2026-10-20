"""쟁점 분석 — 스키마·렌더·게이트·수집 대조. 실제 발행 체인(셸 → 가독성 → 색)을 통과시켜 본다."""

import copy
import re
import json
import os
import sys
import urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, ROOT)

from common import contested as C  # noqa: E402
import collect_contested as Col  # noqa: E402
import contested_build as Bld  # noqa: E402
import contested_local as L  # noqa: E402
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
        {'claim_id': 'c2', 'article_id': a1, 'issue_id': 'i1', 'market_obs': [],
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


TRUST = None


def gate(html, p):
    global TRUST
    if TRUST is None:
        TRUST = G.trusted_styles('us', DATE)
    return C.check(html, p, 'us', DATE, G.transforms(), TRUST)


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
    (lambda p: p['observations'][1].update(value='x' * 200), 'value'),
    (lambda p: p['claims'][0]['evidence'].update(origin='o' * 300), 'origin'),
    (lambda p: p['issues'].append({'issue_id': 'i1', 'issue_ko': '다른 이름'}), 'issue_id 중복'),
    (lambda p: p['observations'][1].update(obs_id='c1'), '겹친다'),
    (lambda p: p['claims'][0].update(market_supported=True, market_obs=['o2'],
                                     credibility='높음', credibility_reason_ko='시장 데이터로 확인'),
     '시장 관측치 참조'),
])
def test_validate_rejects(mut, needle):
    p = payload()
    mut(p)
    rehash(p)
    errs = C.validate(p, 'us', DATE)
    assert any(needle in x for x in errs), errs


def test_hash_mismatch():
    p = payload()
    p['claims'][0]['proposition_ko'] = '바뀐 주장이다'
    assert any('content_hash' in x for x in C.validate(p, 'us', DATE))


def test_iso_date_rejects_paths():
    for bad in ('../../market_data', '2026-13-01', '$(id)', '2026-10-2'):
        with pytest.raises(ValueError):
            C.iso_date(bad)


def test_settled_requires_valid_payload():
    assert not C.settled({'status': 'ok'})
    assert C.settled(payload(), 'us', DATE)
    none = rehash({'schema_version': 1, 'market': 'us', 'span': 'daily', 'report_date': DATE,
                   'status': 'none', 'reason': 'no_conflict'})
    assert C.settled(none) and C.settled_final(none)
    err = rehash(dict(none, status='error', reason='fetch_failed', retryable=True, attempts=1))
    assert not C.settled(err)


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
    assert reg['yields.10Y.bp']['value'] == 3.2


# ── 렌더·게이트(실제 발행 체인) ─────────────────────────────────────────
def test_publish_chain_passes():
    p = payload()
    assert gate(published(p), p) == []


def test_render_escapes_and_is_idempotent():
    p = payload()
    p['claims'][0]['proposition_ko'] = '<script>x</script> 주장이다'
    p['claims'][0]['credibility'], p['claims'][0]['credibility_reason_ko'] = C.credibility(p['claims'][0])
    rehash(p)
    once = R.apply(page(), p)
    assert '<script>x' not in once and '&lt;script&gt;' in once
    assert R.apply(once, p) == once


def _sec(html):
    sec = C._Locate(html).sections[0]
    return html[sec['start']:sec['end']]


@pytest.mark.parametrize('tamper', [
    lambda h, s: h.replace('노조 자체 추산', '노조 공식 집계'),
    lambda h, s: h.replace('<tr data-claim="c1">', '<tr data-claim="c1"><td>x</td></tr><tr data-claim="c1">', 1),
    lambda h, s: h.replace('https://theguardian.com', 'https://evil.example', 1),
    lambda h, s: h.replace(s, f'<template>{s}</template>'),
    lambda h, s: h.replace(s, f'<div hidden>{s}</div>'),
    lambda h, s: h.replace('<section id="contested"', '<section id="contested" class="a" class="b"', 1),
    # 숨긴 정규형 + 보이는 위조본 — 주석·script·noscript·textarea·속성값·CDATA
    lambda h, s: h.replace(s, f'<!--{s}-->' + s.replace('노조 자체 추산', '위성 확인')),
    lambda h, s: h.replace(s, f'<script>var x=`{s}`</script>' + s.replace('노조 자체 추산', '위성 확인')),
    lambda h, s: h.replace(s, f'<noscript>{s}</noscript>' + s.replace('노조 자체 추산', '위성 확인')),
    lambda h, s: h.replace(s, f'<textarea>{s}</textarea>' + s.replace('노조 자체 추산', '위성 확인')),
    lambda h, s: h.replace(s, f'<div data-x="{s.replace(chr(34), "&quot;")}"></div>'
                           + s.replace('노조 자체 추산', '위성 확인')),
    # 외부 CSS 로 숨김
    lambda h, s: h.replace('</body>', '<style>#contested{display:none}</style></body>'),
    # 생략 기록 + 지어낸 분석
    lambda h, s: h.replace(s, '<!--contested-omitted:gate_failed--><p data-essence="structure">지어낸 본질</p>'),
    lambda h, s: h.replace(s, s + '<p data-claim="c9">지어낸 주장</p>'),
])
def test_gate_catches_tampering(tamper):
    p = payload()
    html = published(p)
    bad = tamper(html, _sec(html))
    assert bad != html
    assert gate(bad, p), '위조가 통과했다'


def test_gate_status_rules():
    ok = payload()
    none = rehash({'schema_version': 1, 'market': 'us', 'span': 'daily', 'report_date': DATE,
                   'status': 'none', 'reason': 'no_conflict'})
    err = rehash(dict(none, status='error', reason='fetch_failed', retryable=True, attempts=1))
    assert any('섹션이 있다' in x for x in gate(published(ok), none))
    final = R.apply(page(), none)
    assert C.PENDING not in final and C.MARKER not in final and gate(final, none) == []
    pend = R.apply(page(), None)                      # 미도착 → 자리표시
    assert C.PENDING in pend and gate(pend, None) == [] and gate(pend, err) == []
    assert any('자리표시' in x for x in gate(pend, none))
    assert any('자리표시' in x for x in gate(pend, ok))
    assert any('표지' in x for x in gate(page(), None))     # 표식이 남았다


def test_explicit_omission_passes_once():
    p = payload()
    html = R.apply(published(p), p, omit='gate_failed')
    assert gate(html, p) == []
    with pytest.raises(SystemExit):
        R.apply(html, p)


def test_pending_then_fill():
    p = payload()
    pend = R.apply(page(), None)
    filled = G.transforms()[2](R.apply(pend, p))
    assert gate(filled, p) == []


# ── 수집 ─────────────────────────────────────────────────────────────────
BODY = ('PARIS — The interior ministry said 550,000 people joined protests on Saturday across France. '
        'Unions said more than one million marched. Police arrested 2,400 people after looting.')


def arts3(distinct=True):
    out = []
    for i, (u, s) in enumerate(zip(U, ['The Guardian', 'CNBC', 'The Korea Times'])):
        tail = (f' {s} reporter {i} wrote a different story {i * 7} ' if distinct else ' same text ') * 30
        out.append({'article_id': C.article_id(u), 'url': C.canonical_url(u), 'title': 't', 'source': s,
                    'published_at': '2026-10-19T10:00:00+00:00', 'truncated': False,
                    'body': (f'Story {i}: ' if distinct else '') + BODY + tail})
    return Col.origin_groups(out)


def test_origin_groups_publisher_and_copies():
    assert len({a['origin_group'] for a in arts3(True)}) == 3
    assert len({a['origin_group'] for a in arts3(False)}) == 1
    two_cnbc = arts3(True)
    two_cnbc[2]['source'] = 'CNBC'
    assert len({a['origin_group'] for a in Col.origin_groups(two_cnbc)}) == 2


def test_admit_rejects_garbage_short_and_mismatch():
    long = '<title>France protests turn violent</title>' + '<p>' + 'France protests news. ' * 120 + '</p>'
    assert Col.admit(long, 'France protests turn violent')[1] == 'ok'
    assert Col.admit('<p>' + 'You are using an outdated browser. ' * 80 + '</p>', 'x y')[1] == 'garbage'
    assert Col.admit('<p>short</p>', 'France protests')[1] == 'short'
    assert Col.admit(long.replace('France protests', 'Gyeonggi budget'), 'France protests violence')[1] \
        == 'title_mismatch'


def test_gdelt_cools_down_once_then_throttled():
    calls, slept = [], []

    def opener(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, 'x', {}, None)
    rows, st = Col.gdelt('france protests', None, opener=opener, sleep=slept.append)
    assert rows == [] and st == 'throttled' and len(calls) == 2 and slept == [Col.GDELT_COOLDOWN]


def test_window():
    from datetime import datetime as _dt, timezone as _tz
    cut = _dt(2026, 10, 20, 12, tzinfo=_tz.utc)
    assert Col.in_window('2026-10-19T10:00:00+00:00', cut)
    assert not Col.in_window('2010-01-01T00:00:00+00:00', cut)
    assert not Col.in_window('2026-10-25T00:00:00+00:00', cut)
    assert not Col.in_window(None, cut)


def test_deadline_is_not_swallowed():
    assert not issubclass(Col.Deadline, Exception)


def test_cluster_and_query():
    rows = [{'title': 'France protests turn violent as Macron faces pressure', 'source': 'CNBC'},
            {'title': 'Macron under pressure as France protests spread', 'source': 'Guardian'},
            {'title': 'France protests: Macron vows to keep budget plan', 'source': 'BBC'},
            {'title': 'Nvidia earnings beat estimates', 'source': 'CNBC'}]
    g = Col.cluster(rows)[0]
    assert len(g) == 3 and 'france' in Col.query_of(g) and 'macron' in Col.query_of(g)


# ── 분석 조립 ────────────────────────────────────────────────────────────
def _x(arts, **over):
    a0, a1, a2 = (a['article_id'] for a in arts)
    x = {'topic_ko': '프랑스 시위', 'relevant_articles': [a0, a1, a2],
         'issues': [{'issue_id': 'i1', 'issue_ko': '시위 규모'}],
         'claims': [
             {'claim_id': 'c1', 'article_id': a0, 'issue_id': 'i1', 'proposition_ko': '참가자는 55만 명이다',
              'modality': 'fact', 'speaker_role': '정치', 'speaker_name': '내무부',
              'evidence_kind': 'official_doc', 'evidence_origin': '내무부', 'evidence_desc_ko': '내무부 집계',
              'claim_span': '550,000 people joined protests', 'evidence_span': 'The interior ministry said',
              'market_obs': []},
             {'claim_id': 'c2', 'article_id': a1, 'issue_id': 'i1', 'proposition_ko': '참가자는 100만 명이 넘는다',
              'modality': 'fact', 'speaker_role': '기타', 'speaker_name': '노조',
              'evidence_kind': 'anecdote', 'evidence_origin': '노조', 'evidence_desc_ko': '노조 추산',
              'claim_span': 'more than one million marched', 'evidence_span': 'Unions said more than', 'market_obs': []}],
         'pairs': [{'pair_id': 'p1', 'a': 'c1', 'b': 'c2', 'why_ko': '같은 날 인원이 두 배 차이 난다'}],
         'observations': [
             {'obs_id': 'o1', 'kind': 'market', 'registry_key': 'indices.S&P 500.pct', 'article_id': '',
              'indicator_ko': '', 'entity': '', 'value_text': '99', 'unit': '', 'as_of': '', 'span': ''},
             {'obs_id': 'o2', 'kind': 'article', 'registry_key': '', 'article_id': a2,
              'indicator_ko': '체포 인원', 'entity': '프랑스', 'value_text': '2,400', 'unit': '명',
              'as_of': '2026-10-19', 'span': 'Police arrested 2,400 people'}],
         'analysis': copy.deepcopy(payload()['analysis'])}
    x.update(over)
    return x


REG = {'indices.S&P 500.pct': {'indicator_ko': 'S&P 500 일간 등락률', 'entity': 'S&P 500', 'value': -1.0,
                               'unit': '%', 'as_of': DATE}}


def _verdict(x, **over):
    v = {'pairs': [{'pair_id': q['pair_id'], 'supported_a': True, 'supported_b': True, 'incompatible': True}
                   for q in x['pairs']],
         'claims': [{'claim_id': c['claim_id'], 'evidence_supported': True, 'market_supported': False}
                    for c in x['claims']],
         'observations': [{'obs_id': o['obs_id'], 'supported': True} for o in x['observations']],
         'analysis_items': [{'path': pth, 'grounded': True, 'conditional': True, 'no_advice': True}
                            for pth, _ in Bld.analysis_nodes(x['analysis'])]}
    v.update(over)
    return v


def _bundle(arts):
    return {'status': 'ok', 'gdelt': 'ok', 'registry': REG, 'hosts': {},
            'market_snapshot': {'path': 'data/market_data.json', 'commit': 'abc', 'sha256': 'def'},
            'candidates': [{'cand_id': 'k1', 'query': 'france protests', 'titles': ['t'],
                            'outlets_seen': ['The Guardian', 'CNBC', 'The Korea Times'], 'articles': arts}]}


def _base():
    return {'schema_version': 1, 'market': 'us', 'span': 'daily', 'report_date': DATE, 'status': 'error',
            'reason': 'unknown', 'retryable': True, 'attempts': 1, 'collected_at': 'x', 'cutoff_at': 'x',
            'model': {}, 'prompt_version': C.PROMPT_VERSION, 'market_snapshot': None, 'counts': {},
            'diagnostics': {}, 'event': {'topic_ko': '', 'query': '', 'trigger': []}}


def _fake(x, v):
    def call(prompt, payload_, schema, model, diag=None):
        return x if schema is Bld.EXTRACT_SCHEMA else v
    return call


def _fit_analysis(x):
    an = x['analysis']           # 픽스처 분석을 이 추출의 ID 에 맞춘다
    an['variables'] = [{'var_id': 'v1', 'name_ko': '시위 규모', 'obs': ['o2']},
                       {'var_id': 'v2', 'name_ko': '위험 선호', 'obs': ['o1']}]
    return x


def test_analyze_end_to_end_ok_and_values_from_registry():
    arts = arts3()
    x = _fit_analysis(_x(arts))
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, _verdict(x)))
    assert p['status'] == 'ok', p.get('reason')
    assert C.validate(p, 'us', DATE) == []
    o1 = next(o for o in p['observations'] if o['obs_id'] == 'o1')
    assert o1['value'] == -1.0                        # 모델이 쓴 99 가 아니라 레지스트리 값
    assert all('_span' not in o and 'claim_span' not in json.dumps(p) for o in p['observations'])


def test_invented_span_drops_claim_and_marks_retryable():
    arts = arts3()
    x = _fit_analysis(_x(arts))
    x['claims'][1]['claim_span'] = 'satellite images confirmed two million'
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, _verdict(x)))
    assert p['status'] == 'none' and p['reason'] == 'grounding_failed' and p['retryable']


def test_verifier_rejection_and_duplicate_verdicts():
    arts = arts3()
    x = _fit_analysis(_x(arts))
    v = _verdict(x)
    v['pairs'] = [dict(v['pairs'][0], incompatible=False), v['pairs'][0]]    # 같은 ID 판정 둘
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, v))
    assert p['reason'] == 'verify_rejected' and p['retryable']


def test_duplicate_pair_ids_dropped():
    arts = arts3()
    x = _fit_analysis(_x(arts))
    x['pairs'].append(dict(x['pairs'][0], a='c2', b='c1'))
    _, _, pairs, _ = Bld.ground(x, arts, REG)
    assert pairs == []


def test_article_obs_cannot_confer_market_credibility():
    arts = arts3()
    x = _fit_analysis(_x(arts))
    x['claims'][0]['market_obs'] = ['o2']
    v = _verdict(x)
    v['claims'][0]['market_supported'] = True
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, v))
    c1 = next(c for c in p['claims'] if c['claim_id'] == 'c1')
    assert c1['credibility'] != '높음' and c1['market_obs'] == []


def test_unverified_analysis_is_retryable_with_codes_only():
    arts = arts3()
    x = _fit_analysis(_x(arts))
    v = _verdict(x)
    v['analysis_items'][0]['conditional'] = False
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, v))
    assert p['reason'] == 'analysis_unverified' and p['retryable']
    assert all(re.fullmatch(r'[a-z.\[\]0-9]+:(unverified|dangling)', s) for s in p['problems'])


def test_no_pairs_from_model_is_final_no_conflict():
    arts = arts3()
    x = _fit_analysis(_x(arts, pairs=[]))
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, _verdict(x)))
    assert p['reason'] == 'no_conflict' and not p['retryable']


def test_same_publisher_pair_is_rejected():
    arts = arts3()
    arts[1]['source'] = 'The Guardian'
    arts = Col.origin_groups(arts)
    x = _fit_analysis(_x(arts))
    p = Bld.analyze(_bundle(arts), _base(), call=_fake(x, _verdict(x)))
    assert p['status'] != 'ok'


def test_model_error_is_retryable():
    arts = arts3()

    def boom(*a, **k):
        raise Bld.ModelError('timeout')
    p = Bld.analyze(_bundle(arts), _base(), call=boom)
    assert p['status'] == 'error' and p['retryable']


def test_throttled_without_sources_is_terminal_for_the_day():
    b = _bundle(arts3()[:2])
    b['gdelt'] = 'throttled'
    p = Bld.analyze(b, _base(), call=_fake({}, {}))
    assert p['reason'] == 'gdelt_throttled' and not p['retryable']


def test_claude_cli_parsing():
    class P:
        def __init__(self, out, rc=0):
            self.stdout, self.returncode = out, rc
    ok = json.dumps({'is_error': False, 'subtype': 'success', 'structured_output': {'a': 1},
                     'usage': {'input_tokens': 10, 'output_tokens': 2}})
    diag = {}
    assert Bld.claude('p', {}, {}, 'opus', run=lambda *a, **k: P(ok), diag=diag) == {'a': 1}
    assert diag['tokens'] == {'in': 10, 'out': 2}
    with pytest.raises(Bld.ModelError):
        Bld.claude('p', {}, {}, 'opus', run=lambda *a, **k: P('not json', 1))
    with pytest.raises(Bld.ModelError):
        Bld.claude('p', {}, {}, 'opus', run=lambda *a, **k: P(json.dumps({'is_error': True})))


# ── 로컬 러너 계획 ───────────────────────────────────────────────────────
def test_runner_plan():
    ok = payload()
    none = rehash({'schema_version': 1, 'market': 'us', 'span': 'daily', 'report_date': DATE,
                   'status': 'none', 'reason': 'no_conflict'})
    err = rehash(dict(none, status='error', reason='fetch_failed', retryable=True, attempts=1))
    assert L.plan(None, 'none', DATE) == 'analyze'
    assert L.plan(err, 'pending', DATE) == 'analyze'
    assert L.plan(ok, 'pending', DATE) == 'fill'
    assert L.plan(none, 'pending', DATE) == 'clear'
    assert L.plan(ok, 'section', DATE) == 'skip'
    assert L.plan(None, 'omitted', DATE) == 'skip'           # 발행 증거가 묶였다
    assert L.plan(ok, 'none', DATE) == 'skip'
    assert L.page_state(R.apply(page(), None)) == 'pending'


# ── 루틴 도우미 ─────────────────────────────────────────────────────────
import contested_ready as Rd  # noqa: E402


class _P:
    def __init__(self, rc=0, out=''):
        self.returncode, self.stdout = rc, out


def test_ready_copies_or_reports_missing(tmp_path, capsys):
    out = tmp_path / 'c.json'
    Rd.main(['--date', DATE, '--out', str(out)],
            run=lambda a: _P(0, json.dumps(payload())) if a[1] == 'show' else _P())
    assert json.loads(out.read_text())['status'] == 'ok'
    Rd.main(['--date', DATE, '--out', str(out)], run=lambda a: _P(128) if a[1] == 'show' else _P())
    assert not out.exists() and '미도착' in capsys.readouterr().out


def test_ranker_falls_back_to_score_order():
    def boom(*a, **k):
        raise Bld.ModelError('x')
    assert Bld.ranker(call=boom)([{'cand_id': 'k1'}]) == []
    assert Bld.ranker(call=lambda *a, **k: {'order': ['k2', 'k1']})([]) == ['k2', 'k1']
