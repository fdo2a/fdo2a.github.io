"""발행 전 기록 읽기(`review.prepub_view`) — 2단계(2026-11-08).

막는 거짓말: 정정된 글에 거짓 불일치, 짝이 맞으니 「검증 완료」, 미실행·일부 검사 숨기기, 조회 실패를 「기록 없음」으로.
"""
import json

import pytest

from review import prepub_view as V
from review.tests import prepub_fixture as F
from verification import repo_check as C

HTML = '<html><head><style>p{color:red}</style></head><body><p>미 10년물 4.20%</p></body></html>'


def test_target_of_only_daily_after_effective():
    assert V.target_of('posts/2026-11-09.html') == ('us', '2026-11-09')
    assert V.target_of('kr/posts/2026-11-10.html') == ('kr', '2026-11-10')
    assert V.target_of('posts/2026-11-06.html') is None          # 기록 도입 전
    assert V.target_of('news/2026-11-09.html') is None
    assert V.target_of('weekly/2026-W46.html') is None


def test_normal_publish_separates_pair_and_recorded(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, body=HTML, numbers={'table_cells': 40, 'prose_judged': 12, 'unverified': 30})
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['kind'] == V.OK and v['same_commit']
    text = V.render_publish(v)
    assert '[맥이 직접 확인]' in text and '[루틴이 남긴 검사 결과]' in text
    assert '작업 공간 전용 입력: 대조 불가 1개' in text
    assert '확인 완료' not in text and '발행 전 기록 일치' not in text      # 대조 불가가 있으면
    assert '미검증 30' in text and '루틴 파이썬 3.11.9' in text


def test_not_run_and_partial_are_not_verified(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False, summ=F.summary(verified=False, not_run=['g1']),
              gate_status={'g1': 'not_run', 'check_numbers': 'partial'})
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert V.headline(v) == '발행 전 기록 일치'                    # 짝은 맞다
    text = V.render_publish(v)
    assert '검증 완료 아님' in text and '실행 안 함: g1' in text and '일부만 검사: check_numbers' in text


def _fake_typography(monkeypatch):
    # 조판 판정 자체는 review.prose 의 시험 몫 — 여기서는 판정 결과를 세는 쪽만 본다
    from review import prose

    def fake(path, old, new, root=None):
        if 'TYPESET' in new and old.replace('TYPESET', '') == new.replace('TYPESET', ''):
            return True
        if 'UNKNOWN' in new:
            return None
        return False
    monkeypatch.setattr(prose, 'typography', fake)


def test_correction_does_not_raise_false_mismatch(tmp_path, monkeypatch):
    _fake_typography(monkeypatch)
    repo = F.init(tmp_path)
    F.publish(repo, body=HTML, workspace=False)
    v0 = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    F.write(repo, 'posts/2026-11-09.html', HTML.replace('4.20%', '4.30%'))     # 발행 뒤 사실 정정
    F.commit(repo, 'fix')
    v1 = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v1['check']['overall'] == C.MATCH                       # 기록 커밋 기준이라 불일치가 아니다
    assert V.fingerprint(v0) == V.fingerprint(v1)                   # 정정은 발행 건별 알림을 만들지 않는다
    assert v1['corrections'] == {'typeset': 0, 'other': 1, 'unknown': 0}
    assert '조판 외 변경 1회' in V.render_publish(v1)


def test_correction_counts_each_version(tmp_path, monkeypatch):
    _fake_typography(monkeypatch)
    repo = F.init(tmp_path)
    F.publish(repo, body=HTML, workspace=False)
    F.write(repo, 'posts/2026-11-09.html', HTML + 'TYPESET')
    F.commit(repo, 'typeset')
    F.write(repo, 'posts/2026-11-09.html', HTML + 'TYPESET UNKNOWN')
    F.commit(repo, 'odd')
    F.write(repo, 'data/market_data.json', '{"a": 3}')               # 글을 안 건드린 커밋은 세지 않는다
    F.commit(repo, 'data')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['corrections'] == {'typeset': 1, 'other': 0, 'unknown': 1}
    assert v['check']['overall'] == C.MATCH


