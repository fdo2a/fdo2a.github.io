#!/usr/bin/env python3
"""문체 마감(STEP 2.6) guard — 오케스트레이터가 부른다. 모든 출력은 레포 밖 `$CLOSE_DIR` 에만.

  close_guard.py check  PRE CAND EDITS --out $CLOSE_DIR/pairs.json [--market us|kr] [--date D]
                        [--exclude C03,C04] [--expect-pre SHA256] [--expect-cand SHA256] [--datadir DIR]
      → pairs.json, proposed.html(쓰기 단계까지 돈 제안 판), checker_input.txt(검사자에게 줄 글)
  close_guard.py enabled          킬 스위치 — `close: on`(0) | `close: off`(1). off 면 STEP 2.6 을 건너뛴다
  close_guard.py writer-prompt CAND --out $CLOSE_DIR/writer_input.txt   작성자에게 줄 글(§13 + 후보)
  close_guard.py apply  PRE CAND EDITS PAIRS VERDICTS --out $CLOSE_DIR/approved.html
                        --audit $CLOSE_DIR/audit.json [--round 1|2] (check 와 같은 선택 인자)
      → 마지막 줄 `close: applied N` | `close: recheck exclude=C03,C04` | `close: zero (<이유>)`
        applied·zero 는 approved.html 을 쓴다(zero = pre 그대로). recheck 는 쓰지 않는다.
  close_guard.py zero   PRE --out $CLOSE_DIR/approved.html --audit A --outcome <이유>   편집 0 확정
  close_guard.py verify APPROVED (TARGET | --git REV:PATH [--repo R])   노트 블록 뺀 바이트 일치?
  close_guard.py snapshot --repo R --out $CLOSE_DIR/tree_X.json
  close_guard.py leak-compare A B          STEP 2.6 전후 내용 비교
  close_guard.py staged-scan --repo R --audit A   staged 더해진 줄에 감사 지문?
  close_guard.py note --audit A key=value ...      감사 기록에 결과 필드(outcome·published 등)

종료 코드: 0 정상(기각 포함) · 1 verify 불일치·누출 발견 · 2 입력 오류(→ 편집 0) · 3 pre 를 읽거나
approved 를 쓸 수 없음(→ `cp pre <html>` 확인, 안 되면 발행 중단).
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from close import guard, leak, locks, paths  # noqa: E402
from close.flow import sha256  # noqa: E402


class Exit(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def say(msg):
    print(msg, flush=True)


def _read_bytes(path, code):
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except OSError as exc:
        raise Exit(code, '읽을 수 없다: %s (%s)' % (path, exc))


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise Exit(2, 'JSON 을 읽을 수 없다: %s (%s)' % (path, exc))


def _out(path):
    try:
        return paths.check_out(path)
    except paths.PathError as exc:
        raise Exit(2, str(exc))


def _write(path, data, code=3):
    try:
        paths.write_atomic(path, data)
    except OSError as exc:
        raise Exit(code, '쓸 수 없다: %s (%s)' % (path, exc))


def _common(ap):
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    ap.add_argument('--date', default='2099-12-31')
    ap.add_argument('--exclude', default='')
    ap.add_argument('--expect-pre')
    ap.add_argument('--expect-cand')
    ap.add_argument('--datadir')
    ap.add_argument('--root', default=None)
    ap.add_argument('--no-write', action='store_true', help='쓰기 단계 생략(시험용)')


def _build(args):
    pre = _read_bytes(args.pre, 3)
    cand_raw = _read_bytes(args.cand, 2)
    if args.expect_pre and sha256(pre) != args.expect_pre:
        raise Exit(3, 'pre.html 이 오케스트레이터가 쥔 해시와 다르다 — 게이트 통과 판을 잃었다')
    if args.expect_cand and sha256(cand_raw) != args.expect_cand:
        raise Exit(2, 'candidates.json 이 오케스트레이터가 쥔 해시와 다르다')
    try:
        cand = json.loads(cand_raw.decode('utf-8'))
    except ValueError as exc:
        raise Exit(2, 'candidates 를 읽을 수 없다: %s' % exc)
    edits = _read_json(args.edits)
    names = ()
    if args.datadir:
        from review.style_pass import known_names
        names = known_names(pre.decode('utf-8'), args.datadir)
    ledger = locks.Ledger.load(args.root or paths.REPO, args.market, args.date)
    exclude = tuple(x for x in args.exclude.split(',') if x)
    write = None if args.no_write else guard.write_stage(args.market)
    try:
        return pre, guard.build(pre, cand, edits, market=args.market, names=names, ledger=ledger,
                                exclude=exclude, write=write)
    except guard.GuardError as exc:
        raise Exit(2, str(exc))


def cmd_check(args):
    out = _out(args.out)
    folder = os.path.dirname(os.path.abspath(out))
    pre, res = _build(args)
    doc = guard.pairs_doc(res)
    _write(out, json.dumps(doc, ensure_ascii=False, indent=1), 2)
    if res.get('proposed_written') is not None:
        _write(_out(os.path.join(folder, 'proposed.html')), res['proposed_written'], 2)
        _write(_out(os.path.join(folder, 'checker_input.txt')), guard.checker_input(res), 2)
    st = [e['status'] for e in res['edits'].values()]
    say('close: check passed %d rejected %d unchanged %d bundles %d%s' % (
        st.count('passed'), st.count('rejected'), st.count('unchanged'), len(res['bundles']),
        (' fatal=%s' % res['fatal']) if res.get('fatal') else ''))
    return 0


def _load_audit(path, args, pre):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {'uuid': uuid.uuid4().hex, 'market': args.market, 'date': args.date,
            'created': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'source_sha256': sha256(pre), 'rounds': [], 'outcome': None}


def cmd_apply(args):
    out, audit_path = _out(args.out), _out(args.audit)
    pre, res = _build(args)
    pairs = _read_json(args.pairs)
    raw = None
    try:
        with open(args.verdicts, encoding='utf-8') as fh:
            raw = fh.read()
    except OSError:
        raw = None
    if pairs.get('proposed_sha256') != res.get('proposed_sha256') or \
            pairs.get('edits_sha256') != res.get('edits_sha256'):
        status, exclude, per = 'zero', [], {'_': 'pairs.json 이 다시 만든 판과 다르다'}
    else:
        status, exclude, per = guard.decide(res, raw, args.round)
    doc = guard.parse_verdicts(raw) or {}
    audit = _load_audit(audit_path, args, pre)
    audit['rounds'].append({'round': args.round, 'exclude': res['exclude'], 'edits': res['edits'],
                            'bundles': res['bundles'], 'proposed_sha256': res['proposed_sha256'],
                            'fatal': res.get('fatal'), 'verdicts': doc.get('verdicts') or {},
                            'decided': per, 'status': status})
    if status == 'recheck':
        _write(audit_path, json.dumps(audit, ensure_ascii=False, indent=1), 2)
        say('close: recheck exclude=%s' % ','.join(exclude))
        return 0
    if status == 'applied':
        approved = res['proposed_written'].encode('utf-8')
        write = None if args.no_write else guard.write_stage(args.market)
        if write and write(res['proposed_written']) != res['proposed_written']:
            status, approved = 'zero', pre
            per = dict(per, _='쓰기 단계가 멱등이 아니다')
    else:
        approved = pre
    applied = sorted(e for b in res['bundles'] for e in b['edits']) if status == 'applied' else []
    audit['outcome'] = 'applied' if status == 'applied' else (
        'checker_rejected' if per and '_' not in per else 'zero:' + str(per.get('_', res.get('fatal') or 'no_edits')))
    audit['applied_edits'] = applied
    audit['approved_sha256'] = sha256(approved)
    _write(out, approved, 3)
    _write(audit_path, json.dumps(audit, ensure_ascii=False, indent=1), 2)
    say('close: applied %d' % len(applied) if status == 'applied' else 'close: zero (%s)' % audit['outcome'])
    return 0


def cmd_zero(args):
    out, audit_path = _out(args.out), _out(args.audit)
    pre = _read_bytes(args.pre, 3)
    if args.expect_pre and sha256(pre) != args.expect_pre:
        raise Exit(3, 'pre.html 이 오케스트레이터가 쥔 해시와 다르다')
    audit = _load_audit(audit_path, args, pre)
    audit['outcome'] = 'zero:' + args.outcome
    audit['applied_edits'] = []
    audit['approved_sha256'] = sha256(pre)
    _write(out, pre, 3)
    _write(audit_path, json.dumps(audit, ensure_ascii=False, indent=1), 2)
    say('close: zero (%s)' % audit['outcome'])
    return 0


def cmd_verify(args):
    approved = _read_bytes(args.approved, 2).decode('utf-8')
    if args.git:
        r = subprocess.run(['git', '-C', args.repo, 'show', args.git], capture_output=True)
        if r.returncode:
            raise Exit(2, 'git show %s 실패' % args.git)
        target = r.stdout.decode('utf-8')
    elif args.target:
        target = _read_bytes(args.target, 2).decode('utf-8')
    else:
        raise Exit(2, '대상이 없다')
    ok = guard.same_published(approved, target)
    say('close: verify %s' % ('ok' if ok else 'MISMATCH'))
    return 0 if ok else 1


def cmd_snapshot(args):
    out = _out(args.out)
    try:
        snap = leak.snapshot(args.repo)
    except RuntimeError as exc:
        raise Exit(2, str(exc))
    _write(out, leak.dump(snap), 2)
    say('close: snapshot %d entries' % len(snap))
    return 0


def cmd_leak_compare(args):
    diff = leak.compare(_read_json(args.a), _read_json(args.b))
    for k in diff:
        say('  changed: %s' % k)
    say('close: leak-compare %s' % ('clean' if not diff else 'CHANGED %d' % len(diff)))
    return 1 if diff else 0


def cmd_staged_scan(args):
    audit = _read_json(args.audit)
    try:
        hits = leak.staged_hits(args.repo, audit)
    except RuntimeError as exc:
        raise Exit(2, str(exc))
    for p in hits:
        say('  audit fingerprint in: %s' % p)
    say('close: staged-scan %s' % ('clean' if not hits else 'FOUND %d' % len(hits)))
    return 1 if hits else 0


def cmd_note(args):
    path = _out(args.audit)
    audit = _read_json(path) if os.path.exists(path) else {'uuid': uuid.uuid4().hex, 'rounds': []}
    for kv in args.pairs:
        if '=' not in kv:
            raise Exit(2, 'key=value 꼴이 아니다: %s' % kv)
        k, v = kv.split('=', 1)
        audit[k] = v
    _write(path, json.dumps(audit, ensure_ascii=False, indent=1), 2)
    say('close: note %s' % ' '.join(a.split('=', 1)[0] for a in args.pairs))
    return 0


def cmd_enabled(args):
    on = paths.enabled()
    say('close: %s' % ('on' if on else 'off'))
    return 0 if on else 1


def cmd_writer_prompt(args):
    out = _out(args.out)
    cand = _read_json(args.cand)
    rules = guard.closing_rules(args.exemplars)
    _write(out, guard.writer_input(cand, rules), 2)
    say('close: writer-prompt %d candidates' % len(cand.get('items', [])))
    return 0


def parser():
    ap = argparse.ArgumentParser(prog='close_guard.py')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('check')
    p.add_argument('pre')
    p.add_argument('cand')
    p.add_argument('edits')
    p.add_argument('--out', required=True)
    _common(p)
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser('enabled')
    p.set_defaults(fn=cmd_enabled)
    p = sub.add_parser('writer-prompt')
    p.add_argument('cand')
    p.add_argument('--out', required=True)
    p.add_argument('--exemplars', default=os.path.join(paths.REPO, '.claude', 'agents', guard.EXEMPLARS))
    p.set_defaults(fn=cmd_writer_prompt)
    p = sub.add_parser('apply')
    for a in ('pre', 'cand', 'edits', 'pairs', 'verdicts'):
        p.add_argument(a)
    p.add_argument('--out', required=True)
    p.add_argument('--audit', required=True)
    p.add_argument('--round', type=int, choices=(1, 2), default=1)
    _common(p)
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser('zero')
    p.add_argument('pre')
    p.add_argument('--out', required=True)
    p.add_argument('--audit', required=True)
    p.add_argument('--outcome', required=True)
    _common(p)
    p.set_defaults(fn=cmd_zero)
    p = sub.add_parser('verify')
    p.add_argument('approved')
    p.add_argument('target', nargs='?')
    p.add_argument('--git')
    p.add_argument('--repo', default='.')
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser('snapshot')
    p.add_argument('--repo', default='.')
    p.add_argument('--out', required=True)
    p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser('leak-compare')
    p.add_argument('a')
    p.add_argument('b')
    p.set_defaults(fn=cmd_leak_compare)
    p = sub.add_parser('staged-scan')
    p.add_argument('--repo', default='.')
    p.add_argument('--audit', required=True)
    p.set_defaults(fn=cmd_staged_scan)
    p = sub.add_parser('note')
    p.add_argument('--audit', required=True)
    p.add_argument('pairs', nargs='+')
    p.set_defaults(fn=cmd_note)
    return ap


def main(argv=None):
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        return args.fn(args)
    except Exit as exc:
        say('close: error (%s)' % exc)
        return exc.code
    except Exception as exc:  # 예상 못 한 예외 = 입력 오류로 본다 — 편집 0 으로 진행
        say('close: error (%s: %s)' % (type(exc).__name__, exc))
        return 2


if __name__ == '__main__':
    sys.exit(main())
