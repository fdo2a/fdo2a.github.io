"""국내/해외 판정 섀도 — 일본 일간 뉴스 후보를 정규식·Haiku·Jev 가 각각 어떻게 가르는지 기록한다 (2026-10-27).

사용자 지시 「국내/해외 판정을 Haiku 섀도 모드로 … 일본부터」 + 「같은 섀도 자리에 Jev 판정도 함께 기록해서
둘을 나란히 비교」. 10/27 일간은 발행 뉴스 5건 중 3건이 해외였다(캐나다 중앙은행·미-캐나다 관세·도어대시) —
`japan.news._FOREIGN` 목록 밖의 나라·기업·약칭 조합이다.

**섀도다 — 선택·발행·게이트는 이 모듈을 읽지 않는다.** 경로와 주인이 둘이다(codex 설계 검토 #1):
입력 `region_shadow/input/<session>.json` 은 일간 수집(`fetch_japan_news.collect_daily`)만,
판정 `region_shadow/result/<session>.json` 은 `scripts/japan_region_shadow.py`(워크플로 `region-shadow.yml`)만 쓴다.

판정은 **제목 해시 × 설정 지문**으로 식별한다 — 같은 guid 의 제목이 바뀌거나 라벨 정의·모델이 바뀌면
옛 판정은 다시 쓰이지 않는다(#5). 완료 여부는 저장하지 않고 매번 현재 입력 대비 빠진 판정으로 센다(#3).

Pure — 네트워크 없음.
"""
import hashlib
import inspect
import json
import math

from japan import news as N

LABELS = ('domestic', 'foreign_impact', 'foreign')
LABELS_VERSION = 1
HAIKU_MODEL = 'claude-haiku-5-5'
JEV_MODEL = 'jev-1.14.0'     # 별칭(jev-latest)은 릴리스마다 움직인다 — 비교 기간에는 고정(docs.typesafe.ai/models)
BATCH = 25
PROVIDERS = ('haiku', 'jev')

# 두 모델이 같은 정의를 읽는다(#8). 우선순위: 일본 주어 → 일본 영향 명시 → 그 밖의 해외.
DEFINITIONS = {
    'domestic': ('The main subject is Japan: the Japanese government or a minister, the Bank of Japan, '
                 'a Japanese company, Japanese markets (Nikkei, TOPIX, JGBs, the yen) or Japanese economic data. '
                 'Choose this even when a foreign factor is also mentioned.'),
    'foreign_impact': ('The main subject is a foreign actor or event, and the headline explicitly states an '
                       'effect on Japan, a Japanese company or Japanese markets.'),
    'foreign': ('The main subject is a foreign actor or event (another government, central bank, company, '
                'market or data release) and the headline does not mention Japan. Regional headlines about '
                'Asia that do not name Japan are foreign.'),
}
INSTRUCTIONS = ('This is a Japanese financial news headline. Decide whose economy it is about. '
                'Precedence: if the main subject is Japanese, answer domestic; otherwise, if the headline names '
                'an effect on Japan, answer foreign_impact; otherwise answer foreign.')
HAIKU_SYSTEM = (INSTRUCTIONS + '\n\nLabels:\n'
                + '\n'.join(f'- {k}: {v}' for k, v in DEFINITIONS.items())
                + '\n\nYou receive a JSON list of {"id", "title"}. Return one item per id with its label. '
                  'Judge from the title alone.')
HAIKU_SCHEMA = {
    'type': 'object',
    'properties': {'items': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'id': {'type': 'string'}, 'label': {'type': 'string', 'enum': list(LABELS)}},
        'required': ['id', 'label'], 'additionalProperties': False}}},
    'required': ['items'], 'additionalProperties': False}
QUESTION = 'region'


def title_key(title):
    return hashlib.sha256((title or '').encode('utf-8')).hexdigest()[:16]


def config_id(provider, model):
    """라벨 정의·프롬프트·요청 모델의 지문. 하나라도 바뀌면 다른 실험이다."""
    blob = json.dumps({'v': LABELS_VERSION, 'defs': DEFINITIONS, 'inst': INSTRUCTIONS,
                       'sys': HAIKU_SYSTEM if provider == 'haiku' else None,
                       'provider': provider, 'model': model}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:12]


# ── 정규식 쪽 ─────────────────────────────────────────────────────────────
def regex_region(title, feed):
    """정규식의 **지역 술어** — `classify` 와 같은 정규화(NFKC)와 같은 식. `classify` 가 버린 이유 전체를
    설명하지는 않는다(정례·갈래 없음은 지역 판정이 아니다, #7)."""
    t = N._nfkc(title)
    foreign = bool(N._FOREIGN.search(t) or N._FOREIGN_MARKET.search(t) or feed == 'world')
    return 'foreign' if foreign and not N._JAPAN.search(t) else 'domestic'


