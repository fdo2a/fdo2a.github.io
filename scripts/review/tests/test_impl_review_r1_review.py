"""1a 구현 검토 1회차(2026-11-17) — 발행 뒤 재검사(#9)와 알림(#2·#11).

#9: 정정기·윤문기는 원본도 같은 종료 코드면 「기존 실패」로 허용한다. 새 글(1a 적용일 `STRICT_FROM` 이후)의
exit 2(미완료)는 통과가 아니다 — 원본에서 2 여도 허용하지 않는다. 옛 글은 지금처럼 허용한다(그때는 0 이던
경우가 많다). 적용일 상수는 레포 밖 사본에서도 도는 두 모듈에 사본으로 있다 — 시험이 같게 묶는다.
"""
import json

import pytest

from scripts.review.corrector import correct_one
from scripts.review.tests.test_corrector import _counting, gate, git, setup  # noqa: F401 — fixture


def test_strict_from_copies_are_equal():
    from scripts.review import corrector
    from review import style_pass
    from verification import inputs as I
    # 사본은 켜는 날과 같다(이 모듈은 conftest 가 켠 상태 — 꺼진 상태의 묶음은 test_switch_off.py)
    assert corrector.STRICT_FROM == style_pass.STRICT_FROM == I.strict_from()


def test_corrector_does_not_tolerate_exit2_on_new_posts(setup, monkeypatch):
    from scripts.review import corrector
    root, remote, item, exe = setup                                            # 글 날짜 2026-09-10
    gate(root, 'scripts/check_weight.py', "import sys\nprint('FATAL: 입력 없음', file=sys.stderr)\nraise SystemExit(2)\n")
    _counting(exe)
    base = git(root, 'rev-parse', 'HEAD')
    from verification import inputs as I
    monkeypatch.setattr(corrector, 'STRICT_FROM', '2026-09-01')               # 이 글을 「새 글」로
    monkeypatch.setenv(I.TEST_ENV, '2026-09-01')                              # 판정은 inputs 한 곳(2회차 F5)
    _, error = correct_one(root, item, 'wrong value', base, 10)
    assert error and 'check_weight.py' in error and 'incomplete' in error     # 재현: 전에는 기존 실패로 허용
    assert git(remote, 'show', 'main:' + item.path) == '<p>old 1</p>'


def test_corrector_still_tolerates_exit2_on_old_posts(setup):
    root, remote, item, exe = setup
    gate(root, 'scripts/check_weight.py', "raise SystemExit(2)\n")
    _counting(exe)
    base = git(root, 'rev-parse', 'HEAD')
    result, error = correct_one(root, item, 'wrong value', base, 10)
    assert error is None, error
    assert 'pre-existing' in result


def test_style_pass_judge_strict_for_new_posts():
    from review import style_pass as sp
    same = (2, 'FATAL: 입력 없음')
    assert sp.judge({'check_weight.py': same}, {'check_weight.py': same}) == []           # 옛 글
    assert sp.judge({'check_weight.py': same}, {'check_weight.py': same}, strict=True)    # 새 글 — 거부
    one = (1, '위반')
    assert sp.judge({'check_weight.py': one}, {'check_weight.py': one}, strict=True) == []
    assert sp.strict_for('posts/2026-11-17.html') is True
    assert sp.strict_for('posts/2026-09-21.html') is False
    assert sp.strict_for('weekly/2026-W46.html') is False


# ── #11·#2 알림 ──────────────────────────────────────────────────────────

from review import prepub_view as V  # noqa: E402
from review.tests import prepub_fixture as F  # noqa: E402


def test_v2_counts_pass_and_na_separately(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False, summ=F.summary(status='verified', na=['check_numbers']),
              gate_status={'g1': 'pass', 'check_numbers': 'na'})
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    text = V.render_publish(v, who=V.GITHUB)
    rec = v['recorded']
    assert rec['required'] == 2
    assert f'필수 검사 {rec["required"]}개 중 통과 1 · 해당 없음 1' in text                 # 재현: 「1/2 통과」였다
    assert '1/2 통과' not in text


def test_unconfirmed_empty_reaches_the_alert(tmp_path):
    repo = F.init(tmp_path)
    inputs = {'blocking': [], 'blocking_files': [], 'unclassified': [], 'warnings': ['<datadir>/fed/events.json'],
              'unconfirmed_empty': ['연준 사건 책(fed/events.json) — 대상 없음이 확인되지 않음(적용일 전)']}
    F.publish(repo, workspace=False, summ=F.summary(status='conditional', inputs=inputs,
                                                    conditions=[{'kind': 'unconfirmed_empty',
                                                                 'file': '<datadir>/fed/events.json'}]))
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    text = V.render_publish(v, who=V.GITHUB)
    assert ' · 대상 없음 미확인: 연준 사건 책(fed/events.json) — 대상 없음이 확인되지 않음(적용일 전)' in text
    assert '대상 없음 미확인 1개' in '\n'.join(V.digest_lines(v))
