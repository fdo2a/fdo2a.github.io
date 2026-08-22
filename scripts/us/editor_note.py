"""발행자가 직접 쓰는 의견 블록.

리포트의 나머지는 전부 기계가 쓴다 — 승계되는 국면, 계약으로 묶인 스탠스, 게이트가
대조하는 수치. 이 블록만은 사람이 쓰고, **한 글자도 고쳐지지 않은 채** 실린다.
그래서 파이프라인이 아니라 결정론적 스크립트가 붙인다: 작성 에이전트를 거치면
문체 규칙에 맞춰 다듬고 싶은 유혹이 생기고, 그 순간 그것은 더 이상 그 사람의 글이 아니다.

읽고 쓰는 형식은 마크다운의 아주 작은 부분집합이다(문단 · ## 소제목 · 목록 · 인용 ·
**굵게** · *기울임* · [링크]). 노트 안의 HTML은 실행되지 않고 글자 그대로 보인다.

Pure — 문자열을 받아 문자열을 돌려준다.
"""

import html as _html
import re

MARKER = 'data-editor-note'
DEFAULT_TITLE = '에디터 노트'
CAPTION = '이 항목은 발행자가 직접 쓴 견해다. 나머지 섹션의 자동 분석과 별개다.'

# 자족적인 인라인 스타일 — 발행본마다 <style>이 따로 들어 있어서, 새 클래스를 만들면
# 과거 글을 전부 고쳐야 한다. 카드 하나로 끝나게 둔다.
_SECTION_STYLE = ('background: #fff; border: 1px solid #F2F4F6; border-left: 4px solid #0064FF; '
                  'border-radius: 14px; padding: 18px 20px; margin-bottom: 18px;')
_CAPTION_STYLE = 'color: #8B95A1; font-size: 12.5px; margin-top: 10px;'
_QUOTE_STYLE = ('border-left: 3px solid #E5E8EB; margin: 0 0 9px; padding: 2px 0 2px 12px; '
                'color: #4E5968;')

_SECTION_RE = re.compile(r'\s*<section\b[^>]*\b' + MARKER + r'\s*=\s*"[^"]*"[^>]*>.*?</section>\n?',
                         re.S)


def _inline(text):
    """이스케이프가 먼저다 — 노트에 <script>를 써도 글자로만 보이게."""
    out = _html.escape(text, quote=False)
    out = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',
                 lambda m: f'<a href="{_html.escape(m.group(2), quote=True)}" '
                           f'target="_blank" rel="noopener">{m.group(1)}</a>', out)
    out = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', out)
    out = re.sub(r'(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<em>\1</em>', out)
    return out


def _blocks(body):
    """문단 · 목록 · 인용 · 소제목을 순서대로 HTML로."""
    out = []
    for chunk in re.split(r'\n\s*\n', body):
        lines = [ln.rstrip() for ln in chunk.strip().split('\n') if ln.strip()]
        if not lines:
            continue
        if all(ln.lstrip().startswith(('- ', '* ')) for ln in lines):
            items = ''.join(f'<li>{_inline(ln.lstrip()[2:].strip())}</li>' for ln in lines)
            out.append(f'<ul style="margin: 0 0 9px; padding-left: 20px;">{items}</ul>')
        elif all(ln.lstrip().startswith('>') for ln in lines):
            text = ' '.join(ln.lstrip()[1:].strip() for ln in lines)
            out.append(f'<blockquote style="{_QUOTE_STYLE}">{_inline(text)}</blockquote>')
        elif lines[0].startswith('## '):
            out.append(f'<h3>{_inline(lines[0][3:].strip())}</h3>')
            rest = '\n'.join(lines[1:])
            if rest.strip():
                out.extend(_blocks(rest))
        else:
            out.append(f'<p style="margin: 0 0 9px;">{_inline(" ".join(lines))}</p>')
    return out


# 템플릿을 손대지 않은 채 남겨두면 그 안내문이 발행본에 실린다 — 루틴은 매일 돌고
# 사람은 노트를 만들어두고 잊을 수 있으므로, 미편집 표식이 남아 있으면 싣지 않는다.
TEMPLATE_MARK = '이 줄을 지우면'


def is_template(markdown):
    return TEMPLATE_MARK in (markdown or '')


def render_note(markdown, date):
    """노트 마크다운 → 한 덩어리 <section>. 빈 노트는 빈 문자열(= 섹션 없음)."""
    text = (markdown or '').strip()
    if not text or is_template(text):
        return ''

    title = DEFAULT_TITLE
    if text.startswith('# '):
        head, _, rest = text.partition('\n')
        title = head[2:].strip() or DEFAULT_TITLE
        text = rest.strip()
    body = ''.join(_blocks(text))
    if not body:
        return ''
    return (f'<section id="editor-note" {MARKER}="{date}" style="{_SECTION_STYLE}">\n'
            f'<h2>{_html.escape(title, quote=False)}</h2>\n{body}\n'
            f'<div style="{_CAPTION_STYLE}">{CAPTION} · {date}</div>\n</section>\n')


def _insertion_point(html_doc):
    """§7 전략 코멘트(구 Buy-side 종합 해석) 바로 뒤. 그 섹션이 없으면 면책 문구 앞."""
    m = re.search(r'<section\b[^>]*>(?:(?!</section>).)*?(?:전략 코멘트|Buy-side 종합 해석)'
                  r'.*?</section>\n?',
                  html_doc, re.S)
    if m:
        return m.end()
    m = re.search(r'<section\b[^>]*\bid="disclaimer"', html_doc)
    if m:
        return m.start()
    m = re.search(r'</body>', html_doc)
    return m.start() if m else len(html_doc)


def apply_note(html_doc, note_html):
    """노트를 붙이거나(있으면) 걷어낸다(빈 문자열). 여러 번 돌려도 결과가 같다."""
    cleaned = _SECTION_RE.sub('\n', html_doc, count=1) if MARKER in html_doc else html_doc
    if not note_html:
        return cleaned
    at = _insertion_point(cleaned)
    return cleaned[:at] + '\n' + note_html + cleaned[at:]


def extract_note(html_doc):
    """페이지에 실린 노트를 되읽는다 — 없으면 None."""
    m = _SECTION_RE.search(html_doc)
    if not m:
        return None
    block = m.group(0)
    date = re.search(MARKER + r'\s*=\s*"([^"]*)"', block)
    return {'date': date.group(1) if date else '', 'html': block.strip()}
