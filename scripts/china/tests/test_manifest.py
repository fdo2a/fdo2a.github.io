import pytest

from china import manifest as M

# 2026-08-10 NBS 영문 CPI 릴리스 실제 문장 (2026-09-05 수집)
CPI_EN = ("In July 2026, China's Consumer Price Index (CPI) increased by 0.5% year on "
          "year. Specifically, the price index in urban areas increased by 0.5% while "
          "that in rural areas increased by 0.4%; the price index for food decreased by "
          "1.5% while that for non-food increased by 0.9%; the price index for consumer "
          "goods increased by 0.2% while that for services increased by 0.7%. From "
          "January to July, on average, China's CPI increased by 0.9% year on year.   "
          "In July, China's CPI decreased by 0.1% month on month.")

CPI_ZH = ("2026年7月份，全国居民消费价格同比上涨0.5%。其中，食品价格下降1.5%，"
          "非食品价格上涨0.9%。7月份，全国居民消费价格环比下降0.1%。")


def facts_by_id(facts):
    return {f['metric_id']: f for f in facts}


# ── 부호를 값에 실어 뽑는다 ──

def test_extracts_cpi_yoy_with_sign_from_english():
    f = facts_by_id(M.extract('nbs-cpi', CPI_EN, period='2026-07'))
    assert f['cpi_yoy']['value'] == 0.5
    assert f['cpi_yoy']['unit'] == '%'
    assert f['cpi_yoy']['period'] == '2026-07'


def test_decrease_becomes_a_negative_value():
    f = facts_by_id(M.extract('nbs-cpi', CPI_EN, period='2026-07'))
    assert f['cpi_mom']['value'] == -0.1
    assert f['cpi_food_yoy']['value'] == -1.5


def test_non_food_and_cumulative_are_separate_metrics():
    f = facts_by_id(M.extract('nbs-cpi', CPI_EN, period='2026-07'))
    assert f['cpi_nonfood_yoy']['value'] == 0.9
    assert f['cpi_cum_yoy']['value'] == 0.9


def test_chinese_release_yields_the_same_metric_ids():
    f = facts_by_id(M.extract('nbs-cpi', CPI_ZH, period='2026-07'))
    assert f['cpi_yoy']['value'] == 0.5
    assert f['cpi_mom']['value'] == -0.1
    assert f['cpi_food_yoy']['value'] == -1.5


# ── fail-closed ──

def test_unmatched_metric_is_simply_absent():
    f = facts_by_id(M.extract('nbs-cpi', 'In July 2026 nothing was published.',
                              period='2026-07'))
    assert f == {}


def test_unknown_kind_raises_rather_than_returning_empty():
    """오타난 kind 가 조용히 «발표 없음» 이 되면 안 된다."""
    with pytest.raises(KeyError):
        M.extract('nbs-nope', CPI_EN, period='2026-07')


def test_flat_is_zero_not_missing():
    txt = "In July 2026, China's CPI remained flat year on year."
    f = facts_by_id(M.extract('nbs-cpi', txt, period='2026-07'))
    assert f['cpi_yoy']['value'] == 0.0


# ── 레벨 지표 (부호 없음) ──

def test_pmi_levels_are_extracted_as_levels():
    txt = ("In August 2026, the Purchasing Managers' Index (PMI) for China's "
           "manufacturing sector was 49.6%, and the non-manufacturing business "
           "activity index was 50.3%.")
    f = facts_by_id(M.extract('nbs-pmi', txt, period='2026-08'))
    assert f['pmi_mfg']['value'] == 49.6
    assert f['pmi_nonmfg']['value'] == 50.3
    assert f['pmi_mfg']['kind'] == 'level'


def test_lpr_levels():
    txt = '1年期LPR为3.0%，5年期以上LPR为3.5%。'
    f = facts_by_id(M.extract('pboc-lpr', txt, period='2026-08'))
    assert f['lpr_1y']['value'] == 3.0
    assert f['lpr_5y']['value'] == 3.5


# ── manifest 조립 ──

