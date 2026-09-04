"""이 판과 저 판의 차이가 «조판 도구가 한 일»뿐인가.

원장이 blob SHA 하나로만 동일성을 판단하던 탓에, `apply_readability.py` 가 조판 사양을
고칠 때마다 발행본 60여 편이 통째로 큐에 다시 올랐다(2026-08-24·26·28 세 차례, 실측
51건). `.claude/REVIEW_GATE.md` §2 는 codex 검토에서 「레이아웃·HTML·CSS는 보지 마」라고
지시하므로 그 51건은 **정의상 지적을 만들 수 없다.**

**방향이 이 모듈의 전부다.** 초안은 두 판을 각각 손실 정규화해 해시를 맞댔는데, 그 방식은
2026-09-04 codex 검토에서 두 번 뚫렸다 — 마커 뒤에 `html, body { display:none !important; }`
를 넣어도 지문이 같았고(지우는 규칙은 무엇이 지워지는지를 보지 않는다), 서로 다른 CSS 가 같은
정준형으로 합쳐졌다. 그래서 뒤집었다.

**사람이 이미 읽은 판을 조판 변환으로 밀어, 새 판이 바이트 그대로 나오는지만 본다.**
통과하는 새 판은 **단 하나**다 — 옛 판과 블록으로 완전히 결정되므로 그 사이에 무엇도 끼워
넣을 수 없다. 새 판은 어디서도 정규화하지 않는다.

블록은 아무거나 받지 않는다. `known_blocks` 에 등록된 것만 조판으로 인정한다.

설계: /Users/daeyoung/Desktop/AI/report/plan.md
"""

import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review.known_blocks import is_known  # noqa: E402
from us.readability import _blank_inert as blank_inert  # noqa: E402
from us.readability import _head_style_spans as head_style_spans  # noqa: E402
from us.readability import (block_labels, demote_card_p_font,  # noqa: E402
                            unpin_inline_labels)

_MARKER = re.compile(r'/\*\s*readability-v\d+\s*\*/', re.I)

# **감추는** 선언. 값까지 본다 — `display:inline-block` 은 라벨을 옆에 세울 뿐이고 실제로
# 발행본 CSS 에 흔하다(오탐 19편, 2026-09-04 실측). 문단을 사라지게 하는 것만 센다.
# 감추는 방법을 전부 열거할 수는 없다. 이것은 보안 경계가 아니라 사고 방지용 가드다.
_HIDING = re.compile(
    r'(?:^|[;{])\s*(?:'
    r'display\s*:\s*(?:none|var\()'
    r'|visibility\s*:\s*(?:hidden|collapse|inherit|var\()'
    r'|opacity\s*:\s*(?:0(?:\.0+)?\s*(?:;|$|!)|0\s*%|calc\(|var\()'
    r'|font-size\s*:\s*0'
    r'|content\s*:\s*none'
    r'|(?:max-)?height\s*:\s*0'
    r'|width\s*:\s*0'
    r'|text-indent\s*:\s*-'
    r'|clip(?:-path)?\s*:'
    r'|transform\s*:\s*scale\(\s*0'
    r'|(?:left|top)\s*:\s*-\s*\d{3}'
    r')', re.I)
# 특정도가 내려가는 것만으로 문제가 되는 선언들(값은 무엇이든).
_VISIBILITY = re.compile(
    r'(?i)(?:^|[;{])\s*(display|visibility|opacity|content|position)\s*:')
_FONT_SIZE = re.compile(r'(?i)(?:^|[;{])\s*font-size\s*:')
_LABEL_SEL = re.compile(r'(?i)(?:box|p)-label')
_RULE = re.compile(r'([^{}]*)\{([^{}]*)\}')

# 주석과 문자열은 **규칙을 자르기 전에** 덮어야 한다. 나중에 지우면
# `.p-label{/*{*/display:none/*}*/}` 처럼 주석 안에 중괄호를 넣어 선택자와 선언을 갈라
# 놓을 수 있고, 그러면 가장 기본적인 `display:none` 이 검사를 통과한다(2026-09-04 codex
# 검토가 재현). 길이를 보존해 덮으므로 여기서 얻은 오프셋은 원본에 그대로 쓸 수 있다.
_CSS_INERT = re.compile(r'/\*.*?\*/' r'|"(?:[^"\\]|\\.)*"' r"|'(?:[^'\\]|\\.)*'", re.S)
# CSS 이스케이프와 네이티브 중첩(`&`)은 우리 CSS 에 없다. 나타나면 이 검사가 읽을 수 있는
# 문법이 아니므로 판정을 포기한다. **16진 이스케이프만 막으면 모자란다** — `.p\2d label` 은
# 잡히는데 `.p\-label` 은 빠져나갔다(2026-09-04 실측). 둘 다 `.p-label` 을 가리킨다.
# 문자열 안의 백슬래시는 `_mask_css` 가 이미 덮었으므로 여기 걸리지 않는다.
_CSS_EXOTIC = re.compile(r'\\|&')


def _mask_css(css):
    """주석·문자열 안을 공백으로 덮는다. 길이는 그대로."""
    return _CSS_INERT.sub(lambda m: ' ' * (m.end() - m.start()), css)


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    text: str


