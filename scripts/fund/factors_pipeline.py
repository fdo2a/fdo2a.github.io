"""FF3 trial: write data/fund_factors.json beside the board — never into it.

Called by collect_market_data.main() **after** fund.pipeline.run, in its own try, so
nothing here can change fund_board.json / fund_board.html. The file is always written
(status unavailable + `missing` on a failure) so yesterday's file never stands in for
today. `official` comes from the committed monthly check through
`factors_check.validate`; `official_meta` is always present, even when the daily
regression or the monthly validation raises.

Until the merge step this file has its own header (`factors_schema_version`) and leaves
core.SCHEMA_VERSION / CALCULATION_VERSION alone.
"""

import json
import math
import os
import sys

from fund import factors

OUT = 'fund_factors.json'


def _finite(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def _official(outdir, report_date, holidays):
    """(official, official_meta, missing). Never raises: a validator crash is reported as
    `invalid_types` with the always-present meta shape (codex impl review 1 #4)."""
    from fund import factors_check
    try:
        official, meta = factors_check.validate_file(outdir, report_date, holidays)
        return official, meta, []
    except Exception as e:
        _, meta = factors_check.validate(None, report_date, holidays)
        meta['reason'] = 'invalid_types'
        return None, meta, [f'factors: official check failed: {e}'[:300]]


def build(closes, hist_dates, rf_obs, report_date, generated_at, outdir, holidays):
    head = {'factors_schema_version': factors.FACTORS_SCHEMA_VERSION,
            'factors_calculation_version': factors.FACTORS_CALCULATION_VERSION,
            'model': factors.MODEL, 'report_date': report_date, 'generated_at': generated_at}
    # The monthly check and the daily regression fail independently: `official_meta` is
    # present whichever of them raises.
    official, meta, check_missing = _official(outdir, report_date, holidays)
    try:
        body = factors.compute_daily(closes, hist_dates, rf_obs, report_date, holidays)
        body = {**body, 'missing': list(body.get('missing') or []) + check_missing}
        return _finite({**head, **body, 'official': official, 'official_meta': meta})
    except Exception as e:
        return _finite({**head, 'status': 'unavailable',
                        'missing': [f'factors: build failed: {e}'[:300]] + check_missing,
                        'rows': [], 'official': official, 'official_meta': meta})


def run_trial(closes, hist_dates, rf_obs, report_date, generated_at, outdir, holidays):
    out = build(closes, hist_dates, rf_obs, report_date, generated_at, outdir, holidays)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, OUT), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, allow_nan=False)
    ok = sum(r.get('status') == 'ok' for r in out.get('rows') or [])
    print(f"  factors trial: status {out['status']} · rows ok {ok}/{len(out.get('rows') or [])}"
          f" · official {((out.get('official_meta') or {}).get('reason'))}"
          + (f" · missing {out['missing'][:3]}" if out['missing'] else ''),
          file=sys.stdout)
    return out
