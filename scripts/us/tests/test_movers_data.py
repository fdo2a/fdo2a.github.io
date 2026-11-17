"""US 움직인 종목 모집단 — S&P 500 중 달러 거래대금 상위 60 (2026-09-24)."""
from us import movers_data as D

TABLE = '''<table id="constituents"><thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>
<th>GICS Sub-Industry</th></tr></thead><tbody>
<tr><td>MU</td><td>Micron Technology</td><td>Information Technology</td><td>Semiconductors</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector Holdings</td></tr>
</tbody></table>'''


def test_constituents_parse_and_translate_symbols_for_yahoo():
    rows = D.parse_constituents(TABLE)
    assert rows == [
        {"symbol": "MU", "yf": "MU", "name": "Micron Technology", "sub_industry": "Semiconductors"},
        {"symbol": "BRK.B", "yf": "BRK-B", "name": "Berkshire Hathaway",
         "sub_industry": "Multi-Sector Holdings"}]


def test_universe_keeps_top_dollar_volume_on_the_report_date():
    series = {
        "MU": [("2026-09-22", 100.0, 10), ("2026-09-23", 97.78, 50)],
        "NVDA": [("2026-09-22", 200.0, 100), ("2026-09-23", 201.0, 100)],
        "OLD": [("2026-09-21", 10.0, 1), ("2026-09-22", 11.0, 1)],     # 오늘 봉 없음
        "ONE": [("2026-09-23", 5.0, 1)],                                 # 전일 종가 없음
    }
    names = {"MU": "Micron Technology (MU)", "NVDA": "NVIDIA (NVDA)",
             "OLD": "Old (OLD)", "ONE": "One (ONE)"}
    out = D.universe(series, names, "2026-09-23", top_n=1)
    assert out == [{"name": "NVIDIA (NVDA)", "yf": "NVDA", "change_pct": 0.5,
                    "close": 201.0, "value": 20100.0}]
    two = D.universe(series, names, "2026-09-23", top_n=5)
    assert [r["yf"] for r in two] == ["NVDA", "MU"]
    assert two[1]["change_pct"] == -2.22


def test_universe_uses_the_report_date_bar_even_when_a_later_bar_exists():
    """수집이 늦게 돌거나 재실행되면 다음 날 장중 봉이 끝에 붙는다(9/24 실측)."""
    series = {"MU": [("2026-09-22", 100.0, 10), ("2026-09-23", 97.78, 50),
                     ("2026-09-24", 96.0, 5)]}
    out = D.universe(series, {"MU": "Micron Technology (MU)"}, "2026-09-23")
    assert out[0]["change_pct"] == -2.22 and out[0]["close"] == 97.78



# --- collect 칸(2026-11-17): 묶음 0개가 실패인지 「없음 확인」인지 가른다 -------------------

def _cons(n):
    return [{'symbol': f'T{i}', 'yf': f'T{i}', 'name': f'Co{i}', 'sub_industry': f'Ind{i % 3}'}
            for i in range(n)]


def _flat(n, rd='2026-09-23', pct=0.0, skip=()):
    out = {}
    for i in range(n):
        if i in skip:
            continue
        out[f'T{i}'] = [('2026-09-22', 100.0, 1000 + i), (rd, 100.0 * (1 + pct / 100), 1000 + i)]
    return out


def test_assemble_full_coverage_with_movers_is_has_data():
    series = _flat(70)
    series['T3'][1] = ('2026-09-23', 110.0, 5000)            # +10%
    book = D.assemble('2026-09-23', _cons(70), series, lambda t: 1e9)
    c = book['collect']
    assert c['status'] == 'ok' and c['empty'] == 'has_data' and c['checked'] == 70
    assert c['as_of'] == '2026-09-23' and book['groups']


def test_assemble_quiet_day_fully_measured_is_confirmed_none():
    """시총이 없어 기여 후보도 없고 ±5% 도 없는 날 — 다 쟀으므로 「없음 확인」."""
    book = D.assemble('2026-09-23', _cons(70), _flat(70), lambda t: 0)
    assert book['groups'] == []
    assert book['collect']['status'] == 'ok' and book['collect']['empty'] == 'confirmed_none'


def test_assemble_no_bars_for_the_day_is_failed_not_none():
    """그날 봉이 하나도 없으면(늦은 실행·원천 장애) 묶음 0개는 실패다."""
    book = D.assemble('2026-09-23', _cons(70), _flat(70, rd='2026-09-24'), lambda t: 1e9)
    assert book['groups'] == []
    assert book['collect']['status'] == 'failed' and book['collect']['empty'] == 'unknown'


def test_assemble_low_coverage_is_partial_unknown():
    book = D.assemble('2026-09-23', _cons(70), _flat(70, skip=range(20)), lambda t: 0)
    c = book['collect']
    assert c['status'] == 'partial' and c['empty'] == 'unknown' and c['required_ok'] is False
    assert c['missing'] == ['coverage:50/70']


def test_assemble_cap_lookup_failures_are_partial():
    def boom(t):
        raise RuntimeError('rate limited')
    book = D.assemble('2026-09-23', _cons(70), _flat(70), boom)
    assert book['collect']['status'] == 'partial'
    assert book['collect']['missing'] == ['lookup:60/60']


def test_failed_book_keeps_error_and_says_failed():
    book = D.failed('2026-09-23', RuntimeError('wiki 503'))
    assert book['groups'] == [] and book['error'] == 'wiki 503'
    assert book['collect']['status'] == 'failed' and book['collect']['empty'] == 'unknown'


def test_empty_constituents_is_failed():
    book = D.assemble('2026-09-23', [], {}, lambda t: 1e9)
    assert book['collect']['status'] == 'failed'
