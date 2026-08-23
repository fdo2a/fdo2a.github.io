#!/usr/bin/env python3
"""산문 가독성 게이트 — 문장이 길어지고 수치가 뭉치는 것을 발행 전에 잡는다.

2026-08-24 실측(최근 US·KR 10편, 문장 1,249개): 중앙값 88자, P90 147자,
문장당 수치 중앙값 3개·P90 8개. 한 문장에 수치 여덟 개가 들어가면 문장이
아니라 표다. 임계는 그 분포의 상위 10%를 겨냥해 잡았다.

    python3 scripts/check_readability.py posts/2026-08-21.html
    python3 scripts/check_readability.py --strict posts/2026-08-21.html
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.us import readability as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

LEN_WARN, LEN_FAIL = 120, 160
FIG_WARN, FIG_FAIL = 6, 9
ECHO_LIMIT = 3


def clip(s, n=90):
    return s if len(s) <= n else s[:n] + "…"


def audit(path):
    html = Path(path).read_text(encoding="utf-8")
    m = R.measure(html)
    fails, warns = [], []

    for s, n in R.long_sentences(html, LEN_WARN):
        (fails if n > LEN_FAIL else warns).append("%d자 문장 · %s" % (n, clip(s)))
    for s, n in R.dense_sentences(html, FIG_WARN):
        (fails if n > FIG_FAIL else warns).append("수치 %d개 문장 · %s" % (n, clip(s)))
    for tok in sorted(set(R.overprecise(html))):
        fails.append("산문 과잉 정밀 %s — 반올림할 것" % tok)
    for tok in sorted(set(R.loosely_precise(html))):
        warns.append("산문 소수점 %s — 호가가 아니면 반올림" % tok)
    for tok, n in R.echoed_figures(html, ECHO_LIMIT):
        warns.append("같은 수치 %s가 산문에서 %d회 되풀이" % (tok, n))

    if not R.has_override(html):
        fails.append("조판 오버라이드 미적용 — apply_readability.py를 돌릴 것")
    return m, fails, warns


def main(argv):
    strict = "--strict" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print("사용법: check_readability.py [--strict] <파일…>")
        return 2
    bad = 0
    for p in paths:
        m, fails, warns = audit(p)
        print("== %s" % p)
        print(
            "   문장 %d · 중앙 %d자 · P90 %d자 · 120자 초과 %d문장 · 수치 중앙 %d개"
            % (m["sentences"], m["median_len"], m["p90_len"], m["over_120"], m["median_figures"])
        )
        for f in fails:
            print("   FAIL %s" % f)
        for w in warns:
            print("   warn %s" % w)
        if fails or (strict and warns):
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
