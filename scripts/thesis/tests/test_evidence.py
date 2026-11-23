"""Evidence the gate computes itself (2026-11-23) — all synthetic, no ticker is in kill today."""

import json
from datetime import date, timedelta

from thesis import evidence as E
from thesis import triggers as T

TODAY = '2026-11-20'


def days_before(n, today=TODAY):
    return (date.fromisoformat(today) - timedelta(days=n)).isoformat()


def snap(price=200.0, bear=100.0, eps=150.0, low=100.0, high=200.0):
    s = {'eps_fy1': eps, 'eps_fy1_low': low, 'eps_fy1_high': high, 'price': price}
    if bear is not None:
        s['bear'] = bear
    return s


def history(n, cross_on=None, today=TODAY, sym='MU'):
    """`n` daily rows ending today; MU drops into the bear zone on `cross_on` (a date)."""
    rows = []
    for i in range(n - 1, -1, -1):
        day = days_before(i, today)
        price = 105.0 if cross_on and day >= cross_on else 200.0
        rows.append({'date': day, 'tickers': {sym: snap(price=price)}})
    return rows


def text(rows):
    return '\n'.join(json.dumps(r) for r in rows) + '\n'


def watch_for(rows, as_of=TODAY, sym='MU'):
    row = dict(rows[-1]['tickers'][sym])
    row['fair_value'] = {'bear': row.get('bear')}
    return {'as_of': as_of, 'complete': True, 'tickers': {sym: row}}


def filing(day, axis='contract', confirmed=True, url=None):
    return {'date': day, 'title': '단일판매ㆍ공급계약해지', 'axis': axis,
            'confirmed': confirmed, 'url': url or f'https://dart.example/{day}'}


def disclosures(events, as_of=TODAY, sym='MU'):
    return {'as_of': as_of, 'tickers': {sym: {'events': events}}, 'missing': []}


# ── history 를 엄격하게 읽는다 ──

def test_clean_history_parses_with_gaps():
    rows = history(5)
    del rows[2]
    parsed, bad = E.parse_history(text(rows))
    assert bad is None and [r['date'] for r in parsed] == [r['date'] for r in rows]


def test_invalid_json_line_makes_history_unusable():
    parsed, bad = E.parse_history(text(history(3)) + '{not json\n')
    assert parsed is None and 'JSON' in bad


def test_duplicate_date_makes_history_unusable():
    rows = history(3)
    parsed, bad = E.parse_history(text(rows + [rows[-1]]))
    assert parsed is None and '두 번' in bad


def test_row_without_date_or_object_is_invalid():
    assert E.parse_history('[1, 2]\n')[0] is None
    assert E.parse_history('{"tickers": {}}\n')[0] is None


def test_missing_history_is_empty_not_invalid():
    assert E.parse_history(None) == ([], None)


# ── 오늘 수치: 낡으면 보류 ──

def test_stale_watch_is_deferred_not_empty():
    rows = history(25)
    hits, reason = E.today_triggers(watch_for(rows, as_of=days_before(1)), rows, TODAY)
    assert hits is None and '오늘 것이 아니다' in reason


def test_fresh_watch_gives_step1_hits():
    rows = history(25, cross_on=TODAY)
    hits, reason = E.today_triggers(watch_for(rows), rows, TODAY)
    assert reason is None
    assert [h['key'] for h in hits['MU']] == ['bear_proximity']


# ── 가격 축: STEP 1 재현, 깊이 필요, 30일 창 ──

def test_bear_crossing_in_window_is_a_price_day():
    rows = history(40, cross_on=days_before(5))
    assert E.price_axis_days(rows, TODAY, 'MU') == [days_before(5)]


def test_short_history_gives_no_price_day_though_trigger_fires():
    rows = history(2, cross_on=TODAY)
    hits, _ = E.today_triggers(watch_for(rows), rows, TODAY)
    assert hits['MU']                        # the trigger still licenses an edit
    assert E.price_axis_days(rows, TODAY, 'MU') == []   # but kill gets no price axis


