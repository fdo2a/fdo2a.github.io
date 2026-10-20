#!/usr/bin/env python3
"""쟁점 분석 섹션을 표식 자리에 찍는다 — 루틴은 이 섹션을 손으로 쓰지 않는다.

    python3 scripts/render_contested.py --html news_industry_D.html --json <ws>/contested.json
    python3 scripts/render_contested.py --html news_industry_D.html --omit gate_failed

- 데이터 `ok` → 표식(`<!--CONTESTED-->`)을 정규 섹션으로 바꾼다.
- `none`/`error`/파일 없음 → 표식을 지운다(섹션 없음).
- `--omit REASON` → 섹션·표식을 지우고 생략 기록을 남긴다. 게이트를 못 넘는 선택 섹션 때문에
  글 전체를 붙잡지 않기 위한 출구다(N07). 기록은 최종 보고에 그대로 적는다.

다시 돌려도 결과가 같다: 이미 찍힌 섹션은 새 정규형으로 통째로 바꾼다.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import contested as C  # noqa: E402

_SECTION = re.compile(r'<section\b[^>]*\bdata-contested="[^"]*"[^>]*>.*?</section>', re.S)


def apply(html, payload, omit=None):
    if omit:
        if not re.fullmatch(r'[a-z_]+', omit):
            raise SystemExit('--omit 사유는 소문자·밑줄만')
        html = _SECTION.sub(C.MARKER, html, count=1)
        if C.MARKER not in html:
            raise SystemExit('생략할 자리(표식이나 섹션)가 없다')
        return html.replace(C.MARKER, f'<!--contested-omitted:{omit}-->', 1)
    if C.OMIT_RE.search(html):
        raise SystemExit('이미 생략 기록이 있다')
    html = _SECTION.sub(C.MARKER, html, count=1)
    n = html.count(C.MARKER)
    if n != 1:
        raise SystemExit(f'표식이 {n}개 — 정확히 하나여야 한다')
    if payload and payload.get('status') == 'ok':
        return html.replace(C.MARKER, C.render(payload), 1)
    return html.replace(C.MARKER, '', 1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--json')
    ap.add_argument('--market', default='us')
    ap.add_argument('--date')
    ap.add_argument('--omit')
    a = ap.parse_args(argv)
    payload = None
    if a.json and os.path.exists(a.json):
        with open(a.json, encoding='utf-8') as fh:
            payload = json.load(fh)
        errs = C.validate(payload, a.market, a.date)
        if errs and not a.omit:
            print('데이터 위반 — 섹션을 찍지 않는다:\n  ' + '\n  '.join(errs[:10]), file=sys.stderr)
            return 1
    with open(a.html, encoding='utf-8') as fh:
        html = fh.read()
    out = apply(html, payload, a.omit)
    with open(a.html, 'w', encoding='utf-8') as fh:
        fh.write(out)
    state = (f'생략({a.omit})' if a.omit else
             (payload or {}).get('status', '미도착') if payload else '미도착')
    print(f'쟁점 분석: {state}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
