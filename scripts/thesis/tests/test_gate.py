from thesis import gate as G


ENTRY = '''<li data-date="2026-09-29" data-signal="주의" data-stance="Bearish">
  <h4>Micron FQ4 실적 — 총이익률 가이던스 하회</h4>
  <div data-part="fact">비GAAP GM 82%로 가이던스 86% 하회. <cite>Micron FQ4'26 실적자료</cite></div>
  <div data-part="inference">추론: 비계약 물량의 가격이 먼저 꺾였을 가능성.</div>
  <div data-part="delta">RPO는 유지됐으나 마진 축이 처음으로 훼손.</div>
  <div data-part="next">FQ1 가이던스와 RPO 잔액.</div>
</li>'''

PAGE = '''<article data-ticker="MU" data-grade="주의" data-since="2026-09-29">
<ol data-block="changelog">{entries}</ol>
<section data-block="thesis">기준표</section>
<section data-block="valuation" data-computed="2026-09-29">밸류</section>
</article>'''


def page(entries=ENTRY, **kw):
    html = PAGE.format(entries=entries)
    for old, new in kw.items():
        html = html.replace(old.replace('_', '-'), new)
    return html


def keys(problems):
    return {p['check'] for p in problems}


# ── 등급 어휘 ──

def test_controlled_grade_passes():
    assert 'grade_vocabulary' not in keys(G.check(page(), state_grade='주의'))


def test_free_form_grade_is_rejected():
    html = PAGE.format(entries=ENTRY).replace('data-grade="주의"', 'data-grade="적극매수"')
    assert 'grade_vocabulary' in keys(G.check(html, state_grade='적극매수'))


# ── state 정합 ──

def test_state_grade_must_match_page():
    assert 'state_consistency' in keys(G.check(page(), state_grade='홀딩 강화'))


def test_matching_state_passes():
    assert 'state_consistency' not in keys(G.check(page(), state_grade='주의'))


# ── 알림 7요소 ──

def test_complete_entry_passes():
    assert 'entry_format' not in keys(G.check(page(), state_grade='주의'))


def test_entry_missing_fact_is_flagged():
    broken = ENTRY.replace('<div data-part="fact">비GAAP GM 82%로 가이던스 86% 하회. '
                           '<cite>Micron FQ4\'26 실적자료</cite></div>', '')
    assert 'entry_format' in keys(G.check(page(broken), state_grade='주의'))


def test_entry_missing_next_is_flagged():
    broken = ENTRY.replace('<div data-part="next">FQ1 가이던스와 RPO 잔액.</div>', '')
    assert 'entry_format' in keys(G.check(page(broken), state_grade='주의'))


def test_bad_stance_label_is_flagged():
    broken = ENTRY.replace('data-stance="Bearish"', 'data-stance="아주 나쁨"')
    assert 'entry_format' in keys(G.check(page(broken), state_grade='주의'))


def test_init_entry_is_exempt_from_seven_elements():
    init = '<li data-date="2026-08-24" data-signal="init"><h4>최초 작성</h4></li>'
    assert 'entry_format' not in keys(G.check(page(init), state_grade='주의'))


# ── 사실/추론 분리 ──

def test_fact_without_source_is_flagged():
    broken = ENTRY.replace('<cite>Micron FQ4\'26 실적자료</cite>', '')
    assert 'fact_sourcing' in keys(G.check(page(broken), state_grade='주의'))


# ── kill 두 축 ──

def test_held_kill_page_is_not_rechecked_per_day():
    """Kill is judged on entry (check_grades); a held kill day needs no fresh axes."""
    html = PAGE.format(entries=ENTRY).replace('data-grade="주의"', 'data-grade="kill condition"')
    assert 'kill_axes' not in keys(G.check(html, state_grade='kill condition'))


# ── 등급 규율 — HEAD 의 책에서 propose() 재현 ──

TODAY = '2026-11-20'


def bk(grade, since='2026-11-10'):
    return {'grade': grade, 'grade_since': since}


def ev(licences=('bear_proximity',), axes=()):
    return {'MU': {'licences': list(licences), 'kill_evidence': tuple(axes)}}


