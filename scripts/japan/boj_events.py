"""일본은행 금융정책결정회의 문서 — 목록 읽기와 공표문·전망 변경점. 네트워크 없음 (2026-11-27).

수집은 `scripts/collect_boj_events.py`, 검사는 `japan/daily_gate.py` 의 boj 절. 원천(일본어 원문, 2026-11-27 실측):
  · 공표문 `/mopo/mpmdeci/mpr_{Y}/k{yymmdd}{a-d}.pdf` — 목록 `/mopo/mpmdeci/state_{Y}/index.htm`. 같은 회의의
    「（参考）」 부속 문서는 거른다. 회의 종료 직후(10/30 12:02).
  · 전망 기본 견해 `/mopo/outlook/gor{yymm}a.pdf` — 목록 `/mopo/outlook/index.htm`(b 는 배경 설명 포함 전문).
  · 총재 정례 회견 기록 `/about/press/kaiken_{Y}/kk{yymmdd}a.pdf` — 목록 `/about/press/kaiken_{Y}/index.htm` 에서
    「総裁定例記者会見（M月D日）」 이름으로 고른다(같은 목록에 심의위원·부총재 회견이 섞여 있다). 다음 영업일 공개.
  · 주요 의견 `/mopo/mpmsche_minu/opinion_{Y}/opi{yymmdd}.pdf`, 의사요지 `/mopo/mpmsche_minu/minu_{Y}/g{yymmdd}.pdf`
    — 파일 이름의 날짜는 회의 마지막 날, 공개일은 일정표(`/mopo/mpmsche_minu/index.htm`)에 있다.
"""
import difflib
import html as _html
import re

from common.cb_quote import normalize_cjk

BASE = 'https://www.boj.or.jp'
STATE_INDEX = BASE + '/mopo/mpmdeci/state_{year}/index.htm'
OUTLOOK_INDEX = BASE + '/mopo/outlook/index.htm'
KAIKEN_INDEX = BASE + '/about/press/kaiken_{year}/index.htm'
OPINION_INDEX = BASE + '/mopo/mpmsche_minu/opinion_{year}/index.htm'
MINUTES_INDEX = BASE + '/mopo/mpmsche_minu/minu_{year}/index.htm'

_LINK = re.compile(r'<a\b[^>]*\bhref="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')


def links(page):
    """목록 페이지 → [(절대 주소, 링크 글)]."""
    out = []
    for m in _LINK.finditer(page or ''):
        href = _html.unescape(m.group(1))
        text = re.sub(r'\s+', ' ', _html.unescape(_TAG.sub('', m.group(2)))).strip()
        out.append((href if href.startswith('http') else BASE + href, text))
    return out


def _yymmdd(iso):
    return iso[2:4] + iso[5:7] + iso[8:10]


def statement_links(page, meeting_date):
    """그 회의의 공표문 PDF(a 가 먼저) — 「（参考）」 부속 문서는 뺀다."""
    pat = re.compile(r'/mopo/mpmdeci/mpr_\d{4}/k%s([a-z])\.pdf$' % _yymmdd(meeting_date))
    got = [(pat.search(u).group(1), u) for u, t in links(page) if pat.search(u) and not t.startswith(('（参考）', '(参考)'))]
    return [u for _s, u in sorted(got)]


def statement_meetings(page):
    """공표문 목록에 있는 회의 날짜(오름차순) — 직전 공표문을 찾는 데 쓴다."""
    out = set()
    for u, _t in links(page):
        m = re.search(r'/mpr_(\d{4})/k(\d{2})(\d{2})(\d{2})a\.pdf$', u)
        if m:
            out.add(f'20{m.group(2)}-{m.group(3)}-{m.group(4)}')
    return sorted(out)


def outlook_links(page):
    """[(YYYY-MM, 주소)] — 기본 견해(a)만, 오름차순."""
    out = []
    for u, _t in links(page):
        m = re.search(r'/mopo/outlook/gor(\d{2})(\d{2})a\.pdf$', u)
        if m:
            out.append((f'20{m.group(1)}-{m.group(2)}', u))
    return sorted(set(out))


