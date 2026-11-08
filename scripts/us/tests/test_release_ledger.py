"""새 발표 원장 — 매일 「오늘 처음 본 숫자」를 덧붙이기만 하는 기록.

주간 레짐 점검이 이 원장을 기간 전체로 읽는다. 일간 `new_releases` 는 어제 책
(macro.json.last_seen)과 견주므로 같은 날 재실행·책 미승격에 흔들린다 — 원장은 자기
마지막 상태와 견준다(2026-11-08 설계).
"""

import json

import pytest

from us import release_ledger as L

GEN = '2026-11-03 07:42 KST'


def ind(name, ref, actual, axis='Labor', direction='개선', vs_prev='개선', role=None):
    r = {'name': name, 'label_ko': name, 'axis': axis, 'ref_period': ref,
         'actual': actual, 'direction': direction, 'vs_prev': vs_prev}
    if role:
        r['role'] = role
    return r


def inputs(report_date, indicators, gen=GEN, econ_roles=None):
    mm = {'report_date': report_date, 'generated': gen, 'indicators': indicators}
    market = {'report_date': report_date, 'generated': gen}
    econ = {'generated': gen,
            'indicators': [{'name': i['name'], **({'role': econ_roles[i['name']]}
                                                  if econ_roles and i['name'] in econ_roles
                                                  else {})}
                           for i in indicators]}
    return mm, econ, market


def calendar(report_date, events, horizon=10):
    return {'report_date': report_date, 'horizon_days': horizon,
            'events': [{'key': f'release-{slug}-{d.replace("-", "")}', 'kind': 'release',
                        'date': d, 'status': status}
                       for slug, d, status in events]}


def run(rows, report_date, indicators, cal=None, run_id='r1', **kw):
    mm, econ, market = inputs(report_date, indicators, **kw)
    new, warnings = L.record(rows, mm, econ, market, cal, run_id)
    return rows + new, new, warnings


def kinds(rows, kind):
    return [r for r in rows if r['kind'] == kind]


# ---- 첫 실행(부트스트랩) ---------------------------------------------------

def test_bootstrap_records_a_baseline_and_no_release():
    rows, new, _ = run([], '2026-11-02', [ind('JOLTS Job Openings', '2026-08-01', 7190.0)])
    assert [r['kind'] for r in new] == ['scan', 'baseline']
    assert new[0]['baseline'] is True
    assert kinds(rows, 'release') == []


def test_baseline_keeps_the_value_so_a_revision_can_be_detected_later():
    rows, _, _ = run([], '2026-11-02', [ind('Durable Goods Orders MoM', '2026-09-01', 1.84)])
    rows, new, _ = run(rows, '2026-11-03', [ind('Durable Goods Orders MoM', '2026-09-01', 1.91)])
    rev = kinds(new, 'revision')
    assert len(rev) == 1 and rev[0]['actual'] == 1.91 and rev[0]['prior_actual'] == 1.84
    assert kinds(new, 'release') == []


# ---- 보통의 새 발표 ---------------------------------------------------------

def test_a_new_ref_period_is_a_release_with_its_trend_and_vs_prev():
    rows, _, _ = run([], '2026-11-02', [ind('JOLTS Job Openings', '2026-08-01', 7190.0)])
    cal = calendar('2026-11-02', [('jolts', '2026-11-03', 'confirmed')])
    rows, new, _ = run(rows, '2026-11-03',
                       [ind('JOLTS Job Openings', '2026-09-01', 7523.0, direction='보합')], cal)
    rel = kinds(new, 'release')[0]
    assert rel['id'] == 'JOLTS Job Openings|2026-09-01'
    assert rel['trend'] == '보합' and rel['vs_prev'] == '개선'
    assert rel['detected_on'] == '2026-11-03' and rel['since'] == '2026-11-02'
    assert rel['official_date'] == '2026-11-03' and rel['date_source'] == 'calendar'
    assert rel['calendar_report_date'] == '2026-11-02'
    assert rel['gap'] is False
    assert new[0]['kind'] == 'scan' and new[0]['baseline'] is False