def grades(base, new, evidence=None):
    return [(p['check'], p['where']) for p in
            G.check_grades({'MU': base}, {'MU': new}, TODAY, evidence or ev())]


def test_unchanged_grade_needs_nothing():
    assert grades(bk('kill condition'), bk('kill condition'), ev(())) == []


def test_one_step_with_licence_passes():
    assert grades(bk('홀딩 강화'), bk('주의', TODAY)) == []


def test_move_without_licence_is_blocked():
    assert grades(bk('홀딩 강화'), bk('주의', TODAY), ev(())) == [('grade_discipline', 'MU')]


def test_two_steps_are_blocked():
    assert grades(bk('홀딩 강화'), bk('비중 조절 검토', TODAY)) == [('grade_discipline', 'MU')]


def test_recovery_inside_lock_is_blocked():
    assert grades(bk('주의', '2026-11-19'), bk('홀딩 강화', TODAY)) == [('grade_discipline', 'MU')]


def test_kill_with_both_axes_passes():
    assert grades(bk('비중 조절 검토'), bk('kill condition', TODAY),
                  ev(axes=('contract', 'price'))) == []


def test_kill_with_one_axis_is_blocked():
    assert grades(bk('비중 조절 검토'), bk('kill condition', TODAY),
                  ev(axes=('price',))) == [('grade_discipline', 'MU')]


def test_second_move_on_a_day_head_already_moved_is_blocked():
    moved = bk('비중 조절 검토', TODAY)
    for later in (bk('kill condition', TODAY), bk('주의', TODAY), bk('주의', '2026-11-10')):
        assert grades(moved, later, ev(axes=('contract', 'price'))) != [], later


def test_grade_since_only_change_is_tamper():
    assert grades(bk('주의', '2026-11-10'), bk('주의', '2026-11-01')) == [
        ('grade_since_tamper', 'MU')]


def test_unreadable_head_state_blocks():
    assert [p['check'] for p in G.check_grades(None, {'MU': bk('주의')}, TODAY, {})] == [
        'grade_discipline']


def test_ticker_missing_from_head_blocks():
    problems = G.check_grades({}, {'MU': bk('주의')}, TODAY, {})
    assert [(p['check'], p['where']) for p in problems] == [('grade_discipline', 'MU')]


def test_free_form_grade_in_state_is_blocked_not_raised():
    assert grades(bk('주의'), bk('매도', TODAY)) == [('grade_discipline', 'MU')]


def test_unresolved_marker_is_flagged():
    assert 'banned_markers' in keys(
        G.check(page(ENTRY.replace('82%', '[확인필요]')), state_grade='주의'))


def test_buyside_wording_is_flagged():
    assert 'banned_labels' in keys(
        G.check(page(ENTRY.replace('추론:', 'buy-side 관점:')), state_grade='주의'))


# ── 침묵 강제 ──

def test_edit_without_trigger_is_rejected():
    p = G.check_silence(triggers=[], events=[], page_changed=True)
    assert p and p['check'] == 'silence'


def test_no_edit_without_trigger_is_fine():
    assert G.check_silence(triggers=[], events=[], page_changed=False) is None


def test_edit_with_numeric_trigger_is_fine():
    assert G.check_silence(triggers=[{'key': 'bear_proximity'}], events=[],
                           page_changed=True) is None


def test_edit_with_confirmed_event_is_fine():
    assert G.check_silence(triggers=[], events=[{'confirmed': True}],
                           page_changed=True) is None


def test_unconfirmed_event_alone_cannot_justify_an_edit():
    p = G.check_silence(triggers=[], events=[{'confirmed': False}], page_changed=True)
    assert p and p['check'] == 'silence'


# ── 구조 ──

def test_missing_required_block_is_flagged():
    html = PAGE.format(entries=ENTRY).replace('<section data-block="thesis">기준표</section>', '')
    assert 'required_blocks' in keys(G.check(html, state_grade='주의'))


def test_clean_page_reports_nothing():
    assert G.check(page(), state_grade='주의') == []
