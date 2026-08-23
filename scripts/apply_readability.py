#!/usr/bin/env python3
"""발행본에 조판 오버라이드를 소급 주입한다.

한글 장문에 필요한 세 가지만 고친다 — 문단 폭(한 줄 42자), 줄간격 1.78,
문단 간격 15px. 본문·수치·마크업은 손대지 않으므로 `verify_post.py`의
수치 멀티셋 대조를 그대로 통과한다.

    python3 scripts/apply_readability.py              # posts + kr/posts + thesis
    python3 scripts/apply_readability.py posts/2026-08-21.html
    python3 scripts/apply_readability.py --check      # 미적용 파일만 나열
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.us import readability as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOBS = ("posts/*.html", "kr/posts/*.html", "thesis/*.html")


def targets(args):
    if args:
        return [ROOT / a for a in args]
    out = []
    for g in DEFAULT_GLOBS:
        out += sorted(ROOT.glob(g))
    return out


def main(argv):
    check = "--check" in argv
    files = targets([a for a in argv if not a.startswith("-")])
    done = skipped = 0
    for path in files:
        html = path.read_text(encoding="utf-8")
        if R.has_override(html):
            skipped += 1
            continue
        if check:
            print("미적용 %s" % path.relative_to(ROOT))
            done += 1
            continue
        path.write_text(R.inject_css(html), encoding="utf-8")
        done += 1
    verb = "미적용" if check else "적용"
    print("%s %d편 · 이미 적용 %d편 · 대상 %d편" % (verb, done, skipped, len(files)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
