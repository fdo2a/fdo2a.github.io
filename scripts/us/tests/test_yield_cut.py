"""국채 16:00 ET 컷 — 오늘·전일·1주 전이 같은 규칙, 한 커브 한 원천, 비교일은 건너뛰지 않는다."""
from us import yield_cut as Y

S = '2026-11-06'           # 금
PREV = '2026-11-05'
WEEK = '2026-10-30'


def pts(day, *pairs):
    return [(day, hhmm, v) for hhmm, v in pairs]


def naver_day(day, base=4.5):
    return {t: pts(day, ('15:38', base + i), ('15:59', base + i + 0.01), ('16:09', base + i + 0.02))
            for i, t in enumerate(Y.TENORS)}


# ---- pick -------------------------------------------------------------------------

def test_pick_nearest_to_1600_prefers_earlier_on_tie():
    p = pts(S, ('15:55', 1.0), ('16:05', 2.0))
    assert Y.pick(p, S) == {'value': 1.0, 'stamp': '15:55'}


def test_pick_takes_after_1600_when_closer():
    p = pts(S, ('15:38', 1.0), ('16:09', 2.0))     # 15:38 은 창 밖, 16:09 는 안
    assert Y.pick(p, S)['stamp'] == '16:09'


def test_pick_window_is_15_minutes_each_side():
    assert Y.pick(pts(S, ('15:44', 1.0), ('16:16', 2.0)), S) is None
    assert Y.pick(pts(S, ('15:45', 1.0)), S)['stamp'] == '15:45'
    assert Y.pick(pts(S, ('16:15', 1.0)), S)['stamp'] == '16:15'


def test_pick_matches_each_points_own_date():
    # 응답이 다음 날로 넘어가 전날 포인트가 섞여 와도 날짜로 가른다
    p = pts(PREV, ('15:59', 9.9)) + pts(S, ('16:09', 1.0))
    assert Y.pick(p, S)['value'] == 1.0
    assert Y.pick(p, PREV)['value'] == 9.9


# ---- parse ------------------------------------------------------------------------

def test_parse_naver_chart_reads_both_lists_with_ny_stamps():
    payload = {'result': {'priceInfos': [{'localDateTime': '20261106155900', 'currentPrice': 4.518}],
                          'lastPriceInfos': [{'localDateTime': '20261105170500', 'currentPrice': '4,47'}]}}
    got = Y.parse_naver_chart(payload)
    assert ('2026-11-06', '15:59', 4.518) in got
    assert all(len(r) == 3 for r in got)


def test_parse_cnbc_5d_bars():
    payload = {'barData': {'priceBars': [{'close': '4.5140', 'tradeTime': '20261106160100'},
                                         {'close': None, 'tradeTime': '20261106160600'}]}}
    assert Y.parse_cnbc_5d(payload) == [('2026-11-06', '16:01', 4.514)]


def test_parse_ignores_garbage():
    assert Y.parse_naver_chart({'priceInfos': [{'localDateTime': 'x', 'currentPrice': 1}]}) == []
    assert Y.parse_cnbc_5d(None) == []


# ---- curve: 한 커브 한 원천 -----------------------------------------------------------

def test_curve_uses_naver_when_all_four_tenors_present():
    c = Y.curve(S, naver_day(S))
    assert c['source'] == 'naver' and set(c['tenors']) == set(Y.TENORS)


def test_curve_never_mixes_vendors():
    naver = naver_day(S)
    naver['2Y'] = []                              # 한 만기 빠짐 → 네이버 통째로 버림
    cnbc = naver_day(S, base=5.0)
    c = Y.curve(S, naver, cnbc)
    assert c['source'] == 'cnbc'
    assert c['tenors']['10Y']['value'] == round(5.0 + 2 + 0.01, 4)


def test_curve_none_when_neither_vendor_complete():
    naver = naver_day(S)
    naver['30Y'] = pts(S, ('15:00', 1.0))
    assert Y.curve(S, naver, None) is None


# ---- sessions ---------------------------------------------------------------------

def test_sessions_skip_weekends_and_closed_days():
    assert Y.sessions_before('2026-11-09', 1, set()) == ['2026-11-06']          # 월 → 금
    assert Y.sessions_before('2026-11-12', 1, {'2026-11-11'}) == ['2026-11-10']  # 재향군인의 날
    assert Y.needed(S, set()) == [S, PREV, WEEK]


