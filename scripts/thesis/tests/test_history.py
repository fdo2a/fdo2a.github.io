import json

from thesis import history as H


ROWS = [
    {'date': '2026-07-20', 'tickers': {'MU': {'eps_fy1': 120.0, 'price': 700.0}}},
    {'date': '2026-07-27', 'tickers': {'MU': {'eps_fy1': 130.0, 'price': 800.0}}},
    {'date': '2026-08-21', 'tickers': {'MU': {'eps_fy1': 155.0, 'price': 966.78}}},
]


def write(tmp_path, rows=ROWS):
    p = tmp_path / 'history.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    return p


def test_append_adds_one_line(tmp_path):
    p = write(tmp_path)
    H.append(p, {'date': '2026-08-24', 'tickers': {'MU': {'eps_fy1': 156.0}}})
    assert len(p.read_text(encoding='utf-8').strip().splitlines()) == 4


def test_append_replaces_same_date_never_duplicates(tmp_path):
    p = write(tmp_path)
    H.append(p, {'date': '2026-08-21', 'tickers': {'MU': {'eps_fy1': 999.0}}})
    rows = H.load(p)
    dates = [r['date'] for r in rows]
    assert dates.count('2026-08-21') == 1
    assert rows[-1]['tickers']['MU']['eps_fy1'] == 999.0


def test_append_keeps_rows_sorted_by_date(tmp_path):
    p = write(tmp_path)
    H.append(p, {'date': '2026-07-01', 'tickers': {'MU': {'eps_fy1': 100.0}}})
    dates = [r['date'] for r in H.load(p)]
    assert dates == sorted(dates)


def test_lookup_finds_exact_date(tmp_path):
    p = write(tmp_path)
    assert H.value_on(H.load(p), '2026-07-27', 'MU', 'eps_fy1') == 130.0


def test_lookup_falls_back_to_nearest_earlier_date(tmp_path):
    """영업일·휴장 때문에 정확히 30일 전 행이 없는 게 정상이다."""
    rows = H.load(write(tmp_path))
    assert H.value_on(rows, '2026-07-30', 'MU', 'eps_fy1') == 130.0


def test_lookup_returns_none_before_history_starts(tmp_path):
    rows = H.load(write(tmp_path))
    assert H.value_on(rows, '2026-01-01', 'MU', 'eps_fy1') is None


def test_lookup_returns_none_for_unknown_ticker(tmp_path):
    rows = H.load(write(tmp_path))
    assert H.value_on(rows, '2026-08-21', 'NVDA', 'eps_fy1') is None


def test_load_missing_file_is_empty(tmp_path):
    assert H.load(tmp_path / 'nope.jsonl') == []


def test_load_skips_corrupt_lines(tmp_path):
    p = tmp_path / 'history.jsonl'
    p.write_text('{"date": "2026-08-01", "tickers": {}}\nnot json\n', encoding='utf-8')
    assert len(H.load(p)) == 1


def test_has_depth_reports_whether_lookback_is_usable(tmp_path):
    rows = H.load(write(tmp_path))
    assert not H.has_depth(rows, minimum=20)
    assert H.has_depth(rows, minimum=3)
