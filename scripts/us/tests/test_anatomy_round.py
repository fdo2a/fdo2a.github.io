"""The collector's half of the anatomy: release dates, introduced rows, FRED's round."""
import collect_market_data as cmd
from us import macro_metrics as mm
from us.tests.test_macro_metrics import dated, ind, jump

D = '2026-10-15'


class Client:
    transport = 'api'

    def __init__(self, days, rows=None, fail=()):
        self.days, self.rows, self.fail, self.calls = days, rows or {}, set(fail), []

    def preflight(self):
        return self.transport

    def series_release(self, sid):
        self.calls.append(('series_release', sid))
        return {'CPIAUCSL': 10, 'HOUST': 27, 'HSN1F': 97}[sid], 'x'

    def last_release_date(self, rid, as_of):
        self.calls.append(('dates', rid, as_of))
        return self.days.get(rid)

    def vintage(self, sid, a, b, as_of):
        self.calls.append(('vintage', sid, a, b, as_of))
        if sid in self.fail:
            raise RuntimeError('boom')
        return self.rows.get(sid, [{'date': b, 'realtime_start': as_of, 'realtime_end': as_of,
                                    'value': 100.5}, {'date': a, 'realtime_start': '2026-09-01',
                                                      'realtime_end': as_of, 'value': 100.0}])


def _run(monkeypatch, client, econ, series, seen, book_date='2026-10-14'):
    monkeypatch.setattr(cmd, 'fred_client', lambda: client)
    out = mm.compute(series, econ, seen, book_state='ok')
    return cmd._anatomy_round(out, econ, series, seen, 'ok', book_date, D, mm.compute)


def _cpi():
    econ = [ind('CPI MoM', 'Inflation', 'CPIAUCSL', actual=0.6, ref='2026-09-01', tf='mom_pct')]
    return econ, {'CPIAUCSL': dated(jump(1))}, {'CPI MoM': ['2026-08-01', 0.4]}


def test_every_promoted_release_gets_its_fred_round(monkeypatch):
    econ, series, seen = _cpi()
    out = _run(monkeypatch, Client({10: D}), econ, series, seen)
    anat = out['headline_releases'][0]['anatomy']
    assert anat['release_date'] == D and anat['round'] == 'ok'
    assert all(c['round_ok'] for c in anat['candidates'])
    assert out['headline_releases'][0]['components'] == []


def test_no_release_date_means_no_candidate(monkeypatch):
    econ, series, seen = _cpi()
    out = _run(monkeypatch, Client({}), econ, series, seen)
    anat = out['headline_releases'][0]['anatomy']
    assert anat['round'] == 'no_release_date'
    assert not any(c['round_ok'] for c in anat['candidates'])


def test_without_the_official_api_nothing_is_fetched(monkeypatch):
    econ, series, seen = _cpi()
    client = Client({10: D})
    client.transport = 'csv'
    out = _run(monkeypatch, client, econ, series, seen)
    assert out['headline_releases'][0]['anatomy']['round'] == 'no_release_date'
    assert not [c for c in client.calls if c[0] == 'vintage']


def test_an_introduced_row_released_after_the_book_is_dissected(monkeypatch):
    econ = [ind('New Home Sales', 'Activity', 'HSN1F', actual=676.0, ref='2026-09-01'),
            ind('Housing Starts', 'Activity', 'HOUST', actual=1221.0, ref='2026-09-01')]
    series = {'HSN1F': dated(jump(1)), 'HOUST': dated(jump(1))}
    seen = {'New Home Sales': ['2026-09-01', 676.0]}
    out = _run(monkeypatch, Client({27: D, 97: '2026-09-25'}), econ, series, seen)
    assert [r['key'] for r in out['headline_releases']] == ['housing-starts']
    assert out['headline_releases'][0]['role'] == 'anatomy'
    assert out['new_releases'] == []


def test_an_introduced_row_released_before_the_book_is_only_seeded(monkeypatch):
    econ = [ind('Housing Starts', 'Activity', 'HOUST', actual=1221.0, ref='2026-09-01')]
    seen = {'New Home Sales': ['2026-09-01', 676.0]}
    out = _run(monkeypatch, Client({27: '2026-10-01'}), econ, {'HOUST': dated(jump(1))}, seen)
    assert out['headline_releases'] == [] and out['introduced'] == ['Housing Starts']


def test_census_four_and_philly_are_on_the_dashboard(monkeypatch):
    rows = {r[1]: r for r in cmd.ECON}
    for name in ('Housing Starts', 'Trade Balance', 'Construction Spending MoM',
                 'Factory Orders MoM', 'Philly Fed Manufacturing'):
        assert name in rows and rows[name][0] == 'Activity'
        assert name in mm.INDICATOR_RELEASE and name in mm.LABELS_KO
    assert rows['Philly Fed Manufacturing'][5] == {'role': 'anatomy'}

    hist = [(f'2026-{m:02d}-01', -100000.0 - m * 1000) for m in range(1, 10)]
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: hist)
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    econ, series = cmd.collect_econ()
    by = {e['name']: e for e in econ}
    tb = by['Trade Balance']
    assert tb['actual'] == -109.0 and tb['previous'] == -108.0 and tb['units'] == '$B'
    assert series['BOPGSTB'][-1] == ('2026-09-01', -109.0)
    assert by['Philly Fed Manufacturing']['role'] == 'anatomy'
    assert 'role' not in by['Housing Starts']


# ------------------------------------------------ codex 구현 검토 1회 #5 (11/08)

HOUST_ROW = [ind('Housing Starts', 'Activity', 'HOUST', actual=1221.0, ref='2026-09-01')]
SEEN = {'New Home Sales': ['2026-09-01', 676.0]}


def test_an_unknown_release_date_keeps_the_row_pending_not_seeded(monkeypatch):
    out = _run(monkeypatch, Client({}), HOUST_ROW, {'HOUST': dated(jump(1))}, SEEN,
               book_date='2026-10-14')
    assert out['headline_releases'] == []
    assert out['last_seen']['Housing Starts'] == ['pending', '2026-10-14']


def test_a_pending_row_is_judged_against_the_date_it_was_first_seen(monkeypatch):
    seen = dict(SEEN, **{'Housing Starts': ['pending', '2026-10-14']})
    # Today's book is from 10-15; the release (10-15) is after the first sighting (10-14).
    out = _run(monkeypatch, Client({27: '2026-10-15'}), HOUST_ROW, {'HOUST': dated(jump(1))},
               seen, book_date='2026-10-15')
    assert [r['key'] for r in out['headline_releases']] == ['housing-starts']
    assert out['last_seen']['Housing Starts'] == ['2026-09-01', 1221.0]


def test_a_pending_row_released_before_it_was_first_seen_is_seeded(monkeypatch):
    seen = dict(SEEN, **{'Housing Starts': ['pending', '2026-10-14']})
    out = _run(monkeypatch, Client({27: '2026-10-01'}), HOUST_ROW, {'HOUST': dated(jump(1))},
               seen, book_date='2026-10-15')
    assert out['headline_releases'] == []
    assert out['last_seen']['Housing Starts'] == ['2026-09-01', 1221.0]


def test_a_pending_entry_is_never_read_as_a_reading():
    out = mm.compute({'HOUST': dated(jump(1))}, HOUST_ROW,
                     last_seen=dict(SEEN, **{'Housing Starts': ['pending', '2026-10-14']}))
    assert out['new_releases'] == [] and out['introduced'] == ['Housing Starts']
