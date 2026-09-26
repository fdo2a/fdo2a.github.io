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
