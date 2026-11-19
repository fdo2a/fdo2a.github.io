"""기사·텔레그램 원글의 숫자 목록 — 수집 잡 안(본문이 있는 곳)에서 뽑아 숫자만 커밋한다 (2026-11-20).

본문은 공개 레포에 올리지 않는다(`fetch_news.py` 머리말). 이 모듈이 쓰는 파일에는 **숫자와 닫힌 낱말만** 들어간다:
  {report_date, extractor, items: [{guid, summary_sha, title_numbers, body_numbers, n, summary_check}]}
  숫자 = [값, 갈래, 통화] — 갈래·통화는 닫힌 목록. 글자가 드는 자리는 guid 와 summary_check.missing(우리 요약의 표기)뿐.
직렬화는 허용 목록(`serialize`)으로만 한다 — 본문 낱말이 새는 길을 코드로 막는다(시험이 강제).

일치(`matches`) = 갈래가 같고, 통화가 둘 다 있으면 같고, 글의 수량이 목록 값을 **글에 인쇄된 자리**로 반올림한 값.
부호는 보지 않는다(기사는 방향을 낱말로 쓴다). 요약 ⊂ 본문 검사는 섀도 — 기사·요약을 버리지 않고 기록만 한다.
설계: docs/superpowers/specs/2026-11-20-number-sources.md §4
"""
import hashlib
import json
import os
import re

from common import numsrc as S

EXTRACTOR = 'v1'
KINDS = ('pct', 'pp', 'bp', 'times', 'money', 'num')
CURRENCIES = ('USD', 'KRW', 'JPY', 'EUR', 'GBP', 'CNY', 'TWD')
MAX_MISSING, MAX_MISSING_LEN = 12, 20
MAX_NUMBERS = 400
ITEM_KEYS = ('guid', 'summary_sha', 'title_numbers', 'body_numbers', 'n', 'summary_check')
STATUSES = ('ok', 'mismatch', 'no_body')

# ── 영문(·일본어 숫자) ───────────────────────────────────────────────────

_CUR_PRE = (('US$', 'USD'), ('C$', None), ('A$', None), ('HK$', None), ('$', 'USD'), ('€', 'EUR'), ('£', 'GBP'),
            ('¥', 'JPY'), ('₩', 'KRW'))
_SCALE_WORD = {'thousand': 1e3, 'k': 1e3, 'million': 1e6, 'mn': 1e6, 'mln': 1e6, 'm': 1e6, 'billion': 1e9,
               'bn': 1e9, 'b': 1e9, 'trillion': 1e12, 'tn': 1e12, 't': 1e12,
               '兆': 1e12, '億': 1e8, '万': 1e4, '千': 1e3}
_CUR_WORD = {'dollars': 'USD', 'dollar': 'USD', 'usd': 'USD', 'yen': 'JPY', '円': 'JPY', 'won': 'KRW', 'euros': 'EUR',
             'euro': 'EUR', 'eur': 'EUR', 'yuan': 'CNY', 'renminbi': 'CNY', 'pounds': 'GBP', 'sterling': 'GBP',
             'ドル': 'USD'}
_EN = re.compile(
    r'(?<![\w.])(US\$|C\$|A\$|HK\$|\$|€|£|¥|₩)?\s?'
    r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|(?<![\d])\.\d+)'
    r'(?:\s?(thousand|million|billion|trillion|mln|mn|bn|tn|[kmbt](?![a-z])|兆|億|万|千))?'
    r'(?:\s?(percentage points?|percentage-points?|pct points?|basis points?|bps?(?![a-z])|percent|per cent|pct|%'
    r'|x(?![a-z])|times|-fold|fold))?'
    r'(?:\s?(dollars?|usd|yen|円|won|euros?|eur|yuan|renminbi|pounds|sterling|ドル))?',
    re.I)


def _en_kind(unit):
    u = (unit or '').lower()
    if not u:
        return None
    if u.startswith(('percentage', 'pct point')):
        return 'pp'
    if u.startswith(('basis', 'bp')):
        return 'bp'
    if u in ('%', 'percent', 'per cent', 'pct'):
        return 'pct'
    if u in ('x', 'times', '-fold', 'fold'):
        return 'times'
    return None


