#!/usr/bin/env python3
"""쟁점 분석 — 기사끼리 충돌하는 주장만 추려 본질과 걱정의 크기로 정리한 선택 섹션의 순수 로직.

2026-10-21 사용자 지시: 「기존의 뉴스 정리 방식은 그대로 진행하되, 세간의 주목을 받고 있는
내용이라던가 서로 상충되는 부분이 많은 주제만 저 방식대로 추가로 정리해서 레포트에 반영해」.
방식 = 충돌 주장 비교표 → 주장 평가표(발언 주체·실물 데이터·신빙성) → 본질 ①-④ → 걱정 3단계.

**누가 무엇을 쓰는가.** 기사 본문과 판단이 필요한 일은 전부 Actions(`fetch_contested.py`)가
한다 — 클라우드 루틴은 금융·언론 호스트에 닿지 못하고, 루틴이 손으로 쓴 판단은 근거를 대조할
방법이 없다. 루틴은 표식 한 줄(`MARKER`)만 쓰고, 섹션 전체는 `render()` 가 커밋된 JSON 에서
찍는다. 게이트(`check()`)는 같은 JSON 으로 다시 찍어 최종 문서와 대조한다.

**이 모듈이 증명하지 못하는 것.** 주장·근거·관측치가 원문에 있다는 것(span 대조)과 두 주장이
양립하지 않는다는 것(검증 호출)은 수집 단계가 본문을 버리기 전에 확인했다. 여기서는 그 결과가
스키마대로 왔는지, 발행본이 그것과 한 글자도 다르지 않은지까지만 본다. 인과 해석이 맞는지,
예측을 하지 않았는지는 검증 호출의 판정이지 정규식이 증명할 수 있는 것이 아니다.

Pure — 네트워크 없음. 설계 근거: `docs/superpowers/specs/2026-10-21-contested-analysis-design.md`.
"""

import hashlib
import html as _html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

SCHEMA_VERSION = 1
PROMPT_VERSION = '2026-10-21.1'
MARKER = '<!--CONTESTED-->'
SECTION_ID = 'contested'
OMIT_RE = re.compile(r'<!--contested-omitted:([a-z_]+)-->')
PENDING = '<!--contested-pending-->'     # 결과가 아직 없을 때 발행본에 남기는 자리 — 로컬 러너가 채운다

MARKETS = ('us',)                 # 1단계. kr 은 출처 어댑터(네이버 검색 API)가 붙을 때 연다
SPANS = ('daily',)                # 주간은 2단계 — 일간 ok 파일의 결정적 연대기
STATUSES = ('ok', 'none', 'error')
# 동결되는 none — 그날 다시 돌려도 결과가 같은 「편집상 결론」. 나머지는 재시도할 수 있다.
FINAL_NONE = ('no_candidate', 'insufficient_sources', 'no_conflict', 'below_threshold')
MAX_ATTEMPTS = 3

SPEAKER_ROLES = ('정치', '군', '시장', '전문가', '기타')
MODALITIES = ('fact', 'forecast', 'allegation', 'opinion')
EVIDENCE_KINDS = ('named_data', 'official_doc', 'observation', 'anecdote', 'none')
EVIDENCE_KO = {'named_data': '공표 통계·데이터', 'official_doc': '공식 문서·발표',
               'observation': '현장 관측', 'anecdote': '일화·전언', 'none': '제시 없음'}
DATA_KO = {'named_data': '있음', 'official_doc': '있음', 'observation': '있음',
           'anecdote': '일부', 'none': '없음'}
MODALITY_KO = {'fact': '사실 주장', 'forecast': '전망', 'allegation': '의혹 제기', 'opinion': '견해'}
WORRY_TIERS = (('most', '가장 걱정해야 할 것'),
               ('moderate', '걱정하되 공포는 불필요한 것'),
               ('unlikely', '사실상 가능성이 낮은 것'))

LIMITS = {'value': 40, 'unit': 12, 'entity': 40, 'origin': 60, 'query': 80,
          'proposition_ko': 90, 'evidence_desc_ko': 70, 'why_ko': 90, 'issue_ko': 40,
          'topic_ko': 40, 'text_ko': 220, 'condition_ko': 120, 'name_ko': 30,
          'indicator_ko': 40, 'speaker_name': 40, 'direction_ko': 60}
MIN_ORIGINS = 3                   # 최종 기사의 독립 출처(신디케이션 묶음) 하한
MIN_PAIRS = 2                     # 「상충이 많은」 트리거 — 검증된 충돌 쌍 수(구현 검토 3차)
ID_RE = {'claim': r'c\d{1,3}', 'issue': r'i\d{1,3}', 'pair': r'p\d{1,3}', 'obs': r'o\d{1,3}',
         'var': r'v\d{1,3}'}