def test_crossing_older_than_window_is_out():
    rows = history(60, cross_on=days_before(31))
    assert E.price_axis_days(rows, TODAY, 'MU') == []


def test_replay_ignores_rows_after_the_day():
    rows = history(40, cross_on=days_before(5))
    later = E.price_axis_days(rows, days_before(10), 'MU')
    assert later == []


def test_depth_is_counted_up_to_the_day_not_over_the_whole_log():
    """25 rows: a crossing on the 19th row has 19 rows behind it, the 20th has 20."""
    young = history(25, cross_on=days_before(6))        # 19th row
    assert E.price_axis_days(young, TODAY, 'MU') == []
    deep = history(25, cross_on=days_before(5))         # 20th row
    assert E.price_axis_days(deep, TODAY, 'MU') == [days_before(5)]


def test_non_finite_or_non_positive_price_is_an_invalid_line_not_a_crossing():
    """json.loads reads -Infinity / 1e999 / NaN; a price of -inf is below every bear line."""
    for bad in ('-Infinity', 'Infinity', 'NaN', '1e999', '-1e999', '0', '-5',
                'false', 'true', '"105"', '[105]', '{"v": 105}'):
        rows = history(25)
        lines = text(rows).splitlines()
        lines[-1] = lines[-1].replace('"price": 200.0', f'"price": {bad}')
        assert bad in lines[-1]
        parsed, reason = E.parse_history('\n'.join(lines))
        assert parsed is None and reason, bad
        snaps = [disclosures([filing(days_before(3))])]
        out = E.assess(TODAY, ['MU'], watch=watch_for(rows), history_text='\n'.join(lines),
                       disclosures=None, snapshots=snaps)
        mu = out['tickers']['MU']
        assert mu['price_days'] == [] and mu['numeric'] is None, bad
        assert mu['kill_evidence'] == ('contract',), bad


def test_non_finite_watch_defers_numeric():
    rows = history(25, cross_on=TODAY)
    for bad in (float('-inf'), float('nan'), 0, False, '105'):
        watch = watch_for(rows)
        watch['tickers']['MU']['price'] = bad
        hits, reason = E.today_triggers(watch, rows, TODAY)
        assert hits is None and '보류' in reason


def test_false_price_with_a_real_contract_filing_gives_no_price_axis():
    """codex 구현 4회차: yesterday 200 / bear 100, today `false` read as 0 → a crossing."""
    rows = history(25)
    rows[-1]['tickers']['MU']['price'] = False
    out = E.assess(TODAY, ['MU'], watch=watch_for(history(25)), history_text=text(rows),
                   disclosures=None, snapshots=[disclosures([filing(days_before(3))])])
    assert out['tickers']['MU']['kill_evidence'] == ('contract',)
    assert out['tickers']['MU']['numeric'] is None


def test_negative_bear_is_data_not_a_broken_line():
    rows = history(25)
    rows[-1]['tickers']['MU']['bear'] = -40.0
    parsed, reason = E.parse_history(text(rows))
    assert reason is None and E.price_axis_days(parsed, TODAY, 'MU') == []


def test_confirmed_must_be_the_boolean_true():
    for fake in ('false', 'true', 1, 'yes'):
        disc = disclosures([filing(days_before(1), confirmed=fake)])
        out = assess(disc=disc, snaps=[disc])
        assert out['tickers']['MU']['licences'] == [], fake
        assert out['tickers']['MU']['contract_days'] == [], fake


def test_row_without_bear_does_not_crash_or_invent_a_crossing():
    rows = history(40, cross_on=days_before(5))
    assert E.price_axis_days(rows, TODAY, 'MU') == [days_before(5)]
    crossing = next(r for r in rows if r['date'] == days_before(5))
    crossing['tickers']['MU'].pop('bear')          # the crossing day itself, past depth
    del next(r for r in rows if r['date'] == days_before(2))['tickers']['MU']
    assert E.price_axis_days(rows, TODAY, 'MU') == []


