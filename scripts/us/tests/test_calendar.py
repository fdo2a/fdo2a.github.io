import datetime as dt

from us import calendar as C


# --- KST 병기: 이 리포트를 읽는 사람은 한국에 있다 -----------------------------

def test_kst_follows_us_daylight_saving():
    """ET 는 서머타임이 있고 KST 는 없다 — 시차를 상수로 박으면 연 두 번 틀린다."""
    winter = C.to_kst(dt.date(2026, 1, 14), '08:30')   # EST, UTC-5
    summer = C.to_kst(dt.date(2026, 7, 14), '08:30')   # EDT, UTC-4
    assert winter.strftime('%H:%M') == '22:30'
    assert summer.strftime('%H:%M') == '21:30'


def test_kst_rolls_to_the_next_day_for_an_afternoon_release():
    """14:00 ET FOMC 성명은 한국에서 다음 날 새벽이다."""
    kst = C.to_kst(dt.date(2026, 9, 16), '14:00')
    assert kst.date() == dt.date(2026, 9, 17)
    assert kst.strftime('%H:%M') == '03:00'


def test_an_unknown_time_yields_no_kst():
    assert C.to_kst(dt.date(2026, 9, 16), None) is None


# --- 만기: 순수 계산이라 출처가 필요 없다 --------------------------------------

def test_monthly_expiry_is_the_third_friday():
    assert C.monthly_expiry(2026, 9) == dt.date(2026, 9, 18)
    assert C.monthly_expiry(2026, 1) == dt.date(2026, 1, 16)


def test_monthly_expiry_when_the_month_opens_on_a_friday():
    """1일이 금요일이면 셋째 금요일은 15일이다 — 「15일 언저리」로 셈하면 틀린다."""
    first = dt.date(2026, 5, 1)
    assert first.weekday() == 4
    assert C.monthly_expiry(2026, 5) == dt.date(2026, 5, 15)


def test_quad_witching_is_the_four_quarter_end_expiries():
    got = C.quad_witching(2026)
    assert got == [C.monthly_expiry(2026, m) for m in (3, 6, 9, 12)]
    assert all(d.weekday() == 4 for d in got)


def test_expiry_events_mark_quad_witching_apart():
    evs = C.expiry_events(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert len(evs) == 1
    assert evs[0]['date'] == '2026-09-18'
    assert '쿼드러플' in evs[0]['name_ko']
    plain = C.expiry_events(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert '쿼드러플' not in plain[0]['name_ko']


# --- 연준 블랙아웃: 회의일이 주어졌을 때만 계산한다 ----------------------------

def test_blackout_runs_from_the_second_preceding_saturday_to_the_thursday_after():
    start, end = C.blackout_window(dt.date(2026, 9, 16))   # 수요일 회의
    assert start.weekday() == 5 and end.weekday() == 3
    assert start == dt.date(2026, 9, 5)
    assert end == dt.date(2026, 9, 17)
    assert (dt.date(2026, 9, 16) - start).days >= 11


def test_blackout_membership():
    meetings = [dt.date(2026, 9, 16)]
    assert C.in_blackout(dt.date(2026, 9, 8), meetings) == dt.date(2026, 9, 16)
    assert C.in_blackout(dt.date(2026, 9, 4), meetings) is None
    assert C.in_blackout(dt.date(2026, 9, 18), meetings) is None


def test_no_meeting_table_means_no_fed_events_and_a_recorded_gap():
    """일정표가 비면 **지어내지 않고 빠진다.** 삭제가 창작보다 낫다."""
    book = C.build(dt.date(2026, 9, 11), meetings=[], horizon_days=10)
    assert [e for e in book['events'] if e['kind'] == 'fomc'] == []
    assert 'fomc' in book['missing']
    assert book['complete'] is False


def test_a_stale_meeting_table_is_not_used():
    """마지막 회의일이 과거면 그 표는 낡은 것이다 — 조용히 쓰면 안 된다."""
    book = C.build(dt.date(2026, 9, 11), meetings=[dt.date(2026, 1, 28)],
                   horizon_days=10)
    assert [e for e in book['events'] if e['kind'] == 'fomc'] == []
    assert 'fomc' in book['missing']


def test_a_supplied_meeting_shows_up_with_both_clocks():
    book = C.build(dt.date(2026, 9, 11), meetings=[dt.date(2026, 9, 16)],
                   horizon_days=10)
    fomc = [e for e in book['events'] if e['kind'] == 'fomc']
    assert len(fomc) == 1
    assert fomc[0]['date'] == '2026-09-16'
    assert fomc[0]['time_et'] == '14:00'
    assert fomc[0]['time_kst'].startswith('2026-09-17')
    assert fomc[0]['status'] == 'confirmed'
    assert 'fomc' not in book['missing']


def test_blackout_is_reported_when_today_sits_inside_it():
    book = C.build(dt.date(2026, 9, 8), meetings=[dt.date(2026, 9, 16)],
                   horizon_days=10)
    assert book['blackout']['active'] is True
    assert book['blackout']['until'] == '2026-09-17'
    quiet = C.build(dt.date(2026, 9, 4), meetings=[dt.date(2026, 9, 16)],
                    horizon_days=10)
    assert quiet['blackout']['active'] is False


# --- 조립 ---------------------------------------------------------------------

def test_events_are_sorted_and_clipped_to_the_horizon():
    book = C.build(dt.date(2026, 9, 11), meetings=[dt.date(2026, 9, 16)],
                   horizon_days=10)
    dates = [e['date'] for e in book['events']]
    assert dates == sorted(dates)
    assert all(book['report_date'] < d <= '2026-09-25' for d in dates)


def test_the_book_never_reaches_back_before_the_report_date():
    book = C.build(dt.date(2026, 9, 18), meetings=[], horizon_days=10)
    assert all(e['date'] > '2026-09-18' for e in book['events'])


def test_every_event_carries_the_fields_the_writer_contract_needs():
    book = C.build(dt.date(2026, 9, 11), meetings=[dt.date(2026, 9, 16)],
                   horizon_days=10)
    assert book['events']
    for e in book['events']:
        assert set(('key', 'kind', 'name_ko', 'date', 'status', 'source')) <= set(e)
        assert e['status'] in ('confirmed', 'scheduled', 'tentative')


def test_the_statement_time_is_not_the_press_conference_time():
    """03:00 과 03:30 중 틀린 쪽에 깨어 있게 만들지 않는다."""
    ev = C.fomc_events([dt.date(2026, 10, 28)], dt.date(2026, 10, 1),
                       dt.date(2026, 11, 30))[0]
    assert ev['name_ko'] == 'FOMC 성명'
    assert ev['time_et'] == '14:00'
    assert '기자회견' in ev['watch']


def test_the_dot_plot_is_promised_only_at_quarterly_meetings():
    """점도표는 여덟 번 중 네 번만 나온다."""
    quarterly = C.fomc_events([dt.date(2026, 9, 16)], dt.date(2026, 9, 1),
                              dt.date(2026, 9, 30))[0]
    other = C.fomc_events([dt.date(2026, 10, 28)], dt.date(2026, 10, 1),
                          dt.date(2026, 10, 31))[0]
    assert '점도표' in quarterly['watch']
    assert '점도표' not in other['watch']
