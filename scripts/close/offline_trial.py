#!/usr/bin/env python3
"""문체 마감 오프라인 시험 — 로컬 전용. 공개 레포에는 아무것도 쓰지 않는다(출력은 레포 밖 --out).

  offline_trial.py run    --out DIR --posts posts/2026-10-21.html kr/posts/2026-10-22.html ...
  offline_trial.py report --out DIR          비용·반영 집계(report.json, report.md)
  offline_trial.py sheets --out DIR [--artificial A.json]   사람 판정지 judge.html + key.json(눈가림)
  offline_trial.py score  --out DIR --answers answers.json  사람 판정 → 의미·가독성 숫자

`run` 은 STEP 2.6 과 같은 순서를 글마다 돈다: 후보 → 작성자(`claude -p --model opus`, 시스템
프롬프트 = 작성자 정의 파일, 도구 = 정의 머리말 그대로) → guard check(쓰기 단계 포함) → 검사자(정의
파일, 도구 없음) → apply → 필요하면 재검사 1회. 호출마다 `usage`(입력·캐시 생성·캐시 읽기·출력)와
`total_cost_usd` 를 calls.jsonl 에 남긴다. 게이트 재실행·누출 검사·감사 업로드는 돌리지 않는다(토큰을
쓰지 않는 결정적 단계).
"""

import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from close import flow, guard, locks, paths  # noqa: E402

REPO = paths.REPO
AGENTS = os.path.join(REPO, '.claude', 'agents')
WRITER = {'us': 'brief-report-writer.md', 'kr': 'kr-report-writer.md'}
CHECKER = 'close-meaning-checker.md'
MODEL = os.environ.get('TRIAL_MODEL', 'opus')


def _front(path):
    text = open(path, encoding='utf-8').read()
    m = re.match(r'---\n(.*?)\n---\n', text, re.S)
    head = dict(l.split(':', 1) for l in m.group(1).splitlines() if ':' in l) if m else {}
    return {k.strip(): v.strip() for k, v in head.items()}, (text[m.end():] if m else text)


def market_of(path):
    return 'kr' if path.startswith('kr/') else 'us'


def date_of(path):
    return re.search(r'(\d{4}-\d{2}-\d{2})', path).group(1)


def claude(system_file, prompt, tools, cwd, model=MODEL, timeout=600):
    """→ dict(text, usage, cost, ms, ok, error). 실패해도 예외를 내지 않는다(그 단계 편집 0)."""
    cmd = ['claude', '-p', '--model', model, '--output-format', 'json', '--system-prompt-file', system_file,
           '--tools', tools, '--strict-mcp-config', '--setting-sources', '', '--no-session-persistence']
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        doc = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        return {'text': '', 'usage': {}, 'cost': 0.0, 'ms': int((time.time() - t0) * 1000), 'ok': False,
                'error': '%s: %s' % (type(exc).__name__, exc)}
    return {'text': doc.get('result') or '', 'usage': doc.get('usage') or {}, 'cost': doc.get('total_cost_usd') or 0.0,
            'ms': int((time.time() - t0) * 1000), 'ok': not doc.get('is_error'), 'turns': doc.get('num_turns'),
            'model_usage': doc.get('modelUsage'), 'error': doc.get('api_error_status')}


def _sysfile(out, name):
    """정의 파일의 머리말을 뗀 본문을 시스템 프롬프트 파일로."""
    head, body = _front(os.path.join(AGENTS, name))
    path = os.path.join(out, 'sys_' + name)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)
    return path, head


