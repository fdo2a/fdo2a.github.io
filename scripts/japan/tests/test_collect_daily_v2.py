"""일본 일간 v2 수집기 — JPX·네이버는 주입, facts·schema 2, 실패가 다른 블록에 번지지 않는다 (설계 §8·§11-1·2·4·11)."""
import json
import os
from datetime import datetime, timezone

import collect_japan_daily as C
from japan import daily_facts as JF
from japan import daily_render as R
from japan.tests import jpx_fixture as F
from japan.tests.test_collect_daily import CAL, Fake

S, P = '2026-11-18', '2026-11-17'
LATE = datetime(2026, 11, 18, 9, 30, tzinfo=timezone.utc)        # 18:30 JST
NK = ('Date of Data,Close,Open,High,Low\r\n"2026/11/17","58860.43","1","1","1"\r\n'
      '"2026/11/18","59024.28","1","1","1"\r\n')


class Fake2(Fake):
    def __init__(self, jpx=None, basic=None, day=None, jpx_error=None, step=0.0, **over):
        over.setdefault('nikkei_csv', NK)
        over.setdefault('quote', {'^N225': {'last': 59024.28, 'bar_date': S}})
        super().__init__(**over)
        self._jpx = jpx if jpx is not None else F.standard()
        self._basic, self._day, self._err = basic, day, jpx_error
        self.t, self.step, self.sleeps = 0.0, step, []

    def jpx(self, url, timeout=None):
        if self._err:
            raise self._err
        return self._jpx.get(url)

    def naver_topix_basic(self, timeout=None):
        return self._basic if self._basic is not None else F.naver_basic()

    def naver_topix_day(self, session, prev, timeout=None):
        return self._day if self._day is not None else F.naver_day()

    def sleep(self, s):
        self.sleeps.append(s)

    def clock(self):
        self.t += self.step
        return self.t


def _run(tmp_path, fake, session=S, prev=P, now=LATE):
    return C.collect(session, prev, fake, now, root=str(tmp_path), calendar=CAL, holidays=())


def test_1118_inputs_end_to_end(tmp_path):
    snap = _run(tmp_path, Fake2())
    assert snap['schema'] == 2 and snap['complete']
    assert snap['facts']['blocks'] == {'topix': 'current', 'sectors': 'current',
                                       'curve': {'s2s10': 'invalid', 's10s30': 'invalid'}}   # 고정 MOF 는 10월
    assert JF.gen_topix(snap) == ('TOPIX는 3,824.00으로 전 거래일보다 0.42% 내렸다. '
                                  '닛케이 225는 0.28% 올라 두 지수의 방향이 엇갈렸다.')
    assert '3개가 올랐고 14개가 내렸다(보합 0개)' in JF.gen_sectors(snap)
    assert '<td>TOPIX</td><td>3,824.00</td><td><span class="neg">-0.42%</span></td>' in R.render_tables(snap)['indices']
    assert snap['fetch_status']['topix'] == 'ok' and snap['fetch_status']['sectors'] == 'ok'
    ev = snap['facts']['evidence']['topix']
    assert ev['xcheck']['via'] == 'naver:basic' and [s['slot'] for s in ev['slots']] == ['', '.1']
    assert snap['calendar']['coverage']['today_missing'] == [n for _, n in __import__(
        'japan.daily_calendar', fromlist=['x']).REQUIRED]          # 고정 입력의 일정표에는 확인 창이 없다


def test_1104_inputs_no_etf(tmp_path):
    """11/04: ETF +0.24% 였던 날 — TOPIX 지수 −0.89%, 닛케이 −1.42% → 같은 방향. 스냅샷에 ETF 필드 없음."""
    s4, s2 = '2026-11-04', '2026-11-02'
    day = dict(F.D1118, Topix=('3,895.38', '-34.90', '-0.89'))
    prev = dict(F.D1117, Topix=('3,930.28', '0.00', '0.00'))
    jpx = F.FakeJPX({'': F.slot('202611041659', day), '.1': F.slot('202611021659', prev)})
    nk = ('Date of Data,Close\r\n"2026/11/02","63081.86"\r\n"2026/11/04","62188.63"\r\n')
    fake = Fake2(jpx, basic=F.naver_basic(closePrice='3,895.38', compareToPreviousClosePrice='-34.90',
                                          localTradedAt='2026-11-04T15:30:02+09:00'),
                 nikkei_csv=nk, quote={'^N225': {'last': 62188.63, 'bar_date': s4},
                                       '1306.T': {'last': 414.0, 'bar_date': s4}})
    snap = _run(tmp_path, fake, s4, s2, datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc))
    assert JF.gen_topix(snap) == ('TOPIX는 3,895.38로 전 거래일보다 0.89% 내렸다. '
                                  '닛케이 225도 1.42% 내려 두 지수가 같은 방향으로 움직였다.')
    assert '<span class="neg">-0.89%</span>' in R.render_tables(snap)['indices']
    text = json.dumps(snap, ensure_ascii=False)
    assert 'topix_etf' not in text and '414' not in text and '1306' not in text


