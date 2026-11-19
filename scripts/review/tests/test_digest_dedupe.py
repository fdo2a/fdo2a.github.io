"""아침 요약에서 겹치는 줄 빼기(2026-11-19 사용자 「겹치는 것만 빼자」).

빼는 것: 발행 건별 알림에 이미 실린 발행 전 기록 내역, 글 머리(「검토 대기」·「사람이 읽어야 함」)를 되풀이하는 검토 줄,
맺음말과 같은 「자동 숫자 검사 없음」 줄. 남기는 것: 발행 뒤에 생긴 정보(codex 검토 결과·발행 뒤 수정·숫자 재검사 결과),
즉시 확인이 필요한 이상, 기록을 못 읽었다는 줄.
바뀜 판정과 저장은 그대로(block) — 표시만 줄여서 90일치 글이 「바뀐 상태」로 다시 오지 않게 한다.
"""
from datetime import datetime, timedelta, timezone

from review import digest as D
from review.tests.test_digest import COUNTS, post, seen_line
from review.tests.test_prepub_view_kr_numbers import NUMBERS, kr_numbers_repo  # noqa: F401 — pytest fixture

KST = timezone(timedelta(hours=9))


def at(y, m, d, h=9):
    return datetime(y, m, d, h, 5, tzinfo=KST)


def _prepub(tmp_path, market='kr', date='2026-11-09', **kw):
    from review import prepub_view as V
    from review.tests import prepub_fixture as F
    repo = F.init(tmp_path)
    F.publish(repo, market, date, workspace=False, **kw)
    return V.view(str(repo), 'HEAD', market, date)


def _p(path, **kw):
    p = {'path': path, 'sha': 's', 'state': '완료', 'findings': 0, 'number': None, 'auto': True, 'draft': False}
    p.update(kw)
    return p


def test_waiting_post_is_one_line():
    text = D.show(post('japan/daily/2026-11-18.html', state='대기', findings=None))
    assert text == '■ 일본 일간 11/18 — 검토 대기'


def test_news_post_does_not_repeat_its_head():
    text = D.show(post('kr/news/2026-11-18.html', state='대기', findings=None))
    assert text == '■ KR 뉴스 11/18 — 사람이 읽어야 함'


def test_review_result_stays():
    text = D.show(post('kr/posts/2026-11-06.html', state='완료', findings=4))
    assert ' · codex 검토: 끝 · 지적 4건(검토 기록 기준)' in text and '자동 검사 없음' not in text


def test_states_that_add_information_stay():
    assert 'codex 검토: 검토 진행 중' in D.show(dict(post(state='대기', findings=None), draft=True))
    assert '기한 지남' in D.show(post(state='만료', findings=None))
    assert '판정 불가 — 사람이 확인해야 해요' in D.show(post(state='판정 불가', findings=None))


def test_real_recheck_result_stays():
    num = {'kind': 'warn', 'warnings': 2, 'violations': 0, 'counts': COUNTS}
    text = D.show(post(number=num))
    assert '숫자(발행 뒤 재검사)' in text and '경고 2' in text


def test_prepub_detail_is_dropped_but_corrections_stay(tmp_path):
    v = _prepub(tmp_path)
    v['corrections'] = {'typeset': 0, 'other': 2, 'unknown': 0}
    text = D.show(_p('kr/posts/2026-11-09.html', prepub=v, findings=1))
    assert '판정 통과' not in text and '설정된 검사 완료' not in text and '자동 재검사 없음' not in text
    assert text.count('[발행 전 기록]') == 1                      # 남는 것은 표 숫자 대조가 없었다는 한 줄뿐(d2 #2)
    assert '조판 외' in text and '2회' in text                    # 발행 뒤에 생긴 정보 — 발행 알림에는 없다
    assert ' · codex 검토: 끝 · 지적 1건' in text


def test_prepub_anomaly_stays(tmp_path):
    from review.tests import prepub_fixture as F
    v = _prepub(tmp_path, summ=F.summary(publish_ok=False, status='fail', verified=False, blocking=['g1']),
                gate_status={'g1': 'fail'})
    text = D.show(_p('kr/posts/2026-11-09.html', prepub=v))
    assert '[발행 전 기록] 즉시 확인: ' in text and '기록이 발행 불가라고 함' in text


def test_prepub_unread_stays():
    text = D.show(_p('kr/posts/2026-11-09.html', prepub={'error': 'read'}))
    assert '[발행 전 기록] 읽지 못했어요(git 이나 기록 파일을 읽지 못했어요)' in text


