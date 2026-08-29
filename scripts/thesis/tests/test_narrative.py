from thesis import narrative as N
from build_thesis_pages import build_narrative


def test_narrative_is_selective_and_ordered():
    assert 5 <= len(N.PHASES) <= 8
    assert N.PHASES[0]['period'].startswith('출발점')
    assert N.PHASES[-1]['period'].startswith('현재')


def test_each_phase_has_a_real_before_after_shift():
    for phase in N.PHASES:
        assert phase['title']
        assert len(phase['before']) >= 40
        assert len(phase['after']) >= 40
        assert all(key in N.SOURCES for key in phase['sources'])


def test_all_three_companies_have_current_proof_points():
    assert {row['name'] for row in N.COMPANIES} == {'삼성전자', 'SK하이닉스', 'Micron'}
    assert all(row['start'] and row['now'] and row['proof'] for row in N.COMPANIES)


def test_accounting_correction_keeps_rpo_definitions_separate():
    combined = ' '.join(title + ' ' + body for title, body in N.CORRECTIONS)
    for token in ('$5B', '$100B', '$22B', '기준일'):
        assert token in combined


def test_no_unresolved_or_recommendation_markers():
    text = repr((N.PHASES, N.COMPANIES, N.CORRECTIONS, N.CURRENT_FRAME, N.BOTTOM_LINE))
    for forbidden in ('[확인필요]', 'TODO', 'TBD', 'buy-side', '매수 추천'):
        assert forbidden not in text


def test_built_page_contains_the_curated_structure_and_no_archive_ui():
    page = build_narrative('2026-08-24')
    assert page.count('class="phase"') == len(N.PHASES)
    assert page.count('class="company"') == len(N.COMPANIES)
    assert page.count('class="correction"') == len(N.CORRECTIONS)
    assert '전체 감시 기록' not in page
    assert 'data-archive-search' not in page
