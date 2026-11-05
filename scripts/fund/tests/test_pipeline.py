"""Board assembly moved out of collect_market_data.main() — behaviour must not move.

FF3 trial (2026-11): the published board stays byte-identical. Frozen fixtures are the
11/03 and 11/04 committed board JSON with the HTML **HEAD's renderer** produces for them
(ed17327; the committed data/fund_board.html predates two render commits).
"""

import datetime
import json
import os

import pytest

from fund import core, pipeline, publish, render, universe

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')
FROZEN = {'2026-11-03': 'ebcebc2445e6', '2026-11-04': '724ecca745e1'}


@pytest.mark.parametrize('day', sorted(FROZEN))
def test_frozen_board_digest_and_html_bytes(day):
    with open(os.path.join(FIX, f'fund_board_{day}.json'), encoding='utf-8') as fh:
        board = json.load(fh)
    with open(os.path.join(FIX, f'fund_board_{day}.html'), encoding='utf-8') as fh:
        html = fh.read()
    assert core.digest(board) == FROZEN[day]
    assert render.board_html(board) == html


def test_trial_core_versions_are_literal_1_and_2026_10_06():
    # 시운전 동안만 — 병합 커밋(SCHEMA_VERSION 2)에서 지운다.
    assert core.SCHEMA_VERSION == 1
    assert core.CALCULATION_VERSION == '2026-10-06'
    assert core.UNIVERSE_VERSION == '2026-10-06'


# --- synthetic inputs (weekday calendar, holiday file covering it) ---

def weekdays(n, end=datetime.date(2026, 10, 5)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


HOLIDAYS = {'valid_from': '2020-01-01', 'valid_through': '2030-12-31', 'dates': []}
MARKET = {
    'price_context': {'levels': {'VIX': {'value': 16.4, 'percentile': 35.7, 'sessions': 504}}},
    'yield_drivers': {'rows': {'hy_spread': {'level': 3.12, 'date': '2026-09-30', 'chg_5d_bp': 39.0},
                               'real_10y': {'level': 2.93, 'date': '2026-09-30', 'chg_5d_bp': 17.0}}},
}
FRED = {
    'WALCL': [('2026-09-02', 6_770_000), ('2026-09-30', 6_730_000)],
    'WDTGAL': [('2026-09-02', 815_000), ('2026-09-30', 835_000)],
    'RRPONTSYD': [('2026-09-02', 10.0), ('2026-09-30', 1.0)],
    'NFCI': [('2026-08-28', -0.47), ('2026-09-25', -0.43)],
}
BASE = sorted(set(universe.tickers()) | {'^GSPC', 'XLK'})
FACTOR_NEW = ('VTI', 'IWB', 'IWD', 'IWF', 'IWN')


def hist(tickers, n=600):
    dates = weekdays(n)
    closes = {t: [100.0 * (1 + 0.0004 + 0.0001 * (i % 7)) ** k for k in range(n)]
              for i, t in enumerate(tickers)}
    return closes, {t: list(dates) for t in closes}


def run_into(tmp, closes, dates, **kw):
    rd = dates['SPY'][-1]
    return pipeline.run(closes, dates, MARKET, FRED, rd, 't', str(tmp), HOLIDAYS, **kw)


def files(d):
    return {n: (d / n).read_bytes() for n in ('fund_board.json', 'fund_board.html')
            if (d / n).exists()}


def inline_reference(outdir, closes, dates, market, fred, report_date, generated_at, holidays):
    """The pre-extraction block of collect_market_data.main(), verbatim minus FRED I/O."""
    try:
        board = core.build(closes, dates, market, fred, report_date, generated_at,
                           holidays=holidays)
        publish.write(outdir, 'fund_board.json', 'fund_board.html', board,
                      render.board_html(board))
    except Exception as e:
        publish.write(outdir, 'fund_board.json', 'fund_board.html',
                      publish.failed(report_date, generated_at, e, universe=True), None)


@pytest.mark.parametrize('case', ['ok', 'unavailable', 'exception'])
def test_pipeline_run_equals_inline_behaviour(tmp_path, monkeypatch, case):
    closes, dates = hist(BASE)
    if case == 'unavailable':
        closes.pop('SPY')
        dates.pop('SPY')
        rd = dates['QQQ'][-1]
    else:
        rd = dates['SPY'][-1]
    a, b = tmp_path / 'a', tmp_path / 'b'
    for d in (a, b):
        d.mkdir()
        (d / 'fund_board.html').write_text('<div>yesterday</div>')
    if case == 'exception':
        def boom(*a, **k):
            raise RuntimeError('boom')
        monkeypatch.setattr(core, 'build', boom)
    inline_reference(str(a), closes, dates, MARKET, FRED, rd, 't', HOLIDAYS)
    pipeline.run(closes, dates, MARKET, FRED, rd, 't', str(b), HOLIDAYS)
    assert files(a) == files(b)
    if case == 'ok':
        assert 'fund_board.html' in files(b)
    else:
        assert 'fund_board.html' not in files(b)
        assert json.loads(files(b)['fund_board.json'])['status'] == 'unavailable'


def test_factor_only_equals_new_tickers_minus_pre_trial_set():
    import collect_market_data as cmd
    from fund import factors
    pre = cmd.base_history_tickers()
    assert set(factors.FACTOR_ONLY) == set(factors.FACTOR_TICKERS) - pre
    assert set(factors.FACTOR_ONLY) == set(FACTOR_NEW)
    assert cmd.history_tickers() == sorted(pre | set(factors.FACTOR_TICKERS))


def test_board_input_ticker_set_unchanged_by_trial(tmp_path, monkeypatch):
    seen = {}
    real = core.build

    def spy(closes, dates, *a, **k):
        seen['closes'], seen['dates'] = set(closes), set(dates)
        return real(closes, dates, *a, **k)

    monkeypatch.setattr(core, 'build', spy)
    closes, dates = hist(BASE + list(FACTOR_NEW))
    run_into(tmp_path, closes, dates)
    assert seen['closes'] == seen['dates'] == set(BASE)


def test_bad_factor_only_history_keeps_board_bytes(tmp_path):
    """codex 재현: VTI 중복 날짜 → 보드 digest·HTML 이 VTI 없는 실행과 같다."""
    closes, dates = hist(BASE)
    a = tmp_path / 'a'
    run_into(a, closes, dates)
    c2, d2 = hist(BASE + list(FACTOR_NEW))
    d2['VTI'][-2] = d2['VTI'][-3]
    b = tmp_path / 'b'
    run_into(b, c2, d2)
    assert files(a) == files(b)
    board = json.loads(files(b)['fund_board.json'])
    assert not any('VTI' in m for m in board['missing'])
