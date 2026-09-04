"""채권 리포트도 네이버 국채 종가를 쓴다 — 미국 2Y·길트·한국 커브가 목적.

기존 소스의 시차가 그대로 커브에 남아 있었다 (2026-09-02 실측):
  미국 2Y  FRED 09-01 (T-1)   ← 10Y 는 야후 09-02, 2s10s 두 다리가 갈린다
  길트     BOE  08-28 (T-5)
  한국     ECOS 3Y·10Y 두 점뿐 — 커브라 부를 수도 없다
네이버는 셋 다 T-0 로, 그것도 전 만기를 한 날짜로 준다.
"""
import importlib

from scripts.bond import sources as src

collect = importlib.import_module('collect_bond_data')


def test_naver_bond_covers_the_nations_whose_curves_lag():
    assert {'us', 'gb', 'kr'} <= set(src.NAVER_BOND)


def test_naver_codes_are_reuters_government_bond_symbols():
    assert src.NAVER_BOND['us']['2Y'] == 'US2YT=RR'
    assert src.NAVER_BOND['gb']['10Y'] == 'GB10YT=RR'
    assert src.NAVER_BOND['kr']['3Y'] == 'KR3YT=RR'


def test_korean_curve_gains_the_tenors_ecos_never_had():
    # ECOS 는 3Y·10Y 뿐. 커브 형태를 논하려면 짧은 쪽과 긴 쪽이 있어야 한다.
    assert {'1Y', '2Y', '5Y', '20Y', '30Y'} <= set(src.NAVER_BOND['kr'])


# --- rows_at 우선순위 -------------------------------------------------------

def test_a_fresher_observation_still_wins_regardless_of_source():
    hist = {'us_fred_leg': {'2Y': [('2026-09-01', 4.39)]},
            'us_naver_leg': {'2Y': [('2026-09-02', 4.386)]}}
    groups = {'us_fred_leg': ('us_curve', 'FRED'), 'us_naver_leg': ('us_curve', 'Naver')}
    out = collect.rows_at(hist, '2026-09-02', groups=groups)
    assert out['us_curve']['2Y'] == {'level': 4.386, 'date': '2026-09-02',
                                     'source': 'Naver', 'tenor': '2Y'}


def test_on_the_same_date_the_preferred_source_wins():
    """야후와 네이버가 같은 날짜를 주는 것이 보통이다 — 그때 누가 이길지 못 박는다.

    사전 순서에 맡기면 만기마다 출처가 갈려 「전 만기 동일 기준일」이 무의미해진다.
    """
    hist = {'us_spot': {'10Y': [('2026-09-02', 4.796)]},
            'us_naver': {'10Y': [('2026-09-02', 4.794)]}}
    groups = {'us_spot': ('us_curve', 'Yahoo'), 'us_naver': ('us_curve', 'Naver')}
    out = collect.rows_at(hist, '2026-09-02', groups=groups,
                          priority={'Naver': 2, 'Yahoo': 1})
    assert out['us_curve']['10Y']['source'] == 'Naver'
    assert out['us_curve']['10Y']['level'] == 4.794


def test_priority_never_beats_a_fresher_date():
    hist = {'a': {'10Y': [('2026-09-02', 4.79)]}, 'b': {'10Y': [('2026-09-01', 4.80)]}}
    groups = {'a': ('us_curve', 'Yahoo'), 'b': ('us_curve', 'Naver')}
    out = collect.rows_at(hist, '2026-09-02', groups=groups,
                          priority={'Naver': 2, 'Yahoo': 1})
    assert out['us_curve']['10Y']['date'] == '2026-09-02'
    assert out['us_curve']['10Y']['source'] == 'Yahoo'


# --- codex 검토 반영 (2026-09-04) --------------------------------------------

def test_a_failure_on_the_first_page_reaches_the_retry_layer(monkeypatch):
    """예외를 안에서 삼키면 바깥 retry() 가 아무 일도 못 한다.

    실측: _text 가 늘 TimeoutError 를 던지게 해도 tries=3 인 retry 가 호출을
    한 번만 하고 끝났다. 첫 페이지 실패는 «못 받았다»이므로 위로 올려보낸다.
    """
    calls = []

    def boom(url, *a, **kw):
        calls.append(url)
        raise TimeoutError('네트워크')

    monkeypatch.setattr(src, '_text', boom)
    try:
        src.naver_bond_series('US10YT=RR', pages=2)
    except TimeoutError:
        pass
    else:
        raise AssertionError('첫 페이지 실패가 조용히 빈 리스트로 삼켜졌다')
    assert len(calls) == 1


def test_a_failure_on_a_later_page_keeps_what_was_already_read(monkeypatch):
    """뒤 페이지는 «더 없다»일 수 있으므로 앞에서 받은 것을 살린다."""
    payload = {'result': [{'localTradedAt': '2026-09-02T17:05:00-04:00',
                           'closePrice': '4.7940'}]}

    seen = []

    def flaky(url, *a, **kw):
        seen.append(url)
        if len(seen) == 1:
            import json as _j
            return _j.dumps(payload)
        raise TimeoutError('네트워크')

    monkeypatch.setattr(src, '_text', flaky)
    assert src.naver_bond_series('US10YT=RR', pages=3) == [('2026-09-02', 4.794)]
