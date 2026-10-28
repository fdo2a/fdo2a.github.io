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
import sys
import time
import urllib.error
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_news import save_json  # noqa: E402
from common import jev_client as J  # noqa: E402
from japan import news as N  # noqa: E402
from japan import region_shadow as R  # noqa: E402

JEV_URL, JEV_TIMEOUT = J.JEV_URL, J.JEV_TIMEOUT
HAIKU_TIMEOUT = 30
REQUEST_TIMEOUT = {'haiku': HAIKU_TIMEOUT, 'jev': JEV_TIMEOUT}
# 공급자별 초. **부드러운 마감이다** — 새 요청을 시작할지만 정하고, 진행 중인 요청은 끊지 못한다. 실제 상한은
# 워크플로가 공급자마다 나눈 단계의 `timeout-minutes` 다(codex 재검토 #1)
BUDGETS = {'haiku': 240, 'jev': 240}
TRANSIENT_STOP = {'haiku': 2, 'jev': 3}     # 연속 일시 오류가 이만큼이면 이번 실행은 그만
SCHEMA_STOP = 5                             # Jev 400·422 연속 — 요청 모양이 틀린 것이다
_UNSET = object()
_DATA_NEWS = re.compile(r'\bdata-news="([0-9a-f]+)"')


def _dir(datadir, kind):
    return os.path.join(datadir, 'news', 'region_shadow', kind)


def _now_iso():
    return datetime.now(N.JST).isoformat(timespec='seconds')


def _load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _in_range(s, since, until):
    return not ((since and s < since) or (until and s > until))


def _sessions(datadir, since=None, until=None):
    names = (os.path.basename(p)[:-5] for p in glob.glob(os.path.join(_dir(datadir, 'input'), '*.json')))
    return sorted(s for s in names if _in_range(s, since, until))


def _expected_sessions(datadir, html_root, since=None, until=None):
    """일간 뉴스·발행 HTML 이 있는 세션 — 캡처가 없으면 보고가 그 날을 「no_capture」 로 보인다(#3)."""
    paths = glob.glob(os.path.join(datadir, 'news', 'daily', '*.json')) + \
        glob.glob(os.path.join(html_root, 'japan', 'daily', '*.html'))
    names = {os.path.splitext(os.path.basename(p))[0] for p in paths}
    return sorted(s for s in names if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) and _in_range(s, since, until))


# ── Jev 전송 — 국내/해외 필터와 같이 쓴다(`common/jev_client.py`) ───────────────────
JevHTTPError, _NoRedirect = J.JevHTTPError, J._NoRedirect


def jev_post(body, key):
    return J.post(body, key, timeout=JEV_TIMEOUT)


# ── 판정 ─────────────────────────────────────────────────────────────────
def _haiku_client(env):
    from us.news_summary import make_client
    client = make_client(env)
    # 요약 클라이언트의 재시도 3·60초를 물려받지 않는다 — SDK 재시도는 `Retry-After` 를 그대로 기다려
    # 마감을 넘긴다(codex 구현 검토 #1). 재시도는 다음 실행이 빠진 판정으로 한다
    return client.with_options(timeout=float(HAIKU_TIMEOUT), max_retries=0) if client is not None else None


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
            rpath = os.path.join(_dir(self.datadir, 'result'), f'{s}.json')
            try:
                inp = _load(os.path.join(_dir(self.datadir, 'input'), f'{s}.json'))
                res = _load(rpath) if os.path.exists(rpath) else R.empty_result(s)
            except (OSError, ValueError):
                inp = res = None
            # JSON 으로 읽혀도 모양이 틀리면 그 세션만 뺀다 — 다른 세션·공급자는 계속(#2)
            if not R.valid_input(inp) or not R.valid_result(res):
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
            if now() - start + HAIKU_TIMEOUT > budget:      # 요청 하나가 끝나기 전에 마감이 오면 시작하지 않는다
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
            # 응답이 밝힌 실제 모델(#4) — 모델 ID 모양일 때만, 아니면 'other'(재검토 2차 #1)
            at, used = _now_iso(), R.safe_claude_model(getattr(resp, 'model', None) or model)
            for key, label in got.items():
                R.record(book.results[s], 'haiku', cfg, key,
                         {'label': label, 'model': used, 'requested': model, 'at': at})
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
        for row in R.missing(book.inputs[s], book.results[s], 'jev', cfg):
            if now() - start + JEV_TIMEOUT > budget:
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
            except (J.JevTransportError, urllib.error.URLError, OSError, ValueError) as e:
                stat['errors'][f'net:{type(e).__name__}'] += 1
                transient += 1
                if transient >= TRANSIENT_STOP['jev']:
                    stat['stopped'] = 'transient'
                    break
                continue
            transient = schema = 0
            R.record(book.results[s], 'jev', cfg, row['key'],
                     {'label': label, 'p': probs, 'confidence': conf, 'model': used, 'requested': model,
                      'at': _now_iso()})
            stat['done'] += 1
            book.save(s)                      # 건마다 — 잡이 끊겨도 받은 판정은 남는다(#8)
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
    runs = {'haiku': lambda: _run_haiku(book, _haiku_client(env) if haiku_client is _UNSET else haiku_client,
                                        haiku_model or env.get('REGION_SHADOW_MODEL') or R.HAIKU_MODEL,
                                        budgets['haiku'], now),
            'jev': lambda: _run_jev(book, env.get('TYPESAFE_API_KEY'), jev_model or R.JEV_MODEL,
                                    budgets['jev'], now, jev_post)}
    for p in R.PROVIDERS:
        if p not in providers:
            continue
        try:                                  # 한 공급자의 예상 못 한 실패가 다른 공급자를 막지 않는다(#2)
            out[p] = runs[p]()
        except Exception as e:
            out[p] = {'done': 0, 'stopped': f'crash:{type(e).__name__}', 'errors': Counter()}
    for p in providers:
        st = out[p]
        st['errors'] = dict(st['errors'])
        st['stopped'] = st['stopped'] or 'complete'
    return out


