"""에이전트 머리말의 model 값 — docs/superpowers/specs/2026-10-27-model-routing.md."""
import re
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3] / '.claude' / 'agents'
EXPECTED = {'brief-data-collector': None,          # 본체 모델 상속 — 해석·가설 인계를 쓴다(codex #2)
            'brief-report-writer': 'opus', 'kr-report-writer': 'opus',
            'news-industry-writer': 'opus', 'kr-news-writer': 'opus', 'period-report-writer': 'opus',
            'japan-report-writer': 'opus', 'japan-daily-writer': 'sonnet',
            'close-meaning-checker': 'opus',   # STEP 2.6 의미 검사자 — 2026-11-06-style-close.md
            'narrow-editor': 'opus'}           # STYLE_CLOSE A5 edits-JSON 호출 — 작성자와 같은 모델(2026-11-19)


def head(path):
    m = re.match(r'---\n(.*?)\n---\n', path.read_text(encoding='utf-8'), re.S)
    return dict(l.split(':', 1) for l in m.group(1).splitlines() if ':' in l) if m else None


def test_every_agent_has_the_designed_model():
    found = {}
    for p in AGENTS.glob('*.md'):
        h = head(p)
        if h and 'name' in h:
            found[h['name'].strip()] = (h.get('model') or '').strip() or None
    assert found == EXPECTED


def test_narrow_editor_has_no_tools_and_stays_small():
    """A5 호출은 도구 0 회·JSON 답 하나다 — 작성자 정의(95 KB)를 싣지 않으려고 만든 정의라 작아야 한다."""
    p = AGENTS / 'narrow-editor.md'
    h = head(p)
    assert h['tools'].strip() == ''
    assert len(p.read_bytes()) < 4096


def test_style_close_a5_calls_the_narrow_editor_and_keeps_the_writer_fallback():
    text = (AGENTS.parent / 'STYLE_CLOSE.md').read_text(encoding='utf-8')
    a5 = next(l for l in text.splitlines() if l.startswith('5. '))
    assert '`narrow-editor`' in a5 and 'model: "opus"' in a5
    assert '`brief-report-writer`/`kr-report-writer`' in a5          # 타입이 없을 때의 폴백
    assert a5.index('narrow-editor') < a5.index('brief-report-writer')