def english_numbers(text):
    """영문·일본어 본문 → [(값, 갈래, 통화)]. 날짜처럼 보이는 네 자리 연도도 「num」으로 둔다(그 갈래는 개수·기타)."""
    out = []
    for m in _EN.finditer(S.norm(text or '')):
        pre, num, scale, unit, cur = m.groups()
        try:
            v = float(num.replace(',', ''))
        except ValueError:
            continue
        if scale:
            v *= _SCALE_WORD.get(scale.lower(), _SCALE_WORD.get(scale, 1))
        kind = _en_kind(unit)
        currency = None
        if pre:
            currency = next((c for p, c in _CUR_PRE if p == pre), None)
        if cur:
            currency = _CUR_WORD.get(cur.lower(), _CUR_WORD.get(cur))
        if kind is None:
            kind = 'money' if (pre or cur) else 'num'
        out.append((v, kind, currency if kind == 'money' else None))
    return out


# ── 한국어(우리 요약·글) ─────────────────────────────────────────────────

_KO_CUR = {'달러': 'USD', '원': 'KRW', '엔': 'JPY', '유로': 'EUR', '파운드': 'GBP', '위안': 'CNY'}


def ko_kind(q):
    """numsrc 수량 → (갈래, 통화). X-코드(날짜·이름)는 None — 대조할 값이 아니다."""
    if q.code or q.value is None:
        return None
    u = q.unit
    if u == '%':
        return 'pct', None
    if u == '%p':
        return 'pp', None
    if u == 'bp':
        return 'bp', None
    if u == '배':
        return 'times', None
    if u in _KO_CUR:
        return 'money', _KO_CUR[u]
    return 'num', None


def korean_numbers(text, terms=()):
    out = []
    for q in S.quantities(text, terms):
        k = ko_kind(q)
        if k:
            out.append((abs(q.value), k[0], k[1]))
    return out


# ── 일치 ────────────────────────────────────────────────────────────────

def matches(q, entry):
    """글의 수량 q 가 목록 항목 [값, 갈래, 통화] 와 같은가 — 목록 값을 q 의 인쇄 자리로 반올림해 본다."""
    k = ko_kind(q)
    if k is None or not isinstance(entry, (list, tuple)) or len(entry) != 3:
        return False
    v, kind, cur = entry
    if kind != k[0] or (cur and k[1] and cur != k[1]):
        return False
    if not isinstance(v, (int, float)) or isinstance(v, bool) or q.quantum <= 0:
        return False
    printed = abs(q.value)
    return abs(round(abs(v) / q.quantum) * q.quantum - printed) <= q.quantum * 1e-6 + 1e-9


def in_list(q, entries):
    return any(matches(q, e) for e in entries or [])


# ── 항목·파일 ───────────────────────────────────────────────────────────

def summary_sha(summary):
    return hashlib.sha256((summary or '').strip().encode('utf-8')).hexdigest()


def _norm_list(nums):
    seen = set()
    for v, kind, cur in nums:
        if kind not in KINDS or (cur is not None and cur not in CURRENCIES):
            continue
        v = float(f'{abs(v):.10g}')
        seen.add((v, kind, cur))
    return [list(x) for x in sorted(seen, key=lambda x: (x[1], x[0], x[2] or ''))][:MAX_NUMBERS]


def build_item(guid, summary_ko, title, body):
    """한 기사(또는 텔레그램 글)의 숫자 항목. body 가 None 이면 본문을 못 받은 것 — 제목 숫자만."""
    title_nums = _norm_list(english_numbers(title) + korean_numbers(title))
    body_nums = _norm_list(english_numbers(body) + korean_numbers(body)) if body else []
    item = {'guid': guid, 'summary_sha': summary_sha(summary_ko), 'title_numbers': title_nums,
            'body_numbers': body_nums, 'n': len(body_nums)}
    pool = body_nums + title_nums
    if not body:
        item['summary_check'] = {'status': 'no_body', 'missing': []}
        return item
    missing = []
    for q in S.quantities(summary_ko or ''):
        if ko_kind(q) is None:
            continue
        if not in_list(q, pool):
            missing.append(S.clip(q.raw, MAX_MISSING_LEN))
    item['summary_check'] = {'status': 'mismatch' if missing else 'ok', 'missing': missing[:MAX_MISSING]}
    return item


