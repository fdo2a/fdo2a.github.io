"""Telegram notes for the Japan daily close brief — which posts of the one channel are offered (2026-11-15).

Pure rules; the collector is `scripts/fetch_telegram_jp.py`. Nothing here keeps a read position:
the posts of session S are those stamped in `(cut(prev), cut(S)]`, a function of the session
calendar alone. A post is offered when it is about Japan (`jp_basis`), is not a re-upload of an old
note (`note_date`, burst guard) and is not chatter. The writer decides what is worth quoting.
Channel names, 「텔레그램」 and t.me never reach a page (telegram_gate, layout 'jp').
Design: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md
"""
import re
from datetime import date, datetime, timedelta, timezone

from . import telegram as tg
from .tg_links import classify

JP_CHANNEL = 'aethersemiconductor'
JST = timezone(timedelta(hours=9))
CUT = (16, 30)            # the daily news cut, JST
READ_MARGIN_H = 12        # read this far below the floor so a re-upload straddling it is seen whole
MAX_PAGES = 150
HEAD = 160                # a post is about what it opens with
MARKET_REPEAT = 3
STALE_DAYS = 2            # a note dated more than this many days before it was posted is a re-upload
BURST_MIN = 20            # this many stale-dated posts in one read = a bulk re-upload
BURST_TAIL_S = 120        # unmarked continuation messages follow their head within seconds
JP_VALVE = 40             # safety valve, not an editorial cap (largest 6-day window measured: 18)
MIN_TEXT = 80             # an unlinked post shorter than this is a remark, not a note (11/06 실측 40·63자)

_HB = r'(?<![가-힣A-Za-z])'                    # a Korean name starts a word
_LB, _LA = r'(?<![A-Za-z])', r'(?![A-Za-z])'    # a Latin name is the whole word

JP_MARKET = re.compile(
    r'일본은행|' + _LB + r'BOJ' + _LA + r'|일본\s?증시|도쿄\s?증시|(?:닛케이|니케이)\s?(?:225|지수|평균)|'
    + _LB + r'TOPIX' + _LA + r'|토픽스|' + _LB + r'JGB' + _LA + r'|일본\s?국채|'
    r'(?<![가-힣])엔(?:화|저|고)|달러[/·\-]엔|엔[/·]달러|USD/?JPY|엔\s?캐리')
JP_TICKER = re.compile(r'(?<![\d.,])\d{4}\.T\b|(?<![\d.,])\d{4}\s?JP\b|TYO:\s?\d{4}')
# Listed Japanese companies as Korean posts write them. Not here on purpose: bare 「일본」 (see
# 'country'), 「닛케이」 alone (the newspaper), and brokers/banks (노무라·미즈호·다이와·SMBC·MUFG) — they
# are the authors of relayed notes. A short name must not run on into another word: a blocklist
# of compounds, so every particle form matches (「소니로」「소니와의」). A miss here only adds or loses a
# candidate the writer would judge anyway.
_NAMES_KO = (
    '도요타', '토요타', '소니(?!아)', '소프트뱅크', '키옥시아', '어드밴테스트', '어드반테스트', '아드반테스트',
    r'도쿄\s?일렉트론', '레이저텍', '디스코(?!드|텍|장|팡|볼)', r'스크린\s?홀딩스', '르네사스', '무라타', '교세라', '이비덴',
    '신에츠', '섬코', '로옴', '후지쿠라', r'후루카와\s?(?:전기|전공)', r'스미토모\s?(?:전기|전공|화학|금속광산|중공업|상사)',
    r'JX\s?금속', '아지노모토', r'미쓰비시\s?(?:중공업|전기|상사|머티리얼|케미칼|화학|가스화학)', r'가와사키\s?중공업', '히타치',
    '파나소닉', '닌텐도', '패스트리테일링', '유니클로', '키엔스', '화낙', '다이킨', '혼다', '닛산', '덴소', '스바루',
    '마쓰다', '후지쯔', '후지츠', '도시바', '라피더스', '닛토보', '레조낙', '도쿄오카', r'미쓰이\s?(?:금속|물산|화학|부동산)',
    '일본제철', '닛폰스틸', '고마쓰', '코마츠', '다이후쿠', '야스카와', '니덱', r'리크루트\s?홀딩스', r'다케다\s?제약',
    r'다이이[찌치]\s?산쿄', r'[추주]가이\s?제약', '이토추', '세븐앤아이', '아사히카세이', '도레이', '닛토덴코',
    '타이요유덴', '다이요유덴', '메이코', '후지필름', '후지전기', '캐논(?!볼)', '니콘', '올림푸스', '시마노', r'도와\s?홀딩스',
    '울박', '알박(?!기)', r'코쿠사이\s?일렉트릭', '로체(?!스)', '도쿄정밀', '도쿄세이미츠', '소시오넥스트', '미네베아',
    '오므론', '브리지스톤', '라쿠텐', '오리엔탈랜드', r'(?:도쿄|간사이|주부)\s?전력', '신코전기', '재팬디스플레이',
)
_NAMES_EN = ('TDK', 'NTT', 'KDDI', 'HOYA', 'SUMCO', 'TOWA', 'ULVAC', 'KOKUSAI', 'JEOL', 'JSR', 'Advantest', 'Kioxia',
             'Lasertec', 'Renesas', 'Murata', 'Kyocera', 'Ibiden', 'Fujikura', 'SoftBank', 'Toyota', 'Rapidus', 'Resonac',
             'Keyence', 'Fanuc', 'Daikin', 'Nintendo', 'Hitachi', 'Panasonic', 'Sony', 'Tokyo Electron')
