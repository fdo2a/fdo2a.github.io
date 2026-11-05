"""Monthly check of the proxy factors against the official French daily factors (FF3 trial).

Source: Kenneth R. French Data Library, F-F_Research_Data_Factors_daily_CSV.zip.
Attribution is carried in every committed file; the library's terms page was not found
(copyright line only on the listing page and in the file), so only the slice the check
uses (~2 years) is committed, never the whole file, plus the zip's sha256.

One run (scripts/collect_fund_factors.py, workflow check-fund-factors.yml):

  download zip → parse (reject reversed / duplicate dates, skip and list non-numeric rows)
  → slice → slice_sha256 → **no-op** if the previous result is status ok with the same
  slice hash, calculation version and model, and all three committed files exist and
  hash to what check.json says → otherwise fetch ETF histories + DGS1MO, build the
  inputs (factors.prepare) on the 252-return window ending at the French file's last
  session, compute, self-check the structure (check_structure), write
  fund_factors_french.csv, fund_factors_inputs.json, fund_factors_check.json (last).

`compute(inputs, slice_rows)` is pure: the committed inputs + slice reproduce check.json
exactly. Staleness is never stored — `validate()` judges it on every read.
Comparisons pair the official loadings only with the proxy loadings of the **same**
window (`b_*_proxy_m`), never with the daily rows.
"""

import datetime
import hashlib
import io
import json
import math
import os
import re
import zipfile

from fund import factors
from fund.universe import UNITS

FRENCH_URL = ('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/'
              'F-F_Research_Data_Factors_daily_CSV.zip')
ATTRIBUTION = ('Kenneth R. French Data Library · '
               'Copyright Eugene F. Fama and Kenneth R. French')
TERMS_NOTE = 'terms of use not found (listing page and file carry a copyright line only)'

CHECK = 'fund_factors_check.json'
SLICE = 'fund_factors_french.csv'
INPUTS = 'fund_factors_inputs.json'
SLICE_ROWS = 504
STALE_MONTHS = 3
K_MIN, K_MAX = 0.2, 5.0
MAX_CSV_BYTES = 50 * 1024 * 1024
FACTORS = ('mkt', 'smb', 'hml')

ROW_FLOATS = tuple(f'{p}_{f}_{w}' for w in ('official', 'proxy_m')
                   for f in FACTORS for p in ('b', 'se')) + (
    'alpha_d_official', 'r2_official', 'alpha_d_proxy_m', 'r2_proxy_m', 'fit_rmse')
ROW_OPTIONAL = tuple(f'scale_{f}' for f in FACTORS) + tuple(f'scale_gap_{f}' for f in FACTORS)

REASONS = ('none', 'missing_file', 'invalid_json', 'status_not_ok', 'model_mismatch',
           'version_mismatch', 'future_date', 'incomplete_month', 'short_window', 'stale',
           'invalid_types', 'window_mismatch', 'duplicate_row', 'missing_row',
           'status_mismatch')


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


# --- French file -----------------------------------------------------------------------

_HEADER = re.compile(r'^\s*,\s*Mkt-RF\s*,\s*SMB\s*,\s*HML\s*,\s*RF\s*$')
_NUM = re.compile(r'^-?\d+(\.\d+)?$')


def extract_csv(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        members = [m for m in z.infolist() if m.filename.lower().endswith('.csv')]
        if len(members) != 1:
            raise ValueError(f'zip holds {len(members)} csv members, expected 1')
        if members[0].file_size > MAX_CSV_BYTES:
            raise ValueError('csv member too large')
        raw = z.read(members[0])
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')


def parse_french(text):
    """(rows, missing, copyright_line). rows = [(iso, mkt, smb, hml, rf)] with the
    numbers kept as the file's own strings (percent). Reads the layout as structure:
    header lines, the `,Mkt-RF,SMB,HML,RF` line, data rows up to the first blank line,
    then the copyright line. Reversed or duplicate dates reject the whole file."""
    lines = text.splitlines()
    try:
        h = next(i for i, ln in enumerate(lines) if _HEADER.match(ln))
    except StopIteration:
        raise ValueError('French file: no ",Mkt-RF,SMB,HML,RF" header line')
    rows, missing = [], []
    i = h + 1
    while i < len(lines) and lines[i].strip():
        parts = [p.strip() for p in lines[i].split(',')]
        ok = (len(parts) == 5 and re.fullmatch(r'\d{8}', parts[0])
              and all(_NUM.match(p) for p in parts[1:]))
        if ok:
            d = parts[0]
            try:
                iso = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])).isoformat()
            except ValueError:
                ok = False
        if not ok:
            missing.append(f'french: non-numeric row skipped: {lines[i].strip()[:60]}')
        else:
            rows.append((iso,) + tuple(parts[1:]))
        i += 1
    if not rows:
        raise ValueError('French file: no data rows')
    for a, b in zip(rows, rows[1:]):
        if not a[0] < b[0]:
            raise ValueError(f'French file: dates not strictly increasing at {a[0]} → {b[0]}')
    tail = [ln.strip() for ln in lines[i:] if ln.strip()]
    copyright_line = next((ln for ln in tail if 'copyright' in ln.lower()), None)
    return rows, missing, copyright_line