def test_role_comes_from_the_indicator_row_then_the_econ_file_then_defaults_to_scored():
    rows, _, _ = run([], '2026-11-02', [ind('A', '2026-08-01', 1.0), ind('B', '2026-08-01', 1.0),
                                        ind('C', '2026-08-01', 1.0)])
    rows, new, _ = run(rows, '2026-11-03',
                       [ind('A', '2026-09-01', 2.0, role='anatomy'), ind('B', '2026-09-01', 2.0),
                        ind('C', '2026-09-01', 2.0)],
                       econ_roles={'B': 'anatomy'})
    roles = {r['name']: r['role'] for r in kinds(new, 'release')}
    assert roles == {'A': 'anatomy', 'B': 'anatomy', 'C': 'scored'}


# ---- 같은 날 재실행 ---------------------------------------------------------

def test_a_rerun_on_the_same_day_adds_a_scan_but_no_duplicate_release():
    rows, _, _ = run([], '2026-11-05', [ind('Initial Jobless Claims', '2026-10-24', 190000.0)])
    rows, first, _ = run(rows, '2026-11-06', [ind('Initial Jobless Claims', '2026-10-31', 189000.0)],
                         run_id='a')
    rows, again, _ = run(rows, '2026-11-06', [ind('Initial Jobless Claims', '2026-10-31', 189000.0)],
                         run_id='b', gen='2026-11-06 09:13 KST')
    assert len(kinds(first, 'release')) == 1
    assert [r['kind'] for r in again] == ['scan']
    assert len(kinds(rows, 'release')) == 1


def test_a_release_first_seen_on_a_rerun_is_still_recorded():
    rows, _, _ = run([], '2026-11-05', [ind('A', '2026-09-01', 1.0)])
    rows, _, _ = run(rows, '2026-11-06', [ind('A', '2026-09-01', 1.0)], run_id='a')
    rows, again, _ = run(rows, '2026-11-06', [ind('A', '2026-10-01', 2.0)], run_id='b',
                         gen='2026-11-06 09:13 KST')
    assert len(kinds(again, 'release')) == 1


def test_the_same_run_id_twice_writes_nothing():
    rows, _, _ = run([], '2026-11-05', [ind('A', '2026-09-01', 1.0)], run_id='x')
    rows, again, _ = run(rows, '2026-11-05', [ind('A', '2026-09-01', 1.0)], run_id='x')
    assert again == []


def test_a_rerun_reads_the_ledger_not_the_promoted_book():
    """11/05 를 11/06 09:13 에 재실행하자 일간 new_releases 가 [] 가 됐다. 원장은 영향 없다."""
    rows, _, _ = run([], '2026-11-04', [ind('A', '2026-10-24', 1.0)])
    rows, _, _ = run(rows, '2026-11-05', [ind('A', '2026-10-31', 2.0)], run_id='a')
    assert len(kinds(rows, 'release')) == 1   # 책 승격 여부와 무관


# ---- 개정 -------------------------------------------------------------------

def test_a_revision_is_recorded_each_time_the_value_changes():
    rows, _, _ = run([], '2026-11-02', [ind('A', '2026-09-01', 1.0)])
    for day, val in (('2026-11-03', 2.0), ('2026-11-04', 1.0), ('2026-11-05', 2.0)):
        rows, _, _ = run(rows, day, [ind('A', '2026-09-01', val)])
    revs = kinds(rows, 'revision')
    assert [r['actual'] for r in revs] == [2.0, 1.0, 2.0]
    assert len({r['id'] for r in revs}) == 3


def test_an_unchanged_reading_writes_only_the_scan():
    rows, _, _ = run([], '2026-11-02', [ind('A', '2026-09-01', 1.0)])
    rows, new, _ = run(rows, '2026-11-03', [ind('A', '2026-09-01', 1.0)])
    assert [r['kind'] for r in new] == ['scan']


def test_a_ref_period_going_backward_warns_and_writes_no_row():
    rows, _, _ = run([], '2026-11-02', [ind('A', '2026-09-01', 1.0)])
    rows, new, warnings = run(rows, '2026-11-03', [ind('A', '2026-08-01', 0.5)])
    assert [r['kind'] for r in new] == ['scan']
    assert any('A' in w for w in warnings)


# ---- 처음 보는 지표 -----------------------------------------------------------

def test_a_name_added_later_is_a_baseline_not_a_release():
    rows, _, _ = run([], '2026-11-02', [ind('A', '2026-09-01', 1.0)])
    rows, new, _ = run(rows, '2026-11-03', [ind('A', '2026-09-01', 1.0),
                                             ind('Housing Starts', '2026-09-01', 1.3)])
    assert [r['kind'] for r in new] == ['scan', 'baseline']
    assert new[0]['baseline'] is False


