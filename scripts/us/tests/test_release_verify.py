"""Release identity check — real documents in, verdict out (2026-11-06).

Fixtures are trimmed copies of what `fetch_releases.py` actually got: the committed
`data/releases/*.txt` of 2026-11-05 and the BEA / NAR / UMich pages fetched on 11-06.
"""
import os

import pytest

from us.release_verify import verify

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'releases')


def _read(name):
    with open(os.path.join(FX, name), encoding='utf-8') as fh:
        return fh.read()


def rel(key, primary, *rows):
    return {'key': key, 'primary': primary,
            'indicators': [{'name': n, 'actual': a, 'ref_period': p} for n, a, p in rows]}


GOOD = [
    ('cpi.txt', rel('cpi', 'CPI MoM', ('CPI MoM', 0.6, '2026-09-01'))),
    ('ppi.txt', rel('ppi', 'PPI Final Demand MoM', ('PPI Final Demand MoM', 1.3, '2026-09-01'))),
    ('claims.txt', rel('claims', 'Initial Jobless Claims', ('Initial Jobless Claims', 189000.0, '2026-10-31'))),
    ('employment.txt', rel('employment', 'Unemployment Rate', ('Unemployment Rate', 4.2, '2026-09-01'))),
    ('jolts.txt', rel('jolts', 'JOLTS Job Openings', ('JOLTS Job Openings', 7523.0, '2026-09-01'))),
    ('durable-goods.txt', rel('durable-goods', 'Durable Goods Orders MoM',
                              ('Durable Goods Orders MoM', 1.8, '2026-09-01'))),
    ('new-home-sales.txt', rel('new-home-sales', 'New Home Sales', ('New Home Sales', 676.0, '2026-09-01'))),
    ('retail-sales.txt', rel('retail-sales', 'Retail Sales MoM', ('Retail Sales MoM', 0.77, '2026-09-01'))),
    ('industrial-production.txt', rel('industrial-production', 'Industrial Production MoM',
                                      ('Industrial Production MoM', 0.0, '2026-08-01'))),
    ('gdp-full.txt', rel('gdp', 'Real GDP Growth QoQ (ann.)', ('Real GDP Growth QoQ (ann.)', 3.4, '2026-07-01'))),
    ('pce-full.txt', rel('pce', 'PCE Price Index YoY', ('PCE Price Index YoY', 3.65, '2026-09-01'))),
    ('existing-home-sales-full.txt', rel('existing-home-sales', 'Existing Home Sales',
                                         ('Existing Home Sales', 3990000.0, '2026-09-01'))),
    ('michigan-home.txt', rel('michigan', 'Michigan Consumer Sentiment',
                              ('Michigan Consumer Sentiment', 48.0, '2026-10-01'))),
]


@pytest.mark.parametrize('name,release', GOOD, ids=[g[0] for g in GOOD])
def test_the_release_of_this_print_verifies(name, release):
    got = verify(_read(name), release)
    assert got['ok'], got


def test_bea_navigation_is_not_a_release():
    # The committed pce.txt of 2026-10-30: 3,259 bytes of menu, ok:true under the old rule.
    got = verify(_read('pce.txt'), rel('pce', 'PCE Price Index YoY', ('PCE Price Index YoY', 3.65, '2026-09-01')))
    assert not got['ok'] and got['note'] == 'identity_not_found'


def test_the_gdp_landing_summary_is_not_the_release():
    # Old gdp.txt came off the evergreen page: one summary paragraph — the sentence is
    # there, so identity passes; what it lacks is everything after it. The resolver,
    # not this check, is what moves GDP to the dated release.
    got = verify(_read('gdp.txt'), rel('gdp', 'Real GDP Growth QoQ (ann.)', ('Real GDP Growth QoQ (ann.)', 3.4, '2026-07-01')))
    assert got['ok']


def test_last_months_release_fails_on_period():
    got = verify(_read('cpi.txt'), rel('cpi', 'CPI MoM', ('CPI MoM', 0.6, '2026-10-01')))
    assert not got['ok'] and got['note'] == 'period_mismatch'


def test_last_weeks_claims_fail_on_period():
    got = verify(_read('claims.txt'), rel('claims', 'Initial Jobless Claims',
                                          ('Initial Jobless Claims', 189000.0, '2026-10-24')))
    assert got['note'] == 'period_mismatch'