JP_NAMES = re.compile(_HB + '(?:' + '|'.join(_NAMES_KO) + ')|' + _LB + '(?:' + '|'.join(_NAMES_EN) + ')' + _LA)
_COUNTRY = re.compile(r'일본(?!은행|\s?[&＆])')        # 「일본&미국」 is the channel's own name


def jp_basis(text):
    """'keyword' — a Japanese market word, ticker or listed company opens the post (or market words
    recur); 'country' — 「일본」 opens it and recurs; else None."""
    t = text or ''
    firsts = [m.start() for m in (rx.search(t) for rx in (JP_MARKET, JP_TICKER, JP_NAMES)) if m]
    if firsts and min(firsts) < HEAD:
        return 'keyword'
    if len(JP_MARKET.findall(t)) >= MARKET_REPEAT:
        return 'keyword'
    hits = [m.start() for m in _COUNTRY.finditer(t)]
    if len(hits) >= 2 and hits[0] < HEAD:
        return 'country'
    return None


# ── the original date a re-uploaded note carries ─────────────────────────
_NOTE_DATE = (re.compile(r'🗓\s*(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})'),
              re.compile(r'↪[^\n]{0,100}?전달\s*[·•∙]\s*(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})'))
NOTE_HEAD = 140
_DATE_LINE = re.compile(r'^\s*(?:🗓|↪)')


def note_date(text):
    """YYYY-MM-DD from a leading 「🗓 2026.08.05 원문」 / 「↪️ … 전달 · 2026.08.21」, else None."""
    head = (text or '')[:NOTE_HEAD]
    for rx in _NOTE_DATE:
        m = rx.search(head)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return None
    return None


