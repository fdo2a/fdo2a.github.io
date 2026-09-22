"""moomoo 보조 입력의 **정규화와 상태 계약**.

이 모듈이 막는 것은 하나다 — 검증되지 않은 값이 발행 입력으로 승인되는 것.
codex 설계 검토(2026-09-22)의 P1 여덟 개가 전부 여기로 들어온다.
"""

import datetime as dt

import pytest

from us import moomoo_forward as M


# --- 상태 어휘: 「없다」에도 종류가 있다 ---------------------------------------

def test_status_vocabulary_is_closed():
    """ok/empty/partial/unavailable/stale/invalid 여섯뿐이다.

    부분 실패·정상 0건·권한 없음·노후화를 한 단어로 뭉치면 유효한 격주 자료를
    버리거나 낡은 자료에 오늘 날짜만 붙여 승인하게 된다.
    """
    assert M.STATUSES == ('ok', 'empty', 'partial', 'unavailable', 'stale', 'invalid')


def test_envelope_separates_fetch_time_from_source_time():
    """수집시각과 원자료 기준시각은 다른 축이다 — 오늘 다시 저장했어도 원자료가
    어제 것이면 새 자료가 아니다."""
    env = M.envelope('fedwatch', rows=[{'a': 1}], status='ok',
                     fetched_at='2026-09-22T07:00:00+09:00',
                     source_as_of='2026-09-21')
    assert env['fetched_at'] == '2026-09-22T07:00:00+09:00'
    assert env['source_as_of'] == '2026-09-21'
    assert env['status'] == 'ok'
    assert env['kind'] == 'fedwatch'


def test_envelope_rejects_an_unknown_status():
    with pytest.raises(ValueError):
        M.envelope('fedwatch', rows=[], status='fine',
                   fetched_at='2026-09-22T07:00:00+09:00')


def test_unknown_source_time_stays_unknown():
    """원천 시각을 모르면 모른다고 남긴다. 수집시각으로 대체하지 않는다."""
    env = M.envelope('ratings', rows=[{'a': 1}], status='ok',
                     fetched_at='2026-09-22T07:00:00+09:00')
    assert env['source_as_of'] is None


def test_empty_is_not_ok_and_needs_a_confirmed_range():
    """정상 0건은 조회가 성공하고 범위가 확인될 때만 인정한다."""
    env = M.envelope('ratings', rows=[], status='empty',
                     fetched_at='2026-09-22T07:00:00+09:00',
                     query_range={'begin': '2026-09-22', 'end': '2026-09-22'})
    assert env['status'] == 'empty'
    assert env['query_range']['begin'] == '2026-09-22'
    with pytest.raises(ValueError):
        M.envelope('ratings', rows=[], status='empty',
                   fetched_at='2026-09-22T07:00:00+09:00')


# --- FedWatch: 확률은 사건에 묶여야 비교할 수 있다 -----------------------------

FW_ROWS = [
    {'meeting_date': '2026-10-28', 'target_range': '3.75-4.00%', 'probability': 42.4},
    {'meeting_date': '2026-10-28', 'target_range': '4.00-4.25%', 'probability': 57.6},
    {'meeting_date': '2026-12-09', 'target_range': '3.75-4.00%', 'probability': 9.2},
    {'meeting_date': '2026-12-09', 'target_range': '4.00-4.25%', 'probability': 45.7},
    {'meeting_date': '2026-12-09', 'target_range': '4.25-4.50%', 'probability': 45.1},
]


def test_probability_carries_the_event_it_belongs_to():
    """회의일·구간 하단/상단·관측시각·공급자가 확률에 붙어 있어야 전일 비교가 된다."""
    out = M.normalize_fedwatch(FW_ROWS, observed_at='2026-09-22T07:00:00+09:00',
                               provider='moomoo/CME FedWatch')
    first = out[0]['ranges'][0]
    assert out[0]['meeting_date'] == '2026-10-28'
    assert first['lower_pct'] == 3.75
    assert first['upper_pct'] == 4.00
    assert first['probability_pct'] == 42.4
    assert out[0]['observed_at'] == '2026-09-22T07:00:00+09:00'
    assert out[0]['provider'] == 'moomoo/CME FedWatch'


def test_meetings_come_back_sorted_and_grouped():
    out = M.normalize_fedwatch(FW_ROWS, observed_at='2026-09-22T07:00:00+09:00',
                               provider='p')
    assert [m['meeting_date'] for m in out] == ['2026-10-28', '2026-12-09']
    assert len(out[1]['ranges']) == 3


