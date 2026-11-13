"""Stored Telegram summaries that are not summaries (2026-11-12). No imports beyond `re`: the
summariser (collection job) and the publication gate both use it.
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md"""
import re

# Answers that are not a summary (2026-11-12, 85건 중 4건이 저장돼 있었다): the model's refusal
# (「죄송하지만 링크만으로는…」) or a note about the task (「원문은 짧은 댓글 두 줄로… 정리하면 됩니다」).
# The gate refuses to let such an item be quoted (telegram_gate.check), so keep this list narrow.
_REFUSAL = re.compile(r'죄송(?:하지만|합니다|하나|해요)|요약(?:을|해)?\s*드릴 수 없|요약할 수 없|붙여 주시면|제공해 주시면|링크만으로는|'
                      r'^\s*원문(?:은|에는)\s|정리하면 됩니다|정리해 드리겠')
# The prompt asks for the plain register (~다). A sentence ending in 합쇼체·해요체 means the model
# answered the editor instead of writing the paragraph. Quoted speech (「"…하겠습니다"라고」) does not
# end a sentence, and 「아니다」 has no ㅂ under the syllable before 니다.
_NIDA = re.compile(r'([가-힣])니다[.!?]?(?=["”’)\]]*(?:\s|$))')
_YO = re.compile(r'(?:세요|에요|예요|어요|아요|해요|네요|군요|죠)[.!?]?(?=["”’)\]]*(?:\s|$))')


def refusal(text):
    m = _REFUSAL.search(text or '')
    return m.group(0).strip() if m else None


def polite(text):
    for m in _NIDA.finditer(text or ''):
        if (ord(m.group(1)) - 0xAC00) % 28 == 17:          # final consonant ㅂ: 습니다·입니다·됩니다·합니다
            return m.group(0)
    m = _YO.search(text or '')
    return m.group(0) if m else None


def unusable(text):
    """Reason a stored summary must not be kept, or None."""
    r = refusal(text)
    if r:
        return f'요약이 아닌 답 「{r}」'
    p = polite(text)
    if p:
        return f'합쇼체·해요체 「{p}」'
    return None