# ---- ledger -----------------------------------------------------------------------

def test_update_writes_today_from_naver_and_fills_gaps_from_cnbc_only():
    ledger = {}
    calls = []

    def cnbc():
        calls.append(1)
        out = {}
        for d in (PREV, WEEK):
            for t, p in naver_day(d, base=4.0).items():
                out.setdefault(t, []).extend(p)
        return out

    changed = Y.update(ledger, S, set(), naver_day(S), cnbc)
    assert set(changed) == {S, PREV, WEEK}
    assert ledger[S]['source'] == 'naver'
    assert ledger[PREV]['source'] == 'cnbc' and ledger[WEEK]['source'] == 'cnbc'
    assert len(calls) == 1                         # CNBC 는 한 번만 받는다


def test_update_does_not_call_cnbc_when_ledger_is_full():
    ledger = {d: Y.curve(d, naver_day(d)) for d in (PREV, WEEK)}

    def boom():
        raise AssertionError('CNBC 를 부르면 안 된다')
    Y.update(ledger, S, set(), naver_day(S), boom)
    assert ledger[S]['source'] == 'naver'


def test_record_never_overwrites_a_naver_entry():
    ledger = {S: Y.curve(S, naver_day(S))}
    assert Y.record(ledger, S, Y.curve(S, naver_day(S, base=9.0))) is False
    assert ledger[S]['tenors']['2Y']['value'] != 9.01


def test_record_upgrades_cnbc_to_naver():
    ledger = {S: dict(Y.curve(S, naver_day(S, base=9.0)), source='cnbc')}
    assert Y.record(ledger, S, Y.curve(S, naver_day(S))) is True
    assert ledger[S]['source'] == 'naver'


# ---- rows -------------------------------------------------------------------------

def test_rows_compute_bp_and_week_on_the_same_rule():
    ledger = {d: Y.curve(d, naver_day(d, base=b)) for d, b in ((S, 4.5), (PREV, 4.4), (WEEK, 4.0))}
    r = Y.rows(S, ledger, set())
    assert r['2Y']['level'] == 4.51 and round(r['2Y']['bp'], 6) == 10.0
    assert r['2Y']['week_ago'] == 4.01 and r['2Y']['week_ago_date'] == WEEK
    assert r['2Y']['basis'] == Y.BASIS and r['2Y']['stamp_et'] == '15:59'
    assert r['2Y']['prev_source'] == 'naver'


def test_rows_do_not_skip_to_an_older_session_when_prev_is_missing():
    older = '2026-11-04'
    ledger = {d: Y.curve(d, naver_day(d)) for d in (S, older, WEEK)}    # PREV 없음
    r = Y.rows(S, ledger, set())
    assert r['10Y']['bp'] is None and r['10Y']['prev_date'] is None


def test_rows_none_without_today():
    assert Y.rows(S, {PREV: Y.curve(PREV, naver_day(PREV))}, set()) is None


def test_save_keeps_recent_sessions(tmp_path):
    ledger = {f'2026-10-{d:02d}': Y.curve(f'2026-10-{d:02d}', naver_day(f'2026-10-{d:02d}'))
              for d in range(1, 31)}
    p = tmp_path / 'y.json'
    Y.save(str(p), ledger, keep=5)
    assert sorted(Y.load(str(p))) == [f'2026-10-{d}' for d in range(26, 31)]


def test_bootstrap_fills_past_sessions_only_from_cnbc():
    cnbc = {}
    for d in (WEEK, '2026-11-02', PREV, S):
        for t, p in naver_day(d, base=4.0).items():
            cnbc.setdefault(t, []).extend(p)
    ledger = {}
    got = Y.bootstrap(ledger, cnbc, set(), before=S)
    assert got == [WEEK, '2026-11-02', PREV] and S not in ledger
    assert all(ledger[d]['source'] == 'cnbc' for d in got)


def test_today_is_not_recorded_before_the_window_closes():
    import datetime as dt
    ledger = {}
    early = {t: pts(S, ('15:48', 1.0)) for t in Y.TENORS}
    Y.update(ledger, S, set(), early, None, now_et=dt.datetime(2026, 11, 6, 15, 50))
    assert S not in ledger                                   # 장중 실행은 오늘을 적지 않는다
    Y.update(ledger, S, set(), naver_day(S), None, now_et=dt.datetime(2026, 11, 6, 16, 20))
    assert ledger[S]['tenors']['2Y']['stamp'] == '15:59'     # 창이 닫힌 뒤 회차가 정본