def find_block(html):
    """조판 블록의 자리. 확신이 없으면 None — 그 판은 검토로 보낸다.

    **`<style>` 를 문자열로 되짚지 않는다.** 그렇게 하면 `<stylex>` 도, 주석 안의 `<style` 도,
    스크립트 문자열 속 `<style` 도 여는 태그로 읽힌다. 그러면 이식이 엉뚱한 구간을 들어내고
    그 결과가 조판 변경으로 승인된다(2026-09-04 codex 검토가 지적). head 안 **진짜** style
    원소의 범위만 쓰는 `_head_style_spans` 는 조판 도구 자신이 마커를 찾을 때 쓰는 것과 같은
    함수다 — 게이트가 보는 자리와 도구가 고치는 자리가 같아야 한다.

    마커가 둘이면 어느 쪽이 블록인지 정할 수 없다. 블록 안에 `<` 가 있으면 CSS 가 아니다.
    """
    if len(_MARKER.findall(html)) != 1:
        return None
    at = _MARKER.search(html)
    inside = [(a, b) for a, b in head_style_spans(html) if a <= at.start() < b]
    if len(inside) != 1:
        return None
    end = inside[0][1]
    text = html[at.start():end]
    return None if '<' in text else Block(at.start(), end, text)


def _risky_css(html, block):
    """조판 변환이 «보이느냐»를 건드릴 수 있는 CSS 가 있는가.

    두 가지다. ① `demote_card_p_font` 는 `font-size` 가 든 규칙에서 `.card p` 류 선택자를
    떼어 내는데, 같은 규칙에 `display` 가 함께 있으면 그 선언의 특정도까지 내려간다 — 더 약한
    `display:none` 규칙이 이기면 문단이 사라진다. ② `block_labels` 가 붙이는 `p-label` 에
    페이지 자신의 CSS 가 반응하면(`.p-label{display:none}`), 클래스를 붙이는 것만으로 라벨이
    사라진다. 둘 다 2026-09-04 codex 검토가 지목했다.

    등록된 조판 블록 안은 보지 않는다 — 그 내용은 사람이 확인해 등록한 것이다.
    """
    for start, end in head_style_spans(html):
        css = _mask_css(html[start:end])
        if _CSS_EXOTIC.search(css):
            return True
        for rule in _RULE.finditer(css):
            if block is not None and block.start <= start + rule.start() < block.end:
                continue
            selector, declarations = rule.group(1), rule.group(2)
            # 라벨 규칙은 «감추는» 것만 위험하다. 클래스를 붙이는 순간 글이 사라진다.
            if _LABEL_SEL.search(selector) and _HIDING.search(declarations):
                return True
            # 강등 대상 규칙은 특정도가 내려가므로 값과 무관하게 위험하다.
            if (_FONT_SIZE.search(declarations) and _VISIBILITY.search(declarations)
                    and re.search(r'(?:^|[\s,])p(?:[\s,]|$)', selector)):
                return True
    return False


def _inert(html):
    """스크립트·주석 등 «코드가 아닌 것으로 취급되는» 자리의 글자만 이어 붙인다.

    `block_labels`·`unpin_inline_labels` 는 문서 전체에 정규식을 돌리므로 스크립트 문자열
    안의 HTML 흉내까지 고친다. JSON-LD 의 headline 이나 스크립트가 비교하는 문자열이 그렇게
    바뀌면 화면에 나오는 것이 달라진다 — 조판이라 부를 수 없다.
    """
    blanked = blank_inert(html)
    out, at, size = [], 0, len(html)
    while at < size:
        if html[at] == blanked[at]:
            at += 1
            continue
        # 증거(덮인 글자)에서 시작해, 공백을 건너뛰며 마지막 증거까지를 한 구간으로 본다.
        # 증거만 모으면 **원래 공백이 서명에서 사라진다** — 덮인 공백과 구별되지 않기
        # 때문이다. 그러면 스크립트 문자열에 공백 하나를 넣는 변경이 통과한다.
        start = last = at
        while at < size and (html[at] != blanked[at] or html[at].isspace()):
            if html[at] != blanked[at]:
                last = at
            at += 1
        out.append(html[start:last + 1])
    return '\0'.join(out)


def equivalent(old_html, new_html):
    """`old_html` 을 조판 변환으로 밀면 `new_html` 이 바이트 그대로 나오는가.

    True 조판 · False 사람이 읽어야 함 · **None 판정 불가**. None 은 「같다」가 아니다 —
    부르는 쪽은 미검토로 세야 한다.
    """
    if old_html is None or new_html is None:
        return None
    fresh, stale = find_block(new_html), find_block(old_html)
    if fresh is None or stale is None:
        return None
    if not is_known(fresh.text):
        return None  # 등록되지 않은 블록은 조판이라고 부르지 않는다
    grafted = old_html[:stale.start] + fresh.text + old_html[stale.end:]
    try:
        if _risky_css(old_html, stale) or _risky_css(new_html, fresh):
            return None
        # 순서는 `enhance_html()` 과 같다. `inject_css` 자리를 위의 이식이 대신한다.
        out = unpin_inline_labels(block_labels(demote_card_p_font(grafted)))
        if _inert(out) != _inert(grafted):
            return None  # 변환이 스크립트·주석을 건드렸다
    except Exception:  # noqa: BLE001 — 못 다루는 페이지는 미검토로 남기는 것이 안전하다
        return None
    return out == new_html


def typography(path, old, new):
    """(경로, 옛 내용, 새 내용) → True 조판 / False 수정 / None 판정 불가."""
    if old is None or new is None:
        return None
    if not path.endswith('.html'):
        return False  # HTML 이 아닌 원고에는 조판이라는 것이 없다
    return equivalent(old, new)
