"""Ticker lists of the FF3 trial's factor legs — constants only, no imports.

Kept apart from `factors.py` so the board's ticker filter (`pipeline.board_inputs`) and
the collector's download set never depend on the factor model importing cleanly
(codex impl review 1 #1: an ImportError in `fund.factors` escaped the board's try).
`factors.py` re-exports these names.
"""

RF_SERIES = 'DGS1MO'

FACTOR_TICKERS = ('VTI', 'IWB', 'IWM', 'IWD', 'IWF', 'IWN', 'IWO')
# Factor legs the collector did not download before the trial. Fixed as a list, not
# computed at import: a test checks it against the pre-trial download set, so a ticker
# moving into the board's own inputs shows up as a failing test, not a silent change.
FACTOR_ONLY = ('IWB', 'IWD', 'IWF', 'IWN', 'VTI')
