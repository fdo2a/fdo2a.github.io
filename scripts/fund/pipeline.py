"""Board assembly as one callable: build -> render -> publish, failure -> `publish.failed`.

Moved out of `collect_market_data.main()` unchanged so it can be tested end to end.
JSON is always written; HTML only when renderable; a crash leaves the unavailable JSON
and removes yesterday's HTML.

The board sees exactly the tickers it saw before the factor trial: histories that were
downloaded **only** for the factor model (`factors.FACTOR_ONLY`) are dropped here, so a
bad factor leg can never change the board's `missing`, status or digest. This file must
not import numpy — the board cannot depend on the factor model's toolchain.
"""

import sys

from fund import publish
from fund.factors import FACTOR_ONLY


def board_inputs(closes, dates):
    """The board's view of the histories: everything except the factor-only legs."""
    return ({t: c for t, c in (closes or {}).items() if t not in FACTOR_ONLY},
            {t: d for t, d in (dates or {}).items() if t not in FACTOR_ONLY})


def run(closes, hist_dates, data, liq_series, report_date, generated_at, outdir, holidays):
    try:
        from fund import core, render
        b_closes, b_dates = board_inputs(closes, hist_dates)
        board = core.build(b_closes, b_dates, data, liq_series, report_date, generated_at,
                           holidays=holidays)
        publish.write(outdir, 'fund_board.json', 'fund_board.html', board,
                      render.board_html(board))
        mr = board.get('market_regime') or {}
        print(f"  status {board['status']} · 국면 {mr.get('name')} · "
              f"순위 {(board.get('rank_basis') or {}).get('n')}종"
              + (f" · missing {board['missing']}" if board['missing'] else ''))
        return board
    except Exception as e:
        print(f'fund board failed: {e}', file=sys.stderr)
        failed = publish.failed(report_date, generated_at, e, universe=True)
        publish.write(outdir, 'fund_board.json', 'fund_board.html', failed, None)
        return failed
