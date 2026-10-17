"""US 주간 인사이트 — 진단 계산과 조립 계약."""
from datetime import date, timedelta

import pytest

from us import weekly_insight as I


def _weekly(n, start=100.0, swing=1.0, last_day='2026-09-18'):
    """직전 n주: ±swing% 를 번갈아 — 표준편차가 swing 근처가 되게."""
    end = date.fromisoformat(last_day)
    rows, v = [], start
    for i in range(n):
        d = end - timedelta(weeks=n - 1 - i)
        v *= 1 + (swing if i % 2 else -swing) / 100
        rows.append([d.isoformat(), round(v, 4)])
    return rows


def _agg(**over):
    agg = {'key': '2026-W39', 'start_date': '2026-09-21', 'end_date': '2026-09-25',
           'indices': {'S&P 500': {'start': 100, 'end': 100.5, 'pct': 0.5}},
           'fx': {'USD/KRW': {'start': 1340, 'end': 1385, 'pct': 3.35}},
           'sectors': {}, 'commodities': {},
           'yields': {'2Y': {'start': 4.6, 'end': 4.7, 'chg_bp': 10.0},
                      '10Y': {'start': 5.0, 'end': 5.02, 'chg_bp': 2.0}},
           'curve': {}, 'daily': []}
    agg.update(over)
    return agg


def _snap():
    return {'prices': {'S&P 500': {'weekly': _weekly(60)}, 'USD/KRW': {'weekly': _weekly(60)}},
            'fred': {}, 'fetch_status': {}}


def test_anomaly_is_scaled_by_the_assets_own_weekly_volatility():
    rows = I.anomalies(_agg(), _snap())
    by = {r['name']: r for r in rows}
    assert by['USD/KRW']['flagged'] and not by['S&P 500']['flagged']
    assert rows[0]['name'] == 'USD/KRW'      # |z| 내림차순


def test_anomaly_baseline_excludes_the_current_week():
    snap = _snap()
    # 이번 주(9/25) 종가가 스냅샷에 섞여 있어도 기준선은 9/21 이전 주만 쓴다.
    snap['prices']['USD/KRW']['weekly'].append(['2026-09-25', 999.0])
    z1 = {r['name']: r['z'] for r in I.anomalies(_agg(), snap)}['USD/KRW']
    z0 = {r['name']: r['z'] for r in I.anomalies(_agg(), _snap())}['USD/KRW']
    assert z1 == z0


def test_anomaly_without_enough_history_is_not_scored():
    snap = _snap()
    snap['prices']['USD/KRW']['weekly'] = _weekly(10)
    names = {r['name'] for r in I.anomalies(_agg(), snap)}
    assert 'USD/KRW' not in names


