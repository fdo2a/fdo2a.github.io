import pytest

from china import releases as R

NBS_INDEX = '''
<a href="./202609/t20260901_1965170.html">2.Purchasing Managers&rsquo; Index for August 2026</a>
<a href="./202608/t20260810_1965018.html">14.Consumer Price Index in July 2026</a>
<a href="./202608/t20260810_1965017.html">15.Industrial Producer Price Indexes in July 2026</a>
<a href="./202608/t20260818_1965071.html">6.Industrial Production Operation in July 2026</a>
<a href="https://www.stats.gov.cn/english/nbs/200701/t20070104_59235.html">About NBS</a>
'''


# ── 인덱스 파싱 ──

def test_discovers_known_release_kinds():
    got = {r['kind']: r for r in R.parse_nbs_index(NBS_INDEX)}
    assert set(got) == {'nbs-pmi', 'nbs-cpi', 'nbs-ppi', 'nbs-ip'}


def test_reference_period_comes_from_the_title_not_the_url():
    """URL 의 202608 은 발표월이고, 담긴 데이터는 7월분이다. 섞으면 한 달이 밀린다."""
    cpi = [r for r in R.parse_nbs_index(NBS_INDEX) if r['kind'] == 'nbs-cpi'][0]
    assert cpi['period'] == '2026-07'
    assert cpi['published'] == '2026-08-10'


def test_key_is_kind_plus_reference_period():
    cpi = [r for r in R.parse_nbs_index(NBS_INDEX) if r['kind'] == 'nbs-cpi'][0]
    assert cpi['key'] == 'nbs-cpi-2026-07'


def test_urls_are_absolute():
    for r in R.parse_nbs_index(NBS_INDEX):
        assert r['url'].startswith('https://')


def test_non_release_links_are_ignored():
    assert not any('About NBS' in r['title'] for r in R.parse_nbs_index(NBS_INDEX))


def test_quarterly_and_unknown_titles_do_not_crash():
    R.parse_nbs_index('<a href="./202609/t20260901_1.html">Something Else Entirely</a>')


# ── 본문 추출 ──

def test_text_extraction_strips_tags_and_chrome():
    html = ('<html><head><title>t</title></head><body><script>x</script>'
            '<div>In July 2026, China&rsquo;s CPI increased by 0.5% year on year.</div>'
            '</body></html>')
    txt = R.extract_text(html)
    assert 'CPI increased by 0.5%' in txt and 'script' not in txt


def test_text_extraction_keeps_chinese():
    assert '同比上涨' in R.extract_text('<p>居民消费价格同比上涨0.5%</p>')


# ── 원장 (C5) ──

VALID_CPI_BODY = ("Consumer Price Index in July 2026. In July 2026, China's Consumer "
                  "Price Index (CPI) increased by 0.5% year on year. " * 4)


def test_ledger_records_failure_rather_than_dropping_it():
    idx = R.ledger([{'key': 'k', 'kind': 'nbs-cpi', 'period': '2026-07', 'tier': 1,
                     'url': 'u', 'title': 't', 'published': '2026-08-10'}],
                   fetched={}, errors={'k': (403, 'forbidden')})
    row = idx['releases'][0]
    assert row['discovered'] is True
    assert row['fetch_status'] == 'failed'
    assert row['http_status'] == 403


def test_ledger_records_success_with_a_content_hash():
    idx = R.ledger([{'key': 'k', 'kind': 'nbs-cpi', 'period': '2026-07', 'tier': 1,
                     'url': 'u', 'title': 't', 'published': '2026-08-10'}],
                   fetched={'k': (VALID_CPI_BODY, 'en')}, errors={})
    row = idx['releases'][0]
    assert row['fetch_status'] == 'ok' and row['http_status'] == 200
    assert len(row['content_hash']) == 64 and row['language'] == 'en'


def test_english_supersedes_a_previously_stored_chinese_dump():
    """영문이 늦게 뜬다고 seen 으로 버리면 영영 중문만 남는다(codex C5)."""
    prev = {'releases': [{'key': 'k', 'language': 'zh', 'fetch_status': 'ok',
                          'content_hash': 'abc', 'tier': 1, 'discovered': True}]}
    assert R.should_refetch(prev, 'k', 'en') is True
    assert R.should_refetch(prev, 'k', 'zh') is False


def test_a_failed_key_is_always_retried():
    prev = {'releases': [{'key': 'k', 'language': None, 'fetch_status': 'failed',
                          'tier': 1, 'discovered': True}]}
    assert R.should_refetch(prev, 'k', 'zh') is True


def test_unknown_key_is_fetched():
    assert R.should_refetch({'releases': []}, 'new', 'en') is True


def test_tier_comes_from_the_kind_table():
    assert R.TIERS['nbs-cpi'] == 1
    assert R.TIERS['nbs-industrial-profits'] == 2


# ── 실제 인덱스에서 발견된 조용한 누락 (2026-09-05) ──

