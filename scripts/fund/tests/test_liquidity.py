import pytest

from fund import liquidity as liq

WEDS = ['2026-08-05', '2026-08-12', '2026-08-19', '2026-08-26',
        '2026-09-02', '2026-09-09', '2026-09-16', '2026-09-23']


def weekly(start_val, step, dates=WEDS):
    return [(d, start_val + step * i) for i, d in enumerate(dates)]


def base(**over):
    s = {
        'WALCL': weekly(6_800_000, -10_000),      # millions
        'WDTGAL': weekly(800_000, 5_000),          # millions, Wednesday level
        'RRPONTSYD': [('2026-08-25', 9.0), ('2026-08-26', 10.0),
                      ('2026-09-22', 2.0), ('2026-09-23', 1.0)],   # billions
        'NFCI': weekly(-0.50, 0.01, ['2026-08-07', '2026-08-14', '2026-08-21', '2026-08-28',
                                     '2026-09-04', '2026-09-11', '2026-09-18', '2026-09-25']),
    }
    s.update(over)
    return s


def test_net_liquidity_units_dates_and_components():
    out = liq.build(base())
    net = out['net']
    # 6,730,000m - 835,000m - 1b -> 6730 - 835 - 1 = 5894 bn
    assert net['date'] == '2026-09-23'
    assert net['level_bn'] == pytest.approx(5894.0)
    assert net['comparison_date'] == '2026-08-26'
    # 6770 - 815 - 10 = 5945
    assert net['chg_4w_bn'] == pytest.approx(5894.0 - 5945.0)
    comp = net['components']
    assert comp['walcl'] == {'date': '2026-09-23', 'value_m': 6_730_000}
    assert comp['tga'] == {'date': '2026-09-23', 'value_m': 835_000}
    assert comp['rrp'] == {'date': '2026-09-23', 'value_bn': 1.0}


def test_nfci_and_signals_and_direction():
    out = liq.build(base())
    assert out['nfci']['level'] == pytest.approx(-0.43)
    assert out['nfci']['comparison_date'] == '2026-08-28'
    assert out['nfci']['chg_4w'] == pytest.approx(0.04)
    # net falling (-1), NFCI rising = tighter (-1)
    assert out['signals'] == {'net': -1, 'nfci': -1}
    assert out['direction'] == '긴축'
    assert out['nfci']['looser_than_average'] is True


def test_direction_neutral_when_signals_disagree():
    s = base(WALCL=weekly(6_800_000, 10_000), WDTGAL=weekly(800_000, 0),
             RRPONTSYD=[('2026-08-26', 5.0), ('2026-09-23', 5.0)])
    out = liq.build(s)
    assert out['signals'] == {'net': 1, 'nfci': -1}
    assert out['direction'] == '중립'


def test_direction_easing():
    s = base(WALCL=weekly(6_800_000, 10_000), WDTGAL=weekly(800_000, 0),
             RRPONTSYD=[('2026-08-26', 5.0), ('2026-09-23', 5.0)],
             NFCI=weekly(-0.40, -0.01))
    assert liq.build(s)['direction'] == '완화'


def test_tga_must_match_the_wednesday_not_fall_back():
    s = base(WDTGAL=weekly(800_000, 5_000)[:-1])   # no 09-23 TGA
    out = liq.build(s)
    assert out['net'] is None
    assert out['direction'] is None
    assert out['signals']['net'] is None


def test_missing_series_degrades_not_invents():
    out = liq.build({'NFCI': weekly(-0.5, 0.01)})
    assert out['net'] is None
    assert out['nfci']['level'] == pytest.approx(-0.43)
    assert out['direction'] is None
    assert liq.build({}) is None


def test_nan_nfci_is_missing_not_a_direction():
    nan = float('nan')
    s = base(WALCL=weekly(6_800_000, 10_000), WDTGAL=weekly(800_000, 0),
             RRPONTSYD=[('2026-08-26', 5.0), ('2026-09-23', 5.0)],
             NFCI=[(d, nan) for d, _ in weekly(0, 0)])
    out = liq.build(s)
    assert out['nfci'] is None
    assert out['signals']['nfci'] is None and out['direction'] is None


def test_signals_use_raw_change_not_rounded():
    # +0.04 bn over four weeks rounds to 0.0 for display but is still a rise
    s = base(WALCL=[(d, 6_800_000 + (40 if i == 7 else 0)) for i, (d, _) in enumerate(weekly(0, 0))],
             WDTGAL=weekly(800_000, 0),
             RRPONTSYD=[('2026-08-26', 5.0), ('2026-09-23', 5.0)],
             NFCI=weekly(-0.40, -0.0001))
    out = liq.build(s)
    assert out['net']['chg_4w_bn'] == 0.0
    assert out['signals'] == {'net': 1, 'nfci': 1}
    assert out['direction'] == '완화'


def test_four_week_change_is_date_anchored_not_positional():
    fri = ['2026-08-21', '2026-08-28', '2026-09-04', '2026-09-11', '2026-09-18', '2026-09-25']
    vals = [-1.0, 0.0, -0.3, -0.4, float('nan'), -0.5]
    s = base(NFCI=list(zip(fri, vals)))
    out = liq.build(s)
    assert out['nfci']['comparison_date'] == '2026-08-28'
    assert out['nfci']['chg_4w'] == pytest.approx(-0.5)
    assert out['signals']['nfci'] == 1


def test_missing_comparison_week_gives_no_change():
    fri = ['2026-08-21', '2026-09-04', '2026-09-11', '2026-09-18', '2026-09-25']
    s = base(NFCI=list(zip(fri, [-1.0, -0.3, -0.4, -0.45, -0.5])))
    out = liq.build(s)
    assert out['nfci']['chg_4w'] is None and out['signals']['nfci'] is None
    assert out['direction'] is None
