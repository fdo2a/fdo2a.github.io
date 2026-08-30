#!/usr/bin/env python3
"""발행본에 가독성 보정을 소급 적용한다.

한글 장문에 필요한 조판, 빠른 이동, 긴 문단 분리를 더한다. 보이는 글자와
수치는 손대지 않으므로 `verify_post.py`의 수치 멀티셋 대조를 그대로 통과한다.

    python3 scripts/apply_readability.py              # daily US + KR posts
    python3 scripts/apply_readability.py posts/2026-08-21.html
    python3 scripts/apply_readability.py --check      # 미적용 파일만 나열
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.us import readability as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Thesis pages already pass the readability distribution and are regenerated from source.
# This retrofit is for the daily US/KR archive that showed the density problem.
DEFAULT_GLOBS = ("posts/*.html", "kr/posts/*.html", "bond/posts/*.html")


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
        enhanced = R.enhance_html(html)
        if enhanced == html:
            skipped += 1
            continue
        if check:
            print("미적용 %s" % path.relative_to(ROOT))
            done += 1
            continue
        path.write_text(enhanced, encoding="utf-8")
        done += 1
    verb = "미적용" if check else "적용"
    print("%s %d편 · 이미 적용 %d편 · 대상 %d편" % (verb, done, skipped, len(files)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
