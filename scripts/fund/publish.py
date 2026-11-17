"""Write the fund JSON (always) and its HTML block (only when renderable).

A failed or unavailable day still writes the JSON, with status 'unavailable', and
removes yesterday's HTML — so nothing downstream can mistake an old block for today's.
"""

import json
import os


SOURCES = {'fund_board.json': 'yfinance + FRED (fund board)',
           'kr_fund_view.json': 'KR collector in-memory (fund view)'}
_STATUS = {'ok': 'ok', 'partial': 'partial'}


def collect_of(data, source):
    """collect 칸(2026-11-17, 공통 계약 A): ok/partial/unavailable → ok/partial/failed. 블록에 그리지 않고
    digest 에서도 빠진다(`core.digest`)."""
    from common import collect_status as C
    st = _STATUS.get(data.get('status'), 'failed')
    missing = [str(m) for m in data.get('missing') or []]
    if st == 'failed':
        return C.failed(data.get('report_date'), source,
                        '; '.join(missing) or f"status {data.get('status')}", missing=missing)
    return C.build(st, data.get('report_date'), source, missing=missing, empty='has_data')


def write(outdir, json_name, html_name, data, html):
    os.makedirs(outdir, exist_ok=True)
    if isinstance(data, dict) and 'collect' not in data:
        data = dict(data, collect=collect_of(data, SOURCES.get(json_name, json_name)))
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
