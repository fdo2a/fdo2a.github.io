"""style_pass.judge — 원본도 같은 위반으로 실패하면 윤문 탓이 아니다(2026-10-13 codex 4차 #3)."""
from review.style_pass import judge


def test_volume_and_warning_lines_do_not_make_the_same_failure_new():
    base = {'check_weight.py': (1, '분량: 본문 9032자 · 뉴스 요약 0자 · 전체 9032자 (공백 제외)\n'
                                   '경고: 서술형 본문이 9032자다\n매크로가 3770자로 축약일 상한 2400자를 넘는다')}
    after = {'check_weight.py': (1, '분량: 본문 9034자 · 뉴스 요약 0자 · 전체 9034자 (공백 제외)\n'
                                    '경고: 서술형 본문이 9034자다\n매크로가 3770자로 축약일 상한 2400자를 넘는다')}
    assert judge(base, after) == []


def test_a_new_violation_line_is_still_a_new_failure():
    base = {'check_weight.py': (1, '분량: 본문 9032자\n매크로가 3770자로 축약일 상한 2400자를 넘는다')}
    after = {'check_weight.py': (1, '분량: 본문 9032자\n매크로가 3770자로 축약일 상한 2400자를 넘는다\n'
                                    '§2: data-lede="action" 문단이 없다')}
    assert judge(base, after)
