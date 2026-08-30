#!/usr/bin/env python3
"""글로벌 채권 주간·월간 정리 — 원장을 굴려 만든다.

  python scripts/build_bond_period.py --span weekly [--asof 2026-08-27]

**시세를 다시 받지 않는다.** 집계는 그날 발행본이 인쇄한 값이 쌓인 원장을 굴린 것이라
성과표 끝값이 그 기간 마지막 발행본과 갈릴 수 없다. 재수집하면 갈린다.

본문 서술은 발행본에서, 성과표는 이 집계에서 — 소스가 갈리는 이유도 같다.
「이번 주 10년물 +12bp」는 하루 변화의 합이고 그 덧셈은 기계가 해야 한다.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bond import history as ledger          # noqa: E402
from bond import period as per              # noqa: E402
from bond.sources import CREDIT_KO, UNIVERSE  # noqa: E402
from build_bond_report import FOOT, HEAD, cls, esc, ko_date, n, pct  # noqa: E402

RATE_KO = {'us': '미국', 'de': '독일', 'jp': '일본', 'gb': '영국', 'ea': '유로존'}
SPAN_KO = {'weekly': '주간', 'monthly': '월간'}


def rate_label(key):
    country, tenor = key.split('/')
    return f'{RATE_KO.get(country, country)} {tenor}'


def posts_in_range(postsdir, start, end):
    """그 기간에 실제로 발행된 글 — 서사의 유일한 소스."""
    out = []
    for f in sorted(os.listdir(postsdir)) if os.path.isdir(postsdir) else []:
        m = re.fullmatch(r'(\d{4}-\d{2}-\d{2})\.html', f)
        if not m or not (start <= m.group(1) <= end):
            continue
        s = open(os.path.join(postsdir, f)).read()
        h1 = re.search(r'<h1>(.*?)</h1>', s, re.S)
        out.append({'date': m.group(1),
                    'headline': re.sub(r'<[^>]+>', '', h1.group(1)).strip() if h1 else ''})
    return out


def table(rows, headers):
    if not rows:
        return ''
    head = ''.join(f'<th>{h}</th>' for h in headers)
    return ('<div class="tbl-scroll"><table><thead><tr>' + head
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def build(span, asof, datadir, outdir, postsdir):
    rows = ledger.read(os.path.join(datadir, 'history', 'bond_market.jsonl'))
    if not rows:
        print('원장이 비었다 — 아무것도 하지 않는다')
        return None
    asof = asof or rows[-1]['report_date']
    if span == 'weekly':
        key, (start, end) = per.iso_week_key(asof), per.week_range(asof)
    else:
        key, (start, end) = per.month_key(asof), per.month_range(asof)

    p = per.build(rows, start, end, etf_tickers=UNIVERSE)
    if not p.get('sessions'):
        print(f'{key}: 세션이 없다 — 아무것도 하지 않는다')
        return None

    stance_rows = ledger.read(os.path.join(datadir, 'history', 'bond_stance.jsonl'))
    moves = per.stance_changes(stance_rows, start, end)
    posts = posts_in_range(postsdir, start, end)

    rate_rows = [
        f'<tr><td>{rate_label(k)}</td><td>{n(v["start"], 3)}</td>'
        f'<td>{n(v["end"], 3)}</td><td{cls(v.get("bp"))}>{"" if v.get("bp") is None else f"{v['bp']:+.1f}bp"}</td>'
        f'<td class="sub">{v["sessions"]}</td></tr>'
        for k, v in p['rates'].items()]
    credit_rows = [
        f'<tr><td>{CREDIT_KO.get(k, k)}</td><td>{n(v["start"] * 100, 0)}bp</td>'
        f'<td>{n(v["end"] * 100, 0)}bp</td>'
        f'<td{cls(v.get("bp"))}>{"" if v.get("bp") is None else f"{v['bp']:+.1f}bp"}</td></tr>'
        for k, v in p['credit'].items()]
    fx_rows = [
        f'<tr><td>{k}</td><td>{n(v["start"], 4)}</td><td>{n(v["end"], 4)}</td>'
        f'<td{cls(v.get("pct"))}>{pct(v.get("pct"))}</td></tr>'
        for k, v in p['fx'].items()]
    etf_rows = [
        f'<tr><td>{k}</td><td>{n(v["start"], 2)}</td><td>{n(v["end"], 2)}</td>'
        f'<td{cls(v.get("pct"))}>{pct(v.get("pct"))}</td></tr>'
        for k, v in sorted(p['etf'].items(),
                           key=lambda x: -abs(x[1].get('pct') or 0))]

    st = p.get('us10y_standing') or {}
    gap_head, gap_tail = p.get('coverage_gap_days') or (0, 0)
    covered = ('구간을 온전히 덮습니다'
               if p['complete'] else
               f'구간 앞뒤로 {gap_head}·{gap_tail} 영업일이 비어 있어 '
               f'이 표는 덮인 구간만 말합니다')

    if moves:
        move_txt = ' '.join(
            f'{m["date"]}에 {m["axis"]}가 {m["from"]}에서 {m["to"]}로 움직였습니다.'
            for m in moves)
        recap = (f'<p>이 기간에 뷰가 움직인 지점은 {len(moves)}번입니다. {esc(move_txt)} '
                 f'각 이동이 옳았는지는 이후 실현치로 채점하는데, 누적 표본이 쌓이기 전까지는 '
                 f'적중률을 인쇄하지 않습니다 — 표본 몇 개로 성적을 매기는 것은 성적표가 '
                 f'아니라 소음이니까요.</p>')
    else:
        recap = ('<p>이 기간에 뷰 3축은 한 번도 움직이지 않았습니다. 미리 걸어 둔 조건이 '
                 '충족되지 않았다는 뜻이고, 채권 운용에서 이건 실패가 아니라 정상입니다. '
                 '움직일 이유가 없을 때 움직이지 않는 것이 규율의 목적이에요.</p>')

    if posts:
        post_txt = ''.join(
            f'<li><a href="../posts/{x["date"]}.html">{x["date"]}</a> — {esc(x["headline"])}</li>'
            for x in posts)
        narrative = (f'<p>이 기간에 나간 일간 리포트는 {len(posts)}편입니다.</p>'
                     f'<ul>{post_txt}</ul>')
    else:
        narrative = ('<p>이 기간에 나간 일간 리포트가 아직 없습니다. 아래 표는 원장에 쌓인 '
                     '종가만으로 만든 것이라, 그날의 사건 서술 없이 숫자만 남습니다.</p>')

    title = f'글로벌 채권 {SPAN_KO[span]} 정리 — {key}'
    desc = (f'{start}부터 {end}까지 글로벌 채권시장 {SPAN_KO[span]} 정리. '
            f'{p["sessions"]}거래일치 국채 커브·크레딧 스프레드·환율·채권 ETF 성과를 '
            f'원장에서 집계했습니다.')

    body = f'''<section id="b-1">
<div class="headline-card">
<h1>{esc(title)}</h1>
<p>{start} ~ {end} · 실제 세션 {p["sessions"]}일({p["first_session"]} ~ {p["last_session"]}).
{covered}.</p>
<p>기간 끝 기준 미국 10년물은 {n(st.get("value"), 2)}%입니다. 이 기간
{st.get("sessions", 0)}거래일 안에서만 보면 {n(st.get("percentile"), 1)} 백분위 자리예요 —
더 긴 시계에서 어디에 서 있는지는 일간 리포트가 매일 짚습니다.</p>
</div>
</section>

<section id="b-2">
<h2>이 기간에 나간 글</h2>
<div class="card">{narrative}</div>
</section>

<section id="b-3">
<h2>국채금리</h2>
<div class="card">
<p>기간 시작값과 끝값, 그리고 그 차이입니다. 하루하루의 변화를 더한 것이 아니라
원장의 양 끝을 맞댄 값이라, 중간에 어떤 경로를 지났는지는 일간 리포트에 있습니다.</p>
{table(rate_rows, ['만기', '시작', '끝', '변화', '세션'])}
</div>
</section>

<section id="b-6">
<h2>크레딧 스프레드</h2>
<div class="card">
<p>스프레드가 좁아지면 회사채가 국채보다 나았다는 뜻이고, 벌어지면 반대입니다.</p>
{table(credit_rows, ['구간', '시작', '끝', '변화'])}
</div>
</section>

<section id="b-7">
<h2>환율</h2>
<div class="card">
{table(fx_rows, ['통화쌍', '시작', '끝', '변화'])}
</div>
</section>

<section id="b-8">
<h2>채권 ETF</h2>
<div class="card">
<p>기간 수익률이 큰 순서입니다. 달러 기준이고 분배금은 반영하지 않은 가격 수익률입니다.</p>
{table(etf_rows, ['종목', '시작', '끝', '수익률'])}
</div>
</section>

<section id="b-9">
<h2>복기 — 뷰 3축</h2>
<div class="card">{recap}</div>
</section>'''

    html = (HEAD.replace('{{TITLE}}', esc(title)).replace('{{DESC}}', esc(desc))
            .replace('{{DATE}}', key).replace('{{KODATE}}', ko_date(p['last_session']))
            .replace(f'/bond/posts/{key}.html', f'/bond/{span}/{key}.html')
            + body
            + FOOT.replace('{{DATE}}', f'{start} ~ {end}')
            .replace('{{PREV}}', p['first_session'])
            .replace('{{SESSIONS}}', str(p['sessions'])))

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f'{key}.html')
    open(out, 'w').write(html)

    agg = os.path.join(datadir, f'period_{span}_{key}.json')
    json.dump({**p, 'key': key, 'span': span, 'stance_changes': moves,
               'posts': posts}, open(agg, 'w'), ensure_ascii=False, indent=1)
    print(f'✓ {out}  · 집계 {agg}')
    return out, key, title, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--span', choices=('weekly', 'monthly'), required=True)
    ap.add_argument('--asof', default=None)
    ap.add_argument('--datadir', default='bond/data')
    ap.add_argument('--outdir', default=None)
    ap.add_argument('--postsdir', default='bond/posts')
    a = ap.parse_args()
    build(a.span, a.asof, a.datadir, a.outdir or f'bond/{a.span}', a.postsdir)


if __name__ == '__main__':
    main()
