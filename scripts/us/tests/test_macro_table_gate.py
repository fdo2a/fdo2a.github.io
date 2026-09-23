from us import macro_metrics as mm
from us.macro_table_gate import check_tables

REPORT = '2026-09-23'

ECON = [
    {'axis': 'Activity', 'name': 'Durable Goods Orders MoM', 'actual': 1.08, 'previous': 0.58,
     'units': '%', 'transform': 'mom_pct'},
    {'axis': 'Labor', 'name': 'Initial Jobless Claims', 'actual': 196000.0,
     'previous': 206000.0, 'units': '', 'transform': 'level'},
]

TREND = {'Durable Goods Orders MoM': '악화(뚜렷) · 3개월 평균 +2.89% → -0.78%',
         'Initial Jobless Claims': None}


def metrics(report_date=REPORT, schema=mm.SCHEMA, trend=None):
    trend = TREND if trend is None else trend
    return {'report_date': report_date, 'schema': schema,
            'indicators': [{'name': n, 'trend_cell_ko': t} for n, t in trend.items()]}


HEAD = ('<thead><tr><th>지표</th><th>Actual</th><th>Forecast</th><th>Previous</th>'
        '<th>발표일</th><th>컨센 대비</th><th>직전 대비</th><th>추세</th></tr></thead>')


def row(name, label, actual, previous, vs, trend, marked=True):
    tr = f'<tr data-indicator="{name}">' if marked else '<tr>'
    return (f'{tr}<td>{label}</td><td>{actual}</td><td>—</td><td>{previous}</td>'
            f'<td>2026-07 기준월</td><td></td><td data-vs-prev>{vs}</td>'
            f'<td data-trend>{trend}</td></tr>')


DURABLE = row('Durable Goods Orders MoM', '내구재주문 MoM(7월)', '+1.08%', '+0.58%', '개선',
              '악화(뚜렷) · 3개월 평균 +2.89% → -0.78%')
CLAIMS = row('Initial Jobless Claims', '신규 실업수당 청구', '196K', '206K', '개선', '—')
NOTE = f'<p class="caption" data-trend-note>{mm.TREND_NOTE_KO}</p>'


def page(rows=(DURABLE, CLAIMS), note=NOTE, head=HEAD):
    return f'<table>{head}<tbody>{"".join(rows)}</tbody></table>{note}'


def run(html, m=None, econ=ECON, report_date=REPORT):
    return check_tables(html, econ, metrics() if m is None else m, report_date)


def test_clean_tables_pass():
    assert run(page()) == []


def test_vs_prev_must_match_the_printed_pair():
    bad = DURABLE.replace('<td data-vs-prev>개선', '<td data-vs-prev>악화')
    assert any('직전 대비' in v for v in run(page((bad, CLAIMS))))


def test_trend_must_match_the_computed_cell():
    bad = DURABLE.replace('악화(뚜렷)', '악화(완만)')
    assert any('추세' in v for v in run(page((bad, CLAIMS))))


def test_trend_is_dash_when_metrics_are_stale():
    stale = metrics(report_date='2026-09-21')
    assert any('추세' in v for v in run(page(), m=stale))
    dashed = DURABLE.replace('악화(뚜렷) · 3개월 평균 +2.89% → -0.78%', '—')
    assert run(page((dashed, CLAIMS)), m=stale) == []


def test_old_schema_metrics_are_not_trusted():
    assert any('추세' in v for v in run(page(), m=metrics(schema=1)))


def test_vs_prev_is_still_checked_without_metrics():
    dashed = DURABLE.replace('악화(뚜렷) · 3개월 평균 +2.89% → -0.78%', '—')
    bad = dashed.replace('<td data-vs-prev>개선', '<td data-vs-prev>악화')
    assert any('직전 대비' in v for v in run(page((bad, CLAIMS)), m={}))


def test_every_indicator_needs_exactly_one_marked_row():
    assert any('Initial Jobless Claims' in v for v in run(page((DURABLE,))))
    assert any('두 번' in v for v in run(page((DURABLE, DURABLE, CLAIMS))))


def test_unknown_marker_is_rejected():
    ghost = row('Ghost', '유령', '1', '0', '개선', '—')
    assert any('Ghost' in v for v in run(page((DURABLE, CLAIMS, ghost))))


def test_swapped_actual_and_previous_are_caught():
    bad = DURABLE.replace('<td>+1.08%</td><td>—</td><td>+0.58%</td>',
                          '<td>+0.58%</td><td>—</td><td>+1.08%</td>')
    assert any('Actual' in v for v in run(page((bad, CLAIMS))))


def test_scaled_units_and_rounding_are_accepted():
    econ = ECON + [{'axis': 'Activity', 'name': 'Existing Home Sales', 'actual': 3980000.0,
                    'previous': 4060000.0, 'units': '', 'transform': 'level'}]
    homes = row('Existing Home Sales', '기존주택판매', '398.0만', '406.0만', '악화', '—')
    m = metrics(trend=dict(TREND, **{'Existing Home Sales': None}))
    assert run(page((DURABLE, CLAIMS, homes)), m=m, econ=econ) == []


