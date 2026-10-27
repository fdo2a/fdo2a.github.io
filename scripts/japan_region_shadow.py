#!/usr/bin/env python3
"""국내/해외 판정 섀도 — 일본 일간 후보 제목을 Haiku·Jev 로 판정하고(classify), 정규식과 나란히 센다(report).

순수 로직·라벨 정의는 `japan/region_shadow.py`. 입력은 일간 수집이 쓰고(`region_shadow/input/`), 이 CLI 는
**판정 파일(`region_shadow/result/`)만** 쓴다 — 두 수집 워크플로의 운영 데이터 커밋과 같은 파일을 만지지 않는다
(codex 설계 검토 #1). Actions 는 `region-shadow.yml` 이 일간 수집이 끝난 뒤 따로 돌린다(#2).

  python3 scripts/japan_region_shadow.py classify --datadir japan/data          # 빠진 판정 전부
  python3 scripts/japan_region_shadow.py report --datadir japan/data --since 2026-10-28
  python3 scripts/japan_region_shadow.py bootstrap --datadir japan/data --session 2026-10-27

**판정은 섀도다** — 선택·발행·게이트·검토 러너는 이 파일들을 읽지 않는다. 일치율은 정확도가 아니다(#10).
자격 증명: Haiku 는 `us.news_summary.make_client`(WIF 또는 API 키), Jev 는 `TYPESAFE_API_KEY`. 없으면 그
공급자만 건너뛴다. 키는 헤더에만 싣고, 로그·파일에는 HTTP 코드와 예외 이름만 남긴다.
"""
import argparse
import glob
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_news import save_json  # noqa: E402
from japan import news as N  # noqa: E402
from japan import region_shadow as R  # noqa: E402

# 공식 호스트 고정 — 덮어쓰기를 열면 Bearer 키가 엉뚱한 호스트로 간다(codex 설계 검토 #11)
JEV_URL = 'https://api.typesafe.ai/v1/systemone'
JEV_TIMEOUT = 20
BUDGETS = {'haiku': 240, 'jev': 240}       # 공급자별 초 — 한쪽이 다른 쪽의 시간을 먹지 않게(#2)
TRANSIENT_STOP = {'haiku': 2, 'jev': 3}     # 연속 일시 오류가 이만큼이면 이번 실행은 그만
SCHEMA_STOP = 5                             # Jev 400·422 연속 — 요청 모양이 틀린 것이다
JEV_CHECKPOINT = 10
_UNSET = object()
_DATA_NEWS = re.compile(r'\bdata-news="([0-9a-f]+)"')


def _dir(datadir, kind):
    return os.path.join(datadir, 'news', 'region_shadow', kind)


def _now_iso():
    return datetime.now(N.JST).isoformat(timespec='seconds')


def _load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _sessions(datadir, since=None, until=None):
    out = []
    for p in sorted(glob.glob(os.path.join(_dir(datadir, 'input'), '*.json'))):
        s = os.path.basename(p)[:-5]
        if (since and s < since) or (until and s > until):
            continue
        out.append(s)
    return out


