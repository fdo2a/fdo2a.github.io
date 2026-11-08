"""주간 레짐 점검 — 새 발표 원장을 기간 전체로 읽어 성장·물가를 따로 채점한다.

2026-11-08 전까지는 아무도 쓰지 않는 `released` 필드로 발표를 골라 W40 이후 매주
「신규 발표 없음」이었다. 옛 테스트도 실제 데이터에 없는 모양으로 만들어져 통과했다.
"""

from us.period_scorecard import regime_check

START, END = '2026-11-02', '2026-11-06'
WEEK = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06']
HOL = {'us': {'dates': ['2026-11-26'], 'valid_through': '2027-12-31'}}

LABOR = ['Nonfarm Payrolls (chg)', 'Initial Jobless Claims']
INFL = ['CPI YoY']
ALL = [(n, 'Labor') for n in LABOR] + [(n, 'Inflation') for n in INFL]


def scan(day, names=ALL, baseline=False, run='r'):
    return {'id': f'scan|{day}|{run}', 'kind': 'scan', 'report_date': day, 'run_id': run,
            'baseline': baseline, 'observed': [[n, a, 'scored'] for n, a in names]}


def rel(name, ref, trend, detected, axis='Labor', official=None, since=None, role='scored',
        gap=False, kind='release'):
    return {'id': f'{name}|{ref}', 'kind': kind, 'name': name, 'label_ko': name, 'axis': axis,
            'role': role, 'ref_period': ref, 'actual': 1.0, 'trend': trend,
            'detected_on': detected, 'since': since, 'official_date': official, 'gap': gap}


def week(*prints, days=WEEK, names=ALL):
    return [scan(d, names) for d in days] + list(prints)


def book(day, growth, inflation=0):
    return {'report_date': day, 'regime': {'growth': growth, 'inflation': inflation}}


BOOK_UP = [book('2026-10-30', 1, 1)]


def rc(ledger, macro=BOOK_UP, hol=HOL):
    return regime_check(macro, ledger, START, END, hol)


# ---- 보통의 한 주 -------------------------------------------------------------

def test_growth_prints_are_scored_against_the_growth_book():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                rel('Initial Jobless Claims', '2026-10-31', '개선', '2026-11-05', official='2026-11-05'),
                rel('Initial Jobless Claims', '2026-10-24', '악화', '2026-11-02', official='2026-11-02')))
    g = r['growth']
    assert g['verdict'] == '정합'
    assert (g['total'], g['scored'], g['agree'], g['against'], g['flat']) == (3, 3, 2, 1, 0)
    assert g['pct'] == 67
    assert r['inflation']['verdict'] == '판정불가'
    assert r['verdict'] == '정합' and r['partial'] is True


def test_inflation_prints_use_the_inflation_book_and_vocabulary():
    r = rc(week(rel('CPI YoY', '2026-10-01', '둔화', '2026-11-04', axis='Inflation',
                    official='2026-11-04')))
    i = r['inflation']
    assert i['verdict'] == '불일치' and (i['agree'], i['against']) == (0, 1)
    assert r['growth']['verdict'] == '판정불가'


def test_half_is_agreement_and_flat_counts_against_the_book():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                rel('Initial Jobless Claims', '2026-10-31', '보합', '2026-11-05', official='2026-11-05')))
    g = r['growth']
    assert (g['agree'], g['flat'], g['ratio']) == (1, 1, 0.5)
    assert g['verdict'] == '정합'
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                rel('Initial Jobless Claims', '2026-10-31', '보합', '2026-11-05', official='2026-11-05'),
                rel('Initial Jobless Claims', '2026-10-24', '보합', '2026-11-02', official='2026-11-02')))
    assert r['growth']['verdict'] == '불일치'


def test_mixed_axes_give_a_split_top_level_verdict():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                rel('CPI YoY', '2026-10-01', '둔화', '2026-11-04', axis='Inflation', official='2026-11-04')))
    assert r['verdict'] == '엇갈림' and r['partial'] is False


def test_prints_carry_no_values():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')))
    assert r['prints'] == [{'name': 'Nonfarm Payrolls (chg)', 'label_ko': 'Nonfarm Payrolls (chg)',
                            'axis': 'Labor', 'ref_period': '2026-10-01', 'date': '2026-11-06',
                            'trend': '개선'}]


# ---- 책 ----------------------------------------------------------------------

def test_each_print_meets_the_book_of_the_day_before():
    """발표를 보고 바꾼 그날의 책으로 그 발표를 채점하면 늘 맞는다."""
    macro = [book('2026-10-30', -1), book('2026-11-06', 1)]
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')),
           macro=macro)
    assert r['growth']['verdict'] == '불일치'