def test_real_typography_on_hand_css_is_not_typeset(tmp_path):
    # 실제 판정: 등록된 조판 블록 교체가 아닌 손 CSS 변경은 조판으로 받지 않는다(세면 「조판 외」나 「판정 불가」)
    repo = F.init(tmp_path)
    F.publish(repo, body=HTML, workspace=False)
    F.write(repo, 'posts/2026-11-09.html', HTML.replace('color:red', 'color:blue'))
    F.commit(repo, 'css')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['corrections']['typeset'] == 0 and v['corrections']['other'] + v['corrections']['unknown'] == 1


def test_no_record(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, record=False)
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['kind'] == V.NO_RECORD and '발행 전 기록 없음' in V.render_publish(v)


def test_readded_post_is_ambiguous(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.git(repo, 'rm', '-q', 'posts/2026-11-09.html')
    F.commit(repo, 'rm')
    F.write(repo, 'posts/2026-11-09.html', '<p>다시</p>')
    F.commit(repo, 're-add')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['kind'] == V.AMBIGUOUS and '판정 불가' in V.headline(v)


def test_record_in_later_commit_is_noted(tmp_path):
    repo = F.init(tmp_path)
    F.write(repo, 'posts/2026-11-09.html', HTML)
    F.commit(repo, 'post only')
    F.publish(repo, body=HTML, workspace=False)                     # 기록은 다음 커밋에
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['kind'] == V.OK and v['same_commit'] is False
    assert '뒤 커밋에 들어 있어요' in V.render_publish(v)


def test_unreadable_summary_is_not_pass(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rec = json.load(open(repo / 'verification/us/2026-11-09.json'))
    del rec['summary']['verified']
    F.git(repo, 'rm', '-q', '--cached', 'verification/us/2026-11-09.json')
    # 같은 커밋 안에서 고쳐 쓴 기록을 흉내 — amend
    F.write(repo, 'verification/us/2026-11-09.json', json.dumps(rec))
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    text = V.render_publish(v)
    assert '요약을 읽지 못했어요' in text and '판정 통과' not in text


def test_git_failure_is_raised_not_no_record(tmp_path):
    repo = F.init(tmp_path)
    with pytest.raises(V.GitError):
        V.view(str(repo), 'no-such-ref', 'us', '2026-11-09')


def test_digest_lines_short(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False, summ=F.summary(verified=False), gate_status={'g1': 'not_run'})
    lines = V.digest_lines(V.view(str(repo), 'HEAD', 'us', '2026-11-09'))
    assert lines[0].startswith(' · [발행 전 기록]') and '완료 아님' in lines[1] and 'g1' in lines[1]


def test_every_summary_status_has_a_label():
    # 기록이 내는 판정 이름이 모두 번역된다 — 새 이름이 생기면 여기서 걸린다
    import inspect
    import re
    from verification import record as R
    src = inspect.getsource(R.summarize)
    names = set(re.findall(r"status = '([a-z_]+)'", src))
    assert names and names <= set(V.STATUS), names - set(V.STATUS)


def test_gate_without_script_hash_is_unknown(tmp_path):
    # codex 구현 검토 #7 — 해시가 빠진 파일 검사를 건너뛰면 「일치」로 보인다
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rec = json.load(open(repo / 'verification/us/2026-11-09.json'))
    rec['gates'][0]['script_sha256'] = None
    F.write(repo, 'verification/us/2026-11-09.json', json.dumps(rec))
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['check']['cats']['scripts'] == C.UNKNOWN and V.headline(v) != '발행 전 기록 일치'


def test_string_false_is_not_verified(tmp_path):
    rec = {'summary': F.summary(verified='false', publish_ok='true'), 'gates': [{'name': 'g1', 'status': 'pass'}]}
    assert V.recorded(rec) == {'readable': False}


def test_file_gate_without_argv_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    rec = json.load(open(repo / 'verification/us/2026-11-09.json'))
    rec['gates'][0]['argv'] = []
    F.write(repo, 'verification/us/2026-11-09.json', json.dumps(rec))
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['check']['cats']['scripts'] == C.UNKNOWN


def test_missing_summary_lists_are_unreadable():
    s = F.summary()
    del s['blocking']
    assert V.recorded({'summary': s, 'gates': [{'name': 'g1', 'status': 'pass'}]}) == {'readable': False}
