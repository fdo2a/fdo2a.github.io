#!/usr/bin/env python3
"""Assemble a daily brief from the writer's body and meta — head, CSS, top bar, nav.

    python3 scripts/render_post.py --market us --date 2026-09-24 \
        --meta morning_brief_2026-09-24.meta.json \
        --body morning_brief_2026-09-24.body.html \
        --out  morning_brief_2026-09-24.html

meta.json: {"title": "<SEO title>", "summary": "<1–2 sentences>"}. body: the sections
that go inside <div class="doc">, starting with the headline card and its one <h1>.
Exit 1 lists every contract violation; nothing is written then.

Logic: scripts/common/post_shell.py.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import post_shell as S  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', required=True, choices=sorted(S.MARKETS))
    ap.add_argument('--date', required=True)
    ap.add_argument('--meta', required=True)
    ap.add_argument('--body', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    try:
        meta = json.loads(Path(args.meta).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'meta.json 을 읽지 못했다: {exc}')
        return 1
    body = Path(args.body).read_text(encoding='utf-8')
    errors = S.validate(args.market, args.date, meta, body)
    if errors:
        for e in errors:
            print(f'FAIL {e}')
        return 1
    Path(args.out).write_text(S.render(args.market, args.date, meta, body), encoding='utf-8')
    print(f'렌더 완료 — {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
