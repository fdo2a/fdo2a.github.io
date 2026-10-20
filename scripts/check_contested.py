#!/usr/bin/env python3
"""쟁점 분석 섹션 발행 게이트.

    python3 scripts/check_contested.py --html H --json <ws>/contested.json --market us --date D

데이터가 `ok` 면 섹션이 정확히 하나, 본문 컨테이너 바로 아래, 보이는 자리에, 데이터에서 찍은
정규형 그대로 있어야 한다(명시적 생략 기록이면 통과하고 출력에 적는다). 데이터가 없거나 재시도
가능하면 섹션 없이 자리표시 하나까지 허용, 확정된 none 이면 둘 다 없어야 한다. 섹션 밖의 쟁점
표지, 셸이 넣지 않은 `<style>`, 중복 속성은 막는다. 위반은 손으로 고쳐 넘기지 않는다 —
`render_contested.py` 를 다시 돌리거나 `--omit` 으로 생략한다.

exit 0 = 통과 · 1 = 위반
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import contested as C  # noqa: E402

SHELL = {m: cfg['shell'] for m, cfg in C.MARKET_CFG.items()}


def transforms(market='us'):
    """발행 체인이 섹션에 가하는 변형 — 마지막 것이 전체 체인이다. KR 루틴은 `apply_colors` 를
    돌리지 않는다(KR 마감 브리프 오케스트레이터)."""
    from scripts.us import colorize, readability
    if market == 'kr':
        return (readability.enhance_html,)
    return (readability.enhance_html, colorize.apply,
            lambda h: colorize.apply(readability.enhance_html(h)))


def _sector_css():
    """`kr/sectors.py` 의 막대 CSS 리터럴 — 모듈을 불러오지 않고 소스에서 읽는다(그 모듈은 pandas 를
    불러오는데, 이 게이트는 클라우드 루틴에서도 돈다)."""
    import ast
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kr', 'sectors.py')
    with open(path, encoding='utf-8') as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'css' for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return ''
    return ''


def data_styles(market):
    """데이터 생성기가 싣고 오는 `<style>` 블록 — KR 업종 막대(`kr/sectors.py`)·아시아 세션 블록
    (`fund/kr_view.py`)·펀드 점검판(`fund/render.py`). 정상 KR 발행본이 이것 때문에 쟁점 게이트를 못
    넘었다(KR 설계 검토 K02). 손으로 적은 목록이 아니라 생성기의 정규 출력에서 집는다."""
    if market != 'kr':
        return ()
    from fund import kr_view, render
    return tuple(x for x in (_sector_css(), kr_view.STYLE, render.STYLE) if x)


def trusted_styles(market, date):
    """셸·가독성·색이 넣는 `<style>` 블록 — 이 밖의 스타일은 섹션을 숨길 수 있다."""
    from scripts.common import analytics, post_shell
    body = ('<section><div class="card headline-card"><h1>제목</h1><p>본문이다.</p></div></section>'
            + ''.join(f'<section><div class="card">{b}</div></section>' for b in data_styles(market)))
    shell = SHELL[market]
    raw = post_shell.render(shell, date, {'title': 't', 'summary': 's'}, body)
    # Posts still inside the correction window were published with an earlier stylesheet.
    current = post_shell.css(shell)
    raws = [raw] + [raw.replace(current, old, 1) for old in post_shell.legacy_css(shell)]
    out = set()
    for page in raws:
        chain = transforms(market)
        for t in ((lambda h: h),) + chain + (lambda h: analytics.inject(chain[-1](h)),):
            loc = C._Locate(t(page))
            out |= {s.strip() for s in loc.styles if s.strip()} | {f'link:{h}' for h in loc.links}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--json', required=True)
    ap.add_argument('--market', required=True, choices=C.MARKETS)
    ap.add_argument('--date', required=True, type=C.iso_date)
    a = ap.parse_args(argv)
    with open(a.html, encoding='utf-8') as fh:
        html = fh.read()
    payload = None
    if os.path.exists(a.json):
        try:
            with open(a.json, encoding='utf-8') as fh:
                payload = json.load(fh)
        except ValueError:
            print('FAIL 데이터 파일이 JSON 이 아니다')
            return 1
    errs = C.check(html, payload, a.market, a.date, transforms(a.market), trusted_styles(a.market, a.date))
    state = f"{payload.get('status')}({payload.get('reason') or '-'})" if payload else '미도착'
    om = C.OMIT_RE.findall(html)
    if om:
        state += f' → 생략({om[0]})'
    elif C.PENDING in html:
        state += ' → 자리표시(로컬 러너가 채운다)'
    if errs:
        print(f'FAIL 쟁점 분석 ({state})')
        for x in errs:
            print(f'  - {x}')
        return 1
    print(f'OK 쟁점 분석 ({state})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
