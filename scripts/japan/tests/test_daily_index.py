"""일본 일간 v2 — JPX 슬롯·쌍 읽기·연쇄 검산·네이버 대조·업종 (설계 §2·§11-3·§11-4)."""
from decimal import Decimal

from japan import daily_index as I
from japan.tests import jpx_fixture as F

S, P = '2026-11-18', '2026-11-17'


def run(fake, session=S, prev=P, basic=None, day=None):
    sleeps = []
    out = I.collect(fake.get, session, prev, sleeps.append,
                    naver_basic=lambda: basic if basic is not None else F.naver_basic(),
                    naver_day=lambda: day if day is not None else F.naver_day())
    return out, sleeps


def prev_of(day, **over):
    """day 의 분모와 연쇄가 맞는 직전 판(전일비·등락률은 임의)."""
    out = {}
    for k, (cur, cmp_, _) in day.items():
        d = Decimal(cur.replace(',', '')) - Decimal(cmp_)
        out[k] = (f'{d:,.2f}', '0.00', '0.00')
    out.update(over)
    return out


def test_normal_current_slot():
    out, _ = run(F.standard())
    t = out['topix']
    assert t['status'] == 'current' and t['close'] == Decimal('3824.00') and t['denom'] == Decimal('3840.02')
    assert t['ratio'] == Decimal('-0.42') and t['direction'] == -1
    assert t['xcheck']['via'] == 'naver:basic' and t['source_id'] == 'jpx:price3'
    assert [s['slot'] for s in t['slots']] == ['', '.1'] and len(t['slots'][0]['sha256']) == 64
    s = out['sectors']
    assert s['status'] == 'current' and len(s['rows']) == 17
    ep = next(r for r in s['rows'] if r['key'] == 'Topix17ElectricalPrecision')
    assert ep['ratio'] == Decimal('1.12') and ep['name_ko'] == '전기·정밀'


def test_real_slots_pass_every_chain():
    """실측 세 판(11/16·11/17·11/18)의 TOPIX·17업종 연쇄가 모두 통과한다."""
    for day, prev in ((F.D1118, F.D1117), (F.D1117, F.D1116)):
        for k in day:
            got, why = I.chain(dict(zip(('currentPrice', 'previousDayComparison', 'previousDayRatio'), day[k])),
                               {'currentPrice': prev[k][0]})
            assert got is not None, (k, why)


def test_target_older_slot_uses_naver_day():
    """현재 = S+2 → S 를 .2, 분모를 .3 으로 고르고 네이버 /day 로 대조한다."""
    d1113 = prev_of(F.D1116)
    fake = F.standard(**{'.3': F.slot('202611131659', d1113)})
    day = F.naver_day([{'localDate': '20261113', 'closePrice': 3941.57},
                       {'localDate': '20261116', 'closePrice': 3901.37}])
    out, _ = run(fake, '2026-11-16', '2026-11-13', day=day)
    assert out['topix']['status'] == 'current', out['topix']['why']
    assert out['topix']['xcheck']['via'] == 'naver:day'
    assert [s['slot'] for s in out['topix']['slots']] == ['.2', '.3']


def test_no_target_slot_invalid_no_reuse():
    """현재 슬롯이 prev_session 날짜 → TOPIX 당일 슬롯이 없다(§11-2)."""
    fake = F.FakeJPX({'': F.slot('202611171659', F.D1117), '.1': F.slot('202611161659', F.D1116)})
    out, _ = run(fake)
    assert out['topix'] == {'status': 'invalid', 'why': '세션 날짜의 슬롯이 없다'}
    assert out['sectors']['status'] == 'invalid'


def test_denominator_outside_slots_invalid():
    out, _ = run(F.standard(), S, '2026-11-10')
    assert out['topix']['status'] == 'invalid' and out['sectors']['status'] == 'invalid'


def test_two_slots_same_date_invalid():
    out, sleeps = run(F.standard(**{'.2': F.slot('202611171659', F.D1117)}))
    assert out['topix']['status'] == 'invalid' and '둘 이상' in out['topix']['why']
    assert len(sleeps) == 2


