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


def test_jp_daily_telegram_pin_is_optional_evidence(monkeypatch):
    """The pinned Telegram summaries travel with the post when the publish commit has them; a post
    without them (no usable file that day, or before 2026-11-15) is still reviewable."""
    import collections
    import review_gate
    key = '2026-10-26'
    pin = f'japan/data/telegram/published/{key}.json'
    assert kinds.optional_evidence('japan/daily', key) == (pin,)
    assert pin not in kinds.evidence('japan/daily', key)
    for section, k in (('weekly', '2026-W43'), ('kr/weekly', '2026-W43'), ('japan/posts', '2026-W43')):
        assert kinds.optional_evidence(section, k) == ()
    item = collections.namedtuple('Item', 'section path')('japan/daily', f'japan/daily/{key}.html')
    monkeypatch.setattr(review_gate, 'rev_parse', lambda root, ref: 'sha')
    assert review_gate._period_evidence('.', 'c0ffee', item) == kinds.evidence('japan/daily', key) + (pin,)
    monkeypatch.setattr(review_gate, 'rev_parse', lambda root, ref: None if 'telegram' in ref else 'sha')
    have = review_gate._period_evidence('.', 'c0ffee', item)
    assert have == kinds.evidence('japan/daily', key)
    assert [p for p in kinds.evidence('japan/daily', key) if p not in have] == []      # nothing "missing"


def test_pin_travels_from_the_publish_commit_to_the_gate_rerun(tmp_path, capsys):
    """End to end on a real repository: the publish commit's pin is listed as evidence, extracted
    next to the post, and is what the re-run gate reads — never the collector's later file."""
    import collections
    import json
    import subprocess

    import check_japan_daily as CLI
    import review_gate
    from japan.tests import test_daily_views as V

    S = V.S
    root = tmp_path / 'repo'
    files = {f'japan/daily/{S}.html': V.page(),
             f'japan/data/daily/{S}.json': json.dumps(V.SNAP, ensure_ascii=False),
             f'japan/data/news/daily/{S}.json': '{"items": []}',
             f'japan/data/telegram/published/{S}.json': json.dumps(V.DATA, ensure_ascii=False),
             f'japan/data/telegram/{S}.json': json.dumps(V.tg(V.I2), ensure_ascii=False)}    # pushed later by the collector
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')

    def git(*a):
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *a], cwd=root,
                              check=True, capture_output=True, text=True)
    git('init', '-q')
    git('add', '-A')
    git('commit', '-qm', f'Add JP daily [{S}]')
    item = collections.namedtuple('Item', 'section path')('japan/daily', f'japan/daily/{S}.html')
    have = review_gate._period_evidence(str(root), 'HEAD', item)
    assert have == kinds.evidence('japan/daily', S) + kinds.optional_evidence('japan/daily', S)
    ev = tmp_path / 'ev'
    ev.mkdir()
    assert review_gate.snapshot(str(root), 'HEAD', (item.path, *have), str(ev), everything=True)
    assert not (ev / 'japan' / 'data' / 'telegram' / f'{S}.json').exists()             # the collector's file is not evidence
    assert CLI.main(['--session', S, '--root', str(ev)]) == 0
    assert '견해·의견 다시 읽기 3건' in capsys.readouterr().out

    # a publish commit without the pin: the same post fails closed instead of passing unchecked
    git('rm', '-q', f'japan/data/telegram/published/{S}.json')
    git('commit', '-qm', 'no pin')
    have = review_gate._period_evidence(str(root), 'HEAD', item)
    assert have == kinds.evidence('japan/daily', S)
    ev2 = tmp_path / 'ev2'
    ev2.mkdir()
    assert review_gate.snapshot(str(root), 'HEAD', (item.path, *have), str(ev2), everything=True)
    assert CLI.main(['--session', S, '--root', str(ev2)]) == 1
    assert '쓸 수 있는 텔레그램 파일이 없다' in capsys.readouterr().err
