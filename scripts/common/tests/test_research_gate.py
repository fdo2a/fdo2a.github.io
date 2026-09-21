"""Publication checks must bind the visible review to the actual as-of ledger."""
import copy
import importlib
import importlib.util

import pytest


def gate():
    assert importlib.util.find_spec('common.research_gate'), 'research publication gate is not implemented'
    return importlib.import_module('common.research_gate')


def summary():
    return {'market': 'us', 'start': '2026-09-20', 'end': '2026-09-25',
            'as_of': '2026-09-26T00:00:00+00:00',
            'counts': {'total': 1, 'prospective': 1, 'retrospective': 0, 'open': 1, 'overdue': 0},
            'hypotheses': [{'id': 'h1', 'title': '물가 < 기대', 'stage': 'insight',
                            'prospective': True, 'status': 'open', 'overdue': False,
                            'direction': 'supported', 'mechanism': 'undecidable',
                            'execution_status': 'watch',
                            'performance': {'status': 'unavailable', 'reason': '체결 자료 없음'}}],
            'cycles': []}


def test_rendered_review_preserves_unknown_mechanism_and_performance():
    g = gate(); s = summary(); html = g.render_summary(s)
    assert '물가 &lt; 기대' in html
    assert '판단 유보' in html and '평가 불가' in html
    assert '검증된 엣지' not in html
    assert g.checked_summary_body('<main>' + html + '</main>', s) == '<main></main>'


def test_tampered_summary_or_duplicate_marker_is_rejected():
    g = gate(); s = summary(); html = g.render_summary(s)
    for bad in (html.replace('판단 유보', '지지'), html + html,
                html.replace('물가 &lt; 기대', '시장 수익률 77%')):
        with pytest.raises(ValueError):
            g.checked_summary_body(bad, s)


def test_other_market_summary_cannot_be_reused():
    g = gate(); s = summary(); other = copy.deepcopy(s); other['market'] = 'kr'
    with pytest.raises(ValueError):
        g.checked_summary_body(g.render_summary(s), other)


def test_summary_is_compatible_with_readability_enhancement():
    from us.readability import enhance_html
    g = gate(); s = summary(); html = '<html><body data-layout="prose">' + g.render_summary(s) + '</body></html>'
    assert 'data-research-summary' not in g.checked_summary_body(enhance_html(html), s)


def test_daily_missing_wrong_cycle_or_missing_idea_is_rejected():
    g = gate()
    rows = [{'id': 'c1', 'type': 'cycle', 'market': 'us', 'report_date': '2026-09-20',
             'candidate_ids': ['h1'], 'reviewed_ids': [], 'unresolved': []}]
    html = '<section data-research-cycle="c1"><p data-hypothesis="h1">새 자료는 기존 기대와 다르다.</p></section>'
    assert g.check_daily(html, rows, 'c1', 'us', '2026-09-20') == []
    assert g.check_daily(html, rows, 'c1', 'kr', '2026-09-20')
    assert g.check_daily(html.replace('data-hypothesis', 'other'), rows, 'c1', 'us', '2026-09-20')
    assert g.check_daily(html.replace('c1', 'wrong'), rows, 'c1', 'us', '2026-09-20')


def test_editorial_comparison_counts_repetition_without_ai_score():
    g = gate()
    sentence = '코스피는 장 초반의 상승분을 반납한 뒤 전일 종가 부근에서 마감했다.'
    before = f'<p>{sentence}</p><p>{sentence}</p><p>날짜 차이를 따로 설명할 필요는 없다.</p>'
    after = f'<p>{sentence}</p><p>외국인 매도는 오후에 집중됐다.</p>'
    out = g.compare_drafts(before, after)
    assert out['before']['duplicate_sentences'] == 1
    assert out['after']['duplicate_sentences'] == 0
    assert len(out['before']['internal_notes']) == 1
    assert out['after']['internal_notes'] == []
    assert 'ai_score' not in out


