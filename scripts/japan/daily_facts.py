"""일본 일간 v2 — `facts`(검증된 새 데이터)와 코드가 쓰는 사실 문장 (2026-11-19).

원칙(사용자, 2026-11-19): **계산 가능한 사실은 코드가 생성하고, AI 는 검증된 사실을 해석하는 역할만 맡는다.**
TOPIX·업종지수·금리 스프레드의 수치와 방향은 작성자가 쓰는 자리가 없다 — 여기서 문장까지 만들고, 조립이
`<p data-gen="이름">` 으로 넣고, 게이트는 그 문장이 이 함수의 출력과 바이트로 같은지만 본다.

`facts` = {items: [{field_id, observation_date, prev_observation_date?, value, unit, source_id, status, direction?,
denom?}], blocks: {topix, sectors, curve: {s2s10, s10s30}}, evidence: {topix: {slots, xcheck}, sectors: {slots}}}.
- status: current(검증 통과·관측일 == 세션) / stale(MOF 폴백 — 직전 세션 값) / invalid(값 null, 사유는 fetch_status 에 글자로만).
- 변화 값의 `direction`(+1·0·−1)은 반올림 **전** 차의 부호다. 방향·보합·집계는 표시값이 아니라 이것으로 정한다 —
  3,840.02 → 3,840.01 은 −0.00% 로 보이지만 내린 것이다(13회차).
- 분모·슬롯 근거·네이버 대조는 전부 `facts` 아래에만 둔다(R13) — 게이트가 `facts` 를 통째로 작성자 허용 수치에서 뺀다.

Pure — 네트워크 없음. 설계: design-drafts/jp-daily-v2/jp_daily_v2_design.md §3·§4.
"""
import html as _html

from japan import daily_b as B
from japan import daily_index as IX
from japan import daily_rates as RT

SCHEMA = 2
GEN_KINDS = ('topix', 'sectors', 'curve')
GEN_SECTION = {'topix': 'equity', 'sectors': 'equity', 'curve': 'bonds', 'usual': 'equity'}
B_KINDS = ('usual',)        # B 가 있는 스냅샷(`daily_b.has_b`)에서만 — 옛 글은 세 종류 그대로(바이트 동일)
MINUS = '−'

# 문구 틀 — 바꾸면 게이트의 바이트 대조도 같이 바뀐다(같은 함수를 부른다).
TPL = {
    'topix_move': 'TOPIX는 {close}{ro} 전 거래일보다 {pct} {verb}.',
    'topix_flat': 'TOPIX는 {close}{ro} 전 거래일과 같았다.',
    'topix_invalid': 'TOPIX 종가를 확인하지 못해 싣지 않는다.',
    'nk_split': '닛케이 225는 {pct} {verb} 두 지수의 방향이 엇갈렸다.',
    'nk_same': '닛케이 225도 {pct} {verb} 두 지수가 같은 방향으로 움직였다.',
    'nk_plain': '닛케이 225는 {pct} {verb}.',
    'nk_flat': '닛케이 225는 전 거래일과 같았다.',
    'breadth': 'TOPIX-17 업종지수는 17개 업종 중 {up}개가 올랐고 {down}개가 내렸다(보합 {flat}개).',
    'ends_both': '가장 많이 오른 업종은 {top}, 가장 많이 내린 업종은 {bottom}다.',
    'ends_top': '가장 많이 오른 업종은 {top}다.',
    'ends_bottom': '가장 많이 내린 업종은 {bottom}다.',
    'sectors_invalid': '업종별 지수를 확인하지 못해 싣지 않는다.',
    'curve_move': '{seg} 금리 스프레드는 {level}bp로 전 거래일 대비 {chg} {verb}.',
    'curve_flat': '{seg} 금리 스프레드는 {level}bp로 전 거래일과 같았다.',
    'curve_stale': 'JGB 는 {day} 기준 값이라 당일 스프레드 변화를 싣지 않는다.',
    'curve_invalid': '{seg} 금리 스프레드를 확인하지 못했다.',
    'usual_both': 'TOPIX 하루 등락폭은 직전 20거래일 평균의 약 {t}배다. 닛케이 225는 약 {n}배다.',
    'usual_topix': 'TOPIX 하루 등락폭은 직전 20거래일 평균의 약 {t}배다.',
    'usual_nikkei': '닛케이 225 하루 등락폭은 직전 20거래일 평균의 약 {n}배다.',
}
UNDER_PCT, UNDER_BP = '0.01% 미만', '0.1bp 미만'


