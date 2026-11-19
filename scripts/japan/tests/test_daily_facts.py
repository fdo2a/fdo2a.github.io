"""일본 일간 v2 — facts 와 코드가 쓰는 사실 문장 (설계 §3·§4·§11-1)."""
import copy
import json
from decimal import Decimal

from japan import daily_facts as FX
from japan import daily_index as I
from japan import daily_rates as RT
from japan.tests import jpx_fixture as F

S, P = '2026-11-18', '2026-11-17'


def index_from(day, prev, session=S, prev_s=P):
    """고정 판 두 개 → daily_index.collect 와 같은 모양(검산을 실제로 돌린다)."""
    def ent(v):
        return dict(zip(('currentPrice', 'previousDayComparison', 'previousDayRatio'), v))
    t, why = I.chain(ent(day['Topix']), ent(prev['Topix']))
    assert t, why
    slots = [{'slot': '', 'jpx_time': '202611181659', 'last_modified': 'x', 'sha256': '0' * 64}]
    topix = dict(t, status='current', why=None, slots=slots, xcheck={'via': 'naver:basic'},
                 source_id='jpx:price3', denom_source_id='jpx:price3.1')
    rows = []
    for key in I.SECTOR_KEYS:
        r, why = I.chain(ent(day[key]), ent(prev[key]))
        assert r, (key, why)
        rows.append(dict(r, key=key, name_ko=I.SECTOR_NAMES[key]))
    return {'topix': topix, 'sectors': {'status': 'current', 'why': None, 'rows': rows, 'slots': slots,
                                        'source_id': 'jpx:price3', 'denom_source_id': 'jpx:price3.1'}}


NK_1118 = {'value': 59024.28, 'chg_pct': 0.28, 'denom': {'date': P, 'value': 58860.43}}
NK_1104 = {'value': 62188.63, 'chg_pct': -1.42, 'denom': {'date': '2026-11-02', 'value': 63081.86}}
JGB = {t: {'value': v, 'period': S, 'prev_period': P, 'chg_bp': c, 'unit': '%', 'source': 'naver'}
       for t, v, c in (('2Y', 1.867, -0.7), ('5Y', 2.258, -0.7), ('10Y', 2.876, -0.8), ('30Y', 4.062, 1.7))}
RAW = {'2Y': ('1.8670', '1.8740'), '5Y': ('2.2580', '2.2650'), '10Y': ('2.8760', '2.8840'), '30Y': ('4.0620', '4.0450')}


def snap(index=None, nikkei=NK_1118, jgb=JGB, raw=RAW, session=S, prev=P):
    index = index or index_from(F.D1118, F.D1117)
    curve = RT.spreads(jgb, raw, session)
    return {'schema': 2, 'session': session, 'prev_session': prev,
            'indices': {'nikkei': dict(nikkei, ok=True)},
            'jgb': jgb, 'facts': FX.build(session, prev, index, jgb, raw, curve)}


def test_1118_sentences():
    d = snap()
    assert FX.gen_topix(d) == ('TOPIX는 3,824.00으로 전 거래일보다 0.42% 내렸다. '
                               '닛케이 225는 0.28% 올라 두 지수의 방향이 엇갈렸다.')
    assert FX.gen_sectors(d) == ('TOPIX-17 업종지수는 17개 업종 중 3개가 올랐고 14개가 내렸다(보합 0개). '
                                 '가장 많이 오른 업종은 전기·정밀(+1.12%), 가장 많이 내린 업종은 소매(−1.55%)다.')
    assert FX.gen_curve(d) == ('2~10년 금리 스프레드는 100.9bp로 전 거래일 대비 0.1bp 축소됐다. '
                               '10~30년 금리 스프레드는 118.6bp로 전 거래일 대비 2.5bp 확대됐다.')


