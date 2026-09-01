"""발행본에서 수치를 뜯어내고, 데이터가 허용하는 수치 집합을 만드는 공용 함수.

채권 게이트가 2026-08-31 codex 검토에서 뚫린 뒤 다듬은 규칙이 여기 있다. 같은
규칙을 두 번 적어 두면 한쪽만 고쳐지고, 그 순간 뚫린 쪽이 어디인지 아무도 모른다.
`common/discipline.py` 를 뽑을 때와 같은 기준 — **자산 스펙과 무관하게 진짜로
동일한 순수 함수만** 공유한다.
"""

import re

# 속성값 안의 `>` 를 태그 끝으로 읽으면 마크업 조각이 본문 텍스트로 새고, 숫자를
# 쪼개는 태그가 검사에서 사라진다(2026-09-01 codex 11차). 따옴표를 인식한다.
# 주석도 마찬가지다 — `<!-- > -->` 의 `>` 에서 끊기면 `-->` 가 본문으로 샌다(12차).
# 종료 표기는 `-->` 와 `--!>` 둘 다 브라우저가 받아들인다(13차).
TAG_TOKEN = r'''<!--.*?--!?>|<(?:"[^"]*"|'[^']*'|[^>"'])*>'''
TAG_RE = re.compile(TAG_TOKEN, re.S)

# 숫자 사이에 낀 태그·주석은 텍스트를 뽑을 때 공백이 되어 한 수치를 둘로 쪼갠다.
# 「4.<span>47</span>bp」는 화면에 4.47bp 로 보이는데 검사에는 4 와 47bp 로 들어간다.
# **공백을 허용하지 않는다.** 「-0.093</span>, 인플레축」이나 「…4</strong> 5월」처럼
# 태그 뒤에 구두점·공백이 오는 정상 문장을 잡으면 발행본 8편이 매일 걸린다(실측).
# 쪼개진 수치는 붙어 있다 — 그것이 화면에 한 숫자로 보이는 조건이기도 하다.
_TAG_RUN = re.compile(r'\d[.,]?((?:' + TAG_TOKEN + r')+)\d', re.S)
_TAG_NAME = re.compile(r'<\s*(/?)\s*([a-zA-Z][\w-]*)')
_BLOCK_NAMES = frozenset(
    'td th tr p div li ul ol dl dt dd table thead tbody tfoot section article '
    'caption figure figcaption blockquote h1 h2 h3 h4 h5 h6'.split())


def _is_structural(run):
    """이 태그 연속이 «칸·문단을 실제로 끝내는 경계»인가.

    이름만 보면 안 된다 — `<div hidden></div>` 는 블록 태그를 갖고 있지만 아무것도
    끝내지 않고, 숨겨져 있어 사람 눈에도 안 보인다. 진짜 경계는 **연속 안에서
    열리지 않은 블록을 닫는 것**이다: `</td><td>` 의 `</td>` 는 숫자가 들어 있던
    칸을 닫지만, 스스로 열고 닫은 `<div></div>` 는 아무것도 안 닫는다.
    """
    opened = []
    for closing, name in _TAG_NAME.findall(run):
        name = name.lower()
        if not closing:
            opened.append(name)
        elif name in opened:
            opened.remove(name)
        elif name in _BLOCK_NAMES:
            return True
    return False


# 눈에 보이지 않는 문자도 같은 일을 한다 — 「2&#x200B;47bp」는 화면에 247bp 로 보이는데
# 검사에는 47bp 만 들어간다(2026-09-01 codex 검토). 실체 참조는 태그를 지워도 남으므로
# 원문에서 함께 본다.
_HIDDEN_RUN = re.compile(
    r'\d[.,]?((?:&[#a-zA-Z0-9]{1,10};|[\u200b-\u200f\u2060\ufeff\u00ad])+)\d')


def numbers_split_by_tags(html_fragment):
    """수치 사이에 낀 태그·주석·보이지 않는 문자. 비어 있지 않으면 발행을 막는다."""
    html_fragment = html_fragment or ''
    out = [m.group(1) for m in _TAG_RUN.finditer(html_fragment)
           if not _is_structural(m.group(1))]
    out += [m.group(1) for m in _HIDDEN_RUN.finditer(html_fragment)]
    return out

MEASURE_RE = re.compile(
    r'(-?\d[\d,]*(?:\.\d+)?)\s*(?:bp|%p|%|십억|배)'        # 단위를 단 수치
    r'|(-?\d[\d,]*\.\d{2,})'                              # 소수 2자리 이상
    r'|(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?)')                 # 천 단위 구분자


