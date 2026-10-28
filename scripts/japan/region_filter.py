"""일본 일간 뉴스의 국내/해외 필터 — Jev 가 conf ≥ 0.9 로 「해외」라고 답한 후보만 뺀다 (2026-10-27).

사용자 지시 「일본 일간 뉴스 필터를 Jev(conf≥0.9 우선, 실패 시 정규식)로 바꾸는 작업」. 평가(10/22-10/27 층화 표본,
정답 347): 정규식이 국내로 남긴 199건 중 해외 21건 → 이 규칙으로 6건, 잘못 뺀 국내 0건(plan.md 2026-10-27).

**빼기만 한다** — 정규식이 남긴 후보(`screen` → `retag`) 가운데서. 정규식이 버린 것을 되살리지 않는다(0.9 에서 되살아난
것이 0건이었고, 순서가 PRESELECT 자리를 바꾼다 — codex 설계 검토 #3·#6). foreign_impact(제목이 일본 영향을 명시)는 남긴다.
라벨 정의·질문·모델(`jev-1.14.0`)은 평가한 섀도 설정 그대로(`japan/region_shadow.py`), 다른 모델의 응답은 쓰지 않는다(#8).

**실패하면 그 행은 정규식** — 키 없음·인증·HTTP·형식 오류·마감. 받은 판정은 쓴다(행 단위, #2). 예상 못 한 예외는
스레드 안이든 밖이든 **전체 되돌림**이다. Jev 호출은 데몬
스레드에서 돌고 본 흐름은 `deadline` 초 뒤 그때까지의 판정으로 진행한다 — 끝나지 않는 응답이 수집을 붙잡지 못한다(#1).
"""
import http.client
import threading
import time
import urllib.error
from collections import Counter

from japan import jev_client as J
from japan import region_shadow as R

JEV_MIN_CONF = 0.9
DEADLINE = 60          # 초 — 일간 수집은 루틴이 기다린다. 359건 45초 실측, 하루 후보 100-200건
REQUEST_TIMEOUT = 10
TRANSIENT_STOP, SCHEMA_STOP = 3, 5


def apply(rows, verdicts, threshold=JEV_MIN_CONF):
    """(남길 행, 뺀 기록). 원래 순서를 지키는 필터 — 행은 고치지 않는다."""
    kept, dropped = [], []
    for r in rows:
        v = verdicts.get(R.title_key(r.get('title')))
        if v and v[0] == 'foreign' and v[1] >= threshold:
            dropped.append({'guid': r.get('guid'), 'title': r.get('title'), 'label': v[0], 'confidence': v[1]})
            continue
        kept.append(r)
    return kept, dropped


def _ask(titles, key, post, timeout, box, lock, halt):
    """데몬 스레드 본체. 예상 못 한 예외는 `crash` 로 남겨 본 흐름이 전체를 되돌리게 한다."""
    try:
        _ask_loop(titles, key, post, timeout, box, lock, halt)
    except Exception as e:                        # 스레드 밖으로 새면 아무도 못 본다
        with lock:
            box['errors'][f'crash:{type(e).__name__}'] += 1
            box['stopped'] = 'crash'


def _ask_loop(titles, key, post, timeout, box, lock, halt):
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
        body = R.jev_body(title)                  # 필터 코드 — 여기서 깨지면 전체 되돌림(바깥 except)
        try:                                      # 전송 경계 — 여기의 실패만 「그 행은 정규식」
            resp = post(body, key, timeout=timeout)
        except J.JevHTTPError as e:
            with lock:
                box['errors'][f'http:{e.code}'] += 1
            if e.code in (401, 403):
                return stop('auth')
            schema, transient = (schema + 1, transient) if e.code in (400, 422) else (schema, transient + 1)
            if schema >= SCHEMA_STOP:
                return stop('schema')
            if transient >= TRANSIENT_STOP:
                return stop('transient')
            continue
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            # 연결·타임아웃·잘린 응답(IncompleteRead)·JSON 해독 실패 — codex 구현 검토 #2
            with lock:
                box['errors'][f'net:{type(e).__name__}'] += 1
            transient += 1
            if transient >= TRANSIENT_STOP:
                return stop('transient')
            continue
        try:
            label, _, conf, model = R.parse_jev(resp)
        except R.SchemaError as e:
            with lock:
                box['errors'][f'schema:{e}'] += 1
            continue
        transient = schema = 0
        if model != R.JEV_MODEL:                  # 평가하지 않은 버전으로는 빼지 않는다
            with lock:
                box['errors'][f'model:{str(model)[:40]}'] += 1
            continue
        with lock:
            box['verdicts'][k] = (label, conf)


def run(rows, env, post=None, deadline=DEADLINE, timeout=REQUEST_TIMEOUT):
    """(남길 행, region_filter 기록). 키가 없으면 호출 없이 정규식 그대로."""
    rows = list(rows or [])
    meta = {'mode': 'regex', 'model': R.JEV_MODEL, 'threshold': JEV_MIN_CONF, 'asked': 0, 'answered': 0,
            'dropped': [], 'stopped': None, 'errors': {}}
    key = (env or {}).get('TYPESAFE_API_KEY')
    if not key:
        meta['stopped'] = 'no_key'
        return rows, meta
    titles, seen = [], set()
    for r in rows:                                 # 같은 제목은 한 번만 묻는다
        k = R.title_key(r.get('title'))
        if r.get('title') and k not in seen:
            seen.add(k)
            titles.append((k, r['title']))
    box = {'verdicts': {}, 'errors': Counter(), 'stopped': None, 'asked': 0}
    lock, halt = threading.Lock(), threading.Event()
    t0 = time.monotonic()
    worker = threading.Thread(target=_ask, args=(titles, key, post or J.post, timeout, box, lock, halt),
                              daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        halt.set()
    with lock:
        verdicts = dict(box['verdicts'])
        stopped = box['stopped'] or ('deadline' if worker.is_alive() else 'complete')
        meta.update(asked=box['asked'], answered=len(verdicts), stopped=stopped, errors=dict(box['errors']))
    if stopped == 'crash':
        # 예상 못 한 예외 — 그 전 판정도 믿지 않는다. 필터 코드 예외와 같이 전체 정규식(codex 구현 검토)
        return rows, dict(meta, mode='regex', stopped='crash', answered=0)
    kept, meta['dropped'] = apply(rows, verdicts)
    meta['mode'] = 'jev' if verdicts else 'regex'
    meta['seconds'] = round(time.monotonic() - t0, 1)
    return kept, meta