def test_no_target_slot_invalid_complete_by_nikkei(tmp_path):
    jpx = F.FakeJPX({'': F.slot('202611171659', F.D1117), '.1': F.slot('202611161659', F.D1116)})
    snap = _run(tmp_path, Fake2(jpx))
    assert snap['complete'] and snap['facts']['blocks']['topix'] == 'invalid'
    assert JF.gen_topix(snap) == 'TOPIX 종가를 확인하지 못해 싣지 않는다.'
    assert '3840.02' not in json.dumps(snap) and '3,840.02' not in json.dumps(snap)


def test_one_sector_missing_leaves_no_sector_numbers_in_candidate(tmp_path):
    jpx = F.standard(dict(F.D1118, Topix17Bank=('--', '--', '--')))
    snap = _run(tmp_path, Fake2(jpx))
    path = os.path.join(tmp_path, 'japan', 'data', 'daily', 'candidate', f'{S}.json')
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    for key, (cur, _, ratio) in F.D1118.items():
        if key in ('Topix', 'Topix17Bank'):
            continue
        assert cur.replace(',', '') not in text and cur not in text, key
    assert snap['facts']['blocks'] == dict(snap['facts']['blocks'], topix='current', sectors='invalid')
    assert R.render_tables(snap)['sectors'] == ''
    assert JF.gen_sectors(snap) == '업종별 지수를 확인하지 못해 싣지 않는다.'
    assert '엇갈렸다' in JF.gen_topix(snap)


def _core(snap):
    keep = ('session', 'prev_session', 'complete', 'indices', 'stocks', 'movers', 'jgb', 'jgb_recollect',
            'call_rate', 'fx', 'macro', 'macro_periods', 'news_file')
    status = {k: v for k, v in snap['fetch_status'].items() if k not in ('topix', 'sectors')}
    return json.dumps({k: snap[k] for k in keep}, sort_keys=True), status


def test_jpx_exception_or_timeout_does_not_touch_other_blocks(tmp_path):
    ok = _run(tmp_path / 'a', Fake2())
    boom = _run(tmp_path / 'b', Fake2(jpx_error=TimeoutError('jpx')))
    slow = _run(tmp_path / 'c', Fake2(step=7.0))           # 호출마다 7초 — 60초 상한에 걸린다
    for snap in (boom, slow):
        assert _core(snap) == _core(ok)
        assert snap['facts']['blocks']['topix'] == 'invalid' and snap['facts']['blocks']['sectors'] == 'invalid'
    assert '시간' in slow['fetch_status']['topix'] or 'Timeout' in slow['fetch_status']['topix']


def test_nikkei_prev_row_missing_topix_alone(tmp_path):
    nk = 'Date of Data,Close\r\n"2026/11/18","59024.28"\r\n'
    snap = _run(tmp_path, Fake2(nikkei_csv=nk))
    assert snap['complete'] and snap['indices']['nikkei']['chg_pct'] is None
    assert JF.gen_topix(snap) == 'TOPIX는 3,824.00으로 전 거래일보다 0.42% 내렸다.'


def test_naver_jgb_feeds_raw_spreads(tmp_path):
    lv = {'2Y': ('1.8740', '1.8670'), '5Y': ('2.2650', '2.2580'), '10Y': ('2.8840', '2.8760'),
          '30Y': ('4.0450', '4.0620')}
    naver = {t: {'result': [{'localTradedAt': f'{S}T15:25:00+09:00', 'closePrice': now,
                             'fluctuations': f'{float(now) - float(prev):.4f}'},
                            {'localTradedAt': f'{P}T15:27:00+09:00', 'closePrice': prev}]}
             for t, (prev, now) in lv.items()}
    mof = [{'date': '2026-11-16', '2Y': 1.87, '5Y': 2.26, '10Y': 2.88, '30Y': 4.04},
           {'date': P, '2Y': 1.874, '5Y': 2.265, '10Y': 2.884, '30Y': 4.045}]
    snap = _run(tmp_path, Fake2(naver=naver, jgb_rows=mof))
    assert snap['jgb']['10Y']['source'] == 'naver'
    assert JF.gen_curve(snap) == ('2~10년 금리 스프레드는 100.9bp로 전 거래일 대비 0.1bp 축소됐다. '
                                  '10~30년 금리 스프레드는 118.6bp로 전 거래일 대비 2.5bp 확대됐다.')
    assert '2.8760' not in json.dumps({k: v for k, v in snap.items() if k != 'facts'})
