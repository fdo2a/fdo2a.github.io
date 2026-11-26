"""늦은 글의 cycle 한 줄 — 그날(report_date) 열려 있던 가설만 unresolved 로 (2026-11-27).

늦은 글은 원장에 새 가설·복기·근거를 더하지 않는다. daily 검사는 그 날짜의 cycle 한 줄을 요구하므로 cycle 만 덧붙인다.
원장 검증은 이미 report_date 기준이다 — 뒤 세션의 가설은 이름을 댈 수도 없다(`Unresolved hypothesis belongs to a
later session`). 그래서 `check_research.py check` 에는 as-of 가 따로 필요 없다. 실제 원장(11/27 전까지)으로 본다.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.common.research_gate import check_daily
from scripts.common.research_ledger import append_record, late_cycle, read_records

ROOT = Path(__file__).resolve().parents[3]
AS_OF_1124 = {'us-2026-11-17-nvidia-earnings-relief-vs-governance-margin',
              'us-2026-11-19-continuing-claims-michigan-transitory-vs-broadening',
              'us-2026-11-20-front-end-flight-to-quality-vs-hike-path-repricing',
              'us-2026-11-23-ai-rebound-positioning-unwind-vs-uncertainty-removal'}


@pytest.fixture
def ledger(tmp_path):
    """research/us 를 11/27 전까지만 — 해시 사슬은 앞부분이라 그대로 맞는다."""
    root = tmp_path / 'us'
    shutil.copytree(ROOT / 'research' / 'us', root)
    lines = (root / 'ledger.jsonl').read_text(encoding='utf-8').splitlines()
    keep = [ln for ln in lines if json.loads(ln)['recorded_at'] < '2026-11-27']
    (root / 'ledger.jsonl').write_text('\n'.join(keep) + '\n', encoding='utf-8')
    return root


def _open_now(records):
    out = set()
    for h in (r for r in records if r['type'] == 'hypothesis'):
        reviews = [r for r in records if r['type'] == 'review' and r['hypothesis_id'] == h['id']]
        if not reviews or reviews[-1]['status'] == 'open':
            out.add(h['id'])
    return out


def test_the_late_cycle_names_only_what_was_open_that_day(ledger):
    records = read_records(ledger)
    cycle = late_cycle(records, 'us', '2026-11-24')
    assert {u['hypothesis_id'] for u in cycle['unresolved']} == AS_OF_1124
    assert _open_now(records) != AS_OF_1124                       # 지금 열린 가설과 다르다(11/25 가 셋을 닫고 하나를 더했다)
    assert cycle['candidate_ids'] == [] and cycle['reviewed_ids'] == []
    appended = append_record(ledger, cycle)
    html = (f'<section data-research-cycle="{appended["id"]}">'
            + ''.join(f'<p data-hypothesis="{h}">이어 본다.</p>' for h in sorted(AS_OF_1124)) + '</section>')
    assert check_daily(html, read_records(ledger), appended['id'], 'us', '2026-11-24') == []


def test_naming_a_later_sessions_hypothesis_is_refused_by_the_ledger(ledger):
    cycle = late_cycle(read_records(ledger), 'us', '2026-11-24')
    cycle['unresolved'].append({'hypothesis_id': 'us-2026-11-25-long-end-protection-bid-vs-hike-credibility',
                                'reason': 'x'})
    with pytest.raises(ValueError, match='later session'):
        append_record(ledger, cycle)


def test_a_day_that_already_has_records_is_not_a_late_cycle(ledger):
    with pytest.raises(ValueError, match='2026-11-23'):
        late_cycle(read_records(ledger), 'us', '2026-11-23')


def test_cli_prints_the_payload(ledger):
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'research_ledger.py'), 'late-cycle',
                        '--root', str(ledger), '--market', 'us', '--date', '2026-11-24'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got['id'] == 'us-2026-11-24-late-cycle' and got['report_date'] == '2026-11-24'