# ── 만들기(수집기) ──────────────────────────────────────────────────────

def _item(fid, value, unit, session, source, status, **extra):
    out = {'field_id': fid, 'observation_date': session, 'value': value, 'unit': unit,
           'source_id': source, 'status': status}
    out.update(extra)
    return out


def _f(d):
    return None if d is None else float(d)


def _index_items(index, session, prev):
    items, ev = [], {}
    t, s = index['topix'], index['sectors']
    src = t.get('source_id', 'jpx:price3')
    if t['status'] == 'current':
        items.append(_item('topix.close', _f(t['close']), 'index', session, src, 'current'))
        items.append(_item('topix.chg_pct', _f(t['ratio']), '%', session, src, 'current',
                           prev_observation_date=prev, direction=t['direction'],
                           denom={'date': prev, 'value': _f(t['denom']), 'source_id': t['denom_source_id']}))
        ev['topix'] = {'slots': t['slots'], 'xcheck': t['xcheck']}
    else:
        items.append(_item('topix.close', None, 'index', session, src, 'invalid'))
        items.append(_item('topix.chg_pct', None, '%', session, src, 'invalid', prev_observation_date=prev,
                           direction=None))
    ssrc = s.get('source_id', 'jpx:price3')
    if s['status'] == 'current':
        up = down = flat = 0
        for r in s['rows']:
            base = f'sector.{r["key"]}'
            items.append(_item(f'{base}.close', _f(r['close']), 'index', session, ssrc, 'current'))
            items.append(_item(f'{base}.chg_pct', _f(r['ratio']), '%', session, ssrc, 'current',
                               prev_observation_date=prev, direction=r['direction'],
                               denom={'date': prev, 'value': _f(r['denom']), 'source_id': s['denom_source_id']}))
            up, down, flat = up + (r['direction'] > 0), down + (r['direction'] < 0), flat + (r['direction'] == 0)
        for k, v in (('up', up), ('down', down), ('flat', flat)):
            items.append(_item(f'sector.breadth.{k}', v, 'count', session, ssrc, 'current'))
        ev['sectors'] = {'slots': s['slots']}
    else:
        for key in IX.SECTOR_KEYS:
            items.append(_item(f'sector.{key}.close', None, 'index', session, ssrc, 'invalid'))
            items.append(_item(f'sector.{key}.chg_pct', None, '%', session, ssrc, 'invalid',
                               prev_observation_date=prev, direction=None))
        for k in ('up', 'down', 'flat'):
            items.append(_item(f'sector.breadth.{k}', None, 'count', session, ssrc, 'invalid'))
    return items, ev


def _jgb_items(jgb, raw, session):
    items = []
    for t in RT.TENORS:
        r = (jgb or {}).get(t)
        if not isinstance(r, dict):
            continue
        src = 'naver:jgb' if r.get('source') == 'naver' else 'mof:jgb'
        status = 'current' if r.get('source') == 'naver' and r.get('period') == session else 'stale'
        items.append(_item(f'jgb.{t}.yield', r.get('value'), '%', r.get('period'), src, status))
        now, before = ((raw or {}).get(t) or (None, None))
        a, b = RT.raw_dec(now), RT.raw_dec(before)
        direction = IX.sign(a - b) if a is not None and b is not None else None
        items.append(_item(f'jgb.{t}.chg_bp', r.get('chg_bp'), 'bp', r.get('period'), src,
                           status if r.get('chg_bp') is not None else 'invalid',
                           prev_observation_date=r.get('prev_period'), direction=direction))
    return items


def _curve_items(curve, session):
    items, blocks = [], {}
    for seg, _, _ in RT.SEGMENTS:
        c = (curve or {}).get(seg) or {'status': 'invalid'}
        blocks[seg] = c['status']
        if c['status'] == 'invalid':
            items.append(_item(f'curve.{seg}.spread_bp', None, 'bp', session, None, 'invalid'))
            items.append(_item(f'curve.{seg}.chg_bp', None, 'bp', session, None, 'invalid', direction=None))
            continue
        src = 'naver:jgb' if c['source'] == 'naver' else 'mof:jgb'
        items.append(_item(f'curve.{seg}.spread_bp', _f(RT.round_bp(c['spread'])), 'bp', c['period'], src,
                           c['status']))
        items.append(_item(f'curve.{seg}.chg_bp', _f(RT.round_bp(c['chg'])), 'bp', c['period'], src, c['status'],
                           prev_observation_date=c['prev_period'], direction=IX.sign(c['chg'])))
    return items, blocks


