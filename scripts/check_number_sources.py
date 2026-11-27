#!/usr/bin/env python3
"""발행 게이트(참고) — 글의 모든 숫자를 출처 칸 하나에: 자료로 확인 · 기사와 일치 · 텔레그램 글과 일치 · 검색 발췌와 일치 ·
세지 않은 숫자 · 확인 불가 (2026-11-20, US 루틴 1차).

  python3 scripts/check_number_sources.py --market us --date D --html <초안> --datadir <W> --repo . \\
          [--tg <W>/telegram.json] [--cycle <CYCLE_ID>] [--first <W>/numsrc_first.html] [--json]
  python3 scripts/check_number_sources.py --market us-news --date D --html news_industry_D.html --datadir <W> --repo . \\
          [--tg <W>/telegram_news.json] [--first <W>/numsrc_first_news.html] [--json]

처음 2주는 **아무것도 막지 않는다**(config/prepub_gates.json `required: false`). 확인 불가 숫자는 실패가 아니라 기록에
싣는 집계다 — 그래서 위반 줄을 내지 않고 `sources` 로만 낸다. 「확인 불가 0」은 「오류 0」이 아니다.
Exit 0 = 분류 끝(칸 합 == 총수) / 2 = 입력을 읽지 못함·칸 합이 맞지 않음(검사기 결함 — 통과로 치지 않는다).

**막는 판(2026-11-27 「숫자는 코드가 채운다」 1차 — US 일간, `common.numsrc.FILL_EFFECTIVE` 이후 글)**: 채운 글을 다시
풀어 위반을 낸다 — 어느 구역이든 칸을 단 숫자의 자료와 다름·표식 오류·칸 무효·기준일 없음, block 구역
(config/number_fill.json)의 표식 없음·코드 블록(표식 없음)·칸 없음·선언 무효, 첫 판에서 사라졌는데 `removed` 목록
(`--removed`, 기본 `<datadir>/removed.json`)에 없는 숫자, 본문에 없는 제목 이름표. 위반이 있으면 exit 1.
`--first` 가 없거나 이 글의 첫 판이 아니면 수정 이력은 `unverifiable`(「수정 이력 확인 불가」, 0 으로 적지 않는다).
로직 `scripts/us/number_sources.py`·`scripts/common/numsrc.py`·`scripts/us/facts.py`.
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
    ap.add_argument('--market', choices=('us', 'us-news'), required=True)
    ap.add_argument('--date', required=True)
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', required=True)
    ap.add_argument('--repo', default='.')
    ap.add_argument('--tg')
    ap.add_argument('--cycle')
    ap.add_argument('--first')
    ap.add_argument('--removed', help='작성자가 뺀 숫자 목록(기본 <datadir>/removed.json, 없으면 빈 목록)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--effective', help=argparse.SUPPRESS)
    ap.add_argument('--fill-effective', help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    eff = a.effective or S.EFFECTIVE
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.date):
        print('FATAL: --date 는 YYYY-MM-DD', file=sys.stderr)
        return 2
    if a.date < eff:
        if a.json:
            print(json.dumps({'skipped': True, 'effective': eff}, ensure_ascii=False))
        else:
            print(f'number sources: 적용일({eff}) 전 글이라 검사하지 않는다')
        return 0
    from us import number_sources as U
    try:
        with open(a.html, encoding='utf-8') as fh:
            html = fh.read()
        first = None
        if a.first:
            try:
                with open(a.first, encoding='utf-8') as fh:
                    first = fh.read()
            except OSError:
                first = None
        inp = U.Inputs(a.market, a.date, os.path.abspath(a.datadir), os.path.abspath(a.repo), tg=a.tg, cycle=a.cycle,
                       fill_effective=a.fill_effective)
        removed = S.load_removed(a.removed or os.path.join(a.datadir, 'removed.json')) if inp.blocking else []
        res = U.result(inp, html, first, removed)
    except OSError as e:
        print(f'FATAL: 입력을 읽지 못했다: {e}', file=sys.stderr)
        return 2
    except S.InputError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    except S.InvariantError as e:
        print(f'FATAL: 숫자 집계가 맞지 않는다 — {e}', file=sys.stderr)
        return 2
    viols = res.get('violations') or []
    if a.json:
        print(json.dumps({'skipped': False, 'warnings': [], 'violations': viols, 'sources': res}, ensure_ascii=False))
        return 1 if viols else 0
    c = res['counts']
    print(f"number sources: 숫자 {c['total']}개 = 자료로 확인 {c['table'] + c['data']}(표 {c['table']}·칸 {c['data']}) · "
          f"어림선 {c['level']} · "
          f"기사와 일치 {c['article']} · 텔레그램 글과 일치 {c['telegram']} · 검색 발췌와 일치 {c['web']} · "
          f"세지 않은 숫자 {c['excluded']} · 확인 불가 {c['unknown']}")
    if res['unknown_by']:
        print('  확인 불가 이유: ' + ' · '.join(f'{k} {v}' for k, v in res['unknown_by'].items()))
    for u in res['unknown']:
        print(f"  확인 불가({u['why']}): {u['text']}")
    h = res['history']
    print('  수정 이력: ' + ('확인 불가 — ' + res['history_why'] if h == 'unverifiable' else
                          f"첫 판 확인 불가 {h['first_unknown']} → 고쳐서 확인 {h['fixed']} · 문장째 사라짐 {h['gone']} · "
                          f"그대로 {h['still']} · 이력 확인 불가 {h['ambiguous']}"))
    if res.get('blocking'):
        rm = res.get('removal')
        if rm:
            print(f"  지운 숫자: 따라간 숫자 {rm['followed']} · 사라짐 {rm['gone']} · 어디에도 없음(가를 수 없음) "
                  f"{rm['ambiguous_absent']} · removed 목록 {rm['listed']}(맞음 {rm['matched']})")
            for w in rm.get('wanted') or []:
                print('  removed 에 적을 것: ' + json.dumps(w, ensure_ascii=False))
        print(f"  막는 판: 위반 {len(viols)}")
        for v in viols:
            print(f'위반: {v}')
    return 1 if viols else 0


if __name__ == '__main__':
    sys.exit(main())
