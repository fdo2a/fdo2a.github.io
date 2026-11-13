#!/usr/bin/env python3
"""Telegram input for the news posts (`/news/`, `/kr/news/`) — 2026-11-12.

  python3 scripts/tg_news.py input --market us --date 2026-11-11 --repo . \
      --news <workspace>/news/2026-11-11.json --out <workspace>/telegram_news.json
  python3 scripts/tg_news.py strip --html news_industry_2026-11-11.html

`input` reads the Telegram file and the brief from the day's **brief publish commit** (the commit
that added posts/<D>.html) and writes the same file with `news_use` on every item. Nothing is
removed: the gate compares text outside the section with every summary, usable or not.
`news_skip` says why an item may not be quoted in the news post:
  cited                 the brief already quotes it (data-tg in the brief HTML)
  no_summary · junk     no summary / a refusal or the polite register (common/tg_junk.py)
  unsourced_allegation  no outlet (or firm) named and the summary speaks of 의혹·불륜·기소… about someone
  no_outlet             a report whose outlet is unknown — the gate could not accept a sentence for it
  dup_url               a report whose original is one of the collected news articles (`--news`)
`--news` is the news file the news writer and check_news.py use in this run; it is required.
The output is deleted first and written only on success, so a failed run cannot leave a file from
an earlier one. The last line (`tg-news: …`) goes into the routine's final report. Exit 0 — Telegram
never blocks the news post — except exit 1 when the old output could not be deleted: that file must
not be handed to the writer or the gate.

`strip` removes the `<section data-tg-section>` from a news post (idempotent) when the gate could
not be satisfied; rerun every gate with the same telegram_news.json afterwards.
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ci import routine_due as rd  # noqa: E402
from common.numbers import strip_comments  # noqa: E402
from common.telegram_gate import NEWS_TITLE, _close_of, elements  # noqa: E402
from common.tg_junk import unusable  # noqa: E402
from common.tg_links import classify, pool_key  # noqa: E402

PATHS = {'us': ('posts/{d}.html', 'data/telegram/{d}.json'),
         'kr': ('kr/posts/{d}.html', 'kr/data/telegram/{d}.json')}
# A relay post that credits no outlet used to be left out wholesale (`unsourced_relay`). Dropped
# 2026-11-12 (사용자 지시 「뉴스 개수를 한정하지 말고 … 중요도가 높다고 보여지는 내용들은 포함」): it left out
# 5 of 15 items on US 11/11, a Reuters-attributed bond story among them. Such a post is written as
# 「…라는 소식도 전해졌다」; only an allegation about someone with no outlet named stays out.
REASONS = ('cited', 'no_summary', 'junk', 'unsourced_allegation', 'no_outlet', 'dup_url')
# Only for items that credit no outlet. 「경기소비재」「이외도」「구속력」 must not match.
ALLEGATION = re.compile(r'의혹|불륜|(?<![가-힣])외도|혼외|스캔들|사생활|(?<![가-힣])성추|성폭|횡령|배임|'
                        r'(?<![가-힣])기소|체포|피소|구속(?!력)')
SECTION_OPEN = re.compile(r'[ \t]*<section\b[^>]*\bdata-tg-section\b[^>]*>', re.I)


def _git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, timeout=60)


def skip_reason(it, cited, news_keys):
    """Why this item may not be quoted in the news post, or None."""
    summary = it.get('summary_ko')
    if it.get('id') in cited:
        return 'cited'
    if not summary:
        return 'no_summary'
    if unusable(summary):
        return 'junk'
    # who stands behind it: the outlet or the firm. Any kind — a report whose outlet is
    # unknown is as unsourced as an opinion (the collector turns those into opinions; this is for a
    # file that did not come that way).
    sourced = bool((it.get('source') or {}).get('name')) or bool(it.get('firm'))
    if not sourced and ALLEGATION.search(summary):
        return 'unsourced_allegation'
    if it.get('kind') == 'report' and not sourced:
        return 'no_outlet'
    if it.get('kind') == 'report' and news_keys:
        key = classify((it.get('source') or {}).get('url') or '')[1]
        if key and key in news_keys:
            return 'dup_url'
    return None


def build(market, day, repo, ref, news):
    """-> (payload, None) or (None, 'none(…)' | 'error …')."""
    post_path, tg_path = (p.format(d=day) for p in PATHS[market])
    git = lambda *a: _git(repo, *a)                                        # noqa: E731
    if ref == 'origin/main' and git('fetch', '-q', 'origin', 'main').returncode:
        return None, 'error fetch 실패'
    try:
        commit = rd.brief_publish_commit(post_path, ref, git=git)
    except rd.GitLookupError as e:
        return None, f'error {e}'
    if not commit:
        return None, 'none(브리프 없음 — 발행 커밋을 찾지 못했다)'
    if git('cat-file', '-e', f'{commit}:{tg_path}').returncode:
        return None, 'none(발행 커밋에 텔레그램 파일 없음)'
    shown, brief = git('show', f'{commit}:{tg_path}'), git('show', f'{commit}:{post_path}')
    if shown.returncode or brief.returncode:
        return None, f'error {(shown.stderr or brief.stderr).strip()[:200]}'
    try:
        data = json.loads(shown.stdout)
    except ValueError:
        return None, 'none(텔레그램 파일을 읽지 못했다)'
    if not isinstance(data, dict) or data.get('report_date') != day:
        return None, f'none(report_date {data.get("report_date") if isinstance(data, dict) else None} ≠ {day})'
    cited = {tid for tid, _, _, _ in elements(strip_comments(brief.stdout))}
    news_keys = {k for k in (pool_key(it) for it in (news or {}).get('items') or []) if k}
    counts = {r: 0 for r in REASONS}
    for it in data.get('items') or []:
        why = skip_reason(it, cited, news_keys)
        it['news_use'] = why is None
        it.pop('news_skip', None)
        if why:
            it['news_skip'] = why
            counts[why] += 1
    data['news_input'] = {'brief_commit': commit, 'news_file': news is not None, 'counts': counts,
                          'usable': sum(1 for it in data.get('items') or [] if it['news_use'])}
    return data, None


def cmd_input(a):
    for p in (a.out, a.out + '.tmp'):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except OSError as e:
            # the old file is still there: saying "error" with exit 0 would let it be used
            print(f'tg-news: error 옛 출력 파일을 지우지 못했다({type(e).__name__}) — {p} 를 쓰지 않는다')
            return 1
    news = None
    if os.path.exists(a.news):
        try:
            with open(a.news, encoding='utf-8') as f:
                news = json.load(f)
            if not isinstance(news, dict):
                raise ValueError
        except (OSError, ValueError):
            print(f'tg-news: error 뉴스 파일 읽기 실패 — {a.news}')
            return 0
    data, why = build(a.market, a.date, a.repo, a.ref, news)
    if data is None:
        print(f'tg-news: {why}')
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(a.out + '.tmp', a.out)
    ni = data['news_input']
    dropped = ' · '.join(f'{r} {n}' for r, n in ni['counts'].items() if n) or '뺀 것 없음'
    print(f'tg-news: 쓸 수 있는 {ni["usable"]}건 / 전체 {len(data.get("items") or [])}건({dropped})'
          + ('' if ni['news_file'] else ' · news: 없음(기사 중복은 보지 못했다)'))
    return 0


def strip_section(html):
    """-> (html without any `<section data-tg-section>`, how many were removed)."""
    n = 0
    while True:
        m = SECTION_OPEN.search(html)
        if not m:
            return html, n
        end = _close_of(html, 'section', m.end())
        sid = re.search(r'\bid\s*=\s*["\']([^"\']+)', m.group(0))
        if sid:                                 # the reading map's link to this section would be dead
            html_tail = re.sub(r'<a\b[^>]*href="#' + re.escape(sid.group(1)) + r'"[^>]*>.*?</a>', '', html[:m.start()], flags=re.S)
            shift = len(html[:m.start()]) - len(html_tail)
            html = html_tail + html[m.start():]
            m_start, end = m.start() - shift, end - shift
        else:
            m_start = m.start()
        if html[end:end + 1] == '\n' and (m_start == 0 or html[m_start - 1] == '\n'):
            end += 1
        html = html[:m_start] + html[end:]
        n += 1


def cmd_strip(a):
    with open(a.html, encoding='utf-8') as f:
        html = f.read()
    out, n = strip_section(html)
    if n:
        with open(a.html, 'w', encoding='utf-8') as f:
            f.write(out)
    print(f'strip: {n} — 「{NEWS_TITLE}」 섹션' + (' 을 뺐다' if n else ' 이 없다'))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('input')
    i.add_argument('--market', choices=sorted(PATHS), required=True)
    i.add_argument('--date', required=True, help='report_date of the brief and the news post')
    i.add_argument('--repo', default='.')
    i.add_argument('--ref', default='origin/main', help='where to look for the brief publish commit')
    i.add_argument('--news', required=True, help='the news file the news writer and check_news.py use')
    i.add_argument('--out', required=True)
    s = sub.add_parser('strip')
    s.add_argument('--html', required=True)
    a = ap.parse_args(argv)
    return cmd_input(a) if a.cmd == 'input' else cmd_strip(a)


if __name__ == '__main__':
    sys.exit(main())
