"""일본 일간 v2 — 표·생성 문장 조립·본문 구조 거부·일정 캡션 (설계 §4·§7·§11-1·§11-6·§11-7)."""
import copy

from japan import daily_calendar as CAL
from japan import daily_render as R
from japan.tests import jpx_fixture as F
from japan.tests.test_daily_facts import P, S, index_from, snap as facts_snap

ALL_MISSING = [n for _, n in CAL.REQUIRED]


def v2(**over):
    d = facts_snap()
    d.update({'cut': '16:30', 'complete': True, 'fetch_status': {}, 'jgb_recollect': False,
              'movers': {'report_date': S, 'groups': []}, 'stocks': [],
              'call_rate': {'value': 0.727, 'period': '2026-11-17', 'unit': '%'},
              'fx': {'usdjpy': {'value': 155.2, 'chg_pct': 0.1, 'label': 'USD/JPY', 'bar_end': f'{S}T16:30:00+09:00'}},
              'macro': [], 'macro_periods': {},
              'calendar': {'version': 'x', 'today': [], 'event_day': [], 'upcoming': [],
                           'coverage': {'today_missing': [], 'upcoming_missing': []}}})
    d['indices']['nikkei'].update(source='Nikkei Inc. official close', why=None)
    d.update(over)
    return d


def body(order=R.SECTIONS, extra=None):
    extra = extra or {}
    parts = ['<section class="card headline-card"><h1>제목</h1><p>요약.</p></section>']
    for s in order:
        gens = ''.join(f'<!--G:{g}-->' for g in R.GEN_PLACEHOLDERS.get(s, ()))
        tables = ''.join(f'<!--T:{t}-->' for t in R.PLACEHOLDERS.get(s, ()))
        parts.append(f'<section class="card" data-section="{s}"><h2>{R.TITLES[s]}</h2>{gens}'
                     f'<p>본문.</p>{extra.get(s, "")}{tables}</section>')
    return '\n'.join(parts)


def test_tables_follow_facts_and_direction():
    t = R.render_tables(v2())
    assert '<td>TOPIX</td><td>3,824.00</td><td><span class="neg">-0.42%</span></td>' in t['indices']
    assert 'ETF' not in t['indices'] and '1306' not in t['indices']
    assert t['sectors'].count('<tr>') == 18 and '<td>전기·정밀</td><td>539.97</td>' in t['sectors']
    assert '<td>2~10년 스프레드</td><td>100.9bp</td><td>-0.1bp</td>' in t['jgb']
    assert '<td>10~30년 스프레드</td><td>118.6bp</td><td>+2.5bp</td>' in t['jgb']


def test_tiny_drop_table_sign_and_colour_follow_direction():
    day = dict(F.D1118, Topix=('3,840.01', '-0.01', '-0.00'))
    d = v2()
    d['facts'] = facts_snap(index_from(day, F.D1117))['facts']
    assert '<td>TOPIX</td><td>3,840.01</td><td><span class="neg">-0.00%</span></td>' in R.render_tables(d)['indices']


def test_invalid_blocks_render_dash_and_no_sector_table():
    idx = index_from(F.D1118, F.D1117)
    idx['topix'] = {'status': 'invalid', 'why': 'x'}
    idx['sectors'] = {'status': 'invalid', 'why': 'x'}
    d = v2()
    d['facts'] = facts_snap(idx)['facts']
    t = R.render_tables(d)
    assert '<td>TOPIX</td><td>—</td><td>—</td>' in t['indices'] and t['sectors'] == ''


def test_stale_curve_change_dash():
    from japan.tests.test_daily_facts import JGB
    jgb = {k: dict(r, period=P, prev_period='2026-11-16', source='mof') for k, r in JGB.items()}
    d = v2()
    d.update(facts_snap(jgb=jgb), **{k: v2()[k] for k in ('calendar', 'fx', 'call_rate', 'macro', 'movers')})
    t = R.render_tables(d)['jgb']
    assert '<td>2~10년 스프레드</td><td>100.9bp</td><td>—</td>' in t


def test_assemble_places_generated_sentences():
    d = v2()
    html = R.assemble(body(), {'title': '제목', 'summary': '요약'}, d)
    assert html.count('data-gen="topix"') == 1 and html.count('data-gen="curve"') == 1
    assert '<p data-gen="topix">TOPIX는 3,824.00으로 전 거래일보다 0.42% 내렸다.' in html
    assert 'TOPIX·업종지수는 일본거래소그룹(JPX)' in html and '업종·종목·환율' not in html


def test_valid_v2_body_passes():
    assert R.validate_body(body(), R.SECTIONS, schema=2) == []


def _errs(b):
    return R.validate_body(b, R.SECTIONS, schema=2)