# ---- 입력 묶음 검증 ----------------------------------------------------------

def test_files_from_different_runs_write_nothing():
    mm, econ, market = inputs('2026-11-03', [ind('A', '2026-09-01', 1.0)])
    market['generated'] = '2026-11-03 09:00 KST'
    new, warnings = L.record([], mm, econ, market, None, 'r')
    assert new == [] and warnings


def test_report_dates_that_disagree_write_nothing():
    mm, econ, market = inputs('2026-11-03', [ind('A', '2026-09-01', 1.0)])
    market['report_date'] = '2026-11-04'
    new, _ = L.record([], mm, econ, market, None, 'r')
    assert new == []


def test_a_date_older_than_the_newest_scan_is_refused():
    rows, _, _ = run([], '2026-11-05', [ind('A', '2026-09-01', 1.0)])
    rows, new, warnings = run(rows, '2026-11-04', [ind('A', '2026-10-01', 2.0)])
    assert new == [] and warnings


# ---- 공식 발표일 --------------------------------------------------------------

def _two_days(cal, ref_new='2026-10-01', since_day='2026-11-05', day='2026-11-06',
              name='Nonfarm Payrolls (chg)', ref_old='2026-09-01'):
    rows, _, _ = run([], since_day, [ind(name, ref_old, 1.0)])
    rows, new, _ = run(rows, day, [ind(name, ref_new, 2.0)], cal)
    return kinds(new, 'release')[0]


def test_official_date_needs_exactly_one_confirmed_event_in_the_window():
    two = calendar('2026-11-05', [('employment', '2026-11-06', 'confirmed'),
                                  ('employment', '2026-11-06', 'confirmed')])
    assert _two_days(two)['official_date'] is None
    tentative = calendar('2026-11-05', [('employment', '2026-11-06', 'tentative')])
    assert _two_days(tentative)['official_date'] is None


def test_a_calendar_written_today_or_too_old_is_not_trusted():
    today = calendar('2026-11-06', [('employment', '2026-11-06', 'confirmed')])
    assert _two_days(today)['official_date'] is None
    old = calendar('2026-10-20', [('employment', '2026-11-06', 'confirmed')], horizon=10)
    assert _two_days(old)['official_date'] is None
    assert _two_days(None)['official_date'] is None


def test_an_event_before_the_last_observation_is_outside_the_window():
    cal = calendar('2026-11-04', [('employment', '2026-11-05', 'confirmed')])
    assert _two_days(cal)['official_date'] is None


def test_skipping_a_ref_period_is_a_gap_and_gets_no_official_date():
    cal = calendar('2026-11-05', [('employment', '2026-11-06', 'confirmed')])
    rel = _two_days(cal, ref_new='2026-11-01')
    assert rel['gap'] is True and rel['official_date'] is None


def test_weekly_and_quarterly_steps_are_not_gaps():
    cal = calendar('2026-11-04', [('claims', '2026-11-05', 'confirmed')])
    rel = _two_days(cal, name='Initial Jobless Claims', ref_old='2026-10-24',
                    ref_new='2026-10-31', since_day='2026-11-04', day='2026-11-05')
    assert rel['gap'] is False and rel['official_date'] == '2026-11-05'
    cal = calendar('2026-10-28', [('gdp', '2026-10-29', 'confirmed')])
    rel = _two_days(cal, name='Real GDP Growth QoQ (ann.)', ref_old='2026-04-01',
                    ref_new='2026-07-01', since_day='2026-10-28', day='2026-10-29')
    assert rel['gap'] is False and rel['official_date'] == '2026-10-29'


def test_since_is_the_indicators_own_last_observation():
    """월요일에 그 지표만 빠졌다면 창은 그 지표가 마지막으로 보인 날부터다."""
    rows, _, _ = run([], '2026-11-02', [ind('A', '2026-09-01', 1.0), ind('B', '2026-09-01', 1.0)])
    rows, _, _ = run(rows, '2026-11-03', [ind('B', '2026-09-01', 1.0)])      # A 빠짐
    rows, new, _ = run(rows, '2026-11-04', [ind('A', '2026-10-01', 2.0), ind('B', '2026-09-01', 1.0)])
    assert kinds(new, 'release')[0]['since'] == '2026-11-02'


# ---- 파일 쓰기 --------------------------------------------------------------

def _scan(day):
    return {'id': f'scan|{day}|a', 'kind': 'scan', 'report_date': day, 'observed': []}


