from us import macro
from us.macro_gate import (check, parse_group_blocks, parse_transmission_cells,
                           section_macro)

REPORT_DATE = '2026-08-18'

DIRS = {'equities': 0, 'bonds': 1, 'fx': -1, 'energy': 0,
        'metals': 1, 'memory': 1, 'ai_infra': 0}


GROUP_TEXT = {
    'rates': '실질금리 상단이 눌린다. 확인 지표는 Core PCE 3.3% 하회.',
    'demand': '최종수요가 버티는 한 이익 추정치는 유지된다. 확인 지표는 소매판매 0.4% 반등.',
    'dollar': '금리차가 좁혀지며 달러가 약해진다. 확인 지표는 DXY 96.5 하회.',
    'ai_cycle': '캐펙스 사이클이 지표 사이클과 분리돼 있다. 확인 지표는 HBM 계약가 8% 인상.',
}


def strip(dirs):
    """The at-a-glance direction row — one badge per asset, marker inside."""
    items = ''.join(
        f'<span class="mt-item"><b>{a}</b> '
        f'<span data-macro-asset="{a}" data-direction="{d}">'
        f'{macro.TRANSMISSION_LABELS[d]}</span> '
        f'<span class="sub">4영업일</span></span>'
        for a, d in dirs.items())
    return f'<div class="mt-strip">{items}</div>'


def groups(text=None, skip=()):
    text = text or GROUP_TEXT
    out = ''
    for key, label, assets in macro.TRANSMISSION_GROUPS:
        if key in skip:
            continue
        out += (f'<div data-macro-group="{key}"><h4>{label}</h4>'
                f'<p>{text.get(key, "")}</p></div>')
    return out


def build_html(growth=0, inflation=-1, dirs=None, scores=(0.12, -0.55), prob=68.0,
               reconcile=(), extra='', group_text=None, skip_groups=(), anatomy='',
               axes=True):
    dirs = DIRS if dirs is None else dirs
    rec = ''.join(f'<p data-reconcile="{k}">구조적으로는 다르나 스윙 구간에서는…</p>'
                  for k in reconcile)
    name = macro.regime_name(growth, inflation)
    return (
        '<section><h2>7. 전략 코멘트</h2><p>…</p></section>'
        '<section><h2>8. 매크로 논리</h2>'
        f'<p>국면은 <span data-macro="regime" data-growth="{growth}" '
        f'data-inflation="{inflation}">{name}</span>이다. '
        f'성장축 {scores[0]}, 인플레축 {scores[1]}. '
        f'9월 인하 확률은 {prob}%.</p>'
        f'{ax_strip() if axes else ""}'
        f'{strip(dirs)}{rec}{extra}{groups(group_text, skip_groups)}</section>'
        '<section><h2>9. 멀티에셋 매니저 전략</h2></section>'
        f'<section><h2>13. 경제지표 대시보드</h2><table><tr><td>CPI YoY</td></tr></table>'
        f'{anatomy}</section>')


def macro_file(growth=0, inflation=-1, dirs=None, since='2026-08-10',
               date='2026-08-17', timing='2026-09 FOMC', prob=68.0, history=None):
    dirs = DIRS if dirs is None else dirs
    return {
        'report_date': date,
        'horizon': '3-6개월',
        'regime': {'growth': growth, 'inflation': inflation, 'since': since,
                   'thesis': '…'},
        'policy_path': {'stance': 'cut', 'timing': timing, 'prob_pct': prob,
                        'thesis': '…', 'falsifier': '…'},
        'transmission': {a: {'direction': d, 'since': since, 'channel': '…',
                             'confirm': '…'} for a, d in dirs.items()},
        'history': history or [],
        'last_seen': {},
    }


def eval_file(allowed=None, dirs=None, new_releases=('CPI YoY',), growth=0, inflation=-1):
    dirs = DIRS if dirs is None else dirs
    return {
        'report_date': REPORT_DATE,
        'bootstrap': False,
        'new_releases': list(new_releases),
        'allowed_regimes': allowed or [[growth, inflation], [growth - 1, inflation]],
        'regime': {'growth': growth, 'inflation': inflation},
        'scores': {'growth_score': 0.12, 'inflation_score': -0.55},
        'transmission': {a: {'direction': d,
                             'allowed_directions': sorted({d, 0, max(-1, d - 1),
                                                           min(1, d + 1)})}
                         for a, d in dirs.items()},
    }


