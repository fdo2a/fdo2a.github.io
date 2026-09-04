"""커브 캡션은 실제 행에서 유도한다 — 손으로 적은 문구는 소스가 바뀌면 거짓이 된다.

2026-09-04 에 발행용 미국 커브를 네이버 종가로 바꿨는데, 캡션에는
「5·10·30년은 야후 스팟, 나머지 만기는 FRED」가 그대로 박혀 있었다. 행의 출처
칸은 Naver 라고 말하고 캡션은 야후·FRED 라고 말하는 상태였다 (codex 검토).
"""
from scripts.bond import report_note as rn


def _tenors(pairs):
    return {'tenors': {t: {'source': s, 'date': d} for t, (s, d) in pairs.items()}}


def test_a_single_source_on_one_date_reads_as_one_clause():
    node = _tenors({'2Y': ('Naver', '2026-09-02'), '10Y': ('Naver', '2026-09-02')})
    assert rn.source_note(node) == ' · 전 만기 Naver 2026-09-02 동일 기준일'


def test_mixed_sources_are_listed_by_source():
    node = _tenors({'2Y': ('FRED', '2026-09-01'), '5Y': ('Yahoo', '2026-09-02'),
                    '10Y': ('Yahoo', '2026-09-02')})
    note = rn.source_note(node)
    assert '2년은 FRED 2026-09-01' in note
    assert '5·10년은 Yahoo 2026-09-02' in note


def test_one_source_but_split_dates_still_names_the_dates():
    node = _tenors({'2Y': ('Naver', '2026-09-01'), '10Y': ('Naver', '2026-09-02')})
    note = rn.source_note(node)
    assert '동일 기준일' not in note
    assert 'Naver 2026-09-01' in note and 'Naver 2026-09-02' in note


def test_an_empty_curve_produces_no_caption():
    assert rn.source_note({'tenors': {}}) == ''
    assert rn.source_note(None) == ''


# --- 출처 전환 점프 차단 (codex 검토 2026-09-04) -----------------------------

from scripts.bond import history as H, metrics as M


def _market(node, tenor, level, source, date='2026-09-02'):
    return {'report_date': date,
            node: {tenor: {'level': level, 'date': date, 'source': source, 'tenor': tenor}}}


def test_the_ledger_records_the_source_for_every_country_not_just_the_us():
    """길트가 BOE 08-28 에서 네이버 09-02 로 갈아탈 때 10년물이 17bp 뛴다.

    그건 시장이 움직인 게 아니라 소스가 바뀐 것이다. 출처를 안 남기면 다음 날
    «어제 대비»가 그 점프를 하루 변화로 읽는다.
    """
    rec = H.market_record(_market('gb_curve', '10Y', 5.237, 'Naver'))
    assert rec['dates'].get('gb_source', {}).get('10Y') == 'Naver'
    assert rec['dates'].get('kr_source') is not None


def test_a_source_switch_blanks_the_daily_change_for_that_country():
    market = _market('gb_curve', '10Y', 5.237, 'Naver')
    prev = {'gb': {'10Y': 5.063}}
    prev_dates = {'gb': {'10Y': '2026-08-28'}, 'gb_source': {'10Y': 'BOE'}}
    block = M.curve_block(market, prev, prev_dates)
    row = block['gb']['tenors']['10Y']
    assert row['bp'] is None, '소스가 바뀐 날의 전일 대비는 성립하지 않는다'