def test_a_neutral_book_reports_the_lean_instead_of_a_verdict():
    macro = [book('2026-10-30', 0, 0)]
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                rel('Initial Jobless Claims', '2026-10-31', '개선', '2026-11-05', official='2026-11-05'),
                rel('Initial Jobless Claims', '2026-10-24', '보합', '2026-11-02', official='2026-11-02')),
           macro=macro)
    g = r['growth']
    assert g['verdict'] == '기준 보합'
    assert g['lean'] == {'up': 2, 'down': 0, 'flat': 1}
    assert g['scored'] == 0 and g['neutral_book'] == 3
    assert r['verdict'] == '기준 보합'


def test_a_missing_book_is_not_a_neutral_book():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')),
           macro=[])
    assert r['growth']['verdict'] == '판정불가' and r['growth']['no_book'] == 1


def test_a_missing_book_beside_a_neutral_one_blocks_the_neutral_verdict():
    macro = [book('2026-11-03', 0)]
    r = rc(week(rel('Initial Jobless Claims', '2026-10-24', '개선', '2026-11-02', official='2026-11-02'),
                rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')),
           macro=macro)
    assert r['growth']['verdict'] == '판정불가'
    assert (r['growth']['no_book'], r['growth']['neutral_book']) == (1, 1)


def test_an_unknown_trend_word_is_counted_not_scored():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', None, '2026-11-06', official='2026-11-06'),
                rel('Initial Jobless Claims', '2026-10-31', '개선', '2026-11-05', official='2026-11-05')))
    g = r['growth']
    assert g['no_trend'] == 1 and g['scored'] == 1 and g['verdict'] == '정합'


def test_the_book_is_cut_at_the_period_end():
    macro = [book('2026-10-30', 1), book('2026-11-09', -1)]
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')),
           macro=macro)
    assert r['regime']['growth'] == 1


# ---- 날짜 --------------------------------------------------------------------

def test_without_an_official_date_a_window_inside_the_week_counts():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', since='2026-11-05')))
    assert r['growth']['verdict'] == '정합'
    assert r['prints'][0]['date'] is None


def test_a_window_that_straddles_the_week_start_is_uncertain():
    r = rc(week(rel('Initial Jobless Claims', '2026-10-24', '개선', '2026-11-02', since='2026-10-30')))
    g = r['growth']
    assert g['verdict'] == '판정불가' and g['uncertain'] == ['Initial Jobless Claims']


def test_an_official_date_outside_the_week_is_left_out():
    r = rc(week(rel('Initial Jobless Claims', '2026-10-24', '개선', '2026-11-02', official='2026-10-30'),
                rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')))
    assert r['growth']['total'] == 1


def test_a_book_change_inside_the_window_is_uncertain():
    macro = [book('2026-10-30', 1), book('2026-11-03', -1)]
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', since='2026-11-02')),
           macro=macro)
    assert r['growth']['verdict'] == '판정불가'


def test_a_gap_touching_the_week_is_uncertain():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-11-01', '개선', '2026-11-06', since='2026-11-05',
                    gap=True)))
    assert r['growth']['verdict'] == '판정불가'


def test_rows_detected_after_the_week_are_ignored():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-09', official='2026-11-06'))
           + [scan('2026-11-09')])
    assert r['growth']['total'] == 0


# ---- 무엇을 세지 않나 ----------------------------------------------------------

def test_revisions_baselines_and_anatomy_rows_are_not_scored():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '악화', '2026-11-03', kind='revision'),
                rel('Initial Jobless Claims', '2026-10-31', '악화', '2026-11-05', official='2026-11-05',
                    role='anatomy')))
    assert r['growth']['total'] == 0 and r['growth']['verdict'] == '판정불가'


def test_a_name_first_seen_this_week_is_excluded_and_named():
    names = ALL + [('Housing Starts', 'Activity')]
    ledger = ([scan('2026-11-02', ALL)] + [scan(d, names) for d in WEEK[1:]]
              + [rel('Housing Starts', '2026-09-01', '개선', '2026-11-03', axis='Activity',
                     kind='baseline'),
                 rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06')])
    r = rc(ledger)
    assert r['excluded_new'] == ['Housing Starts']
    assert r['growth']['verdict'] == '정합'


# ---- 수집 누락 -----------------------------------------------------------------

def test_a_missing_day_makes_the_whole_check_undecidable():
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                days=[d for d in WEEK if d != '2026-11-04']))
    assert r['verdict'] == '판정불가' and r['missing_days'] == ['2026-11-04']
    assert r['growth']['verdict'] == '판정불가'