# ── who a relayed note is from: the title line's leading 「이름)」 ─────────
# variant (spaces out, lower case) -> the one name a page may use. Ambiguous short forms (MS, GS,
# DB) are left out: a wrong broker on a page is worse than none.
RELAY_FIRMS = {
    'jp모건': 'JP모건', 'jp모간': 'JP모건', 'jpm': 'JP모건', 'jpmorgan': 'JP모건', '제이피모건': 'JP모건',
    '모건스탠리': '모건스탠리', '모간스탠리': '모건스탠리', 'morganstanley': '모건스탠리',
    '골드만삭스': '골드만삭스', '골드만': '골드만삭스', 'goldmansachs': '골드만삭스', 'goldman': '골드만삭스',
    '씨티': '씨티', '시티': '씨티', '씨티그룹': '씨티', 'citi': '씨티', 'citigroup': '씨티',
    'ubs': 'UBS', '노무라': '노무라', 'nomura': '노무라', '미즈호': '미즈호', 'mizuho': '미즈호',
    '다이와': '다이와', 'daiwa': '다이와', 'smbc닛코': 'SMBC닛코', 'smbcnikko': 'SMBC닛코', '오카산': '오카산',
    '도이체방크': '도이체방크', '도이치뱅크': '도이체방크', '도이치방크': '도이체방크', 'deutschebank': '도이체방크',
    '번스타인': '번스타인', 'bernstein': '번스타인', '제프리스': '제프리스', 'jefferies': '제프리스',
    'bofa': 'BofA', '뱅크오브아메리카': 'BofA', 'boa': 'BofA', '메릴린치': 'BofA',
    '바클레이즈': '바클레이즈', '바클레이스': '바클레이즈', 'barclays': '바클레이즈', 'hsbc': 'HSBC', 'clsa': 'CLSA',
    '맥쿼리': '맥쿼리', 'macquarie': '맥쿼리', '에버코어': '에버코어', 'evercore': '에버코어',
    '웰스파고': '웰스파고', 'wellsfargo': '웰스파고', '키뱅크': '키뱅크', 'keybanc': '키뱅크',
    'td코웬': 'TD코웬', 'tdcowen': 'TD코웬', '니덤': '니덤', 'needham': '니덤', '서스퀘하나': '서스퀘하나',
    '레이먼드제임스': '레이먼드제임스', '파이퍼샌들러': '파이퍼샌들러', '웨드부시': '웨드부시', 'wedbush': '웨드부시',
    '오펜하이머': '오펜하이머', '스티펠': '스티펠', '캔터': '캔터', 'bnp파리바': 'BNP파리바', 'bnpparibas': 'BNP파리바',
    '루프캐피탈': '루프캐피탈', '베어드': '베어드', '울프리서치': '울프리서치', '멜리우스': '멜리우스',
    '미즈호증권': '미즈호', '다이와증권': '다이와', '노무라증권': '노무라', 'cantor': '캔터', 'cantorfitzgerald': '캔터',
    'evercoreisi': '에버코어', '에버코어isi': '에버코어', 'rbc': 'RBC', 'stifel': '스티펠', 'truist': '트루이스트',
    '트루이스트': '트루이스트', 'pipersandler': '파이퍼샌들러', 'rosenblatt': '로젠블랫', '로젠블랫': '로젠블랫',
    'raymondjames': '레이먼드제임스', 'oppenheimer': '오펜하이머', 'susquehanna': '서스퀘하나', 'baird': '베어드',
    'wolferesearch': '울프리서치', 'melius': '멜리우스', 'loopcapital': '루프캐피탈',
}
# outlets a title line credits that the US/KR list does not carry (11/14 실측 「닛케이 아시아)」「교도통신)」)
JP_OUTLETS = {'닛케이 아시아': '닛케이아시아', 'Nikkei Asia': '닛케이아시아', '교도통신': '교도통신', '지지통신': '지지통신',
              'NHK': 'NHK', '요미우리': '요미우리신문', '아사히': '아사히신문', '트렌드포스': '트렌드포스',
              '더 인포메이션': '디인포메이션', 'NYT': '뉴욕타임스', '니혼게이자이': '니혼게이자이'}
_OUTLETS = {re.sub(r'\s+', '', k).lower(): v for k, v in {**tg.OUTLETS, **JP_OUTLETS}.items()}
_PREFIX = re.compile(r'^[^A-Za-z가-힣\n()]{0,4}([A-Za-z가-힣][A-Za-z가-힣&. ]{1,19}?)\s*\)')
_SERVICE = re.compile(r' pinned «')            # 「… pinned «…»」 — the channel's own notice, not a post


def remark(post):
    """Not a note: the US/KR chatter rule, a service line, or a short unlinked remark."""
    text = post.get('text') or ''
    return tg.chatter(post) or bool(_SERVICE.search(text[:120])) or (len(text) < MIN_TEXT and not post.get('links'))


def title_prefix(text):
    """(relay_firm, credited outlet) from the leading 「이름)」 of the title line; (None, None) when
    the name is in neither list."""
    for line in (text or '').split('\n'):
        if not line.strip() or _DATE_LINE.match(line):
            continue
        m = _PREFIX.match(line)
        if not m:
            return None, None
        key = re.sub(r'[\s.]+', '', m.group(1)).lower()
        if key in RELAY_FIRMS:
            return RELAY_FIRMS[key], None
        return None, _OUTLETS.get(key)
    return None, None


def _firm_rx(key):
    # as written on a page: spaces may sit between the characters, and the name starts a word
    return re.compile(r'(?<![가-힣A-Za-z])' + r'\s*'.join(re.escape(c) for c in key) + (r'(?![A-Za-z])' if key.isascii() else ''),
                      re.I)


_FIRM_RX = [(_firm_rx(k), v) for k, v in sorted(RELAY_FIRMS.items(), key=lambda kv: -len(kv[0]))]