def test_a_distribution_that_does_not_sum_is_rejected_not_normalised():
    """합계 검사를 통과시키려고 임의 정규화하지 않는다."""
    bad = [{'meeting_date': '2026-10-28', 'target_range': '4.00-4.25%', 'probability': 40.0}]
    with pytest.raises(M.InvalidProbability):
        M.normalize_fedwatch(bad, observed_at='x', provider='p')


def test_a_duplicate_range_is_rejected():
    dup = FW_ROWS[:2] + [dict(FW_ROWS[1])]
    with pytest.raises(M.InvalidProbability):
        M.normalize_fedwatch(dup, observed_at='x', provider='p')


@pytest.mark.parametrize('p', [-0.1, 100.1, float('nan'), float('inf')])
def test_a_probability_outside_the_range_is_rejected(p):
    bad = [{'meeting_date': '2026-10-28', 'target_range': '4.00-4.25%', 'probability': p}]
    with pytest.raises(M.InvalidProbability):
        M.normalize_fedwatch(bad, observed_at='x', provider='p')


def test_comparison_needs_the_same_event_and_provider():
    """비교 불가능하면 변화량은 없음으로 처리한다 — 공급자가 바뀐 차이를
    시장의 15%p 변화로 오해하면 정책 시점이 근거 없이 움직인다."""
    a = M.normalize_fedwatch(FW_ROWS, observed_at='t1', provider='p')
    b = M.normalize_fedwatch(FW_ROWS, observed_at='t2', provider='OTHER')
    assert M.probability_delta(a, b, meeting_date='2026-10-28',
                               lower_pct=4.00) is None
    same = M.normalize_fedwatch(FW_ROWS, observed_at='t2', provider='p')
    assert M.probability_delta(a, same, meeting_date='2026-10-28',
                               lower_pct=4.00) == 0.0


def test_no_delta_when_the_meeting_is_absent_on_one_side():
    a = M.normalize_fedwatch(FW_ROWS, observed_at='t1', provider='p')
    b = M.normalize_fedwatch(FW_ROWS[:2], observed_at='t2', provider='p')
    assert M.probability_delta(a, b, meeting_date='2026-12-09',
                               lower_pct=4.25) is None


# --- FOMC 일정: 공식이 정본, moomoo 는 대조 ------------------------------------

def test_moomoo_never_becomes_the_official_schedule():
    """`calendar.py` 가 출처를 「연준 공표 일정」·`confirmed` 로 고정해 인쇄한다.
    검증 안 된 출처를 그 자리에 넣으면 더 강한 출처로 둔갑한다."""
    book = M.fomc_book(official=None, moomoo_dates=['2026-10-28', '2026-12-09'],
                       checked_at='2026-09-22')
    assert book['meetings'] == []
    assert 'official' in book['missing']
    assert book['cross_check']['moomoo'] == ['2026-10-28', '2026-12-09']


def test_official_schedule_keeps_the_meeting_that_just_ended():
    """직전 회의가 빠지면 그 주 목요일 블랙아웃 판정 근거가 사라진다.
    codex 재현: [09-16, 10-28] 이면 09-17 에 blackout active, [10-28] 만이면 아니다."""
    book = M.fomc_book(official={'meetings': ['2026-09-16', '2026-10-28', '2026-12-09'],
                                 'source': 'https://www.federalreserve.gov/...',
                                 'verified_at': '2026-09-22'},
                       moomoo_dates=['2026-10-28', '2026-12-09'],
                       checked_at='2026-09-22', report_date=dt.date(2026, 9, 17))
    assert '2026-09-16' in book['meetings']
    assert book['missing'] == []


def test_a_conflict_between_sources_is_recorded_not_resolved():
    """출처가 어긋나면 더 최근 파일을 자동으로 택하지 않는다."""
    book = M.fomc_book(official={'meetings': ['2026-10-28'], 'source': 's',
                                 'verified_at': '2026-09-22'},
                       moomoo_dates=['2026-10-27'], checked_at='2026-09-22')
    assert book['cross_check']['agrees'] is False
    assert book['meetings'] == ['2026-10-28']


def test_an_expired_official_check_stops_authorising_the_table():
    """공식 확인에 유효기간을 둔다 — 미래 날짜가 하나 남았다는 사실을
    최신 확인의 대용물로 쓰지 않는다."""
    book = M.fomc_book(official={'meetings': ['2027-06-09'], 'source': 's',
                                 'verified_at': '2026-01-01'},
                       moomoo_dates=[], checked_at='2026-09-22',
                       report_date=dt.date(2026, 9, 22), max_age_days=45)
    assert book['meetings'] == []
    assert 'official_stale' in book['missing']


# --- 컨센서스: 이름으로 잇지 않는다 --------------------------------------------

