"""Publication gate for Telegram-sourced sentences (2026-11-06). Used by scripts/check_telegram.py.

Contract (writers: brief-report-writer.md / kr-report-writer.md 「텔레그램 견해·의견」):
- every Telegram-derived sentence sits inside an element carrying data-tg="<item id>";
- view  : names the firm and the analyst (「키움증권 한지영 연구원은 …로 봤다」);
- report: names the outlet and reads as that outlet's report (「로이터에 따르면」);
- opinion: reads as an opinion (「…라는 의견도 나왔다」) and names the credited outlet if any;
- numbers inside the element come from that item's summary_ko; at most 3 views and 3 others;
- no channel name, 「텔레그램」 or t.me anywhere; firm/analyst names never outside the elements;
- a sentence outside the elements that largely repeats a Telegram summary is blocked.
What it cannot see: a sentence that says the OPPOSITE of the summary with the same words and
numbers — that is left to the post-publish review. The editor's note (human text) is exempt.
"""
import re
from difflib import SequenceMatcher

from .numbers import strip_comments
from .telegram import CHANNEL_WORDS, FIRM_HANWHA, FIRM_KIWOOM, POST_MAX_OPINIONS, POST_MAX_VIEWS

NOTE_RE = re.compile(r'<section\b[^>]*\bdata-editor-note\s*=\s*"[^"]*"[^>]*>.*?</section>', re.S)
OPEN_RE = re.compile(r'<([a-zA-Z][\w-]*)\b([^>]*?)\bdata-tg\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))([^>]*)>', re.I)
TAG_RE = re.compile(r'<[^>]+>')
BANNED = re.compile(r't\.me/|telegram\.me|텔레그램|Telegram', re.I)
OPINION_WORDS = re.compile(r'의견|시각|관측|해석|전망|평가|주장|지적|우려|분석|목소리|얘기|소식|전해|제기|나왔')
REPORT_WORDS = re.compile(r'따르면|보도|전했|밝혔|의하면|보도했')
MIN_COVERAGE = 0.3       # share of the element's text that matches its summary
OUTSIDE_COVERAGE = 0.7   # a sentence outside the elements this close to a summary is blocked
OUTSIDE_MIN_CHARS = 25


UNITS = r'%p|%|퍼센트|bp|배|억\s*달러|억\s*원|조\s*원|만\s*달러|달러|원|억|조|만|포인트|pt|년물|bp'
NUM_RE = re.compile(r'(-?\d[\d,]*(?:\.\d+)?)\s*(' + UNITS + r')?')
DATE_MASK = re.compile(r'\d{4}-\d{2}-\d{2}|\d{4}년|\d{1,2}월|\d{1,2}일|\d{1,2}/\d{1,2}|\d{1,2}분기|\d{1,2}시|\d{1,2}분')


def number_units(text):
    """{(value, unit)} for every figure in the text, dates and clock times masked. Unit-sensitive:
    5.5% and 5.5bp and 5.5달러 are different claims."""
    t = DATE_MASK.sub(' ', text or '')
    t = re.sub(r'(?<=[^\s(\[])-(?=\d)', ' ', t)       # hyphen joining words, not a sign
    out = set()
    for m in NUM_RE.finditer(t):
        try:
            val = round(float(m.group(1).replace(',', '')), 4)
        except ValueError:
            continue
        out.add((val, re.sub(r'\s+', '', m.group(2) or '')))
    return out


def _visible(fragment):
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', fragment, flags=re.S)
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', t)).strip()


def _squash(s):
    return re.sub(r'\s+', '', s or '')


def coverage(text, summary):
    a, b = _squash(text), _squash(summary)
    if not a or not b:
        return 0.0
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(m.size for m in blocks if m.size >= 2) / len(a)


def elements(html):
    """[(id, inner_html, start, end)] for every data-tg element, nested tags balanced."""
    out = []
    for m in OPEN_RE.finditer(html):
        tag, start = m.group(1).lower(), m.start()
        depth, pos = 1, m.end()
        tok = re.compile(r'<(/?)' + re.escape(tag) + r'\b[^>]*?(/?)>', re.I)
        while depth:
            n = tok.search(html, pos)
            if not n:
                pos = len(html)
                break
            if n.group(1):
                depth -= 1
            elif not n.group(2):
                depth += 1
            pos = n.end()
        tid = next(g for g in (m.group(3), m.group(4), m.group(5)) if g is not None)
        out.append((tid, html[m.end():pos], start, pos))
    return out