def slice_csv(rows, copyright_line):
    """The committed slice: ISO dates and the file's own percent strings."""
    out = [f'# Source: {ATTRIBUTION} — {FRENCH_URL}',
           f'# {copyright_line or "copyright line not found in the file"}',
           f'# Daily factors in percent; only rows {rows[0][0]}..{rows[-1][0]} '
           f'(the window this check used plus margin), not the whole file.',
           'date,mkt_rf,smb,hml,rf']
    out += [','.join(r) for r in rows]
    return '\n'.join(out) + '\n'


def read_slice(text):
    """[(iso, mkt, smb, hml, rf)] as floats in percent."""
    rows = []
    for ln in text.splitlines():
        if not ln.strip() or ln.startswith('#') or ln.startswith('date,'):
            continue
        d, a, b, c, e = ln.split(',')
        rows.append((d, float(a), float(b), float(c), float(e)))
    for x, y in zip(rows, rows[1:]):
        if not x[0] < y[0]:
            raise ValueError('slice: dates not strictly increasing')
    return rows


# --- computation ----------------------------------------------------------------------------

def scale_k(official, proxy):
    """k = slope of official on proxy (with intercept) and whether proxy/k may be shown."""
    import numpy as np
    o, p = np.asarray(official, float), np.asarray(proxy, float)
    if not p.max() > p.min():
        return None, 'proxy_constant'
    dp = p - p.mean()
    k = float((dp * (o - o.mean())).sum() / (dp * dp).sum())
    if not math.isfinite(k):
        return None, 'proxy_constant'
    if abs(k) <= 1e-12:
        return k, 'k_zero'
    if k < 0:
        return k, 'k_negative'
    if k < K_MIN:
        return k, 'k_small'
    if k > K_MAX:
        return k, 'k_large'
    return k, 'none'


def _f(x):
    return float(x) if x is not None and math.isfinite(float(x)) else None


def _french_on(slice_rows, ret_dates):
    fmap = {r[0]: r for r in slice_rows}
    missing = []
    cal = set(ret_dates)
    lo, hi = ret_dates[0], ret_dates[-1]
    for d in sorted(fmap):
        if lo <= d <= hi and d not in cal:
            missing.append(f'french: {d} not a session on the calendar — ignored')
    mkt, smb, hml, rf = [], [], [], []
    for d in ret_dates:
        r = fmap.get(d)
        if r is None:
            missing.append(f'french: French file lacks session {d}')
        for out, j in ((mkt, 1), (smb, 2), (hml, 3), (rf, 4)):
            out.append(r[j] / 100 if r is not None else None)
    return mkt, smb, hml, rf, missing


def _empty_row(uid, reason):
    row = {'id': uid, 'status': 'unavailable', 'reason': reason, 'n': None,
           'sign_mismatch': []}
    row.update({k: None for k in ROW_FLOATS + ROW_OPTIONAL})
    return row