def test_consensus_needs_an_allowlisted_identity():
    """CPI YoY 와 MoM, headline 과 core 를 이름만으로 연결할 수 없다."""
    rows = [{'title': 'CPI (YoY)', 'country': 'United States', 'consensus': '3.1%',
             'previous': '3.0%', 'actual': '', 'star': 'HIGH',
             'timestamp': 1790085600.0}]
    out = M.normalize_consensus(rows, observed_at='t')
    assert out[0]['metric_key'] == 'cpi_yoy'
    assert out[0]['unit'] == 'pct'
    assert out[0]['consensus'] == 3.1


def test_an_unmapped_indicator_is_dropped_with_a_reason():
    """모호하면 Forecast 를 비우고 이유를 남긴다 — 틀리게 붙이면 빈 칸보다 나쁘다."""
    rows = [{'title': 'Redbook (YoY)', 'country': 'United States',
             'consensus': '8.5%', 'previous': '8.4%', 'actual': '',
             'star': 'LOW', 'timestamp': 1790081700.0}]
    out = M.normalize_consensus(rows, observed_at='t')
    assert out == []


def test_a_non_us_row_never_enters_the_us_table():
    rows = [{'title': 'CPI (YoY)', 'country': 'Japan', 'consensus': '2.1%',
             'previous': '2.0%', 'actual': '', 'star': 'HIGH',
             'timestamp': 1790085600.0}]
    assert M.normalize_consensus(rows, observed_at='t') == []


def test_consensus_never_overwrites_fred_actual():
    """FRED Actual/Previous 는 정본이다. moomoo 는 Forecast 칸만 채운다."""
    rows = [{'title': 'CPI (YoY)', 'country': 'United States', 'consensus': '3.1%',
             'previous': '9.9%', 'actual': '3.4%', 'star': 'HIGH',
             'timestamp': 1790085600.0}]
    out = M.normalize_consensus(rows, observed_at='t')
    assert 'actual' not in out[0]
    assert 'previous' not in out[0]


# --- 세션 계약: 발행은 KST 화~토다 --------------------------------------------

@pytest.mark.parametrize('kst,expected', [
    (dt.date(2026, 9, 22), dt.date(2026, 9, 21)),   # 화 → 미국 월요일장
    (dt.date(2026, 9, 26), dt.date(2026, 9, 25)),   # 토 → 미국 금요일장
])
def test_target_session_is_the_previous_us_trading_day(kst, expected):
    assert M.target_session(kst) == expected


@pytest.mark.parametrize('kst', [dt.date(2026, 9, 21), dt.date(2026, 9, 27)])
def test_no_target_session_on_a_day_the_report_does_not_publish(kst):
    """월요일 KST 실행은 미국 일요일이라 대상 세션이 없다."""
    assert M.target_session(kst) is None


def test_a_session_that_disagrees_with_the_record_is_not_silently_kept():
    """정본 report_date 와 어긋나면 잠정으로 남기고 발행 때 매칭한다."""
    env = M.envelope('fedwatch', rows=[{'a': 1}], status='ok',
                     fetched_at='2026-09-22T07:00:00+09:00',
                     session='2026-09-21')
    assert M.session_matches(env, report_date='2026-09-21') is True
    assert M.session_matches(env, report_date='2026-09-18') is False


# --- 승인: 파일이 있다는 사실은 권한이 아니다 ---------------------------------

def _fw_env(**kw):
    base = dict(rows=M.normalize_fedwatch(FW_ROWS, observed_at='t', provider='p'),
                status='ok', fetched_at='2026-09-22T07:00:00+09:00',
                session='2026-09-21')
    base.update(kw)
    return M.envelope('fedwatch', **base)


def test_only_a_matching_session_is_approved():
    env = _fw_env()
    assert M.approved_fedwatch(env, report_date='2026-09-21') is not None
    assert M.approved_fedwatch(env, report_date='2026-09-18') is None


def test_a_stale_or_failed_envelope_is_never_approved():
    for status in ('stale', 'partial', 'unavailable', 'invalid'):
        env = _fw_env(status=status, rows=[], query_range={'x': 1}) \
            if status == 'empty' else _fw_env(status=status)
        assert M.approved_fedwatch(env, report_date='2026-09-21') is None


def test_find_probability_needs_the_exact_event():
    book = M.normalize_fedwatch(FW_ROWS, observed_at='t', provider='p')
    assert M.find_probability(book, meeting_date='2026-10-28', lower_pct=4.00) == 57.6
    assert M.find_probability(book, meeting_date='2026-10-28', lower_pct=4.25) is None
    assert M.find_probability(book, meeting_date='2026-11-05', lower_pct=4.00) is None