def test_slot_shift_during_read_never_publishes_next_day():
    """표에서는 .1=S·.2=prev 였는데 쌍을 읽을 때 밀린다. S+1 의 −1.98% 가 실리지 않는다(10회차 #1)."""
    same = ('3,800.00', '0.00', '0.00')
    days = {'S-1': {'Topix': same, 'Topix17Bank': ('100.00', '0.00', '0.00')},
            'S': {'Topix': same, 'Topix17Bank': ('101.00', '1.00', '1.00')},
            'S+1': {'Topix': same, 'Topix17Bank': ('99.00', '-2.00', '-1.98')}}
    base = {k: ('100.00', '0.00', '0.00') for k in F.KEYS}

    def d(name):
        return dict(base, **days[name])
    before = {'': F.slot('202611171659', d('S')), '.1': F.slot('202611161659', d('S-1'))}
    after = {'': F.slot('202611181659', d('S+1')), '.1': F.slot('202611171659', d('S')),
             '.2': F.slot('202611161659', d('S-1'))}
    fake = F.FakeJPX(before)
    seen = {'n': 0}

    def shift(f, url):
        seen['n'] += 1
        if seen['n'] == 7:            # 표(6) 다음 첫 쌍 읽기에서 밀린다
            f.slots = {k: dict(v) for k, v in after.items()}
    fake.on_call = shift
    day = F.naver_day([{'localDate': '20261116', 'closePrice': 3800.0}, {'localDate': '20261117', 'closePrice': 3800.0}])
    out, _ = run(fake, '2026-11-17', '2026-11-16', day=day)
    s = out['sectors']
    assert s['status'] == 'current' and [x['slot'] for x in s['slots']] == ['.1', '.2']   # 다시 골랐다
    bank = next(r for r in s['rows'] if r['key'] == 'Topix17Bank')
    assert bank['ratio'] == Decimal('1.00')
    assert '-1.98' not in repr(out)


def test_impossible_stamp_unreadable():
    assert I.parse_stamp(b'202613011659') is None and I.parse_stamp(b'202611181659') == '202611181659'
    assert I.parse_stamp(b'<!DOCTYPE html>') is None and I.parse_stamp(b'20261118165') is None
    bad = F.slot('202611181659', F.D1118)
    bad['stamp'] = '202613011659'
    fake = F.standard(**{'': bad})
    out, _ = run(fake)
    assert out['topix']['status'] == 'invalid'


def test_naver_offsetless_time_invalid():
    out, _ = run(F.standard(), basic=F.naver_basic(localTradedAt='2026-11-18T15:30:02'))
    assert out['topix']['status'] == 'invalid' and '오프셋' in out['topix']['why']
    assert out['sectors']['status'] == 'invalid'


def test_slot_404_ignored():
    fake = F.standard()
    del fake.slots['.5']
    out, _ = run(fake)
    assert out['topix']['status'] == 'current'
    assert any(u.endswith('.5.time.txt') for u in fake.calls)


def test_front_back_time_mismatch_invalid_after_three_tries():
    fake = F.standard()
    fake.slots['']['time_body'] = '202611181659'
    n = {'c': 0}

    def flip(f, url):
        if url == I.time_url(''):
            n['c'] += 1
            f.slots['']['time_body'] = '202611181659' if n['c'] % 2 else '202611181658'
    fake.on_call = flip
    out, sleeps = run(fake)
    assert out['topix']['status'] == 'invalid'
    assert sleeps.count(2) >= 2


def test_last_modified_three_seconds_apart_invalid():
    fake = F.standard()
    fake.slots['']['time_lm'] = F.http_date('202611181659', sec=33)
    out, _ = run(fake)
    assert out['topix']['status'] == 'invalid'


def test_last_modified_missing_invalid():
    fake = F.standard()
    fake.slots['.1']['lm'] = None
    out, _ = run(fake)
    assert out['topix']['status'] == 'invalid'


def test_duplicate_key_invalid():
    fake = F.standard(**{'': F.slot('202611181659', F.D1118, raw_extra=', "Topix": {}')})
    out, _ = run(fake)
    assert out['topix']['status'] == 'invalid'


def test_target_before_close_invalid():
    out, _ = run(F.standard(**{'': F.slot('202611181529', F.D1118)}))
    assert out['topix']['status'] == 'invalid' and '마감 전' in out['topix']['why']


def test_denominator_intraday_version_invalid():
    """target .1 은 16:59, 분모 .2 가 15:29 장중판(연쇄 검산은 맞는다) → invalid(R8)."""
    fake = F.standard(**{'': F.slot('202611191659', prev_of(F.D1118)), '.1': F.slot('202611181659', F.D1118),
                         '.2': F.slot('202611171529', F.D1117)})
    day = F.naver_day([{'localDate': '20261117', 'closePrice': 3840.02}, {'localDate': '20261118', 'closePrice': 3824.0}])
    out, _ = run(fake, day=day)
    assert out['topix']['status'] == 'invalid' and '마감 전' in out['topix']['why']