def test_1104_same_direction():
    """11/04: TOPIX 3,930.28 → 3,895.38(−0.89%, 네이버 /day 실측 종가), 닛케이 −1.42% → 같은 방향."""
    day = dict(F.D1118, Topix=('3,895.38', '-34.90', '-0.89'))
    prev = dict(F.D1117, Topix=('3,930.28', '0.00', '0.00'))
    d = snap(index_from(day, prev), NK_1104, session='2026-11-04', prev='2026-11-02')
    assert FX.gen_topix(d) == ('TOPIX는 3,895.38로 전 거래일보다 0.89% 내렸다. '
                               '닛케이 225도 1.42% 내려 두 지수가 같은 방향으로 움직였다.')


def test_tied_top_lists_both_in_table_order():
    day = dict(F.D1118)
    day['Topix17Machine'] = ('789.29', '8.88', '1.14')
    day['Topix17ElectricalPrecision'] = ('540.07', '6.08', '1.14')
    prev = dict(F.D1117, Topix17Machine=('780.41', '0', '0'))
    d = snap(index_from(day, prev))
    assert '가장 많이 오른 업종은 기계·전기·정밀(+1.14%)' in FX.gen_sectors(d)


def test_all_down_drops_up_clause():
    down = {k: (v[0], v[1], v[2]) for k, v in F.D1118.items()}
    for k in ('Topix17Energy', 'Topix17Machine', 'Topix17ElectricalPrecision'):
        cur = Decimal(F.D1117[k][0].replace(',', '')) - Decimal('1.00')
        down[k] = (f'{cur:,.2f}', '-1.00', str(I.ratio_of(cur, Decimal(F.D1117[k][0].replace(',', '')))))
    text = FX.gen_sectors(snap(index_from(down, F.D1117)))
    assert '0개가 올랐고 17개가 내렸다' in text and '가장 많이 오른' not in text
    assert '가장 많이 내린 업종은 소매(−1.55%)다.' in text


def test_nikkei_unchanged_no_direction_judgement():
    nk = dict(NK_1118, value=58860.43, chg_pct=0.0)
    t = FX.gen_topix(snap(nikkei=nk))
    assert t.endswith('닛케이 225는 전 거래일과 같았다.') and '엇갈' not in t and '같은 방향' not in t


def test_tiny_topix_drop_is_a_drop():
    """3,840.02 → 3,840.01(원천 −0.00%), 닛케이 +0.28% → 「0.01% 미만 내렸다」 + 「엇갈렸다」(13회차)."""
    day = dict(F.D1118, Topix=('3,840.01', '-0.01', '-0.00'))
    d = snap(index_from(day, F.D1117))
    assert FX.gen_topix(d) == ('TOPIX는 3,840.01로 전 거래일보다 0.01% 미만 내렸다. '
                               '닛케이 225는 0.28% 올라 두 지수의 방향이 엇갈렸다.')
    assert FX.items(d)['topix.chg_pct']['direction'] == -1


def test_exact_flat_topix():
    day = dict(F.D1118, Topix=('3,840.02', '0.00', '0.00'))
    t = FX.gen_topix(snap(index_from(day, F.D1117)))
    assert t == 'TOPIX는 3,840.02로 전 거래일과 같았다. 닛케이 225는 0.28% 올랐다.'


def test_sector_tiny_rise_counts_up_exact_zero_counts_flat():
    """업종 하나가 20,000.00 → 20,000.01(표시 0.00%, 차 양수) → 상승, 차 0 → 보합."""
    prev = dict(F.D1117, Topix17Bank=('20,000.00', '0', '0'), Topix17Retail=('20,000.00', '0', '0'))
    day = dict(F.D1118, Topix17Bank=('20,000.01', '0.01', '0.00'), Topix17Retail=('20,000.00', '0.00', '0.00'))
    it = FX.items(snap(index_from(day, prev)))
    assert it['sector.Topix17Bank.chg_pct']['direction'] == 1 and it['sector.Topix17Retail.chg_pct']['direction'] == 0
    assert (it['sector.breadth.up']['value'], it['sector.breadth.flat']['value']) == (4, 1)


