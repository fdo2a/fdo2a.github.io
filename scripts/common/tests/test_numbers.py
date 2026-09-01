"""공용 수치 추출 — 숫자를 쪼개 검사를 피해 가는 마크업을 잡는다.

「4.<span>47</span>bp」는 화면에 4.47bp 로 보이는데, 태그를 공백으로 바꾸면 검사에는
4 와 47bp 로 들어간다. 발행 게이트가 허용한 47bp 만 보고 통과시키는 길이다
(2026-09-01 codex 검토).
"""
import pytest

from common import numbers as N


@pytest.mark.parametrize('fragment', [
    '4.<span>47</span>bp', '4.<span></span>47bp', '4.<br hidden>47bp',
    '4.<div hidden></div>47bp', '4.<span><div hidden></div></span>47bp',
    '4.<span title=">"></span>47bp', "4.<span title='>'></span>47bp",
    '4.<!-- > -->47bp', '4.<!-- > --!>47bp', '4.<!--\n>\n-->47bp',
])
def test_a_number_split_by_markup_is_reported(fragment):
    assert N.numbers_split_by_tags(fragment)


@pytest.mark.parametrize('fragment', [
    '<td>10</td><td>20</td>', '<p>10</p><p>20</p>',
    '<ul><li>10</li><li>20</li></ul>',
    '<table><tr><td>10</td></tr><tr><td>20</td></tr></table>',
    '<td>4.47bp</td>', '<p>10<strong>가</strong></p><p>20</p>',
])
def test_ordinary_structure_is_not_reported(fragment):
    assert N.numbers_split_by_tags(fragment) == []


def test_a_comment_is_stripped_whole():
    assert '-->' not in N.text_of('<p>가<!-- > -->나</p>')
    assert '--!>' not in N.text_of('<p>가<!-- > --!>나</p>')


def test_an_attribute_angle_bracket_does_not_leak():
    assert '>' not in N.text_of('<p><span title=">">가</span></p>')


@pytest.mark.parametrize('fragment', [
    '2&#x200B;47bp', '2&#8203;47bp', '2​47bp', '2­47bp',
    '4.&#x200B;47bp',
])
def test_an_invisible_character_between_digits_is_reported(fragment):
    """화면에는 247bp 로 보이는데 검사에는 47bp 만 들어간다."""
    assert N.numbers_split_by_tags(fragment)


@pytest.mark.parametrize('fragment', [
    '<td>1,024.27</td>', '<p>2026년 8월</p>', '<p>10 &amp; 20</p>',
])
def test_ordinary_text_is_not_reported(fragment):
    assert N.numbers_split_by_tags(fragment) == []
