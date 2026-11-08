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


def _mark_sent(st):
    W.deliver(st, lambda text: None, lambda s: None, at(11, 10, 13))


def test_resolved_before_publish_after_warning_was_sent(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    _mark_sent(st)                                                   # 미발행 경고를 실제로 보냈다
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 10, 13, 5))
    assert kinds(st)[-2:] == ['resolved', 'publish']
    assert '앞서 보낸 미발행 경고' in st['events'][-2]['text']
    assert st['sessions']['kr:2026-11-09'] == 'resolved'


def test_pending_warning_becomes_late_not_resolved(tmp_path):
    # 받은 적 없는 경고의 「해소」를 보내지 않는다
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))                # KR 경고는 아직 pending(전송 실패 중)
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 10, 13, 5))
    warn = next(e for e in st['events'] if e['kind'] == 'missing')
    assert warn['status'] == 'cancelled' and warn not in W.pending(st)
    assert 'resolved' not in kinds(st) and kinds(st)[-2:] == ['late', 'publish']
    assert '보내기 전에 해소돼 보내지 않았어요' in st['events'][-2]['text']


def test_late_publish_seen_first_after_deadline_without_warning(tmp_path):
    # 맥이 기준 시각에 못 봤고, 깨어 보니 이미 올라와 있다 — 늦었다는 것만, 경고가 있었다고 하지 않는다
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09', when='2026-11-10T15:30:00+09:00')     # 기준 11/10 12:00 뒤
    F.publish(repo, 'kr', '2026-11-09', when='2026-11-09T18:30:00+09:00')     # 기준 안
    st = run(W.new_state('x'), repo, at(11, 10, 16))
    late = [e for e in st['events'] if e['kind'] == 'late']
    assert len(late) == 1 and late[0]['key'] == 'us:2026-11-09'
    assert '커밋 시각 11/10 15:30 기준' in late[0]['text'] and '미발행 경고는 보내지 않았어요' in late[0]['text']
    assert st['sessions'] == {'us:2026-11-09': 'late', 'kr:2026-11-09': 'ok'}
    run(st, repo, at(11, 10, 16, 5))
    assert [e['kind'] for e in st['events']].count('late') == 1         # 한 번만


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
    _mark_sent(st)
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
    # 저장이 실패해 같은 회차를 다시 계산해도 같은 식별자 — 사건이 두 번 쌓이지 않고 빠지지도 않는다
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

    calls = []

    def save_fails(s):                    # 보내기 전 저장(시도 표시)은 되고, 보낸 뒤 저장이 실패한다
        calls.append(1)
        if len(calls) == 2:
            raise OSError('disk full')
        W.save_state(path, s)
    with pytest.raises(OSError):
        W.deliver(st, sent.append, save_fails, at(11, 10, 13))
    assert len(sent) == 1
    again = W.load_state(path)                                     # 디스크는 보내기 전 상태
    assert W.pending(again)[0]['id'] == W.pending(W.load_state(path))[0]['id']
    resent = []
    W.deliver(again, resent.append, lambda s: W.save_state(path, s), at(11, 10, 13, 5))
    assert resent[0] == sent[0]                                    # 중복 가능 — 상태 파일이 살아 있으면 다시 보낸다
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


def test_crash_before_save_does_not_advance_baseline(tmp_path):
    # 사건을 찾고 저장하기 전에 꺼지면 — 디스크의 기준점은 옛 것이라 다음 회차가 같은 사건을 다시 찾는다
    repo = F.init(tmp_path)
    path = str(tmp_path / 'state.json')
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    W.save_state(path, st)
    old_base = st['last_seen']
    F.publish(repo, 'us', '2026-11-09')
    lost = run(W.load_state(path), repo, at(11, 9, 8, 5))           # 저장 없이 꺼짐
    eid = next(e['id'] for e in lost['events'] if e['kind'] == 'publish')
    disk = W.load_state(path)
    assert disk['last_seen'] == old_base                              # 기준점만 앞서 가지 않았다
    again = run(disk, repo, at(11, 9, 8, 10))
    assert [e['id'] for e in W.pending(again) if e['kind'] == 'publish'] == [eid]


def test_crash_after_save_before_send_sends_next_time(tmp_path):
    repo = F.init(tmp_path)
    path = str(tmp_path / 'state.json')
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    W.save_state(path, st)                                            # 저장 뒤, 보내기 전에 꺼짐
    disk = W.load_state(path)
    run(disk, repo, at(11, 9, 8, 5))                                  # 새 사건 없음
    sent = []
    W.deliver(disk, sent.append, lambda s: W.save_state(path, s), at(11, 9, 8, 5))
    assert any(x.startswith('[발행] US 일간 11/09') for x in sent) and not W.pending(W.load_state(path))



def test_save_failure_before_send_sends_nothing(tmp_path):
    st = _st_with_events(tmp_path)
    sent = []

    def save_fails(s):
        raise OSError('disk full')
    with pytest.raises(OSError):
        W.deliver(st, sent.append, save_fails, at(11, 10, 13))
    assert sent == []                     # 시도 표시를 못 남기면 보내지 않는다


# ── codex 구현 검토 1회 반영(11/08) ─────────────────────────────────────────

def test_added_then_deleted_between_observations_is_reported(tmp_path):
    # #2 — 맥이 꺼진 사이 올라왔다 사라진 글
    repo = F.init(tmp_path)
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    F.publish(repo, 'us', '2026-11-09')
    F.git(repo, 'rm', '-q', 'posts/2026-11-09.html')
    F.commit(repo, 'rm')
    run(st, repo, at(11, 9, 9))
    gone = [e for e in st['events'] if e['kind'] == 'gone']
    assert len(gone) == 1 and '맥이 확인하기 전에 올라왔다가 지금은 없어요' in gone[0]['text']


