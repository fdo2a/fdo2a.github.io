"""목록 JSON 과 sitemap 갱신.

sitemap 은 **재생성이 아니라 병합**한다. 지금 이 사이트에는 US·KR 브리프 말고
thesis 파이프라인이 따로 있고, 셋이 각자 sitemap 을 건드린다. 전체 재생성은 남의
항목을 지운다 — 모르는 URL 은 건드리지 않는 것이 유일하게 안전한 규약이다.
"""

import re

_URL = re.compile(r'<url>\s*(.*?)\s*</url>', re.S)
_LOC = re.compile(r'<loc>(.*?)</loc>', re.S)

_HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
_TAIL = '</urlset>\n'


def upsert_entry(entries, entry, key='key'):
    out = [e for e in (entries or []) if e.get(key) != entry.get(key)]
    out.append(entry)
    out.sort(key=lambda e: e.get(key) or '', reverse=True)
    return out


def merge_sitemap(existing_xml, urls, lastmod):
    """우리가 아는 URL 만 갱신·추가하고 나머지 <url> 블록은 원문 그대로 보존한다."""
    kept, seen = [], set()
    for block in _URL.findall(existing_xml or ''):
        m = _LOC.search(block)
        if not m:
            continue
        loc = m.group(1).strip()
        if loc in seen:
            continue
        seen.add(loc)
        if loc in set(urls):
            kept.append(f'<loc>{loc}</loc><lastmod>{lastmod}</lastmod>')
        else:
            kept.append(block)          # 남의 항목 — 원문 보존
    for loc in urls:
        if loc not in seen:
            kept.append(f'<loc>{loc}</loc><lastmod>{lastmod}</lastmod>')
    body = ''.join(f'  <url>{b}</url>\n' for b in kept)
    return _HEAD + body + _TAIL