def build(session, prev, index, jgb, raw, curve):
    """수집 결과 → `facts`. `index` = daily_index.collect, `raw` = 만기별 원시 글자, `curve` = daily_rates.spreads."""
    items, ev = _index_items(index, session, prev)
    items += _jgb_items(jgb, raw, session)
    c_items, c_blocks = _curve_items(curve, session)
    items += c_items
    return {'items': items, 'evidence': ev,
            'blocks': {'topix': index['topix']['status'], 'sectors': index['sectors']['status'], 'curve': c_blocks}}


# ── 읽기 ────────────────────────────────────────────────────────────────

def is_v2(d):
    return (d or {}).get('schema') == SCHEMA


def items(d):
    return {it['field_id']: it for it in ((d or {}).get('facts') or {}).get('items') or []}


def blocks(d):
    return ((d or {}).get('facts') or {}).get('blocks') or {}


def sector_rows(d):
    """현재(current) 업종 행 — 표 순서: 등락률 높은 순, 같으면 JPX 순서. 무효면 []."""
    if blocks(d).get('sectors') != 'current':
        return []
    it = items(d)
    rows = []
    for i, (key, name) in enumerate(IX.SECTORS):
        c, p = it[f'sector.{key}.close'], it[f'sector.{key}.chg_pct']
        if c['value'] is None or p['value'] is None or p.get('direction') not in (-1, 0, 1):
            raise TypeError('업종 항목이 비었다')
        rows.append({'key': key, 'name_ko': name, 'close': c['value'], 'chg_pct': p['value'],
                     'direction': p['direction'], 'order': i})
    rows.sort(key=lambda r: (-r['chg_pct'], r['order']))
    return rows


# ── 문장 ────────────────────────────────────────────────────────────────

def _ro(text):
    """숫자 글자 뒤 조사 로/으로 — 끝 숫자를 읽은 소리(영·삼·육은 받침이 있다, 일·칠·팔은 ㄹ)."""
    return '으로' if text[-1:] in '036' else '로'


def _pct_text(value, direction):
    """등락률 절댓값 + %. 0 이 아닌 차가 0.00 으로 반올림되면 「0.01% 미만」 — 방향은 차의 부호가 정한다."""
    if direction and round(abs(value), 2) == 0:
        return UNDER_PCT
    return f'{abs(value):.2f}%'


def _bp_text(value, direction):
    if direction and round(abs(value), 1) == 0:
        return UNDER_BP
    return f'{abs(value):.1f}bp'


def _verb(direction):
    return '올랐다' if direction > 0 else '내렸다'


def _verb_c(direction):
    return '올라' if direction > 0 else '내려'


def gen_topix(d):
    it = items(d)
    close, chg = it.get('topix.close'), it.get('topix.chg_pct')
    if blocks(d).get('topix') != 'current' or not close or not chg or close['value'] is None:
        return TPL['topix_invalid']
    c = f'{close["value"]:,.2f}'
    tdir = chg['direction']
    if tdir == 0:
        first = TPL['topix_flat'].format(close=c, ro=_ro(c))
    else:
        first = TPL['topix_move'].format(close=c, ro=_ro(c), pct=_pct_text(chg['value'], tdir), verb=_verb(tdir))
    nk = ((d.get('indices') or {}).get('nikkei') or {})
    v, denom, pct = nk.get('value'), (nk.get('denom') or {}).get('value'), nk.get('chg_pct')
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (v, denom, pct)):
        return first                       # 닛케이 등락률이 없는 날(직전 CSV 행 결측) — ② 를 뺀다
    ndir = IX.sign(v - denom)
    if ndir == 0:
        second = TPL['nk_flat']
    elif tdir == 0:
        second = TPL['nk_plain'].format(pct=_pct_text(pct, ndir), verb=_verb(ndir))
    else:
        second = TPL['nk_split' if ndir != tdir else 'nk_same'].format(pct=_pct_text(pct, ndir), verb=_verb_c(ndir))
    return f'{first} {second}'