def check(html, data, warnings=None):
    v = []
    warn = warnings if warnings is not None else []
    doc = NOTE_RE.sub(' ', strip_comments(html or ''))
    vis = _visible(doc)
    # raw markup too: any attribute quoting, any element (a, img, link, meta)
    if BANNED.search(vis) or re.search(r't\.me/|telegram\.me', doc, re.I):
        v.append('「텔레그램」·t.me 가 발행본에 있다 — 채널 출처는 쓰지 않는다')
    for w in CHANNEL_WORDS:
        if w.lower() in vis.lower():
            v.append(f'채널 이름 「{w}」 이 발행본에 있다')
    els = elements(doc)
    items = {it['id']: it for it in (data or {}).get('items', [])}
    if els and not data:
        return v + ['data-tg 표식이 있는데 텔레그램 파일이 없다']
    n_view = n_other = 0
    names = {FIRM_KIWOOM, FIRM_HANWHA}
    for it in items.values():
        if it.get('kind') == 'view' and it.get('analyst'):
            names.add(it['analyst'])
    for tid, inner, _, _ in els:
        it = items.get(tid)
        text = _visible(inner)
        if not it or not it.get('summary_ko'):
            v.append(f'data-tg="{tid}" — 파일에 없거나 요약 없는 항목')
            continue
        kind, summ = it.get('kind'), it['summary_ko']
        src = (it.get('source') or {}).get('name')
        if kind == 'view':
            n_view += 1
            if it.get('firm') and it['firm'] not in text:
                v.append(f'data-tg="{tid}" — 증권사 견해인데 「{it["firm"]}」 이 문장에 없다')
            if it.get('analyst') and it['analyst'] not in text:
                v.append(f'data-tg="{tid}" — 증권사 견해인데 「{it["analyst"]}」 이 문장에 없다')
        else:
            n_other += 1
            if kind == 'report':
                if not src or src not in text:
                    v.append(f'data-tg="{tid}" — 원문 출처 「{src}」 를 문장 안에 단다')
                if not REPORT_WORDS.search(text):
                    v.append(f'data-tg="{tid}" — 보도 틀(「…에 따르면」·「…라고 보도했다」)이 없다')
            else:
                if not OPINION_WORDS.search(text):
                    v.append(f'data-tg="{tid}" — 의견 틀(「…라는 의견도 나왔다」)이 없다')
                if src and src not in text:
                    v.append(f'data-tg="{tid}" — 글이 밝힌 출처 「{src}」 를 문장 안에 단다')
        extra = number_units(text) - number_units(summ)
        if extra:
            v.append(f'data-tg="{tid}" — 요약에 없는 수치 {sorted(extra)[:5]}')
        body = text
        for nm in names | ({src} if src else set()):
            body = body.replace(nm, '')
        if coverage(body, summ) < MIN_COVERAGE:
            v.append(f'data-tg="{tid}" — 문장이 그 항목 요약과 맞지 않는다(겹침 {coverage(body, summ):.2f})')
    if n_view > POST_MAX_VIEWS:
        v.append(f'증권사 견해 {n_view}건 — 최대 {POST_MAX_VIEWS}')
    if n_other > POST_MAX_OPINIONS:
        v.append(f'의견·보도 {n_other}건 — 최대 {POST_MAX_OPINIONS}')
    # outside the elements
    outside = doc
    for _, _, s, e in sorted(els, key=lambda x: -x[2]):
        outside = outside[:s] + ' ' + outside[e:]
    out_vis = _visible(outside)
    # 키움증권 is also a listed stock, so a bare firm name outside is fine; an analyst name, or the
    # firm as the speaker of a view, is not
    # an analyst named outside the elements is blocked only when that sentence carries the
    # analyst's Telegram view (another source may quote the same person)
    by_analyst = {}
    for it in items.values():
        if it.get('kind') == 'view' and it.get('analyst') and it.get('summary_ko'):
            by_analyst.setdefault(it['analyst'], []).append(it['summary_ko'])
    for sent in re.split(r'(?<=[다요])\.\s*', out_vis):
        for nm, sums_a in by_analyst.items():
            if nm in sent and max(coverage(sent.replace(nm, ''), x) for x in sums_a) >= 0.4:
                warn.append(f'「{nm}」 의 텔레그램 견해와 닮은 문장이 data-tg 표식 밖에 있다 — 텔레그램에서 왔으면 감싼다: 「{sent[:40]}…」')
    sums = [it['summary_ko'] for it in items.values() if it.get('summary_ko')]
    for sent in re.split(r'(?<=[다요])\.\s*', out_vis):
        if len(_squash(sent)) < OUTSIDE_MIN_CHARS:
            continue
        best = max((coverage(sent, s) for s in sums), default=0)
        if best >= OUTSIDE_COVERAGE:
            # an independent source can say the same thing — flag for review, do not block
            warn.append(f'표식 밖 문장이 텔레그램 요약과 겹친다({best:.2f}) — 텔레그램에서 왔으면 data-tg 로 감싼다: 「{sent[:40]}…」')
    return v
