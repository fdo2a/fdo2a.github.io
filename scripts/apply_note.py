#!/usr/bin/env python3
"""직접 쓴 의견을 발행본에 붙인다 (또는 고치고, 뺀다).

  python3 scripts/apply_note.py --new                      # 오늘 자 노트 파일 만들기
  python3 scripts/apply_note.py posts/2026-08-20.html      # notes/2026-08-20.md 를 붙인다
  python3 scripts/apply_note.py posts/2026-08-20.html --remove

노트는 `notes/YYYY-MM-DD.md`에 마크다운으로 쓴다. 이 스크립트는 그것을 손대지 않고
그대로 HTML로 옮긴다 — 문장을 다듬거나 수치를 확인하지 않는다. 그 글은 당신 글이다.

같은 파일에 몇 번을 돌려도 노트는 하나만 남는다(다시 돌리면 교체). 노트를 고쳤으면
다시 돌리고, 커밋·푸시하면 사이트에 반영된다.
"""

import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.editor_note import apply_note, is_template, render_note  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES_DIR = os.path.join(ROOT, 'notes')

TEMPLATE = """# (제목 — 이 줄을 지우면 「에디터 노트」로 나간다)

여기에 그날의 생각을 쓴다. 빈 줄로 나누면 문단이 갈린다.

## 소제목도 쓸 수 있다

- 목록
- **굵게** 와 *기울임*
- [링크](https://example.com)

> 인용은 이렇게.
"""


def note_path(date):
    return os.path.join(NOTES_DIR, f'{date}.md')


def date_of(html_path):
    m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(html_path))
    return m.group(1) if m else dt.date.today().isoformat()


def create(date):
    os.makedirs(NOTES_DIR, exist_ok=True)
    path = note_path(date)
    if os.path.exists(path):
        print(f'이미 있다: {path}')
        return path
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(TEMPLATE)
    print(f'만들었다: {path}\n  편집한 뒤 →  python3 scripts/apply_note.py posts/{date}.html')
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html', nargs='?', help='발행본 (예: posts/2026-08-20.html)')
    ap.add_argument('--note', help='노트 파일 경로 (기본: notes/<발행본 날짜>.md)')
    ap.add_argument('--new', metavar='DATE', nargs='?', const='today',
                    help='노트 파일을 템플릿으로 만든다 (기본 오늘)')
    ap.add_argument('--remove', action='store_true', help='발행본에서 노트를 뺀다')
    args = ap.parse_args()

    if args.new:
        create(dt.date.today().isoformat() if args.new == 'today' else args.new)
        if not args.html:
            return 0

    if not args.html:
        ap.error('발행본 경로가 필요하다 (또는 --new 로 노트 파일만 만든다)')

    date = date_of(args.html)
    with open(args.html, encoding='utf-8') as fh:
        page = fh.read()

    if args.remove:
        out, what = apply_note(page, ''), '노트를 뺐다'
    else:
        path = args.note or note_path(date)
        if not os.path.exists(path):
            print(f'노트가 없다: {path}\n  만들려면 →  python3 scripts/apply_note.py --new {date}')
            return 1
        with open(path, encoding='utf-8') as fh:
            markdown = fh.read()
        note = render_note(markdown, date)
        if not note:
            why = ('템플릿 그대로다' if is_template(markdown) else '비어 있다')
            print(f'노트가 {why}: {path} — 발행본은 그대로 둔다')
            return 1
        out, what = apply_note(page, note), f'노트를 붙였다 ({path})'

    if out == page:
        print(f'바뀐 것이 없다 — {args.html}')
        return 0
    with open(args.html, 'w', encoding='utf-8') as fh:
        fh.write(out)
    print(f'{what} — {args.html}\n  확인 →  python3 scripts/verify_post.py {args.html}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