def id_ok(kind, value):
    """모델이 정한 ID 는 짧은 정해진 꼴만 — 본문을 ID 칸에 실어 공개하는 길을 막는다(3차 P1)."""
    return isinstance(value, str) and re.fullmatch(ID_RE[kind], value) is not None
ATTENTION_ORIGINS = 5             # 「세간의 주목」 트리거 — 후보 사건의 독립 출처 수

# ── 시장 관측치 레지스트리 (US) ───────────────────────────────────────────
# 모델은 열쇠만 고른다. 값·단위·기준일은 코드가 `market_data.json` 에서 채운다(N01·N13):
# 모델이 옮긴 숫자는 지어낸 숫자와 구분되지 않는다.
_KO = {'Nasdaq': '나스닥', 'S&P 500': 'S&P 500', 'Dow': '다우', 'Russell 2000': '러셀 2000',
       'DXY': '달러인덱스', 'USD/KRW': '원·달러', 'USD/JPY': '엔·달러', 'EUR/USD': '유로·달러',
       'WTI': 'WTI 유가', 'Brent': '브렌트유', 'Natural Gas': '천연가스', 'Gold': '금',
       '2Y': '미 국채 2년', '5Y': '미 국채 5년', '10Y': '미 국채 10년', '30Y': '미 국채 30년'}


def market_registry(md):
    """{key: observation} — 발행에 쓸 수 있는 시장 관측치. 없는 칸은 만들지 않는다."""
    out = {}
    for group in ('indices', 'fx', 'commodities'):
        for name, row in (md.get(group) or {}).items():
            if name not in _KO or not isinstance(row, dict):
                continue
            if isinstance(row.get('pct'), (int, float)):
                out[f'{group}.{name}.pct'] = {
                    'indicator_ko': f'{_KO[name]} 일간 등락률', 'entity': name,
                    'value': round(row['pct'], 2), 'unit': '%', 'as_of': row.get('date')}
            if isinstance(row.get('last'), (int, float)):
                out[f'{group}.{name}.last'] = {
                    'indicator_ko': f'{_KO[name]} 종가', 'entity': name,
                    'value': round(row['last'], 2), 'unit': '', 'as_of': row.get('date')}
    for name, row in (md.get('yields') or {}).items():
        if name not in _KO or not isinstance(row, dict):
            continue
        if isinstance(row.get('level'), (int, float)):
            out[f'yields.{name}.level'] = {
                'indicator_ko': f'{_KO[name]} 금리', 'entity': name,
                'value': round(row['level'], 3), 'unit': '%', 'as_of': row.get('date')}
        if isinstance(row.get('bp'), (int, float)):
            out[f'yields.{name}.bp'] = {
                'indicator_ko': f'{_KO[name]} 일간 변화', 'entity': name,
                'value': round(row['bp'], 1), 'unit': 'bp', 'as_of': row.get('date')}
    if isinstance(md.get('spread_2s10s_bp'), (int, float)):
        out['spread_2s10s_bp'] = {'indicator_ko': '미 국채 2년-10년 스프레드', 'entity': '2s10s',
                                  'value': round(md['spread_2s10s_bp'], 1), 'unit': 'bp',
                                  'as_of': md.get('report_date')}
    return {k: v for k, v in out.items() if v.get('as_of')}


# ── 식별자·해시 ───────────────────────────────────────────────────────────
_TRACKING = re.compile(r'^(utm_|guccounter|guce_|ref$|src$|cmpid$|tsrc$|\.tsrc$)')


def canonical_url(url):
    p = urlsplit((url or '').strip())
    if p.scheme not in ('http', 'https') or not p.netloc:
        return None
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunsplit(('https', p.netloc.lower().removeprefix('www.'), p.path.rstrip('/') or '/',
                       urlencode(q), ''))


def article_id(url):
    c = canonical_url(url)
    return 'a' + hashlib.sha1(c.encode()).hexdigest()[:10] if c else None


def content_hash(payload):
    """`content_hash` 를 뺀 정렬 JSON 의 sha256 앞 16자리 — 렌더에 영향을 주는 모든 것이 들어간다."""
    body = {k: v for k, v in payload.items() if k != 'content_hash'}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def iso_date(s):
    """argparse type — 실제 달력 날짜만. 경로·셸에 들어가는 값이다(구현 검토 P1)."""
    import datetime as _dt
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s or ''):
        raise ValueError(f'날짜 형식이 아니다: {s!r}')
    _dt.date.fromisoformat(s)
    return s


def settled(p, market=None, date=None):
    """다시 돌리지 않을 결과인가 — 스키마·해시를 통과한 것만(구현 검토 P2)."""
    if not p or validate(p, market, date):
        return False
    if p['status'] == 'ok' or settled_final(p):
        return True
    return not p.get('retryable', True) or p.get('attempts', 0) >= MAX_ATTEMPTS


