"""1a 구현 검토 2회차 F5 — 재검사가 옛 판정을 줄지는 글 파일 이름의 날짜 하나로, 세 곳이 같은 함수로 정한다.

전에는 `inputs.legacy_recheck` 가 이름의 **첫** 날짜, 정정기가 **끝** 날짜, 윤문기가 정규 경로만 봤다 —
`2026-11-16-2026-11-17.html` 은 검사기에서 옛 판정(11/16)을 받았다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from review import corrector, style_pass  # noqa: E402
from verification import inputs as I  # noqa: E402

OLD, NEW = '2026-11-16', I.STRICT_FROM
# (경로, 옛 판정을 받는가)
TABLE = [
    (f'posts/{OLD}.html', True), (f'kr/posts/{OLD}.html', True), (f'/abs/clone/posts/{OLD}.html', True),
    (f'posts/{NEW}.html', False), (f'kr/posts/{NEW}.html', False), ('posts/2026-12-01.html', False),
    (f'posts/{OLD}-{NEW}.html', False),                 # codex 재현 — 첫 날짜를 읽으면 옛 판정
    (f'posts/{NEW}-{OLD}.html', False),                 # 끝 날짜를 읽으면 옛 판정
    (f'posts/x{OLD}.html', False), (f'posts/{OLD}.html.bak', False), (f'posts/{OLD}.htm', False),
    (f'posts/draft-{OLD}.html', False), ('posts/draft.html', False), ('posts/2026-13-45.html', False),
    (f'posts/{OLD}/index.html', False), ('', False), (None, False),
]


@pytest.mark.parametrize('path,legacy', TABLE)
def test_f5_one_rule_three_callers(path, legacy):
    assert I.legacy_post(path) is legacy
    assert I.legacy_recheck(True, path) is legacy and I.legacy_recheck(False, path) is False
    assert corrector.legacy_post(path) is legacy
    assert style_pass.legacy_post(path) is legacy
    # 가져오기가 안 되는 격리 실행을 위한 사본도 같은 답이어야 한다
    assert corrector._legacy_post_copy(path) is legacy
    assert style_pass._legacy_post_copy(path) is legacy


def test_f5_post_date_is_full_basename_match():
    assert I.post_date(f'kr/posts/{OLD}.html') == OLD
    assert I.post_date(f'posts/{OLD}-{NEW}.html') is None
    assert I.post_date('posts/2026-02-30.html') is None          # 없는 날짜


def test_f5_corrector_strict_for_irregular_daily_names():
    # 옛 판정을 못 받는 일간 글 이름은 미완료(2)를 「원본도 그랬다」로 허용하지 않는다
    assert corrector.strict_for(f'posts/{OLD}.html') is False
    assert corrector.strict_for(f'posts/{NEW}.html') is True
    assert corrector.strict_for(f'posts/{OLD}-{NEW}.html') is True       # 전에는 끝 날짜로 판정
    assert corrector.strict_for(f'posts/{NEW}-{OLD}.html') is True       # 재현: 전에는 False(11/16 으로 읽었다)


def test_f5_style_pass_strict_for():
    sp = style_pass
    assert sp.strict_for(f'posts/{OLD}.html') is False and sp.strict_for(f'kr/posts/{OLD}.html') is False
    assert sp.strict_for(f'posts/{NEW}.html') is True and sp.strict_for(f'kr/posts/{NEW}.html') is True
    assert sp.strict_for(f'posts/{NEW}-{OLD}.html') is True               # 재현: 전에는 False(정규 경로만 봤다)
    assert sp.strict_for('weekly/2026-W46.html') is False                 # 일간 글이 아니다 — 1a 밖
    assert sp.strict_for('news/2026-11-17.html') is False


def test_f5_checkers_use_the_same_rule(tmp_path):
    # check_fund·check_numbers·check_macro·check_sources 의 --recheck·--legacy-releases 는 inputs.legacy_recheck 하나를 부른다
    import re
    scripts = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    users = []
    for name in sorted(os.listdir(scripts)):
        if name.startswith('check_') and name.endswith('.py'):
            src = open(os.path.join(scripts, name), encoding='utf-8').read()
            if '--recheck' in src or '--legacy-releases' in src:
                users.append(name)
                assert 'legacy_recheck(' in src, name
                assert not re.search(r"STRICT_FROM\s*=", src), name
    assert {'check_fund.py', 'check_numbers.py', 'check_macro.py', 'check_sources.py'} <= set(users)