def test_window_closed_boundary():
    import datetime as dt
    assert not Y.window_closed(S, dt.datetime(2026, 11, 6, 16, 14))
    assert Y.window_closed(S, dt.datetime(2026, 11, 6, 16, 15))
    assert Y.window_closed(S, dt.datetime(2026, 11, 7, 9, 0))   # 다음 날 재시도
    assert Y.window_closed(S, None)


def test_merge_keeps_naver_and_adds_missing():
    base = {S: Y.curve(S, naver_day(S))}
    other = {S: dict(Y.curve(S, naver_day(S, base=9.0)), source='cnbc'),
             PREV: Y.curve(PREV, naver_day(PREV))}
    assert Y.merge(base, other) == [PREV]
    assert base[S]['source'] == 'naver' and base[S]['tenors']['2Y']['value'] == 4.51


def test_load_distinguishes_missing_from_corrupt(tmp_path):
    import pytest
    p = tmp_path / 'y.json'
    assert Y.load(str(p), strict=True) == {}                  # 첫 실행
    p.write_text('{"2026-11-06": ')                            # 잘린 파일
    assert Y.load(str(p)) == {}
    with pytest.raises(Y.LedgerCorrupt):
        Y.load(str(p), strict=True)


def test_cli_merge_refuses_corrupt_files(tmp_path):
    good = tmp_path / 'good.json'
    Y.save(str(good), {S: Y.curve(S, naver_day(S))})
    bad = tmp_path / 'bad.json'
    bad.write_text('<<<<<<< HEAD\n')
    assert Y._cli(['merge', str(bad), str(good)]) == 1          # 원격이 깨짐 → 덮지 않는다
    assert bad.read_text() == '<<<<<<< HEAD\n'
    assert Y._cli(['merge', str(good), str(bad)]) == 1          # 이 실행 원장이 깨짐 → 성공으로 끝내지 않는다
    fresh = tmp_path / 'new.json'
    assert Y._cli(['merge', str(fresh), str(good)]) == 0        # 원격에 파일이 없는 첫 실행
    assert S in Y.load(str(fresh), strict=True)


def test_strict_load_rejects_structurally_broken_rows(tmp_path):
    import json
    import pytest
    ok = Y.curve(S, naver_day(S))
    for bad in ({S: 'broken'}, {S: None}, {'x': ok}, {S: dict(ok, source='?')},
                {S: dict(ok, tenors={'2Y': {'value': 1.0, 'stamp': '15:59'}})},
                {S: dict(ok, tenors=dict(ok['tenors'], **{'2Y': {'value': 'x', 'stamp': '15:59'}}))}):
        p = tmp_path / 'y.json'
        p.write_text(json.dumps(bad))
        with pytest.raises(Y.LedgerCorrupt):
            Y.load(str(p), strict=True)
    p.write_text(json.dumps({S: ok}))
    assert Y.load(str(p), strict=True)[S]['source'] == 'naver'


def test_strict_load_rejects_bad_keys_nan_and_stamps(tmp_path):
    import json
    import pytest
    ok = Y.curve(S, naver_day(S))
    nan_row = json.loads(json.dumps(ok))
    nan_row['tenors']['2Y']['value'] = float('nan')
    for bad in ({'20261106': ok},
                {S: nan_row},
                {S: dict(ok, tenors=dict(ok['tenors'], **{'2Y': {'value': 4.5, 'stamp': 'bad'}}))},
                {S: dict(ok, tenors=dict(ok['tenors'], **{'2Y': {'value': 4.5, 'stamp': '15:00'}}))}):
        p = tmp_path / 'y.json'
        p.write_text(json.dumps(bad))
        with pytest.raises(Y.LedgerCorrupt):
            Y.load(str(p), strict=True)


