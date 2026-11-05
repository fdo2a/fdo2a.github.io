"""Three-factor exposure of the reference ETFs on ETF proxy factors (FF3 trial).

    R_ETF,d − RF_d = α + β_m (R_VTI,d − RF_d) + β_s SMB_d + β_h HML_d + ε_d

    SMB = IWM − IWB,  HML = ½[(IWD − IWF) + (IWN − IWO)]   (no fallback leg)
    RF  = DGS1MO, (1 + y/100/12)^(1/N) − 1, N = sessions in that calendar month

These are **not** Fama-French factors — an ETF exposure model whose proxies are
compared monthly with the official French file (`factors_check.py`). Internal units are
decimal daily returns; ×100 is display only. Returns are computed per series on the
session calendar first (a gap is None, never a two-day move read as one) and joined by
date; any None in the 252-return window blanks the row. Any RF gap blanks every row —
a varying RF moves both sides of the regression, so there is no "loadings only" mode.

numpy is imported inside the functions: `pipeline.py` imports FACTOR_ONLY from here and
the board must not depend on numpy.
"""

import datetime
import hashlib
import json
import math

MODEL = 'ff3_proxy_v1'
FACTORS_SCHEMA_VERSION = 1
FACTORS_CALCULATION_VERSION = '2026-11-05'
WINDOW = 252
RF_SERIES = 'DGS1MO'
RF_MAX_AGE_DAYS = 7
KAPPA_MAX = 1e6

FACTOR_TICKERS = ('VTI', 'IWB', 'IWM', 'IWD', 'IWF', 'IWN', 'IWO')
# Factor legs the collector did not download before the trial. Fixed as a list, not
# computed at import: a test checks it against the pre-trial download set, so a ticker
# moving into the board's own inputs shows up as a failing test, not a silent change.
FACTOR_ONLY = ('IWB', 'IWD', 'IWF', 'IWN', 'VTI')

PROXIES = {'mkt': 'VTI−RF', 'smb': 'IWM−IWB', 'hml': '½[(IWD−IWF)+(IWN−IWO)]'}
RF_CONVENTION = '(1+y/100/12)^(1/N)−1'
# Russell US index reconstitution, effective after the close of these dates (spec v2 §2-3:
# 2026-06-26, and the first semi-annual one 2026-12-11).
RECONSTITUTIONS = ('2026-06-26', '2026-12-11')
