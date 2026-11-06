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


def test_numbers_exit2_is_not_tolerated_even_if_original_was_2():
    from scripts.review import style_pass as sp
    base = {'check_numbers.py': (2, 'FATAL: x')}
    assert sp.judge(base, {'check_numbers.py': (2, 'FATAL: x')})


def test_numbers_warning_and_summary_lines_do_not_count_as_new():
    from scripts.review import style_pass as sp
    base = {'check_numbers.py': (1, '[채권] 2Y — 데이터 4.477\nnumber audit: 수치 700')}
    after = {'check_numbers.py': (1, '경고(문장): 새 경고\n[채권] 2Y — 데이터 4.477\nnumber audit: 수치 702')}
    assert sp.judge(base, after) == []


def test_numbers_timeout_is_not_tolerated():
    from scripts.review import style_pass as sp
    assert sp.judge({'check_numbers.py': (124, '180초 초과')}, {'check_numbers.py': (124, '180초 초과')})
