"""기계 검사(차단) — 단위 하나(`check_unit`)와 조립된 문서 전체(`check_doc`).

단위 검사 코드:
- placeholder 자리표시 다중집합과 짝·중첩(부모 관계)이 원문과 같다. 형제 순서는 바뀌어도 된다.
- hangul      일본어에 한글이 한 자라도 있다.
- number      아라비아 숫자 토큰 다중집합(NFKC, 쉼표 제거)이 다르다. 한글 수사(하루·한·두)는
              숫자가 아니다 — 일본어가 `1日` 로 쓰면 불일치(지시문이 한자 수사를 쓰게 한다).
              **부호는 보지 않는다**(`-0.51` 과 `0.51`, 일본식 `▲0.51` 이 같은 토큰) — 부호는 soft `sign` 이 본다.
- currency    숫자(조·억·만 포함)에 붙은 통화 단위(원·₩↔ウォン, 엔·¥↔円, 달러·$↔ドル, 유로·€↔ユーロ,
              위안↔元, 파운드·£↔ポンド)가 맞다 — 통화별 개수가 같고, 양쪽에 한 번씩 나오는 같은 숫자에는
              같은 통화가 붙는다. 「달러 강세」처럼 숫자에 붙지 않은 낱말·「엔/달러」 같은 통화쌍은 세지 않는다.
              범위에서 단위를 되풀이한 번역(`5500万ドル〜8000万ドル`)은 걸린다 — 재번역 힌트가 원문 꼴로 돌린다.
- latin       원문의 대문자 토큰(2자 이상)·`LATIN_MAP` 키가 일본어에 그대로 있거나 대응 표기가 있다. 토큰의
              양 끝 너머에 같은 종류의 ASCII 글자(라틴이면 라틴, 숫자면 숫자)가 이어지면 없는 것으로 본다
              (`USD` 가 `USDT` 안에 있어도 「있다」가 아니다). `S&P 500` → `S&P500` 은 그대로 있다.
- empty / length(원문 20자 이상일 때 길이 비 0.3-3.0) / kana(원문 40자 이상이고 한글이 20자 이상이면
              가나 필수 — 한글이 적은 출처·일정 줄은 가나 없는 한자 번역이 정상이다)
- order(soft) 숫자 토큰의 순서가 다르다 — 차단하지 않고 검토에 표시.
- sign(soft)  숫자마다 앞의 부호가 다르다. 원문 `- + −`, 일본어 `- + − ▲ マイナス プラス`. 부호 앞 글자가
              영숫자면 부호가 아니다(날짜 `2026-11-13`, 범위 `1.2-1.5`). 숫자 다중집합이 같을 때만 본다.
              「+2.08%」→「2.08%高」처럼 말로 옮긴 것도 걸린다 — 방향은 검토가 판정한다.

`direction(ko, ja)` 는 단위 검사가 아니라 검토자에게 가는 표시다(`pipeline._flags`): 오름·내림 낱말이 한쪽에만
있다. 「3.2% 상승」→「3.2%下落」은 숫자·부호가 같아 위 검사로는 못 잡는다.

문서 검사는 엔티티(`&#54620;`)를 풀어서도 한글 0, JSON-LD 는 파싱해 문자열(키 포함)에서 한글 0 — 파싱 실패도
문제(`jsonld`)다.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .glossary import LATIN_MAP

HANGUL = re.compile(r"[가-힣]")
KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
PH = re.compile(r"⟦(/?)([a-z]+)(/?)⟧")
NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
CAPS = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9&.\-]+")

KANA_MIN_HANGUL = 20

LANG_TEXT = "한국어"
_LANG_RE = re.compile(r'<a class="ja-lang" href="[^"<>]*" hreflang="ko" lang="ko">한국어</a>')


def lang_button(ko_url: str) -> str:
    """일본어 글 머리의 언어 버튼 — 문서 검사가 허용하는 한글은 이 꼴 하나뿐이다."""
    import html
    return f'<a class="ja-lang" href="{html.escape(ko_url, quote=True)}" hreflang="ko" lang="ko">{LANG_TEXT}</a>'


ALLOW = (_LANG_RE,)


@dataclass(frozen=True)
class Problem:
    code: str
    detail: str
    soft: bool = False


def _nfkc(s):
    return unicodedata.normalize("NFKC", s)


def _strip_ph(s):
    return PH.sub(" ", s)


def numbers(s: str) -> list:
    return [m.group(0).replace(",", "") for m in NUM.finditer(_nfkc(_strip_ph(s)))]


_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")
_KO_SIGNS = {"-": "-", "−": "-", "+": "+"}
_JA_SIGNS = {"-": "-", "−": "-", "▲": "-", "マイナス": "-", "+": "+", "プラス": "+"}


def signed_numbers(s: str, signs=None) -> list:
    """(숫자, 부호 '+'/'-'/'') 목록. `signs` 는 부호 표기 → 부호(기본: 원문 쪽).
    기호 부호는 숫자에 붙어 있어야 하고 그 앞 글자가 ASCII 영숫자가 아니어야 한다.
    낱말 부호(マイナス·プラス)는 사이 공백을 건너뛴다."""
    signs = _KO_SIGNS if signs is None else signs
    marks = sorted(signs, key=len, reverse=True)
    t = _nfkc(_strip_ph(s))
    out = []
    for m in NUM.finditer(t):
        head = t[:m.start()]
        sign = ""
        for mark in marks:
            h = head.rstrip(" \u00a0") if len(mark) > 1 else head
            if h.endswith(mark):
                if len(mark) > 1 or not _ASCII_ALNUM.fullmatch(h[:-1][-1:] or "_"):
                    sign = signs[mark]
                break
        out.append((m.group(0).replace(",", ""), sign))
    return out


def _ph_structure(s):
    """(다중집합, 부모 관계, 오류). 부모 = 그 자리표시를 감싸는 쌍의 글자."""
    seq = [m.group(0) for m in PH.finditer(s)]
    stack, parent, errs = [], {}, []
    for tok in seq:
        m = PH.fullmatch(tok)
        close, name, void = m.group(1), m.group(2), m.group(3)
        if void:
            parent.setdefault(tok, []).append(stack[-1] if stack else None)
        elif not close:
            parent.setdefault(tok, []).append(stack[-1] if stack else None)
            stack.append(name)
        else:
            if not stack or stack[-1] != name:
                errs.append(f"짝이 맞지 않는 {tok}")
                if name in stack:
                    del stack[stack.index(name):]
            else:
                stack.pop()
    if stack:
        errs.append(f"닫히지 않은 자리표시 {stack}")
    return Counter(seq), {k: sorted(v, key=str) for k, v in parent.items()}, errs


# ── 통화 ──────────────────────────────────────────────────────────────────
# 쉼표로 끝나지 않는다 — 「101.995, 유로/달러는」의 `995,` 를 금액으로 읽지 않게.
_AMOUNT = r"(?<![\d.,])(\d(?:[\d,]*\d)?(?:\.\d+)?)"
_KO_CUR = re.compile(_AMOUNT + r"((?:\s*[십백천만억조])*)\s*"
                     r"(원(?!칙)|엔(?!비디아|진)|(?:미국|호주|홍콩|캐나다|싱가포르|대만|뉴질랜드)?\s*달러(?!지수)|유로|위안|파운드)"
                     r"(?!\s*/)")   # 「엔/달러」 같은 통화쌍 표기는 단위가 아니다
_JA_CUR = re.compile(_AMOUNT + r"((?:\s*[十百千万億兆])*)\s*"
                     r"(ウォン|円|(?:米|豪|香港|カナダ|シンガポール|台湾|NZ)?ドル(?!指数)|ユーロ|(?:人民)?元|ポンド)(?!\s*/)")
_SYM_CUR = re.compile(r"([$₩¥€£])\s*" + _AMOUNT)
_CUR_OF = {"원": "KRW", "₩": "KRW", "ウォン": "KRW", "엔": "JPY", "¥": "JPY", "円": "JPY",
           "달러": "USD", "$": "USD", "ドル": "USD", "유로": "EUR", "€": "EUR", "ユーロ": "EUR",
           "위안": "CNY", "元": "CNY", "파운드": "GBP", "£": "GBP", "ポンド": "GBP"}
# 달러는 종류가 다르면 다른 통화다(「5호주달러 → 5米ドル」). 미국·米 는 그냥 달러와 같다.
_DOLLAR_OF = {"호주": "AUD", "豪": "AUD", "홍콩": "HKD", "香港": "HKD", "캐나다": "CAD", "カナダ": "CAD",
              "싱가포르": "SGD", "シンガポール": "SGD", "대만": "TWD", "台湾": "TWD", "뉴질랜드": "NZD", "NZ": "NZD"}
# 규모 단위는 글자만 다르고 자리가 같다 — 「1억 달러 → 1万ドル」은 숫자가 같아도 다른 금액이다.
_SCALE_OF = {"십": "十", "백": "百", "천": "千", "만": "万", "억": "億", "조": "兆"}


def _cur_name(word):
    w = word.replace(" ", "")
    for k, v in _DOLLAR_OF.items():
        if w.startswith(k):
            return v
    for k, v in _CUR_OF.items():
        if w.endswith(k):
            return v
    return word


def _scale(s):
    return "".join(_SCALE_OF.get(ch, ch) for ch in s if not ch.isspace())


def _amounts(s: str, ja: bool = False) -> list:
    """숫자에 붙은 통화 [(숫자, 통화 코드)] — 문서 순서."""
    t = _nfkc(_strip_ph(s))
    out = []
    for pat in ((_JA_CUR,) if ja else (_KO_CUR, _JA_CUR)):
        for m in pat.finditer(t):
            out.append((m.start(), m.group(1).replace(",", ""), _cur_name(m.group(3))))
    for m in _SYM_CUR.finditer(t):
        out.append((m.start(), m.group(2).replace(",", ""), _cur_name(m.group(1))))
    return [(n, c) for _i, n, c in sorted(out)]


def currencies(s: str, ja: bool = False) -> list:
    """숫자에 붙은 통화 [(숫자, 통화 코드)] — 문서 순서. 원문 쪽은 일본어 단위도 센다 — 원제로 되돌린
    뉴스 머리(`news.localize`)는 원문 단위 안에 일본어가 있다."""
    return _amounts(s, ja)


def _currency_problem(ko, ja):
    a, b = _amounts(ko), _amounts(ja, ja=True)
    sa, sb = Counter(c for _n, c in a), Counter(c for _n, c in b)
    if sa != sb:
        return f"통화 {dict(sa)} → {dict(sb)}"
    na, nb = Counter(n for n, _c in a), Counter(n for n, _c in b)
    for n, c in a:
        if na[n] == 1 and nb[n] == 1:
            c2 = next(c2 for n2, c2 in b if n2 == n)
            if c2 != c:
                return f"{n}: {c} → {c2}"
    return None


# ── 규모 ──────────────────────────────────────────────────────────────────
# 숫자 바로 뒤의 규모 글자(억·만·조…)는 글자만 다르고 자리가 같다 — 「1억 → 1万」은 숫자가 같아도 다른 값이다.
# 통화가 붙었든 아니든(「3만 명」) 모든 숫자에서 본다.
_KO_SCALE = re.compile(r"[십백천만억조]+")
_JA_SCALE = re.compile(r"[十百千万億兆]+")
# 원문 쪽에서 뒤 글자가 규모가 아닌 숫자(2026-11-25 실제 보류 3편):
# · 이름에 붙은 숫자 — 「러셀2000만」(만 = 조사), 「FTSE100만」, 「제1조」. 숫자 바로 앞이 규모 글자가 아닌 한글·라틴이다
#   (「1조5100억」「3억8000만」처럼 앞이 규모 글자면 규모다).
# · 법 조항 — 「무역법 301조」(조 = 조항).
_KO_NAMED = re.compile(r"[A-Za-z&가-힣](?<![십백천만억조])$")
_KO_ARTICLE = re.compile(r"법\s?$")


def scaled_numbers(s: str, ja: bool = False) -> list:
    """[(숫자, 규모)] — 문서 순서. 숫자는 `numbers()` 와 **같은 토큰**(`NUM`)이다 — 따로 읽으면 한쪽 검사만
    보는 숫자가 생긴다. 규모는 일본어 글자로 맞춘다. 원문 쪽은 일본어 규모도 읽는다(원제 머리)."""
    t = _nfkc(_strip_ph(s))
    out = []
    for m in NUM.finditer(t):
        sc = (_JA_SCALE if ja else _KO_SCALE).match(t, m.end())
        if sc is None and not ja:
            sc = _JA_SCALE.match(t, m.end())
        if sc is not None and not ja:
            head = t[max(0, m.start() - 3):m.start()]
            if _KO_NAMED.search(head) or (sc.group(0) == "조" and _KO_ARTICLE.search(head)):
                sc = None
        out.append((m.group(0).replace(",", ""), _scale(sc.group(0)) if sc else ""))
    return out


def _scale_problem(ko, ja):
    """(hard 문제, soft 문제). 같은 숫자의 규모 다중집합이 다르면 hard, 순서만 다르면 soft(검토자에게)."""
    a, b = scaled_numbers(ko), scaled_numbers(ja, ja=True)
    if Counter(n for n, _s in a) != Counter(n for n, _s in b):
        return None, None                      # 숫자 자체가 다르다 — 같은 토큰이라 number 문제가 이미 말했다
    if Counter(a) != Counter(b):
        miss = sorted((Counter(a) - Counter(b)).elements())
        extra = sorted((Counter(b) - Counter(a)).elements())
        return f"규모 {miss} → {extra}", None
    # 같은 숫자가 서로 다른 규모로 두 번 이상 나오면(「1억 … 1만」) 어느 것이 어느 것인지는 순서로만 가린다 —
    # 그 숫자의 규모 순서가 바뀌었으면 맞바뀐 것일 수 있어 막는다. 드문 꼴이라 어순 때문에 걸려도 다시 번역하면 된다.
    for n in dict.fromkeys(n for n, _s in a):
        sa, sb = [s for m, s in a if m == n], [s for m, s in b if m == n]
        if len(set(sa)) > 1 and sa != sb:
            return f"{n} 의 규모 순서 {sa} → {sb}", None
    if a != b and any(s for _n, s in a):
        return None, f"규모 붙은 숫자의 순서 {a} → {b}"
    return None, None


# ── 방향(검토 표시) ─────────────────────────────────────────────────────────
# 값의 오르내림 낱말만 — 늘다·줄다·인상 같은 말까지 넣으면 2026-11-13 실제 번역 722쌍에서 표시가 1할을 넘었다.
_KO_UP = re.compile(r"상승|올랐|올라|오른|오르|반등|급등")
_KO_DOWN = re.compile(r"하락|내렸|내려|내린|내리|떨어|급락")
_JA_UP = re.compile(r"上昇|反発|急騰|続伸|値上がり|[%幅面]高|(?<!引き)(?<!押し)(?<!切り)(?<!繰り)(?<!利)上げ")
_JA_DOWN = re.compile(r"下落|低下|反落|急落|続落|値下がり|[%幅面]安|(?<!引き)(?<!押し)(?<!切り)(?<!利)下げ")


def direction(ko: str, ja):
    """오름·내림 낱말이 한쪽에만 있으면 Problem(soft), 아니면 None."""
    if not ja:
        return None
    k = (bool(_KO_UP.search(ko)), bool(_KO_DOWN.search(ko)))
    j = (bool(_JA_UP.search(ja)), bool(_JA_DOWN.search(ja)))
    if k == j:
        return None
    names = lambda x: "·".join(n for n, on in zip(("오름", "내림"), x) if on) or "없음"
    return Problem("direction", f"방향 낱말 원문 {names(k)} → 일본어 {names(j)}", soft=True)


def _has_token(t, text):
    """토큰 양 끝 너머에 같은 종류의 ASCII 글자가 붙어 있지 않은 출현이 있는가."""
    pre = r"(?<![A-Za-z])" if t[:1].isalpha() and t[:1].isascii() else \
        r"(?<![0-9])" if t[:1].isdigit() else ""
    post = r"(?![A-Za-z])" if t[-1:].isalpha() and t[-1:].isascii() else \
        r"(?![0-9])" if t[-1:].isdigit() else ""
    return re.search(pre + re.escape(t) + post, text) is not None


_WORD_TAIL = re.compile(r"[A-Za-z0-9]*")


def _latin_tokens(ko):
    text = _strip_ph(ko)
    # 대문자 머리 뒤에 소문자가 이어지면(FXEmpire) 낱말 전체가 토큰이다 — 경계 검사가 머리만 보고 막지 않게.
    toks = [(m.group(0) + (_WORD_TAIL.match(text, m.end()).group(0) if m.group(0)[-1].isalnum() else ""))
            .rstrip(".-&") for m in CAPS.finditer(text)]
    toks = [t for t in toks if len(t) >= 2]
    for k in LATIN_MAP:
        if not CAPS.fullmatch(k) and re.search(r"(?<![A-Za-z])" + re.escape(k) + r"(?![A-Za-z])", text):
            toks.append(k)
    return toks


def check_unit(ko: str, ja) -> list:
    out = []
    if ja is None or not str(ja).strip():
        return [Problem("empty", "번역이 비었다")]
    ja = str(ja)
    # placeholder
    a, pa, ea = _ph_structure(ko)
    b, pb, eb = _ph_structure(ja)
    if a != b:
        out.append(Problem("placeholder", f"자리표시 다중집합 {dict(a)} ≠ {dict(b)}"))
    elif eb or pa != pb:
        out.append(Problem("placeholder", "; ".join(eb) or "자리표시 중첩이 바뀌었다"))
    # hangul
    left = HANGUL.findall(ja)
    if left:
        out.append(Problem("hangul", f"한글 {len(left)}자: {''.join(left[:10])}"))
    # number
    na, nb = numbers(ko), numbers(ja)
    if Counter(na) != Counter(nb):
        miss = list((Counter(na) - Counter(nb)).elements())
        extra = list((Counter(nb) - Counter(na)).elements())
        out.append(Problem("number", f"빠짐 {miss} 더함 {extra}"))
    else:
        if na != nb:
            out.append(Problem("order", f"숫자 순서 {na} → {nb}", soft=True))
        sa, sb = signed_numbers(ko), signed_numbers(ja, _JA_SIGNS)
        # 순서가 같으면 자리마다, 다르면 다중집합으로 맞춘다(엇갈린 부호도 잡는다).
        bad = ([(a, b) for a, b in zip(sa, sb) if a != b] if na == nb else
               [] if Counter(sa) == Counter(sb) else [(sorted((Counter(sa) - Counter(sb)).elements()),
                                                       sorted((Counter(sb) - Counter(sa)).elements()))])
        if bad:
            out.append(Problem("sign", f"부호가 다르다(원문 → 일본어): {bad}", soft=True))
    # currency
    cur = _currency_problem(ko, ja)
    if cur:
        out.append(Problem("currency", cur))
    hard, soft = _scale_problem(ko, ja)
    if hard:
        out.append(Problem("scale", hard))
    elif soft:
        out.append(Problem("order", soft, soft=True))
    # latin
    jn = _nfkc(ja)
    lost = []
    for t in _latin_tokens(ko):
        if _has_token(t, jn):
            continue
        if any(_has_token(alt, jn) for alt in LATIN_MAP.get(t, ())):
            continue
        lost.append(t)
    if lost:
        out.append(Problem("latin", f"라틴 토큰이 없다: {sorted(set(lost))}"))
    # length / kana — 자리표시를 뺀 글자 수
    ka, kb = _strip_ph(ko).strip(), _strip_ph(ja).strip()
    if len(ka) >= 20:
        r = len(kb) / len(ka)
        if not 0.3 <= r <= 3.0:
            out.append(Problem("length", f"길이 비 {r:.2f} ({len(ka)}→{len(kb)})"))
    if len(ka) >= 40 and len(HANGUL.findall(ka)) >= KANA_MIN_HANGUL and not KANA.search(ja):
        out.append(Problem("kana", "가나가 없다 — 미번역·중국어 의심"))
    return out


_LD = re.compile(r"<script\b[^>]*\btype\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script\s*>", re.S | re.I)


def _json_texts(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _json_texts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _json_texts(v)


def check_doc(html_ja: str, source_html: str) -> list:
    """조립된 문서 전체: 한글 없음(ALLOW 꼴만 예외, 엔티티를 풀어서도), JSON-LD 문자열에 한글 없음,
    ⟦ 없음, <html lang="ja">, 통계 표식 1개."""
    import html as _html
    import json
    from scripts.common.analytics import MARKER

    out = []
    rest = html_ja
    for pat in ALLOW:
        rest = pat.sub("", rest)
    rest = _html.unescape(rest)
    hits = [m.start() for m in HANGUL.finditer(rest)]
    if hits:
        i = hits[0]
        out.append(Problem("hangul", f"한글 {len(hits)}자, 첫 자리: {rest[max(0, i - 40):i + 20]!r}"))
    for n, m in enumerate(_LD.finditer(html_ja)):
        try:
            obj = json.loads(m.group(1))
        except ValueError as e:
            out.append(Problem("jsonld", f"JSON-LD {n + 1}번째를 읽지 못했다: {e}"))
            continue
        left = [t for t in _json_texts(obj) if HANGUL.search(t)]
        if left:
            out.append(Problem("hangul", f"JSON-LD 문자열에 한글: {left[0][:40]!r}"))
    if "⟦" in html_ja or "⟧" in html_ja:
        out.append(Problem("placeholder", "자리표시가 남았다"))
    if not re.search(r"<html\b[^>]*\blang=\"ja\"", html_ja):
        out.append(Problem("lang", '<html lang="ja"> 가 없다'))
    if MARKER in source_html and html_ja.count(MARKER) != 1:
        out.append(Problem("marker", f"방문 통계 표식 {html_ja.count(MARKER)}개(1개여야 한다)"))
    return out