def test_a_wrong_headline_value_fails():
    got = verify(_read('cpi.txt'), rel('cpi', 'CPI MoM', ('CPI MoM', 0.4, '2026-09-01')))
    assert not got['ok'] and got['note'] == 'value_mismatch'


def test_michigan_page_a_month_ahead_of_fred_fails():
    # FRED still carried September (48.1) while the home page showed October final.
    got = verify(_read('michigan-home.txt'), rel('michigan', 'Michigan Consumer Sentiment',
                                                 ('Michigan Consumer Sentiment', 48.1, '2026-09-01')))
    assert not got['ok'] and got['note'] == 'period_mismatch'


def test_claims_primary_without_its_own_sentence_dates_off_the_release():
    # 4-week average promoted alone: no lede sentence of its own, the document is dated
    # by any row of the release and primary_checked stays False.
    got = verify(_read('claims.txt'), rel('claims', 'Initial Claims 4-wk MA',
                                          ('Initial Claims 4-wk MA', 205000.0, '2026-10-31')))
    assert got['ok'] and not got['primary_checked']


def test_primary_checked_when_its_sentence_carries_the_value():
    got = verify(_read('pce-full.txt'), rel('pce', 'PCE Price Index YoY', ('PCE Price Index YoY', 3.65, '2026-09-01')))
    assert got['primary_checked']
    got = verify(_read('pce-full.txt'), rel('pce', 'Core PCE YoY',
                                            ('PCE Price Index YoY', 3.65, '2026-09-01'), ('Core PCE YoY', 3.12, '2026-09-01')))
    assert got['ok'] and got['primary_checked']


def test_unknown_release_key_fails_closed():
    assert verify('anything', {'key': 'nope', 'indicators': []})['note'] == 'no_spec'


def test_a_number_inside_a_bigger_one_is_not_the_value():
    text = ('The Consumer Price Index for All Urban Consumers (CPI-U) increased 10.6 percent on a '
            'seasonally adjusted basis in September, 2026 release')
    assert verify(text, rel('cpi', 'CPI MoM', ('CPI MoM', 0.6, '2026-09-01')))['note'] == 'value_mismatch'


# --- codex 구현 검토 2026-11-06 #2·#3·#4 ------------------------------------------

def test_the_verb_must_carry_the_sign_of_the_print():
    # 「increased 0.6 percent」 is not a -0.6 print.
    got = verify(_read('cpi.txt'), rel('cpi', 'CPI MoM', ('CPI MoM', -0.6, '2026-09-01')))
    assert got['note'] == 'value_mismatch'


def test_only_the_indicators_own_unit_scale_is_allowed():
    # 600 is 0.6 x 1000 — CPI percent has no thousands scale.
    got = verify(_read('cpi.txt'), rel('cpi', 'CPI MoM', ('CPI MoM', 600, '2026-09-01')))
    assert got['note'] == 'value_mismatch'
    # JOLTS really is thousands on FRED vs millions in the lede.
    assert verify(_read('jolts.txt'), rel('jolts', 'JOLTS Job Openings',
                                          ('JOLTS Job Openings', 7523.0, '2026-09-01')))['ok']


def test_another_years_release_fails_on_the_year():
    # The realistic failure: last year's document (it never mentions this year) served
    # for this year's print. A month-only lede is dated by the year the document names.
    lede = ('The Consumer Price Index for All Urban Consumers (CPI-U) increased 0.6 percent on a '
            'seasonally adjusted basis in September after rising 0.4 percent in August. '
            'Sep. 2024 Aug. 2025 Sep. 2025')
    got = verify(lede, rel('cpi', 'CPI MoM', ('CPI MoM', 0.6, '2026-09-01')))
    assert got['note'] == 'period_mismatch'
    assert verify(lede, rel('cpi', 'CPI MoM', ('CPI MoM', 0.6, '2025-09-01')))['ok']
    claims = ('In the week ending October 31, the advance figure for seasonally adjusted initial '
              'claims was 189,000. October 31, 2025')
    got = verify(claims, rel('claims', 'Initial Jobless Claims', ('Initial Jobless Claims', 189000.0, '2026-10-31')))
    assert got['note'] == 'period_mismatch'


