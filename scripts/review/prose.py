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

import base64
import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review.known_blocks import is_known  # noqa: E402
from us.colorize import paint  # noqa: E402
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


def transformed(old_html, new_html):
    """`old_html` 에 «새 판의 조판 블록 + 색칠»을 입힌 결과. 판정 불가면 None.

    `equivalent()` 와 조합 경로가 같은 변환을 쓰게 하려고 갈라 두었다 — 두 변환이 한
    판에 겹쳤을 때(조판·색 + 자산 외부화) 이 결과를 다음 변환의 입력으로 넘긴다.
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
        # 색칠(`apply_colors.py`)은 그다음 단계라 여기서도 뒤에 온다. 값에서 결정론적으로
        # 다시 계산하므로, 손으로 바꿔 넣은 색은 이 변환을 통과하지 못한다.
        out = paint(unpin_inline_labels(block_labels(demote_card_p_font(grafted))))
        if _inert(out) != _inert(grafted):
            return None  # 변환이 스크립트·주석을 건드렸다
    except Exception:  # noqa: BLE001 — 못 다루는 페이지는 미검토로 남기는 것이 안전하다
        return None
    return out


def equivalent(old_html, new_html):
    """`old_html` 을 조판 변환으로 밀면 `new_html` 이 바이트 그대로 나오는가.

    True 조판 · False 사람이 읽어야 함 · **None 판정 불가**. None 은 「같다」가 아니다 —
    부르는 쪽은 미검토로 세야 한다.
    """
    out = transformed(old_html, new_html)
    return None if out is None else out == new_html


# 임베드를 파일 참조로 바꾼 판. `equivalent()` 는 CSS 블록만 이식하므로 여기에 닿지
# 못한다. 방향은 이 모듈의 원칙 그대로 — **새 판을 되감아 옛 판이 바이트 그대로 나오는지**
# 만 본다. 수치·태그 비교로는 다른 이미지를 걸어도, 문장을 함께 고쳐도 통과한다.
_SRC_EXTERNAL = re.compile(r'src="([^"]*)"')
_SRC_INLINE = re.compile(r'src="data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)"', re.I)
_INLINE_URI = re.compile(r'data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)\Z', re.I)
_MASK = '\x00src\x00'
# 주석은 태그가 아니다 — 먼저 소진시켜 그 안의 `src` 가 속성으로 읽히지 않게 한다.
_TAG_SPAN = re.compile(r'<!--.*?-->|<[^>]*>', re.S)


def asset_externalized(old_html, new_html, read_asset):
    """True 자산 외부화만 한 판 / False 그 밖의 변경이 섞임 / None 판정 불가.

    `read_asset(경로)` 는 새 판이 가리키는 파일의 바이트, 없으면 None 을 돌려준다.

    되감기를 `src` 전부에 걸던 판은 광고 로더 `<script src="https://…">` 까지 파일로
    찾다가 모든 발행본을 「판정 불가」로 만들었다(2026-09-06, 실측 38편 전부). 그래서
    **양쪽의 `src` 를 자리표시자로 가려 나머지 바이트가 같은지 먼저 보고**, 그다음 자리
    별로 짝을 맞춘다 — 안 바뀐 `src` 는 그대로여야 하고, 바뀐 자리는 옛 판이 임베드,
    새 판이 파일이어야 하며 그 파일이 임베드 바이트와 정확히 같아야 한다.
    """
    if old_html is None or new_html is None:
        return None
    if not _SRC_INLINE.search(old_html):
        return None  # 되감을 것이 없다 — 이 변환의 사례가 아니다
    if _SRC_INLINE.search(new_html):
        return None  # 아직 임베드가 남았다면 이 변환이 끝난 판이 아니다

    def mask(html):
        """태그 **안**의 `src` 만 가린다.

        문서 전체에 정규식을 걸던 판은 산문에 `src="data:…"` 라고 쓰여 있기만 해도
        그 글자를 자산으로 읽었다 — 본문을 고치고 「조판」으로 통과시킬 수 있었다
        (2026-09-06 codex 검토 1). 주석 안도 태그가 아니다.
        """
        srcs = []
        out = []
        at = 0
        for tag in _TAG_SPAN.finditer(html):
            out.append(html[at:tag.start()])
            span = tag.group(0)
            out.append(span if span.startswith('<!--') else _SRC_EXTERNAL.sub(
                lambda m: srcs.append(m.group(1)) or _MASK, span))
            at = tag.end()
        out.append(html[at:])
        return ''.join(out), srcs

    masked_old, old_srcs = mask(old_html)
    masked_new, new_srcs = mask(new_html)
    if masked_old != masked_new or len(old_srcs) != len(new_srcs):
        return False  # src 밖의 바이트가 다르다

    for was, now in zip(old_srcs, new_srcs):
        if was == now:
            continue  # 손대지 않은 자리
        m = _INLINE_URI.match(was)
        if not m:
            return False  # 임베드가 아니었는데 바뀌었다
        raw = read_asset(now)
        if raw is None:
            return None
        if base64.b64encode(raw).decode() != m.group(2):
            return False
    return True


def typography(path, old, new, root=None):
    """(경로, 옛 내용, 새 내용) → True 조판 / False 수정 / None 판정 불가.

    `root` 를 주면 자산 외부화(임베드 → 파일 참조)도 같은 자리로 받는다. 그 변환은
    독자가 받는 그림이 바이트 그대로라 조판과 성격이 같은데, `equivalent()` 는 CSS
    블록만 이식하므로 닿지 못한다(2026-09-06).
    """
    if old is None or new is None:
        return None
    if not path.endswith('.html'):
        return False  # HTML 이 아닌 원고에는 조판이라는 것이 없다
    verdict = equivalent(old, new)
    if verdict:
        return True
    reader = _asset_reader(root, path)
    asset = asset_externalized(old, new, reader)
    if asset is not True:
        # **두 변환이 한 판에 겹친 경우.** 각각으로는 설명되지 않는다 — 색이 섞이면
        # `asset_externalized` 는 src 밖 바이트가 다르다며 False 를 준다 — 조판·색을 먼저
        # 입히고 나서 자산 외부화만 남는지 본다. 2026-09-12 색 소급이 임베드가 남아 있던
        # 옛 판 28편을 한꺼번에 「수정됨」으로 만든 자리다. 방향은 그대로 — 되감아
        # 바이트가 같은지만 본다.
        staged = transformed(old, new)
        if staged is not None:
            composed = asset_externalized(staged, new, reader)
            if composed is not None:
                asset = composed
    if asset is not None:
        return asset
    return verdict


def _asset_reader(root, path):
    """발행본 위치를 기준으로 상대경로를 푸는 읽기 함수. root 가 없으면 늘 None."""
    def read(rel):
        if root is None or rel.startswith(('http:', 'https:', 'data:', '//')):
            return None
        target = os.path.normpath(os.path.join(root, os.path.dirname(path), rel))
        if not os.path.isfile(target):
            return None
        with open(target, 'rb') as fh:
            return fh.read()
    return read
