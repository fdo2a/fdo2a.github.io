#!/usr/bin/env python3
"""발행 전 codex 검토 — 루틴이 부르는 진입점(절차: `.claude/PREPUB_REVIEW.md`).

  prepub_review.py submit --section us|kr --date D --html H --notes research_notes.md --out DIR [--deadline-min 25]
      묶음 → review-drafts push → 비공개 워크플로 기동. `prepub: submitted rid=…` (exit 0) 또는
      `prepub: fallback submit_failed …` (exit 10). 마감 시각(절대)을 DIR/status.json 에 적는다.
  prepub_review.py wait --dir DIR [--minutes 9]
      결과를 최대 N 분 기다린다(루틴의 Bash 한 번은 10분까지라 나눠 부른다).
      `prepub: reviewed` (exit 0, DIR/review.md) · `prepub: waiting` (exit 11, 다시 부른다) ·
      `prepub: fallback <state>` (exit 10 — 마감·한도·실패·불일치).
  prepub_review.py split --review DIR/review.md --html H --section us|kr --date D --out DIR
      → DIR/facts.md(정확성 몫), DIR/candidates.json(문체 후보, STYLE_CLOSE 형식), DIR/split.json
  prepub_review.py merge-verdicts --pairs pairs.json --first v1.json --second v2.json --out verdicts.json
      판단 문장 낱말까지 바뀐 묶음(`judgment: true`)은 두 번의 의미 검사가 **둘 다 same** 일 때만 same.
      나머지 묶음은 첫 검사를 따른다. 두 답의 proposed_sha256 이 pairs 와 다르면 exit 2.
  prepub_review.py record --dir DIR --section us|kr --date D [--facts-applied N] [--facts-rejected N]
                          [--style-applied N] [--style-rejected N]
      → reviews/prepublish/<section>/<date>.json (발행 커밋에 함께 넣는다)

fallback 은 실패가 아니다 — 그날 글은 지금처럼 발행되고 맥 러너가 발행 뒤에 본다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prepub import bundle as bundle_mod  # noqa: E402
from prepub import submit as submit_mod  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLBACK = 10
WAITING = 11


def _write(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def _now():
    import time
    return time.time()


def cmd_submit(a):
    os.makedirs(a.out, exist_ok=True)
    status = {'section': a.section, 'date': a.date, 'state': 'fallback'}
    import shutil
    try:
        # 무엇보다 먼저 — 검토가 실패하거나 고치다 막히면 이 판으로 되돌린다(codex 구현 #7, 재검토 #7)
        shutil.copyfile(a.html, os.path.join(a.out, 'original.html'))
        notes = a.notes if a.notes and os.path.isfile(a.notes) else None
        status['notes'] = bool(notes)
        man = bundle_mod.build(ROOT, a.section, a.date, a.html, os.path.join(a.out, 'bundle'),
                               notes_path=notes)
        status['request_id'] = rid = man['request_id']
        status['source_html_sha256'] = man['source_html_sha256']
        status['draft_sha'] = sha = submit_mod.push_bundle(ROOT, os.path.join(a.out, 'bundle'), rid)
        submit_mod.dispatch(rid, sha)
    except (bundle_mod.BundleError, submit_mod.SubmitError, OSError) as exc:
        status.update(state='submit_failed', reason=str(exc)[:300])
        _write(os.path.join(a.out, 'status.json'), status)
        print(f'prepub: fallback submit_failed {str(exc)[:160]}')
        return FALLBACK
    status.update(state='submitted', deadline=_now() + a.deadline_min * 60)
    _write(os.path.join(a.out, 'status.json'), status)
    print(f'prepub: submitted rid={rid}')
    return 0


def cmd_wait(a):
    path = os.path.join(a.dir, 'status.json')
    try:
        with open(path, encoding='utf-8') as fh:
            status = json.load(fh)
    except (OSError, ValueError):
        print('prepub: fallback no_status')
        return FALLBACK
    if status.get('state') != 'submitted':
        print(f"prepub: {'reviewed' if status.get('state') == 'reviewed' else 'fallback ' + str(status.get('state'))}")
        return 0 if status.get('state') == 'reviewed' else FALLBACK
    left = float(status.get('deadline', 0)) - _now()
    budget = min(left, a.minutes * 60)
    state, res = (submit_mod.wait(status['request_id'], status['draft_sha'], budget)
                  if budget > 0 else ('timeout', None))
    if res is not None:
        _write(os.path.join(a.dir, 'result.json'), res)
        status['auth_saved'] = res.get('auth_saved')
    if state == 'timeout' and left > budget:
        _write(path, status)
        print('prepub: waiting')
        return WAITING
    if state != 'reviewed':
        status.update(state=state, reason=str((res or {}).get('error', ''))[:300])
        _write(path, status)
        print(f"prepub: fallback {state} {status['reason'][:160]}".rstrip())
        return FALLBACK
    with open(os.path.join(a.dir, 'review.md'), 'w', encoding='utf-8') as fh:
        fh.write(res.get('review') or '')
    status['state'] = 'reviewed'
    _write(path, status)
    print(f"prepub: reviewed rid={status['request_id']}")
    return 0


def cmd_split(a):
    import hashlib
    from close import locks
    from prepub import split as split_mod
    with open(a.review, encoding='utf-8') as fh:
        review = fh.read()
    with open(a.html, 'rb') as fh:
        raw = fh.read()
    html = raw.decode('utf-8')
    if not a.after_fixes:
        # 검토 결과는 제출한 판에 대한 것이다 — 그 사이 글이 바뀌었으면 적용하지 않는다(codex 구현 #6)
        try:
            with open(os.path.join(a.out, 'status.json'), encoding='utf-8') as fh:
                want = json.load(fh).get('source_html_sha256')
        except (OSError, ValueError):
            want = None
        if want != hashlib.sha256(raw).hexdigest():
            print('prepub: fallback stale_html — 제출한 판과 지금 판이 다르다')
            return FALLBACK
    ledger = locks.Ledger.load(ROOT, a.section, a.date)
    got = split_mod.split(review, html, ledger)
    os.makedirs(a.out, exist_ok=True)
    lines = [got['facts'].rstrip(), '']
    if got['accuracy']:
        lines.append('=== 확신도 지적(근거와 대조해 정확성 오류로 판정) ===')
        lines += [f"- [{f['kind']}] 「{f['quote']}」 — {f['note']}" for f in got['accuracy']]
    with open(os.path.join(a.out, 'facts.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    _write(os.path.join(a.out, 'candidates.json'), got['candidates'])
    summary = {k: got[k] for k in ('accuracy', 'unplaced', 'excluded')}
    summary['candidates'] = len(got['candidates']['items'])
    summary['style_findings'] = got['style']
    _write(os.path.join(a.out, 'split.json'), summary)
    print(f"prepub: accuracy {len(got['accuracy'])} · style candidates {summary['candidates']} · "
          f"excluded {len(got['excluded'])} · unplaced {len(got['unplaced'])}")
    return 0


def merge_verdicts(pairs, first, second):
    sha = pairs.get('proposed_sha256')
    if not sha or first.get('proposed_sha256') != sha or second.get('proposed_sha256') != sha:
        raise ValueError('의미 검사 답이 다른 판에 대한 것이다')
    v1, v2 = first.get('verdicts') or {}, second.get('verdicts') or {}
    out = {}
    for b in pairs.get('bundles', []):
        bid = b['id']
        a = (v1.get(bid) or {}).get('verdict', 'unsure')
        if not b.get('judgment'):
            out[bid] = v1.get(bid) or {'verdict': 'unsure', 'why': '첫 검사에 답 없음'}
            continue
        c = (v2.get(bid) or {}).get('verdict', 'unsure')
        if a == c == 'same':
            out[bid] = {'verdict': 'same', 'why': '판단 문장 — 두 검사 모두 same'}
        elif 'changed' in (a, c):
            out[bid] = {'verdict': 'changed', 'why': f'판단 문장 — {a}/{c}'}
        else:
            out[bid] = {'verdict': 'unsure', 'why': f'판단 문장 — {a}/{c}'}
    return {'proposed_sha256': sha, 'verdicts': out}


def cmd_merge(a):
    try:
        docs = [json.load(open(p, encoding='utf-8')) for p in (a.pairs, a.first, a.second)]
        merged = merge_verdicts(*docs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'prepub: merge failed {exc}')
        return 2
    _write(a.out, merged)
    j = sum(1 for b in docs[0].get('bundles', []) if b.get('judgment'))
    same = sum(1 for v in merged['verdicts'].values() if v['verdict'] == 'same')
    print(f'prepub: merged {len(merged["verdicts"])} bundles (judgment {j}) · same {same}')
    return 0


_BLOB = __import__('re').compile(r'[A-Za-z0-9+/_=-]{40,}')
PUBLIC_REASON = {
    'reviewed': '', 'submit_failed': '초안을 올리거나 검토를 띄우지 못했다', 'timeout': '마감까지 검토가 오지 않았다',
    'limit': 'codex 사용 한도', 'failed': '검토 실행 실패', 'mismatch': '다른 초안의 결과',
    'stale_html': '기다리는 사이 초안이 바뀌었다', 'not_reviewed': 'codex 가 검토하지 못했다',
    'suspicious_output': '검토 답을 버렸다(인코딩 덩어리)', 'sandbox_failed': '검토 샌드박스 실패',
    'manifest_mismatch': '묶음 해시 불일치', 'auth_missing': '로그인 비밀값 없음', 'bad_input': '입력 형식 오류',
    'fix_failed': '고치다 막혀 원래 판으로 발행',
}


def _public_findings(findings, post_text=''):
    """공개 기록에 남길 문체 지적 — **분류와, 발행본에 실제로 있는 인용만**(codex 구현 재검토 3차 #1).

    codex 의 자유 텍스트(방향·설명)는 공개 레포로 내보내지 않는다 — 인코딩 필터로는 모든 유출을 못 막는다.
    인용은 글에 그대로 있는 문장 조각일 때만 남긴다(글에 없는 글자는 실리지 않는다). 방향은 비공개 결과에만 있다.
    """
    norm = ' '.join((post_text or '').split())
    out = []
    for f in findings or ():
        quote = ' '.join(str(f.get('quote') or '').split())[:40]
        out.append({'kind': f.get('kind'), 'quote': quote if quote and quote in norm else ''})
    return out


def _post_text(folder):
    """제출한 판의 본문 글자(태그 뺌) — 인용이 글에 있는지 대조한다."""
    import re
    try:
        with open(os.path.join(folder, 'original.html'), encoding='utf-8') as fh:
            return re.sub(r'<[^>]+>', ' ', fh.read())
    except OSError:
        return ''


def cmd_record(a):
    try:
        with open(os.path.join(a.dir, 'status.json'), encoding='utf-8') as fh:
            status = json.load(fh)
    except (OSError, ValueError):
        status = {'state': 'fallback', 'reason': 'status.json 없음'}
    try:
        with open(os.path.join(a.dir, 'split.json'), encoding='utf-8') as fh:
            split = json.load(fh)
    except (OSError, ValueError):
        split = {}
    state = a.state or status.get('state')
    # 공개 기록의 이유는 우리가 만든 상태 이름뿐이다 — codex·러너 출력은 옮기지 않는다(codex 구현 재검토 #1)
    rec = {'section': a.section, 'date': a.date, 'request_id': status.get('request_id'),
           'draft_sha': status.get('draft_sha'), 'state': state,
           'reason': PUBLIC_REASON.get(state, ''), 'auth_saved': status.get('auth_saved'),
           'accuracy_findings': len(split.get('accuracy', [])),
           'style_candidates': split.get('candidates', 0),
           'style_excluded': len(split.get('excluded', [])),
           'style_unplaced': len(split.get('unplaced', [])),
           'facts_applied': a.facts_applied, 'facts_rejected': a.facts_rejected,
           'style_applied': a.style_applied, 'style_rejected': a.style_rejected,
           'skeleton_rejected': a.skeleton_rejected, 'checker_rejected': a.checker_rejected,
           # 주간 묶음(`scripts/review/style_digest.py`)이 읽는다 — 반복되는 꼴을 예문으로 되먹인다
           'style_findings': _public_findings(split.get('style_findings', []), _post_text(a.dir)),
           'recorded_at': __import__('datetime').datetime.now(
               __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    folder = os.path.join(ROOT, 'reviews', 'prepublish', a.section)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{a.date}.json')
    _write(path, rec)
    print(f"prepub: recorded {os.path.relpath(path, ROOT)} state={rec['state']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='prepub_review.py')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('submit')
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--notes', default=None, help='작성자가 읽은 research_notes.md')
    p.add_argument('--out', required=True)
    p.add_argument('--deadline-min', type=int, default=25)
    p = sub.add_parser('wait')
    p.add_argument('--dir', required=True)
    p.add_argument('--minutes', type=float, default=9)
    p = sub.add_parser('split')
    p.add_argument('--review', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--after-fixes', action='store_true',
                   help='정확성 수정 뒤의 최종 판으로 다시 나눌 때 — 제출 판 해시 대조를 건너뛴다')
    p = sub.add_parser('merge-verdicts')
    p.add_argument('--pairs', required=True)
    p.add_argument('--first', required=True)
    p.add_argument('--second', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('record')
    p.add_argument('--dir', required=True)
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    p.add_argument('--state', default=None, choices=('fix_failed',),
                   help='검토는 왔지만 고치다 막혀 원래 판으로 발행할 때')
    for k in ('facts-applied', 'facts-rejected', 'style-applied', 'style-rejected',
              'skeleton-rejected', 'checker-rejected'):
        p.add_argument(f'--{k}', type=int, default=0)
    a = ap.parse_args(argv)
    return {'submit': cmd_submit, 'wait': cmd_wait, 'split': cmd_split,
            'merge-verdicts': cmd_merge, 'record': cmd_record}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