def test_build_merges_releases_and_keys_by_metric_and_period():
    m = M.build([
        {'key': 'nbs-cpi-2026-07', 'kind': 'nbs-cpi', 'period': '2026-07', 'text': CPI_EN},
        {'key': 'nbs-cpi-2026-06', 'kind': 'nbs-cpi', 'period': '2026-06',
         'text': "In June 2026, China's CPI increased by 0.2% year on year."},
    ])
    assert m['cpi_yoy']['2026-07']['value'] == 0.5
    assert m['cpi_yoy']['2026-06']['value'] == 0.2
    assert m['cpi_yoy']['2026-07']['source_key'] == 'nbs-cpi-2026-07'


def test_allowed_values_flattens_for_the_gate():
    m = M.build([{'key': 'k', 'kind': 'nbs-cpi', 'period': '2026-07', 'text': CPI_EN}])
    vals = M.allowed_values(m, 'cpi_yoy')
    assert '0.5' in vals and '-0.5' not in vals


def test_label_is_korean_so_the_gate_can_name_the_metric():
    assert '소비자물가' in M.METRICS['cpi_yoy'].label_ko


def test_allowed_values_can_be_narrowed_to_one_period():
    m = M.build([
        {'key': 'k7', 'kind': 'nbs-cpi', 'period': '2026-07', 'text': CPI_EN},
        {'key': 'k6', 'kind': 'nbs-cpi', 'period': '2026-06',
         'text': "In June 2026, China's CPI increased by 0.2% year on year."},
    ])
    july = M.allowed_values(m, 'cpi_yoy', '2026-07')
    assert '0.5' in july and '0.50' in july      # 같은 값의 표기 변형은 허용
    assert '0.2' not in july                     # 다른 달 값은 불허 — 이게 요점이다
    assert M.allowed_values(m, 'cpi_yoy', '2026-09') == set()
    assert {'0.5', '0.2'} <= M.allowed_values(m, 'cpi_yoy')


def test_typographic_apostrophes_do_not_defeat_patterns():
    """실제 NBS 페이지는 `China’s` 를 쓴다 — 곧은 따옴표로만 맞추면 조용히 놓친다."""
    txt = "From January to July, on average, China’s CPI increased by 0.9% year on year."
    f = facts_by_id(M.extract('nbs-cpi', txt, period='2026-07'))
    assert f['cpi_cum_yoy']['value'] == 0.9


# ── 실제 릴리스에서 잡힌 오귀속 (2026-09-05) ──────────────────────────────
# 아래 문장은 전부 2026-08 NBS 영문 릴리스 원문이다. 「지표 이름이 들어 있는 문장」이
# 아니라 **헤드라인 문장**에 붙어야 한다는 것을 지키는 회귀 검사다.

FAI_REAL = (
    "From January to July 2026, the national investment in fixed assets (excluding "
    "rural households) was 26,032.8 billion yuan, a year-on-year decrease of 6.7% "
    "(calculated on a comparable basis). Specifically, investment in infrastructure "
    "increased by 24.6%. By statistical category of registration, the investment in "
    "fixed assets of domestic-invested enterprises decreased by 6.4% year on year, the "
    "investment in fixed assets of enterprises funded by investors from Hong Kong, "
    "Macao, and Taiwan increased by 1.1% year on year.")


def test_fai_takes_the_headline_not_a_sub_category():
    """-6.4% 는 「내자기업」 하위 항목 값이다. 헤드라인은 -6.7%."""
    f = facts_by_id(M.extract('nbs-fai', FAI_REAL, period='2026-07'))
    assert f['fai_cum_yoy']['value'] == -6.7


RETAIL_REAL = (
    "From January to July 2026, the total retail sales of consumer goods reached "
    "28,774.4 billion yuan, up by 1.2% year on year. Specifically, the retail sales of "
    "consumer goods excluding automobiles reached 26,514.2 billion yuan, up by 2.7%. "
    "In July, the total retail sales of consumer goods reached 3,902.2 billion yuan, "
    "up by 0.6% year on year.")


def test_retail_monthly_and_cumulative_are_not_confused():
    """누계 문장이 먼저 나온다 — 앞에서부터 찾으면 월간 값 자리에 누계가 들어간다."""
    f = facts_by_id(M.extract('nbs-retail', RETAIL_REAL, period='2026-07'))
    assert f['retail_yoy']['value'] == 0.6
    assert f['retail_cum_yoy']['value'] == 1.2


