"""KR fund-reference block: kr/data/kr_fund_view.json + .html.

Built in collect_kr_data.py from the same run's in-memory objects — no new requests.
Three things a desk running US trend units can use from the Korean close:

  fx          USD/KRW in Korean hours (last 30-minute bar, high/low). No daily change:
              there is no previous observation on the same basis.
  cash_rates  CD 91d, KTB 3y, BOK base rate — reference rates for the cash sleeve,
              not the yield of any RP, MMF or ETF.
  observations  same-day Korean industries / stocks / Asian indices linked to a US
              reference index (fund/kr_links.py). One row per observation, only what
              exists; no composite signal. Industries come from a top-60-by-change
              list, so absence means "not in the list", never "flat".
"""

import math
from html import escape

from fund.core import _finite, digest
from fund.kr_links import LINKS
from fund.universe import UNITS

SCHEMA_VERSION = 1
CALCULATION_VERSION = '2026-10-06'
RATES = ('CD 91일', '국고채 3년', '한국은행 기준금리')
UNIT_NAME = {uid: name for uid, name, _, _ in UNITS}


def _f(x):
    """A finite number or None — non-finite input is cleaned before availability is
    judged, so one NaN cannot drop the whole block at render time."""
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _fx(session):
    w = (session or {}).get('usdkrw_intraday')
    if not w or _f(w.get('close')) is None:
        return None
    return {'last': w['close'], 'last_t': w.get('last_t'), 'high': _f(w.get('high')),
            'high_t': w.get('high_t'), 'low': _f(w.get('low')), 'low_t': w.get('low_t'),
            'bars': w.get('bars'),
            'source': '야후 30분봉, 한국장 시간대 마지막 관측(서울 외환시장 공식 종가 아님)'}


def _rates(econ):
    series = (econ or {}).get('series') or {}
    out = []
    for name in RATES:
        r = series.get(name)
        if r and _f(r.get('value')) is not None:
            out.append({'name': name, 'value': r['value'], 'date': r.get('date'),
                        'bp': _f(r.get('bp'))})
    return out


def _futures(session):
    f = (session or {}).get('us_futures_during_kr') or {}
    out = {k: {'pct': v['pct'], 'first_t': v.get('first_t'), 'last_t': v.get('last_t')}
           for k, v in f.items() if v and _f(v.get('pct')) is not None}
    return out or None


def _observations(session, industry, moves, report_date):
    ind = {r.get('name'): r for r in industry or [] if _f(r.get('change_pct')) is not None}
    stk = {r.get('name'): r for r in moves or [] if _f(r.get('change_pct')) is not None}
    peers = (session or {}).get('asia_peers') or {}
    prow, pdate = peers.get('rows') or {}, peers.get('dates') or {}
    out = []
    for uid, inds, stocks, idxs in LINKS:
        unit = UNIT_NAME.get(uid, uid)
        for n in inds:
            if n in ind:
                r = ind[n]
                out.append({'unit_id': uid, 'unit_name': unit, 'kind': 'industry', 'name': n,
                            'change_pct': r['change_pct'], 'breadth': _f(r.get('breadth')),
                            'leading': r.get('leading'), 'date': report_date})
        for n in stocks:
            if n in stk:
                out.append({'unit_id': uid, 'unit_name': unit, 'kind': 'stock', 'name': n,
                            'change_pct': stk[n]['change_pct'], 'date': report_date})
        for n in idxs:
            if _f(prow.get(n)) is not None:
                out.append({'unit_id': uid, 'unit_name': unit, 'kind': 'index', 'name': n,
                            'change_pct': prow[n], 'date': pdate.get(n)})
    return out


def build(report_date, session, econ, industry, moves, generated_at):
    missing = []
    if session and session.get('report_date') != report_date:
        missing.append(f"session: date {session.get('report_date')} != {report_date}")
        session = None
    elif not session:
        missing.append('session: missing')
    fx, fut = _fx(session), _futures(session)
    if session and fx is None:
        missing.append('fx: missing')
    rates = _rates(econ)
    if not rates:
        missing.append('cash_rates: missing')
    obs = _observations(session, industry, moves, report_date)
    if not obs:
        missing.append('observations: none')
    if not (fx or rates or obs):
        status = 'unavailable'
    else:
        status = 'partial' if missing else 'ok'
    return _finite({
        'schema_version': SCHEMA_VERSION, 'calculation_version': CALCULATION_VERSION,
        'report_date': report_date, 'generated_at': generated_at,
        'status': status, 'missing': missing,
        'source_dates': {'session': (session or {}).get('report_date'),
                         **{r['name']: r['date'] for r in rates}},
        'fx': fx, 'cash_rates': rates, 'us_futures': fut, 'observations': obs,
    })


