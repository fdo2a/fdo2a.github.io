import json
from us.history import market_record


SNAP = {
    'report_date': '2026-08-28',
    'indices': {'S&P 500': {'last': 7711.759765625, 'pct': -0.24},
                'Nasdaq': {'last': 26402.42, 'pct': -0.52}},
    'sectors': {'Technology': {'last': 185.69, 'pct': -1.5}},
    'fx': {'DXY': {'last': 99.677, 'pct': 0.52},
           'USD/KRW': {'last': 1375.6700439453125, 'pct': -0.56}},
    'commodities': {'Gold': {'last': 4504.1, 'pct': 0.3}},
    'memory': {'Micron': {'last': 932.86}},
    'ai_infra': {'Marvell': {'last': 216.62}},
    'yields': {'2Y': {'level': 4.2, 'date': '2026-08-27', 'source': 'FRED'},
               '10Y': {'level': 4.72, 'date': '2026-08-28', 'source': 'Yahoo'}},
}


def test_record_carries_the_published_closes_verbatim():
    r = market_record(SNAP)
    assert r['report_date'] == '2026-08-28'
    # 발행본이 인쇄한 값 그대로 — 반올림도 재계산도 하지 않는다
    assert r['indices']['S&P 500'] == 7711.759765625
    assert r['fx']['USD/KRW'] == 1375.6700439453125
    assert r['commodities']['Gold'] == 4504.1
    assert r['yields']['10Y'] == 4.72


def test_record_covers_every_group_the_period_aggregation_reads():
    r = market_record(SNAP)
    for g in ('indices', 'sectors', 'fx', 'commodities', 'memory', 'ai_infra'):
        assert g in r, g
    assert r['sectors']['Technology'] == 185.69
    assert r['memory']['Micron'] == 932.86


def test_record_drops_names_without_a_close_rather_than_inventing_one():
    snap = json.loads(json.dumps(SNAP))
    snap['indices']['Russell 2000'] = {'last': None, 'pct': None}
    snap['yields']['30Y'] = {'date': '2026-08-28'}
    r = market_record(snap)
    assert 'Russell 2000' not in r['indices']
    assert '30Y' not in r['yields']


def test_record_is_json_round_trippable():
    assert json.loads(json.dumps(market_record(SNAP)))['yields']['2Y'] == 4.2


from us.period import series_from  # noqa: E402

LEDGER = [
    {'report_date': '2026-08-21', 'indices': {'S&P 500': 100.0}, 'sectors': {'Technology': 180.0},
     'fx': {'DXY': 98.0}, 'commodities': {'Gold': 4400.0}, 'memory': {'Micron': 900.0},
     'ai_infra': {}, 'yields': {'10Y': 4.60, '2Y': 4.10}},
    {'report_date': '2026-08-24', 'indices': {'S&P 500': 102.0}, 'sectors': {'Technology': 180.0},
     'fx': {'DXY': 99.0}, 'commodities': {'Gold': 4450.0}, 'memory': {'Micron': 930.0},
     'ai_infra': {}, 'yields': {'10Y': 4.68}},
    {'report_date': '2026-08-28', 'indices': {'S&P 500': 110.0}, 'sectors': {'Technology': 180.0},
     'fx': {'DXY': 99.677}, 'commodities': {'Gold': 4504.1}, 'memory': {'Micron': 932.86},
     'ai_infra': {}, 'yields': {'10Y': 4.72, '2Y': 4.20}},
]


def test_series_from_turns_the_ledger_into_dated_closes():
    closes, yields_hist = series_from(LEDGER)
    assert closes['indices']['S&P 500'] == [('2026-08-21', 100.0), ('2026-08-24', 102.0),
                                            ('2026-08-28', 110.0)]
    assert yields_hist['10Y'][-1] == ('2026-08-28', 4.72)


def test_series_from_sorts_by_date_regardless_of_ledger_order():
    closes, _ = series_from(list(reversed(LEDGER)))
    assert [d for d, _ in closes['fx']['DXY']] == ['2026-08-21', '2026-08-24', '2026-08-28']


def test_series_from_leaves_gaps_rather_than_carrying_a_value_forward():
    # 08-24 행에 2Y 가 없다 — 없는 날은 없는 채로 둔다(직전 값을 끌어오지 않는다)
    _, yields_hist = series_from(LEDGER)
    assert [d for d, _ in yields_hist['2Y']] == ['2026-08-21', '2026-08-28']