def test_editorial_ignores_tables_scripts_and_personal_notes():
    g = gate(); text = '날짜 차이를 따로 설명할 필요는 없다.'
    html = f'<script>{text}</script><table><tr><td>{text}</td></tr></table><section data-editor-note="1"><p>{text}</p></section><p>10년 금리는 4.25%였다.</p>'
    assert g.compare_drafts(html, html)['after']['internal_notes'] == []


def test_cli_renders_then_checks_bootstrap_and_detects_tampering(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    cli = repo / 'scripts/check_research.py'
    out = tmp_path / 'summary.html'
    common = ['--root', str(tmp_path / 'research'), '--market', 'us', '--start', '2026-09-20',
              '--end', '2026-09-25', '--as-of', '2026-09-26T00:00:00+00:00']
    rendered = subprocess.run([sys.executable, str(cli), 'render', *common, '--out', str(out)], capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stderr
    checked = subprocess.run([sys.executable, str(cli), 'check', '--span', 'weekly', '--html', str(out), *common], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr + checked.stdout
    out.write_text(out.read_text().replace('진행 중 0건', '진행 중 9건'))
    checked = subprocess.run([sys.executable, str(cli), 'check', '--span', 'weekly', '--html', str(out), *common], capture_output=True, text=True)
    assert checked.returncode == 1


@pytest.mark.parametrize("later_date", ["2026-09-20", "2026-09-19"])
def test_daily_cycle_cannot_hide_later_research(later_date):
    rows = [{'id': 'c1', 'type': 'cycle', 'market': 'us', 'report_date': '2026-09-20',
             'candidate_ids': [], 'reviewed_ids': [], 'unresolved': []},
            {'id': 'h2', 'type': 'hypothesis', 'market': 'us', 'report_date': later_date}]
    html = '<section data-research-cycle="c1"><p>새 후보 없음.</p></section>'
    assert gate().check_daily(html, rows, 'c1', 'us', '2026-09-20')


def test_registered_research_flows_to_daily_and_period_publication(tmp_path):
    from scripts.research_ledger import template
    from common.research_ledger import append_record, read_records, summarize
    from us.prose_swap import extract
    root = tmp_path / 'research' / 'us'
    source = tmp_path / 'evidence.txt'
    source.write_text('Synthetic fixture: observed price reaction. Not investment evidence.')
    p = template('hypothesis', 'us')
    p.update(id='h1', report_date='2026-09-20', data_cutoff='2026-09-20T11:00:00Z',
             test_start_at='2026-09-21T12:00:00Z', deadline='2026-09-25T12:00:00Z',
             sources=[dict(id='s1', path=str(source), provenance='test fixture',
                           published_at='2026-09-20T10:00:00Z', observed_at='2026-09-20T10:30:00Z')])
    for field in ('title','question','observation','our_view','difference','mechanism','alternative','support','invalidation'):
        p[field] = '검증용 가설 설명'
    p['expectation'] = {'kind': 'unknown', 'description': '기대 자료 없음'}
    append_record(root, p, now='2026-09-20T12:00:00Z')
    c = {key: p[key] for key in ('market','report_date','data_cutoff','sources')}
    c.update(id='c1', type='cycle', central_questions=['무엇을 확인할 것인가?'], candidate_ids=['h1'], reviewed_ids=[], unresolved=[])
    append_record(root, c, now='2026-09-20T12:01:00Z')
    daily = '<section data-research-cycle="c1"><p data-hypothesis="h1">다음 관측에서 설명의 타당성을 확인한다.</p></section>'
    assert gate().check_daily(daily, read_records(root), 'c1', 'us', '2026-09-20') == []
    s = summarize(root, 'us', '2026-09-20', '2026-09-20', '2026-09-20T13:00:00Z')
    fragment = gate().render_summary(s)
    assert s['counts']['prospective'] == 1
    assert '평가 불가' in fragment
    assert gate().checked_summary_body(fragment, s) == ''
    assert not extract(fragment)[1]['items']
    with pytest.raises(ValueError):
        gate().checked_summary_body(fragment.replace('평가 불가', '성과 확인'), s)