def next_file(**kw):
    kw.setdefault('date', REPORT_DATE)
    return macro_file(**kw)


# --- location ---------------------------------------------------------------

def test_macro_section_is_located_and_bounded():
    s = section_macro(build_html())
    assert 'data-macro="regime"' in s and '멀티에셋 매니저' not in s


def test_missing_section_is_the_only_violation():
    assert check('<p>없음</p>', macro_file(), eval_file(), next_file()) == \
        ['§8(매크로 논리) 섹션을 찾을 수 없다']


def test_parse_reads_every_transmission_marker():
    cells = parse_transmission_cells(section_macro(build_html()))
    assert set(cells) == set(macro.TRANSMISSION_ASSETS)
    assert cells['bonds']['direction'] == 1


# --- regime -----------------------------------------------------------------

def test_clean_report_passes():
    assert check(build_html(), macro_file(), eval_file(), next_file()) == []


def test_regime_name_must_match_the_grid():
    html = build_html().replace('>골디락스<', '>완만한 디스인플레 국면<')
    assert any('통제 어휘' in x for x in
               check(html, macro_file(), eval_file(), next_file()))


def test_regime_outside_allowed_regimes_is_rejected():
    ev = eval_file(allowed=[[0, -1]])
    html = build_html(growth=-1, inflation=-1)
    nxt = next_file(growth=-1, inflation=-1, since=REPORT_DATE,
                    history=[{'date': REPORT_DATE, 'from': [0, -1], 'to': [-1, -1],
                              'reason': '…'}])
    assert any('허용 범위' in x for x in check(html, macro_file(), ev, nxt))


def test_axis_scores_must_be_quoted_in_the_section():
    html = build_html(scores=('', ''))
    assert any('축 점수' in x for x in
               check(html, macro_file(), eval_file(), next_file()))


# --- transmission -----------------------------------------------------------

def test_missing_transmission_badge_is_flagged():
    dirs = {k: v for k, v in DIRS.items() if k != 'metals'}
    html = build_html(dirs=dirs)
    assert any('metals' in x for x in
               check(html, macro_file(), eval_file(), next_file(dirs=dirs)))


def test_direction_outside_allowed_is_rejected():
    ev = eval_file()
    ev['transmission']['equities']['allowed_directions'] = [0]
    dirs = dict(DIRS, equities=1)
    html = build_html(dirs=dirs)
    nxt = next_file(dirs=dirs, since=REPORT_DATE)
    assert any('equities' in x and '허용' in x for x in check(html, macro_file(), ev, nxt))


def test_transmission_label_must_match_the_controlled_vocabulary():
    html = build_html().replace('>우호<', '>중립~우호<')
    assert any('통제 어휘' in x for x in
               check(html, macro_file(), eval_file(), next_file()))


# --- §9 reconciliation ------------------------------------------------------

def test_conflict_with_the_stance_book_must_be_reconciled_in_prose():
    stance = {'assets': {'bonds': {'grade': -1}}}   # macro 우호(+1) vs 숏 바이어스(-1)
    out = check(build_html(), macro_file(), eval_file(), next_file(), stance)
    assert any('bonds' in x and 'data-reconcile' in x for x in out)


def test_reconciled_conflict_passes():
    stance = {'assets': {'bonds': {'grade': -1}}}
    out = check(build_html(reconcile=['bonds']), macro_file(), eval_file(),
                next_file(), stance)
    assert out == []


def test_agreeing_signs_need_no_reconciliation():
    stance = {'assets': {'bonds': {'grade': 1}, 'fx': {'grade': -1}}}
    assert check(build_html(), macro_file(), eval_file(), next_file(), stance) == []


# --- policy path ------------------------------------------------------------

def test_policy_timing_cannot_move_without_a_release_or_a_probability_jump():
    ev = eval_file(new_releases=())
    nxt = next_file(timing='2026-10 FOMC', prob=70.0)
    html = build_html(prob=70.0)
    assert any('정책 경로' in x for x in check(html, macro_file(), ev, nxt))


def test_policy_timing_may_move_on_a_large_probability_shift():
    ev = eval_file(new_releases=())
    nxt = next_file(timing='2026-10 FOMC', prob=40.0)
    html = build_html(prob=40.0)
    assert check(html, macro_file(), ev, nxt) == []


