#!/usr/bin/env python3
"""방문 통계(GoatCounter) 로더를 방문자용 페이지에 넣는다. 멱등.

    python3 scripts/inject_analytics.py                 # git 이 추적하는 방문자용 페이지 전부
    python3 scripts/inject_analytics.py posts/2026-09-25.html
    python3 scripts/inject_analytics.py --check         # 빠진 페이지만 나열, 있으면 exit 1

발행 흐름에서는 따로 부를 일이 없다 — `apply_readability.py`·`post_shell`·
`build_thesis_pages.py` 가 넣는다. 이 스크립트는 소급과 점검용이다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.common import analytics as A  # noqa: E402


def tracked_pages():
    out = subprocess.run(['git', 'ls-files', '-z', '*.html'], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    return [ROOT / rel for rel in sorted(out.split('\0')) if rel and A.is_page(rel)]


def main(argv):
    check = '--check' in argv
    args = [a for a in argv if not a.startswith('-')]
    files = [ROOT / a for a in args] if args else tracked_pages()
    changed, missing = 0, []
    for path in files:
        html = path.read_text(encoding='utf-8')
        new = A.inject(html)
        if A.MARKER not in new:
            missing.append(path)  # 붙일 자리(</head>·광고 로더)가 없다
            continue
        if new == html:
            continue
        if check:
            missing.append(path)
            continue
        path.write_text(new, encoding='utf-8')
        changed += 1
    for path in missing:
        print('통계 로더 없음 %s' % path.relative_to(ROOT))
    if not check:
        print('삽입 %d편 · 대상 %d편' % (changed, len(files)))
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
