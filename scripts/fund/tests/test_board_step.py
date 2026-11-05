"""The board block of collect_market_data.main() — failure paths must match ed17327's inline block.

codex impl review 1 (#1 P1, #2 P2): an ImportError in a factor module escaped the board's
try and stopped the collector; a `fund.liquidity` import failure built a board from empty
FRED input instead of writing `publish.failed`; a failure in the second holiday load ran
outside the protection. `original_block` below is the ed17327 block verbatim (only
`args.outdir` → `outdir`), so each injection is compared file-for-file to what the
pre-trial collector would have left behind.
"""

import json
import sys
import time

import pytest

import collect_market_data as cmd
import fund
from fund import calendar as fund_calendar, core
from fund.tests.test_pipeline import BASE, FACTOR_NEW, FRED, HOLIDAYS, MARKET, files, hist


def original_block(closes, hist_dates, data, report_date, outdir):
    """`git show ed17327:scripts/collect_market_data.py` lines 1148-1175, verbatim."""
    import os
    from collect_market_data import fred_series, retry
    print('building fund board...')
    from fund import publish as fund_publish
    try:
        from fund import core as fund_core, render as fund_render
        from fund.liquidity import SERIES as LIQ_SERIES
        liq_series = {}
        for sid in LIQ_SERIES:
            try:
                got = retry(lambda sid=sid: fred_series(sid), attempts=2)
                if got:
                    liq_series[sid] = got
            except Exception as e:
                print(f'  liquidity {sid} failed: {e}', file=sys.stderr)
            time.sleep(0.3)
        from fund.calendar import load as load_holidays
        board = fund_core.build(closes, hist_dates, data, liq_series, report_date,
                                data['generated'],
                                holidays=load_holidays(os.path.join(outdir, 'market_holidays.json')))
        fund_publish.write(outdir, 'fund_board.json', 'fund_board.html', board,
                           fund_render.board_html(board))
        mr = board.get('market_regime') or {}
        print(f"  status {board['status']} · 국면 {mr.get('name')} · "
              f"순위 {(board.get('rank_basis') or {}).get('n')}종"
              + (f" · missing {board['missing']}" if board['missing'] else ''))
    except Exception as e:
        print(f'fund board failed: {e}', file=sys.stderr)
        fund_publish.write(outdir, 'fund_board.json', 'fund_board.html',
                           fund_publish.failed(report_date, data['generated'], e, universe=True), None)


DATA = {**MARKET, 'generated': 't'}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: FRED.get(sid) or [])
    dirs = []
    for name in ('ref', 'new'):
        d = tmp_path / name
        d.mkdir()
        (d / 'market_holidays.json').write_text(json.dumps({'us': HOLIDAYS}), encoding='utf-8')
        (d / 'fund_board.html').write_text('<div>yesterday</div>', encoding='utf-8')
        dirs.append(d)
    return dirs


def both(env, closes, dates, desk=False):
    ref, new = env
    rd = dates['QQQ'][-1]
    original_block(closes, dates, DATA, rd, str(ref))
    (cmd.fund_desk if desk else cmd.fund_board_step)(closes, dates, DATA, rd, str(new))
    return files(ref), files(new)


def test_normal_run_matches_original_block(env):
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates)
    assert a == b and 'fund_board.html' in b


def test_build_exception_matches_original_block(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('boom')
    monkeypatch.setattr(core, 'build', boom)
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates)
    assert a == b and 'fund_board.html' not in b


def test_liquidity_import_error_writes_failed_like_original(env, monkeypatch):
    """codex #2: `fund.liquidity` import failure → `publish.failed`, not a board on empty FRED."""
    monkeypatch.setitem(sys.modules, 'fund.liquidity', None)
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates)
    assert a == b
    assert 'fund_board.html' not in b
    assert json.loads(b['fund_board.json'])['status'] == 'unavailable'


def test_holiday_load_failure_writes_failed_like_original(env, monkeypatch):
    """codex #2: the board's holiday load raising → inside the protection → `publish.failed`."""
    def bad(path):
        raise RuntimeError('holiday file exploded')
    monkeypatch.setattr(fund_calendar, 'load', bad)
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates)
    assert a == b
    assert 'fund_board.html' not in b
    assert 'holiday file exploded' in json.dumps(json.loads(b['fund_board.json']), ensure_ascii=False)


def _break_factor_modules(monkeypatch):
    for mod in ('fund.factors', 'fund.factors_check', 'fund.factors_pipeline', 'fund.pipeline'):
        monkeypatch.delitem(sys.modules, mod, raising=False)
        monkeypatch.delattr(fund, mod.split('.')[1], raising=False)
    monkeypatch.setitem(sys.modules, 'fund.factors', None)     # import → ImportError


def test_factor_import_error_board_identical_and_collect_continues(env, monkeypatch, capsys):
    """codex #1 P1: ImportError in fund.factors must not escape. The download set falls back
    to the pre-trial set, the board files equal a run without factor modules, and the desk
    step returns so the rest of main() runs."""
    _break_factor_modules(monkeypatch)
    with pytest.raises(ImportError):
        import fund.factors  # noqa: F401
    # the leg list does not live behind fund.factors, so the download set is unchanged
    assert cmd.history_tickers() == sorted(cmd.base_history_tickers() | set(FACTOR_NEW)
                                           | {'IWM', 'IWO'})
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates, desk=True)            # must not raise
    assert a == b and 'fund_board.html' in b
    assert not (env[1] / 'fund_factors.json').exists()
    assert 'fund factors trial failed' in capsys.readouterr().err


def test_factor_import_error_with_factor_legs_present_keeps_board(env, monkeypatch):
    """Even if factor-only histories reached the board while fund.factors is broken, the
    board still drops them (the leg list does not live behind the factor model's import)."""
    _break_factor_modules(monkeypatch)
    closes, dates = hist(BASE)
    ref, new = env
    rd = dates['QQQ'][-1]
    original_block(closes, dates, DATA, rd, str(ref))
    c2, d2 = hist(BASE + list(FACTOR_NEW))
    cmd.fund_desk(c2, d2, DATA, rd, str(new))
    assert files(ref) == files(new)


def test_desk_survives_trial_exception(env, monkeypatch):
    from fund import factors_pipeline

    def boom(*a, **k):
        raise RuntimeError('trial boom')
    monkeypatch.setattr(factors_pipeline, 'run_trial', boom)
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates, desk=True)
    assert a == b


def test_leg_list_import_error_falls_back_to_pre_trial_set(env, monkeypatch, capsys):
    """Breaking the leg list itself (the last factor module the board path touches): the
    download set is the pre-trial one, the board filters nothing, files equal the original."""
    _break_factor_modules(monkeypatch)
    monkeypatch.delitem(sys.modules, 'fund.factor_legs', raising=False)
    monkeypatch.delattr(fund, 'factor_legs', raising=False)
    monkeypatch.setitem(sys.modules, 'fund.factor_legs', None)
    assert cmd.history_tickers() == sorted(cmd.base_history_tickers())
    closes, dates = hist(BASE)
    a, b = both(env, closes, dates, desk=True)
    assert a == b and 'fund_board.html' in b
    assert 'fund factors trial failed' in capsys.readouterr().err
