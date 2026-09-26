from scripts.common import signcolor as C


def test_signed_numbers_get_the_sign_colour():
    out = C.paint('<p>나스닥 +1.57%, 러셀 -0.87%, 금리차 −36.2bp</p>')
    assert '<span class="pos">+1.57%</span>' in out
    assert '<span class="neg">-0.87%</span>' in out and '<span class="neg">−36.2bp</span>' in out


def test_dates_ranges_and_unsigned_numbers_are_left_alone():
    s = '<p>2026-09-21부터 2026-09-24까지 6.3~9.5bp, 16.6bp 올랐다</p>'
    assert C.paint(s) == s


def test_attributes_and_style_are_not_touched():
    s = '<div data-x="-5"><style>.a{margin:-3px}</style><td>+2.0</td></div>'
    out = C.paint(s)
    assert 'data-x="-5"' in out and 'margin:-3px' in out and '<span class="pos">+2.0</span>' in out


def test_zero_change_stays_neutral():
    assert C.paint('<td>+0.0bp</td>') == '<td>+0.0bp</td>'


def test_visible_text_is_unchanged():
    import re
    s = '<p>상관 -0.68, 순포지션 +7,423계약, 해외채권 -16,065억 엔</p>'
    assert re.sub(r'<[^>]+>', '', C.paint(s)) == re.sub(r'<[^>]+>', '', s)