def test_show_is_used_for_sending_and_block_for_memory():
    a = post('kr/posts/2026-11-06.html', state='대기', findings=None)
    text, lines = D.render([a], {}, at(2026, 11, 9))
    assert '■ KR 일간 11/06 — 검토 대기' in text and '자동 검사 없음' not in text
    assert lines[a['path']]['text'] == D.block(a)                     # 기억하는 문장은 옛 판 그대로


def test_unchanged_status_is_not_relisted_after_the_display_change():
    # 어제 옛 표시로 보낸 글 — 상태가 그대로면 표시만 줄었다고 다시 보내지 않는다
    a = post('kr/posts/2026-11-06.html', state='완료', findings=3)
    text, _ = D.render([a], {a['path']: seen_line(a)}, at(2026, 11, 9))
    assert '■ KR 일간 11/06' not in text and '새로 나온 글이나 바뀐 상태가 없어요.' in text


def test_caveat_claims_only_the_post_publish_recheck():
    # 발행 전 검사는 글마다 다르다(KR 표 대조는 도입 전 글에 없고, 일본 주간은 발행 게이트가 수치를 본다 — d2 #2·#3)
    assert D.CAVEAT.startswith('※ 발행 뒤 숫자 재검사는 US 일간만 해요')
    assert '발행 전에 표만 대조' not in D.CAVEAT and '자동 숫자 검사 없음' not in D.CAVEAT


def test_kr_record_without_table_numbers_says_so(tmp_path):
    # 표 숫자 검사 도입 전 기록 — 검사는 「완료」라 다른 줄이 없고, 기준선으로 넘어간 글은 발행 알림도 없었다(d2 #2)
    v = _prepub(tmp_path)
    assert v['recorded']['verified'] and not v['recorded'].get('numbers')
    text = D.show(_p('kr/posts/2026-11-09.html', prepub=v))
    assert ' · [발행 전 기록] 표 숫자 대조 없음(도입 전)' in text.split('\n')


def _kr(repo, **kw):
    from review import prepub_view as V
    from review.tests import prepub_fixture as F
    F.publish(repo, 'kr', '2026-11-16', **kw)
    return V.view(str(repo), 'HEAD', 'kr', '2026-11-16')


def test_kr_record_with_table_numbers_has_no_such_line(kr_numbers_repo):
    v = _kr(kr_numbers_repo, numbers=NUMBERS)
    assert v['recorded'].get('numbers')
    assert '[발행 전 기록]' not in D.show(_p('kr/posts/2026-11-16.html', prepub=v))


def test_kr_numbers_indeterminate_or_lost_says_why(kr_numbers_repo):
    v = _kr(kr_numbers_repo, gate_status={'check_numbers': 'pass'})          # 돌았는데 결과가 빠졌다
    assert ' · [발행 전 기록] 표 숫자 대조 없음(기록 손상)' in D.show(_p('kr/posts/2026-11-16.html', prepub=v))


def test_us_record_without_numbers_says_so_too(tmp_path):
    v = _prepub(tmp_path, market='us')
    assert not v['recorded'].get('numbers')
    text = D.show(_p('posts/2026-11-09.html', prepub=v))
    assert ' · [발행 전 기록] 숫자 자동 대조 없음' in text.split('\n') and '표 숫자' not in text


def test_new_lines_go_out_whole_and_the_post_is_remembered(tmp_path, monkeypatch):
    # 보내는 길 전체(render) — 새 줄이 가려지거나 잘리면 그 글은 「보냄」으로 기억되지 않아 매일 다시 온다
    from review import prepub_view as V
    v = _prepub(tmp_path)
    v['corrections'] = {'typeset': 0, 'other': 2, 'unknown': 0}
    monkeypatch.setattr(V, 'correction_line', lambda v: [
        ' · 발행 뒤 수정 2회(조판 0회 · 조판 외 2회 · 판별 못 함 0회) — 위 검사는 기록을 처음 담은 판 기준, '
        '수정된 판은 발행 뒤 검토가 따로 봐요(숫자 재검사는 US 일간만)'])
    a = _p('kr/posts/2026-11-09.html', prepub=v)
    text, lines = D.render([a], {}, at(2026, 11, 10))
    assert ' · [발행 전 기록] 표 숫자 대조 없음(도입 전)' in text.split('\n')
    assert '발행 전 검사 기록은 처음 기록을 담은 판 기준' in text and D.REDACTED not in text
    assert lines[a['path']]['text'] == D.block(a) and D.CAVEAT in text
    again, _ = D.render([a], lines, at(2026, 11, 11))
    assert '■ KR 일간 11/09' not in again                          # 기억했으니 다음 날 다시 오지 않는다