def text_of(html):
    """본문 + 메타 설명 + 제목.

    메타를 빼면 SEO 설명에 실린 수치 주장이 검사를 통째로 피해 간다 — 태그를
    지우면 content="..." 속 문장도 같이 사라지기 때문이다.
    """
    t = re.sub(r'<style.*?</style>', ' ', html, flags=re.S)
    t = re.sub(r'<script.*?</script>', ' ', t, flags=re.S)
    metas = ' '.join(re.findall(r'<meta[^>]+content="([^"]*)"', t))
    titles = ' '.join(re.findall(r'<title>(.*?)</title>', t, re.S))
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', t) + ' ' + metas + ' ' + titles)


COMMENT_RE = re.compile(r'<!--.*?--!?>', re.S)


def strip_comments(html):
    """주석을 통째로 지운다. 주석 안의 표식이 살아 있으면 그것으로 구역을 위조한다."""
    return COMMENT_RE.sub(' ', html or '')


def text_dense(html):
    """태그를 **공백 없이** 지운 텍스트.

    `text_of` 는 태그를 공백으로 바꾼다. 그래서 「변<span></span>동성」은 화면에
    「변동성」으로 보이는데 검사 문자열은 「변 동성」이 되어 금지어와 안 맞는다
    (2026-09-02 codex 검토). 어휘 검사는 두 판을 모두 본다.
    """
    t = re.sub(r'<style.*?</style>', ' ', html or '', flags=re.S)
    t = re.sub(r'<script.*?</script>', ' ', t, flags=re.S)
    return TAG_RE.sub('', t)


def measure_numbers(text):
    """비교 가능한 수치 토큰.

    하이픈을 음수 부호로 잘못 읽는 사고가 두 종류 있다. 하나는 날짜
    (「2026-08-27」에서 -27 을 뜯어내는 것, 주간 게이트가 2026-08-30 에 겪은 실패)이고,
    다른 하나는 만기 구간 표기(「5년-30년」에서 -30 을 뜯어내는 것)다.
    그래서 날짜를 먼저 가리고, **앞에 공백이나 여는 괄호가 오지 않는 하이픈은
    부호가 아니라 이음표**로 처리한다.

    **단위를 단 수치만 검사한다.** 예전에는 모든 숫자를 뜯어냈고, 그러면 산문의
    「세 가지」·「3개월물」까지 걸리므로 0~100 정수를 통째로 면제해야 했다. 그 면제가
    게이트를 갉아먹었다 — 지어낸 bp 값이 0~100 범위면 무조건 통과했다. 검사 대상을
    좁히는 쪽이 면제를 넓히는 쪽보다 낫다.
    """
    masked = re.sub(r'\d{4}-\d{2}-\d{2}', ' ', text)
    masked = re.sub(r'\d{4}년|\d{1,2}월|\d{1,2}일', ' ', masked)
    masked = re.sub(r'(?<=[^\s(\[])-', ' ', masked)

    out = set()
    for m in MEASURE_RE.finditer(masked):
        raw = next(g for g in m.groups() if g)
        try:
            out.add(round(float(raw.replace(',', '')), 4))
        except ValueError:
            continue
    return out


def numeric_tokens(*blobs):
    """발행본이 인용해도 되는 수치의 전체 집합.

    **단위 변환은 허용하지 않는다.** 예전에는 ×100(% -> bp)과 ÷10억(USD -> 십억)과
    절댓값을 전부 허용했는데, 그러면 무관한 값이 남의 단위로 세탁된다 — 10년물 4.67 이
    ×100 되어 「하이일드 스프레드 467bp」라는 거짓 문장을 통과시켰다(2026-08-31 codex
    검토에서 실증). 발행본이 인쇄하는 단위는 데이터가 그 단위로 직접 내려보낸다.
    여기서는 **같은 값을 다른 자릿수로 인쇄하는 것**만 허용한다.

    정수 반올림(0자리)은 넣지 않는다. 달러지수 99.16 이 99 가 되어 「금리차 99bp」를
    통과시킨다. 발행본이 정수로 인쇄해야 하는 값은 데이터가 그 자릿수로 내려보낸다.
    """
    out = set()

    def add(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            f = float(v)
            out.add(round(f, 4))
            for d in (1, 2, 3):
                out.add(round(f, d))
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                add(x)

    for blob in blobs:
        add(blob)
    return out