def test_research_rows_leave_both_columns_blank():
    ism = ('<tr><td>ISM 제조업</td><td>49.1</td><td>49.5</td><td>48.7</td><td>9/2</td>'
           '<td>하회▼</td><td>—</td><td>—</td></tr>')
    assert run(page((DURABLE, CLAIMS, ism))) == []
    # 표식 없는 행에 판정을 적으면 정본 행을 우회한 판정이 된다.
    sneaky = ism.replace('<td>—</td><td>—</td></tr>', '<td>개선</td><td>—</td></tr>')
    assert any('표식 없는 행' in v for v in run(page((DURABLE, CLAIMS, sneaky))))


def test_cells_must_sit_under_their_headers():
    swapped = HEAD.replace('<th>직전 대비</th><th>추세</th>', '<th>추세</th><th>직전 대비</th>')
    assert any('열' in v for v in run(page(head=swapped)))


def test_caption_is_required_and_must_be_verbatim():
    assert any('data-trend-note' in v for v in run(page(note='')))
    loose = '<p class="caption" data-trend-note>최근 흐름입니다.</p>'
    assert any('data-trend-note' in v for v in run(page(note=loose)))


def test_no_econ_file_means_nothing_to_check():
    assert run(page(), econ=None) == []


def test_minus_sign_and_whitespace_are_normalised():
    fancy = DURABLE.replace('-0.78%', '−0.78%').replace(' · ', '  ·  ')
    assert run(page((fancy, CLAIMS))) == []


# ---- 구현 검토(2026-09-23) 반영 ----

NFP = {'axis': 'Labor', 'name': 'Nonfarm Payrolls (chg)', 'actual': 162.0, 'previous': 21.0,
       'units': 'K', 'transform': 'mom_diff'}


def nfp_run(actual, previous='+21K'):
    econ = ECON + [NFP]
    m = metrics(trend=dict(TREND, **{'Nonfarm Payrolls (chg)': None}))
    r = row('Nonfarm Payrolls (chg)', '비농업 고용', actual, previous, '개선', '—')
    return run(page((DURABLE, CLAIMS, r)), m=m, econ=econ)


def test_posts_before_the_cutover_are_not_checked():
    # 검토 러너가 옛 발행본에 오늘 게이트를 다시 돌린다 — 소급하면 전부 막힌다.
    assert run('<table><tbody><tr><td>x</td></tr></tbody></table>', report_date='2026-09-22') == []


def test_unit_suffixes_are_read():
    assert nfp_run('+162K') == []
    assert nfp_run('+16.2만 명', '+2.1만 명') == []
    assert nfp_run('+0.162M', '+0.021M') == []


def test_a_wrong_scale_is_caught():
    assert any('Actual' in v for v in nfp_run('+162만 명'))
    assert any('Actual' in v for v in nfp_run('+162M'))


def test_html_entities_are_decoded():
    fancy = DURABLE.replace('<td>+0.58%</td>', '<td>&#43;0.58%</td>').replace(' → ', '&nbsp;&rarr;&nbsp;')
    assert run(page((fancy, CLAIMS))) == []
    minus = DURABLE.replace('<td>+0.58%</td>', '<td>&minus;0.58%</td>')
    assert any('Previous' in v for v in run(page((minus, CLAIMS))))


def test_a_leading_period_label_is_not_the_value():
    lab = DURABLE.replace('<td>+1.08%</td>', '<td>(7월) +1.08%</td>')
    assert run(page((lab, CLAIMS))) == []


def test_row_header_cells_count_as_columns():
    th = DURABLE.replace('<td>내구재주문 MoM(7월)</td>', '<th scope="row">내구재주문 MoM(7월)</th>')
    assert run(page((th, CLAIMS))) == []


def test_header_spelling_variants_are_recognised():
    head = HEAD.replace('<th>직전 대비</th>', '<th>직전대비<sup>*</sup></th>')
    assert run(page(head=head)) == []


def test_marked_rows_accept_any_dash():
    alt = CLAIMS.replace('<td data-trend>—</td>', '<td data-trend>-</td>')
    assert run(page((DURABLE, alt))) == []


def test_an_indicator_table_without_the_new_columns_is_rejected():
    old = ('<table><thead><tr><th>지표</th><th>Actual</th><th>Previous</th><th>판정</th></tr>'
           '</thead><tbody><tr><td>내구재</td><td>1.08%</td><td>0.58%</td><td>악화</td></tr>'
           '</tbody></table>')
    assert any('열이 없다' in v for v in run(page() + old))


def test_row_headers_do_not_pollute_the_header_row():
    th = DURABLE.replace('<td>내구재주문 MoM(7월)</td>', '<th scope="row">추세</th>')
    assert run(page((th, CLAIMS))) == []