def settled_final(p):
    return bool(p) and p.get('status') == 'none' and p.get('reason') in FINAL_NONE


def ws(text):
    """span 대조용 정규화 — 공백·따옴표 모양만 맞춘다. 낱말은 건드리지 않는다."""
    t = _html.unescape(text or '')
    t = t.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return re.sub(r'\s+', ' ', t).strip().lower()


def span_in(span, body):
    s = ws(span)
    return len(s) >= 12 and s in ws(body)


# ── 신빙성 루브릭 (N03) ───────────────────────────────────────────────────
def credibility(claim):
    """(등급, 사유). 기사가 전한 근거만으로는 「중간」까지 — 우리가 직접 본 것이 아니다.

    「높음」은 우리가 가진 시장 데이터(레지스트리 관측치)로 검증 호출이 그 주장을 지지한다고
    판정한 경우뿐이다. 같은 발표를 두 매체가 전한 것은 교차 확인이 아니다.
    """
    ev = claim.get('evidence') or {}
    kind = ev.get('kind')
    if claim.get('market_supported') and kind != 'none':
        return '높음', '시장 데이터로 확인'
    if kind in ('anecdote', 'none') or (claim.get('modality') == 'allegation'
                                        and not claim.get('speaker_name')):
        return '낮음', f"근거 {EVIDENCE_KO.get(kind, '제시 없음')}"
    origin = ev.get('origin') or '출처 미상'
    return '중간', f'기사가 전한 {EVIDENCE_KO[kind]}({origin}) · 원자료 미확인'


# ── 스키마 검증 ───────────────────────────────────────────────────────────
def _str(v, field, errs, where, limit=None, empty_ok=False):
    if not isinstance(v, str) or (not empty_ok and not v.strip()):
        errs.append(f'{where}.{field}: 빈 값이거나 문자열이 아니다')
        return
    lim = limit or LIMITS.get(field)
    if lim and len(v) > lim:
        errs.append(f'{where}.{field}: {len(v)}자 > {lim}자')