def test_append_writes_every_row_of_a_run_and_keeps_old_rows(tmp_path):
    path = tmp_path / 'releases.jsonl'
    L.append_rows(str(path), [_scan('2026-11-02')])
    L.append_rows(str(path), [_scan('2026-11-03'),
                              {'id': 'A|2026-10-01', 'kind': 'release', 'name': 'A',
                               'ref_period': '2026-10-01', 'detected_on': '2026-11-03'}])
    got = [json.loads(x) for x in path.read_text().splitlines()]
    assert [r['id'] for r in got] == ['scan|2026-11-02|a', 'scan|2026-11-03|a', 'A|2026-10-01']


def test_append_refuses_an_id_that_already_exists(tmp_path):
    path = tmp_path / 'releases.jsonl'
    L.append_rows(str(path), [_scan('2026-11-02')])
    with pytest.raises(ValueError):
        L.append_rows(str(path), [_scan('2026-11-02')])


def test_a_corrupt_line_stops_reading_and_writing(tmp_path):
    path = tmp_path / 'releases.jsonl'
    path.write_text(json.dumps(_scan('2026-11-02')) + '\n{broken\n')
    with pytest.raises(ValueError):
        L.load(str(path))
    with pytest.raises(ValueError):
        L.append_rows(str(path), [_scan('2026-11-03')])
    assert path.read_text().endswith('{broken\n')


@pytest.mark.parametrize('line', [
    '{"id": "scan|2026-11-02|a", "kind": "scan", "report_date": "2026-11-02", "observed": [["x", "Labor"]]}',
    '{"id": "scan|2026-11-02|a", "kind": "scan", "report_date": "2026-11-02"}',
    '{"id": "A|2026-10-01", "kind": "release", "name": "A", "ref_period": "x", "detected_on": "2026-11-02"}',
    '{"kind": "release"}',
    '[1, 2]',
])
def test_a_well_formed_json_line_with_the_wrong_shape_is_refused(tmp_path, line):
    path = tmp_path / 'releases.jsonl'
    path.write_text(line + '\n')
    with pytest.raises(ValueError):
        L.load(str(path))


@pytest.mark.parametrize('line', [
    '{"id": "scan|2026-11-02|a", "kind": "scan", "report_date": "2026-11-02", "observed": [["x", [], "scored"]]}',
    '{"id": "A|2026-10-01", "kind": "release", "name": "A", "ref_period": "2026-10-01", "detected_on": "2026-11-02", "axis": []}',
])
def test_non_string_axis_or_role_is_refused(tmp_path, line):
    path = tmp_path / 'releases.jsonl'
    path.write_text(line + '\n')
    with pytest.raises(ValueError):
        L.load(str(path))


@pytest.mark.parametrize('extra', ['"official_date": ["bad"]', '"official_date": "x"',
                                   '"since": 5', '"gap": "no"'])
def test_bad_dates_or_gap_on_a_print_row_are_refused(tmp_path, extra):
    path = tmp_path / 'releases.jsonl'
    path.write_text('{"id": "A|2026-10-01", "kind": "release", "name": "A", "ref_period": "2026-10-01", '
                    '"detected_on": "2026-11-02", ' + extra + '}\n')
    with pytest.raises(ValueError):
        L.load(str(path))


def test_a_collection_with_no_indicators_writes_nothing():
    mm, econ, market = inputs('2026-11-03', [])
    new, warnings = L.record([], mm, econ, market, None, 'r')
    assert new == [] and warnings


@pytest.mark.parametrize('extra', ['"official_date": 20261106', '"actual": 1e999'])
def test_integer_dates_are_refused_and_huge_values_do_not_crash(tmp_path, extra):
    path = tmp_path / 'releases.jsonl'
    path.write_text('{"id": "A|2026-10-01", "kind": "release", "name": "A", "ref_period": "2026-10-01", '
                    '"detected_on": "2026-11-02", ' + extra + '}\n')
    if 'official_date' in extra:
        with pytest.raises(ValueError):
            L.load(str(path))
    else:
        rows = L.load(str(path))
        rows[0]['actual'] = 10 ** 400
        mm, econ, market = inputs('2026-11-03', [ind('A', '2026-10-01', 1.0)])
        new, _ = L.record(rows, mm, econ, market, None, 'r')
        assert [r['kind'] for r in new] == ['scan', 'revision']