IP_REAL = (
    "In July, the total value added of industrial enterprises above the designated size "
    "increased by 4.5% year on year in real terms. On a month-on-month basis, in July, "
    "the total value added of industrial enterprises above the designated size increased "
    "by 0.11% over the previous month. From January to July, the total value added of "
    "industrial enterprises above the designated size increased by 5.3% year on year. "
    "In terms of three sectors, in July, the value added of the mining industry "
    "decreased by 4.2% year on year.")


def test_industrial_production_takes_the_monthly_headline():
    f = facts_by_id(M.extract('nbs-ip', IP_REAL, period='2026-07'))
    assert f['ip_yoy']['value'] == 4.5


PPI_REAL = ("In July 2026, China's producer price index for industrial products (PPI) "
            "increased by 3.5% year on year and decreased by 0.7% month on month.")


def test_ppi_yoy_and_mom_from_one_sentence():
    f = facts_by_id(M.extract('nbs-ppi', PPI_REAL, period='2026-07'))
    assert f['ppi_yoy']['value'] == 3.5
    assert f['ppi_mom']['value'] == -0.7


PMI_REAL = ("In August, the purchasing managers' index (PMI) of China's manufacturing "
            "industry was 49.8%, an increase of 0.6 percentage points from the previous "
            "month. II. Non-manufacturing Purchasing Managers' Index In August, the "
            "non-manufacturing business activity index was 49.0%, unchanged from the "
            "previous month. III. Composite PMI Output Index In August, the composite "
            "PMI output index was 49.5%, an increase of 0.2 percentage points.")


def test_three_pmi_levels_are_distinguished():
    f = facts_by_id(M.extract('nbs-pmi', PMI_REAL, period='2026-08'))
    assert f['pmi_mfg']['value'] == 49.8
    assert f['pmi_nonmfg']['value'] == 49.0
    assert f['pmi_composite']['value'] == 49.5


PROPERTY_REAL = ("From January to July, the investment in real estate development was "
                 "4,300.9 billion yuan, a year-on-year decrease of 19.2% (calculated on "
                 "a comparable basis).")


def test_property_investment_uses_the_year_on_year_of_construction():
    f = facts_by_id(M.extract('nbs-property', PROPERTY_REAL, period='2026-07'))
    assert f['property_inv_cum_yoy']['value'] == -19.2


def test_trailing_zero_decimals_are_allowed():
    """원문이 「49.0%」라고 쓴 레벨을 발행본도 그렇게 쓴다 — 「49」만 허용하면 오탐."""
    m = {'pmi_nonmfg': {'2026-08': {'value': 49.0, 'unit': '%', 'label_ko': 'x',
                                    'kind': 'level', 'period': '2026-08',
                                    'metric_id': 'pmi_nonmfg', 'source_key': 'k'}}}
    vals = M.allowed_values(m, 'pmi_nonmfg', '2026-08')
    assert '49.0' in vals and '49' in vals


# ── codex 3차: 문구 변형 오염 (2026-09-05) ──

CPI_VARIANT = (
    "In July 2026, China's Consumer Price Index (CPI) rose 0.5% year on year. "
    "Specifically, the price index for food decreased by 1.5% while that for non-food "
    "increased by 0.9%. From January to July, on average, China's CPI increased by "
    "0.9% year on year. In July, China's CPI decreased by 0.1% month on month. "
    "Specifically, the price index for food remained flat while that for non-food "
    "decreased by 0.1%.")


def test_a_verb_variant_does_not_leak_the_cumulative_figure():
    """「rose」로 바뀌자 첫 패턴이 빗나가 누계 0.9 를 월간 값으로 물어 왔다."""
    f = facts_by_id(M.extract('nbs-cpi', CPI_VARIANT, period='2026-07'))
    assert f['cpi_yoy']['value'] == 0.5
    assert f['cpi_cum_yoy']['value'] == 0.9


def test_food_yoy_is_not_taken_from_the_month_on_month_paragraph():
    """전월비 문단에도 「price index for food」 가 있다 — 전년비 값이어야 한다."""
    f = facts_by_id(M.extract('nbs-cpi', CPI_VARIANT, period='2026-07'))
    assert f['cpi_food_yoy']['value'] == -1.5
    assert f['cpi_nonfood_yoy']['value'] == 0.9