TRUNCATED = ('<a title="Sales Prices of Commercial Residential Buildings in 70 Medium '
             'and Large-sized Cities in July 2026" href="./202608/t20260817_1965061.html">'
             '12.Sales Prices of Commercial Residential Buildings in 70 Medium and '
             'Large-sized Cities in...</a>')

PROFITS = ('<a title="Profits of Industrial Enterprises above the Designated Size from '
           'January to July in 2026" href="./202608/t20260828_1965134.html">'
           '4.Profits of Industrial Enterprises above the Designated Size from January '
           'to July in 2026</a>')


def test_full_title_comes_from_the_title_attribute_when_the_link_text_is_truncated():
    """앵커 텍스트가 「…Cities in...」로 잘려 참조월이 사라진다 — tier 1 이 통째로 빠졌다."""
    got = R.parse_nbs_index(TRUNCATED)
    assert [r['key'] for r in got] == ['nbs-house-prices-2026-07']


def test_month_followed_by_in_year_is_parsed():
    """「from January to July in 2026」 — 월과 연도 사이에 in 이 낀 표기."""
    got = R.parse_nbs_index(PROFITS)
    assert got[0]['key'] == 'nbs-industrial-profits-2026-07'
    assert got[0]['tier'] == 2


# ── codex 2차 검토: HTTP 200 이라고 본문이 아닌 것은 아니다 (2026-09-05) ──

REAL_CPI = ("Consumer Price Index in July 2026 2026-08-10 09:30 In July 2026, China's "
            "Consumer Price Index (CPI) increased by 0.5% year on year. Specifically, "
            "the price index for food decreased by 1.5% while that for non-food "
            "increased by 0.9%. From January to July, on average, China's CPI increased "
            "by 0.9% year on year.")


def test_a_real_release_body_is_valid():
    assert R.valid_body('nbs-cpi', REAL_CPI, '2026-07') is None


def test_an_access_denied_page_is_not_a_release():
    """HTTP 200 을 돌려주는 WAF 안내문. 이걸 통과시키면 수집 장애가 무발표로 위장된다."""
    assert R.valid_body('nbs-cpi', 'Access denied. Your request was blocked.', '2026-07')


def test_a_body_missing_the_reference_period_is_rejected():
    body = "China's Consumer Price Index (CPI) increased by 0.5% year on year." * 6
    assert R.valid_body('nbs-cpi', body, '2026-07')


def test_a_body_too_short_is_rejected():
    assert R.valid_body('nbs-cpi', 'July 2026 CPI', '2026-07')


def test_ledger_marks_an_invalid_body_as_invalid_not_ok():
    idx = R.ledger([{'key': 'nbs-cpi-2026-07', 'kind': 'nbs-cpi', 'period': '2026-07',
                     'tier': 1, 'url': 'u', 'title': 't', 'published': '2026-08-10'}],
                   fetched={'nbs-cpi-2026-07': ('Access denied.', 'en')}, errors={})
    assert idx['releases'][0]['fetch_status'] == 'invalid'


def test_an_empty_index_is_a_failure_not_a_quiet_week():
    """인덱스는 늘 최근 릴리스 십여 건을 싣는다 — 0건은 인덱스가 깨진 것이다."""
    assert R.index_looks_broken([])
    assert not R.index_looks_broken([{'key': 'k'}])


def test_block_cue_anywhere_in_the_body_is_caught():
    """차단문이 앞 2,000자 밖에 있으면 통과하던 구멍."""
    body = 'Consumer Price Index in July 2026. ' * 90 + ' Access denied.'
    assert R.valid_body('nbs-cpi', body, '2026-07')


def test_the_year_must_match_not_just_the_month():
    body = ("Consumer Price Index in July 2025. In July 2025, China's Consumer Price "
            "Index (CPI) increased by 0.5% year on year. " * 4)
    assert R.valid_body('nbs-cpi', body, '2026-07')


def test_abbreviated_month_is_accepted():
    body = ("Consumer Price Index in Jul. 2026. China's Consumer Price Index (CPI) "
            "increased by 0.5% year on year. " * 4)
    assert R.valid_body('nbs-cpi', body, '2026-07') is None


def test_short_notice_kinds_have_a_lower_length_floor():
    body = ('中国人民银行授权全国银行间同业拆借中心公布，2026年8月20日贷款市场报价利率'
            '（LPR）为：1年期LPR为3.0%，5年期以上LPR为3.5%。')
    assert R.valid_body('pboc-lpr', body, '2026-08') is None


def test_fiscal_release_vocabulary_is_recognised():
    body = ('2026年1-7月财政收支情况。一般公共预算收入同比增长1.2%，'
            '国有土地使用权出让收入同比下降4.6%。' * 3)
    assert R.valid_body('mof-fiscal', body, '2026-07') is None


def test_month_in_year_variant_is_accepted_in_the_body_too():
    """「from January to July in 2026」 — 제목 파서에서 이미 겪은 변형."""
    body = ("Profits of Industrial Enterprises above the Designated Size from January "
            "to July in 2026. Profits of industrial enterprises grew 1.2%. " * 4)
    assert R.valid_body('nbs-industrial-profits', body, '2026-07') is None
