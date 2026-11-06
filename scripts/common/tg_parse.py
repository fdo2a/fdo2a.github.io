# Ported from fdo2a/telegram-shadow shadow/parse.py (2026-11-06). Keep the two in step or retire the shadow.
"""t.me/s/<channel> preview HTML -> post records. stdlib only.

A page with zero posts carrying both data-post and datetime is a parse failure,
never an empty success (the preview layout may change under us).
"""
import hashlib
import re
from html import unescape
from html.parser import HTMLParser

BEFORE_RE = re.compile(r'href="/s/([A-Za-z0-9_]+)\?before=(\d+)"')


class ParseError(Exception):
    pass


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts = []
        self.cur = None
        self.stack = []          # (tag, role) for open tags inside a post
        self.depth = 0           # div depth inside the current message wrapper
        self.capture = None      # 'text' | 'doc' | 'fwd'
        self.capture_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get('class') or ''
        if tag == 'div' and 'tgme_widget_message ' in cls + ' ' and a.get('data-post'):
            self.cur = dict(post=a['data-post'], dt=None, text=[], links=[], doc=[], fwd=[],
                            photo=False)
            self.posts.append(self.cur)
            return
        if self.cur is None:
            return
        if tag == 'time' and a.get('datetime') and self.cur['dt'] is None:
            self.cur['dt'] = a['datetime']
        if 'tgme_widget_message_photo' in cls or 'tgme_widget_message_video' in cls:
            self.cur['photo'] = True
        if self.capture:
            if tag == 'div':
                self.capture_depth += 1
            if tag == 'br' and self.capture == 'text':
                self.cur['text'].append('\n')
            if tag == 'a' and self.capture == 'text' and a.get('href', '').startswith(('http://', 'https://')):
                self.cur['links'].append(a['href'])
            return
        if tag == 'div' and 'tgme_widget_message_text' in cls:
            self.capture, self.capture_depth = 'text', 1
        elif tag == 'div' and 'tgme_widget_message_document_title' in cls:
            self.capture, self.capture_depth = 'doc', 1
        elif 'tgme_widget_message_forwarded_from_name' in cls:
            self.capture, self.capture_depth = 'fwd', (1 if tag == 'div' else 0)
            self._fwd_tag = tag

    def handle_startendtag(self, tag, attrs):
        if self.cur is not None and self.capture == 'text' and tag == 'br':
            self.cur['text'].append('\n')
        elif tag != 'br':
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.cur is None or not self.capture:
            return
        if self.capture == 'fwd' and self.capture_depth == 0:
            if tag == self._fwd_tag:
                self.capture = None
            return
        if tag == 'div':
            self.capture_depth -= 1
            if self.capture_depth == 0:
                self.capture = None

    def handle_data(self, data):
        if self.cur is not None and self.capture:
            self.cur[self.capture].append(data)


def _clean(parts):
    s = ''.join(parts)
    lines = [' '.join(x.split()) for x in s.split('\n')]
    return '\n'.join(x for x in lines if x).strip()


def parse_page(html, channel):
    """Return (posts, before_id). before_id = smallest ?before= link for this channel, or None."""
    p = _Page()
    p.feed(html)
    out = []
    for r in p.posts:
        ch, _, num = r['post'].partition('/')
        if ch.lower() != channel.lower() or not num.isdigit() or not r['dt']:
            continue
        text = _clean(r['text'])
        out.append(dict(
            id=int(num),
            url=f'https://t.me/{channel}/{num}',
            dt_utc=r['dt'],
            text=text,
            links=list(dict.fromkeys(unescape(l) for l in r['links'])),
            forwarded_from=_clean(r['fwd']) or None,
            doc_title=_clean(r['doc']) or None,
            has_photo=r['photo'],
            text_sha=hashlib.sha256(text.encode()).hexdigest()[:16],
        ))
    if not out:
        raise ParseError(f'{channel}: no post with data-post and datetime')
    befores = [int(n) for c, n in BEFORE_RE.findall(html) if c.lower() == channel.lower()]
    return out, (min(befores) if befores else None)
