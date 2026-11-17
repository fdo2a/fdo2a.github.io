#!/usr/bin/env python3
"""발행 게이트 — 본문 수치 대조(자리 단위). US 는 전수, KR 은 표 네 종(2026-11-13).

  python3 scripts/check_numbers.py --html morning_brief_DATE.html --datadir <workspace>
  python3 scripts/check_numbers.py --html kr/posts/DATE.html --datadir kr/data --market kr --date DATE

시장 표 칸은 행·열이 가리키는 데이터 값과, 문장 수치는 자산·단위로 정해지는 필드와 맞춘다.
문장 층의 차단 여부는 `config/number_audit.json` 의 `prose`(warn|block), `--prose` 로 덮는다.
Exit 0 = 발행 가능(경고는 0), 1 = 위반(한 줄에 하나), 2 = 입력을 읽지 못함(통과로 치지 않는다). 2026-11-17 부터
위임 자료(econ_indicators·macro_metrics·fund_board·liquidity, KR kr_intraday·kr_econ·kr_fund_view)가 없거나
설정(`config/number_audit.json`)을 읽지 못해도 2 — 「없으면 미검증으로 센다」를 끝냈다.
`--json` 은 같은 판정을 stdout 한 줄 JSON 으로 낸다(종료 코드 동일) — 매일 검증 알림이 경고와
위반을 줄 모양으로 짐작하지 않게(2026-11-08). 입력 오류(2)는 여전히 stderr 다.
로직 `scripts/us/number_audit.py`.

KR(`--market kr`, 로직 `scripts/kr/number_audit.py`): `--date` 필수 — 파일명 날짜·`kr_market_data.report_date` 와
다르면 2. 적용일(`kr.number_audit.EFFECTIVE`) 전 글은 입력을 읽기 전에 skipped. `--prose` 는 무시(문장은 범위 밖).
숨은 `--effective D` 는 소급 재실행·시험용으로 적용일을 덮는다 — 발행 실행 목록(config/prepub_gates.json)은 쓰지 않는다.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from us import number_audit as N  # noqa: E402

CONFIG = os.path.join(os.path.dirname(HERE), 'config', 'number_audit.json')
OPTIONAL = ('econ_indicators', 'macro_metrics', 'fund_board')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


class ConfigMissing(Exception):
    pass


def _mode(arg):
    if arg:
        return arg
    try:
        mode = _read(CONFIG).get('prose', 'warn')
    except (OSError, ValueError, AttributeError) as e:
        # 2026-11-17: 설정을 못 읽으면 문장 층을 어느 쪽으로 돌릴지 모른다 — 미완료(2), 경고로 넘기지 않는다
        raise ConfigMissing(f'config/number_audit.json 을 읽지 못했다: {type(e).__name__}') from e
    if mode not in ('warn', 'block'):
        raise ConfigMissing(f'config/number_audit.json prose={mode!r}')
    return mode


def _legacy(args, post_date):
    """--recheck(옛 판정)은 1a 적용일(`verification.inputs.STRICT_FROM`) 전 글에만 — 새 글에는 붙여도 효과가 없다
    (1a 구현 검토 #9). 글 날짜는 정규 파일 이름(YYYY-MM-DD.html)으로만 정하고, `post_date`(--date 나 이름에서 읽은 것)가
    그것과 다르거나 이름이 정규가 아니면 옛 판정을 쓰지 않는다(2회차 F5)."""
    from verification.inputs import legacy_recheck
    return bool(post_date) and legacy_recheck(args.recheck, args.html, post_date)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--prose', choices=('warn', 'block'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    ap.add_argument('--date', help='KR: 글 날짜(필수)')
    ap.add_argument('--effective', help=argparse.SUPPRESS)
    ap.add_argument('--recheck', action='store_true',
                    help='지난 글을 그 커밋 자료로 재검사(정정기·윤문기·매일 알림) — 그때 없던 위임 자료는 2026-11-17 전처럼 '
                         '미검증으로 센다. 발행 실행 목록은 쓰지 않는다')
    args = ap.parse_args(argv)
    if args.market == 'kr':
        return _main_kr(args)

    def skipped():
        if args.json:
            print(json.dumps({'skipped': True, 'effective': N.EFFECTIVE}, ensure_ascii=False))
        else:
            print(f'number audit: 적용일({N.EFFECTIVE}) 전 글이라 검사하지 않는다')
        return 0

    # 적용일 전 글은 입력을 읽기 전에 끝낸다 — 정정기가 옛 글에 다시 돌릴 때 판정 불가(2)로 막지 않게
    m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(args.html))
    if m and m.group(0) < N.EFFECTIVE:
        return skipped()
    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
        data = {'market_data': _read(os.path.join(args.datadir, 'market_data.json'))}
    except (OSError, ValueError) as e:
        print(f'FATAL: 입력을 읽지 못했다: {e}', file=sys.stderr)
        return 2
    # 2026-11-17: 위임 자료도 필수 — 없으면 「미검증으로 센다」가 아니라 미완료(2)
    for k, rel in [(k, f'{k}.json') for k in OPTIONAL] + [('liquidity', os.path.join('liquidity', 'liquidity.json'))]:
        try:
            data[k] = _read(os.path.join(args.datadir, rel))
        except FileNotFoundError:
            if _legacy(args, m.group(0) if m else None):
                continue             # 지난 글 재검사: 없으면 그 위임이 성립하지 않아 미검증으로 센다(옛 판정)
            print(f'FATAL: {os.path.basename(rel)} 이 없다', file=sys.stderr)
            return 2
        except (OSError, ValueError) as e:
            print(f'FATAL: {os.path.basename(rel)} 을 읽지 못했다: {type(e).__name__}', file=sys.stderr)
            return 2
    # 글 날짜와 데이터 날짜가 다르면 다른 날 값으로 대조하게 된다 — 판정할 수 없다(발행 커밋의 data 가
    # 다음 세션인 경우가 있다: 10/15 글 → 10/16 data)
    rd = (data['market_data'] or {}).get('report_date') if isinstance(data['market_data'], dict) else None
    if m and rd and rd != m.group(0):
        print(f'FATAL: 데이터 report_date {rd} 가 글 날짜 {m.group(0)} 와 다르다 — 그 날 판으로 다시 돌린다',
              file=sys.stderr)
        return 2
    try:
        r = N.audit(html, data, prose=_mode(args.prose))
    except ConfigMissing as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    except N.InputError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    if r.skipped:
        return skipped()
    if args.json:
        keys = ('tokens_seen', 'table_cells', 'prose_judged', 'unverified', 'delegated', 'excluded')
        print(json.dumps({'skipped': False, 'warnings': list(r.warnings),
                          'violations': list(r.violations), 'summary': r.summary(),
                          'counts': {k: int(getattr(r, k)) for k in keys},
                          # 자동 대조하지 못한 수치의 이유별 개수 — 알림이 「243개」만 말하지 않게(11/11)
                          'unverified_by': {str(k): int(v) for k, v in r.unverified_by.items() if v}},
                         ensure_ascii=False))
        return 1 if r.violations else 0
    for w in r.warnings:
        print(w)
    for v in r.violations:
        print(v)
    print(r.summary())
    return 1 if r.violations else 0


def _emit(r, as_json):
    """US 와 같은 출력 형식 — 기록기(verification/record.py)·정정기·윤문 재생이 이 모양을 읽는다."""
    if as_json:
        keys = ('tokens_seen', 'table_cells', 'prose_judged', 'unverified', 'delegated', 'excluded')
        print(json.dumps({'skipped': False, 'warnings': list(r.warnings),
                          'violations': list(r.violations), 'summary': r.summary(),
                          'counts': {k: int(getattr(r, k)) for k in keys},
                          'unverified_by': {str(k): int(v) for k, v in r.unverified_by.items() if v}},
                         ensure_ascii=False))
        return 1 if r.violations else 0
    for w in r.warnings:
        print(w)
    for v in r.violations:
        print(v)
    print(r.summary())
    return 1 if r.violations else 0


def _main_kr(args):
    from kr import number_audit as K
    eff = args.effective or K.EFFECTIVE
    if not args.date or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date):
        print('FATAL: --market kr 에는 --date YYYY-MM-DD 가 필요하다', file=sys.stderr)
        return 2
    m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(args.html))
    if m and m.group(0) != args.date:
        print(f'FATAL: --date {args.date} 가 파일명 날짜 {m.group(0)} 와 다르다', file=sys.stderr)
        return 2
    if args.date < eff:
        if args.json:
            print(json.dumps({'skipped': True, 'effective': eff}, ensure_ascii=False))
        else:
            print(f'number audit: 적용일({eff}) 전 글이라 검사하지 않는다')
        return 0
    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
        data = K.load_inputs(args.datadir)
        lacking = [k for k in ('kr_intraday', 'kr_econ', K.FUND) if data.get(k) is None]
        if lacking and not _legacy(args, args.date):
            # 2026-11-17: 선택 자료도 그날 수집분이 있어야 한다 — 없으면 미완료(2)
            print(f'FATAL: {", ".join(k + ".json" for k in lacking)} 이 없거나 읽히지 않는다', file=sys.stderr)
            return 2
        r = K.audit(html, data, args.date, effective=eff)
    except OSError as e:
        print(f'FATAL: 입력을 읽지 못했다: {e}', file=sys.stderr)
        return 2
    except N.InputError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    return _emit(r, args.json)


if __name__ == '__main__':
    sys.exit(main())
