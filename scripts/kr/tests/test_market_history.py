import json

from kr.history import index_record, index_series


SNAP = {'report_date': '2026-08-28',
        'indices': {'KOSPI': {'close': 6788.88, 'change_pct': -1.79},
                    'KOSDAQ': {'close': 838.41, 'change_pct': 0.09}}}


def test_record_carries_the_published_closes_verbatim():
    r = index_record(SNAP)
    assert r == {'report_date': '2026-08-28',
                 'indices': {'KOSPI': 6788.88, 'KOSDAQ': 838.41}}


def test_record_drops_an_index_without_a_close():
    snap = json.loads(json.dumps(SNAP))
    snap['indices']['KOSPI'] = {'close': None, 'change_pct': None}
    assert 'KOSPI' not in index_record(snap)['indices']


LEDGER = [{'report_date': '2026-08-21', 'indices': {'KOSPI': 6700.0}},
          {'report_date': '2026-08-27', 'indices': {'KOSPI': 6912.5}},
          {'report_date': '2026-08-28', 'indices': {'KOSPI': 6788.88}}]


def test_index_series_is_dated_and_sorted():
    got = index_series(list(reversed(LEDGER)))
    assert got['KOSPI'] == [('2026-08-21', 6700.0), ('2026-08-27', 6912.5),
                            ('2026-08-28', 6788.88)]


def test_period_return_is_measured_between_published_closes():
    from kr.period import finalize
    agg = {'span': 'weekly', 'key': '2026-W35',
           'sessions': {'2026-08-27': {}, '2026-08-28': {}}}
    out = finalize(agg, index_series(LEDGER))
    # 직전 발행본 종가 6,700.0 대비 6,788.88 — 두 값 모두 발행본에 실린 숫자다
    assert out['indices']['KOSPI']['end'] == 6788.88
    assert abs(out['indices']['KOSPI']['pct'] - 1.3266) < 0.001


# ── 2026-08-30 codex 검토 ─────────────────────────────────────────────────────

def _agg(dates=('2026-08-27', '2026-08-28')):
    return {'span': 'weekly', 'key': '2026-W35',
            'sessions': {d: {} for d in dates}}


def test_an_empty_index_ledger_is_not_complete():
    from kr.period import finalize
    out = finalize(_agg(), {})
    assert out['complete'] is False
    assert out['missing'], out


def test_an_index_missing_on_the_last_day_is_not_complete():
    from kr.period import finalize
    # 08-28 종가가 없다 — 끝값이 08-27 값이 되어 발행본과 갈린다
    series = {'KOSPI': [('2026-08-21', 6700.0), ('2026-08-27', 6912.5)]}
    out = finalize(_agg(), series)
    assert out['complete'] is False
    assert any('KOSPI' in m for m in out['missing']), out['missing']


def test_index_series_keeps_a_name_that_vanished_from_later_rows():
    rows = [{'report_date': '2026-08-27', 'indices': {'KOSPI': 6912.5, 'KOSDAQ': 830.0}},
            {'report_date': '2026-08-28', 'indices': {'KOSPI': 6788.88}}]
    got = index_series(rows)
    assert 'KOSDAQ' in got, got


# ── 거래일 확정과 원장 충돌 — 2026-10-13 02:27 KST 사고 재현 ─────────────────────
# 10/12 예약 실행이 Actions 지연으로 10/13 새벽에 돌았다. yfinance ^KS11 은 아직 10/08 이
# 마지막 행이었고 네이버는 10/12 종가를 줬다 → 10/12 종가가 10/08 행을 덮었다.

import pytest

from kr.history import StaleIndexData, ledger_conflicts, resolve_report_date

REAL = [{'report_date': '2026-10-07', 'indices': {'KOSPI': 6803.9, 'KOSDAQ': 898.43}},
        {'report_date': '2026-10-08', 'indices': {'KOSPI': 6625.93, 'KOSDAQ': 892.27}},
        {'report_date': '2026-10-12', 'indices': {'KOSPI': 6384.24, 'KOSDAQ': 849.19}}]


def test_report_date_follows_the_source_of_the_closes():
    got, _ = resolve_report_date({'KOSPI': '2026-10-12', 'KOSDAQ': '2026-10-12'},
                                 '2026-10-08', '2026-10-13')
    assert got == '2026-10-12'


def test_report_date_falls_back_to_yfinance_then_today():
    assert resolve_report_date({'KOSPI': None}, '2026-10-08', '2026-10-13')[0] == '2026-10-08'
    assert resolve_report_date({}, None, '2026-10-13')[0] == '2026-10-13'


def test_report_date_notes_a_yfinance_disagreement():
    _, notes = resolve_report_date({'KOSPI': '2026-10-12'}, '2026-10-08', '2026-10-13')
    assert any('2026-10-08' in n for n in notes)


def test_report_date_refuses_split_index_dates():
    with pytest.raises(StaleIndexData):
        resolve_report_date({'KOSPI': '2026-10-12', 'KOSDAQ': '2026-10-08'}, None, '2026-10-13')


def test_the_october_13_run_is_refused_as_stale_and_duplicate():
    rec = {'report_date': '2026-10-08', 'indices': {'KOSPI': 6384.24, 'KOSDAQ': 849.19}}
    problems = ledger_conflicts(REAL, rec)
    assert any('2026-10-12' in p and '늦' in p for p in problems)   # 원장 최신보다 이른 날짜
    assert any('같' in p for p in problems)                          # 다른 날짜와 같은 종가


def test_a_holiday_labelled_with_the_previous_close_is_refused():
    rec = {'report_date': '2026-10-09', 'indices': {'KOSPI': 6625.93, 'KOSDAQ': 892.27}}
    assert ledger_conflicts(REAL[:2], rec)


def test_the_next_session_and_a_same_day_rerun_pass():
    nxt = {'report_date': '2026-10-13', 'indices': {'KOSPI': 6035.35, 'KOSDAQ': 837.03}}
    assert ledger_conflicts(REAL, nxt) == []
    rerun = {'report_date': '2026-10-12', 'indices': {'KOSPI': 6384.5, 'KOSDAQ': 849.19}}
    assert ledger_conflicts(REAL, rerun) == []
    assert ledger_conflicts(REAL, REAL[-1]) == []


def test_one_equal_index_alone_is_not_a_duplicate():
    rec = {'report_date': '2026-10-13', 'indices': {'KOSPI': 6384.24, 'KOSDAQ': 837.03}}
    assert ledger_conflicts(REAL, rec) == []


def test_empty_ledger_and_closeless_record_pass():
    assert ledger_conflicts([], REAL[0]) == []
    assert ledger_conflicts(REAL, {'report_date': '2026-10-13', 'indices': {}}) == []
