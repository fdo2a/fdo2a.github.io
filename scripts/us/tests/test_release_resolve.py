import datetime
import os

from us.release_resolve import bea_from_rss, nar_from_page, normalize_link, same_site

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'releases')


def _read(name):
    with open(os.path.join(FX, name), encoding='utf-8') as fh:
        return fh.read()


def test_bea_feed_gives_the_dated_pio_release():
    html, pdf, pub = bea_from_rss(_read('bea_rss.xml'), ('Personal Income and Outlays',),
                                  datetime.date(2026, 10, 30))
    assert html == 'https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026'
    assert pdf.endswith('/2026-10/pi0926.pdf') and pub == datetime.date(2026, 10, 29)


def test_bea_feed_gdp_by_title_prefix_not_the_name_attribute():
    html, _, _ = bea_from_rss(_read('bea_rss.xml'), ('GDP', 'Gross Domestic Product'),
                              datetime.date(2026, 10, 30))
    assert html.endswith('/gdp-advance-estimate-3rd-quarter-2026')


def test_a_stale_feed_item_is_not_this_round():
    # A month later the September PIO is no longer "today's" release.
    assert bea_from_rss(_read('bea_rss.xml'), ('Personal Income and Outlays',),
                        datetime.date(2026, 11, 30)) == (None, None, None)


def test_feed_item_dated_after_today_is_ignored():
    assert bea_from_rss(_read('bea_rss.xml'), ('Personal Income and Outlays',),
                        datetime.date(2026, 10, 28))[0] is None


def test_links_without_scheme_are_normalised():
    assert normalize_link('www.bea.gov/news/x') == 'https://www.bea.gov/news/x'
    assert normalize_link('https://bea.gov/news/x') == 'https://bea.gov/news/x'
    assert normalize_link('/news/x') == 'https://www.bea.gov/news/x'


def test_same_site_is_the_registrable_domain():
    assert same_site('https://apps.bea.gov/rss', 'https://www.bea.gov/news/x')
    assert not same_site('https://www.bea.gov/x', 'https://evil.example/bea.gov')


def test_nar_page_link_is_followed():
    url = nar_from_page(_read('nar_data.html'))
    assert url == ('https://www.nar.realtor/newsroom/'
                   'existing-home-sales-increased-1-5-in-september-according-to-nar-report')


def test_nar_page_without_the_link_resolves_to_nothing():
    assert nar_from_page('<html><a href="/x">Other</a></html>') is None


def test_philly_report_url_is_built_from_the_reference_month():
    from us import release_resolve as rr
    assert rr.philly_url('2026-10-01') == ('https://www.philadelphiafed.org/surveys-and-data/'
                                           'regional-economic-analysis/mbos-2026-10')
    assert rr.philly_url(None) is None
    assert rr.RESOLVERS['philly-fed'][0] == 'philly_month'