def test_period_returns_match_the_published_closes_exactly():
    from us.period import build
    agg = build('weekly', '2026-W35', *series_from(LEDGER), [])
    # 100.0 → 110.0 은 그 주 발행본 두 편이 인쇄한 종가다. 재수집이 없으니 갈릴 수 없다.
    assert agg['indices']['S&P 500']['end'] == 110.0
    assert agg['yields']['10Y']['end'] == 4.72
    assert agg['commodities']['Gold']['end'] == 4504.1


# ── 2026-08-30 codex 검토: 원장 롤업이 재수집 대비 놓치는 것들 ────────────────

def _ledger(**overrides):
    rows = [
        {'report_date': '2026-08-21', 'indices': {'S&P 500': 100.0}, 'sectors': {'Technology': 180.0},
         'fx': {'DXY': 98.0}, 'commodities': {'Gold': 4400.0, 'WTI': 80.0},
         'memory': {'Micron': 900.0}, 'ai_infra': {'Marvell': 200.0}, 'yields': {'2Y': 4.10, '5Y': 4.40, '10Y': 4.60, '30Y': 5.20}},
        {'report_date': '2026-08-27', 'indices': {'S&P 500': 105.0}, 'sectors': {'Technology': 180.0},
         'fx': {'DXY': 99.0}, 'commodities': {'Gold': 4450.0, 'WTI': 81.0},
         'memory': {'Micron': 900.0}, 'ai_infra': {'Marvell': 200.0}, 'yields': {'2Y': 4.15, '5Y': 4.45, '10Y': 4.68, '30Y': 5.25}},
        {'report_date': '2026-08-28', 'indices': {'S&P 500': 110.0}, 'sectors': {'Technology': 186.0},
         'fx': {'DXY': 99.7}, 'commodities': {'Gold': 4504.1, 'WTI': 82.0},
         'memory': {'Micron': 900.0}, 'ai_infra': {'Marvell': 200.0}, 'yields': {'2Y': 4.20, '5Y': 4.48, '10Y': 4.72, '30Y': 5.30}},
    ]
    for k, v in overrides.items():
        rows[-1][k] = v
    return rows


def _agg(rows):
    from us.period import build
    return build('weekly', '2026-W35', *series_from(rows), [])


def test_an_instrument_missing_on_the_last_day_is_not_complete():
    # 금이 08-28 원장 행에 없다 — 그러면 성과표의 금 종가는 08-27 값이 된다.
    # 「끝값 = 마지막 발행본 종가」가 깨지는데 조용히 통과하면 안 된다.
    rows = _ledger(commodities={'WTI': 82.0})
    agg = _agg(rows)
    assert agg['complete'] is False
    assert any('Gold' in m for m in agg['missing']), agg['missing']


def test_an_instrument_that_vanished_from_the_ledger_is_reported():
    # 재수집 시절엔 계열이 비어도 이름은 늘 나왔다(missing 으로 걸렸다).
    # 원장은 없는 이름을 아예 안 만들므로 과거 행을 근거로 명부를 세운다.
    rows = _ledger(fx={})
    agg = _agg(rows)
    assert agg['complete'] is False
    assert any('DXY' in m for m in agg['missing']), agg['missing']


def test_a_yield_tenor_missing_on_the_last_day_is_not_complete():
    rows = _ledger(yields={'2Y': 4.20, '5Y': 4.48, '30Y': 5.30})
    agg = _agg(rows)
    assert agg['complete'] is False
    assert any('10Y' in m for m in agg['missing']), agg['missing']


def test_a_full_ledger_is_complete():
    agg = _agg(_ledger())
    assert agg['complete'] is True, agg['missing']
    assert agg['missing'] == []


def test_the_ledger_takes_the_corrected_row_for_the_same_day():
    # 수집 워크플로는 하루 두 번 돈다. 두 번째 실행의 확정 스냅샷이 발행본이 되므로
    # 원장도 그것을 들고 있어야 한다 — 선착순이면 원장과 발행본이 갈린다.
    import os
    import tempfile
    from us.history import append_jsonl, read_jsonl
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'market.jsonl')
        append_jsonl(path, {'report_date': '2026-08-28', 'indices': {'S&P 500': 1.0}},
                     upsert=True)
        append_jsonl(path, {'report_date': '2026-08-28', 'indices': {'S&P 500': 2.0}},
                     upsert=True)
        rows = read_jsonl(path)
        assert len(rows) == 1
        assert rows[0]['indices']['S&P 500'] == 2.0


def test_the_judgement_ledgers_stay_first_write_wins():
    import os
    import tempfile
    from us.history import append_jsonl, read_jsonl
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'stance.jsonl')
        append_jsonl(path, {'report_date': '2026-08-28', 'horizon': 'a'})
        append_jsonl(path, {'report_date': '2026-08-28', 'horizon': 'b'})
        assert [r['horizon'] for r in read_jsonl(path)] == ['a']
