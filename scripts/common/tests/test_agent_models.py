"""에이전트 머리말의 model 값 — docs/superpowers/specs/2026-10-27-model-routing.md."""
import re
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3] / '.claude' / 'agents'
EXPECTED = {'brief-data-collector': None,          # 본체 모델 상속 — 해석·가설 인계를 쓴다(codex #2)
            'brief-report-writer': 'opus', 'kr-report-writer': 'opus',
            'news-industry-writer': 'opus', 'period-report-writer': 'opus',
            'japan-report-writer': 'opus', 'japan-daily-writer': 'sonnet'}


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