def test_kr_numbers_not_run_always_says_no_numbers(kr_numbers_repo):
    # 겹침을 따져 줄을 빼지 않는다 — 한 줄 겹치는 쪽을 택했다(codex d3: 이름이 가려지면 겹침 판단이 틀렸다)
    from review.tests import prepub_fixture as F
    v = _kr(kr_numbers_repo, summ=F.summary(verified=False, not_run=['check_numbers']),
            gate_status={'check_numbers': 'not_run'})
    text = D.show(_p('kr/posts/2026-11-16.html', prepub=v))
    assert '설정된 검사 완료 아님 — 실행 안 함·일부만' in text and '표 숫자 대조 없음(' in text


def test_masked_checker_name_keeps_the_no_numbers_line(kr_numbers_repo, monkeypatch):
    # 설정을 못 읽어 이름이 「이름 모를 검사기」로 가려져도 숫자 대조 없음 줄은 남는다 — 보내는 경로(render)까지(codex d3)
    from review import prepub_view as V
    from review.tests import prepub_fixture as F
    v = _kr(kr_numbers_repo, summ=F.summary(verified=False, not_run=['check_numbers']),
            gate_status={'check_numbers': 'not_run'})
    monkeypatch.setattr(V, '_disp', lambda name, rec: '이름 모를 검사기')
    a = _p('kr/posts/2026-11-16.html', prepub=v)
    assert '표 숫자 대조 없음(' in D.show(a)
    text, _ = D.render([a], {}, at(2026, 11, 17))
    assert '표 숫자 대조 없음(' in text and '이름 모를 검사기' in text


def test_correction_line_stands_alone_with_either_wording(tmp_path, monkeypatch):
    # 요약에는 수정 줄만 온다 — 「위 검사」가 가리킬 줄이 없다(d2 #4). 다른 가지의 문장이 합쳐져도 스스로 읽히게
    from review import prepub_view as V
    v = _prepub(tmp_path, market='us')
    v['corrections'] = {'typeset': 0, 'other': 2, 'unknown': 0}
    now = D.show(_p('posts/2026-11-09.html', prepub=v))
    # 병합 전 문구(「발행 전 기록은 이전 판 기준」)든 병합 뒤 문구를 고쳐 쓴 것이든 스스로 읽혀야 한다
    assert '위 검사' not in now and ('발행 전 기록은 이전 판 기준' in now or '발행 전 검사 기록은 처음 기록을 담은 판 기준' in now)
    monkeypatch.setattr(V, 'correction_line', lambda v: [
        ' · 발행 뒤 수정 2회(조판 0회 · 조판 외 2회 · 판별 못 함 0회) — 위 검사는 기록을 처음 담은 판 기준, '
        '수정된 판은 발행 뒤 검토가 따로 봐요(숫자 재검사는 US 일간만)'])
    merged = D.show(_p('posts/2026-11-09.html', prepub=v))
    assert '위 검사' not in merged
    assert ' · 발행 뒤 수정 2회(조판 0회 · 조판 외 2회 · 판별 못 함 0회) — 발행 전 검사 기록은 처음 기록을 담은 판 기준, ' in merged


def test_review_state_stays_when_the_head_says_something_else():
    # 숫자 경고로 머리가 「확인 필요」면 검토 상태는 검토 줄에만 있다(codex d1 #2)
    num = {'kind': 'warn', 'warnings': 1, 'violations': 0, 'counts': COUNTS}
    a = D.show(post(state='대기', findings=None, number=num))
    b = D.show(post(state='읽지 않음', findings=None, number=num))
    assert a.startswith('■ US 일간 11/06 — 확인 필요') and 'codex 검토: 대기' in a
    assert 'codex 검토: 범위에만 넣고 읽지 않음' in b and a != b


def test_unfinished_checks_stay_in_the_summary(tmp_path):
    # 발행 알림이 기준선으로 조용히 넘어갔거나 못 갔으면 여기서만 보인다(codex d1 #1 부분 채택)
    from review.tests import prepub_fixture as F
    v = _prepub(tmp_path, market='us', summ=F.summary(verified=False, not_run=['g1']),
                gate_status={'g1': 'not_run', 'check_numbers': 'partial'}, date='2026-11-09')
    text = D.show(_p('posts/2026-11-09.html', prepub=v))
    assert ' · [발행 전 기록] 설정된 검사 완료 아님 — 실행 안 함·일부만 g1, check_numbers' in text
