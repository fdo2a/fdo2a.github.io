"""Turn a watch.json row into the HTML blocks that carry numbers.

The split matters: **prose is authored, numbers are rendered.** Anything a person or an
agent types by hand drifts — the brief has the scars (FX direction, oil % change). By
generating every figure from the committed snapshot, the publish gate's token comparison
against HEAD becomes meaningful rather than a formality.

Pure — takes dicts, returns strings.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

GRADE_CLASS = {
    '홀딩 강화': 'g-hold',
    '주의': 'g-watch',
    '비중 조절 검토': 'g-trim',
    'kill condition': 'g-kill',
}


def money(value, currency):
    if value is None:
        return '—'
    if currency == 'USD':
        return f'${value:,.2f}'
    return f'{value:,.0f}원'


def pct(value, signed=True):
    if value is None:
        return '—'
    return f'{value:+.1f}%' if signed else f'{value:.1f}%'


def _num(value, currency):
    """Bare figure for table cells, without the unit repeated on every row."""
    if value is None:
        return '—'
    return f'{value:,.2f}' if currency == 'USD' else f'{value:,.0f}'


def valuation_block(row, as_of):
    """The scenario table, band table and caveats — every figure from `row`."""
    cur = row.get('currency', 'KRW')
    fv, pos = row.get('fair_value'), row.get('position')
    if not fv or not pos:
        return ('<section data-block="valuation" data-computed="%s">\n'
                '<h3>밸류에이션</h3>\n<p class="muted">컨센서스 데이터가 없어 이번 회차에는 '
                '적정가치를 계산하지 않았다.</p>\n</section>' % as_of)

    unit = 'USD' if cur == 'USD' else '원'
    rows = '\n'.join(
        f'      <tr><td>{label}</td><td class="n">{_num(fv[key], cur)}</td>'
        f'<td class="n">{weight}</td><td class="n">{pct(chg)}</td></tr>'
        for label, key, weight, chg in (
            ('Bear 사이클 회귀', 'bear', '25%', pos['downside_bear_pct']),
            ('Base 연착륙', 'base', '45%', round((fv['base'] / row['price'] - 1) * 100, 1)),
            ('Bull 구조적 재평가', 'bull', '30%', pos['upside_bull_pct']),
        ))

    band_state = ('2차 관심선 아래' if pos['in_band2']
                  else '1차 관심선 아래' if pos['in_band1']
                  else '관심선 위')

    return f'''<section data-block="valuation" data-computed="{as_of}">
  <h3>밸류에이션</h3>
  <p class="lead">정규화이익법(FY1 컨센 EPS × 정규화율 × 정규화 P/E)과 자산법(2년 뒤 예상 BPS ×
  시나리오 P/B)을 각각 계산해 평균했다. 두 방법이 비슷한 값에 닿는지가 신뢰도의 척도다.</p>
  <div class="tbl-scroll">
    <table>
      <thead><tr><th>시나리오</th><th>적정가치 ({unit})</th><th>확률</th><th>현재가 대비</th></tr></thead>
      <tbody>
{rows}
        <tr class="hi"><td>확률가중</td><td class="n">{_num(fv['weighted'], cur)}</td>
          <td class="n">—</td><td class="n">{pct(-pos['vs_weighted_pct'])}</td></tr>
      </tbody>
    </table>
  </div>
  <div class="kv">
    <div><span>현재가</span><b>{money(row.get('price'), cur)}</b></div>
    <div><span>1차 관심선 (가중 −20%)</span><b>{_num(fv['band1'], cur)}</b></div>
    <div><span>2차 관심선 (−32%)</span><b>{_num(fv['band2'], cur)}</b></div>
    <div><span>현재 위치</span><b>{band_state}</b></div>
  </div>
  <p class="caveat"><b>가정이 결과를 지배한다.</b> 정규화율(80/48/25%)·배수·확률(30/45/25)은
  측정이 아니라 판단이다. Bull 확률을 50%로 올리면 현재가가 저평가로 바뀐다. 이건 모델의 결함이
  아니라 이 사이클의 실제 불확실성이며, 목표주가가 아니라 판단 보조용 기준선이다.</p>
</section>'''


def snapshot_block(row, as_of):
    """Today's raw numbers, so the reader can check the valuation's inputs."""
    cur = row.get('currency', 'KRW')
    disp = round(row['eps_fy1_high'] / row['eps_fy1_low'], 1) if (
        row.get('eps_fy1_high') and row.get('eps_fy1_low')) else None
    return f'''<section data-block="snapshot" data-as-of="{as_of}">
  <h3>오늘의 수치</h3>
  <div class="kv">
    <div><span>주가 ({row.get('price_date', '—')})</span><b>{money(row.get('price'), cur)}</b></div>
    <div><span>52주 고점 대비</span><b>{pct(row.get('pct_from_52w_high'))}</b></div>
    <div><span>FY1 컨센 EPS</span><b>{_num(row.get('eps_fy1'), cur)}</b></div>
    <div><span>FY1 P/E</span><b>{row.get('pe_fy1', '—')}배</b></div>
    <div><span>P/B ({row.get('bvps_as_of', '—')} 재무제표 기준)</span><b>{row.get('pb', '—')}배</b></div>
    <div><span>추정치 분산 (최고/최저)</span><b>{f'{disp}배' if disp else '—'}</b></div>
    <div><span>다음 실적</span><b>{row.get('next_earnings_date') or '미정'}</b></div>
  </div>
  <p class="caveat">P/B의 분모는 <b>마지막으로 <em>보고된</em> 재무제표</b>({row.get('bvps_as_of', '—')})다.
  최근 분기 실적이 발표됐어도 데이터 소스에 반영되기 전이면 자본 증가가 아직 안 잡혀 P/B가 실제보다
  높게 보인다. 손으로 보정하지 않는다 — 창작한 숫자보다 기준일이 명시된 낡은 숫자가 낫다.</p>
</section>'''


def ticker_card(symbol, row, book, href):
    """One card on the index page."""
    cur = row.get('currency', 'KRW')
    grade = book.get('grade', '홀딩 강화')
    pos = row.get('position') or {}
    vs = pos.get('vs_weighted_pct')
    return f'''    <a class="card" href="{href}" data-ticker="{symbol}">
      <div class="card-head">
        <b>{row.get('name', symbol)}</b>
        <span class="badge {GRADE_CLASS.get(grade, 'g-hold')}">{grade}</span>
      </div>
      <div class="card-px">{money(row.get('price'), cur)}</div>
      <div class="card-sub">
        확률가중 적정가치 대비 {pct(-vs) if vs is not None else '—'} ·
        52주 고점 대비 {pct(row.get('pct_from_52w_high'))}
      </div>
      <div class="card-since">등급 유지 {book.get('grade_since', '—')}부터</div>
    </a>'''