def compute(inputs, slice_rows):
    """Pure: official and same-window proxy loadings per ETF, fit gap, sign mismatches,
    factor-level agreement and the scale rule."""
    import numpy as np
    ret_dates, rets, p_mkt, p_smb, p_hml, p_rf, missing = factors.proxy_factors(inputs)
    o_mkt, o_smb, o_hml, o_rf, more = _french_on(slice_rows, ret_dates)
    missing = list(missing) + more
    n = len(ret_dates)
    proxy_gap = any(x is None for x in p_mkt + p_smb + p_hml + p_rf)
    official_gap = any(x is None for x in o_mkt + o_smb + o_hml + o_rf)

    factor_level = None
    scale = {f: (None, 'factor_missing') for f in FACTORS}
    if not (proxy_gap or official_gap):
        P = {'mkt': np.array(p_mkt) - np.array(p_rf), 'smb': np.array(p_smb),
             'hml': np.array(p_hml)}
        O = {'mkt': np.array(o_mkt), 'smb': np.array(o_smb), 'hml': np.array(o_hml)}
        factor_level = {}
        for f in FACTORS:
            k, reason = scale_k(O[f], P[f])
            scale[f] = (k, reason)
            with np.errstate(all='ignore'):
                corr = np.corrcoef(O[f], P[f])[0, 1]
            factor_level[f] = {'corr': _f(corr),
                               'tracking_error': _f(np.std(O[f] - P[f], ddof=1) * 100),
                               'k': _f(k) if k is not None else None,
                               'scale_reason': reason}

    rows = []
    for uid, _, t, _ in UNITS:
        if proxy_gap:
            reason = 'rf_missing' if any(x is None for x in p_rf) else 'factor_missing'
            rows.append(_empty_row(uid, reason))
            continue
        if official_gap:
            rows.append(_empty_row(uid, 'official_missing'))
            continue
        r = rets.get(t)
        if r is None or None in r:
            rows.append(_empty_row(uid, 'price_gap'))
            missing.append(f'factors: {t} price gap')
            continue
        r = np.array(r)
        Xo = np.column_stack([np.ones(n), o_mkt, o_smb, o_hml])
        ro = factors.ols(Xo, r - np.array(o_rf))
        rp = factors.fit(r, p_mkt, p_smb, p_hml, p_rf)
        if ro['status'] != 'ok' or rp['status'] != 'ok':
            bad = ro if ro['status'] != 'ok' else rp
            rows.append(_empty_row(uid, bad['reason']))
            missing.append(f'factors: {t} {bad["reason"]}')
            continue
        Xp = np.column_stack([np.ones(n), np.array(p_mkt) - np.array(p_rf), p_smb, p_hml])
        fo = np.array(o_rf) + Xo @ np.array(ro['beta'])
        fp = np.array(p_rf) + Xp @ np.array(rp['beta'])
        row = {'id': uid, 'status': 'ok', 'reason': None, 'n': n,
               'fit_rmse': float(np.sqrt(np.mean((fo - fp) ** 2)) * 100),
               'alpha_d_official': ro['beta'][0], 'r2_official': ro['r2'],
               'alpha_d_proxy_m': rp['beta'][0], 'r2_proxy_m': rp['r2']}
        mismatch = []
        for j, f in enumerate(FACTORS, start=1):
            bo, bp = ro['beta'][j], rp['beta'][j]
            row[f'b_{f}_official'], row[f'se_{f}_official'] = bo, ro['se'][j]
            row[f'b_{f}_proxy_m'], row[f'se_{f}_proxy_m'] = bp, rp['se'][j]
            if bo * bp < 0:
                mismatch.append(f)
            k, reason = scale[f]
            row[f'scale_{f}'] = bp / k if reason == 'none' else None
            row[f'scale_gap_{f}'] = (bp / k - bo) if reason == 'none' else None
        row['sign_mismatch'] = mismatch
        rows.append(row)
    return {'status': factors.status_of(rows), 'rows': rows, 'factor_level': factor_level,
            'missing': missing, 'window': factors.window_of(inputs)}


# --- structure (producer and consumer) -------------------------------------------------------

def _is_float(x):
    return isinstance(x, float) and math.isfinite(x)


