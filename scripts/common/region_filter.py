"""뉴스의 국내/해외 필터 — Jev 가 conf ≥ 0.9 로 「해외」라고 답한 국내 갈래 후보만 뺀다 (일본 2026-10-27, US·KR 10-28).

사용자 지시: 「일본 일간 뉴스 필터를 Jev(conf≥0.9 우선, 실패 시 정규식)로」 → 「미국 한국 일본 셋 다 jev로 바꿔」.
일본 평가(10/22-10/27 층화 표본, 정답 347): 정규식이 국내로 남긴 199건 중 해외 21건 → 이 규칙으로 6건, 잘못 뺀
국내 0건. **US·KR 은 평가 없이 바꿨다**(사용자 결정 — 나중에 `candidates` 감사로 잰다). US 는 경제·매크로·정치만.

**빼기만 한다** — 정규식이 그 시장의 국내 갈래로 남긴 후보 가운데서. 되살리지 않는다(codex 설계 검토 #3·#6),
foreign_impact 는 남긴다, **그날 파일에 이미 있는 기사는 빼지 않는다**(재수집이 작성 중인 글의 근거를 지우지 않게 —
US·KR 설계 검토 #1). 라벨 정의·질문은 `common/region_labels.py`, 모델은 `jev-1.14.0` 고정(다른 응답 모델은 정규식).

**실패하면 그 행은 정규식** — 키 없음·인증·HTTP·전송·형식 오류·마감. 받은 판정은 쓴다(행 단위). 예상 못 한 예외는
스레드 안이든 밖이든 **전체 되돌림**이다. Jev 호출은 데몬 스레드에서 돌고 본 흐름은 `deadline` 초 뒤 그때까지의
판정으로 진행한다 — 끝나지 않는 응답이 수집을 붙잡지 못한다.
"""
import threading
import time
from collections import Counter

from common import jev_client as J
from common import region_labels as L

JEV_MIN_CONF = 0.9
DEADLINE = 60          # 초 — 일본 일간. 359건 45초 실측, 하루 후보 100-200건
# US·KR 수집은 루틴이 `timeout 900` 으로 기다리는데 KR 은 이미 306-1062초 걸린다(10/28 실측) — 짧게 두고
# 최신 순으로 물어, 못 물은 행은 선정 순위가 낮은 쪽이 되게 한다(설계 검토 #5)
DEADLINE_SHORT = 30
REQUEST_TIMEOUT = 10
TRANSIENT_STOP, SCHEMA_STOP = 3, 5


def apply(rows, verdicts, threshold=JEV_MIN_CONF, exempt=()):
    """(남길 행, 뺀 기록). 원래 순서를 지키는 필터 — 행은 고치지 않는다. `exempt` guid 는 빼지 않는다."""
    kept, dropped = [], []
    for r in rows:
        v = verdicts.get(L.title_key(r.get('title')))
        if v and v[0] == 'foreign' and v[1] >= threshold and r.get('guid') not in exempt:
            dropped.append({'guid': r.get('guid'), 'title': r.get('title'), 'label': v[0], 'confidence': v[1]})
            continue
        kept.append(r)
    return kept, dropped


def _ask(titles, key, post, timeout, box, lock, halt, market):
    """데몬 스레드 본체. 예상 못 한 예외는 `crash` 로 남겨 본 흐름이 전체를 되돌리게 한다."""
    try:
        _ask_loop(titles, key, post, timeout, box, lock, halt, market)
    except Exception as e:                        # 스레드 밖으로 새면 아무도 못 본다
        with lock:
            box['errors'][f'crash:{type(e).__name__}'] += 1
            box['stopped'] = 'crash'


def _ask_loop(titles, key, post, timeout, box, lock, halt, market):
    """판정은 받는 대로 `box` 에 — 본 흐름이 마감에 그때까지를 가져간다."""
    transient = schema = 0

    def stop(why):
        with lock:
            box['stopped'] = why

    for k, title in titles:
        if halt.is_set():
            return
        with lock:
            box['asked'] += 1
        body = L.jev_body(title, market)          # 필터 코드 — 여기서 깨지면 전체 되돌림(바깥 except)
        try:                                      # 전송 경계 — 여기의 실패만 「그 행은 정규식」
            resp = post(body, key, timeout=timeout)
        except J.JevHTTPError as e:
            with lock:
                box['errors'][f'http:{e.code}'] += 1
                box['status'][k] = f'http:{e.code}'
            if e.code in (401, 403):
                return stop('auth')
            schema, transient = (schema + 1, transient) if e.code in (400, 422) else (schema, transient + 1)
            if schema >= SCHEMA_STOP:
                return stop('schema')
            if transient >= TRANSIENT_STOP:
                return stop('transient')
            continue
        except J.JevTransportError as e:
            # 연결·타임아웃·잘린 응답·해독 실패 — 클라이언트가 이 한 종류로 바꿔 준다(codex 구현 검토 #2, 재검토 #1)
            with lock:
                box['errors'][f'net:{e.kind}'] += 1
                box['status'][k] = f'net:{e.kind}'
            transient += 1
            if transient >= TRANSIENT_STOP:
                return stop('transient')
            continue
        try:
            label, _, conf, model = L.parse_jev(resp)
        except L.SchemaError as e:
            with lock:
                box['errors'][f'schema:{e}'] += 1
                box['status'][k] = f'schema:{e}'
            continue
        transient = schema = 0
        if model != L.JEV_MODEL:                  # 평가하지 않은 버전으로는 빼지 않는다
            with lock:                            # 응답 문자열은 감사에 옮기지 않는다(재검토 #2)
                box['errors']['model:mismatch'] += 1
                box['status'][k] = 'model:mismatch'
            continue
        with lock:
            box['verdicts'][k] = (label, conf)
            box['status'][k] = 'judged'