def test_policy_probability_must_appear_in_the_section():
    html = build_html(prob=68.0).replace('9월 인하 확률은 68.0%.', '9월 인하 우위.')
    assert any('확률' in x for x in check(html, macro_file(), eval_file(), next_file()))


# --- macro_next.json --------------------------------------------------------

def test_missing_next_file_is_fatal():
    assert any('macro_next.json' in x for x in
               check(build_html(), macro_file(), eval_file(), None))


def test_next_file_must_be_dated_today():
    assert any('report_date' in x for x in
               check(build_html(), macro_file(), eval_file(), next_file(date='2026-08-17')))


def test_next_file_regime_must_match_the_section():
    nxt = next_file(growth=-1, inflation=-1, since=REPORT_DATE)
    assert any('§8 표식' in x for x in check(build_html(), macro_file(), eval_file(), nxt))


def test_changed_regime_must_update_since_and_history():
    ev = eval_file(allowed=[[0, -1], [-1, -1]])
    html = build_html(growth=-1, inflation=-1)
    nxt = next_file(growth=-1, inflation=-1, since='2026-08-10')
    out = check(html, macro_file(), ev, nxt)
    assert any('since' in x for x in out)
    assert any('history' in x for x in out)


def test_changed_transmission_direction_must_update_since():
    ev = eval_file()
    dirs = dict(DIRS, energy=1)
    html = build_html(dirs=dirs)
    nxt = next_file(dirs=dirs)     # since left at the old date
    assert any('energy' in x and 'since' in x for x in check(html, macro_file(), ev, nxt))


# --- channel groups ---------------------------------------------------------

def test_every_channel_group_must_be_present():
    out = check(build_html(skip_groups=('dollar',)), macro_file(), eval_file(),
                next_file())
    assert any('dollar' in x for x in out)


def test_group_block_without_a_number_is_flagged():
    text = dict(GROUP_TEXT, rates='실질금리 상단이 눌린다. 추이를 지켜본다.')
    out = check(build_html(group_text=text), macro_file(), eval_file(), next_file())
    assert any('rates' in x and '확인 지표' in x for x in out)


def test_parse_group_blocks_slices_each_channel():
    blocks = parse_group_blocks(section_macro(build_html()))
    assert set(blocks) == {k for k, _, _ in macro.TRANSMISSION_GROUPS}
    assert 'Core PCE' in blocks['rates']
    assert 'Core PCE' not in blocks['demand']


# --- release anatomy --------------------------------------------------------

RELEASES = [{'key': 'cpi', 'label': '소비자물가(CPI)', 'tier': 1, 'agency': 'BLS',
             'url': 'https://www.bls.gov/news.release/cpi.nr0.htm',
             'primary': 'CPI YoY',
             'indicators': [{'name': 'CPI YoY', 'actual': 3.54, 'previous': 3.73,
                             'ref_period': '2026-07-01'}],
             'components': [{'label': '에너지', 'actual': -1.484},
                            {'label': '주거비(shelter)', 'actual': 0.139},
                            {'label': '서비스 ex-에너지', 'actual': 0.228}]}]

ANATOMY = ('<div data-release="cpi"><h4>7월 CPI 3.54%</h4>'
           '<p>헤드라인 3.54%는 전월 3.73%에서 내려왔다. 에너지가 -1.5% 빠지며 끌어내렸고 '
           '주거비는 +0.14%로 여전히 붙어 있다. 출처 BLS.</p></div>')


def rel_eval(releases=None, **kw):
    ev = eval_file(**kw)
    ev['headline_releases'] = RELEASES if releases is None else releases
    return ev


def test_new_release_requires_an_anatomy_block():
    out = check(build_html(), macro_file(), rel_eval(), next_file())
    assert any('cpi' in x for x in out)


def test_anatomy_block_satisfies_the_requirement():
    out = check(build_html(anatomy=ANATOMY), macro_file(), rel_eval(), next_file())
    assert out == []


def test_anatomy_must_quote_the_headline_number():
    block = (ANATOMY.replace('<h4>7월 CPI 3.54%</h4>', '<h4>7월 CPI</h4>')
                    .replace('헤드라인 3.54%는 전월 3.73%에서', '헤드라인은 전월 3.73%에서'))
    out = check(build_html(anatomy=block), macro_file(), rel_eval(), next_file())
    assert any('cpi' in x and '실제값' in x for x in out)