def presser_link(page, meeting_date):
    """회의 마지막 날의 총재 정례 회견 기록 → (공개일 YYYY-MM-DD, 주소) | (None, None)."""
    _y, m, d = (int(x) for x in meeting_date.split('-'))
    want = f'総裁定例記者会見（{m}月{d}日）'
    for u, t in links(page):
        hit = re.search(r'/kaiken_\d{4}/kk(\d{2})(\d{2})(\d{2})a\.pdf$', u)
        if hit and t.startswith(want):
            return f'20{hit.group(1)}-{hit.group(2)}-{hit.group(3)}', u
    return None, None


def doc_link(page, prefix, meeting_date):
    """주요 의견(`opi`)·의사요지(`g`) PDF 주소 | None — 파일 이름의 날짜는 회의 마지막 날."""
    pat = re.compile(r'/%s%s\.pdf$' % (re.escape(prefix), _yymmdd(meeting_date)))
    return next((u for u, _t in links(page) if pat.search(u)), None)


# ── 공표문 변경점: 정책금리 문장 + 표결 문장 ─────────────────────────────────────────
# 공표문은 제목·구성이 회의마다 달라(「当面の金融政策運営について」/「金融市場調節方針の変更について」) 문장 단위
# redline 을 하지 않는다. 금리 문장과 표결 문장만 맞댄다. 공백을 지운 NFKC 꼴에서 찾는다(PDF 는 글자 사이에 공백).
_RATE = re.compile(r'無担保コールレート\(オーバーナイト物\)を、?[\d.]+%程度で推移するよう促す')
_VOTE = re.compile(r'\(注\)賛成:[^。]*。(?:反対:[^。]*。)?')
_UNANIMOUS = re.compile(r'金融市場調節方針[^。]{0,40}\(全員一致\)')


def rate_sentence(text):
    m = _RATE.search(normalize_cjk(text))
    return m.group(0) + '。' if m else None


def vote_sentence(text):
    t = normalize_cjk(text)
    m = _VOTE.search(t)
    if m:
        return m.group(0)
    u = _UNANIMOUS.search(t)
    return u.group(0) if u else None


def statement_diff(prev_text, curr_text):
    """직전 공표문 대비 금리·표결 문장 변경. 어느 공표문에서든 둘 중 하나라도 못 찾으면 None(비교 포기)."""
    parts = {}
    for name, fn in (('정책금리', rate_sentence), ('표결', vote_sentence)):
        a, b = fn(prev_text), fn(curr_text)
        if a is None or b is None:
            return None
        parts[name] = (a, b)
    changed = [{'part': k, 'before': a, 'after': b} for k, (a, b) in parts.items() if a != b]
    return {'changed': changed, 'added': [], 'removed': [], 'kept': len(parts) - len(changed),
            'current': {k: b for k, (_a, b) in parts.items()}}


# ── 전망 기본 견해: 문장 단위 redline ─────────────────────────────────────────────
_SENT = re.compile(r'(?<=。)')
OUTLOOK_MIN_SENTENCES = 10


def outlook_sentences(text):
    """기본 견해 PDF 글 → 문장(공백 지운 NFKC 꼴). 쪽 번호·머리글은 마침표가 없어 자연히 빠진다."""
    t = normalize_cjk(text)
    return [s for s in (x.strip() for x in _SENT.split(t)) if len(s) >= 15 and s.endswith('。')]


def outlook_redline(prev_text, curr_text, cutoff=0.55):
    """직전 기본 견해 대비 {'added','removed','changed','kept'}. 문장이 10개 미만이면 None."""
    a, b = outlook_sentences(prev_text), outlook_sentences(curr_text)
    if len(a) < OUTLOOK_MIN_SENTENCES or len(b) < OUTLOOK_MIN_SENTENCES:
        return None
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    removed, added, kept = [], [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            kept += i2 - i1
        else:
            removed.extend(a[i1:i2])
            added.extend(b[j1:j2])
    changed, used = [], set()
    for new in list(added):
        best, score = None, cutoff
        for i, old in enumerate(removed):
            if i in used:
                continue
            r = difflib.SequenceMatcher(None, old, new, autojunk=False).ratio()
            if r > score:
                best, score = i, r
        if best is not None:
            used.add(best)
            changed.append({'before': removed[best], 'after': new, 'ratio': round(score, 3)})
            added.remove(new)
    removed = [s for i, s in enumerate(removed) if i not in used]
    return {'added': added, 'removed': removed, 'changed': changed, 'kept': kept}