def _entry_ok(e):
    return (isinstance(e, list) and len(e) == 3 and isinstance(e[0], (int, float)) and not isinstance(e[0], bool)
            and e[1] in KINDS and (e[2] is None or e[2] in CURRENCIES))


def serialize(report_date, items):
    """허용 목록 직렬화 — 약속한 키와 숫자 배열만. 어긋나는 항목은 버린다(그 기사는 「목록 없음」이 된다)."""
    out = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get('guid'), str):
            continue
        sc = it.get('summary_check') or {}
        if sc.get('status') not in STATUSES:
            continue
        miss = [str(x)[:MAX_MISSING_LEN] for x in (sc.get('missing') or [])][:MAX_MISSING]
        tn = [e for e in it.get('title_numbers') or [] if _entry_ok(e)]
        bn = [e for e in it.get('body_numbers') or [] if _entry_ok(e)]
        if not re.fullmatch(r'[0-9a-f]{64}', str(it.get('summary_sha') or '')):
            continue
        out.append({'guid': it['guid'], 'summary_sha': it['summary_sha'], 'title_numbers': tn, 'body_numbers': bn,
                    'n': len(bn), 'summary_check': {'status': sc['status'], 'missing': miss}})
    return {'report_date': str(report_date), 'extractor': EXTRACTOR, 'items': out}


def numbers_path(datadir, sub, date):
    """`<datadir>/<sub>/numbers/<date>.json` — sub = 'news' | 'telegram'. 하위 폴더인 이유: `news/*.json` 을
    「가장 최근 수집분」으로 고르는 코드(check_news.load_collected)가 숫자 파일을 집지 않게."""
    return os.path.join(datadir, sub, 'numbers', f'{date}.json')


def load_prev(path):
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
        return {it['guid']: it for it in d.get('items') or [] if isinstance(it, dict) and 'guid' in it}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def write_day(path, report_date, rows, prev=None):
    """rows = [(guid, summary_ko, title, body|None)]. 본문을 이번에 못 받았고 요약이 그대로면 앞 판 항목을 옮긴다.
    → (저장한 항목 수, 요약⊂본문 어긋남 [(guid, missing)])."""
    prev = prev or {}
    items, off = [], []
    for guid, summary, title, body in rows:
        if not summary:
            continue
        old = prev.get(guid)
        if body is None and old and old.get('summary_sha') == summary_sha(summary):
            items.append(old)
            continue
        it = build_item(guid, summary, title, body)
        items.append(it)
        if it['summary_check']['status'] == 'mismatch':
            off.append((guid, it['summary_check']['missing']))
    payload = serialize(report_date, items)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return len(payload['items']), off


def lists_for(numbers, summaries):
    """게이트 쪽 — (guid → 숫자 목록 | None, 이유). summaries = {guid: 지금 요약}.
    같은 guid 가 둘 이상 / 뉴스 파일에 없는 guid / 그 기사 항목 없음 / 요약 해시 다름 → 그 기사 목록은 쓰지 않는다."""
    out = {}
    items = (numbers or {}).get('items') if isinstance(numbers, dict) else None
    if not isinstance(items, list):
        return {g: None for g in summaries}
    count = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get('guid'), str):
            count[it['guid']] = count.get(it['guid'], 0) + 1
    by = {it['guid']: it for it in items if isinstance(it, dict) and isinstance(it.get('guid'), str)}
    for g, summ in summaries.items():
        it = by.get(g)
        if it is None or count.get(g, 0) != 1 or it.get('summary_sha') != summary_sha(summ):
            out[g] = None
            continue
        ents = [e for e in (it.get('body_numbers') or []) + (it.get('title_numbers') or []) if _entry_ok(e)]
        out[g] = ents
    return out