def test_anatomy_must_name_the_primary_source():
    block = ANATOMY.replace(' 출처 BLS.', '')
    out = check(build_html(anatomy=block), macro_file(), rel_eval(), next_file())
    assert any('cpi' in x and '원본 발표' in x for x in out)


def test_headline_number_alone_is_not_anatomy():
    block = ('<div data-release="cpi"><p>7월 CPI는 3.54%로 나왔다. 출처 BLS.</p></div>')
    out = check(build_html(anatomy=block), macro_file(), rel_eval(), next_file())
    assert any("cpi" in x and "구성 항목" in x for x in out)


def test_a_year_is_not_counted_as_a_component_figure():
    rel = dict(RELEASES[0]); rel.pop('components')
    block = ('<div data-release="cpi"><p>2026년 7월 CPI는 3.54%. 출처 BLS.</p></div>')
    out = check(build_html(anatomy=block), macro_file(), rel_eval([rel]), next_file())
    assert any('cpi' in x and '세부' in x for x in out)


def test_a_quiet_day_may_not_carry_a_market_comment_card():
    """2026-08-20 사용자 지시 — 새 발표가 없는 날은 굳이 코멘트를 달지 않는다.

    The 08-19 brief opened its 시장 해석 card with 「오늘은 새로 발표된 헤드라인
    경제지표가 없는 날이었다」 and then talked about something else entirely.
    """
    html = build_html(extra='<div class="card"><h4>시장 해석</h4><p>오늘은 발표가 없었다.</p></div>')
    out = check(html, macro_file(), eval_file(), next_file())
    assert any('시장 해석' in x for x in out)


def test_a_release_day_keeps_its_market_comment_card():
    html = build_html(anatomy=ANATOMY,
                      extra='<div class="card"><h4>시장 해석</h4><p>10년물 -1.8bp.</p></div>')
    assert check(html, macro_file(), rel_eval(), next_file()) == []


def test_the_next_release_calendar_is_welcome_on_a_quiet_day():
    html = build_html(extra='<div class="card"><h4>다음 발표 일정</h4><p>9/16 FOMC.</p></div>')
    assert check(html, macro_file(), eval_file(), next_file()) == []


def test_quiet_day_needs_no_anatomy_block():
    assert check(build_html(), macro_file(), rel_eval(releases=[]), next_file()) == []


def test_anatomy_must_cite_the_components_that_moved():
    """The whole point: a block that names no basket line has not decomposed anything."""
    block = ('<div data-release="cpi"><p>7월 CPI 3.54%는 전월 3.73%에서 0.19%p '
             '내려왔다. 출처 BLS.</p></div>')
    out = check(build_html(anatomy=block), macro_file(), rel_eval(), next_file())
    assert any("cpi" in x and "구성 항목" in x for x in out)


def test_one_component_is_not_enough():
    block = ('<div data-release="cpi"><p>7월 CPI 3.54%. 에너지가 -1.5% 빠졌다. '
             '전월 3.73%. 출처 BLS.</p></div>')
    out = check(build_html(anatomy=block), macro_file(), rel_eval(), next_file())
    assert any("cpi" in x and "구성 항목" in x for x in out)


def test_a_release_without_a_known_breakdown_falls_back_to_the_figure_count():
    rel = dict(RELEASES[0]); rel.pop('components')
    block = ('<div data-release="cpi"><p>CPI 3.54%, 전월 3.73%, MoM 0.07%. 출처 BLS.</p></div>')
    assert check(build_html(anatomy=block), macro_file(), rel_eval([rel]), next_file()) == []


def test_anatomy_in_the_macro_section_is_not_where_it_belongs():
    """It was §8 briefly; the numbers live in §13, so the dissection sits with them."""
    out = check(build_html(extra=ANATOMY), macro_file(), rel_eval(), next_file())
    assert any('cpi' in x and '해부 블록이 없다' in x for x in out)