def regex_fingerprint():
    """정규식 기준선의 지문 — `regex_region` 이 읽는 패턴·플래그와 술어·정규화 코드. 하나라도 바뀐 날의 입력은
    다른 기준선이다(재검토 #4, 2차: 플래그·NFKC 변경도 잡는다)."""
    parts = [f'{rx.pattern}\x00{rx.flags}' for rx in (N._JAPAN, N._FOREIGN, N._FOREIGN_MARKET)]
    parts += [inspect.getsource(regex_region), inspect.getsource(N._nfkc)]
    blob = '\n'.join(parts)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:12]


def binary(label):
    """정규식과의 비교는 두 칸 — 정규식에는 foreign_impact 가 없고 일본 표지가 있으면 국내로 친다."""
    return None if label is None else ('foreign' if label == 'foreign' else 'domestic')


def build_input(session, cut_rows, chosen_guids, commit=None, captured_at=None, cohort='full',
                collection_complete=None):
    """컷 안 목록 행 → 섀도 입력. 운영과 같은 순서(dedupe → 유료·매체)로, 행은 새 dict 로 만든다(원본 불변).
    공식 출처(일본은행·닛세이)는 넣지 않는다 — 보고의 단계 수는 이 코호트 안의 수다."""
    chosen = set(chosen_guids or ())
    rows = []
    for r in N.dedupe(cut_rows):
        if r.get('paid') or r.get('source') not in N.MEDIA_RANK or not r.get('title'):
            continue
        title, feed = r['title'], r.get('feed')
        rows.append({'guid': r.get('guid'), 'title': title, 'source': r.get('source'), 'feed': feed,
                     'key': title_key(title),
                     'regex_category': N.classify(title, feed),
                     'regex_region': regex_region(title, feed),
                     'regex_routine': bool(N._ROUTINE.search(N._nfkc(title))),
                     'collector_chosen': r.get('guid') in chosen})
    return {'session': session, 'market': 'japan', 'cohort': cohort, 'labels_version': LABELS_VERSION,
            'captured_at': captured_at, 'commit': commit, 'collection_complete': collection_complete,
            'regex_fp': regex_fingerprint(), 'rows': rows}


def bootstrap_input(session, daily_news, commit=None, captured_at=None):
    """이미 발행된 날 — 확정분만 남아 있다. 버려진 후보는 되살릴 수 없다(#6), 코호트로 표시한다."""
    items = (daily_news or {}).get('items') or []
    rows = [dict(r, paid=False) for r in items if not r.get('official')]
    return build_input(session, rows, [r.get('guid') for r in rows], commit=commit,
                       captured_at=captured_at, cohort='chosen_only',
                       collection_complete=(daily_news or {}).get('complete'))


# ── 판정 묶음 ─────────────────────────────────────────────────────────────
_ROW_STR = ('guid', 'title', 'key')


def valid_input(inp):
    """JSON 으로는 읽혀도 모양이 틀린 입력은 그 세션만 격리한다(codex 구현 검토 #2)."""
    if not isinstance(inp, dict) or not isinstance(inp.get('rows'), list):
        return False
    return all(isinstance(r, dict) and all(isinstance(r.get(k), str) and r.get(k) for k in _ROW_STR)
               and r.get('regex_region') in ('domestic', 'foreign') for r in inp['rows'])


def valid_result(res):
    """판정 파일 구조 — 라벨 밖의 판정이 「다 했다」로 세지지 않게."""
    if not isinstance(res, dict) or not isinstance(res.get('results'), dict):
        return False
    for provider, by_cfg in res['results'].items():
        if provider not in PROVIDERS or not isinstance(by_cfg, dict):
            return False
        for verdicts in by_cfg.values():
            if not isinstance(verdicts, dict):
                return False
            if not all(isinstance(v, dict) and v.get('label') in LABELS and _opt_str(v.get('model'))
                       and _opt_str(v.get('requested')) for v in verdicts.values()):
                return False
    return True


def _opt_str(v):
    """없거나 비지 않은 문자열 — 보고가 모델 이름으로 묶다 죽지 않게(재검토 #9). 길이는 묻지 않는다: 쓰는 쪽과
    읽는 쪽 규칙이 하나여야 한다 — 받아 적은 판정을 다시 읽다 세션째 격리하면 안 된다(2차 재검토)."""
    return v is None or (isinstance(v, str) and bool(v))