def _newest_first(rows):
    return sorted(rows, key=lambda r: r.get('published') or '', reverse=True)


def run(rows, env, market='japan', post=None, deadline=DEADLINE, timeout=REQUEST_TIMEOUT, exempt=(),
        newest_first=False):
    """(남길 행, region_filter 기록). `rows` 는 전부 대상이다. 키가 없으면 호출 없이 정규식 그대로."""
    rows, exempt = list(rows or []), set(exempt or ())
    meta = {'mode': 'regex', 'market': market, 'model': L.JEV_MODEL, 'threshold': JEV_MIN_CONF, 'asked': 0,
            'answered': 0, 'dropped': [], 'stopped': None, 'errors': {}, 'candidates': []}
    key = (env or {}).get('TYPESAFE_API_KEY')
    if not key:
        meta['stopped'] = 'no_key'
        meta['candidates'] = _candidates(rows, {}, exempt, {}, 'no_key')
        return rows, meta
    titles, seen = [], set()
    for r in (_newest_first(rows) if newest_first else rows):   # 같은 제목은 한 번만, 빼지 않을 것은 묻지 않는다
        k = L.title_key(r.get('title'))
        if r.get('title') and k not in seen and r.get('guid') not in exempt:
            seen.add(k)
            titles.append((k, r['title']))
    box = {'verdicts': {}, 'errors': Counter(), 'stopped': None, 'asked': 0, 'status': {}}
    lock, halt = threading.Lock(), threading.Event()
    t0 = time.monotonic()
    worker = threading.Thread(target=_ask, args=(titles, key, post or J.post, timeout, box, lock, halt, market),
                              daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        halt.set()
    with lock:
        verdicts, status = dict(box['verdicts']), dict(box['status'])
        stopped = box['stopped'] or ('deadline' if worker.is_alive() else 'complete')
        meta.update(asked=box['asked'], answered=len(verdicts), stopped=stopped, errors=dict(box['errors']))
    meta['seconds'] = round(time.monotonic() - t0, 1)
    if stopped == 'crash':
        # 예상 못 한 예외 — 그 전 판정도 믿지 않는다. 필터 코드 예외와 같이 전체 정규식
        meta.update(mode='regex', answered=0, candidates=_candidates(rows, {}, exempt, {}, 'rolled_back'))
        return rows, meta
    kept, meta['dropped'] = apply(rows, verdicts, exempt=exempt)
    meta['mode'] = 'jev' if verdicts else 'regex'
    meta['candidates'] = _candidates(rows, verdicts, exempt, status, 'unasked')
    return kept, meta


def _candidates(rows, verdicts, exempt, status, default):
    """나중 측정용 — 대상 후보 전부와 그 판정·상태. 제목만, 본문·응답 원문 없음(설계 검토 #4).
    상태: judged · http:/net:/schema:… (그 행 실패) · model:mismatch · unasked(마감 전에 못 물음) · exempt ·
    no_key · rolled_back — 실패와 못 물은 것을 가른다(US·KR 구현 검토 #3)."""
    out = []
    for r in rows:
        k = L.title_key(r.get('title'))
        v = verdicts.get(k)
        st = 'exempt' if r.get('guid') in exempt else status.get(k, default)
        out.append({'guid': r.get('guid'), 'title': r.get('title'), 'category': r.get('category'),
                    'label': v[0] if v else None, 'confidence': v[1] if v else None,
                    'exempt': r.get('guid') in exempt, 'status': st})
    return out


def guard(rows, env, market, categories=None, exempt=(), post=None, deadline=DEADLINE, newest_first=False):
    """수집기가 부르는 입구. `categories` 의 행만 대상, 나머지는 손대지 않고 원래 순서 그대로.
    여기서 어떤 예외가 나도 정규식 결과(`rows`)로 되돌린다."""
    rows = list(rows or [])
    try:
        targets = [r for r in rows if categories is None or r.get('category') in categories]
        kept, meta = run(targets, env, market, post=post, deadline=deadline, exempt=exempt,
                         newest_first=newest_first)
        keep = {id(r) for r in kept}
        tid = {id(r) for r in targets}
        meta['categories'] = sorted(categories) if categories is not None else None
        return [r for r in rows if id(r) not in tid or id(r) in keep], meta
    except Exception as e:
        return rows, {'mode': 'regex', 'market': market, 'stopped': f'crash:{type(e).__name__}'}


def guids_in(path):
    """그날 이미 저장된 기사 guid — 재수집이 이것을 빼지 않는다. 파일이 없거나 읽을 수 없으면 빈 집합."""
    import json
    try:
        with open(path, encoding='utf-8') as fh:
            return {it.get('guid') for it in json.load(fh).get('items') or [] if it.get('guid')}
    except (OSError, ValueError, AttributeError):
        return set()