# ── 보고 ─────────────────────────────────────────────────────────────────
def _daily_items(datadir, s):
    """그날 일간 뉴스 확정분 {guid: item}. 없거나 읽을 수 없으면 None."""
    path = os.path.join(datadir, 'news', 'daily', f'{s}.json')
    try:
        return {it.get('guid'): it for it in _load(path).get('items') or []}
    except (OSError, ValueError, AttributeError):
        return None


def _published_guids(html_root, s):
    path = os.path.join(html_root, 'japan', 'daily', f'{s}.html')
    if not os.path.exists(path):
        return set()
    with open(path, encoding='utf-8') as fh:
        return set(_DATA_NEWS.findall(fh.read()))


def build_report(datadir, html_root='.', since=None, until=None, haiku_model=None, jev_model=None):
    """일치율·적용 범위·단계별 수. 정확도는 아니다 — 셋이 같이 틀린 행은 여기서 보이지 않는다(#10).
    단계 수는 **캡처된 비공식 코호트 안**의 수다 — 공식 출처(일본은행) 발행분은 들어가지 않는다(#3)."""
    from us.news_summary import summary_problem
    haiku_model = haiku_model or os.environ.get('REGION_SHADOW_MODEL') or R.HAIKU_MODEL
    jev_model = jev_model or R.JEV_MODEL
    cfg = {'haiku': R.config_id('haiku', haiku_model), 'jev': R.config_id('jev', jev_model)}
    book = _Book(datadir)
    book.load(_sessions(datadir, since, until))
    no_capture = [s for s in _expected_sessions(datadir, html_root, since, until)
                  if s not in book.inputs and s not in book.bad]
    cohorts = Counter(book.inputs[s].get('cohort') for s in book.inputs)
    incomplete = [s for s in book.inputs if book.inputs[s].get('collection_complete') is False]
    coverage = {p: {'done': 0, 'missing': 0} for p in R.PROVIDERS}
    actual = {p: Counter() for p in R.PROVIDERS}
    stage_names = ('captured', 'collector_chosen', 'summary_usable', 'published')
    stages, stale = Counter(), 0
    by_stage = {st: {'regex': Counter(), 'haiku': Counter(), 'jev': Counter()} for st in stage_names}
    pairs = {}
    disagree, other_configs = [], Counter()
    for s, inp in book.inputs.items():
        res = book.results[s]
        for p in R.PROVIDERS:
            other_configs[p] += len(set((res.get('results', {}).get(p) or {})) - {cfg[p]})
        daily, published = _daily_items(datadir, s), _published_guids(html_root, s)
        for r in inp['rows']:
            hv = R.verdict_of(res, 'haiku', cfg['haiku'], r['key']) or {}
            jv = R.verdict_of(res, 'jev', cfg['jev'], r['key']) or {}
            h, j = hv.get('label'), jv.get('label')
            for p, v in (('haiku', hv), ('jev', jv)):
                coverage[p]['done' if v else 'missing'] += 1
                if v:
                    actual[p][v.get('model')] += 1
            # 요약·발행 단계는 guid **와 제목**이 일간 근거와 같을 때만 — 다른 회차의 캡처를 옛 근거에 잇지 않는다(#5)
            item = (daily or {}).get(r['guid'])
            same = item is not None and item.get('title') == r['title']
            if item is not None and not same:
                stale += 1
            usable = same and bool(item.get('summary_ko')) and summary_problem(item['summary_ko']) is None
            flags = {'captured': True, 'collector_chosen': r.get('collector_chosen'),
                     'summary_usable': usable, 'published': same and r['guid'] in published}
            for st in stage_names:
                if flags[st]:
                    stages[st] += 1
                    by_stage[st]['regex'][r['regex_region']] += 1
                    by_stage[st]['haiku'][h or 'missing'] += 1
                    by_stage[st]['jev'][j or 'missing'] += 1
            # 일치율은 실제 모델별로 나눈다 — 별칭이 움직이면 다른 실험이다(#4)
            # 정규식 쪽은 기준선 지문으로도 나눈다 — 정규식이 바뀐 날과 섞지 않는다(재검토 #4)
            hm, jm, fp = hv.get('model'), jv.get('model'), inp.get('regex_fp') or 'unknown'
            pairs.setdefault(('regex~haiku', f'{hm}|regex:{fp}'), []).append((r['regex_region'], R.binary(h)))
            pairs.setdefault(('regex~jev', f'{jm}|regex:{fp}'), []).append((r['regex_region'], R.binary(j)))
            pairs.setdefault(('haiku~jev', f'{hm}|{jm}'), []).append((h, j))
            if len({x for x in (r['regex_region'], R.binary(h), R.binary(j)) if x}) > 1 or (h and j and h != j):
                disagree.append({'session': s, 'title': r['title'], 'regex': r['regex_region'],
                                 'regex_category': r.get('regex_category'), 'haiku': h, 'jev': j,
                                 'jev_p': (R.verdict_of(res, 'jev', cfg['jev'], r['key']) or {}).get('p'),
                                 'chosen': r.get('collector_chosen'), 'published': flags['published']})
    agreement = {}
    for (name, model), v in sorted(pairs.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        c = R.compare(v)
        if c['n']:
            agreement[f'{name} [{model}]'] = c
    return {'sessions': list(book.inputs), 'bad': book.bad, 'no_capture': no_capture,
            'incomplete_collection': incomplete, 'cohorts': dict(cohorts),
            'models': {'haiku': haiku_model, 'jev': jev_model}, 'config': cfg,
            'actual_models': {p: dict(c) for p, c in actual.items()},
            'other_configs': dict(other_configs), 'coverage': coverage, 'stale_rows': stale,
            'stages': {st: stages[st] for st in stage_names},
            'by_stage': {st: {k: dict(v) for k, v in d.items()} for st, d in by_stage.items()},
            'agreement': agreement, 'disagreements': disagree}


def print_report(rep):
    print(f"세션 {len(rep['sessions'])}개 · 코호트 {rep['cohorts']} · 읽지 못한 세션 {rep['bad'] or '없음'}")
    print(f"캡처 없음 {rep['no_capture'] or '없음'} · 수집 미완주 {rep['incomplete_collection'] or '없음'}"
          f" · 제목이 바뀐 행 {rep['stale_rows']}")
    for p, c in rep['coverage'].items():
        other = rep['other_configs'].get(p)
        print(f"  {p} ({rep['models'][p]}): 판정 {c['done']} · 빠짐 {c['missing']} · 실제 모델 "
              f"{rep['actual_models'][p] or '-'}" + (f' · 다른 설정 묶음 {other}' if other else ''))
    print('단계별 — 캡처된 비공식 코호트 안의 수 (정규식 지역 / Haiku / Jev):')
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
def _commit():
    """정규식 기준선을 알아볼 커밋 — Actions 는 GITHUB_SHA, 로컬은 HEAD."""
    if os.environ.get('GITHUB_SHA'):
        return os.environ['GITHUB_SHA']
    import subprocess
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__)), timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def bootstrap(datadir, session, force=False):
    path = os.path.join(_dir(datadir, 'input'), f'{session}.json')
    if os.path.exists(path) and not force:
        print(f'{path} 가 이미 있다 — 수집이 만든 입력을 덮지 않는다(--force 로만)', file=sys.stderr)
        return 1
    daily = _load(os.path.join(datadir, 'news', 'daily', f'{session}.json'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, R.bootstrap_input(session, daily, commit=_commit(), captured_at=_now_iso()))
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
    r.add_argument('--haiku-model')
    r.add_argument('--jev-model')
    b = sub.add_parser('bootstrap')
    b.add_argument('--datadir', default='japan/data')
    b.add_argument('--session', required=True)
    b.add_argument('--force', action='store_true')
    args = ap.parse_args(argv)
    if args.cmd == 'bootstrap':
        return bootstrap(args.datadir, args.session, args.force)
    if args.cmd == 'report':
        rep = build_report(args.datadir, args.html_root, args.since, args.until,
                           haiku_model=args.haiku_model, jev_model=args.jev_model)
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