# ── 계약 축: 확정 contract 공시만, 창 안, url 중복 제거 ──

def test_confirmed_contract_filing_in_window_counts():
    snaps = [disclosures([filing(days_before(3))]), disclosures([filing(days_before(3))])]
    assert E.contract_axis_days(snaps, TODAY, 'MU') == [days_before(3)]


def test_other_axis_unconfirmed_or_old_filings_do_not_count():
    snaps = [disclosures([filing(days_before(2), axis='capital'),
                          filing(days_before(2), confirmed=False, url='https://x/u'),
                          filing(days_before(31), url='https://x/old')])]
    assert E.contract_axis_days(snaps, TODAY, 'MU') == []


def test_pending_file_with_one_feed_collected_counts_only_that_ticker():
    payload = {'as_of': TODAY, 'pending': True, 'missing': [],
               'tickers': {'MU': {'events': [filing(days_before(1))]}}}
    assert E.contract_axis_days([payload], TODAY, 'MU') == [days_before(1)]
    assert E.contract_axis_days([payload], TODAY, '005930.KS') == []
    out = assess(disc=payload, snaps=[payload])       # the live feed still licenses today
    assert out['tickers']['MU']['licences'] == [f'filing:https://dart.example/{days_before(1)}']
    assert out['tickers']['005930.KS']['licences'] == []
    assert any('pending' in n for n in out['notes'])


def test_kill_evidence_needs_a_day_on_each_axis():
    assert E.kill_evidence(['d'], ['d']) == ('contract', 'price')
    assert E.kill_evidence(['d'], []) == ('price',)
    assert E.kill_evidence([], []) == ()


# ── assess: 허용 근거와 run.json ──

def assess(rows=None, watch=None, disc=None, snaps=None, run=None, **kw):
    rows = rows if rows is not None else history(25)
    return E.assess(TODAY, ['MU', '005930.KS'], watch=watch or watch_for(rows),
                    history_text=text(rows), disclosures=disc,
                    snapshots=snaps or [], run=run, **kw)


def test_quiet_day_has_no_licence():
    out = assess()
    assert out['tickers']['MU']['licences'] == [] and out['problems'] == []


def test_numeric_trigger_licenses():
    out = assess(rows=history(25, cross_on=TODAY))
    assert out['tickers']['MU']['licences'] == ['bear_proximity']


def test_todays_confirmed_filing_licenses_whatever_its_own_date():
    disc = disclosures([filing(days_before(1), axis='capital')])
    assert assess(disc=disc)['tickers']['MU']['licences'] == [
        f'filing:https://dart.example/{days_before(1)}']


def test_yesterdays_file_does_not_license():
    disc = disclosures([filing(days_before(1))], as_of=days_before(1))
    assert assess(disc=disc)['tickers']['MU']['licences'] == []


def test_confirmed_research_event_licenses():
    run = {'events': {'MU': [{'title': 'NVIDIA 공급 발표', 'confirmed': True,
                              'source': 'https://nvidia.example/news'}]}}
    out = assess(run=run)
    assert out['tickers']['MU']['licences'] == ['event:NVIDIA 공급 발표']
    assert out['problems'] == []


def test_unconfirmed_event_does_not_license():
    run = {'events': {'MU': [{'title': '보도', 'confirmed': False,
                              'source': 'https://news.example/a'}]}}
    out = assess(run=run)
    assert out['tickers']['MU']['licences'] == [] and out['problems'] == []


def test_event_without_source_blocks():
    out = assess(run={'events': {'MU': [{'title': '발표', 'confirmed': True}]}})
    assert [p[1] for p in out['problems']] == ['event_shape']
    assert out['tickers']['MU']['licences'] == []