# ── Jev 전송 ─────────────────────────────────────────────────────────────
class JevHTTPError(Exception):
    """HTTP 코드만 담는다 — urllib 의 HTTPError 는 헤더·본문을 끌고 다닌다."""

    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다 — urllib 은 Authorization 을 새 호스트로 그대로 옮긴다(#11)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise JevHTTPError(code)


def jev_post(body, key):
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(JEV_URL, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                                 headers={'Authorization': f'Bearer {key}',
                                          'Content-Type': 'application/json'}, method='POST')
    try:
        with opener.open(req, timeout=JEV_TIMEOUT) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise JevHTTPError(e.code) from None


# ── 판정 ─────────────────────────────────────────────────────────────────
def _haiku_client(env):
    from us.news_summary import make_client
    client = make_client(env)
    # 요약 클라이언트의 재시도 3·60초를 물려받지 않는다 — 섀도는 실행 마감이 있다(#2)
    return client.with_options(timeout=30.0, max_retries=1) if client is not None else None


def _err_kind(e):
    code = getattr(e, 'status_code', None) or getattr(e, 'code', None)
    return f'api:{code}' if code else f'api:{type(e).__name__}'


def _is_auth(e):
    from us.news_summary import is_auth_failure
    return is_auth_failure(e) or getattr(e, 'code', None) in (401, 403)


class _Book:
    """세션별 판정 파일. 읽을 수 없는 판정 파일은 덮어쓰지 않고 그 세션을 건너뛴다."""

    def __init__(self, datadir):
        self.datadir, self.inputs, self.results, self.bad = datadir, {}, {}, []

    def load(self, sessions):
        for s in sessions:
            try:
                inp = _load(os.path.join(_dir(self.datadir, 'input'), f'{s}.json'))
                if not isinstance(inp.get('rows'), list):
                    raise ValueError('rows')
            except (OSError, ValueError, AttributeError):
                self.bad.append(s)
                continue
            rpath = os.path.join(_dir(self.datadir, 'result'), f'{s}.json')
            try:
                res = _load(rpath) if os.path.exists(rpath) else R.empty_result(s)
            except (OSError, ValueError):
                self.bad.append(s)
                continue
            self.inputs[s], self.results[s] = inp, res

    def save(self, s):
        path = os.path.join(_dir(self.datadir, 'result'), f'{s}.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        save_json(path, self.results[s])


def _run_haiku(book, client, model, budget, now):
    cfg = R.config_id('haiku', model)
    stat = {'done': 0, 'stopped': None, 'errors': Counter()}
    if client is None:
        stat['stopped'] = 'no_credentials'
        return stat
    from us.news_summary import EFFORT_MODELS
    output_config = {'format': {'type': 'json_schema', 'schema': R.HAIKU_SCHEMA}}
    if model in EFFORT_MODELS:
        output_config['effort'] = EFFORT_MODELS[model]
    start, transient = now(), 0
    for s in book.inputs:
        todo = R.missing(book.inputs[s], book.results[s], 'haiku', cfg)
        for i in range(0, len(todo), R.BATCH):
            if now() - start >= budget:
                stat['stopped'] = 'deadline'
                return stat
            rows = todo[i:i + R.BATCH]
            try:
                resp = client.messages.create(
                    model=model, max_tokens=4096, system=R.HAIKU_SYSTEM,
                    messages=[{'role': 'user', 'content': json.dumps(R.haiku_payload(rows), ensure_ascii=False)}],
                    output_config=output_config)
            except Exception as e:
                stat['errors'][_err_kind(e)] += 1
                if _is_auth(e):
                    stat['stopped'] = 'auth'
                    return stat
                transient += 1
                if transient >= TRANSIENT_STOP['haiku']:
                    stat['stopped'] = 'transient'
                    return stat
                continue
            transient = 0
            if resp.stop_reason not in ('end_turn', 'stop_sequence'):
                stat['errors'][f'stop:{resp.stop_reason}'] += 1   # 잘림·거절은 판정이 아니다
                continue
            try:
                got = R.parse_haiku(''.join(b.text for b in resp.content if b.type == 'text'), rows)
            except R.SchemaError as e:
                stat['errors'][f'schema:{e}'] += 1
                continue
            at = _now_iso()
            for key, label in got.items():
                R.record(book.results[s], 'haiku', cfg, key, {'label': label, 'model': model, 'at': at})
            stat['done'] += len(got)
            book.save(s)                      # 묶음마다 저장 — 죽어도 한 일은 남는다(#4)
    return stat


def _run_jev(book, key, model, budget, now, post):
    cfg = R.config_id('jev', model)
    stat = {'done': 0, 'stopped': None, 'errors': Counter()}
    if not key:
        stat['stopped'] = 'no_key'
        return stat
    start, transient, schema = now(), 0, 0
    for s in book.inputs:
        pending = 0
        for row in R.missing(book.inputs[s], book.results[s], 'jev', cfg):
            if now() - start >= budget:
                stat['stopped'] = 'deadline'
                break
            try:
                label, probs, conf, used = R.parse_jev(post(R.jev_body(row['title'], model), key))
            except JevHTTPError as e:
                stat['errors'][f'http:{e.code}'] += 1
                if e.code in (401, 403):
                    stat['stopped'] = 'auth'
                    break
                if e.code in (400, 422):
                    schema += 1
                    if schema >= SCHEMA_STOP:
                        stat['stopped'] = 'schema'
                        break
                    continue
                transient += 1
                if transient >= TRANSIENT_STOP['jev']:
                    stat['stopped'] = 'transient'
                    break
                continue
            except R.SchemaError as e:
                stat['errors'][f'schema:{e}'] += 1
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                stat['errors'][f'net:{type(e).__name__}'] += 1
                transient += 1
                if transient >= TRANSIENT_STOP['jev']:
                    stat['stopped'] = 'transient'
                    break
                continue
            transient = schema = 0
            R.record(book.results[s], 'jev', cfg, row['key'],
                     {'label': label, 'p': probs, 'confidence': conf, 'model': used, 'at': _now_iso()})
            stat['done'] += 1
            pending += 1
            if pending >= JEV_CHECKPOINT:
                book.save(s)
                pending = 0
        if pending:
            book.save(s)
        if stat['stopped']:
            break
    return stat


def classify(datadir, providers=R.PROVIDERS, env=None, haiku_client=_UNSET, jev_post=jev_post,
             now=time.monotonic, budgets=None, haiku_model=None, jev_model=None, sessions=None):
    env = os.environ if env is None else env
    budgets = budgets or BUDGETS
    book = _Book(datadir)
    book.load(sessions or _sessions(datadir))
    out = {'bad_inputs': list(book.bad)}
    if 'haiku' in providers:
        model = haiku_model or env.get('REGION_SHADOW_MODEL') or R.HAIKU_MODEL
        client = _haiku_client(env) if haiku_client is _UNSET else haiku_client
        out['haiku'] = _run_haiku(book, client, model, budgets['haiku'], now)
    if 'jev' in providers:
        model = jev_model or R.JEV_MODEL
        out['jev'] = _run_jev(book, env.get('TYPESAFE_API_KEY'), model, budgets['jev'], now, jev_post)
    for p in providers:
        st = out[p]
        st['errors'] = dict(st['errors'])
        st['stopped'] = st['stopped'] or 'complete'
    return out


# ── 보고 ─────────────────────────────────────────────────────────────────
def _usable_guids(datadir, s):
    from us.news_summary import summary_problem
    path = os.path.join(datadir, 'news', 'daily', f'{s}.json')
    if not os.path.exists(path):
        return set()
    return {it.get('guid') for it in _load(path).get('items') or []
            if it.get('summary_ko') and summary_problem(it['summary_ko']) is None}


def _published_guids(html_root, s):
    path = os.path.join(html_root, 'japan', 'daily', f'{s}.html')
    if not os.path.exists(path):
        return set()
    with open(path, encoding='utf-8') as fh:
        return set(_DATA_NEWS.findall(fh.read()))


def build_report(datadir, html_root='.', since=None, until=None, haiku_model=R.HAIKU_MODEL,
                 jev_model=R.JEV_MODEL):
    """일치율·적용 범위·단계별 수. 정확도는 아니다 — 셋이 같이 틀린 행은 여기서 보이지 않는다(#10)."""
    cfg = {'haiku': R.config_id('haiku', haiku_model), 'jev': R.config_id('jev', jev_model)}
    book = _Book(datadir)
    book.load(_sessions(datadir, since, until))
    cohorts = Counter(book.inputs[s].get('cohort') for s in book.inputs)
    coverage = {p: {'done': 0, 'missing': 0} for p in R.PROVIDERS}
    stage_names = ('captured', 'collector_chosen', 'summary_usable', 'published')
    stages = Counter()
    by_stage = {st: {'regex': Counter(), 'haiku': Counter(), 'jev': Counter()} for st in stage_names}
    pairs = {'regex~haiku': [], 'regex~jev': [], 'haiku~jev': []}
    disagree, other_configs = [], Counter()
    for s, inp in book.inputs.items():
        res = book.results[s]
        for p in R.PROVIDERS:
            other_configs[p] += len(set((res.get('results', {}).get(p) or {})) - {cfg[p]})
        usable, published = _usable_guids(datadir, s), _published_guids(html_root, s)
        for r in inp['rows']:
            h = (R.verdict_of(res, 'haiku', cfg['haiku'], r['key']) or {}).get('label')
            j = (R.verdict_of(res, 'jev', cfg['jev'], r['key']) or {}).get('label')
            for p, v in (('haiku', h), ('jev', j)):
                coverage[p]['done' if v else 'missing'] += 1
            flags = {'captured': True, 'collector_chosen': r.get('collector_chosen'),
                     'summary_usable': r['guid'] in usable, 'published': r['guid'] in published}
            for st in stage_names:
                if flags[st]:
                    stages[st] += 1
                    by_stage[st]['regex'][r['regex_region']] += 1
                    by_stage[st]['haiku'][h or 'missing'] += 1
                    by_stage[st]['jev'][j or 'missing'] += 1
            pairs['regex~haiku'].append((r['regex_region'], R.binary(h)))
            pairs['regex~jev'].append((r['regex_region'], R.binary(j)))
            pairs['haiku~jev'].append((h, j))
            if len({x for x in (r['regex_region'], R.binary(h), R.binary(j)) if x}) > 1 or (h and j and h != j):
                disagree.append({'session': s, 'title': r['title'], 'regex': r['regex_region'],
                                 'regex_category': r.get('regex_category'), 'haiku': h, 'jev': j,
                                 'jev_p': (R.verdict_of(res, 'jev', cfg['jev'], r['key']) or {}).get('p'),
                                 'chosen': r.get('collector_chosen'), 'published': flags['published']})
    return {'sessions': list(book.inputs), 'bad': book.bad, 'cohorts': dict(cohorts), 'config': cfg,
            'other_configs': dict(other_configs), 'coverage': coverage,
            'stages': {st: stages[st] for st in stage_names},
            'by_stage': {st: {k: dict(v) for k, v in d.items()} for st, d in by_stage.items()},
            'agreement': {k: R.compare(v) for k, v in pairs.items()}, 'disagreements': disagree}


def print_report(rep):
    print(f"세션 {len(rep['sessions'])}개 · 코호트 {rep['cohorts']} · 읽지 못한 세션 {rep['bad'] or '없음'}")
    for p, c in rep['coverage'].items():
        other = rep['other_configs'].get(p)
        print(f"  {p}: 판정 {c['done']} · 빠짐 {c['missing']}" + (f' · 다른 설정 묶음 {other}' if other else ''))
    print('단계별 (정규식 지역 / Haiku / Jev):')
    for st, n in rep['stages'].items():
        d = rep['by_stage'][st]
        print(f"  {st:16s} {n:4d}  regex {d['regex']}  haiku {d['haiku']}  jev {d['jev']}")
    print('일치율 — 정확도가 아니다(셋이 같이 틀린 행은 보이지 않는다):')
    for k, a in rep['agreement'].items():
        rate = f"{a['agree'] / a['n']:.0%}" if a['n'] else '-'
        print(f"  {k:12s} {a['agree']}/{a['n']} ({rate}) · 대상 {a['eligible']}")
    print(f"불일치 {len(rep['disagreements'])}건:")
    for d in rep['disagreements']:
        mark = '발행' if d['published'] else ('확정' if d['chosen'] else '')
        print(f"  {d['session']} [{mark:2s}] regex={d['regex']} haiku={d['haiku']} jev={d['jev']} {d['title']}")


# ── CLI ──────────────────────────────────────────────────────────────────
def bootstrap(datadir, session, force=False):
    path = os.path.join(_dir(datadir, 'input'), f'{session}.json')
    if os.path.exists(path) and not force:
        print(f'{path} 가 이미 있다 — 수집이 만든 입력을 덮지 않는다(--force 로만)', file=sys.stderr)
        return 1
    daily = _load(os.path.join(datadir, 'news', 'daily', f'{session}.json'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, R.bootstrap_input(session, daily, commit=os.environ.get('GITHUB_SHA'),
                                      captured_at=_now_iso()))
    print(f'{path} — 확정분만 {len(daily.get("items") or [])}건(chosen_only)')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('classify')
    c.add_argument('--datadir', default='japan/data')
    c.add_argument('--providers', default='haiku,jev')
    r = sub.add_parser('report')
    r.add_argument('--datadir', default='japan/data')
    r.add_argument('--html-root', default='.')
    r.add_argument('--since')
    r.add_argument('--until')
    r.add_argument('--json', action='store_true')
    b = sub.add_parser('bootstrap')
    b.add_argument('--datadir', default='japan/data')
    b.add_argument('--session', required=True)
    b.add_argument('--force', action='store_true')
    args = ap.parse_args(argv)
    if args.cmd == 'bootstrap':
        return bootstrap(args.datadir, args.session, args.force)
    if args.cmd == 'report':
        rep = build_report(args.datadir, args.html_root, args.since, args.until)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print_report(rep)
        return 0
    out = classify(args.datadir, providers=tuple(p for p in args.providers.split(',') if p))
    if out['bad_inputs']:
        print(f"읽지 못한 입력·판정 파일: {', '.join(out['bad_inputs'])}", file=sys.stderr)
    for p in R.PROVIDERS:
        if p in out:
            st = out[p]
            print(f"{p}: 판정 {st['done']} · 끝 {st['stopped']} · 오류 {st['errors'] or '없음'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
