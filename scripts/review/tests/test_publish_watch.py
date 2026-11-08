"""발행 건별 알림(`review.publish_watch`, CLI `scripts/verify_publish.py`) — 2단계(2026-11-08).

막는 것: 맥이 꺼진 사이 사건 유실, 조회 실패를 미발행으로, 빈 달력으로 휴일 경보, 정정마다 경보, 전송·저장 실패로
사건이 조용히 사라짐, 금요일 세션을 토요일에 안 봄.
"""
import json
import os
from datetime import datetime

import pytest

from review import digest as D
from review import publish_watch as W
from review.tests import prepub_fixture as F

KST = W.KST


def at(m, d, h, mi=0):
    return datetime(2026, m, d, h, mi, tzinfo=KST)


def kinds(st):
    return [e['kind'] for e in st['events']]


def run(st, repo, now, fetched=True):
    return W.step(st, str(repo), now, fetched, ref='HEAD')


def test_first_run_reports_publish_and_missing(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('처음 실행했어요'), repo, at(11, 10, 13))
    assert kinds(st) == ['reset', 'missing', 'publish']             # KR 11/09 은 23:00 기준을 넘겼다
    miss = next(e for e in st['events'] if e['kind'] == 'missing')
    assert 'KR 일간 11/09 세션 보고서 미발행 확인' in miss['text'] and '11/09 23:00 KST' in miss['text']
    assert '원인: 확인 불가' in miss['text'] and '보류' not in miss['text']


def test_no_change_no_new_event(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    n = len(st['events'])
    run(st, repo, at(11, 10, 13, 5))
    assert len(st['events']) == n


def test_resolved_before_publish(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 10, 13, 5))
    assert kinds(st)[-2:] == ['resolved', 'publish']
    assert st['sessions']['kr:2026-11-09'] == 'resolved'


def test_fetch_failure_is_not_missing_and_keeps_baseline(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 9))                # 아직 KR 기준 시각 전? KR 11/09 23:00 지났다
    base = st['last_seen']
    before = list(kinds(st))
    run(st, repo, at(11, 10, 10), fetched=False)
    assert kinds(st) == before and st['last_seen'] == base           # 1시간 — 아직 알리지 않는다
    run(st, repo, at(11, 10, 11, 1), fetched=False)
    assert kinds(st)[-1] == 'fetch' and '미발행 여부를 몰라요' in st['events'][-1]['text']
    run(st, repo, at(11, 10, 11, 30), fetched=False)
    assert kinds(st).count('fetch') == 1                             # 한 번만
    run(st, repo, at(11, 10, 12))
    assert kinds(st)[-1] == 'fetch_ok' and st['fetch'] == {}


def test_missed_events_recovered_after_long_sleep(tmp_path):
    # 맥이 꺼져 있던 동안의 글·세션을 기준점 커밋 이후 변화로 전부 찾는다(날짜 창이 아니다)
    repo = F.init(tmp_path)
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    for d in ('2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-16',
              '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20'):
        F.publish(repo, 'us', d)
    run(st, repo, at(11, 21, 13))
    pubs = [e['key'] for e in st['events'] if e['kind'] == 'publish']
    assert len(pubs) == 10 and pubs[0] == 'posts/2026-11-09.html'
    assert 'missing' not in [e['kind'] for e in st['events'] if e['key'].startswith('us:')]


def test_unresolved_missing_kept_beyond_any_window(tmp_path):
    repo = F.init(tmp_path)
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    assert st['sessions']['us:2026-11-09'] == 'missing'
    run(st, repo, at(12, 20, 13))                                    # 한 달 넘게 지나도
    F.publish(repo, 'us', '2026-11-09')
    run(st, repo, at(12, 20, 13, 5))
    assert any(e['kind'] == 'resolved' and e['key'] == 'us:2026-11-09' for e in st['events'])


