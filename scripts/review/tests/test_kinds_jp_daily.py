"""일본 일간이 검토 러너에 들어가는 길 — 시장(jp)·디렉터리(japan/daily)·주기(daily) (codex 설계 검토 #9).

자동 Claude 정정은 일간 us·kr 만이다. 일본 일간은 codex 검토 초안 → 수동 review-gate 정정(주간·일본 주간과 같다).
"""
import sys
from datetime import date

from review import kinds
from review import style_pass


def test_jp_daily_section_and_publish_day():
    assert kinds.section_of('japan/daily/2026-10-26.html') == 'japan/daily'
    assert kinds.PERIOD['japan/daily'] == ('jp', 'daily')
    assert kinds.publish_day('japan/daily/2026-10-26.html') == date(2026, 10, 26)
    assert 'japan/daily' in kinds.SECTIONS and kinds.MAX_AGE['japan/daily'] == 2


def test_jp_daily_evidence_is_self_contained():
    assert kinds.evidence('japan/daily', '2026-10-26') == (
        'japan/data/daily/2026-10-26.json', 'japan/data/news/daily/2026-10-26.json')


def test_jp_daily_gates():
    cmds = style_pass.gate_commands('japan/daily', 'p.html', '/ev', 'o.html', '2026-10-26', None)
    flat = [' '.join(c[1:]) for c in cmds]
    assert any(c.startswith('scripts/check_japan_daily.py') and '--session 2026-10-26' in c
               and '--root /ev' in c and '--html p.html' in c for c in flat)
    assert any(c.startswith('scripts/check_news.py') and '--market jp-daily' in c
               and '--datadir /ev/japan/data' in c for c in flat)
    assert not any('check_japan.py' in c for c in flat)


def test_jp_daily_not_auto_corrected():
    assert 'japan/daily' not in kinds.DAILY and 'jp' not in kinds.DAILY


def test_japan_weekly_kind_unchanged():
    assert kinds.PERIOD['japan/posts'] == ('jp', 'weekly') and kinds.MAX_AGE['japan/posts'] == 3
    assert kinds.publish_day('japan/posts/2026-W43.html') == date(2026, 10, 25)
    assert kinds.evidence('japan/posts', '2026-W43') == ('japan/data/2026-W43.json', 'japan/data/2026-W43.news.json')
    cmds = style_pass.gate_commands('japan/posts', 'p.html', '/ev', 'o.html', '2026-W43', None)
    assert any('check_japan.py' in ' '.join(c) for c in cmds)


def test_span_name_has_daily():
    import review_gate
    assert review_gate.SPAN_NAME['daily'] == '일간'
    assert sys.modules['review_gate']
