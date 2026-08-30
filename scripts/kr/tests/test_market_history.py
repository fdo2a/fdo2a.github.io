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