def _signed_pct(value, direction):
    mark = '+' if direction > 0 else MINUS if direction < 0 else ''
    return f'{mark}{_pct_text(value, direction)}'


def gen_sectors(d):
    if blocks(d).get('sectors') != 'current':
        return TPL['sectors_invalid']
    it = items(d)
    counts = [(it.get(f'sector.breadth.{k}') or {}).get('value') for k in ('up', 'down', 'flat')]
    try:
        rows = sector_rows(d)
    except (KeyError, TypeError):
        rows = None
    if not rows or any(not isinstance(c, int) for c in counts):
        return TPL['sectors_invalid']            # 블록은 current 인데 항목이 빠진 스냅샷 — 싣지 않는다
    up, down, flat = counts
    out = [TPL['breadth'].format(up=up, down=down, flat=flat)]
    ups = [r for r in rows if r['direction'] > 0]
    downs = [r for r in rows if r['direction'] < 0]

    def ends(group, pick):
        if not group:
            return None
        best = pick(r['chg_pct'] for r in group)
        tied = [r for r in group if r['chg_pct'] == best]
        return '·'.join(r['name_ko'] for r in tied) + f'({_signed_pct(best, tied[0]["direction"])})'
    top, bottom = ends(ups, max), ends(downs, min)
    if top and bottom:
        out.append(TPL['ends_both'].format(top=top, bottom=bottom))
    elif top:
        out.append(TPL['ends_top'].format(top=top))
    elif bottom:
        out.append(TPL['ends_bottom'].format(bottom=bottom))
    return ' '.join(out)


def _day_ko(iso):
    y, m, dd = (iso or '0000-00-00').split('-')
    return f'{int(m)}월 {int(dd)}일'


def gen_curve(d):
    it = items(d)
    b = blocks(d).get('curve') or {}
    out, stale_day = [], None
    for seg, _, _ in RT.SEGMENTS:
        name = RT.SEGMENT_KO[seg]
        st = b.get(seg, 'invalid')
        lvl, chg = it.get(f'curve.{seg}.spread_bp'), it.get(f'curve.{seg}.chg_bp')
        if st == 'stale' and lvl and lvl.get('observation_date'):
            stale_day = stale_day or lvl['observation_date']
            continue
        if (st != 'current' or not lvl or not chg or lvl.get('value') is None or chg.get('value') is None
                or chg.get('direction') not in (-1, 0, 1)):
            out.append(TPL['curve_invalid'].format(seg=name))
            continue
        level = f'{lvl["value"]:.1f}'
        direction = chg['direction']
        if direction == 0:
            out.append(TPL['curve_flat'].format(seg=name, level=level))
            continue
        verb = '확대됐다' if direction > 0 else '축소됐다'
        out.append(TPL['curve_move'].format(seg=name, level=level, chg=_bp_text(chg['value'], direction), verb=verb))
    if stale_day:
        out.insert(0, TPL['curve_stale'].format(day=_day_ko(stale_day)))
    return ' '.join(out)


def gen_usual(d):
    """평소 대비 배수(B) — 둘 다 계산 못 하면 빈 글자(조립·게이트 모두 요소 0개를 기대한다)."""
    t, n = B.get(d, 'b.topix.usual'), B.get(d, 'b.nikkei.usual')
    if t and n:
        return TPL['usual_both'].format(t=f'{t["value"]:.1f}', n=f'{n["value"]:.1f}')
    if t:
        return TPL['usual_topix'].format(t=f'{t["value"]:.1f}')
    if n:
        return TPL['usual_nikkei'].format(n=f'{n["value"]:.1f}')
    return ''


GENERATORS = {'topix': gen_topix, 'sectors': gen_sectors, 'curve': gen_curve, 'usual': gen_usual}


def kinds(d):
    """이 스냅샷의 생성 문장 종류 — B 가 있을 때만 `usual` 이 붙는다."""
    return GEN_KINDS + (B_KINDS if B.has_b(d) else ())


def generated(d):
    """{종류: `<p data-gen="종류">…</p>` | ''} — 조립과 게이트가 같은 함수를 부른다. 빈 글자 = 그 요소 없음."""
    out = {}
    for k in kinds(d):
        text = GENERATORS[k](d)
        out[k] = f'<p data-gen="{k}">{_html.escape(text, quote=False)}</p>' if text else ''
    return out