def check_structure(obj, holidays):
    """(ok, reason). Structure only — a partial result is structurally fine. The producer
    runs this on its own output and writes nothing when it fails."""
    from fund.calendar import us_sessions
    if not isinstance(obj, dict):
        return False, 'invalid_types'
    for k in ('status', 'model', 'factors_calculation_version', 'french_through'):
        if not isinstance(obj.get(k), str):
            return False, 'invalid_types'
    if obj['status'] not in ('ok', 'partial', 'unavailable'):
        return False, 'invalid_types'
    w = obj.get('window')
    if not (isinstance(w, dict) and isinstance(w.get('start'), str)
            and isinstance(w.get('end'), str) and isinstance(w.get('n'), int)):
        return False, 'invalid_types'
    try:
        s = us_sessions(w['start'], w['end'], holidays)
    except ValueError:
        return False, 'window_mismatch'
    if (w['n'] != factors.WINDOW or not s or len(s) != factors.WINDOW
            or s[0] != w['start'] or s[-1] != w['end'] or w['end'] != obj['french_through']):
        return False, 'window_mismatch'
    rows = obj.get('rows')
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get('id'), str)
                                             for r in rows):
        return False, 'invalid_types'
    ids = [r['id'] for r in rows]
    if len(set(ids)) != len(ids):
        return False, 'duplicate_row'
    if set(ids) != {u for u, _, _, _ in UNITS}:
        return False, 'missing_row'
    for r in rows:
        if r.get('status') not in ('ok', 'unavailable'):
            return False, 'invalid_types'
        sm = r.get('sign_mismatch')
        if not isinstance(sm, list) or not set(sm) <= set(FACTORS):
            return False, 'invalid_types'
        for k in ROW_FLOATS + ROW_OPTIONAL:
            v = r.get(k, 'absent')
            if v is None and (k in ROW_OPTIONAL or r['status'] == 'unavailable'):
                continue
            if not _is_float(v):
                return False, 'invalid_types'
        if r['status'] == 'ok' and (not isinstance(r.get('n'), int) or isinstance(r['n'], bool)):
            return False, 'invalid_types'
    if obj['status'] != factors.status_of(rows):
        return False, 'status_mismatch'
    return True, 'none'


# --- consumer ---------------------------------------------------------------------------------

def months_behind(report_date, french_through):
    ry, rm = int(report_date[:4]), int(report_date[5:7])
    fy, fm = int(french_through[:4]), int(french_through[5:7])
    return (ry * 12 + rm) - (fy * 12 + fm)


def _month_end_session(day, holidays):
    from fund.calendar import us_sessions
    y, m = int(day[:4]), int(day[5:7])
    last = datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1)
    s = us_sessions(f'{y:04d}-{m:02d}-01', last.isoformat(), holidays)
    return s[-1] if s else None


def validate(obj, report_date, holidays, slice_dates=None):
    """(official | None, official_meta) — may today's table use this check?

    official_meta is always returned. Order: file → structure → status → model → version
    → future dates → complete month → window length → staleness (months_behind ≥ 3)."""
    d = obj if isinstance(obj, dict) else {}
    meta = {'french_through': d.get('french_through'), 'checked_at': d.get('fetched_at'),
            'window': d.get('window'), 'slice_sha256': d.get('slice_sha256'), 'reason': 'none'}

    def no(reason):
        meta['reason'] = reason
        return None, meta

    if obj is None:
        return no('missing_file')
    ok, reason = check_structure(obj, holidays)
    if not ok:
        return no(reason)
    if obj['status'] != 'ok':
        return no('status_not_ok')
    if obj['model'] != factors.MODEL:
        return no('model_mismatch')
    if obj['factors_calculation_version'] != factors.FACTORS_CALCULATION_VERSION:
        return no('version_mismatch')
    ft = obj['french_through']
    if ft > report_date or obj['window']['end'] > report_date or any(
            x > report_date for x in (slice_dates or [])):
        return no('future_date')
    if _month_end_session(ft, holidays) != ft:
        return no('incomplete_month')
    if obj['window']['n'] != factors.WINDOW:
        return no('short_window')
    if months_behind(report_date, ft) >= STALE_MONTHS:
        return no('stale')
    official = {'rows': obj['rows'], 'window': obj['window'], 'french_through': ft,
                'slice_sha256': obj.get('slice_sha256'),
                'factor_level': obj.get('factor_level')}
    return official, meta


