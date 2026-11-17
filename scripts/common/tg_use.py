"""Whether a Telegram item may be quoted in a post — shared by the news posts (`scripts/tg_news.py`)
and the Japan daily collector (`scripts/fetch_telegram_jp.py`). Moved here 2026-11-15.
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md"""
import re

from .tg_junk import unusable
from .tg_links import classify

# A relay post that credits no outlet used to be left out wholesale (`unsourced_relay`). Dropped
# 2026-11-12 (사용자 지시 「뉴스 개수를 한정하지 말고 … 중요도가 높다고 보여지는 내용들은 포함」): it left out
# 5 of 15 items on US 11/11, a Reuters-attributed bond story among them. Such a post is written as
# 「…라는 소식도 전해졌다」; only an allegation about someone with no outlet named stays out.
REASONS = ('cited', 'no_summary', 'junk', 'unsourced_allegation', 'no_outlet', 'dup_url')
# Only for items that credit no outlet. 「경기소비재」「이외도」「구속력」 must not match.
ALLEGATION = re.compile(r'의혹|불륜|(?<![가-힣])외도|혼외|스캔들|사생활|(?<![가-힣])성추|성폭|횡령|배임|'
                        r'(?<![가-힣])기소|체포|피소|구속(?!력)')

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
