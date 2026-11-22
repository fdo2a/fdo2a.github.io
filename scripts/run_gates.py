#!/usr/bin/env python3
"""발행 게이트 실행·기록·짝 확인 — 실행 목록은 `config/prepub_gates.json` 하나 (2026-11-08).

  # 반복 고리(초안을 고칠 때마다) — 실행 목록을 돌리고 출력을 그대로 보인다. 기록하지 않는다.
  python3 scripts/run_gates.py check  --market us --date D --html <초안> --datadir <W> --repo . \\
          [--tg <W>/telegram.json] [--stance-next <W>/kr_stance_next.json] [--cycle <CYCLE_ID>]
  # 최종(실제로 올릴 파일, 노트 붙인 뒤) — 같은 목록을 돌리고 결과를 기록한다
  python3 scripts/run_gates.py record --market us --date D --html posts/D.html --datadir <W> --repo . \\
          [같은 선택 인자] [--first-html <W>/numsrc_first.html] --out verification/us/D.json
  # US 뉴스·산업 글(2026-11-20): --market us-news --html news/D.html --tg <W>/telegram_news.json --contested <W>/contested.json
  # 커밋 직전(index) / push 직전(HEAD) — 기록과 그 판의 글·검사 코드·입력이 짝인지
  python3 scripts/run_gates.py verify --market us --date D --repo . (--index | --rev HEAD) [--datadir <W>]

종료 코드
  check : 0 발행 가능 / 1 필수 검사 실패·판정 불가 → 위반을 작성자에게 넘겨 다시
  record: 0 기록됨·발행 가능 / 1 발행 불가(필수 검사 실패·판정 불가, 노트가 구조를 망가뜨림, 검사 중 글·입력 변경)
          4 레포 안 기록 저장 실패 — 검사는 다 돌았고 발행 가능이었다. 같은 기록을 레포 밖에 남기고
            `fallback_record=<경로>` 를 찍는다. 처음 2주는 경고하고 발행하되 verify 에 `--record-file <경로>`
          5 기록 도구 자체 오류, 또는 대체 기록도 못 남김 — 최종 판이 검사됐다는 근거가 없다 → **발행 보류**
  verify: 0 짝 맞음 / 1 어긋남(다시 record → add → commit --amend) / 2 git 을 읽지 못함(보류) / 4 기록 없음
1a 를 켠 뒤(`verification.inputs.enforcing()` — 그 전에는 위의 종료 코드 그대로다. 2판 실행기 `_main2`·기록 `record2.py`)
종료 코드(2026-11-17 1a — 2판 기록)
  check : 0 발행 가능 / 1 필수 검사 위반 → 위반을 작성자에게 넘겨 다시 /
          2 미완료(입력 자료가 없거나 비었거나 낡았거나 수집 실패, 분류 안 된 파일, 검사기가 돌지 못함, 설정·도구 오류)
            → 글을 고쳐서 풀리는 문제가 아니다 — 글을 고치지 말고 수집을 다시 돌린다
  record: 0 기록됨·발행 가능 / 1 위반(노트가 구조를 망가뜨림 포함) / 2 미완료(검사 중 글·입력 변경 포함)
          4 레포 안 기록 저장 실패 — 검사는 다 돌았고 발행 가능이었다. 같은 기록을 레포 밖에 남기고
            `fallback_record=<경로>` 를 찍는다. 처음 2주는 경고하고 발행하되 verify 에 `--record-file <경로>`
          5 기록 도구 자체 오류(설정을 못 읽음 포함), 또는 대체 기록도 못 남김 — 최종 판이 검사됐다는 근거가 없다 → **발행 보류**
  위반과 미완료가 함께면 1(우선순위 실패 > 미완료) — 미완료 목록도 함께 찍는다.
로직 `scripts/verification/record.py`(1판)·`record2.py`(2판). 설계 `docs/superpowers/specs/2026-11-08-prepub-record.md`.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from verification import record as R  # noqa: E402

DEFAULT_CONFIG = os.path.join(os.path.dirname(HERE), 'config', 'prepub_gates.json')
LABEL = {'pass': '통과', 'warn': '경고', 'fail': '실패', 'indeterminate': '판정 불가', 'not_run': '실행 안 함',
         'partial': '일부만 검사'}


def _only_news_contested(ap, a):
    """`--contested`(쟁점 분석 결과)는 US 뉴스 글(us-news)의 입력이다 — 다른 갈래의 자료 분류표에는 그 뿌리가 없어
    넘기면 「분류 안 된 파일」로 막힌다. 잘못 넘긴 인자로 조용히 막히지 않게 여기서 거절한다(exit 2, 2026-11-22)."""
    if getattr(a, 'contested', None) and a.market != 'us-news':
        ap.error(f'--contested 는 --market us-news 에만 준다(받은 시장: {a.market})')


def _ctx(a):
    repo = os.path.abspath(a.repo)
    return {'html': os.path.abspath(a.html), 'datadir': os.path.abspath(a.datadir) if a.datadir else None,
            'repo': repo, 'date': a.date, 'tg': os.path.abspath(a.tg) if a.tg else None,
            'stance_next': os.path.abspath(a.stance_next) if a.stance_next else None, 'cycle': a.cycle,
            'first_html': os.path.abspath(a.first_html) if a.first_html else None,
            'contested': os.path.abspath(a.contested) if a.contested else None}


def _print(res, show_output):
    for r in res['gates']:
        tag = '필수' if r['required'] else '참고'
        extra = f' — {r["reason"]}' if r.get('reason') else ''
        print(f'== {r["name"]} [{tag}] {LABEL.get(r["status"], r["status"])} (exit {r["exit"]}){extra}')
        if show_output and r.get('_out', '').strip():
            print(r['_out'].rstrip())
        n = r.get('note')
        if n:
            print(f'   노트를 뺀 사본: {LABEL.get(n["stripped_status"], n["stripped_status"])}'
                  f' · 노트 구간 {len(n["note_items"])} · 본문 {len(n["body_items"])}')
    s = res['summary']
    print(f'판정: {s["status"]} · 발행 {"가능" if s["publish_ok"] else "불가"}'
          + (f' · 막은 것 {", ".join(s["blocking"])}' if s['blocking'] else '')
          + (f' · 실행 안 함 {", ".join(s["not_run"])}' if s['not_run'] else '')
          + (f' · 노트 수치 불일치 {", ".join(s["note_numbers"])}' if s['note_numbers'] else '')
          + (f' · 노트 형식 {", ".join(s["note_format"])}' if s['note_format'] else ''))


def _main1(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'record'):
        p = sub.add_parser(name)
        p.add_argument('--market', required=True)
        p.add_argument('--date', required=True)
        p.add_argument('--html', required=True)
        p.add_argument('--datadir')
        p.add_argument('--repo', default='.')
        p.add_argument('--tg')
        p.add_argument('--stance-next')
        p.add_argument('--cycle')
        # 숫자 출처 검사의 첫 판(2026-11-20) — 게이트를 처음 돌리기 전 초안 사본. 없으면 수정 이력이 「확인 불가」로 기록된다
        p.add_argument('--first-html')
        p.add_argument('--contested', help='us-news: 쟁점 분석 결과(<workspace>/contested.json)')
        p.add_argument('--config', default=DEFAULT_CONFIG)
        if name == 'record':
            p.add_argument('--out', required=True)
    v = sub.add_parser('verify')
    v.add_argument('--market', required=True)
    v.add_argument('--date', required=True)
    v.add_argument('--repo', default='.')
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument('--index', action='store_true')
    g.add_argument('--rev')
    v.add_argument('--datadir')
    v.add_argument('--tg')
    v.add_argument('--stance-next')
    v.add_argument('--contested')
    v.add_argument('--record-file', help='record 가 4 였을 때만 — 레포 밖 대체 기록으로 대조')
    v.add_argument('--config', default=DEFAULT_CONFIG)
    a = ap.parse_args(argv)
    _only_news_contested(ap, a)

    try:
        cfg = R.load_config(a.config)
    except R.ConfigError as exc:
        print(f'기록 도구 오류: {exc}', file=sys.stderr)
        return 5 if a.cmd == 'record' else 1

    if a.cmd == 'verify':
        extra = {k: os.path.abspath(x) for k, x in (('tg', a.tg), ('stance_next', a.stance_next),
                                                     ('contested', a.contested)) if x}
        code, why = R.verify(cfg, a.market, a.date, os.path.abspath(a.repo),
                             rev=None if a.index else a.rev,
                             datadir=os.path.abspath(a.datadir) if a.datadir else None, extra=extra,
                             record_file=a.record_file)
        for w in why:
            print(w)
        return code

    ctx = _ctx(a)
    try:
        res = R.run_gates(cfg, a.market, ctx)
    except Exception as exc:  # noqa: BLE001 — 기록 도구의 실패는 검사 실패와 다르다
        print(f'기록 도구 오류: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 5 if a.cmd == 'record' else 1
    _print(res, show_output=(a.cmd == 'check' or not res['summary']['publish_ok']))
    for w in res['summary'].get('integrity') or []:
        print(f'무결성: {w}')
    print(f'report_sha256={res["post_sha256"]}')
    if a.cmd == 'check':
        return 0 if res['summary']['publish_ok'] else 1

    try:
        rec = R.build_record(cfg, a.config, a.market, ctx, res)
    except Exception as exc:  # noqa: BLE001
        print(f'기록 도구 오류: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1 if not res['summary']['publish_ok'] else 5
    fb = R.fallback_path(a.market, a.date)
    saved = R.save_record(rec, os.path.abspath(a.out), fallback=fb)
    if not res['summary']['publish_ok']:
        return 1
    if saved == 4:
        print('레포 안 기록 저장 실패 — 그 날짜 기록은 지웠다(경고). 대체 기록으로 verify 한다', file=sys.stderr)
        print(f'fallback_record={fb}')
        return 4
    if saved == 5:
        print('기록 도구 오류: 기록을 어디에도 남기지 못했다 — 발행 보류', file=sys.stderr)
        return 5
    print(f'기록: {os.path.relpath(os.path.abspath(a.out), ctx["repo"])}')
    return 0



# ── 2판(1a 「자료 누락 차단」) — `verification.inputs.enforcing()` 이 참일 때만 돈다 ─────────────────
from verification import inputs as I  # noqa: E402
from verification import record2 as R2  # noqa: E402

LABEL2 = dict(R2.STATUS_KO, indeterminate='판정 불가', not_run='실행 안 함', partial='일부만 검사')


def _print2(res, show_output):
    for r in res['gates']:
        tag = '필수' if r['required'] else '참고'
        extra = f' — {r["reason"]}' if r.get('reason') else ''
        print(f'== {r["name"]} [{tag}] {LABEL2.get(r["status"], r["status"])} (exit {r["exit"]}){extra}')
        if show_output and r.get('_out', '').strip():
            print(r['_out'].rstrip())
        n = r.get('note')
        if n:
            print(f'   노트를 뺀 사본: {LABEL2.get(n["stripped_status"], n["stripped_status"])}'
                  f' · 노트 구간 {len(n["note_items"])} · 본문 {len(n["body_items"])}')
    s = res['summary']
    print(f'판정: {R2.VERDICT_KO.get(s["status"], s["status"])}({s["status"]}) · 발행 {"가능" if s["publish_ok"] else "불가"}'
          + (f' · 막은 것 {", ".join(s["blocking"])}' if s['blocking'] else '')
          + (f' · 미완료 {", ".join(s["incomplete"])}' if s.get('incomplete') else '')
          + (f' · 해당 없음 {", ".join(s["na"])}' if s.get('na') else '')
          + (f' · 노트 수치 불일치 {", ".join(s["note_numbers"])}' if s['note_numbers'] else '')
          + (f' · 노트 형식 {", ".join(s["note_format"])}' if s['note_format'] else ''))
    inp = s.get('inputs')
    if inp is None:
        print('자료 상태: 분류 정책 없이 돌았다(시험용 설정) — 자료 누락을 검사하지 않았다')
    else:
        for x in inp['blocking']:
            print(f'자료 미완료: {x}')
        for x in inp['unclassified']:
            print(f'자료 미완료: 분류되지 않은 파일 {x} — config/prepub_inputs.json 에 분류를 넣어야 한다')
        if inp['warnings']:
            print(f'자료 경고: 수집 상태 표시 없음 {len(inp["warnings"])}개(적용일 전이라 막지 않는다)')
    if not s['publish_ok'] and s['status'] != 'failed':
        print('미완료 — 글을 고치지 말고 수집을 다시 돌린다(재수집 1회 뒤에도 2 면 보류)')


def _main2(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'record'):
        p = sub.add_parser(name)
        p.add_argument('--market', required=True)
        p.add_argument('--date', required=True)
        p.add_argument('--html', required=True)
        p.add_argument('--datadir')
        p.add_argument('--repo', default='.')
        p.add_argument('--tg')
        p.add_argument('--stance-next')
        p.add_argument('--cycle')
        p.add_argument('--first-html')          # 숫자 출처 검사의 첫 판(1판과 같다)
        p.add_argument('--contested', help='us-news: 쟁점 분석 결과(<workspace>/contested.json)')
        p.add_argument('--config', default=DEFAULT_CONFIG)
        if name == 'record':
            p.add_argument('--out', required=True)
    v = sub.add_parser('verify')
    v.add_argument('--market', required=True)
    v.add_argument('--date', required=True)
    v.add_argument('--repo', default='.')
    g = v.add_mutually_exclusive_group(required=True)
    g.add_argument('--index', action='store_true')
    g.add_argument('--rev')
    v.add_argument('--datadir')
    v.add_argument('--tg')
    v.add_argument('--stance-next')
    v.add_argument('--contested')
    v.add_argument('--record-file', help='record 가 4 였을 때만 — 레포 밖 대체 기록으로 대조')
    v.add_argument('--config', default=DEFAULT_CONFIG)
    a = ap.parse_args(argv)
    _only_news_contested(ap, a)

    try:
        cfg = R2.load_config(a.config)
        policy = R2.load_policy(cfg, a.config)
    except R2.ConfigError as exc:
        print(f'기록 도구 오류: {exc}', file=sys.stderr)
        return 5 if a.cmd == 'record' else (2 if a.cmd == 'check' else 1)

    if a.cmd == 'verify':
        extra = {k: os.path.abspath(x) for k, x in (('tg', a.tg), ('stance_next', a.stance_next),
                                                     ('contested', a.contested)) if x}
        code, why = R2.verify(cfg, a.market, a.date, os.path.abspath(a.repo),
                             rev=None if a.index else a.rev,
                             datadir=os.path.abspath(a.datadir) if a.datadir else None, extra=extra,
                             record_file=a.record_file)
        for w in why:
            print(w)
        return code

    ctx = _ctx(a)
    try:
        res = R2.run_gates(cfg, a.market, ctx, policy=policy)
    except Exception as exc:  # noqa: BLE001 — 기록 도구의 실패는 검사 실패와 다르다
        print(f'기록 도구 오류: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 5 if a.cmd == 'record' else 2
    _print2(res, show_output=(a.cmd == 'check' or not res['summary']['publish_ok']))
    for w in res['summary'].get('integrity') or []:
        print(f'무결성: {w}')
    print(f'report_sha256={res["post_sha256"]}')
    code = R2.exit_code(res['summary'])
    if a.cmd == 'check':
        return code

    try:
        rec = R2.build_record(cfg, a.config, a.market, ctx, res)
    except Exception as exc:  # noqa: BLE001
        print(f'기록 도구 오류: {type(exc).__name__}: {exc}', file=sys.stderr)
        return code if code else 5
    fb = R2.fallback_path(a.market, a.date)
    saved = R2.save_record(rec, os.path.abspath(a.out), fallback=fb)
    if code:
        return code
    if saved == 4:
        print('레포 안 기록 저장 실패 — 그 날짜 기록은 지웠다(경고). 대체 기록으로 verify 한다', file=sys.stderr)
        print(f'fallback_record={fb}')
        return 4
    if saved == 5:
        print('기록 도구 오류: 기록을 어디에도 남기지 못했다 — 발행 보류', file=sys.stderr)
        return 5
    print(f'기록: {os.path.relpath(os.path.abspath(a.out), ctx["repo"])}')
    return 0



def main(argv=None):
    """꺼져 있으면 1판(1a 전과 같은 판정·종료 코드·기록), 켜면 2판."""
    return _main2(argv) if I.enforcing() else _main1(argv)


if __name__ == '__main__':
    sys.exit(main())