def _log(out, row):
    with open(os.path.join(out, 'calls.jsonl'), 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def tokens(u):
    return sum(int(u.get(k) or 0) for k in ('input_tokens', 'cache_creation_input_tokens',
                                            'cache_read_input_tokens', 'output_tokens'))


LEAN_SYS = ('너는 이 시황 보고서(PM 이 읽는 데스크 문서, 어미 -다)를 쓴 작성자다. 지금은 마감 편집만 한다. '
            '프롬프트의 규칙과 후보 문단만 보고 JSON 하나로 답한다. 파일을 읽거나 쓰지 않는다.')


def run_post(path, out, sandbox, lean=False):
    market, date = market_of(path), date_of(path)
    key = '%s_%s' % (market, date)
    d = os.path.join(out, 'runs', key)
    os.makedirs(d, exist_ok=True)
    pre = open(os.path.join(REPO, path), 'rb').read()
    html = pre.decode('utf-8')
    ledger = locks.Ledger.load(REPO, market, date)
    cand = flow.scan(html, ledger)
    rec = {'post': path, 'market': market, 'date': date, 'candidates': len(cand['items']),
           'skipped': cand['skipped'], 'outcome': None, 'rounds': []}
    json.dump(cand, open(os.path.join(d, 'candidates.json'), 'w'), ensure_ascii=False, indent=1)
    if not cand['items']:
        rec['outcome'] = 'no_candidates'
        return rec
    wsys, whead = _sysfile(out, WRITER[market])
    if lean:            # 비교 변형 — 작성자 정의 대신 짧은 역할 한 줄(규칙은 프롬프트의 §13 그대로)
        wsys, whead = os.path.join(out, 'sys_lean.md'), {'tools': ''}
        open(wsys, 'w', encoding='utf-8').write(LEAN_SYS)
    csys, _ = _sysfile(out, CHECKER)
    rules = guard.closing_rules(os.path.join(AGENTS, guard.EXEMPLARS))
    wprompt = guard.writer_input(cand, rules)
    open(os.path.join(d, 'writer_input.txt'), 'w').write(wprompt)
    w = claude(wsys, wprompt, whead.get('tools', '').replace(' ', ''), sandbox)
    _log(out, {'post': path, 'role': 'writer', 'round': 1, **{k: w[k] for k in ('usage', 'cost', 'ms', 'ok', 'error')},
               'turns': w.get('turns')})
    open(os.path.join(d, 'writer_reply.txt'), 'w').write(w['text'])
    edits = guard.parse_verdicts(w['text'])     # 같은 JSON 추출기
    if not w['ok'] or edits is None:
        rec['outcome'] = 'writer_failed'
        return rec
    rec['writer_edits'] = sum(1 for k, v in edits.items() if isinstance(v, str))
    json.dump(edits, open(os.path.join(d, 'edits.json'), 'w'), ensure_ascii=False, indent=1)
    write = guard.write_stage(market)
    exclude = ()
    for round_no in (1, 2):
        res = guard.build(pre, cand, edits, market=market, ledger=ledger, exclude=exclude, write=write)
        info = {'round': round_no, 'exclude': list(exclude), 'edits': res['edits'], 'fatal': res.get('fatal'),
                'bundles': res['bundles']}
        if res.get('fatal') or not res['bundles']:
            info['status'] = 'zero'
            rec['rounds'].append(info)
            rec['outcome'] = 'zero:' + (res.get('fatal') or 'no_bundles')
            break
        cin = guard.checker_input(res)
        open(os.path.join(d, 'checker_input_%d.txt' % round_no), 'w').write(cin)
        c = claude(csys, cin, '', sandbox)
        _log(out, {'post': path, 'role': 'checker', 'round': round_no,
                   **{k: c[k] for k in ('usage', 'cost', 'ms', 'ok', 'error')}, 'turns': c.get('turns'),
                   'bundles': len(res['bundles'])})
        open(os.path.join(d, 'checker_reply_%d.txt' % round_no), 'w').write(c['text'])
        status, excl, per = guard.decide(res, c['text'] if c['ok'] else None, round_no)
        doc = guard.parse_verdicts(c['text']) or {}
        info.update({'status': status, 'decided': per, 'verdicts': doc.get('verdicts') or {}})
        rec['rounds'].append(info)
        if status == 'applied':
            rec['outcome'] = 'applied'
            rec['applied'] = [b for b in res['bundles']]
            open(os.path.join(d, 'approved.html'), 'w').write(res['proposed_written'])
            break
        if status == 'zero':
            rec['outcome'] = 'checker_rejected' if per and '_' not in per else 'zero:verdicts'
            break
        exclude = tuple(excl)
    return rec


def cmd_run(args):
    out = os.path.abspath(args.out)
    paths.check_out(out, close_dir=None)
    os.makedirs(out, exist_ok=True)
    sandbox = os.path.join(out, 'sandbox')
    os.makedirs(sandbox, exist_ok=True)
    done = os.path.join(out, 'posts.jsonl')
    have = set()
    if os.path.exists(done):
        have = {json.loads(l)['post'] for l in open(done, encoding='utf-8')}
    for p in args.posts:
        if p in have:
            continue
        print('[trial] %s' % p, flush=True)
        rec = run_post(p, out, sandbox, lean=args.lean)
        rec['at'] = datetime.datetime.now().isoformat(timespec='seconds')
        with open(done, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print('  → %s (후보 %d)' % (rec['outcome'], rec['candidates']), flush=True)
    return 0


def _load(out):
    posts = [json.loads(l) for l in open(os.path.join(out, 'posts.jsonl'), encoding='utf-8')]
    calls = [json.loads(l) for l in open(os.path.join(out, 'calls.jsonl'), encoding='utf-8')] \
        if os.path.exists(os.path.join(out, 'calls.jsonl')) else []
    return posts, calls


def cmd_report(args):
    out = os.path.abspath(args.out)
    posts, calls = _load(out)
    per = {}
    for c in calls:
        p = per.setdefault(c['post'], {'tokens': 0, 'cost': 0.0, 'calls': 0, 'by_role': {}})
        t = tokens(c['usage'])
        p['tokens'] += t
        p['cost'] += c['cost'] or 0
        p['calls'] += 1
        r = p['by_role'].setdefault(c['role'], {'tokens': 0, 'input': 0, 'cache_creation': 0, 'cache_read': 0,
                                                'output': 0, 'calls': 0})
        r['tokens'] += t
        r['calls'] += 1
        for k, kk in (('input', 'input_tokens'), ('cache_creation', 'cache_creation_input_tokens'),
                      ('cache_read', 'cache_read_input_tokens'), ('output', 'output_tokens')):
            r[k] += int(c['usage'].get(kk) or 0)
    rows, mk = [], {'us': [], 'kr': []}
    stats = {'posts': len(posts), 'candidates': 0, 'writer_edits': 0, 'guard_rejected': 0, 'guard_passed': 0,
             'checker_rejected_bundles': 0, 'applied_edits': 0, 'applied_bundles': 0, 'outcomes': {}}
    for p in posts:
        u = per.get(p['post'], {'tokens': 0, 'cost': 0.0, 'calls': 0, 'by_role': {}})
        mk[p['market']].append(u)
        stats['candidates'] += p['candidates']
        stats['writer_edits'] += p.get('writer_edits', 0)
        stats['outcomes'][p['outcome']] = stats['outcomes'].get(p['outcome'], 0) + 1
        if p['rounds']:
            first = p['rounds'][0]['edits']
            stats['guard_rejected'] += sum(1 for e in first.values() if e['status'] == 'rejected')
            stats['guard_passed'] += sum(1 for e in first.values() if e['status'] == 'passed')
            for r in p['rounds']:
                stats['checker_rejected_bundles'] += sum(1 for v in (r.get('decided') or {}).values()
                                                         if v in ('changed', 'unsure'))
        for b in p.get('applied', []):
            stats['applied_bundles'] += 1
            stats['applied_edits'] += len(b['edits'])
        rows.append({'post': p['post'], 'outcome': p['outcome'], 'candidates': p['candidates'],
                     'writer_edits': p.get('writer_edits', 0),
                     'applied': sum(len(b['edits']) for b in p.get('applied', [])), **u})

    def avg(xs, k):
        return sum(x[k] for x in xs) / len(xs) if xs else 0
    daily = {m: {'tokens': avg(v, 'tokens'), 'cost': avg(v, 'cost'), 'posts': len(v)} for m, v in mk.items()}
    daily['us+kr'] = {'tokens': daily['us']['tokens'] + daily['kr']['tokens'],
                      'cost': daily['us']['cost'] + daily['kr']['cost']}
    rep = {'stats': stats, 'daily': daily, 'rows': rows}
    json.dump(rep, open(os.path.join(out, 'report.json'), 'w'), ensure_ascii=False, indent=1)
    lines = ['# 오프라인 시험 집계', '', '| 글 | 결과 | 후보 | 작성자 편집 | 반영 | 호출 | 토큰 | USD |', '|---|---|---|---|---|---|---|---|']
    for r in rows:
        lines.append('| %s | %s | %d | %d | %d | %d | %d | %.3f |' % (
            r['post'], r['outcome'], r['candidates'], r['writer_edits'], r['applied'], r['calls'], r['tokens'],
            r['cost']))
    lines += ['', '하루(글당 평균): US %.0f 토큰 $%.3f · KR %.0f 토큰 $%.3f · 합 %.0f 토큰 $%.3f' % (
        daily['us']['tokens'], daily['us']['cost'], daily['kr']['tokens'], daily['kr']['cost'],
        daily['us+kr']['tokens'], daily['us+kr']['cost']), '', json.dumps(stats, ensure_ascii=False)]
    open(os.path.join(out, 'report.md'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines[-3:]))
    return 0


# ---------------------------------------------------------------- 사람 판정지

def _items(out, artificial=None, rejected_sample=10, seed=20261106):
    posts, _ = _load(out)
    rnd = random.Random(seed)
    items = []
    for p in posts:
        for b in p.get('applied', []):
            items.append({'src': 'real_applied', 'post': p['post'], 'bundle': b})
        for r in p['rounds']:
            for b in r['bundles']:
                if (r.get('decided') or {}).get(b['id']) in ('changed', 'unsure'):
                    items.append({'src': 'real_rejected', 'post': p['post'], 'bundle': b,
                                  'checker': r['verdicts'].get(b['id'])})
    rej = [i for i in items if i['src'] == 'real_rejected']
    keep = [i for i in items if i['src'] == 'real_applied'] + rnd.sample(rej, min(rejected_sample, len(rej)))
    if artificial:
        for a in json.load(open(artificial, encoding='utf-8')):
            keep.append({'src': 'artificial', 'post': a['post'], 'bundle': {
                'title': a.get('title', ''), 'prev': a.get('prev', ''), 'next': a.get('next', ''),
                'before': [a['before']], 'after': [a['after']]}, 'meta': a})
    rnd.shuffle(keep)
    return keep


def cmd_sheets(args):
    out = os.path.abspath(args.out)
    items = _items(out, args.artificial)
    rnd = random.Random(7)
    key, cards = [], []
    for n, it in enumerate(items, 1):
        flip = rnd.random() < 0.5
        b = it['bundle']
        a_txt, b_txt = (b['after'], b['before']) if flip else (b['before'], b['after'])
        qid = 'Q%03d' % n
        key.append({'id': qid, 'src': it['src'], 'post': it['post'], 'A_is': 'after' if flip else 'before',
                    'checker': it.get('checker'), 'meta': it.get('meta')})
        cards.append({'id': qid, 'title': b.get('title', ''), 'prev': b.get('prev', ''), 'next': b.get('next', ''),
                      'A': a_txt, 'B': b_txt, 'readability': it['src'] != 'artificial'})
    json.dump(key, open(os.path.join(out, 'key.json'), 'w'), ensure_ascii=False, indent=1)
    page = JUDGE_HTML.replace('/*CARDS*/', json.dumps(cards, ensure_ascii=False))
    open(os.path.join(out, 'judge.html'), 'w').write(page)
    print('판정지 %d문항 → %s' % (len(cards), os.path.join(out, 'judge.html')))
    return 0


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def cmd_score(args):
    out = os.path.abspath(args.out)
    key = {k['id']: k for k in json.load(open(os.path.join(out, 'key.json'), encoding='utf-8'))}
    ans = json.load(open(args.answers, encoding='utf-8'))
    res = {'real_applied': {'n': 0, 'changed': 0, 'better': 0, 'same': 0, 'worse': 0},
           'real_rejected': {'n': 0, 'changed': 0}, 'artificial': {}}
    for qid, a in ans.items():
        k = key.get(qid)
        if not k:
            continue
        meaning = a.get('meaning')           # same | changed
        pick = a.get('read')                 # A | B | none
        if k['src'] == 'real_applied':
            r = res['real_applied']
            r['n'] += 1
            r['changed'] += meaning == 'changed'
            if pick in ('A', 'B'):
                after_won = (pick == 'A') == (k['A_is'] == 'after')
                r['better' if after_won else 'worse'] += 1
            elif pick == 'none':
                r['same'] += 1
        elif k['src'] == 'real_rejected':
            res['real_rejected']['n'] += 1
            res['real_rejected']['changed'] += meaning == 'changed'
        else:
            m = k.get('meta') or {}
            g = res['artificial'].setdefault(meaning or '?', {'n': 0, 'blocked': 0})
            g['n'] += 1
            g['blocked'] += bool(m.get('blocked'))
    ra = res['real_applied']
    if ra['n']:
        ra['better_rate'] = ra['better'] / ra['n']
        ra['worse_rate'] = ra['worse'] / ra['n']
        ra['unneeded_rate'] = (ra['same'] + ra['worse']) / ra['n']
        ra['changed_upper95'] = wilson(ra['changed'], ra['n'])[1]
        ra['pass'] = (ra['changed'] == 0 and ra['better_rate'] >= 0.6 and ra['worse_rate'] <= 0.1
                      and ra['unneeded_rate'] <= 0.4)
    for g in res['artificial'].values():
        g['blocked_rate'] = g['blocked'] / g['n'] if g['n'] else 0
        g['ci95'] = wilson(g['blocked'], g['n'])
    json.dump(res, open(os.path.join(out, 'score.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


JUDGE_HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>문체 마감 판정</title><style>
:root{--bg:#F2F4F6;--card:#fff;--ink:#191F28;--sub:#4E5968;--line:#E5E8EB;--blue:#0064FF}
@media (prefers-color-scheme:dark){:root{--bg:#101215;--card:#1b1e23;--ink:#e8eaed;--sub:#a3abb5;--line:#2c3036}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Pretendard,-apple-system,'Apple SD Gothic Neo',sans-serif;word-break:keep-all;line-height:1.7}
main{max-width:860px;margin:0 auto;padding:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:0 0 16px}
.ctx{color:var(--sub);font-size:14px}.ab{display:grid;grid-template-columns:1fr;gap:10px;margin:10px 0}.ab div{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.ab b{color:var(--blue)}.q{margin:8px 0}.q label{margin-right:14px;white-space:nowrap}header{position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:2}
button{background:var(--blue);color:#fff;border:0;border-radius:10px;padding:8px 14px;font-size:15px}
</style></head><body><main><header><b>문체 마감 판정</b> — 각 문항에서 ① 두 글의 의미(사실·주장·귀속·관계·세기·조건·한계)가 같은가 ② (있으면) 어느 쪽이 읽기 쉬운가.
어느 쪽이 원문인지는 알리지 않는다. 답은 이 브라우저에 저장된다. <span id="n"></span> <button onclick="exp()">답 내보내기(JSON)</button></header><div id="list"></div></main>
<script>
const CARDS=/*CARDS*/;const KEY='close-judge-v1';let A={};try{A=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(A))}catch(e){}cnt()}
function cnt(){const d=CARDS.filter(c=>A[c.id]&&A[c.id].meaning&&(!c.readability||A[c.id].read)).length;document.getElementById('n').textContent=d+' / '+CARDS.length}
function esc(s){return String(s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]))}
function radio(id,k,v,l){const c=(A[id]||{})[k]===v?'checked':'';return `<label><input type=radio name="${id}-${k}" ${c} onchange="set('${id}','${k}','${v}')"> ${l}</label>`}
function set(id,k,v){A[id]=A[id]||{};A[id][k]=v;save()}
document.getElementById('list').innerHTML=CARDS.map(c=>`<section class=card><div class=ctx><b>${c.id}</b> ${esc(c.title||'')}</div>
<div class=ctx>앞 문단: ${esc(c.prev||'(없음)')}</div><div class=ab><div><b>A</b> ${c.A.map(esc).join('<br><br>')}</div><div><b>B</b> ${c.B.map(esc).join('<br><br>')}</div></div>
<div class=ctx>뒤 문단: ${esc(c.next||'(없음)')}</div>
<div class=q>① 의미: ${radio(c.id,'meaning','same','같다')}${radio(c.id,'meaning','changed','달라졌다')}</div>
${c.readability?`<div class=q>② 읽기: ${radio(c.id,'read','A','A가 확실히 낫다')}${radio(c.id,'read','none','차이 없음')}${radio(c.id,'read','B','B가 확실히 낫다')}</div>`:''}
<div class=q><input placeholder="메모(선택)" style="width:100%" value="${esc((A[c.id]||{}).note||'')}" onchange="set('${c.id}','note',this.value)"></div></section>`).join('');cnt();
function exp(){const b=new Blob([JSON.stringify(A,null,1)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='answers.json';a.click()}
</script></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('run')
    p.add_argument('--out', required=True)
    p.add_argument('--posts', nargs='+', required=True)
    p.add_argument('--lean', action='store_true', help='작성자 정의 대신 짧은 역할 프롬프트(비용 비교용)')
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser('report')
    p.add_argument('--out', required=True)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser('sheets')
    p.add_argument('--out', required=True)
    p.add_argument('--artificial')
    p.set_defaults(fn=cmd_sheets)
    p = sub.add_parser('score')
    p.add_argument('--out', required=True)
    p.add_argument('--answers', required=True)
    p.set_defaults(fn=cmd_score)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
