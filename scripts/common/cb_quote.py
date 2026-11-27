"""한국은행·일본은행 원문 인용 대조 — 한국어·일본어 원문용 (2026-11-27).

미국 연준 칸(`us/fed_events.verify_quote`)과 같은 알고리즘(조각·순서·간격·생략 횟수)을 쓰되, 대조 문자열을
**공백을 전부 지운 꼴**로 만든다. 실측(2026-11-27): 한은 RSS 본문은 span 경계에서(「국내경 제는」), PDF 는
줄바꿈에서 단어가 갈리고, 일본은행 PDF 는 글자 사이에 공백이 들어간다(「わ が 国」·「１． ２５％」). 공백을
남기면 맞는 인용이 매일 걸린다. 한국어·일본어 인용은 공백 위치가 뜻을 바꾸지 않으므로 지워도 잃는 것이 없다.

미국 코드는 고치지 않는다 — 따옴표·줄표 표와 생략 표시만 가져다 쓴다.
설계: docs/superpowers/specs/2026-11-27-central-bank-events.md
"""
import html as _html
import re
import unicodedata

from us.fed_events import _QUOTE_MAP

_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'\s+')
# 생략 표시. NFKC 가 「…」 를 「...」 로 바꾸므로 정규화 뒤의 꼴로 나눈다. 2026-11-27 실측: 한은 결정문·모두발언·
# 자막·의사록, 일본은행 공표문·전망·회견·주요 의견·의사요지 어디에도 「…」「...」「‥」 가 없다 — 원문 자체의
# 말줄임과 겹치지 않는다.
_ELLIPSIS = re.compile(r'\[\.\.\.\]|\.\.\.|‥')
# 조각 앞뒤에서 떼어 내는 문장부호(공백은 이미 없다).
_EDGE = ',.;:-"\'、。·'

QUOTE_MIN = 20       # 인용 전체(공백 제거 뒤 글자 수)
SEGMENT_MIN = 12     # 생략 표시로 나눈 조각 하나
MAX_ELISIONS = 2
# 조각 사이 허용 거리(공백 제거 뒤 글자 수) — 「한 사람의 한 답변」 길이 90분위에서 올려 잡았다(2026-11-27 실측):
#   한국어: 11/26 총재 기자간담회 자막, 총재 발언 9개(모두발언 포함) p50 1,150 · p90 2,401 · p95 2,508 · 최대 2,614
#   일본어: 10/30 총재 정례 회견 기록(11/02 공개 PDF), 답변 28개 p50 360 · p90 816 · p95 1,317 · 최대 2,269
# 한 답변 안의 생략은 통과하고, 서로 다른 질문에 대한 답을 잇는 것은 막는다. 미국은 2,000(영어 p90 1,799).
SEGMENT_GAP_MAX = {'ko': 2500, 'ja': 900}
# 생략 표시가 지운 부분의 하한. 한국어·일본어 부정은 짧은 꼬리(「…하지 않고」 의 「않고」, 「上昇しない」 의 「ない」)라
# 앞뒤 조각을 둘 다 길게 남긴 채 부정어만 지울 수 있다 — 미국 칸의 조각 하한(짧은 조각 금지)으로는 안 잡힌다.
# 문장 일부를 덜어 내는 정상적인 생략은 한 구절(8자 이상)을 지운다.
ELIDED_MIN = 8


def normalize_cjk(text):
    """대조용 표준형 — 태그 제거 → 엔티티 해제 → NFKC → 따옴표·줄표 통일 → **모든 공백 제거**."""
    t = _html.unescape(_TAG.sub('', text or ''))
    t = unicodedata.normalize('NFKC', t)
    for a, b in _QUOTE_MAP.items():
        t = t.replace(a, b)
    return _WS.sub('', t)


def quote_fragments(quote):
    """생략 표시로 나눈 **모든** 조각. 짧다고 버리지 않는다 — 부정어만 생략 표시 뒤로 숨기면 남는 조각은
    원문 그대로라 대조를 통과하고 지면에는 정반대 뜻이 남는다(미국 칸 2026-09-02 codex 실증, 같은 규칙)."""
    return [f for f in (s.strip(_EDGE) for s in _ELLIPSIS.split(normalize_cjk(quote))) if f]