def test_merged_layout_keeps_the_dissection_with_the_axis_tables():
    """2026-08-20 사용자 지시 — 지표 표가 §8 안으로 들어와 축 진단 바로 아래 붙는다.

    There is no separate 경제지표 대시보드 section any more, so the dissection that used
    to live at the back now sits inside the macro section, still next to its numbers.
    """
    html = build_html(extra=ANATOMY).replace(
        '<section><h2>13. 경제지표 대시보드</h2><table><tr><td>CPI YoY</td></tr></table></section>', '')
    assert '경제지표 대시보드' not in html
    assert check(html, macro_file(), rel_eval(), next_file()) == []


def test_merged_layout_still_demands_the_dissection():
    html = build_html().replace(
        '<section><h2>13. 경제지표 대시보드</h2><table><tr><td>CPI YoY</td></tr></table></section>', '')
    out = check(html, macro_file(), rel_eval(), next_file())
    assert any('cpi' in x and '해부 블록이 없다' in x for x in out)


def test_a_release_block_does_not_swallow_the_following_section():
    block = '<div data-release="cpi"><p>CPI 3.54%. 출처 BLS.</p></div>'
    html = build_html(anatomy=block) + '<section><p>에너지 -1.484 주거비 0.139</p></section>'
    out = check(html, macro_file(), rel_eval(), next_file())
    assert any("cpi" in x and "구성 항목" in x for x in out)


# --- published-surface hygiene ----------------------------------------------

def test_internal_filenames_never_reach_the_page():
    """The 2026-08-17 brief published '…로 보도, research_notes.md)'."""
    html = build_html(extra='<p>동결 확률 68% (research_notes.md)</p>')
    out = check(html, macro_file(), eval_file(), next_file())
    assert any('research_notes.md' in x for x in out)


def test_every_pipeline_artifact_is_covered():
    for name in ('macro_metrics.json', 'stance_eval.json', 'econ_indicators.json',
                 'macro_next.json', 'market_data.json'):
        html = build_html(extra=f'<p>근거는 {name}이다</p>')
        out = check(html, macro_file(), eval_file(), next_file())
        assert any(name in x for x in out), name


def test_z_score_jargon_is_rejected():
    html = build_html(extra='<p>고용은 signed-z 0.895로 축을 끌어올렸다</p>')
    out = check(html, macro_file(), eval_file(), next_file())
    assert any('내부 지표' in x for x in out)


def test_ordinary_prose_is_untouched():
    html = build_html(extra='<p>고용은 구인건수가 개선을 주도했다</p>')
    assert check(html, macro_file(), eval_file(), next_file()) == []


def test_buy_side_label_is_rejected():
    """2026-08-22 사용자 지시 — 발행본에서 「buy-side」를 쓰지 않는다."""
    for word in ('buy-side 종합 해석', 'Buy-side 해석', 'buy side 관점', '바이사이드 시각'):
        html = build_html(extra=f'<p>{word}으로 정리하면</p>')
        out = check(html, macro_file(), eval_file(), next_file())
        assert any('buy-side' in x for x in out), word


def test_strategy_wording_passes():
    html = build_html(extra='<p>전략 코멘트로 정리하면 방어적이다</p>')
    assert check(html, macro_file(), eval_file(), next_file()) == []


def test_hygiene_covers_the_whole_page_not_just_the_macro_section():
    html = build_html() + '<section><p>출처 research_notes.md</p></section>'
    out = check(html, macro_file(), eval_file(), next_file())
    assert any('research_notes.md' in x for x in out)


# --- four-axis strip --------------------------------------------------------

def ax_strip(dirs=('개선', '개선', '악화', '둔화')):
    keys = ('Labor', 'Activity', 'Consumption', 'Inflation')
    items = ''.join(f'<span class="ax-item"><b>{k}</b> '
                    f'<span data-axis="{k}">{d}</span></span>'
                    for k, d in zip(keys, dirs))
    return f'<div class="ax-strip">{items}</div>'


def test_four_axis_strip_is_required():
    out = check(build_html(axes=False), macro_file(), eval_file(), next_file())
    assert any('4축' in x and '스트립' in x for x in out)


def test_four_axis_strip_satisfies_the_check():
    assert check(build_html(), macro_file(), eval_file(), next_file()) == []


def test_a_missing_axis_is_named():
    keys = ('Labor', 'Activity', 'Consumption')
    strip_html = ''.join(f'<span data-axis="{k}">개선</span>' for k in keys)
    out = check(build_html(axes=False, extra=strip_html), macro_file(), eval_file(),
                next_file())
    assert any('Inflation' in x for x in out)
