from us.post_check import (banned_markers, body_text, markup_diff, report,
                           token_diff)

PAGE = ('<html><head><style>.a{color:#fff}</style></head><body>'
        '<p>S&amp;P 500은 7,707.98로 +0.21% 올랐다. VIX 14.89.</p></body></html>')


def test_style_and_markup_are_not_text():
    assert 'color' not in body_text(PAGE)
    assert 'S&P 500은' in body_text(PAGE)


def test_pure_prose_edits_pass():
    edited = PAGE.replace('올랐다', '상승 마감했다')
    assert report(PAGE, edited) == []


def test_a_changed_figure_is_caught():
    edited = PAGE.replace('+0.21%', '+0.12%')
    out = report(PAGE, edited)
    assert any('+0.21%' in x and '사라졌다' in x for x in out)
    assert any('+0.12%' in x and '생겼다' in x for x in out)


def test_a_deleted_sentence_reports_only_its_figures():
    edited = PAGE.replace(' VIX 14.89.', '')
    assert token_diff(PAGE, edited)['removed'] == {'VIX': 1, '14.89': 1}


def test_repeated_figures_are_counted_not_deduped():
    twice = PAGE.replace('VIX 14.89.', 'VIX 14.89. 재차 14.89.')
    assert token_diff(twice, PAGE)['removed'] == {'14.89': 1}


def test_placeholder_markers_never_ship():
    assert banned_markers(PAGE.replace('14.89', '[확인필요]')) == ['[확인필요]']


# ── 윤문 뒤 안전망 (AI 티 제거 스킬이 문장을 다시 쓴 뒤) ──

def test_rewriting_a_sentence_keeps_the_markup_intact():
    edited = PAGE.replace('S&amp;P 500은 7,707.98로 +0.21% 올랐다.',
                          'S&amp;P 500은 7,707.98까지 올라 +0.21% 상승 마감했습니다.')
    assert markup_diff(PAGE, edited) == []


def test_a_dropped_tag_is_caught():
    edited = PAGE.replace('<p>', '').replace('</p>', '')
    assert any('p' in m for m in markup_diff(PAGE, edited))


def test_an_added_tag_is_caught():
    edited = PAGE.replace('<p>', '<p><em>x</em>')
    assert any('em' in m for m in markup_diff(PAGE, edited))


def test_reordered_tags_are_caught():
    before = '<body><p>가</p><table><tr><td>나</td></tr></table></body>'
    after = '<body><table><tr><td>나</td></tr></table><p>가</p></body>'
    assert markup_diff(before, after) != []
