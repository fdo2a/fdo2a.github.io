"""주간 스냅샷을 그대로 써도 되는가 — 루틴은 금융 호스트에 못 닿으므로(2026-10-02 실측) 이 판정이
「Actions 수집을 다시 띄울지」를 정한다. 틀리는 방향: 낡은 스냅샷을 READY 로 보면 금요일이 빠진
주간이 나가고, 멀쩡한 것을 STALE 로 보면 수집을 한 번 더 띄울 뿐이다."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'snapshot_ready', os.path.join(HERE, '..', '..', 'ci', 'snapshot_ready.py'))
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


def snap(generated='2026-10-04T08:10:00+09:00', jgb_last='2026-10-02', nikkei_last='2026-10-02',
         status=None, key='2026-W40', end='2026-10-02'):
    st = {'price:^GSPC': 'ok', 'fred:DGS10': 'ok', 'mof:week': 'ok', 'price:^N225': 'ok',
          'cftc:097741': 'ok', 'jgb:curve': 'ok'}
    st.update(status or {})
    return {'key': key, 'end_date': end, 'generated': generated, 'fetch_status': st,
            'jgb': [{'date': '2026-09-24', '10Y': 1.8}, {'date': jgb_last, '10Y': 1.81}],
            'prices': {'Nikkei 225': {'daily': [['2026-09-24', 1.0], [nikkei_last, 1.0]]}}}


def test_matching_complete_snapshot_is_ready_for_both():
    assert sr.verdict('us', snap(), '2026-W40', '2026-10-02')[0] == 'READY'
    assert sr.verdict('japan', snap(), '2026-W40', '2026-10-02')[0] == 'READY'


def test_missing_snapshot_is_stale():
    assert sr.verdict('us', None, '2026-W40', '2026-10-02')[0] == 'STALE'


def test_other_week_or_end_is_stale():
    assert sr.verdict('us', snap(key='2026-W39'), '2026-W40', '2026-10-02')[0] == 'STALE'
    assert sr.verdict('us', snap(end='2026-10-01'), '2026-W40', '2026-10-02')[0] == 'STALE'


def test_us_needs_every_source_because_its_diag_gates_on_all_failures():
    """US 진단은 실패 소스를 전부 게이트로 넘긴다 — 재무성 실패도 US 발행을 막는다(구현 검토 #2)."""
    assert sr.verdict('us', snap(status={'mof:week': 'HTTP 503'}), '2026-W40', '2026-10-02')[0] == 'STALE'
    assert sr.verdict('us', snap(status={'price:^GSPC': 'empty'}), '2026-W40', '2026-10-02')[0] == 'STALE'


def test_japan_ignores_us_only_failures_but_not_its_own():
    s = snap(status={'price:^GSPC': 'empty'})
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02')[0] == 'READY'
    s = snap(status={'cftc:097741': 'timeout'})
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02')[0] == 'STALE'


def test_saturday_snapshot_without_tokyo_friday_is_stale_for_japan():
    """2026-09-26 실측: 토요일 새벽 스냅샷은 JGB 금요일분이 비어 있었다."""
    s = snap(generated='2026-10-03T12:05:00+09:00', jgb_last='2026-10-01')
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02')[0] == 'STALE'
    assert sr.verdict('us', s, '2026-W40', '2026-10-02')[0] == 'READY'


def test_jgb_still_on_thursday_is_stale_because_mof_posts_friday_on_the_next_business_day():
    """MOF 커브는 다음 도쿄 영업일에 올라온다(2026-10-04 실측: 토 15시~일 22시 스냅샷 6개가 전부
    목요일에서 끝났다). 그래서 일본 주간은 그 게시일에 발행한다 — 판정은 금요일분을 그대로 요구한다."""
    s = snap(generated='2026-10-04T22:09:00+09:00', jgb_last='2026-10-01', nikkei_last='2026-10-02')
    v, why = sr.verdict('japan', s, '2026-W40', '2026-10-02', jp_holidays=())
    assert v == 'STALE' and 'JGB' in why


def test_sunday_snapshot_still_missing_friday_is_stale_unless_the_calendar_says_holiday():
    """일요일에 받았다는 사실만으로 금요일 누락을 휴장으로 보지 않는다(구현 검토 #3)."""
    s = snap(generated='2026-10-04T08:10:00+09:00', jgb_last='2026-10-01', nikkei_last='2026-10-01')
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02', jp_holidays=())[0] == 'STALE'
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02', jp_holidays=('2026-10-02',))[0] == 'READY'


def test_observations_after_the_end_date_do_not_hide_a_missing_friday():
    s = snap(jgb_last='2026-10-05')     # 다음 주 월요일 행만 있고 금요일은 없다
    s['jgb'] = [{'date': '2026-10-01', '10Y': 1.8}, {'date': '2026-10-05', '10Y': 1.82}]
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02', jp_holidays=())[0] == 'STALE'


def test_last_tokyo_day_walks_back_over_jpx_holidays():
    assert sr.last_tokyo_day('2026-09-23', ('2026-09-21', '2026-09-22', '2026-09-23')).isoformat() == '2026-09-18'