def empty_result(session):
    return {'session': session, 'market': 'japan', 'results': {p: {} for p in PROVIDERS}, 'runs': []}


def missing(inp, result, provider, cfg):
    """현재 입력 가운데 이 설정의 판정이 없는 행(제목 해시 기준, 중복 제목은 한 번)."""
    have = ((result or {}).get('results', {}).get(provider) or {}).get(cfg) or {}
    out, seen = [], set()
    for r in (inp or {}).get('rows') or []:
        if r['key'] in have or r['key'] in seen:
            continue
        seen.add(r['key'])
        out.append(r)
    return out


def record(result, provider, cfg, key, verdict):
    result.setdefault('results', {}).setdefault(provider, {}).setdefault(cfg, {})[key] = verdict


def verdict_of(result, provider, cfg, key):
    return (((result or {}).get('results', {}).get(provider) or {}).get(cfg) or {}).get(key)


# ── Haiku ─────────────────────────────────────────────────────────────────
class SchemaError(ValueError):
    pass


def haiku_payload(rows):
    """짧은 번호로 보낸다 — guid·해시를 모델이 옮겨 적다 틀리지 않게."""
    return [{'id': str(i), 'title': r['title']} for i, r in enumerate(rows)]


def parse_haiku(text, rows):
    """→ {row key: label}. 모르는 id·중복 id·라벨 밖은 묶음 전체를 버린다. 빠진 id 는 다음 실행이 다시 묻는다.
    id 는 보낸 문자열 그대로만 받는다 — 「00」·「²」 를 숫자로 읽으면 같은 행에 두 라벨이 앉는다(#6)."""
    try:
        items = json.loads(text)['items']
    except (ValueError, KeyError, TypeError):
        raise SchemaError('json') from None
    if not isinstance(items, list):
        raise SchemaError('items')
    sent = {p['id']: r for p, r in zip(haiku_payload(rows), rows)}
    out, seen = {}, set()
    for it in items:
        if not isinstance(it, dict):
            raise SchemaError('item')
        i, label = it.get('id'), it.get('label')
        if not isinstance(i, str) or i not in sent or i in seen:
            raise SchemaError('id')
        if label not in LABELS:
            raise SchemaError('label')
        seen.add(i)
        out[sent[i]['key']] = label
    return out


# ── Jev ───────────────────────────────────────────────────────────────────
def jev_body(title, model=JEV_MODEL):
    return {'model': model, 'state': title,
            'questions': {QUESTION: {'type': 'choice', 'instructions': INSTRUCTIONS,
                                     'criteria': dict(DEFINITIONS)}}}


def parse_jev(resp):
    """→ (label, probabilities, confidence, 응답 모델). 모양이 다르면 SchemaError — 제3자가 아닌 공식 문서
    형식(docs.typesafe.ai/api/system-one)이지만 방어적으로 본다."""
    try:
        ans = resp['answers'][QUESTION]
        label, probs, conf = ans['choice'], ans['probabilities'], ans.get('confidence')
    except (KeyError, TypeError):
        raise SchemaError('shape') from None
    if ans.get('type') != 'choice':
        raise SchemaError('type')
    if label not in LABELS or not isinstance(probs, dict) or set(probs) != set(LABELS):
        raise SchemaError('labels')
    vals = list(probs.values())
    if not all(_unit(v) for v in vals):
        raise SchemaError('prob')
    if abs(sum(vals) - 1) > 0.02:
        raise SchemaError('sum')
    if probs[label] < max(vals) - 1e-9:                 # 고른 것이 최대 확률이어야 한다(동률 허용)
        raise SchemaError('argmax')
    if not _unit(conf):                                 # 문서상 Choice 는 늘 confidence 를 준다
        raise SchemaError('confidence')
    model = resp.get('model')
    if model is None or not _opt_str(model):
        raise SchemaError('model')
    return label, {k: round(float(v), 4) for k, v in probs.items()}, conf, model


def _unit(v):
    """[0, 1] 의 유한한 실수 — bool 은 int 의 하위형이라 따로 뺀다."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1


# ── 보고 ─────────────────────────────────────────────────────────────────
def compare(pairs):
    """[(a, b)] → 일치 수·교집합 분모. 한쪽이라도 없으면 분모에서 뺀다 — 빠진 것끼리는 일치가 아니다(#10)."""
    both = [(a, b) for a, b in pairs if a is not None and b is not None]
    return {'agree': sum(a == b for a, b in both), 'n': len(both), 'eligible': len(pairs)}