BAD_SOURCES = [
    'https:///www.sec.gov/report',      # no host (codex 구현 2회차)
    'https://[v1.sec.gov]/report',      # bracketed literal a parser unwraps (3회차)
    'https://', 'http:///', 'https://?q=1', 'https://#frag', 'https://:443/x',
    'https://report', 'https://.', 'https://sec..gov/x', 'https://sec.gov../x',
    'https://-sec.gov/x', 'https://sec-.gov/x', 'https://sec_x.gov/x',
    'https://sec.gov:port/x', 'https://sec.gov:99999/x', 'https://sec.gov:0/x',
    'https://sec.gov:/x', 'https://user@sec.gov/x', 'https://user:pw@/x',
    'https://sec.gov/a b', ' https://sec.gov/x', 'https://sec.gov/x\n',
    'https://sec.gov/x\x00', 'https://\\www.sec.gov/x', 'https://www.sec.gov%2Fx',
    'https://[::1]/x', 'https://127.0.0.1/x', 'https://sec.gov.123/x',
    'https://한국거래소.kr/공시',        # host is ASCII only — IDN goes in as xn--
    'https://١٢٣.com/x', 'https://sec.gov/a\u3000b',
    'ftp://sec.gov/x', 'sec.gov/report', 'HTTPS//sec.gov', '', None, 3,
    ['https://sec.gov/x'],
]

GOOD_SOURCES = [
    'https://www.sec.gov/Archives/edgar/data/723125/x.htm',
    'https://www.sec.gov./report',      # root dot — a browser opens it (3회차)
    'http://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261120000001',
    'HTTPS://IR.Example.com:8443/news#top',
    'https://xn--3e0b707e.kr/공시', 'https://a-b.co.kr?x=1',
    'https://sec.gov',
]


def test_event_source_must_be_http_with_a_named_host():
    for src in BAD_SOURCES:
        run = {'events': {'MU': [{'title': '발표', 'confirmed': True, 'source': src}]}}
        out = assess(run=run)
        assert [p[1] for p in out['problems']] == ['event_shape'], src
        assert out['tickers']['MU']['licences'] == [], src
    for src in GOOD_SOURCES:
        run = {'events': {'MU': [{'title': '발표', 'confirmed': True, 'source': src}]}}
        out = assess(run=run)
        assert out['problems'] == [], src
        assert out['tickers']['MU']['licences'] == ['event:발표'], src


def test_numeric_key_as_event_blocks():
    run = {'events': {'MU': [{'key': 'bear_proximity', 'title': 'bear 진입',
                              'confirmed': True, 'source': 'https://ir.example'}]}}
    out = assess(run=run)
    assert [p[1] for p in out['problems']] == ['numeric_as_event']
    assert out['tickers']['MU']['licences'] == []


def test_claimed_trigger_not_recomputed_is_fabricated():
    out = assess(run={'triggers': {'MU': [{'key': 'consensus_swing'}]}})
    assert [p[1] for p in out['problems']] == ['fabricated_evidence']


def test_claimed_trigger_on_deferred_day_is_fabricated():
    rows = history(25, cross_on=TODAY)
    out = assess(rows=rows, watch=watch_for(rows, as_of=days_before(1)),
                 run={'triggers': {'MU': ['bear_proximity']}})
    assert out['tickers']['MU']['numeric'] is None
    assert [p[1] for p in out['problems']] == ['fabricated_evidence']


def test_claimed_axis_not_computed_is_fabricated():
    out = assess(run={'kill_evidence': {'MU': ['price', 'contract']}})
    assert [p[1] for p in out['problems']] == ['fabricated_evidence', 'fabricated_evidence']


def test_matching_claims_pass():
    rows = history(25, cross_on=TODAY)
    out = assess(rows=rows, run={'triggers': {'MU': [{'key': 'bear_proximity'}]},
                                 'kill_evidence': {'MU': ['price']}})
    assert out['problems'] == []
    assert out['tickers']['MU']['kill_evidence'] == ('price',)


