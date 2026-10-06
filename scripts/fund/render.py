"""Deterministic HTML for the fund board — the writer inserts it verbatim and the
gate re-renders the same JSON and compares bytes.

Everything visible is derived from the JSON alone (no clock, no environment), so
the same file always renders the same block. Number colours are set here, and the
block is skipped by apply_colors and by the prose pass, so nothing downstream
rewrites it.
"""

from html import escape

from fund.core import digest
from fund.universe import KIND_KO, KIND_ORDER

STYLE = (
    '<style>\n'
    '.fund-board .fb-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }\n'
    '.fund-board .fb-card { background: #fff; border: 1px solid #F2F4F6; border-radius: 14px;'
    ' padding: 14px 16px; break-inside: avoid-page; }\n'
    '.fund-board .fb-k { font-size: 13px; font-weight: 800; color: #0050D9; margin: 0 0 6px; }\n'
    '.fund-board .fb-big { font-size: 22px; font-weight: 800; color: #191F28; margin: 0 0 4px; }\n'
    '.fund-board .fb-line { font-size: 14px; color: #333D4B; margin: 2px 0; }\n'
    '.fund-board .fb-note { font-size: 12.5px; color: #8B95A1; font-weight: 600; margin: 6px 2px 0; }\n'
    '.fund-board .fb-h { font-size: 14px; font-weight: 800; color: #191F28; margin: 14px 2px 6px; }\n'
    '.fund-board table { font-size: 13px; }\n'
    '.fund-board td, .fund-board th { white-space: nowrap; }\n'
    '.fund-board .fb-t { color: #8B95A1; font-weight: 600; }\n'
    '.fund-board .fb-p { color: #00A85A; font-weight: 700; }\n'
    '.fund-board .fb-n { color: #FF4040; font-weight: 700; }\n'
    '@media (max-width: 560px) { .fund-board .fb-grid { grid-template-columns: 1fr; } }\n'
    '</style>\n')

DASH = '–'


def _num(v, nd=1, sign=False, unit=''):
    if v is None:
        return DASH
    v = round(v, nd) + 0.0          # -0.0 -> 0.0: a value that rounds to zero has no sign
    s = f'{v:+,.{nd}f}' if sign and v != 0 else f'{v:,.{nd}f}'
    return s + unit


def _signed_cell(v, nd=1, unit=''):
    if v is None:
        return f'<td>{DASH}</td>'
    r = round(v, nd)
    cls = 'fb-p' if r > 0 else ('fb-n' if r < 0 else '')
    attr = f' class="{cls}"' if cls else ''
    return f'<td{attr}>{_num(v, nd, True, unit)}</td>'


def _md(d):
    """'2026-09-30' -> '9/30'; anything else is printed as is."""
    if d and len(d) == 10 and d[4] == '-' and d[7] == '-':
        return f'{int(d[5:7])}/{int(d[8:10])}'
    return escape(str(d)) if d else DASH


def _regime_card(mr):
    if not mr:
        return ('<div class="fb-card"><div class="fb-k">시장 국면</div>'
                '<div class="fb-line">국면을 가를 S&amp;P 500 이력이 부족하다.</div></div>')
    held = (f'{_md(mr["since"])}부터 {mr["sessions_held"]}거래일' if mr['since_exact']
            else f'최소 {mr["sessions_held"]}거래일')
    lines = [f'<div class="fb-big">{escape(mr["name"])}</div>',
             f'<div class="fb-line">{held}'
             + (f' · 직전 {escape(mr["prev"])}' if mr.get('prev') else '') + '</div>']
    if mr.get('pending_name'):
        lines.append(f'<div class="fb-line">오늘 판정 {escape(mr["pending_name"])} '
                     f'{mr["pending_sessions"]}거래일째 — '
                     f'{mr["rules"]["confirm_sessions"]}거래일 이어지면 전환</div>')
    i = mr['inputs']
    lines.append(f'<div class="fb-line">SPY {_num(i["close"], 2)} · 50일선 {_num(i["sma50"], 2)}'
                 f' · 200일선 {_num(i["sma200"], 2)}(20거래일 전 {_num(i["sma200_prev"], 2)})</div>')
    lines.append(f'<div class="fb-line">3개월 {_num(i["ret_3m"], 1, True, "%")}'
                 f' · 52주 고점 대비 {_num(i["drawdown"], 1, True, "%")}</div>')
    lines.append(f'<div class="fb-note">{escape(mr["basis"])}. 52주 고점 대비 '
                 f'{_num(mr["rules"]["drawdown_pct"], 0)}% 이하이면서 50일선 아래면 단기 약세, '
                 f'200일선 아래이고 200일선이 내려가면 장기 약세. '
                 f'{escape(mr["residual_note"])}.</div>')
    return '<div class="fb-card"><div class="fb-k">시장 국면</div>' + ''.join(lines) + '</div>'