def validate_file(outdir, report_date, holidays):
    path = os.path.join(outdir, CHECK)
    if not os.path.exists(path) or not os.path.exists(os.path.join(outdir, SLICE)):
        return validate(None, report_date, holidays)
    try:
        with open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
        with open(os.path.join(outdir, SLICE), encoding='utf-8') as fh:
            dates = [r[0] for r in read_slice(fh.read())]
    except (ValueError, OSError):
        _, meta = validate(None, report_date, holidays)
        meta['reason'] = 'invalid_json'
        return None, meta
    return validate(obj, report_date, holidays, slice_dates=dates)


# --- producer ---------------------------------------------------------------------------------

def _read(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


def is_noop(outdir, slice_sha):
    raw = _read(os.path.join(outdir, CHECK))
    sl, inp = _read(os.path.join(outdir, SLICE)), _read(os.path.join(outdir, INPUTS))
    if raw is None or sl is None or inp is None:
        return False
    try:
        prev = json.loads(raw.decode('utf-8'))
    except ValueError:
        return False
    return (isinstance(prev, dict) and prev.get('status') == 'ok'
            and prev.get('slice_sha256') == slice_sha
            and prev.get('factors_calculation_version') == factors.FACTORS_CALCULATION_VERSION
            and prev.get('model') == factors.MODEL
            and sha256_bytes(sl) == slice_sha
            and sha256_bytes(inp) == prev.get('inputs_sha256'))


def _dumps_compact(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False) + '\n'


def run(outdir, holidays, fetch_zip, fetch_histories, fetch_rf, now):
    """One monthly check. Returns an exit code; writes the three files or nothing."""
    zip_bytes, http = fetch_zip()
    try:
        text = extract_csv(zip_bytes)
        rows, parse_missing, copyright_line = parse_french(text)
    except (ValueError, zipfile.BadZipFile) as e:
        print(f'French file rejected: {e}')
        return 1
    sl = rows[-SLICE_ROWS:]
    csv_text = slice_csv(sl, copyright_line)
    slice_sha = sha256_bytes(csv_text.encode('utf-8'))
    if is_noop(outdir, slice_sha):
        print(f'no-op: previous check is ok and the slice through {sl[-1][0]} is unchanged')
        return 0
    french_through = sl[-1][0]
    closes, dates = fetch_histories()
    rf_obs = fetch_rf()
    inputs, prep_missing = factors.prepare(closes, dates, rf_obs, french_through, holidays)
    if inputs is None:
        print('cannot build the window: ' + '; '.join(prep_missing))
        return 1
    w = factors.window_of(inputs)
    doc = {'factors_calculation_version': factors.FACTORS_CALCULATION_VERSION,
           'model': factors.MODEL, 'window': w, 'calendar': inputs['calendar'],
           'prices': inputs['prices'], 'rf': inputs['rf'],
           'sha256': factors.inputs_hashes(inputs)}
    inputs_text = _dumps_compact(doc)
    rt = json.loads(inputs_text)            # compute from exactly what is committed
    out = compute(rt, read_slice(csv_text))
    check = {'status': out['status'], 'model': factors.MODEL,
             'factors_calculation_version': factors.FACTORS_CALCULATION_VERSION,
             'french_through': french_through, 'window': out['window'],
             'slice_sha256': slice_sha, 'zip_sha256': sha256_bytes(zip_bytes),
             'http': {'etag': (http or {}).get('etag'),
                      'last_modified': (http or {}).get('last_modified')},
             'fetched_at': now(), 'inputs_sha256': sha256_bytes(inputs_text.encode('utf-8')),
             'source': {'name': 'Kenneth R. French Data Library', 'url': FRENCH_URL,
                        'attribution': ATTRIBUTION, 'copyright': copyright_line,
                        'terms': TERMS_NOTE},
             'factor_level': out['factor_level'], 'rows': out['rows'],
             'missing': parse_missing + prep_missing + out['missing']}
    ok, reason = check_structure(check, holidays)
    if not ok:
        print(f'self-check failed ({reason}) — nothing written')
        return 1
    check_text = json.dumps(check, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    os.makedirs(outdir, exist_ok=True)
    for name, body in ((SLICE, csv_text), (INPUTS, inputs_text), (CHECK, check_text)):
        with open(os.path.join(outdir, name), 'w', encoding='utf-8', newline='') as fh:
            fh.write(body)
    print(f"check {check['status']} · French through {french_through} · "
          f"window {w['start']}..{w['end']} · inputs {len(inputs_text.encode())} B")
    return 0
