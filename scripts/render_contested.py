#!/usr/bin/env python3
"""쟁점 분석 자리를 채운다 — 이 섹션은 사람·루틴이 손으로 쓰지 않는다.

    python3 scripts/render_contested.py --html H --json <ws>/contested.json --market us --date D
    python3 scripts/render_contested.py --html H --json … --omit gate_failed

자리 = 작성자가 둔 표식(`<!--CONTESTED-->`), 앞서 남긴 자리표시(`<!--contested-pending-->`), 또는
이미 찍힌 섹션. 정확히 하나여야 한다. 데이터에 따라:
- `ok` → 정규 섹션
- 확정된 결과(최종 none·시도 소진) → 지운다
- 파일 없음·재시도 가능한 결과 → 자리표시. 로컬 러너(`contested_local.py`)가 나중에 채운다.
- `--omit REASON` → 생략 기록. 게이트를 못 넘는 선택 섹션 때문에 글 전체를 붙잡지 않기 위한 출구다.

다시 돌려도 결과가 같다.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import contested as C  # noqa: E402

_SLOT = '\x00CONTESTED-SLOT\x00'


def _slot(html):
    loc = C._Locate(html)
    for sec in reversed(loc.sections):
        html = html[:sec['start']] + _SLOT + html[sec['end']:]
    html = html.replace(C.MARKER, _SLOT).replace(C.PENDING, _SLOT)
    if C.OMIT_RE.search(html):
        raise SystemExit('이미 생략 기록이 있다 — 그 날짜는 다시 찍지 않는다')
    n = html.count(_SLOT)
    if n != 1:
        raise SystemExit(f'쟁점 자리가 {n}개 — 정확히 하나여야 한다')
    return html


def apply(html, payload, omit=None):
    html = _slot(html)
    if omit:
        if not re.fullmatch(r'[a-z_]+', omit):
            raise SystemExit('--omit 사유는 소문자·밑줄만')
        return html.replace(_SLOT, f'<!--contested-omitted:{omit}-->')
    if payload and payload.get('status') == 'ok':
        return html.replace(_SLOT, C.render(payload))
    if payload and C.settled(payload):
        return html.replace(_SLOT, '')
    return html.replace(_SLOT, C.PENDING)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--json', required=True)
    ap.add_argument('--market', default='us')
    ap.add_argument('--date', required=True, type=C.iso_date)
    ap.add_argument('--omit')
    a = ap.parse_args(argv)
    payload = None
    if os.path.exists(a.json):
        try:
            with open(a.json, encoding='utf-8') as fh:
                payload = json.load(fh)
        except ValueError:
            payload = None
        if payload is not None and C.validate(payload, a.market, a.date):
            print('데이터가 검증을 못 넘었다 — 자리표시로 둔다(로컬 러너가 다시 만든다)', file=sys.stderr)
            payload = None
    with open(a.html, encoding='utf-8') as fh:
        html = fh.read()
    out = apply(html, payload, a.omit)
    with open(a.html, 'w', encoding='utf-8') as fh:
        fh.write(out)
    state = (f'생략({a.omit})' if a.omit else
             'ok' if payload and payload['status'] == 'ok' else
             f'{payload["status"]}({payload.get("reason")})' if payload else '미도착 → 자리표시')
    print(f'contested: {state}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