def test_a_baseline_scan_does_not_count_as_collection():
    ledger = [scan('2026-11-02', baseline=True)] + [scan(d) for d in WEEK[1:]]
    assert rc(ledger)['missing_days'] == ['2026-11-02']


def test_an_indicator_not_seen_by_the_last_day_makes_its_axis_undecidable():
    names = [(n, a) for n, a in ALL if n != 'Nonfarm Payrolls (chg)']
    ledger = [scan(d) for d in WEEK[:-1]] + [scan('2026-11-06', names)]
    ledger.append(rel('CPI YoY', '2026-10-01', '재가속', '2026-11-04', axis='Inflation',
                      official='2026-11-04'))
    r = rc(ledger)
    assert r['growth']['verdict'] == '판정불가'
    assert r['growth']['stale'] == ['Nonfarm Payrolls (chg)']
    assert r['inflation']['verdict'] == '정합'


def test_a_bond_only_holiday_is_still_a_collection_day():
    hol = {'us': {'dates': [], 'valid_through': '2027-12-31'},
           'us_bond': {'dates': ['2026-11-11']}}
    r = regime_check(BOOK_UP, [scan(d) for d in ['2026-11-09', '2026-11-10', '2026-11-12', '2026-11-13']],
                     '2026-11-09', '2026-11-13', hol)
    assert r['missing_days'] == ['2026-11-11']


def test_an_exchange_holiday_is_not_expected():
    hol = {'us': {'dates': ['2026-11-04'], 'valid_through': '2027-12-31'}}
    r = rc(week(days=[d for d in WEEK if d != '2026-11-04']), hol=hol)
    assert r['missing_days'] == [] and r['days_expected'] == 4


def test_missing_or_expired_holidays_are_undecidable():
    assert rc(week(), hol=None)['verdict'] == '판정불가'
    expired = {'us': {'dates': [], 'valid_through': '2026-11-05'}}
    assert rc(week(), hol=expired)['verdict'] == '판정불가'


def test_no_ledger_at_all_is_undecidable():
    r = rc([])
    assert r['verdict'] == '판정불가' and len(r['missing_days']) == 5


def test_a_scored_indicator_without_a_known_axis_blocks_both_axes():
    names = ALL + [('Mystery', None)]
    r = rc(week(rel('Nonfarm Payrolls (chg)', '2026-10-01', '개선', '2026-11-06', official='2026-11-06'),
                names=names))
    assert r['unknown_axis'] == ['Mystery']
    assert r['growth']['verdict'] == '판정불가' and r['inflation']['verdict'] == '판정불가'


def test_a_holiday_file_without_a_date_list_is_undecidable():
    assert rc(week(), hol={'us': {'valid_through': '2027-12-31'}})['verdict'] == '판정불가'
    assert rc(week(), hol={'us': {'valid_through': '2027-12-31', 'dates': ['bad']}})['verdict'] == '판정불가'


def test_an_indicator_missing_the_whole_week_is_still_caught():
    names = [(n, a) for n, a in ALL if n != 'Nonfarm Payrolls (chg)']
    ledger = [scan('2026-10-30')] + [scan(d, names) for d in WEEK]
    r = rc(ledger)
    assert r['growth']['verdict'] == '판정불가'
    assert r['growth']['stale'] == ['Nonfarm Payrolls (chg)']


def test_an_indicator_missing_for_two_weeks_is_still_caught():
    names = [(n, a) for n, a in ALL if n != 'Nonfarm Payrolls (chg)']
    prior = ['2026-10-23', '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30']
    ledger = [scan('2026-10-23')] + [scan(d, names) for d in prior[1:]] + [scan(d, names) for d in WEEK]
    r = rc(ledger)
    assert r['growth']['stale'] == ['Nonfarm Payrolls (chg)']


def test_an_indicator_gone_longer_than_the_retire_window_is_dropped():
    names = [(n, a) for n, a in ALL if n != 'Nonfarm Payrolls (chg)']
    ledger = [scan('2026-09-01')] + [scan(d, names) for d in WEEK]
    r = rc(ledger)
    assert r['growth']['stale'] == []


def test_a_scan_that_observed_nothing_is_not_a_collection_day():
    ledger = [scan(d) for d in WEEK[:-1]] + [scan('2026-11-06', names=[])]
    assert rc(ledger)['missing_days'] == ['2026-11-06']