STYLE = (
    '<style>\n'
    '.fund-kr .fk-card { background: #fff; border: 1px solid #F2F4F6; border-radius: 14px;'
    ' padding: 14px 16px; margin-bottom: 12px; break-inside: avoid-page; }\n'
    '.fund-kr .fk-k { font-size: 13px; font-weight: 800; color: #0050D9; margin: 0 0 6px; }\n'
    '.fund-kr .fk-line { font-size: 14px; color: #333D4B; margin: 2px 0; }\n'
    '.fund-kr .fk-note { font-size: 12.5px; color: #8B95A1; font-weight: 600; margin: 6px 2px 0; }\n'
    '.fund-kr td, .fund-kr th { white-space: nowrap; }\n'
    '.fund-kr .fk-p { color: #00A85A; font-weight: 700; }\n'
    '.fund-kr .fk-n { color: #FF4040; font-weight: 700; }\n'
    '</style>\n')

KIND_KO = {'industry': '업종', 'stock': '종목', 'index': '지수'}


def _pct(v):
    if v is None:
        return '<td>–</td>'
    v = round(v, 2) + 0.0
    cls = 'fk-p' if v > 0 else ('fk-n' if v < 0 else '')
    return (f'<td class="{cls}">' if cls else '<td>') + (f'{v:+.2f}%' if v else '0.00%') + '</td>'


def _md(d):
    if d and len(d) == 10 and d[4] == '-':
        return f'{int(d[5:7])}/{int(d[8:10])}'
    if d and len(d) == 7 and d[4] == '-':
        return f'{int(d[:4])}년 {int(d[5:7])}월'
    return escape(str(d)) if d else '–'


def html(data):
    if not data or data.get('status') == 'unavailable':
        return None
    lines = []
    fx = data.get('fx')
    if fx:
        parts = [f'원/달러 {fx["last"]:,.2f}원({escape(str(fx["last_t"]))})']
        for key, label in (('high', '고점'), ('low', '저점')):
            if fx.get(key) is not None:
                parts.append(f'{label} {fx[key]:,.2f}({escape(str(fx[key + "_t"]))})')
        lines.append('<div class="fk-line">' + ' · '.join(parts) + '</div>')
    for r in data.get('cash_rates') or []:
        b = round(r['bp'], 1) + 0.0 if r.get('bp') is not None else None
        bp = '' if b is None else (f' · {b:+.1f}bp' if b else ' · 변화 없음')
        lines.append(f'<div class="fk-line">{escape(r["name"])} {r["value"]:.3f}%({_md(r["date"])}){bp}</div>')
    fut = data.get('us_futures') or {}
    if fut:
        lines.append('<div class="fk-line">한국장 시간대 미국 선물 '
                     + ' · '.join(f'{escape(k)} {v["pct"]:+.2f}%' for k, v in sorted(fut.items()))
                     + '</div>')
    card = ('<div class="fk-card"><div class="fk-k">원화·현금 참고 금리·미국 선물</div>' + ''.join(lines)
            + '<div class="fk-note">원/달러는 야후 30분봉의 한국장 시간대 마지막 관측으로 서울 외환시장 '
            '공식 종가가 아니다. 금리는 현금 운용의 참고 금리이며 RP·MMF·단기채 ETF의 실제 수익률이 '
            '아니다.</div></div>') if lines else ''
    obs = data.get('observations') or []
    table = ''
    if obs:
        rows = ''.join(
            f'<tr><td>{escape(o["unit_name"])}</td><td>{KIND_KO[o["kind"]]}</td>'
            f'<td>{escape(o["name"])}</td>{_pct(o["change_pct"])}'
            f'<td>{"–" if o.get("breadth") is None else format(o["breadth"] * 100, ".0f") + "%"}</td>'
            f'<td>{_md(o.get("date"))}</td></tr>' for o in obs)
        table = ('<div class="tbl-scroll"><table><thead><tr><th>미국 참조 지수</th><th>구분</th>'
                 '<th>관측</th><th>등락률</th><th>업종 내 상승 비율</th><th>기준일</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>'
                 '<div class="fk-note">미국 개장 전 관련 업종 관측이다. 한국 업종·종목이 미국 지수를 '
                 '앞서 움직인다는 예측력은 검증하지 않았다. 업종은 등락률 상위 60개 목록에 든 경우만 '
                 '보이며, 목록에 없다고 보합인 것은 아니다.</div>')
    return (f'<div class="fund-kr" data-fund-kr="{digest(data)}" '
            f'data-report-date="{escape(data["report_date"])}">\n' + STYLE + card + table + '\n</div>')