def test_a_primary_whose_own_sentence_disagrees_fails():
    got = verify(_read('pce-full.txt'), rel('pce', 'Core PCE YoY',
                                            ('PCE Price Index YoY', 3.65, '2026-09-01'),
                                            ('Core PCE YoY', 99.9, '2026-09-01')))
    assert not got['ok'] and got['note'] == 'primary_value_mismatch'


def test_was_unchanged_is_a_zero_print():
    got = verify(_read('industrial-production.txt'), rel('industrial-production', 'Industrial Production MoM',
                                                          ('Industrial Production MoM', 0.0, '2026-08-01')))
    assert got['ok']


def test_unchanged_is_not_any_value():
    text = 'Industrial production was unchanged in August. 2026'
    got = verify(text, rel('industrial-production', 'Industrial Production MoM',
                           ('Industrial Production MoM', 9.0, '2026-08-01')))
    assert got['note'] == 'value_mismatch'


# ------------------------------------------------- 2026-11-08 (A단계) additions

import os as _os

_AFX = _os.path.join(_os.path.dirname(__file__), 'fixtures', 'anatomy')


def _afx(key):
    with open(_os.path.join(_AFX, f'{key}.txt'), encoding='utf-8') as fh:
        return fh.read()


def _rel(key, primary, *inds):
    return {'key': key, 'primary': primary,
            'indicators': [{'name': n, 'actual': a, 'ref_period': r} for n, a, r in inds]}


EMP = (('Nonfarm Payrolls (chg)', 165.0, '2026-10-01'), ('Unemployment Rate', 4.1, '2026-10-01'),
       ('Avg Hourly Earnings MoM', 0.37, '2026-10-01'))


def test_employment_headline_values_are_checked_whichever_is_primary():
    for name, _, _ in EMP:
        out = verify(_afx('employment'), _rel('employment', name, *EMP))
        assert out['ok'] and out['primary_checked'], name


def test_a_wrong_payroll_figure_is_a_wrong_round():
    inds = (('Nonfarm Payrolls (chg)', 120.0, '2026-10-01'),) + EMP[1:]
    out = verify(_afx('employment'), _rel('employment', 'Nonfarm Payrolls (chg)', *inds))
    assert out['ok'] is False and out['note'] == 'primary_value_mismatch'


@pytest.mark.parametrize('key,name,actual,ok', [
    ('housing-starts', 'Housing Starts', 1221.0, True),
    ('housing-starts', 'Housing Starts', 1288.0, False),
    ('trade-balance', 'Trade Balance', -105.05, True),
    ('trade-balance', 'Trade Balance', 105.05, False),       # a deficit is negative
    ('construction-spending', 'Construction Spending MoM', -1.85, True),
    ('construction-spending', 'Construction Spending MoM', 1.85, False),
    ('factory-orders', 'Factory Orders MoM', 1.84, True),
    ('factory-orders', 'Factory Orders MoM', 0.3, False),
])
def test_census_identity_sentences_check_the_value_and_its_sign(key, name, actual, ok):
    out = verify(_afx(key), _rel(key, name, (name, actual, '2026-09-01')))
    assert out['identity'] and out['period']
    assert out['ok'] is ok
    if ok:
        assert out['value'] is True


def test_a_census_release_of_another_month_is_refused():
    out = verify(_afx('housing-starts'), _rel('housing-starts', 'Housing Starts',
                                              ('Housing Starts', 1221.0, '2026-08-01')))
    assert out['ok'] is False and out['note'] == 'period_mismatch'


# Philadelphia Fed — a paraphrased sentence in the bank's shape, not its text.
PHILLY = ('Manufacturing Business Outlook Survey March 2026 Report. The diffusion index for '
          'current general activity fell for a third month, sliding from 4.4 in February to '
          '-3.4 in March.')


@pytest.mark.parametrize('actual,ok', [(-3.4, True), (3.4, False), (4.4, False)])
def test_philly_identity_keeps_the_sign_of_a_negative_index(actual, ok):
    name = 'Philly Fed Manufacturing'
    out = verify(PHILLY, _rel('philly-fed', name, (name, actual, '2026-03-01')))
    assert out['ok'] is ok