def test_current_slot_still_updating_invalid():
    """현재 슬롯이 16:59 판이어도 Date − Last-Modified 가 1분이면 invalid."""
    fake = F.standard(**{'': F.slot('202611181659', F.D1118, date_plus=1)})
    out, _ = run(fake)
    assert out['topix']['status'] == 'invalid' and '30분' in out['topix']['why']
    assert out['sectors']['status'] == 'invalid'


def test_1531_version_kept_until_1829_invalid():
    """15:31 판이 18:29 까지 남음(Date − Last-Modified 178분) → 슬롯 시각 < 16:30 이라 invalid."""
    out, _ = run(F.standard(**{'': F.slot('202611181531', F.D1118, date_plus=178)}))
    assert out['topix']['status'] == 'invalid'


def test_1531_version_minute_old_invalid_even_if_values_final():
    out, _ = run(F.standard(**{'': F.slot('202611181531', F.D1118, date_plus=1)}))
    assert out['topix']['status'] == 'invalid' and out['sectors']['status'] == 'invalid'


def test_naver_not_close_invalid():
    out, _ = run(F.standard(), basic=F.naver_basic(marketStatus='OPEN'))
    assert out['topix']['status'] == 'invalid'


def test_naver_two_cents_off_invalid():
    out, _ = run(F.standard(), basic=F.naver_basic(closePrice='3,824.02'))
    assert out['topix']['status'] == 'invalid'


def test_naver_basic_late_date_invalid_no_day_fallback():
    called = []
    fake = F.standard()
    out = I.collect(fake.get, S, P, lambda s: None,
                    naver_basic=lambda: F.naver_basic(localTradedAt='2026-11-17T15:30:02+09:00'),
                    naver_day=lambda: called.append(1) or F.naver_day())
    assert out['topix']['status'] == 'invalid' and called == []


def test_chain_two_cents_off_invalid():
    fake = F.standard(F.D1118, dict(F.D1117, Topix=('3,840.04', '-61.35', '-1.57')))
    out, _ = run(fake, basic=F.naver_basic())
    assert out['topix']['status'] == 'invalid'


def _boundary(ratio):
    day = dict(F.D1118, Topix=('3,873.00', '-127.00', ratio))
    prev = dict(F.D1117, Topix=('4,000.00', '0.00', '0.00'))
    out, _ = run(F.standard(day, prev), basic=F.naver_basic(closePrice='3,873.00', compareToPreviousClosePrice='-127.00'))
    return out['topix']


def test_rounding_boundary_half_up():
    """4,000.00 → 3,873.00 은 정확히 −3.175% — ROUND_HALF_UP 이면 −3.18(12회차 (b)1)."""
    assert I.ratio_of(Decimal('3873.00'), Decimal('4000.00')) == Decimal('-3.18')
    assert _boundary('-3.18')['status'] == 'current'
    assert _boundary('-3.17')['status'] == 'invalid'
    assert _boundary('-3.16')['status'] == 'invalid'


def test_float_never_accepted():
    assert I.dec(3824.0) is None and I.dec('3,824.00') == Decimal('3824.00') and I.dec('--') is None
    assert I.dec('NaN') is None and I.dec('') is None


# ── 업종 (§11-4) ─────────────────────────────────────────────────────────

def test_one_sector_dashes_invalidates_sector_block_only():
    fake = F.standard(dict(F.D1118, Topix17Bank=('--', '--', '--')))
    out, _ = run(fake)
    assert out['topix']['status'] == 'current'
    assert out['sectors'] == {'status': 'invalid', 'why': '업종 은행 값이 수가 아니다'}


def test_missing_sector_key_keeps_topix():
    fake = F.standard(**{'': F.slot('202611181659', F.D1118, drop=('Topix17Bank',))})
    out, _ = run(fake)
    assert out['topix']['status'] == 'current' and out['sectors']['status'] == 'invalid'
    assert '17개' in out['sectors']['why']


def test_sector_zero_close_invalid_even_if_chain_holds():
    """은행 종가 0.00·전일비 −100.00·등락률 −100.00%(검산식은 통과) → 업종 블록 invalid(9회차 #2)."""
    fake = F.standard(dict(F.D1118, Topix17Bank=('0.00', '-100.00', '-100.00')),
                      dict(F.D1117, Topix17Bank=('100.00', '0.00', '0.00')))
    out, _ = run(fake)
    assert out['topix']['status'] == 'current' and out['sectors']['status'] == 'invalid'
    assert '양수' in out['sectors']['why']


def test_why_strings_have_no_data_numbers():
    fake = F.standard(dict(F.D1118, Topix17Bank=('--', '--', '--')))
    out, _ = run(fake)
    assert not any(c.isdigit() for c in out['sectors']['why'].replace('17', ''))
