"""Write the fund JSON (always) and its HTML block (only when renderable).

A failed or unavailable day still writes the JSON, with status 'unavailable', and
removes yesterday's HTML — so nothing downstream can mistake an old block for today's.
"""

import json
import os


def write(outdir, json_name, html_name, data, html):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, json_name), 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, allow_nan=False)
    path = os.path.join(outdir, html_name)
    if html:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(html)
    elif os.path.exists(path):
        os.remove(path)


def failed(report_date, generated_at, reason, universe=False):
    """The JSON a crashed build leaves behind — same common header as a normal one."""
    from fund.core import CALCULATION_VERSION, SCHEMA_VERSION, UNIVERSE_VERSION
    out = {'schema_version': SCHEMA_VERSION, 'calculation_version': CALCULATION_VERSION,
           'report_date': report_date, 'generated_at': generated_at,
           'status': 'unavailable', 'missing': [f'build failed: {reason}'[:300]],
           'source_dates': {}}
    if universe:
        out['universe_version'] = UNIVERSE_VERSION
    return out