def _hangul(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum('가' <= c <= '힣' for c in letters) / len(letters) >= 0.5


def validate(p, market=None, date=None):
    """위반 목록(빈 목록 = 통과). 수집 저장·렌더·게이트 세 곳이 같은 함수를 쓴다.

    중첩 구조가 깨진 입력(문자열 자리에 객체 등)도 예외 없이 위반으로 돌려준다(4차 P2).
    """
    try:
        return _validate(p, market, date)
    except (AttributeError, TypeError, KeyError, ValueError):
        return ['구조가 깨졌다']


def _validate(p, market=None, date=None):
    errs = []
    if not isinstance(p, dict):
        return ['페이로드가 객체가 아니다']
    if p.get('schema_version') != SCHEMA_VERSION:
        errs.append(f"schema_version {p.get('schema_version')!r} != {SCHEMA_VERSION}")
    if p.get('market') not in MARKETS:
        errs.append(f"market {p.get('market')!r} 은 열려 있지 않다")
    if market and p.get('market') != market:
        errs.append(f"market {p.get('market')!r} != 기대 {market!r}")
    if p.get('span') not in SPANS:
        errs.append(f"span {p.get('span')!r}")
    if date and p.get('report_date') != date:
        errs.append(f"report_date {p.get('report_date')!r} != 기대 {date!r}")
    st = p.get('status')
    if st not in STATUSES:
        errs.append(f'status {st!r}')
        return errs
    if p.get('content_hash') != content_hash(p):
        errs.append('content_hash 가 내용과 맞지 않는다')
    if st != 'ok':
        if not p.get('reason'):
            errs.append(f'status {st} 인데 reason 이 없다')
        if p.get('claims') or p.get('analysis'):
            errs.append(f'status {st} 인데 주장·분석이 들어 있다')
        return errs
    return errs + _validate_ok(p)


def _validate_ok(p):
    errs = []
    ev = p.get('event') or {}
    _str(ev.get('topic_ko'), 'topic_ko', errs, 'event')
    trig = ev.get('trigger')
    if not isinstance(trig, list) or not trig or not set(trig) <= {'attention', 'conflict'}:
        errs.append(f'event.trigger {trig!r}')

    arts = p.get('articles') or []
    aids = {}
    for i, a in enumerate(arts):
        w = f'articles[{i}]'
        if a.get('article_id') != article_id(a.get('url')):
            errs.append(f'{w}: article_id 가 정규 URL 과 맞지 않는다')
        for f in ('title', 'source', 'origin_group'):
            _str(a.get(f), f, errs, w, limit=300)
        aids[a.get('article_id')] = a
    if len(aids) != len(arts):
        errs.append('article_id 중복')
    origins = {a.get('origin_group') for a in arts}
    if len(origins) < MIN_ORIGINS:
        errs.append(f'독립 출처 {len(origins)}곳 < {MIN_ORIGINS}')

    issues = {i.get('issue_id'): i for i in p.get('issues') or []}
    if len(issues) != len(p.get('issues') or []):
        errs.append('issue_id 중복')
    for kind, rows, key in (('issue', p.get('issues'), 'issue_id'), ('claim', p.get('claims'), 'claim_id'),
                            ('pair', p.get('pairs'), 'pair_id'), ('obs', p.get('observations'), 'obs_id'),
                            ('var', (p.get('analysis') or {}).get('variables'), 'var_id')):
        bad = [r.get(key) for r in rows or [] if not id_ok(kind, r.get(key))]
        if bad:
            errs.append(f'{key} 꼴이 아니다 ({len(bad)}개)')
    if isinstance(trig, list) and not ('attention' in trig or len(p.get('pairs') or []) >= MIN_PAIRS):
        errs.append('트리거 미달 — 주목(매체 ≥5) 또는 검증된 충돌 ≥2')
    _str(ev.get('query'), 'query', errs, 'event', empty_ok=True)
    for iid, i in issues.items():
        _str(i.get('issue_ko'), 'issue_ko', errs, f'issues[{iid}]')

    claims = {}
    for c in p.get('claims') or []:
        w = f"claims[{c.get('claim_id')}]"
        if c.get('claim_id') in claims:
            errs.append(f'{w}: 중복 ID')
        claims[c.get('claim_id')] = c
        if c.get('article_id') not in aids:
            errs.append(f'{w}: 없는 기사 {c.get("article_id")!r}')
        if c.get('issue_id') not in issues:
            errs.append(f'{w}: 없는 쟁점 {c.get("issue_id")!r}')
        if c.get('speaker_role') not in SPEAKER_ROLES:
            errs.append(f'{w}: speaker_role {c.get("speaker_role")!r}')
        if c.get('modality') not in MODALITIES:
            errs.append(f'{w}: modality {c.get("modality")!r}')
        _str(c.get('proposition_ko'), 'proposition_ko', errs, w)
        _str(c.get('speaker_name'), 'speaker_name', errs, w, empty_ok=True)
        e = c.get('evidence') or {}
        if e.get('kind') not in EVIDENCE_KINDS:
            errs.append(f'{w}: evidence.kind {e.get("kind")!r}')
        _str(e.get('desc_ko'), 'evidence_desc_ko', errs, w)
        _str(e.get('origin'), 'origin', errs, w, empty_ok=True)
        if c.get('market_supported') and not any(
                (o.get('kind') == 'market') for o in (p.get('observations') or [])
                if o.get('obs_id') in (c.get('market_obs') or [])):
            errs.append(f'{w}: 시장 확인인데 시장 관측치 참조가 없다')
        if (c.get('credibility'), c.get('credibility_reason_ko')) != credibility(c):
            errs.append(f'{w}: 신빙성이 루브릭과 다르다')
        for f in ('proposition_ko', ):
            if isinstance(c.get(f), str) and not _hangul(c[f]):
                errs.append(f'{w}.{f}: 한국어가 아니다')

    pairs = p.get('pairs') or []
    if not pairs:
        errs.append('검증된 충돌 쌍이 없다')
    used, seen_pairs = set(), set()
    for q in pairs:
        w = f"pairs[{q.get('pair_id')}]"
        a, b = q.get('a'), q.get('b')
        if a not in claims or b not in claims:
            errs.append(f'{w}: 없는 주장 참조')
            continue
        if claims[a]['issue_id'] != claims[b]['issue_id']:
            errs.append(f'{w}: 두 주장의 쟁점이 다르다')
        oa = aids.get(claims[a]['article_id'], {}).get('origin_group')
        ob = aids.get(claims[b]['article_id'], {}).get('origin_group')
        if oa == ob:
            errs.append(f'{w}: 같은 출처끼리의 충돌')
        key = frozenset((a, b))
        if key in seen_pairs:
            errs.append(f'{w}: 중복 쌍')
        seen_pairs.add(key)
        _str(q.get('why_ko'), 'why_ko', errs, w)
        used |= {a, b}
    if set(claims) - used:
        errs.append(f'쌍에 속하지 않은 주장 {sorted(set(claims) - used)}')
    if set(issues) - {c['issue_id'] for c in claims.values()}:
        errs.append('주장이 없는 쟁점')

    obs = {}
    for o in p.get('observations') or []:
        w = f"observations[{o.get('obs_id')}]"
        obs[o.get('obs_id')] = o
        if o.get('kind') == 'market':
            if not o.get('registry_key'):
                errs.append(f'{w}: 시장 관측치에 registry_key 가 없다')
        elif o.get('kind') == 'article':
            if o.get('article_id') not in aids:
                errs.append(f'{w}: 없는 기사')
        else:
            errs.append(f'{w}: kind {o.get("kind")!r}')
        _str(o.get('indicator_ko'), 'indicator_ko', errs, w)
        _str(o.get('entity') or '', 'entity', errs, w, empty_ok=True)
        _str(o.get('unit') or '', 'unit', errs, w, empty_ok=True)
        val = o.get('value')
        if isinstance(val, str):
            _str(val, 'value', errs, w)
        elif not isinstance(val, (int, float)) or isinstance(val, bool):
            errs.append(f'{w}: 값이 없다')
        if not re.match(r'\d{4}-\d{2}-\d{2}', str(o.get('as_of') or '')):
            errs.append(f'{w}: 기준일이 날짜가 아니다')
    if p.get('observations') and p.get('market_snapshot') is None and \
            any(o.get('kind') == 'market' for o in obs.values()):
        errs.append('시장 관측치가 있는데 market_snapshot 이 없다')

    vids = {v.get('var_id') for v in (p.get('analysis') or {}).get('variables') or []}
    if (set(claims) & set(obs)) or (set(claims) & vids) or (set(obs) & vids):
        errs.append('주장·관측치·변수 ID 가 겹친다')
    errs += _validate_analysis(p.get('analysis'), set(claims), obs)
    return errs


def _support_ok(sup, claims, obs, where, errs, need=1):
    if not isinstance(sup, list) or len(sup) < need:
        errs.append(f'{where}: 근거 참조 {need}개 이상 필요')
        return
    bad = [s for s in sup if s not in claims and s not in obs]
    if bad:
        errs.append(f'{where}: 없는 근거 {bad}')


def _validate_analysis(an, claims, obs):
    errs = []
    if not isinstance(an, dict):
        return ['analysis 가 없다']
    st = an.get('structure') or {}
    _str(st.get('text_ko'), 'text_ko', errs, 'structure')
    if isinstance(st.get('text_ko'), str) and len(re.findall(r'다\.', st['text_ko'])) != 1:
        errs.append('structure: 정확히 한 문장(「-다.」 하나)이어야 한다')
    _support_ok(st.get('support'), claims, obs, 'structure', errs)
    vs = an.get('variables') or []
    if not 1 <= len(vs) <= 3:
        errs.append(f'variables {len(vs)}개 — 1-3개')
    vids = set()
    for v in vs:
        w = f"variables[{v.get('var_id')}]"
        vids.add(v.get('var_id'))
        _str(v.get('name_ko'), 'name_ko', errs, w)
        if not v.get('obs') or any(o not in obs for o in v['obs']):
            errs.append(f'{w}: 관측치 참조가 없거나 없는 관측치')
    edges = an.get('edges') or []
    if not edges:
        errs.append('edges 가 없다 — 작동 방식은 변수 간 조건부 관계다')
    for i, ed in enumerate(edges):
        w = f'edges[{i}]'
        if ed.get('from_var') not in vids or ed.get('to_var') not in vids | {'outcome'}:
            errs.append(f'{w}: 없는 변수')
        _str(ed.get('condition_ko'), 'condition_ko', errs, w)
        _str(ed.get('direction_ko'), 'direction_ko', errs, w)
        _support_ok(ed.get('support'), claims, obs, w, errs)
    memo = an.get('memo') or []
    if len(memo) != 3:
        errs.append(f'memo {len(memo)}개 — 정확히 3개')
    for i, m in enumerate(memo):
        _str(m.get('text_ko'), 'text_ko', errs, f'memo[{i}]')
        _support_ok(m.get('support'), claims, obs, f'memo[{i}]', errs)
    worry = an.get('worry') or {}
    for tier, _ in WORRY_TIERS:
        items = worry.get(tier) or []
        if not items:
            errs.append(f'worry.{tier} 가 비었다')
        for i, it in enumerate(items):
            w = f'worry.{tier}[{i}]'
            _str(it.get('text_ko'), 'text_ko', errs, w)
            _str(it.get('condition_ko'), 'condition_ko', errs, w)
            _support_ok(it.get('support'), claims, obs, w, errs)
            if tier == 'unlikely':
                co = it.get('counter_obs') or []
                if not co or any(o not in obs for o in co):
                    errs.append(f'{w}: 현재 반대 관측치(counter_obs)가 있어야 한다')
    return errs


# ── 렌더 ─────────────────────────────────────────────────────────────────
def e(text):
    return _html.escape(str(text), quote=True)


def _date_ko(iso):
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', iso or '')
    return f'{int(m.group(2))}월 {int(m.group(3))}일' if m else ''


def _obs_text(o):
    v = o['value']
    unit = o.get('unit') or ''
    sep = '' if unit in ('%', 'bp', '') else ' '
    return f"{o['indicator_ko']} {v}{sep}{unit} ({_date_ko(o['as_of'])})"


def render(p):
    """정규 섹션 HTML. 모든 문자열은 이스케이프, 링크는 http(s) 만."""
    arts = {a['article_id']: a for a in p['articles']}
    claims = {c['claim_id']: c for c in p['claims']}
    issues = {i['issue_id']: i for i in p['issues']}
    obs = {o['obs_id']: o for o in p.get('observations') or []}
    an = p['analysis']
    ev = p['event']
    names = {v['var_id']: v['name_ko'] for v in an['variables']}
    names['outcome'] = '결과'

    order = []
    for q in p['pairs']:
        for cid in (q['a'], q['b']):
            if cid not in order:
                order.append(cid)
    first = {cid: i for i, cid in enumerate(order)}
    rank = {iid: i for i, iid in enumerate(issues)}
    order = sorted(order, key=lambda cid: (rank[claims[cid]['issue_id']], first[cid]))

    trig = []
    if 'attention' in ev['trigger']:
        trig.append('여러 매체가 동시에 다룬 주제')
    if 'conflict' in ev['trigger']:
        trig.append('기사 사이에 엇갈리는 주장이 많은 주제')
    n_origin = len({a['origin_group'] for a in p['articles']})

    out = [f'<section id="{SECTION_ID}" data-contested="{e(p["content_hash"])}">',
           f'<h2>쟁점 분석 — {e(ev["topic_ko"])}</h2>',
           '<div class="card">',
           f'<p class="caption">{e(" · ".join(trig))} · 독립 출처 {n_origin}곳 · '
           f'검증된 충돌 {len(p["pairs"])}건</p>',
           '<h3>서로 충돌하는 주장</h3>',
           '<div class="tbl-scroll"><table><thead><tr><th>쟁점</th><th>주장</th><th>출처</th>'
           '<th>근거</th></tr></thead><tbody>']
    for cid in order:
        c, a = claims[cid], arts[claims[cid]['article_id']]
        when = _date_ko(a.get('published_at') or a.get('seen_at'))
        src = f'{a["source"]} · {when}' if when else a['source']
        out.append(
            f'<tr data-claim="{e(cid)}"><td data-label="쟁점">{e(issues[c["issue_id"]]["issue_ko"])}</td>'
            f'<td data-label="주장">{e(c["proposition_ko"])}</td>'
            f'<td data-label="출처"><a href="{e(a["url"])}" rel="noopener">{e(src)}</a></td>'
            f'<td data-label="근거">{e(c["evidence"]["desc_ko"])}</td></tr>')
    out += ['</tbody></table></div>',
            '<h3>주장 평가</h3>',
            '<div class="tbl-scroll"><table><thead><tr><th>주장</th><th>발언 주체</th>'
            '<th>기사가 제시한 실물 데이터</th><th>신빙성</th></tr></thead><tbody>']
    for cid in order:
        c = claims[cid]
        who = c['speaker_role'] + (f' · {c["speaker_name"]}' if c['speaker_name'] else '')
        kind = c['evidence']['kind']
        data = DATA_KO[kind] + ('' if kind == 'none' else f' — {EVIDENCE_KO[kind]}')
        out.append(
            f'<tr data-claim-eval="{e(cid)}"><td data-label="주장">{e(c["proposition_ko"])} '
            f'<span class="sub">{e(MODALITY_KO[c["modality"]])}</span></td>'
            f'<td data-label="발언 주체">{e(who)}</td>'
            f'<td data-label="기사가 제시한 실물 데이터">{e(data)}</td>'
            f'<td data-label="신빙성">{e(c["credibility"])} '
            f'<span class="sub">{e(c["credibility_reason_ko"])}</span></td></tr>')
    out += ['</tbody></table></div>',
            '<p class="caption">신빙성 기준 — 높음: 이 리포트가 가진 시장 데이터로 주장이 확인됨 · '
            '중간: 기사가 이름 붙은 통계·문서·관측을 전했으나 원자료는 확인하지 않음 · '
            '낮음: 근거가 일화·전언이거나 없음. 같은 발표를 여러 매체가 전한 것은 교차 확인으로 치지 '
            '않는다.</p>',
            '</div>',
            '<div class="card">',
            '<h3>본질</h3>',
            f'<p data-essence="structure"><span class="box-label">① 본질 구조</span> '
            f'{e(an["structure"]["text_ko"])}</p>',
            '<h4>② 핵심 변수</h4><ol data-essence="vars">']
    for v in an['variables']:
        ob = '; '.join(_obs_text(obs[o]) for o in v['obs'])
        out.append(f'<li>{e(v["name_ko"])} <span class="sub">관측: {e(ob)}</span></li>')
    out += ['</ol>', '<h4>③ 작동 방식</h4><ul data-essence="mechanism">']
    for ed in an['edges']:
        out.append(f'<li>{e(names[ed["from_var"]])} → {e(names[ed["to_var"]])}: '
                   f'{e(ed["condition_ko"])} {e(ed["direction_ko"])}</li>')
    out += ['</ul>', '<h4>④ 투자자 기억 포인트</h4><ol data-essence="memo">']
    for m in an['memo']:
        out.append(f'<li>{e(m["text_ko"])}</li>')
    out += ['</ol>', '</div>', '<div class="card">', '<h3>걱정의 크기</h3>']
    for tier, label in WORRY_TIERS:
        out.append(f'<h4>{label}</h4><ul data-worry="{tier}">')
        for it in an['worry'][tier]:
            extra = ''
            if tier == 'unlikely':
                extra = '; '.join(_obs_text(obs[o]) for o in it['counter_obs'])
                extra = f' <span class="sub">지금 관측: {e(extra)}</span>'
            out.append(f'<li>{e(it["text_ko"])} <span class="sub">조건: {e(it["condition_ko"])}'
                       f'</span>{extra}</li>')
        out.append('</ul>')
    out += ['<p class="caption">「사실상 가능성이 낮은 것」은 확률 추정이 아니라, 그 일이 일어나는 데 '
            '필요한 조건을 지금 관측치가 반대로 가리킨다는 판단이다. 주장·근거는 각 기사가 전한 '
            '내용을 옮긴 것이며 독립 검증이 아니다. 정보 제공 목적이며 매수·매도 권유가 아니다.</p>',
            '</div>', '</section>']
    return '\n'.join(out)


# ── 게이트 ───────────────────────────────────────────────────────────────
_INERT = {'template', 'noscript', 'script', 'style', 'head', 'title', 'textarea', 'iframe', 'object',
          'svg', 'math'}
_VOID = {'br', 'img', 'hr', 'meta', 'link', 'input', 'col', 'wbr', 'source', 'area', 'base',
         'embed', 'param', 'track'}
# 인증된 섹션 밖에 있으면 안 되는 표지 — 주석·script·속성값·CDATA 어디에 숨겨도 글자로 걸린다
# (구현 검토 2차 P1 두 건: 숨긴 정규형으로 인증받고 다른 섹션을 보이기, 생략 기록 + 지어낸 분석).
_RESERVED = ('data-contested', 'data-claim', 'data-essence', 'data-worry', 'id="contested"',
             "id='contested'", 'id=contested', MARKER, 'contested-omitted', PENDING)


class _Locate(HTMLParser):
    """`<section … data-contested>` 의 정확한 위치(오프셋)·조상·중복 속성을 잡는다."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self._starts = [0]
        for m in re.finditer('\n', html):
            self._starts.append(m.end())
        self.stack, self.sections, self.dupes, self.styles, self.links = [], [], [], [], []
        self._open = None
        self._depth = 0
        self.feed(html)
        self.close()

    def _off(self):
        line, col = self.getpos()
        return self._starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        names = [k for k, _ in attrs]
        if len(names) != len(set(names)):
            self.dupes.append(tag)
        d = dict(attrs)
        if tag == 'section':
            if self._open is not None:
                self._depth += 1
            elif 'data-contested' in d:
                self._open = {'start': self._off(), 'ancestors': list(self.stack), 'attrs': d}
                self._depth = 0
        if tag == 'link' and 'stylesheet' in (d.get('rel') or '').lower().split():
            self.links.append(d.get('href') or '')
        if tag not in _VOID:
            self.stack.append((tag, d))

    def handle_startendtag(self, tag, attrs):
        # 브라우저는 void 가 아닌 태그의 「/>」를 무시하고 그대로 연다 — <div hidden/> 는 열린 div 다(3차 P1)
        if tag not in _VOID:
            self.handle_starttag(tag, attrs)
            return
        names = [k for k, _ in attrs]
        if len(names) != len(set(names)):
            self.dupes.append(tag)
        if tag == 'link':
            d = dict(attrs)
            if 'stylesheet' in (d.get('rel') or '').lower().split():
                self.links.append(d.get('href') or '')

    def handle_endtag(self, tag):
        if tag == 'section' and self._open is not None:
            if self._depth:
                self._depth -= 1
            else:
                self._open['end'] = self._off() + len('</section>')
                self.sections.append(self._open)
                self._open = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][0] == 'style':
            self.styles.append(data)


def _hidden(attrs):
    style = re.sub(r'\s+', '', (attrs.get('style') or '')).lower()
    cls = f" {attrs.get('class') or ''} "
    return ('hidden' in attrs or 'inert' in attrs or 'display:none' in style
            or 'visibility:hidden' in style or 'opacity:0' in style or 'content-visibility:hidden' in style
            or ' sr-only ' in cls or attrs.get('aria-hidden') == 'true')


def _first(html):
    loc = _Locate(html)
    s = loc.sections[0] if loc.sections else None
    return html[s['start']:s['end']] if s else None


def check(html, payload, market, date, transforms=(), trusted_styles=None):
    """위반 목록. `payload` 는 None(파일 없음 = 미도착)일 수 있다.

    - ok: 섹션 정확히 하나(본문 컨테이너 바로 아래, 보이는 자리, 정규형 그대로) 또는 생략 기록 하나.
    - 동결된 none: 섹션·자리표시·생략 기록 모두 없음.
    - 미도착·error·재시도 가능한 none: 섹션 없음. 자리표시(`PENDING`) 하나는 허용 — 로컬 러너가
      나중에 채운다.
    `transforms` 는 발행 체인이 섹션에 가하는 변형(가독성·색), `trusted_styles` 는 셸·변형이 넣는
    `<style>` 블록 목록이다. 그 밖의 `<style>` 은 섹션을 숨길 수 있어 막는다. 덮개 같은 시각 공격은
    범위 밖이다 — 이 게이트는 작성자의 손질·실수를 막지 악의적 HTML 작성자를 막지 않는다.
    """
    errs = []
    if payload is not None:
        v = validate(payload, market, date)
        if v:
            return [f'데이터: {x}' for x in v[:10]]
    loc = _Locate(html)
    secs = loc.sections
    rest = html
    for sec in reversed(secs[:1]):
        rest = rest[:sec['start']] + rest[sec['end']:]
    counts = {k: rest.count(k) for k in _RESERVED}
    omitted = OMIT_RE.findall(rest)
    pending = counts[PENDING]
    stray = {k: n for k, n in counts.items() if n and k not in ('contested-omitted', PENDING)}
    if len(secs) > 1:
        errs.append(f'쟁점 섹션 {len(secs)}개')
    if stray:
        errs.append(f'섹션 밖에 쟁점 표지가 있다 {sorted(stray)}')
    if counts['contested-omitted'] != len(omitted) or len(omitted) > 1:
        errs.append('생략 기록이 형식에 맞지 않거나 둘 이상이다')
    if pending > 1:
        errs.append('자리표시가 둘 이상이다')
    if trusted_styles is not None:
        bad = [s for s in loc.styles if s.strip() and s.strip() not in trusted_styles]
        if bad:
            errs.append(f'신뢰하지 않는 <style> 블록 {len(bad)}개')
        links = [h for h in loc.links if f'link:{h}' not in trusted_styles]
        if links:
            errs.append(f'신뢰하지 않는 스타일시트 링크 {len(links)}개')
    if loc.dupes:
        errs.append(f'중복 속성이 있는 태그 {sorted(set(loc.dupes))}')
    st = payload.get('status') if payload else None
    if st == 'ok':
        if pending:
            errs.append('데이터가 ok 인데 자리표시가 남아 있다')
        if omitted:
            if secs:
                errs.append('생략 기록과 섹션이 함께 있다')
            return errs                  # 명시적 생략 — 보고 대상이지 위반이 아니다
        if len(secs) != 1:
            errs.append('쟁점 섹션이 없다(또는 명시적 생략 기록이 없다)')
            return errs
        sec = secs[0]
        for tag, attrs in sec['ancestors']:
            if tag in _INERT or _hidden(attrs):
                errs.append(f'섹션이 보이지 않는 조상 <{tag}> 안에 있다')
        anc = sec['ancestors']
        if not anc or anc[-1][0] != 'div' or 'doc' not in (anc[-1][1].get('class') or '').split():
            errs.append('섹션이 본문 컨테이너(div.doc) 바로 아래에 있지 않다')
        got = html[sec['start']:sec['end']]
        canon = render(payload)
        forms = {canon} | {(_first(t(f'<div class="doc">{canon}</div>')) or canon) for t in transforms}
        if got not in forms:
            errs.append('섹션이 데이터에서 찍은 정규형과 다르다 — 손으로 고치지 않는다')
        return errs
    if secs:
        errs.append(f"상태 {st or '미도착'} 인데 섹션이 있다")
    if omitted:
        errs.append(f"상태 {st or '미도착'} 인데 생략 기록이 있다")
    if pending and settled_final(payload):
        errs.append('동결된 결과인데 자리표시가 남아 있다')
    return errs