def test_invalid_history_defers_numeric_and_price_axis():
    rows = history(25, cross_on=TODAY)
    out = E.assess(TODAY, ['MU'], watch=watch_for(rows),
                   history_text=text(rows) + 'garbage\n', disclosures=None, snapshots=[])
    mu = out['tickers']['MU']
    assert mu['numeric'] is None and mu['price_days'] == [] and mu['licences'] == []
    assert any('판정 불가' in n for n in out['notes'])


def test_history_refused_by_provenance_defers_everything_numeric():
    rows = history(25, cross_on=TODAY)
    out = assess(rows=rows, history_problem='history.jsonl 이 수집 봇 커밋이 아니다')
    assert out['tickers']['MU']['numeric'] is None
    assert out['tickers']['MU']['price_days'] == []


def test_both_axes_open_kill_evidence():
    rows = history(40, cross_on=days_before(4))
    out = assess(rows=rows, snaps=[disclosures([filing(days_before(2))])])
    assert out['tickers']['MU']['kill_evidence'] == ('contract', 'price')


def test_quiet_uses_the_same_numeric_function(tmp_path, monkeypatch, capsys):
    import thesis_quiet
    assert not hasattr(thesis_quiet, 'numeric_triggers')
    rows = history(25)
    d = _quiet_dir(tmp_path, rows, watch_for(rows))
    calls = []
    monkeypatch.setattr(E, 'today_triggers', lambda *a: calls.append(a) or (
        {'MU': [{'key': 'bear_proximity', 'message': 'sentinel'}]}, None))
    assert thesis_quiet.main(['--data', str(d), '--today', TODAY]) == 10
    assert calls and 'sentinel' in capsys.readouterr().out


def test_numeric_name_inside_a_title_is_still_numeric():
    run = {'events': {'MU': [{'title': 'bear_proximity 진입', 'confirmed': True,
                              'source': 'https://example.com/x'}]}}
    assert [p[1] for p in assess(run=run)['problems']] == ['numeric_as_event']


def _quiet_dir(tmp_path, rows, watch, extra=''):
    import thesis_quiet  # noqa: F401
    (tmp_path / 'history.jsonl').write_text(text(rows) + extra, encoding='utf-8')
    (tmp_path / 'watch.json').write_text(json.dumps(watch), encoding='utf-8')
    return tmp_path


def test_quiet_stale_watch_lists_no_numeric_trigger(tmp_path, capsys):
    import thesis_quiet
    rows = history(25, cross_on=TODAY)
    d = _quiet_dir(tmp_path, rows, watch_for(rows, as_of=days_before(1)))
    assert thesis_quiet.main(['--data', str(d), '--today', TODAY]) == 10
    out = capsys.readouterr().out
    assert '오늘 것이 아니다' in out and '수치 트리거' not in out


def test_quiet_invalid_history_is_not_quiet(tmp_path, capsys):
    import thesis_quiet
    rows = history(25)
    d = _quiet_dir(tmp_path, rows, watch_for(rows), extra='garbage\n')
    assert thesis_quiet.main(['--data', str(d), '--today', TODAY]) == 10
    assert 'JSON 이 아니다' in capsys.readouterr().out


def test_quiet_deferred_for_an_unreadable_number_is_not_quiet(tmp_path, capsys):
    """codex 구현 4회차: today's watch with price NaN — the helper defers, so QUIET must not
    end the run before STEP 1."""
    import thesis_quiet
    rows = history(25)
    watch = watch_for(rows)
    watch['tickers']['MU']['price'] = float('nan')
    d = _quiet_dir(tmp_path, rows, watch)
    assert thesis_quiet.main(['--data', str(d), '--today', TODAY]) == 10
    out = capsys.readouterr().out
    assert 'THESIS_CHECK' in out and '보류' in out