def test_curve_direction_from_snapshot_not_value():
    """direction +1 인데 value 0.0 → 「0.1bp 미만 확대됐다」, direction 0 → 「같았다」(조립이 value 로 다시 판정하지 않는다)."""
    d = snap()
    it = FX.items(d)
    it['curve.s2s10.chg_bp'].update(value=0.0, direction=1)
    it['curve.s10s30.chg_bp'].update(value=0.0, direction=0)
    assert FX.gen_curve(d) == ('2~10년 금리 스프레드는 100.9bp로 전 거래일 대비 0.1bp 미만 확대됐다. '
                               '10~30년 금리 스프레드는 118.6bp로 전 거래일과 같았다.')


def test_curve_tiny_negative_from_raw():
    raw = dict(RAW, **{'2Y': ('1.8804', '1.8800'), '10Y': ('2.8800', '2.8800')})
    assert FX.gen_curve(snap(raw=raw)).startswith('2~10년 금리 스프레드는 100.0bp로 전 거래일 대비 0.1bp 미만 축소됐다.')


def test_curve_mof_fallback_stale_sentence():
    jgb = {t: dict(r, period=P, prev_period='2026-11-16', source='mof') for t, r in JGB.items()}
    d = snap(jgb=jgb)
    assert FX.gen_curve(d) == 'JGB 는 11월 17일 기준 값이라 당일 스프레드 변화를 싣지 않는다.'


def test_curve_missing_2y():
    jgb = dict(JGB, **{'2Y': None})
    raw = {k: v for k, v in RAW.items() if k != '2Y'}
    assert FX.gen_curve(snap(jgb=jgb, raw=raw)) == ('2~10년 금리 스프레드를 확인하지 못했다. '
                                                     '10~30년 금리 스프레드는 118.6bp로 전 거래일 대비 2.5bp 확대됐다.')


def test_topix_invalid_no_second_sentence():
    idx = index_from(F.D1118, F.D1117)
    idx['topix'] = {'status': 'invalid', 'why': '세션 날짜의 슬롯이 없다'}
    idx['sectors'] = {'status': 'invalid', 'why': 'x'}
    d = snap(idx)
    assert FX.gen_topix(d) == 'TOPIX 종가를 확인하지 못해 싣지 않는다.'
    assert FX.gen_sectors(d) == '업종별 지수를 확인하지 못해 싣지 않는다.'
    it = FX.items(d)
    assert it['topix.close']['value'] is None and it['topix.close']['status'] == 'invalid'


def test_sector_invalid_keeps_topix_and_nikkei_comparison():
    idx = index_from(F.D1118, F.D1117)
    idx['sectors'] = {'status': 'invalid', 'why': '업종 키가 정해진 17개와 다르다'}
    d = snap(idx)
    assert '엇갈렸다' in FX.gen_topix(d) and FX.gen_sectors(d) == '업종별 지수를 확인하지 못해 싣지 않는다.'


def test_nikkei_change_missing_drops_second_sentence():
    nk = {'value': 59024.28, 'chg_pct': None, 'denom': None}
    assert FX.gen_topix(snap(nikkei=nk)) == 'TOPIX는 3,824.00으로 전 거래일보다 0.42% 내렸다.'


def test_facts_shape_and_evidence_only_under_facts():
    d = snap()
    it = FX.items(d)
    c = it['topix.chg_pct']
    assert c['denom'] == {'date': P, 'value': 3840.02, 'source_id': 'jpx:price3.1'}
    assert c['direction'] == -1 and c['observation_date'] == S and c['prev_observation_date'] == P
    assert it['curve.s2s10.chg_bp']['value'] == -0.1 and it['curve.s2s10.chg_bp']['direction'] == -1
    rest = copy.deepcopy(d)
    del rest['facts']
    text = json.dumps(rest, ensure_ascii=False)
    for n in ('3824', '3840.02', '539.97', '100.9', '118.6', '1.12', '1.55'):
        assert n not in text


def test_generated_wraps_and_escapes():
    g = FX.generated(snap())
    assert g['topix'].startswith('<p data-gen="topix">TOPIX는 ') and g['topix'].endswith('</p>')
    assert set(g) == {'topix', 'sectors', 'curve'}
