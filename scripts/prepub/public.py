"""독자가 보는 글자 — 검토자의 인용을 글과 대조할 때 쓰는 한 가지 읽기.

`split` 이 인용의 자리를 찾을 때, `prepub_review record` 가 명료성 지적의 인용을 공개 기록에 실을지 정할 때,
주간 묶음(`review/style_digest.py`)이 그 인용이 발행본에 남았는지 볼 때 **같은 함수**를 쓴다. 읽기가 다르면
「S&amp;P」를 「S&P」로 인용한 지적이 글에 없는 것으로 보인다. 가벼운 모듈이다 — 다른 것을 끌어오지 않는다.
"""
import html as _html
import re

_TAG = re.compile(r'<[^>]+>')
# 블록 경계 — 제목 끝 「앞단 」과 다음 캡션 첫 「재가격」이 붙어 가짜 중복을 만들지 않게 칸막이를 둔다(codex 구현 재검토 #3)
_BLOCK = re.compile(r'</?(?:p|h[1-6]|li|ul|ol|td|th|tr|table|caption|figcaption|figure|div|section|article|header|'
                    r'footer|nav|aside|details|summary|blockquote|title|br|hr)\b[^>]*>', re.I)
_WALL = '\x00'
# 화면에 안 보이는 것 — 스크립트·스타일·머리·주석 안의 글은 세지 않는다(재검토 3회 #2)
_HIDDEN = re.compile(r'<!--.*?-->|<(script|style|template|noscript|head)\b.*?</\1\s*>', re.S | re.I)


def norm(text):
    return ' '.join((text or '').split())


def visible(html):
    """독자가 보는 글 — 블록 사이에 칸막이, 인라인 태그는 떼고, 엔티티(&nbsp; …)는 풀어서(재검토 #1)."""
    return norm(_html.unescape(_TAG.sub('', _BLOCK.sub(_WALL, _HIDDEN.sub('', html or '')))))