def test_hidden_div_placeholder_rejected():
    b = body().replace('<!--G:topix-->', '<div hidden><!--G:topix--></div>')
    assert any('hidden' in e for e in _errs(b)) and any('바로 아래 자식' in e for e in _errs(b))


def test_style_display_none_rejected():
    b = body().replace('<!--G:curve-->', '<div style="display:none"><!--G:curve--></div>')
    assert any('style=' in e for e in _errs(b))


def test_placeholder_inside_details_rejected():
    b = body().replace('<!--G:sectors-->', '<details><!--G:sectors--></details>')
    assert any('<!--G:sectors-->' in e for e in _errs(b))


def test_section_wrapped_in_details_rejected():
    b = body().replace('<section class="card" data-section="equity">',
                       '<details><summary>주식</summary><section class="card" data-section="equity">', 1)
    b = b.replace('</section>\n<section class="card" data-section="bonds">',
                  '</section></details>\n<section class="card" data-section="bonds">', 1)
    errs = _errs(b)
    assert any('맨 바깥에 <details>' in e for e in errs)


def test_data_gen_in_body_rejected():
    b = body(extra={'equity': '<p data-gen="topix">TOPIX는 9,999.99로 올랐다.</p>'})
    assert any('data-gen' in e for e in _errs(b))


def test_section_tag_must_be_exact():
    b = body().replace('<section class="card" data-section="bonds">', '<section class="card x" data-section="bonds">')
    assert any('<!--G:curve-->' in e for e in _errs(b))


def test_missing_or_duplicate_generated_placeholder_rejected():
    assert any('<!--G:topix--> 가 0번' in e for e in _errs(body().replace('<!--G:topix-->', '')))
    assert any('<!--G:curve--> 가 2번' in e for e in _errs(body().replace('<!--G:curve-->', '<!--G:curve--><!--G:curve-->')))


def test_old_schema_body_rules_unchanged():
    """옛 스냅샷은 G 자리 없이도 통과한다(옛 본문 계약)."""
    from japan.tests.test_daily_render import body as old_body
    assert R.validate_body(old_body(), R.SECTIONS) == []


# ── 일정 캡션 (§7·§11-7) ────────────────────────────────────────────────

def _cal(today=(), upcoming=(), today_missing=(), upcoming_missing=()):
    return {'version': 'x', 'today': list(today), 'event_day': [], 'upcoming': list(upcoming),
            'coverage': {'today_missing': list(today_missing), 'upcoming_missing': list(upcoming_missing)}}


def test_absence_caption_only_when_everything_covered():
    t = R.render_tables(v2(calendar=_cal()))
    assert t['macro'] == '<p class="caption">확인해 둔 발표 일정표(필수 16개 계열)에 오늘 잡힌 일본 지표가 없다.</p>'
    assert '앞으로 2주 안에 잡힌 일본 지표가 없다' in t['next']


def test_unconfirmed_series_no_absence_caption():
    t = R.render_tables(v2(calendar=_cal(today_missing=['무역통계', '기계수주'], upcoming_missing=['무역통계'])))
    assert t['macro'] == '<p class="caption">발표 일정표 미확인 계열: 무역통계·기계수주.</p>'
    assert t['next'] == '<p class="caption">앞으로 2주 발표 일정표 미확인 계열: 무역통계.</p>'
    assert '없다' not in t['macro'] + t['next']


def test_today_row_present_no_absence_caption():
    item = {'name_ko': '전국 소비자물가지수(10월)', 'series': None, 'status': 'event', 'period': None, 'value': None}
    d = v2(macro=[item], calendar=_cal(today=[{'date': S, 'kind': 'release', 'name_ko': '전국 CPI'}]))
    t = R.render_tables(d)['macro']
    assert '<td>일정</td>' in t and '없다' not in t


def test_meeting_only_day():
    d = v2(calendar=_cal(today=[{'date': S, 'kind': 'meeting', 'name_ko': 'BOJ 금융정책결정회의(12월 17-18일)'}]))
    assert R.render_tables(d)['macro'] == ('<p class="caption">오늘 일정표에는 회의 일정만 있다: '
                                           'BOJ 금융정책결정회의(12월 17-18일).</p>')


def test_coverage_missing_from_snapshot_treated_as_all_unconfirmed():
    d = v2(calendar={'version': 'x', 'today': [], 'event_day': [], 'upcoming': []})
    assert '없다' not in R.render_tables(d)['macro']


def test_old_snapshot_keeps_old_caption():
    from japan.tests.test_daily_render import SNAP
    old = copy.deepcopy(SNAP)
    old['calendar']['upcoming'] = []
    assert R.render_tables(old)['next'] == ('<p class="caption">확인해 둔 발표 일정표에는 앞으로 2주 안에 잡힌 '
                                            '일본 지표가 없다.</p>')