def test_attempted_warning_is_resolved_not_cancelled(tmp_path):
    # #3 — 보내려 했던 경고는 텔레그램이 받았을 수 있다: 취소하지 않고 다시 보낸 뒤 해소
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    warn = next(e for e in st['events'] if e['kind'] == 'missing')
    warn['attempted'] = True                                         # 보낸 직후 저장 전에 꺼진 상태
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 10, 13, 5))
    assert warn['status'] == 'pending' and 'late' not in kinds(st)
    order = [(e['kind'], e['key']) for e in W.pending(st)]
    assert order.index(('missing', 'kr:2026-11-09')) < order.index(('resolved', 'kr:2026-11-09')) \
        < order.index(('publish', 'kr/posts/2026-11-09.html'))


def test_transient_read_error_does_not_freeze_unknown(tmp_path, monkeypatch):
    # #4 — 일시 읽기 오류는 대조 불가로 굳히지 않고 기준점도 옮기지 않는다
    from verification import repo_check as C
    repo = F.init(tmp_path)
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    base = st['last_seen']
    F.publish(repo, 'us', '2026-11-09', workspace=False)
    real = C._show

    def flaky(repo_, rev, path):
        if path.startswith('scripts/'):
            raise C.ReadError('fatal: unable to read')
        return real(repo_, rev, path)
    monkeypatch.setattr(C, '_show', flaky)
    run(st, repo, at(11, 9, 8, 5))
    assert st['last_seen'] == base and 'publish' not in kinds(st)
    monkeypatch.setattr(C, '_show', real)
    run(st, repo, at(11, 9, 8, 10))
    pub = next(e for e in st['events'] if e['kind'] == 'publish')
    assert '검사 코드: 일치' in pub['text'] and '발행 전 기록 일치' in pub['text']


def test_published_then_deleted_is_gone_and_back(tmp_path):
    # #5
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09', workspace=False)
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    assert st['sessions']['us:2026-11-09'] == 'ok'
    F.git(repo, 'rm', '-q', 'posts/2026-11-09.html')
    F.commit(repo, 'rm')
    run(st, repo, at(11, 10, 14))
    assert kinds(st).count('gone') == 1 and st['sessions']['us:2026-11-09'] == 'gone'
    assert any('올라갔다가 지금 없는 세션: US 일간 11/09' in x for x in W.summary_lines_from(st, at(11, 10, 14)))
    F.write(repo, 'posts/2026-11-09.html', '<p>글</p>')
    F.commit(repo, 're-add')
    run(st, repo, at(11, 10, 15))
    assert 'back' in kinds(st) and st['sessions']['us:2026-11-09'] == 'ok'


def test_valid_json_with_bad_contents_is_corrupt(tmp_path):
    # #6
    path = tmp_path / 'state.json'
    st = W.new_state('x')
    st['last_ok'] = '어제쯤'
    path.write_text(json.dumps(st))
    with pytest.raises(W.StateError):
        W.load_state(str(path))
    st['last_ok'] = None
    st['events'] = ['문자열']
    path.write_text(json.dumps(st))
    with pytest.raises(W.StateError):
        W.load_state(str(path))
    assert W.summary_lines(str(path), at(11, 10, 9)) == ['발행 알림: 상태를 못 읽었어요 — 미발행·전송 여부를 몰라요']


def test_first_run_is_baseline_only(tmp_path):
    # #8 — 늦게 설치해도 지난 글·경고가 한꺼번에 오지 않는다
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('처음 실행했어요', baseline=True), repo, at(11, 12, 13))
    assert kinds(st) == ['reset'] and '기준선으로만' in st['events'][0]['text']
    assert st['sessions']['kr:2026-11-09'] == 'missing_quiet'       # 경고 없이 — 아침 요약에 보인다
    assert any('아직 안 올라온 세션: KR 일간 11/09' in x for x in W.summary_lines_from(st, at(11, 12, 13)))
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 12, 13, 5))
    assert 'resolved' not in kinds(st) and kinds(st)[-2:] == ['late', 'publish']   # 받은 적 없는 경고의 해소 아님


def test_send_timeout_counts_as_failure(tmp_path):
    # #10
    import subprocess
    st = _st_with_events(tmp_path)

    def slow(text):
        raise subprocess.TimeoutExpired('curl', 60)
    assert W.deliver(st, slow, lambda s: None, at(11, 10, 13)) is False
    assert st['send_fail'] == 1 and W.pending(st)[0]['tries'] == 1


def test_cli_corrupt_state_is_copied_and_survives_failed_save(tmp_path, monkeypatch):
    # #9 — 손상 파일을 옮기지 않는다: 새 상태 저장이 실패해도 다음 회차가 다시 복구에 들어간다
    import verify_publish as CLI
    repo = F.init(tmp_path)
    state = tmp_path / 'st' / 'state.json'
    state.parent.mkdir()
    state.write_text('{broken')
    monkeypatch.setenv(W.STATE_ENV, str(state))
    monkeypatch.chdir(repo)

    def boom(path, st):
        raise OSError('disk full')
    monkeypatch.setattr(W, 'save_state', boom)
    with pytest.raises(OSError):
        CLI.main(['--no-fetch'])
    assert state.read_text() == '{broken'
    assert len([p for p in os.listdir(state.parent) if '.corrupt-' in p]) == 1
