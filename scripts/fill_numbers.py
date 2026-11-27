#!/usr/bin/env python3
"""조립 단계 — 글의 `data-ref` 칸 안 숫자를 칸 값으로 다시 쓴다(US 일간, 2026-11-27 「숫자는 코드가 채운다」 1차).

  python3 scripts/fill_numbers.py --market us --date D --html <W>/morning_brief_D.html --datadir <W> --repo . \\
          [--meta <W>/morning_brief_D.meta.json] [--report <W>/fill_report.json]

순서: 작성(render_post) → **fill_numbers** → apply_readability → apply_colors → run_gates check → 위반이면 수리 → 처음부터.
글을 제자리에서 덮어쓰고(두 번 돌려도 같다) `fill_report.json` 에 칸마다 이름표·자산·관측일·상태·쓴 글자·채운 글자를 쓴다.
쓴 값 ≠ 칸 값, 모양 규칙 위반, 풀 수 없는·무효인 칸은 덮지 않고 되돌린다 — 목록을 작성자에게 넘긴다.
관측일이 글 날짜와 다른 칸은 숫자 바로 뒤에 「(M월 D일 기준)」을 코드가 찍는다(표 칸 안은 찍지 않는다).
Exit 0 = 되돌릴 것 없음 / 1 = 되돌릴 것 있음(목록을 찍는다, 글은 맞는 칸만 채운 채 저장) / 2 = 입력 오류.
적용일(`common.numsrc.FILL_EFFECTIVE`) 전 글은 아무것도 바꾸지 않고 0.
로직 scripts/us/fill.py, 구역 config/number_fill.json.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import numsrc as S  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', choices=('us',), required=True)
    ap.add_argument('--date', required=True)
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', required=True)
    ap.add_argument('--repo', default='.')
    ap.add_argument('--meta')
    ap.add_argument('--report')
    ap.add_argument('--effective', help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.date):
        print('FATAL: --date 는 YYYY-MM-DD', file=sys.stderr)
        return 2
    eff = a.effective or S.FILL_EFFECTIVE
    if a.date < eff:
        print(f'fill numbers: 적용일({eff}) 전 글이라 채우지 않는다')
        return 0
    from us import fill as FL
    from us import zones as Z
    try:
        with open(a.html, encoding='utf-8') as fh:
            html = fh.read()
        meta = None
        if a.meta:
            with open(a.meta, encoding='utf-8') as fh:
                meta = json.load(fh)
        md = json.load(open(os.path.join(a.datadir, 'market_data.json'), encoding='utf-8'))
        if md.get('report_date') != a.date:
            print(f'FATAL: market_data report_date {md.get("report_date")} 가 글 날짜 {a.date} 와 다르다', file=sys.stderr)
            return 2
        new, rep = FL.fill(html, os.path.abspath(a.datadir), a.date, os.path.abspath(a.repo), meta=meta)
    except (OSError, ValueError, S.InputError, Z.ConfigError) as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    if new != html:
        with open(a.html, 'w', encoding='utf-8') as fh:
            fh.write(new)
    report = a.report or os.path.join(os.path.dirname(os.path.abspath(a.html)), 'fill_report.json')
    with open(report, 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    c = rep['counts']
    print(f"fill numbers: 칸 {c['slots']}개 — 채움 {c['filled']}(글자 바뀜 {c['changed']}) · 기준일 찍음 {c['stale_stamped']} · "
          f"되돌림 {c['blocking']} · 참고 {c['problems'] - c['blocking']}")
    for p in rep['problems']:
        tag = '되돌림' if p.get('blocking') else '참고'
        print(f"  {tag}({p['problem']}) [{p.get('zone', '')}] {p.get('ref', '')} — 쓴 글자 「{p.get('written', '')}」"
              + (f" · 칸 값으로 찍으면 「{p['filled']}」" if p.get('filled') else '') + f" — {p.get('why', '')}")
    return 1 if c['blocking'] else 0


if __name__ == '__main__':
    sys.exit(main())