def test_gap_when_baseline_commit_not_in_history(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    st['last_seen'] = '0' * 40
    n_pub = kinds(st).count('publish')
    run(st, repo, at(11, 10, 13, 5))
    assert kinds(st)[-1] == 'gap' or 'gap' in kinds(st)
    assert '다 봤다고 할 수 없어요' in next(e for e in st['events'] if e['kind'] == 'gap')['text']
    assert kinds(st).count('publish') == n_pub                       # 같은 글은 다시 알리지 않는다


def test_calendar_unreadable_stops_missing(tmp_path):
    repo = F.init(tmp_path)
    F.write(repo, 'data/market_holidays.json', '{broken')
    F.commit(repo, 'break cal')
    st = run(W.new_state('x'), repo, at(11, 12, 13))
    assert 'missing' not in kinds(st)
    assert set(st['calendar']) == {'us', 'kr'}
    assert any('휴장 달력' in x for x in W.summary_lines_from(st, at(11, 12, 13)))


def test_us_friday_session_checked_on_saturday(tmp_path):
    repo = F.init(tmp_path)
    for d in ('2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12'):
        F.publish(repo, 'us', d)
    for d in ('2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13'):
        F.publish(repo, 'kr', d)
    st = run(W.new_state('x'), repo, at(11, 14, 11, 59))
    assert 'us:2026-11-13' not in st['sessions']
    run(st, repo, at(11, 14, 12, 0))
    assert st['sessions'].get('us:2026-11-13') == 'missing'
    miss = [e for e in st['events'] if e['kind'] == 'missing']
    assert len(miss) == 1 and '11/14 12:00 KST' in miss[0]['text']


def test_holiday_is_not_missing(tmp_path):
    repo = F.init(tmp_path)
    st = W.new_state('x')
    days = ['2026-11-%02d' % d for d in (9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 23, 24, 25, 27)]
    for d in days:
        F.publish(repo, 'us', d)
    run(st, repo, at(11, 28, 13))
    assert 'us:2026-11-26' not in st['sessions']                    # 추수감사절(달력)


def test_dst_end_week_sessions(tmp_path):
    # 11/1 DST 끝 — 그 뒤 주에도 세션 경계가 KST 기준으로 하루 밀리지 않는다
    repo = F.init(tmp_path)
    st = run(W.new_state('x'), repo, at(11, 10, 11, 59))
    assert 'us:2026-11-09' not in st['sessions']
    run(st, repo, at(11, 10, 12, 0))
    assert st['sessions']['us:2026-11-09'] == 'missing'


def test_correction_makes_no_publish_alert(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09', body='<p>4.20%</p>')
    st = run(W.new_state('x'), repo, at(11, 10, 9))
    n = len(st['events'])
    F.write(repo, 'posts/2026-11-09.html', '<p>4.30%</p>')
    F.commit(repo, 'fix')
    run(st, repo, at(11, 10, 9, 5))
    assert len(st['events']) == n


def test_record_arriving_later_is_state_change(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09', record=False)
    st = run(W.new_state('x'), repo, at(11, 10, 9))
    assert '발행 전 기록 없음' in next(e for e in st['events'] if e['kind'] == 'publish')['text']
    F.publish(repo, 'us', '2026-11-09')                              # 기록이 뒤 커밋에
    run(st, repo, at(11, 10, 9, 5))
    assert kinds(st)[-1] == 'changed' and '[상태 바뀜]' in st['events'][-1]['text']


def test_same_events_regenerate_with_same_ids(tmp_path):
    # 저장이 실패해 같은 회차를 다시 계산해도 같은 식별자 — 사건이 두 번 쌓이지 않고, 유실도 없다
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    a = run(W.new_state('x'), repo, at(11, 10, 13))
    b = run(W.new_state('x'), repo, at(11, 10, 13))
    assert [e['id'] for e in a['events'] if e['kind'] != 'reset'] == \
        [e['id'] for e in b['events'] if e['kind'] != 'reset']


# ── 전송·저장 ──────────────────────────────────────────────────────────────

def _st_with_events(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    return run(W.new_state('x'), repo, at(11, 10, 13))


def test_send_failure_keeps_pending_and_order(tmp_path):
    st = _st_with_events(tmp_path)
    sent = []

    def bad(text):
        raise D.SendError('curl 실패(코드 28)')
    assert W.deliver(st, bad, lambda s: None, at(11, 10, 13)) is False
    first = W.pending(st)[0]
    assert first['tries'] == 1 and st['send_fail'] == 1 and len(W.pending(st)) == 3
    assert W.deliver(st, sent.append, lambda s: None, at(11, 10, 13, 5)) is True
    assert not W.pending(st) and sent[0].endswith('#' + first['id'])       # 같은 식별자로 재시도
    assert st['send_fail'] == 0


def test_save_failure_after_send_means_resend_not_loss(tmp_path):
    st = _st_with_events(tmp_path)
    path = str(tmp_path / 'state.json')
    W.save_state(path, st)
    sent = []

    def save_fails(s):
        raise OSError('disk full')
    with pytest.raises(OSError):
        W.deliver(st, sent.append, save_fails, at(11, 10, 13))
    assert len(sent) == 1
    again = W.load_state(path)                                     # 디스크는 보내기 전 상태
    assert W.pending(again)[0]['id'] == W.pending(W.load_state(path))[0]['id']
    resent = []
    W.deliver(again, resent.append, lambda s: W.save_state(path, s), at(11, 10, 13, 5))
    assert resent[0] == sent[0]                                    # 중복 가능 — 유실 없음
    assert not W.pending(W.load_state(path))


def test_corrupt_state_is_not_assumed_fine(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text('{broken')
    with pytest.raises(W.StateError):
        W.load_state(str(path))
    assert W.summary_lines(str(path), at(11, 10, 9)) == ['발행 알림: 상태를 못 읽었어요 — 미발행·전송 여부를 몰라요']


def test_summary_lines(tmp_path):
    st = _st_with_events(tmp_path)
    path = str(tmp_path / 'state.json')
    W.save_state(path, st)
    lines = W.summary_lines(path, at(11, 10, 17))
    assert any('마지막 정상 확인이 4시간 전' in x for x in lines)
    assert any('아직 안 올라온 세션: KR 일간 11/09' in x for x in lines)
    assert any('발행 알림 미전송 3건' in x for x in lines)
    assert W.summary_lines(str(tmp_path / 'none.json'), at(11, 10, 9)) == ['발행 알림: 아직 실행 기록이 없어요']


def test_separate_from_daily_digest():
    assert W.DEFAULT_STATE != D.DEFAULT_STATE and W.STATE_ENV != D.STATE_ENV
