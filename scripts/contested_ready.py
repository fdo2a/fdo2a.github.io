#!/usr/bin/env python3
"""루틴용 — origin/main 의 쟁점 분석 결과를 워크스페이스로 가져온다(없으면 없다고).

    python3 scripts/contested_ready.py --market us --date D --out <ws>/contested.json

결과는 Mac 의 로컬 러너(`contested_local.py`)가 만들어 푸시한다. 루틴은 기다리지 않는다 — 아직
없으면 `render_contested.py` 가 자리표시를 남기고, 러너가 나중에 발행본을 채운다.
항상 exit 0. 마지막 줄 = `contested: <상태>`.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import contested as C  # noqa: E402


def sh(args):
    return subprocess.run(args, capture_output=True, text=True)


def main(argv=None, run=sh):
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', default='us', choices=C.MARKETS)
    ap.add_argument('--date', required=True, type=C.iso_date)
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    run(['git', 'fetch', '-q', 'origin', 'main'])
    r = run(['git', 'show', f'origin/main:data/contested/{a.market}/{a.date}.json'])
    p = None
    if r.returncode == 0:
        try:
            p = json.loads(r.stdout)
        except ValueError:
            p = None
    if os.path.exists(a.out):
        os.remove(a.out)
    if p is None:
        print('contested: 미도착(로컬 러너가 아직 안 만들었다 — 자리표시로 발행)')
        return 0
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(p, fh, ensure_ascii=False)
    bad = C.validate(p, a.market, a.date)
    print(f'contested: {p.get("status")}({p.get("reason") or "-"})' + (' · 검증 실패' if bad else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