def firms_in(text):
    """Canonical names of every RELAY_FIRMS variant the text carries — longest variant first, so
    「골드만삭스」 is not also 「골드만」."""
    t, found = text or '', set()
    for rx, name in _FIRM_RX:
        if rx.search(t):
            found.add(name)
            t = rx.sub('\x00', t)
    return found


# ── window ───────────────────────────────────────────────────────────────

def cut(session):
    d = date.fromisoformat(session)
    return datetime(d.year, d.month, d.day, CUT[0], CUT[1], tzinfo=JST)


def window(session, prev):
    """(floor, ceiling]: the previous Tokyo session's cut to this session's."""
    floor, ceiling = cut(prev), cut(session)
    if floor >= ceiling:
        raise ValueError(f'직전 세션 {prev} 이 세션 {session} 보다 앞서지 않는다')
    return floor, ceiling


def _dt(post):
    return datetime.fromisoformat(post['dt_utc'])


def _stale(post):
    """The note's own date is more than STALE_DAYS before the JST day it was posted. Measured
    against the post, not the session: a note dated Friday and forwarded on Saturday is Monday's
    news, and after a holiday week the session date would call every such note old."""
    nd = note_date(post.get('text'))
    return bool(nd) and nd < (_dt(post).astimezone(JST).date() - timedelta(days=STALE_DAYS)).isoformat()


def burst_span(posts):
    """(start, end) of a bulk re-upload among everything read, or None."""
    marked = sorted(_dt(p) for p in posts if _stale(p))
    if len(marked) < BURST_MIN:
        return None
    return marked[0], marked[-1] + timedelta(seconds=BURST_TAIL_S)


def classify_post(post, basis):
    """-> item without a summary. kind/source as in the US/KR path; plus note_date and relay_firm."""
    text = post.get('text') or ''
    firm, credit = title_prefix(text)
    base = {'id': f'{JP_CHANNEL}/{post["id"]}', 'channel': JP_CHANNEL, 'group': 'individual',
            'dt_utc': post['dt_utc'], 'url': post['url'], 'market_basis': basis,
            'firm': None, 'analyst': None, 'relay_firm': firm, 'note_date': note_date(text)}
    link = tg.origin_link(post)
    if link and tg.paywalled(link):
        name = tg.outlet_for(link)
        return dict(base, kind='opinion', article_date=tg.url_date(link),
                    source={'name': name, 'url': None, 'basis': 'paywalled_link'} if name else None)
    if link:
        return dict(base, kind='report', article_date=tg.url_date(link),
                    source={'name': tg.outlet_for(link), 'url': link, 'basis': 'link'})
    return dict(base, kind='opinion', source=credit_source(text, credit))


def credit_source(text, credit=None):
    """The outlet an unlinked post credits — the title prefix first, then the US/KR patterns."""
    name = credit or tg.credited_source(text)
    return {'name': name, 'url': None, 'basis': 'credit'} if name else None


def candidates(posts, session, floor, ceiling):
    """posts = everything read (the margin below the floor included). -> ([(item, post)] oldest
    first, counts of what was left out and why)."""
    stats = {'read': len(posts), 'outside': 0, 'chatter': 0, 'stale': 0, 'burst': 0, 'not_japan': 0, 'dup': 0}
    span = burst_span(posts)
    out, seen = [], set()
    for p in sorted(posts, key=lambda p: (_dt(p), p['id'])):
        when = _dt(p)
        if not floor < when <= ceiling:
            stats['outside'] += 1
            continue
        if remark(p):
            stats['chatter'] += 1
            continue
        if _stale(p):
            stats['stale'] += 1
            continue
        if span and span[0] <= when <= span[1]:
            stats['burst'] += 1
            continue
        basis = jp_basis(p.get('text'))
        if not basis:
            stats['not_japan'] += 1
            continue
        link = tg.origin_link(p)
        key = classify(link)[1] if link else None
        if key and key in seen:
            stats['dup'] += 1
            continue
        if key:
            seen.add(key)
        out.append((classify_post(p, basis), p))
    return out, stats


def valve(cands):
    """-> (kept oldest first, how many were dropped). Keyword posts before country posts, then by
    the US/KR score, newest first."""
    if len(cands) <= JP_VALVE:
        return cands, 0
    ranked = sorted(cands, key=lambda c: (c[0]['market_basis'] == 'keyword', tg._score(c[0], c[1], False), c[0]['dt_utc']),
                    reverse=True)
    kept = sorted(ranked[:JP_VALVE], key=lambda c: (c[0]['dt_utc'], c[0]['id']))
    return kept, len(cands) - JP_VALVE
