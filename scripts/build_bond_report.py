#!/usr/bin/env python3
"""글로벌 채권 EMP 일간 리포트 렌더러.

  python scripts/build_bond_report.py [--datadir bond/data] [--outdir bond/posts]

**산문은 여기서 저작하고 숫자는 전부 데이터 파일에서 렌더한다.** thesis 페이지와 같은
규칙이다 — 손으로 타이핑한 수치는 반드시 흔들린다(과거 FX 방향·유가 등락률 오류 전례).
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bond.sources import CREDIT_KO             # noqa: E402

WD = ['월', '화', '수', '목', '금', '토', '일']


# --- 포맷 -------------------------------------------------------------------

def n(v, d=2, dash='—'):
    return dash if v is None else f'{v:,.{d}f}'


def bp(v, dash='—'):
    return dash if v is None else f'{v:+.1f}bp'


def pct(v, d=2, dash='—'):
    return dash if v is None else f'{v:+.{d}f}%'


def cls(v):
    if v is None:
        return ''
    return ' class="up"' if v > 0 else (' class="down"' if v < 0 else '')


def ko_date(iso):
    from datetime import date
    d = date.fromisoformat(iso)
    return f'{d.year}년 {d.month}월 {d.day}일 ({WD[d.weekday()]}요일)'


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


# --- 조각 -------------------------------------------------------------------

def curve_table(node, title, note=''):
    order = ['3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y', '40Y']
    ten = node.get('tenors') or {}
    rows = []
    for t in order:
        r = ten.get(t)
        if not r:
            continue
        stale = ' <span class="sub">(전일자)</span>' if r.get('stale') else ''
        rows.append(
            f'<tr><td>{t}</td><td>{n(r["level"], 3)}</td>'
            f'<td{cls(r.get("bp"))}>{bp(r.get("bp"))}</td>'
            f'<td class="sub">{r.get("date","")}{stale}</td>'
            f'<td class="sub">{r.get("source","")}</td></tr>')
    if not rows:
        return ''
    return (f'<div class="tbl-scroll"><table><caption class="sub" '
            f'style="text-align:left;padding:0 0 6px">{title}{note}</caption>'
            '<thead><tr><th>만기</th><th>수익률(%)</th><th>1일</th>'
            '<th>기준일</th><th>출처</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')


def movers_strip(movers, kinds, limit=6):
    items = [x for x in movers if x['kind'] in kinds][:limit]
    out = []
    for x in items:
        v = x['value']
        c = 'up' if v > 0 else ('down' if v < 0 else '')
        label = CREDIT_KO.get(x['label'], x['label'])
        val = f'{v:+.1f}{x["unit"]}' if x['unit'] != '%' else f'{v:+.2f}%'
        out.append(f'<span class="mt-item"><b>{esc(label)}</b>'
                   f'<span class="{c}" style="font-weight:700">{val}</span></span>')
    return '<div class="mt-strip">' + ''.join(out) + '</div>' if out else ''


def build(datadir, outdir, sitedir):
    mk = json.load(open(os.path.join(datadir, 'bond_market.json')))
    m = json.load(open(os.path.join(datadir, 'bond_metrics.json')))
    ev = json.load(open(os.path.join(datadir, 'bond_stance_eval.json')))
    book = json.load(open(os.path.join(datadir, 'bond_stance.json')))

    rd = m['report_date']
    prev = m['prev_date']
    us = m['curves']['us']
    ust = us['tenors']
    de = m['curves'].get('de') or {}
    det = de.get('tenors') or {}
    jp = m['curves'].get('jp') or {}
    jpt = jp.get('tenors') or {}
    gb = m['curves'].get('gb') or {}
    st10 = m['standing']['us10y']
    st30 = m['standing']['us30y']
    vol = m['vol']
    cr = m['credit']
    hy, ig, ccc = cr['us_hy'], cr['us_ig'], cr['us_hy_ccc']
    fx = m['fx']
    etf = m['etf']
    bm = m['benchmark']
    misc = mk.get('misc') or {}
    ffr = (misc.get('fed_funds') or {}).get('level')
    sofr = (misc.get('sofr') or {}).get('level')
    tp = misc.get('term_premium_10y') or {}
    fwd = us['forwards']

    tlt = etf['TLT']
    tea = m['teaching']
    tlt_theory = tea['tlt_theory_pct']

    head = open(os.path.join(os.path.dirname(datadir), '..', 'bond',
                             '_head.html')).read() if False else HEAD
    title = ('미국 국채는 제자리, 움직인 건 독일 — '
             f'글로벌 채권 커브·크레딧·ETF 정리 | {rd}')
    desc = (f'{ko_date(rd)} 글로벌 채권시장 정리. 미국 국채는 전 만기 ±2bp 안쪽에서 '
            f'거의 움직이지 않았지만 10년물은 2년 표본 {n(st10["percentile"],1)} 백분위에 '
            f'서 있고, 독일 30년물이 {bp(det["30Y"]["bp"])} 내리며 커브가 눌렸습니다. '
            f'HY 스프레드 {n(hy["bp"],0)}bp, CCC {n(ccc["bp"],0)}bp의 갈림까지 정리했습니다.')

    P = []
    A = P.append

    # ------------------------------------------------------------------ §1
    A(f'''<section id="b-1">
<div class="headline-card">
<h1>미국 국채는 하루 종일 제자리였지만, 서 있는 자리가 2년 만의 꼭대기입니다</h1>
<p>{ko_date(rd)} 미국 국채는 3개월물부터 30년물까지 전부 2bp 안쪽에서만 움직였습니다.
커브 모양이 바뀐 게 아니라 커브 전체가 아주 조금 위로 밀린 하루였고, 금리 변동성을 재는 MOVE 지수도
{n(vol['move'],2)}로 1년 표본에서 {n(vol['standing']['percentile'],1)} 백분위에 머물렀습니다. 조용했다는 뜻입니다.</p>
<p>그런데 조용한 것과 편안한 것은 다릅니다. 10년물 {n(ust['10Y']['level'],2)}%는 최근 2년 구간에서
{n(st10['percentile'],1)} 백분위, 30년물 {n(ust['30Y']['level'],2)}%는 {n(st30['percentile'],1)} 백분위입니다.
2년 동안 이보다 금리가 높았던 날이 손에 꼽는다는 뜻이고, 채권을 사는 쪽에는 그만큼 표면금리가 두툼하다는 뜻이기도 합니다.</p>
<p>오늘 진짜로 움직인 곳은 미국이 아니라 독일이었습니다. 독일 30년물이 {bp(det['30Y']['bp'])},
5년물이 {bp(det['5Y']['bp'])} 내리는 동안 1년물은 오히려 {bp(det['1Y']['bp'])} 올랐습니다.
앞은 오르고 뒤는 내리는 전형적인 불 플래트닝이고, 미국 커브가 멈춰 선 날 유럽에서 혼자 일어난 일입니다.</p>
</div>
</section>

<nav class="reading-map" aria-label="빠른 이동"><span class="reading-map-label">빠른 이동</span>
<a href="#b-2">어제 대비</a><a href="#b-3">국채·커브</a><a href="#b-4">정책 기대</a>
<a href="#b-6">크레딧</a><a href="#b-7">FX·환헤지</a><a href="#b-8">ETF</a>
<a href="#b-9">뷰 3축</a><a href="#b-10">오늘의 개념</a></nav>''')

    # ------------------------------------------------------------------ §2
    top = m['diff_summary']['movers']
    A(f'''<section id="b-2">
<h2>어제 대비 무엇이 바뀌었나</h2>
<div class="card">
<p>채권 운용에서 아침에 가장 먼저 해야 할 일은 값을 읽는 게 아니라 <b>어제와 달라진 것</b>을 찾는 일입니다.
값은 어제도 있었고 오늘도 있지만, 판단을 바꾸는 건 차이니까요. {prev} 대비 크기순으로 줄을 세우면 이렇습니다.</p>
{movers_strip(top, {'rate', 'credit'}, 8)}
<p>상위 네 자리를 독일이 전부 가져갔어요. 미국에서 가장 크게 움직인 건 1년물
{bp(ust['1Y']['bp'])}였고, 그다음이 3개월물 {bp(ust['3M']['bp'])}입니다.
글로벌 채권을 운용한다면 이런 날 미국 화면만 보고 「오늘은 별일 없었다」고 적으면 곤란하죠.
그날의 사건은 다른 시간대에서 이미 끝나 있었으니까요.</p>
<p>크레딧에서는 미국 HY 스프레드가 {bp(hy['chg_bp'])} 좁아져 {n(hy['bp'],0)}bp가 됐습니다.
금리는 살짝 오르고 스프레드는 좁아졌으니, 국채는 조금 손해였지만 회사채는 그 손해를 스프레드로 일부 메운 하루입니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §3
    A(f'''<section id="b-3">
<h2>국채금리와 커브</h2>
<div class="card">
<p data-standing="rates">미국 10년물은 {n(ust['10Y']['level'],2)}%로 최근 2년({st10['sessions']}거래일) 안에서
{n(st10['percentile'],1)} 백분위, 같은 기간 최저 {n(st10['min'],2)}%·최고 {n(st10['max'],2)}% 사이에서
꼭대기에 바싹 붙어 있습니다. 30년물은 {n(ust['30Y']['level'],2)}%로 {n(st30['percentile'],1)} 백분위고요.
오늘 하루 움직임은 전 만기 {bp(ust['10Y']['bp'])} 수준이라 그 자체로는 이야깃거리가 아닙니다.
읽을거리는 「얼마나 움직였나」가 아니라 「어디에 서 있나」 쪽에 있습니다.</p>
<p>커브 모양은 「{us['shape']}」입니다. 2년물과 10년물이 같은 폭으로 함께 올랐기 때문에 기울기가 그대로예요.
이런 날을 스티프닝이나 플래트닝이라고 부르면 안 됩니다. 커브가 기울어진 게 아니라 커브 전체가 평행하게 밀린 것이고,
듀레이션이 긴 자산일수록 손실이 커지는 구조라는 점만 달라집니다.</p>
<p>장단기 금리차는 2년-10년 {n(us['spread_2s10s_bp'],1)}bp, 5년-30년 {n(us['spread_5s30s_bp'],1)}bp입니다.
장기물이 단기물보다 확실히 높은, 우상향 커브예요. 커브가 우상향이라는 건 금리가 하나도 안 움직여도 이익이 난다는 뜻이에요.
시간이 지나면 10년물이던 채권이 9년물이 되고, 커브가 우상향이면 9년 금리가 더 낮으니
그만큼 가격이 오릅니다. 만기가 짧아지며 저절로 붙는 이익이죠.
채권 아이디어를 금리 방향만으로 보면 안 되는 이유가 여기 있습니다.</p>
{curve_table(us, '미국 국채 (FRED, 만기별 고정만기 수익률)')}
<figure style="margin:16px 0 6px">
<img src="../data/yield_curves.png" alt="미국·독일·일본·영국 국채 수익률 곡선" style="width:100%;border-radius:12px;border:1px solid #F2F4F6">
<figcaption class="caption" style="margin-top:6px">네 나라를 같은 축에 겹쳐 그렸습니다. 세로 간격이 곧 금리차이고,
이 간격이 뒤에 나올 환헤지 이야기의 재료가 됩니다.</figcaption>
</figure>
<h3>독일 — 오늘의 사건</h3>
<p>독일 커브는 「{de.get('shape')}」 모양이었습니다. 1년물이 {bp(det['1Y']['bp'])} 오르는 동안 30년물이
{bp(det['30Y']['bp'])} 내렸으니, 짧은 쪽은 팔리고 긴 쪽은 사들여진 하루입니다.
2년-10년 금리차가 {n(de.get('spread_2s10s_bp'),1)}bp까지 좁아졌습니다.</p>
<p>이런 모양은 보통 두 가지 중 하나를 말합니다. 당장의 정책금리 기대는 조금 더 매파적으로 밀렸는데,
더 먼 미래의 성장이나 물가 전망은 오히려 낮아졌다는 것이죠. 미국 커브가 같은 날 평행하게 밀린 것과 대비되어
유로존 쪽에 국지적인 재료가 있었다는 신호로 읽는 것이 출발점입니다.</p>
{curve_table(de, '독일 국채 (Bundesbank)')}
<h3>일본과 영국</h3>
<p>일본은 10년물 {n(jpt['10Y']['level'],3)}%, 30년물 {n(jpt['30Y']['level'],3)}%로 사실상 제자리였습니다
(2년-10년 {n(jp.get('spread_2s10s_bp'),1)}bp). 다만 커브 자체가 네 나라 중 가장 가파릅니다 —
2년물이 {n(jpt['2Y']['level'],3)}%인데 30년물이 {n(jpt['30Y']['level'],3)}%니까요.
짧은 돈은 여전히 거의 공짜인데 긴 돈에는 값이 붙어 있다는 뜻이고, 이 구조가 뒤에 나올 환헤지 계산의 핵심입니다.</p>
<p>영국 길트는 기준일이 {list((gb.get('tenors') or {}).values())[0]['date'] if gb.get('tenors') else '—'}로 하루 늦어
당일 변화를 계산하지 않았습니다. 수준만 보면 10년물 {n((gb.get('tenors') or {}).get('10Y',{}).get('level'),2)}%로
네 나라 중 가장 높습니다.</p>
{curve_table(jp, '일본 국채 (일본 재무성)')}
{curve_table(gb, '영국 길트 (영란은행)', ' · 전일자 기준')}
</div>
</section>''')

    # ------------------------------------------------------------------ §4
    dec = m['decomposition']
    d10 = dec.get('10Y') or {}
    d5 = dec.get('5Y') or {}
    A(f'''<section id="b-4">
<h2>정책 기대와 금리의 원인 분해</h2>
<div class="card">
<p>채권 운용에서 정책금리 자체보다 중요한 건 <b>시장이 이미 무엇을 반영해 놓았는가</b>입니다.
시장이 1년 안에 100bp 인하를 이미 깔아 놨다면 「연준이 내릴 것 같다」는 견해에는 값이 없어요.
값이 있는 견해는 「시장이 반영한 것보다 더 빠르거나 더 느릴 것이다」뿐입니다.</p>
<p>지금 실효 연방기금금리는 {n(ffr,2)}%, 담보부 하루짜리 금리(SOFR)는 {n(sofr,2)}%예요.
그런데 국채 커브에서 뽑은 1년 뒤 1년 금리는 {n(fwd.get('1y1y'),2)}%로 지금보다 <b>높습니다</b>.
시장이 앞으로 1년 사이 단기금리가 올라가는 쪽에 이미 서 있다는 뜻이죠.
5년 뒤 5년 금리는 {n(fwd.get('5y5y'),2)}%인데, 먼 미래의 중립금리를 시장이 이 언저리로 본다는 얘기가 됩니다.</p>
<p><b>여기서 조심할 점</b>이 하나 있습니다. 이 선도금리는 정책금리 기대만 담고 있지 않아요.
기간프리미엄(즉 돈을 오래 묶어 두는 데 대해 따로 요구하는 대가)도 함께 들어 있습니다.
뉴욕 연준 추정치로는 10년물의 이 대가가 {n(tp.get('level'),2)}%({tp.get('date','')} 기준)네요.
그러니 선도금리가 높다고 곧바로 인상 기대라고 읽으면 곤란하고, 얼마가 대가이고 얼마가 기대인지를 갈라야 합니다.</p>
<h3>명목 = 실질 + 기대인플레</h3>
<p>금리가 왜 움직였는지를 보려면 명목금리를 물가연동국채가 알려주는 실질금리와, 둘의 차이인 기대인플레로 쪼갭니다.
{rd} 기준 10년물은 명목 {bp(d10.get('nominal_bp'))} 가운데 실질이 {bp(d10.get('real_bp'))},
기대인플레가 {bp(d10.get('breakeven_bp'))}였습니다. 즉 {d10.get('driver_ko')}가 주도한 셈입니다.
5년물은 반대로 실질 {bp(d5.get('real_bp'))} · 기대인플레 {bp(d5.get('breakeven_bp'))}로 {d5.get('driver_ko')} 쪽이었고요.</p>
<p>왜 굳이 쪼개느냐면 대응이 갈리기 때문이에요. 실질금리가 밀어 올린 상승이면 성장과 국채 발행 물량 쪽을
의심하고, 기대인플레가 밀어 올린 상승이면 유가·관세·임금 쪽을 봅니다. 오늘은 두 축 모두 1bp 안쪽이라
어느 쪽으로도 이야기를 만들 만한 날은 아니었죠. 수준만 적어 두면 실질 {n(d10.get('real_level'),2)}%,
기대인플레 {n(d10.get('bei_level'),2)}%입니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §5
    rows = []
    for it in m.get('econ') or []:
        a, p_, u, dv = it['actual'], it['previous'], it['units'], it['diff']
        rows.append(f'<tr><td>{esc(it["name"])}</td><td class="sub">{it["axis"]}</td>'
                    f'<td>{a:,.1f}{u}</td><td>{p_:,.1f}{u}</td>'
                    f'<td{cls(dv)}>{"" if dv is None else f"{dv:+,.1f}"}</td>'
                    f'<td class="sub">{it.get("ref_period","")}</td></tr>')
    econ_tbl = ('<div class="tbl-scroll"><table><thead><tr><th>지표</th><th>축</th>'
                '<th>실제</th><th>직전</th><th>변화</th><th>기준</th></tr></thead><tbody>'
                + ''.join(rows) + '</tbody></table></div>') if rows else ''
    A(f'''<section id="b-5">
<h2>경제지표 — 실제·직전·컨센서스</h2>
<div class="card">
<p>지표를 볼 때 절대 수치만 보면 시장 반응을 못 읽습니다. 물가가 2.5%에서 2.4%로 내려갔어도
컨센서스가 2.2%였다면 채권에는 악재예요. 시장은 숫자가 아니라 <b>예상과의 차이</b>에 반응하니까요.
그래서 순서를 실제 → 컨센서스 → 시장이 이미 반영한 것 → 포지션 → 가격 반응으로 놓고 봅니다.</p>
<p>아래 표는 미국 연준 경제데이터(FRED)에서 결정론적으로 받은 실제·직전 값입니다.
컨센서스는 기관 집계라 여기 없고, 실제 운용에서는 이 표 옆에 컨센서스 열을 붙여 놓고 봅니다.</p>
{econ_tbl}
</div>
</section>''')

    # ------------------------------------------------------------------ §6
    crows = []
    for k in ['us_ig', 'us_ig_bbb', 'us_hy', 'us_hy_ccc', 'euro_hy', 'em_sov',
              'em_corp', 'em_hy']:
        v = cr.get(k)
        if not v:
            continue
        s = v.get('standing') or {}
        crows.append(
            f'<tr><td>{CREDIT_KO.get(k,k)}</td><td>{n(v["bp"],0)}bp</td>'
            f'<td{cls(v.get("chg_bp"))}>{bp(v.get("chg_bp"))}</td>'
            f'<td>{n(s.get("percentile"),1)}</td><td>{s.get("band","")}</td>'
            f'<td class="sub">{v.get("date","")}</td></tr>')
    A(f'''<section id="b-6">
<h2>크레딧 스프레드</h2>
<div class="card">
<p data-standing="credit">미국 하이일드 스프레드는 {n(hy['bp'],0)}bp입니다. 숫자만 보면 감이 안 오는데,
최근 2년 표본에서 <b>{n(hy['standing']['percentile'],1)} 백분위</b>예요. 2년 동안 이보다 좁았던 날이
거의 없다는 뜻이고, 국채 대신 회사채를 들고 위험을 떠안는 대가가 지금 역사적으로 가장 얇은 축이라는 뜻입니다.
투자등급은 {n(ig['bp'],0)}bp로 {n(ig['standing']['percentile'],1)} 백분위라 그나마 보통 수준입니다.</p>
<p><b>그런데 여기서 갈립니다.</b> 하이일드 안에서도 가장 등급이 낮은 CCC 이하는
{n(ccc['bp'],0)}bp로 {n(ccc['standing']['percentile'],1)} 백분위입니다. 지수 전체는 2년 만의 최저 수준으로
좁은데, 바닥층은 거꾸로 2년 만의 최고 수준으로 벌어져 있어요. 평균 하나만 보고 「크레딧이 편안하다」고
적으면 안 되는 이유가 이 한 줄에 있습니다.</p>
<p>실무에서 이 갈림이 뜻하는 건 이렇습니다. 지수를 통째로 사는 상품은 좁은 스프레드를 사는 셈이고,
문제가 생기는 곳은 지수 안에서 비중이 작은 바닥층이라 지수 수익률에 잘 안 드러납니다.
그래서 하이일드를 볼 때는 지수 스프레드와 등급별 분포를 같이 보고, 벌어지기 시작하면 아래에서부터 벌어진다는 걸 기억합니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>구간</th><th>OAS</th><th>1일</th>
<th>2년 백분위</th><th>위치</th><th>기준일</th></tr></thead><tbody>{''.join(crows)}</tbody></table></div>
<p class="caption">스프레드는 ICE BofA 지수를 FRED가 게시한 값입니다. 게시가 하루 늦어
주식·ETF 종가일보다 항상 하루 앞선 날짜를 답니다 — 표의 기준일 열이 그 사실을 그대로 보여줍니다.</p>
<p>회사채 수익률을 볼 때는 항상 국채와 스프레드로 쪼개서 봅니다. 예를 들어 오늘 투자등급 회사채 ETF의
만기수익률은 {n(etf['LQD'].get('ytw_pct'),2)}%인데, 같은 듀레이션 언저리의 국채가 {n(ust['7Y']['level'],2)}%(7년물)이니
나머지가 신용위험의 대가입니다. 「6% 준다」가 아니라 「국채 4% + 신용 2%」로 읽는 습관이 크레딧 판단의 출발점입니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §7
    us10, jp10, de10 = ust['10Y']['level'], jpt['10Y']['level'], det['10Y']['level']
    A(f'''<section id="b-7">
<h2>환율과 환헤지</h2>
<div class="card">
<p data-standing="fx">달러지수는 {n(fx['DXY']['level'],2)}로 {pct(fx['DXY'].get('change_pct'))} 움직였습니다.
사실상 정지 상태예요. 유로·달러는 {n(fx['EURUSD']['level'],4)}({pct(fx['EURUSD'].get('change_pct'))}),
달러·엔은 {n(fx['USDJPY']['level'],2)}({pct(fx['USDJPY'].get('change_pct'))})였습니다.
오늘 환율은 이야깃거리가 아니었으니, 대신 환헤지 자체를 짚고 넘어가겠습니다.</p>
<p>글로벌 채권에서 초보가 가장 많이 놓치는 게 이 부분이에요. 미국 10년물이 {n(us10,2)}%고
일본 10년물이 {n(jp10,3)}%니까 미국채가 {n(m['us_jp_10y_bp'],1)}bp 더 준다, 그러니 미국채가 좋다 —
이렇게 끝내면 틀립니다. 일본 투자자가 엔으로 자금을 조달해 미국채를 사려면 환위험을 없애야 하고,
그러자면 달러를 선물로 되팔아야 하거든요. 그 비용이 대략 <b>두 나라의 단기금리 차이</b>만큼 붙습니다.</p>
<p>지금 미국 3개월물이 {n(ust['3M']['level'],2)}%예요. 일본의 단기금리는 이보다 훨씬 낮고,
그 차이가 그대로 헤지 비용이 됩니다. 환헤지를 하고 나면 미국채의 표면 수익률 상당 부분이 사라지죠.
남는 게 자국 국채보다 나은지, 그게 실제 판단 기준입니다.</p>
<p>유로 투자자도 사정은 같아요. 독일 10년물 {n(de10,2)}%와 미국 10년물 {n(us10,2)}%의 차이가
{n(m['us_de_10y_bp'],1)}bp인데, 헤지 후에 이 중 얼마가 남느냐가 유럽 자금이 미국채로 오느냐 마느냐를 가릅니다.</p>
<p>이 리포트는 달러 기준으로 쓰기 때문에 아래 표의 수익률은 전부 달러 기준입니다.
다만 원화 투자자라면 여기에 원·달러 변동이 그대로 더해집니다. 오늘 원·달러는
{n(fx['USDKRW']['level'],2)}({pct(fx['USDKRW'].get('change_pct'))})였습니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>통화쌍</th><th>수준</th><th>1일</th><th>기준일</th></tr></thead><tbody>
''' + ''.join(
        f'<tr><td>{k}</td><td>{n(v["level"],4)}</td>'
        f'<td{cls(v.get("change_pct"))}>{pct(v.get("change_pct"))}</td>'
        f'<td class="sub">{v.get("date","")}</td></tr>'
        for k, v in fx.items()) + '''</tbody></table></div>
</div>
</section>''')

    # ------------------------------------------------------------------ §8
    erows = []
    for t, v in etf.items():
        erows.append(
            f'<tr><td>{t}</td><td>{n(v.get("close"),2)}</td>'
            f'<td{cls(v.get("change_pct"))}>{pct(v.get("change_pct"))}</td>'
            f'<td>{n(v.get("duration"),2)}</td><td>{n(v.get("ytw_pct"),2)}%</td>'
            f'<td>{n(v.get("oas_bp"),1)}bp</td>'
            f'<td>{n(v.get("aum_bn"), 1)}</td></tr>')
    brows = ''.join(
        f'<tr><td>{c["ticker"]}</td><td>{c["weight_pct"]:.0f}%</td>'
        f'<td{cls(c["return_pct"])}>{pct(c["return_pct"])}</td>'
        f'<td{cls(c["contribution_pct"])}>{c["contribution_pct"]:+.4f}%p</td></tr>'
        for c in bm['contributions'])
    A(f'''<section id="b-8">
<h2>ETF — 상품을 고르는 일</h2>
<div class="card">
<p>여러 채권 ETF를 조합해 운용한다면 시장 분석만으로는 모자라요. 이름이 같아도 안이 다르거든요.
같은 미국 투자등급 회사채 ETF라도 듀레이션 {n(etf['LQD'].get('duration'),1)}년짜리와
{n(etf['IGIB'].get('duration'),1)}년짜리는 금리가 움직일 때 완전히 다르게 반응합니다.
그래서 상품 이름이 아니라 <b>듀레이션·만기수익률·스프레드</b>를 보고 골라요.</p>
<p>오늘 미국 국채가 전 만기 {bp(ust['10Y']['bp'])} 오르자 만기 20년 이상 국채 ETF가
{pct(tlt.get('change_pct'))}로 가장 크게 밀렸습니다. 듀레이션이 {n(tlt.get('duration'),2)}년이니
금리 1bp에 이론상 {pct(tlt_theory)} 정도 움직이는 상품이고, 실제로 그 언저리가 나온 겁니다.
반대로 듀레이션이 사실상 0인 변동금리 ETF는 {pct(etf['FLOT'].get('change_pct'))}로 거의 꿈쩍하지 않았습니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>종목</th><th>종가</th><th>1일</th>
<th>듀레이션</th><th>만기수익률</th><th>OAS</th><th>순자산(십억$)</th></tr></thead>
<tbody>{''.join(erows)}</tbody></table></div>
<p class="caption">종가는 야후 파이낸스 {rd} 기준이고, 듀레이션·만기수익률·OAS·순자산은
운용사(iShares)가 {etf['AGG'].get('nav_as_of')} 기준으로 공시한 값입니다. 기준일이 하루 다르므로
시장가와 순자산가치의 괴리는 이번 회차에서 계산하지 않았습니다 — 날짜가 어긋난 두 값을 나누면
하루치 시장 움직임이 괴리로 둔갑합니다. 순유입 추정치도 전일 순자산이 쌓인 뒤부터 나옵니다.</p>
<h3>벤치마크 바스켓을 쪼개 보기</h3>
<p>실제 펀드라면 매일 성과를 요인별로 쪼개서 설명할 수 있어야 합니다. 「오늘 얼마 벌었다」로 끝내지 않고
듀레이션에서 얼마, 크레딧에서 얼마, 환에서 얼마인지를 말할 수 있어야 해요. 아래는 그 연습입니다 —
종합채권 60 · 해외국채 15 · 신흥국채 10 · 하이일드 10 · 물가연동 5로 짠 고정 바스켓의 오늘 하루입니다.</p>
<div class="tbl-scroll"><table><thead><tr><th>종목</th><th>비중</th><th>수익률</th>
<th>기여도</th></tr></thead><tbody>{brows}
<tr><td><b>합계</b></td><td></td><td></td>
<td{cls(bm['total_pct'])}><b>{bm['total_pct']:+.4f}%p</b></td></tr></tbody></table></div>
<p>바스켓 전체는 {bm['total_pct']:+.4f}% 였습니다. 눈여겨볼 점은 비중이 60%인 종합채권이
가장 큰 마이너스 기여가 아니었다는 겁니다. 비중 15%짜리 해외국채가 더 크게 깎아먹었어요.
비중이 크다고 기여가 큰 게 아니라 <b>비중 × 그날 움직임</b>이 기여이고, 이 곱셈이 성과 분해의 전부입니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §9
    srows = []
    for k in ('duration', 'curve', 'credit'):
        a = ev['assets'][k]
        inc = ' · '.join(f"{t['desc']} (현재 {n(t['actual'],2)})"
                         for t in a['increase'] if t.get('desc'))
        srows.append(
            f'<tr><td><b>{a["name"]}</b></td>'
            f'<td><span data-axis-key="{k}" data-grade="{a["grade"]}">{a["label"]}</span></td>'
            f'<td class="sub">{a["axis"]}</td>'
            f'<td class="sub">{esc(book["assets"][k].get("thesis") or "")}</td>'
            f'<td class="sub">{esc(inc)}</td></tr>')
    A(f'''<section id="b-9">
<h2>뷰 3축 — 듀레이션·커브·크레딧</h2>
<div class="card">
<p>이 리포트의 판단은 매일 새로 그리지 않고 <b>전날 것을 물려받습니다</b>. 오늘 값이 어제와 비슷하면
판단도 어제와 같아야 하는데, 매일 백지에서 다시 쓰면 하루 만에 뒤집히기 때문입니다.
그래서 세 축 각각에 미리 조건을 걸어 두고, 그 조건이 실제로 충족됐을 때만 한 칸씩 움직입니다.</p>
<p><b>{rd}은 첫 회차입니다.</b> 세 축 모두 중립에서 출발합니다. 근거 없이 걸린 베팅을 들고 시작하면
조건이 채워질 때까지 그 베팅이 그대로 유지되기 때문에, 시작점은 언제나 「걸지 않음」이어야 합니다.</p>
<div class="tbl-scroll"><table class="stance-tbl"><thead><tr><th>축</th><th>등급</th><th>기준</th>
<th>논거</th><th>무엇이 나와야 움직이나</th></tr></thead><tbody>{''.join(srows)}</tbody></table></div>
<p>규칙은 넷입니다. 하루에 한 축은 한 칸만 움직여요. 중립에서 멀어지는 방향, 즉 베팅을 <b>거는</b>
쪽으로 갈 때만 미리 걸어 둔 조건이 충족돼야 합니다. 줄이는 쪽은 조건 없이 언제든 되고요.
한 번 움직인 뒤에는 3영업일 동안 더 늘리지 못합니다 — 늘리는 데는 인내가 필요하고
줄이는 데는 필요 없다는 원칙이죠.</p>
<p>오늘 세 축의 조건은 전부 충족되지 않았습니다. 10년물은 {n(ust['10Y']['level'],2)}%로
듀레이션을 늘릴 기준선 아래에 있었어요. 2년-10년 금리차도 스티프너 기준과 플래트너 기준
사이 한가운데에 놓였습니다.</p>
<p>크레딧도 마찬가지였습니다. 하이일드 스프레드 {n(hy['bp'],0)}bp는 늘릴 기준선과 줄일 기준선
사이였고요. 그래서 세 축 모두 중립을 유지합니다. 각 기준선의 정확한 값은 위 표의 마지막 칸에 있습니다.</p>
</div>
</section>''')

    # ------------------------------------------------------------------ §10
    A(f'''<section id="b-10">
<h2>오늘의 개념 — 듀레이션</h2>
<div class="card">
<p>채권에서 가장 먼저 몸에 붙여야 하는 숫자가 듀레이션입니다. 정의는 「금리가 1%p 움직일 때
가격이 몇 % 움직이는가」이고, 방향은 반대입니다. 금리가 오르면 가격은 내려요.</p>
<p>오늘이 마침 딱 맞는 예제를 줬습니다. 만기 20년 이상 국채 ETF는 듀레이션이 {n(tlt.get('duration'),2)}년입니다.
오늘 30년물 금리가 {bp(ust['30Y']['bp'])} 움직였으니, 공식대로면 가격은
−{n(tea['tlt_duration'],2)} × {n(ust['30Y']['bp'],1)} ÷ 100 = <b>{pct(tlt_theory)}</b>가 나와야 합니다.
실제로는 {pct(tlt.get('change_pct'))}였어요. 거의 맞았습니다.</p>
<p>완전히 똑같지 않은 이유도 알아 둘 만해요. ETF가 담은 채권은 30년물 하나가 아니라 20년부터 30년까지
섞여 있고, 그 구간의 금리가 저마다 조금씩 다르게 움직였거든요. 게다가 듀레이션은 직선으로 어림한 값이라
금리가 크게 움직일수록 오차가 커집니다. 이 휘어지는 정도를 볼록성이라 부르고, 큰 폭 변동에서는 이것까지 같이 봐요.</p>
<p>실무에서는 이 공식을 이렇게 씁니다. 포트폴리오 듀레이션이 {n(tea['ref_duration'],0)}이면
금리가 {n(tea['ref_bp'],0)}bp 오를 때 대략 {pct(tea['ref_impact_pct'])} 손실이죠.
벤치마크 듀레이션이 {n(tea['benchmark_duration'],1)}인데 우리가 {n(tea['portfolio_duration'],1)}이라면
{n(tea['active_duration'],1)}년만큼 금리 하락에 더 걸어 둔 셈이고, 그만큼이 그날 성과 차이의 대부분을 설명해요.
채권 운용에서 「지금 얼마나 걸려 있나」는 결국 이 한 숫자입니다.</p>
</div>
</section>''')

    body = '\n'.join(P)
    html = (HEAD.replace('{{TITLE}}', esc(title)).replace('{{DESC}}', esc(desc))
            .replace('{{DATE}}', rd).replace('{{KODATE}}', ko_date(rd))
            + body + FOOT.replace('{{DATE}}', rd)
            .replace('{{PREV}}', prev or '—')
            .replace('{{SESSIONS}}', str(m['sessions_in_ledger'])))

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f'{rd}.html')
    open(out, 'w').write(html)
    print(f'✓ {out}  ({len(html):,} bytes)')
    return out, title, desc, rd


HEAD = '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{{DESC}}">
<link rel="canonical" href="https://fdo2a.github.io/bond/posts/{{DATE}}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="{{TITLE}}">
<meta property="og:url" content="https://fdo2a.github.io/bond/posts/{{DATE}}.html">
<meta property="og:description" content="{{DESC}}">
<title>{{TITLE}}</title>
<style>
:root { --blue:#0064FF; --ink:#191F28; --sub:#4E5968; --muted:#8B95A1;
  --border:#E5E8EB; --border2:#F2F4F6; --up:#00A85A; --upbg:#E8F8EE;
  --down:#FF4040; --downbg:#FFE8E8; --infobg:#E8F2FF; }
* { box-sizing: border-box; }
body { font-family: 'Toss Product Sans', Pretendard, 'Noto Sans CJK KR', -apple-system, sans-serif;
  letter-spacing: -0.01em; background: #F2F4F6; color: var(--ink); margin: 0;
  word-break: keep-all; overflow-wrap: break-word; }
.container { max-width: 1120px; margin: 0 auto; padding: 0 20px 60px; }
.topbar { background: #fff; border-bottom: 1px solid var(--border2); padding: 14px 20px; }
.topbar-inner { max-width: 1120px; margin: 0 auto; display: flex; align-items: baseline; gap: 10px; }
.brand { color: var(--blue); font-weight: 800; font-size: 15px; }
.topbar-date { color: var(--muted); font-size: 13px; }
.card { background: #fff; border-radius: 14px; border: 1px solid var(--border2);
  padding: 20px 22px; margin: 16px 0; break-inside: avoid-page; }
section { break-inside: avoid-page; margin-bottom: 8px; }
h1 { font-size: 22px; margin: 0 0 10px; line-height: 1.4; }
h2 { font-size: 18.5px; font-weight: 800; margin: 26px 0 12px; padding-left: 12px; position: relative; }
h2::before { content:""; position:absolute; left:0; top:2px; bottom:2px; width:6px;
  border-radius:6px; background: var(--blue); }
h3 { font-size: 16px; font-weight: 800; margin: 22px 0 8px; }
p { font-size: 16px; line-height: 1.78; margin: 0 0 15px; color: var(--ink); max-width: 42em; }
p:last-child { margin-bottom: 0; }
.caption, .sub { font-size: 12.5px; color: var(--muted); }
.sub { font-weight: 600; }
.headline-card { background: var(--infobg); border-radius: 14px; padding: 22px 24px; margin: 16px 0; }
.up { color: var(--up); } .down { color: var(--down); }
table { border-collapse: collapse; width: 100%; font-size: 14.5px; font-variant-numeric: tabular-nums; }
thead th { background: var(--border2); border-bottom: 2px solid var(--blue); font-weight: 800;
  text-align: right; padding: 9px 10px; }
thead th:first-child, td:first-child { text-align: left; }
tbody td { padding: 8px 10px; border-bottom: 1px solid var(--border2); text-align: right; }
.tbl-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 10px; margin: 12px 0 16px; }
.mt-strip { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px; }
.mt-item { display: inline-flex; align-items: baseline; gap: 6px; padding: 7px 11px;
  background: #F9FAFB; border: 1px solid #F2F4F6; border-radius: 9999px;
  font-size: 13.5px; white-space: nowrap; }
.mt-item b { font-weight: 700; }
.reading-map { display: flex; align-items: center; gap: 8px; overflow-x: auto;
  margin: -2px 0 20px; padding: 10px 2px 4px; scrollbar-width: none; }
.reading-map::-webkit-scrollbar { display: none; }
.reading-map-label { flex: 0 0 auto; color: #8B95A1; font-size: 12px; font-weight: 700; }
.reading-map a { flex: 0 0 auto; color: #4E5968; background: #fff; border: 1px solid #E5E8EB;
  border-radius: 9999px; padding: 6px 11px; font-size: 12.5px; font-weight: 700;
  line-height: 1.2; text-decoration: none; }
.footer-note { border-top: 1px solid var(--border); margin-top: 30px; padding-top: 16px;
  font-size: 12.5px; color: var(--muted); line-height: 1.7; }
.stance-tbl { table-layout: fixed; }
@media (min-width: 561px) {
  .stance-tbl th:nth-child(1), .stance-tbl td:nth-child(1) { width: 10%; }
  .stance-tbl th:nth-child(2), .stance-tbl td:nth-child(2) { width: 14%; text-align: left; }
  .stance-tbl th:nth-child(3), .stance-tbl td:nth-child(3) { width: 14%; text-align: left; }
  .stance-tbl th:nth-child(4), .stance-tbl td:nth-child(4) { width: 31%; text-align: left; }
  .stance-tbl th:nth-child(5), .stance-tbl td:nth-child(5) { width: 31%; text-align: left; }
}
@media (max-width: 560px) {
  .container { padding-left: 14px; padding-right: 14px; }
  table { font-size: 11px; }
  th, td { padding: 5px 7px; white-space: nowrap; }
  th:first-child, td:first-child { white-space: normal; }
  .card { padding: 16px 16px; }
  .stance-tbl, .stance-tbl tbody, .stance-tbl tr, .stance-tbl td { display: block; width: auto; }
  .stance-tbl thead { display: none; }
  .stance-tbl tr { background:#fff; border:1px solid #E5E8EB; border-radius:12px;
    padding:12px 14px; margin-bottom:10px; }
  .stance-tbl td { padding:0; border:none; text-align:left; white-space:normal; }
}
@media (min-width: 1024px) {
  p, .caption, .sub, li { max-width: none; }
  p:not([class]) { font-size: 17px; line-height: 1.8; }
  h1 { font-size: 25px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-inner">
<span class="brand">Global Bond Desk</span>
<span class="topbar-date">{{KODATE}} 글로벌 채권시장 정리</span>
</div></div>
<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;display:flex;align-items:center;gap:10px;">
  <a href="../index.html" style="text-decoration:none;background:#fff;border:1px solid #E5E8EB;border-radius:9999px;padding:6px 14px;font-size:12px;font-weight:700;color:#191F28;">‹ 전체 보고서</a>
  <a href="../index.html" style="text-decoration:none;font-size:14px;font-weight:800;color:#0064FF;letter-spacing:-0.02em;">Global Bond Desk</a>
</div>
<div class="container">
'''

FOOT = '''
<div class="footer-note">
기준일 {{DATE}} · 직전 비교일 {{PREV}} · 누적 원장 {{SESSIONS}}거래일<br>
데이터: 미국 연준 경제데이터(FRED) · 독일 분데스방크 · 유럽중앙은행 · 일본 재무성 · 영란은행 · iShares · 야후 파이낸스.
축마다 게시 시차가 달라 각 표에 기준일과 출처를 함께 실었습니다.<br>
내재선도금리는 현물 수익률 곡선을 무이표채로 근사해 계산한 값이고, ETF 순유입은 순자산 변화에서
가격 수익분을 뺀 추정치입니다.<br>
본 자료는 정보 제공과 학습 목적으로 작성된 것으로, 특정 종목의 매수·매도 권유가 아닙니다.
</div>
</div>
</body>
</html>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='bond/data')
    ap.add_argument('--outdir', default='bond/posts')
    ap.add_argument('--sitedir', default='.')
    a = ap.parse_args()
    build(a.datadir, a.outdir, a.sitedir)


if __name__ == '__main__':
    main()
