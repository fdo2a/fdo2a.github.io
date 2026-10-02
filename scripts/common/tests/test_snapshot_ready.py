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


def test_us_ignores_japan_only_failures_but_not_its_own():
    assert sr.verdict('us', snap(status={'mof:week': 'HTTP 503'}), 'W', 'E')[0] == 'STALE'  # key mismatch
    s = snap(status={'mof:week': 'HTTP 503'})
    assert sr.verdict('us', s, '2026-W40', '2026-10-02')[0] == 'READY'
    s = snap(status={'price:^GSPC': 'empty'})
    assert sr.verdict('us', s, '2026-W40', '2026-10-02')[0] == 'STALE'


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


def test_sunday_snapshot_tolerates_a_tokyo_friday_holiday():
    """일요일에 받았는데도 금요일이 없으면 도쿄 휴장으로 본다 — 사흘까지."""
    s = snap(generated='2026-10-04T08:10:00+09:00', jgb_last='2026-10-01', nikkei_last='2026-10-01')
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02')[0] == 'READY'
    s = snap(generated='2026-10-04T08:10:00+09:00', jgb_last='2026-09-28')
    assert sr.verdict('japan', s, '2026-W40', '2026-10-02')[0] == 'STALE'
