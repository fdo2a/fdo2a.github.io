#!/usr/bin/env python3
"""발행본의 수치 칸에 방향 색을 입힌다 (초록 = 좋아짐, 빨강 = 나빠짐).

`apply_readability.py` **다음**, 나머지 게이트 **앞**에 돌린다. 보이는 글자와 수치는
손대지 않고 `<td>`에 class 만 얹으므로 `verify_post.py`의 멀티셋 대조를 통과한다.

    python3 scripts/apply_colors.py                   # posts/*.html 전부
    python3 scripts/apply_colors.py posts/2026-09-10.html
    python3 scripts/apply_colors.py --check           # 미적용이면 exit 1

ponytail: 표 칸만 칠한다. 산문 속 수치는 어느 지표에 속하는지 판정할 규칙이 없어
오채색 위험이 이득보다 크다. 문장-지표 귀속 규칙을 세우면 같은 `colorize.paint()`에
문단 경로를 더하면 된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.us import colorize as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# US 발행본 전용이다. KR·중국은 표 열 이름이 다르고 채권 반전 규칙도 없다.
DEFAULT_GLOBS = ("posts/*.html",)


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
        painted = C.apply(html)
        if painted == html:
            skipped += 1
            continue
        if check:
            print("미적용 %s" % path.relative_to(ROOT))
        else:
            path.write_text(painted, encoding="utf-8")
        done += 1
    verb = "미적용" if check else "적용"
    print("%s %d편 · 이미 적용 %d편 · 대상 %d편" % (verb, done, skipped, len(files)))
    # `--check` 는 **닫히면서 실패한다.** exit 0 으로 알리면 체인에서 이 단계가 빠진
    # 날을 아무도 모른다 — 색 class 만 있고 CSS 가 없는 문서도 여기서 걸린다
    # (2026-09-12 codex 구현 검토).
    return 1 if (check and done) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
