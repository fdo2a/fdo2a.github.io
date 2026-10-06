"""Reference indices for trend-unit candidates.

Each row is an idea's tradable proxy: the index whose constituents a unit would be
screened from. The list is a judgment — a theme that is not here does not show on
the board — so it is kept small, named, and changed only with a reason recorded in
docs/superpowers/specs/2026-10-06-fund-desk-design.md.

kind: 'benchmark' (not ranked), 'risk_on', 'risk_off', 'region'.
"""

BENCHMARK = 'SPY'

UNITS = (
    # id, 이름, ticker, kind
    ('spy', 'S&P 500', 'SPY', 'benchmark'),
    ('rsp', 'S&P 500 동일가중', 'RSP', 'benchmark'),
    ('qqq', '나스닥 100', 'QQQ', 'benchmark'),

    ('semis', '반도체·AI 하드웨어', 'SMH', 'risk_on'),
    ('software', '소프트웨어', 'IGV', 'risk_on'),
    ('megacap', '초대형주 Top 50', 'XLG', 'risk_on'),
    ('grid', '전력망', 'GRID', 'risk_on'),
    ('industrials', '산업재', 'XLI', 'risk_on'),
    ('discretionary', '경기소비재', 'XLY', 'risk_on'),
    ('homebuilders', '주택건설', 'XHB', 'risk_on'),
    ('metals', '금속·광업', 'XME', 'risk_on'),
    ('financials', '금융', 'XLF', 'risk_on'),
    ('banks', '은행', 'KBE', 'risk_on'),
    ('defense', '방산', 'ITA', 'risk_on'),
    ('energy', '에너지', 'XLE', 'risk_on'),
    ('smallcap', '소형주', 'IWM', 'risk_on'),
    ('small_growth', '소형 성장', 'IWO', 'risk_on'),
    ('momentum', '모멘텀 팩터', 'MTUM', 'risk_on'),

    ('lowvol', '저변동성', 'SPLV', 'risk_off'),
    ('dividend', '배당', 'SCHD', 'risk_off'),
    ('quality', '퀄리티 팩터', 'QUAL', 'risk_off'),
    ('staples', '필수소비재', 'XLP', 'risk_off'),
    ('utilities', '유틸리티', 'XLU', 'risk_off'),
    ('healthcare', '헬스케어', 'XLV', 'risk_off'),

    ('europe', '유럽', 'VGK', 'region'),
    ('japan', '일본', 'EWJ', 'region'),
    ('china', '중국', 'MCHI', 'region'),
    ('em', '신흥국', 'EEM', 'region'),
)

# 「방어 스타일」 — 위험회피라 부르지 않는다. 손실 회피나 헤지 성능을 뜻하지 않는다.
KIND_KO = {'risk_on': '위험선호', 'risk_off': '방어 스타일', 'region': '지역', 'benchmark': '기준'}
KIND_ORDER = ('risk_on', 'risk_off', 'region', 'benchmark')


def tickers():
    return sorted({t for _, _, t, _ in UNITS})