def test_strict_load_requires_the_1600_target(tmp_path):
    import json
    import pytest
    ok = Y.curve(S, naver_day(S))
    fifteen = dict(ok, target='15:00',
                   tenors={t: {'value': 4.5, 'stamp': '15:00'} for t in Y.TENORS})
    bad_min = dict(ok, tenors=dict(ok['tenors'], **{'2Y': {'value': 4.5, 'stamp': '15:60'}}))
    for bad in ({S: fifteen}, {S: bad_min}):
        p = tmp_path / 'y.json'
        p.write_text(json.dumps(bad))
        with pytest.raises(Y.LedgerCorrupt):
            Y.load(str(p), strict=True)


def test_infinite_provider_values_are_dropped_and_fall_back():
    payload = {'priceInfos': [{'localDateTime': '20261106155900', 'currentPrice': 'Infinity'},
                              {'localDateTime': '20261106160900', 'currentPrice': '-inf'}]}
    assert Y.parse_naver_chart(payload) == []
    bars = {'barData': {'priceBars': [{'close': 'Infinity', 'tradeTime': '20261106160100'}]}}
    assert Y.parse_cnbc_5d(bars) == []
    naver = naver_day(S)
    naver['2Y'] = Y.parse_naver_chart(payload)                       # 무한대만 온 만기 → 네이버 버림
    c = Y.curve(S, naver, naver_day(S, base=5.0))
    assert c['source'] == 'cnbc'


def test_impossible_provider_stamps_are_dropped_and_fall_back():
    payload = {'priceInfos': [{'localDateTime': '20261106156000', 'currentPrice': 4.5},   # 15:60
                              {'localDateTime': '20261130155900', 'currentPrice': 4.5},   # 11/30 은 있다
                              {'localDateTime': '20260230155900', 'currentPrice': 4.5}]}  # 2/30 은 없다
    got = Y.parse_naver_chart(payload)
    assert got == [('2026-11-30', '15:59', 4.5)]
    bars = {'barData': {'priceBars': [{'close': '4.5', 'tradeTime': '20261106156000'}]}}
    assert Y.parse_cnbc_5d(bars) == []
    naver = naver_day(S)
    naver['10Y'] = Y.parse_naver_chart({'priceInfos': [{'localDateTime': '20261106156000',
                                                         'currentPrice': 4.8}]})
    ledger = {}
    Y.update(ledger, S, set(), naver, lambda: naver_day(S, base=5.0))
    assert ledger[S]['source'] == 'cnbc'                    # 네이버는 통째로 버리고 CNBC


def test_stamp_seconds_and_length_are_validated():
    assert Y._stamp('20261106160099') is None
    assert Y._stamp('2026110616009') is None              # 13자리
    assert Y._stamp('20261106160059x') is None
    assert Y._stamp('20261106160059') == ('2026-11-06', '16:00:59')
    assert Y._stamp('202611061600') == ('2026-11-06', '16:00')
    naver = naver_day(S)
    naver['5Y'] = Y.parse_naver_chart({'priceInfos': [{'localDateTime': '20261106160099',
                                                        'currentPrice': 4.6}]})
    assert Y.curve(S, naver, naver_day(S, base=5.0))['source'] == 'cnbc'


def test_pick_measures_distance_and_window_in_seconds():
    p = pts(S, ('15:59:59', 1.0), ('16:00:59', 2.0))
    assert Y.pick(p, S) == {'value': 1.0, 'stamp': '15:59:59'}       # 1초 vs 59초
    assert Y.pick(pts(S, ('16:15:59', 1.0)), S) is None               # 창(16:15:00) 밖
    assert Y.pick(pts(S, ('16:15:00', 1.0)), S)['stamp'] == '16:15:00'
    assert Y._stamp('20261106155959') == ('2026-11-06', '15:59:59')
    assert Y._stamp('20261106155900') == ('2026-11-06', '15:59')


def test_strict_load_accepts_second_stamps_inside_the_window(tmp_path):
    import json
    import pytest
    ok = Y.curve(S, naver_day(S))
    sec = dict(ok, tenors={t: {'value': 4.5, 'stamp': '15:59:59'} for t in Y.TENORS})
    out = dict(ok, tenors={t: {'value': 4.5, 'stamp': '16:15:01'} for t in Y.TENORS})
    p = tmp_path / 'y.json'
    p.write_text(json.dumps({S: sec}))
    assert Y.load(str(p), strict=True)
    p.write_text(json.dumps({S: out}))
    with pytest.raises(Y.LedgerCorrupt):
        Y.load(str(p), strict=True)