def verify_quote(quote, corpus, lang):
    """인용이 원문과 어긋나는 지점을 설명하는 문장. 어긋남이 없으면 None. `lang` = 'ko' | 'ja'."""
    gap_max = SEGMENT_GAP_MAX[lang]
    frags = quote_fragments(quote)
    if not frags:
        return '인용에 대조할 내용이 없다'
    if len(frags) - 1 > MAX_ELISIONS:
        return (f'생략이 {len(frags) - 1}번이다 — {MAX_ELISIONS}번까지만 쓴다. '
                '토막을 이어 붙인 인용은 원문에 없는 문장이 된다')
    for f in frags:
        if len(f) < SEGMENT_MIN:
            return (f'대조하기에 너무 짧은 조각 — 「{f[:40]}」({len(f)}자). '
                    f'{SEGMENT_MIN}자 미만 조각은 생략 표시로 감싸 넘길 수 없다')
    norm = normalize_cjk(corpus)
    at = None
    for f in frags:
        i = norm.find(f) if at is None else norm.find(f, at)
        if i < 0:
            if f in norm:
                return f'원문에는 있지만 인용이 원문 순서를 뒤집었다 — 「{f[:40]}」'
            return f'원문에 없는 조각 — 「{f[:40]}」'
        if at is not None and i - at < ELIDED_MIN:
            return (f'생략 표시가 원문 {i - at}자만 지웠다 — 「{f[:40]}」 앞. 부정어 같은 짧은 말을 생략 표시로 지우면 '
                    f'뜻이 뒤집힌다. 생략은 {ELIDED_MIN}자 이상의 구절에만 쓴다')
        if at is not None and i - at > gap_max:
            return (f'앞 조각에서 {i - at:,}자 떨어진 조각 — 「{f[:40]}」. {gap_max:,}자 넘게 떨어진 발언을 '
                    '이으면 따로 한 말이 한 문장이 된다')
        at = i + len(f)
    return None


# ── 한국어 원문의 수치(KR 칸) ────────────────────────────────────────────────────
# 원문이 «단위를 달고» 적은 값만. 단위 목록은 11/26 결정문·모두발언·자막·10/22 의사록에서 실제로 나온 것
# (2026-11-27 실측: % 120여 회, %p, bp, 조, 억, 명, 배) + 같은 뜻의 표기(퍼센트·포인트·베이시스포인트·원·달러).
_KO_UNIT = r'(?:%p|%포인트|%|bp|퍼센트포인트|퍼센트|베이시스포인트|포인트|조|억|만|명|배|원|달러)'
_KO_NUM = r'(\d[\d,]*(?:\.\d+)?)'
_KO_VALUE = re.compile(_KO_NUM + r'\s*' + _KO_UNIT)
# 「2∼3%」·「2~3%」 — 범위의 앞 끝에는 단위가 없다
_KO_RANGE = re.compile(_KO_NUM + r'\s*[∼~〜-]\s*' + _KO_NUM + r'\s*' + _KO_UNIT)


def source_numbers(text):
    """원문이 단위를 달고 적은 수치(반올림 꼴 포함). KR 칸이 인용해도 되는 값에 더한다."""
    t = unicodedata.normalize('NFKC', _html.unescape(text or ''))
    out = set()

    def add(raw):
        try:
            v = float(raw.replace(',', ''))
        except ValueError:
            return
        out.add(round(v, 4))
        for d in (1, 2, 3):
            out.add(round(v, d))

    for m in _KO_VALUE.finditer(t):
        add(m.group(1))
    for m in _KO_RANGE.finditer(t):
        add(m.group(1))
        add(m.group(2))
    return out


def ja_source_text(text):
    """일본어 원문을 일본 일간 숫자 검사(`japan.gate._text_figures`)에 넣을 꼴로 — 兆·億 을 조·억 으로 바꿔
    번역문(「2조 4,600억 엔」·「8,600억 엔」)과 같은 정규화(`_jo_eok`)를 타게 한다."""
    t = unicodedata.normalize('NFKC', text or '')
    return t.replace('兆', '조').replace('億', '억')