def test_yield_anomaly_uses_bp_changes_of_fred_weekly_closes():
    fred = []
    d = date(2025, 9, 1)
    v = 4.0
    for i in range(400):
        day = d + timedelta(days=i)
        if day.weekday() < 5:
            v += 0.01 if (i // 7) % 2 else -0.01
            fred.append([day.isoformat(), round(v, 3)])
    snap = {'prices': {}, 'fred': {'DGS2': fred}, 'fetch_status': {}}
    row = {r['name']: r for r in I.anomalies(_agg(), snap)}['2Y']
    assert row['unit'] == 'bp' and row['move'] == 10.0 and row['z'] > 0


@pytest.mark.parametrize('d2,d10,label', [
    (9.9, 2.1, '베어 플래트닝'), (2.0, 9.0, '베어 스티프닝'),
    (-9.0, -2.0, '불 스티프닝'), (-2.0, -9.0, '불 플래트닝'),
    (5.0, -4.0, '트위스트 플래트닝'), (-5.0, 4.0, '트위스트 스티프닝'),
    (1.0, -2.0, '보합'),
    # 기울기 변화가 2bp 안이면 모양 이름을 붙이지 않는다 — W41 의 2년 -3.4bp·10년 -3.3bp 는
    # 「불 스티프닝」으로 인쇄됐지만 2s10s 는 0.1bp 움직였다(2년물은 T-1 FRED 라 날짜 잡음 안이다).
    (-3.4, -3.3, '평행 하락'), (4.0, 5.5, '평행 상승'), (-9.0, -7.0, '불 스티프닝'),
])
def test_curve_regime_names_the_shape_of_the_move(d2, d10, label):
    assert I.curve_regime(d2, d10) == label


def test_positioning_reports_net_change_and_three_year_percentile():
    rows = [{'date': f'2026-{1 + i // 28:02d}-{1 + i % 28:02d}', 'lev_long': 100 + i,
             'lev_short': 100, 'am_long': 0, 'am_short': 0, 'oi': 1000} for i in range(30)]
    snap = {'cftc': {'097741': {'label': '엔 선물', 'rows': rows}}}
    out = I.positioning(snap, '2026-12-31')[0]
    assert out['lev_net'] == 29 and out['lev_net_chg'] == 1 and out['pct_3y'] == 100


def test_positioning_ignores_reports_after_the_week():
    rows = [{'date': '2026-09-15', 'lev_long': 10, 'lev_short': 0},
            {'date': '2026-09-29', 'lev_long': 99, 'lev_short': 0}]
    snap = {'cftc': {'097741': {'label': '엔 선물', 'rows': rows}}}
    assert I.positioning(snap, '2026-09-25')[0]['date'] == '2026-09-15'


def test_fed_path_prices_each_month_against_effr_in_bp():
    snap = {'fred': {'EFFR': [['2026-09-24', 3.88], ['2026-09-25', 3.88]]},
            'fedfunds': [{'month': '2026-09', 'implied': 3.7475, 'price': 96.2525, 'week_ago': 96.25},
                         {'month': '2026-11', 'implied': 4.035, 'price': 95.965, 'week_ago': 95.95}]}
    out = I.fed_path(snap, '2026-09-25', ['2026-10-28', '2026-12-09'])
    nov = next(c for c in out['contracts'] if c['month'] == '2026-11')
    assert out['effr'] == 3.88 and nov['bp_vs_effr'] == 15.5 and nov['chg_1w_bp'] == -1.5
    assert out['next_meeting'] == '2026-10-28'
    # 이미 지난 달(9월물)은 다음 경로가 아니다.
    assert [c['month'] for c in out['contracts']] == ['2026-11']


def test_next_week_keeps_releases_and_coupons_but_drops_bills():
    cal = {'events': [
        {'date': '2026-09-29', 'kind': 'release', 'name_ko': 'JOLTS 구인·이직'},
        {'date': '2026-09-29', 'kind': 'auction', 'name_ko': '52-Week 국채 입찰 540억 달러'},
        {'date': '2026-09-30', 'kind': 'auction', 'name_ko': '7-Year 국채 입찰 440억 달러'},
        {'date': '2026-10-09', 'kind': 'release', 'name_ko': 'CPI'},
        {'date': '2026-09-25', 'kind': 'release', 'name_ko': '미시간대'}]}
    names = [e['name_ko'] for e in I.next_week(cal, '2026-09-25')]
    assert names == ['JOLTS 구인·이직', '7-Year 국채 입찰 440억 달러']


def _body(**drop):
    parts = {
        'head': '<section class="card headline-card"><h1>제목</h1><p>리드.</p></section>',
        'question': '<section data-section="question"><h2>이번 주의 질문</h2><p>본문.</p>'
                    '<p data-alt>대안.</p><p data-watch>가를 관측.</p></section>',
        'diag': '<section data-section="diag"><h2>크로스에셋 진단</h2><!--T:anomalies-->'
                '<!--T:regime--><p>해설.</p></section>',
        'positioning': '<section data-section="positioning"><h2>포지셔닝과 기대</h2>'
                       '<!--T:positioning--><!--T:fed--><p>해설.</p></section>',
        'review': '<section data-section="review"><h2>판단 복기</h2><p>복기.</p></section>',
        'next': '<section data-section="next"><h2>다음 주에 가를 것</h2><!--T:next-->'
                '<p>조건.</p></section>',
        'appendix': '<section data-section="appendix"><h2>부록</h2><!--T:performance-->'
                    '<!--T:daily--></section>',
    }
    for k in drop:
        parts.pop(k)
    return ''.join(parts.values())


def test_assemble_fills_every_placeholder_and_declares_the_desk_register():
    diag = I.build(_agg(), _snap(), {'events': []}, [])
    html = I.assemble(_body(), {'title': 'T', 'summary': 'S'}, diag, _agg())
    assert '<!--T:' not in html
    assert 'data-register="da"' in html and 'data-layout="prose"' in html


def test_validate_names_a_missing_section_and_a_missing_placeholder():
    errs = I.validate_body(_body(review=True).replace('<!--T:fed-->', ''))
    assert any('review' in e for e in errs) and any('T:fed' in e for e in errs)


def test_validate_rejects_sections_out_of_order():
    body = _body()
    q = body[body.index('<section data-section="question"'):body.index('<section data-section="diag"')]
    swapped = body.replace(q, '').replace('<section data-section="next"', q + '<section data-section="next"')
    assert any('순서' in e for e in I.validate_body(swapped))


def test_rates_are_coloured_from_the_bond_side():
    # 2026-09-26 사용자: 「금리가 오른 건 채권 가격 입장에서는 마이너스」.
    assert I._c(15.2, 'bp', 1, invert=True) == '<span class="neg">+15.2bp</span>'
    assert I._c(-3.0, 'bp', 1, invert=True) == '<span class="pos">-3.0bp</span>'
    assert I._c(1.57, '%') == '<span class="pos">+1.57%</span>'
    assert I._c(0.0, 'bp', 1, invert=True) == '+0.0bp'


def test_only_tables_are_coloured_not_the_prose():
    diag = I.build(_agg(), _snap(), {'events': []}, [])
    body = _body().replace('<p>본문.</p>', '<p>금리가 +15.2bp 올랐다.</p>')
    html = I.assemble(body, {'title': 'T', 'summary': 'S'}, diag, _agg())
    assert '<p>금리가 +15.2bp 올랐다.</p>' in html
    perf = html[html.index('미 국채 금리'):]
    assert '<span class="neg">+10.0bp</span>' in perf     # 2년물 +10bp → 채권 쪽에서 손실


def test_baseline_cuts_by_iso_week_not_by_date():
    # codex #9: 집계가 화요일에 시작하는 휴일 주, 그 주 월요일 값이 기준선에 섞이던 길.
    rows = [['2026-09-11', 100.0], ['2026-09-18', 101.0], ['2026-09-21', 150.0]]
    assert I._baseline(rows, '2026-09-22') == pytest.approx([1.0])


def test_daily_record_marks_a_gap_instead_of_calling_it_the_previous_day():
    agg = _agg(start_date='2026-09-14', end_date='2026-09-18',
               series={'equities': [['2026-09-11', 100.0], ['2026-09-14', 101.0], ['2026-09-17', 102.0]]})
    rec = {r['date']: r for r in I.daily_record(agg)}
    assert 'since' not in rec['2026-09-14']['S&P 500']
    assert rec['2026-09-17']['S&P 500']['since'] == '2026-09-14'


def test_a_ratio_just_under_the_flag_is_not_flagged_by_rounding():
    """필수소비재 3.60% ÷ 1.82% = 1.978 — 반올림하면 2.0 이지만 문턱은 넘지 않았다(W41)."""
    a = I._anom('Consumer Staples', 'sectors', 3.60, '%', 1.82)
    assert not a['flagged']
    assert a['z'] == 1.98          # 표시값이 판정과 어긋나지 않게 두 자리
    b = I._anom('Utilities', 'sectors', 3.97, '%', 2.32)
    assert b['z'] == 1.7 and not b['flagged']
    c = I._anom('USD/KRW', 'fx', 4.0, '%', 2.0)
    assert c['z'] == 2.0 and c['flagged']


def test_the_anomaly_table_says_ratio_not_z_score():
    diag = {'z_flag': 2.0, 'anomalies': [I._anom('Consumer Staples', 'sectors', 3.60, '%', 1.82)]}
    html = I._t_anomalies(diag)
    assert '배수(z)' not in html and '평소 대비 배수' in html
    assert '+1.98' in html and '평균은 빼지 않았다' in html


def test_the_curve_row_prints_the_2s10s_change():
    agg = _agg(yields={'2Y': {'chg_bp': -3.4}, '10Y': {'chg_bp': -3.3}})
    r = I.regime(agg, {'prices': {}, 'fred': {}})
    assert r['curve'] == '평행 하락'
    html = I._t_regime({'regime': r})
    assert '2s10s +0.1bp' in html


# ── 다음 주 표: 발행본이 예고한 일정과 걸린 판단 (2026-10-17) ──────────────────

_NW = [{'date': '2026-10-15', 'time_kst': '2026-10-15 21:30', 'kind': 'release',
        'name_ko': '생산자물가(PPI)', 'watch': '추세 확인'}]


def test_next_events_annotate_a_calendar_row_and_add_a_post_row():
    rows, errs = I.merge_next(_NW, [
        {'date': '2026-10-15', 'name': '생산자물가', 'watch': '물가 압력 지속', 'stake': '정책금리 전망'},
        {'date': '2026-10-15', 'name': 'TSMC 3분기 실적', 'watch': 'AI 수요 가이던스', 'stake': 'AI 수익화 기대'}],
        '2026-10-09')
    assert errs == []
    ppi = next(r for r in rows if r['name_ko'].startswith('생산자물가'))
    assert ppi['watch'] == '물가 압력 지속' and ppi['stake'] == '정책금리 전망' and ppi['source'] == 'calendar'
    tsmc = next(r for r in rows if r['name_ko'].startswith('TSMC'))
    assert tsmc['source'] == 'post' and tsmc['kind'] == 'post'


def test_next_events_refuse_numbers_in_writer_cells_and_dates_outside_the_window():
    _, errs = I.merge_next(_NW, [
        {'date': '2026-10-15', 'name': 'TSMC 실적', 'watch': '가이던스 446억~458억 달러', 'stake': 'AI'},
        {'date': '2026-10-26', 'name': '베라이즌 실적', 'watch': '가이던스', 'stake': '통신'},
        {'date': '2026-10-14', 'name': '', 'watch': 'x', 'stake': 'y'}], '2026-10-09')
    assert len(errs) == 3


def test_the_next_table_shows_what_judgment_each_event_carries():
    rows, _ = I.merge_next(_NW, [{'date': '2026-10-15', 'name': 'TSMC 3분기 실적',
                                  'watch': 'AI 수요 가이던스', 'stake': 'AI 수익화 기대'}], '2026-10-09')
    html = I._t_next({'next_week': _NW, 'next_table': rows})
    assert I._t_next({'next_week': _NW, 'end_date': '2026-10-09', 'next_events': [
        {'date': '2026-10-15', 'name': 'TSMC 3분기 실적', 'watch': 'AI 수요 가이던스',
         'stake': 'AI 수익화 기대'}]}) == html
    assert '걸린 판단' in html and 'TSMC 3분기 실적' in html and 'AI 수익화 기대' in html
    assert '발행본 예고' in html


def test_without_next_events_the_table_is_the_calendar():
    html = I._t_next({'next_week': _NW})
    assert '생산자물가(PPI)' in html and '추세 확인' in html


def test_the_next_table_dates_a_row_by_its_kst_day():
    # 13:00 ET 입찰은 다음 날 02:00 KST 다. 날짜 칸이 미국 날짜면 시각(KST)과 하루 어긋난다(W40).
    nw = [{'date': '2026-10-06', 'time_kst': '2026-10-07 02:00', 'kind': 'auction',
           'name_ko': '3-Year 국채 입찰 580억 달러', 'watch': '응찰배율과 간접 낙찰 비중'}]
    html = I._t_next({'next_week': nw})
    assert '<td>2026-10-07</td><td>02:00</td>' in html
    assert '2026-10-06' not in html


def test_the_basket_label_counts_its_members():
    # 메모리 바스켓은 6종목인데 라벨이 「5종목」으로 고정돼 있었다(W39~W41).
    names = ['Micron', 'Western Digital', 'Seagate', 'Nvidia', 'Samsung Elec', 'SK hynix']
    mem = {n: {'pct': 1.0} for n in names}
    mem.update(basket_pct=1.0, basket_excess_pct=0.5)
    ai = {n: {'pct': 1.0} for n in ['Marvell', 'Coherent', 'Lumentum', 'GE Vernova', 'Vertiv']}
    ai.update(basket_pct=2.0, basket_excess_pct=1.5)
    html = I._t_performance(_agg(memory=mem, ai_infra=ai))
    assert '메모리 6종목 바스켓' in html and 'AI 인프라 5종목 바스켓' in html
