"""Synthetic world for the FF3 monthly check tests. **No real French rows** — every
number is drawn from a seeded RNG; the French-format text uses invented header lines.

Official factors are drawn in % with two decimals (the French file's format). The proxy
legs are built so that, with `scale=2`, proxy = 2 × official exactly per day: VTI = 2·Mkt,
IWM − IWB = 2·SMB, ½[(IWD − IWF) + (IWN − IWO)] = 2·HML.
"""

import datetime
import os

import numpy as np

from fund import calendar, universe

HERE = os.path.dirname(__file__)
HOLIDAYS = calendar.load(os.path.join(HERE, '..', '..', '..', 'data', 'market_holidays.json'))
ETFS = [t for _, _, t, _ in universe.UNITS]


def sessions(start, end):
    return calendar.us_sessions(start, end, HOLIDAYS)


def make(end='2026-09-30', n=320, seed=11, scale=2.0, rf_pct=0.0, dgs1mo=0.0,
         etf_override=None):
    days = sessions('2024-11-01', end)[-n:]
    rng = np.random.default_rng(seed)
    o_mkt, o_smb, o_hml = (np.round(rng.normal(0, 1, n), 2) for _ in range(3))
    o_rf = np.full(n, rf_pct)
    m, s, h = o_mkt / 100, o_smb / 100, o_hml / 100
    n1, n2, n3 = rng.normal(0, .006, (3, n))
    r = {'VTI': scale * m, 'IWB': n1, 'IWM': n1 + scale * s,
         'IWF': n2, 'IWD': n2 + scale * h, 'IWO': n3, 'IWN': n3 + scale * h}
    for t in ETFS:
        if t in r:
            continue
        b = rng.uniform(.3, 1.5, 3)
        r[t] = b[0] * m + (b[1] - .8) * s + (b[2] - .9) * h + rng.normal(0, .003, n)
    for t, fn in (etf_override or {}).items():
        r[t] = fn(m, s, h)
    # the first day's return is never read (it is before the first anchor)
    closes = {t: [float(x) for x in 100 * np.cumprod(1 + v)] for t, v in r.items()}
    dates = {t: list(days) for t in closes}
    rf_obs = [(d, dgs1mo) for d in days]
    french = [(d, float(a), float(b), float(c), float(e))
              for d, a, b, c, e in zip(days, o_mkt, o_smb, o_hml, o_rf)]
    return {'days': days, 'closes': closes, 'dates': dates, 'rf_obs': rf_obs,
            'french': french}


def french_text(rows, copyright_line='Copyright 2026 Synthetic Fixture (not French data)'):
    """French daily-factor layout: 3 header lines, blank, column header, rows, blank,
    copyright line."""
    out = ['Synthetic file in the layout of the daily three-factor CSV.',
           'All values are random draws for tests.',
           'Columns are percent per day.', '', ',Mkt-RF,SMB,HML,RF']
    for d, a, b, c, e in rows:
        out.append(f"{d.replace('-', '')},{a:8.2f},{b:8.2f},{c:8.2f},{e:8.2f}")
    out += ['', copyright_line, '']
    return '\r\n'.join(out)


def zip_bytes(text, name='F-F_Research_Data_Factors_daily.CSV'):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, text)
    return buf.getvalue()


def today():
    return datetime.date(2026, 11, 8)