def _risk_card(liq, risk):
    lines = []
    net = (liq or {}).get('net')
    nf = (liq or {}).get('nfci')
    if net:
        lines.append(f'<div class="fb-line">순유동성 {_num(net["level_bn"], 0)}십억 달러'
                     f'({_md(net["date"])}) · 4주 {_num(net["chg_4w_bn"], 0, True)}</div>')
    if nf:
        lines.append(f'<div class="fb-line">NFCI {_num(nf["level"], 2)}({_md(nf["date"])})'
                     f' · 4주 {_num(nf["chg_4w"], 2, True)}'
                     + (' · 평균보다 느슨' if nf.get('looser_than_average') else ' · 평균보다 빡빡')
                     + '</div>')
    if liq and liq.get('direction'):
        lines.append(f'<div class="fb-line">유동성 방향 <b>{escape(liq["direction"])}</b></div>')
    vix = (risk or {}).get('vix')
    if vix:
        n = vix.get('sessions')
        span = '최근 2년' if isinstance(n, int) and n >= 504 else (
            f'최근 {n}거래일' if isinstance(n, int) else None)
        lines.append(f'<div class="fb-line">VIX {_num(vix["level"], 1)}'
                     + (f' · {span} 중 {_num(vix["percentile_2y"], 0)}% 위치' if span else '')
                     + '</div>')
    hy = (risk or {}).get('hy_spread')
    if hy:
        lines.append(f'<div class="fb-line">하이일드 스프레드 {_num(hy["level"], 2)}%'
                     f'({_md(hy["date"])}) · 5거래일 {_num(hy["chg_5d_bp"], 0, True)}bp</div>')
    rr = (risk or {}).get('real_10y')
    if rr:
        lines.append(f'<div class="fb-line">10년 실질금리 {_num(rr["level"], 2)}%'
                     f'({_md(rr["date"])}) · 5거래일 {_num(rr["chg_5d_bp"], 0, True)}bp</div>')
    if not lines:
        lines.append('<div class="fb-line">유동성·위험 신호 자료가 없다.</div>')
    note = ('<div class="fb-note">순유동성은 연준 총자산에서 재무부 일반계정과 역레포를 뺀 '
            '수요일 기준 단순 대리 지표다. 유동성 방향은 순유동성과 NFCI의 4주 변화가 '
            '같은 쪽일 때만 완화·긴축으로 부른다.</div>') if liq else ''
    return ('<div class="fb-card"><div class="fb-k">유동성·위험 신호</div>'
            + ''.join(lines) + note + '</div>')


HEAD = ('<thead><tr><th>지수</th><th>순위(5거래일 전)</th><th>1개월</th><th>3개월</th>'
        '<th>SPY 대비 3개월</th><th>대비 변화</th><th>12-1 모멘텀</th><th>변동성</th>'
        '<th>1일 VaR 95%</th><th>베타</th><th>50/200일선</th><th>52주 고점 대비</th></tr></thead>')


def _trend(u):
    if u['above_50'] is None or u['above_200'] is None:
        return DASH
    return ('위' if u['above_50'] else '아래') + '/' + ('위' if u['above_200'] else '아래')


def _rank(u):
    if u['rank'] is None:
        return DASH
    return f'{u["rank"]}({u["rank_5d"]})'


def _row(u):
    name = f'{escape(u["name"])} <span class="fb-t">{escape(u["ticker"])}</span>'
    if u['status'] != 'ok':
        return f'<tr><td>{name}</td><td colspan="11">이번 마감 시세 없음</td></tr>'
    return ('<tr>'
            f'<td>{name}</td><td>{_rank(u)}</td>'
            + _signed_cell(u['ret_1m'], 1, '%') + _signed_cell(u['ret_3m'], 1, '%')
            + _signed_cell(u['rel_3m'], 1, '%p') + _signed_cell(u['rel_3m_chg_pp'], 1, '%p')
            + _signed_cell(u['mom_12_1'], 1, '%')
            + f'<td>{_num(u["vol_60"], 1, unit="%")}</td>'
            + f'<td>{_num(u["var_1d_95"], 1, unit="%")}</td>'
            + f'<td>{_num(u["beta_60"], 2)}</td>'
            + f'<td>{_trend(u)}</td>'
            + _signed_cell(u['drawdown_52w'], 1, '%')
            + '</tr>')


def _tables(units):
    parts = []
    for kind in KIND_ORDER:
        rows = [u for u in units if u['kind'] == kind]
        if not rows:
            continue
        if kind != 'benchmark':
            rows.sort(key=lambda u: (u['rank'] is None, u['rank'] or 0, u['id']))
        parts.append(f'<div class="fb-h">{KIND_KO[kind]}</div>'
                     '<div class="tbl-scroll"><table>' + HEAD + '<tbody>'
                     + ''.join(_row(u) for u in rows) + '</tbody></table></div>')
    return ''.join(parts)


def board_html(data):
    if not data or data.get('status') == 'unavailable':
        return None
    basis = data['rank_basis']
    note = (f'<div class="fb-note">수정종가, {_md(basis["date"])} 마감, 거래일 기준(1개월 21·3개월 63·'
            f'12-1 모멘텀은 252거래일 전부터 21거래일 전까지). 순위는 위험선호·방어 스타일·지역 '
            f'{basis["n"]}종의 3개월 수익률 순서이고 괄호는 5거래일 전({_md(basis["date_5d"])}) 순위, '
            f'「대비 변화」는 SPY 대비 3개월 초과수익이 그사이 얼마나 바뀌었는지를 뜻한다. '
            f'변동성은 최근 60거래일 일간 수익률의 연율, VaR는 최근 60거래일 표본의 1일 VaR'
            f'(역사적 방식)로 ETF 기준이며 종목을 골라 만든 묶음의 위험과 같지 않다. '
            f'방어 스타일은 손실 회피나 헤지 성능을 뜻하지 않는다.</div>')
    return (f'<div class="fund-board" data-fund-board="{digest(data)}" '
            f'data-report-date="{escape(data["report_date"])}">\n'
            + STYLE
            + '<div class="fb-grid">' + _regime_card(data.get('market_regime'))
            + _risk_card(data.get('liquidity'), data.get('risk')) + '</div>\n'
            + _tables(data['units']) + '\n' + note + '\n</div>')
