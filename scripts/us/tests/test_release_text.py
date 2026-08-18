from us import release_text as rt


def test_script_and_style_are_dropped():
    html = '<p>본문</p><script>var x=1;</script><style>p{color:red}</style>'
    assert 'var x' not in rt.to_text(html)
    assert 'color:red' not in rt.to_text(html)


def test_entities_are_unescaped():
    assert '0.1% & up' in rt.to_text('<p>0.1&#37; &amp; up</p>')


def test_tags_become_spaces_not_glued_words():
    assert 'rose 0.1 percent' in rt.to_text('<p>rose <b>0.1</b> percent</p>')


def test_table_rows_stay_on_their_own_lines():
    html = '<table><tr><td>Jul</td><td>0.1</td></tr><tr><td>Jun</td><td>-0.4</td></tr></table>'
    lines = [l for l in rt.to_text(html).splitlines() if l.strip()]
    assert len(lines) == 2
    assert 'Jul' in lines[0] and '0.1' in lines[0]


def test_blank_runs_are_collapsed():
    assert '\n\n\n' not in rt.to_text('<p>a</p>' + '<br>' * 20 + '<p>b</p>')


def test_body_starts_at_the_release_headline_when_present():
    html = ('<nav>Skip to Content Home Subjects</nav>'
            '<p>Consumer Price Index for All Urban Consumers (CPI-U) increased 0.1 percent</p>')
    assert rt.to_text(html).startswith('Consumer Price Index')


def test_text_is_capped_and_marked_when_truncated():
    out = rt.to_text('<p>' + 'x' * 5000 + '</p>', max_chars=500)
    assert len(out) <= 600
    assert out.rstrip().endswith(rt.TRUNCATED)


def test_short_text_is_not_marked():
    assert rt.TRUNCATED not in rt.to_text('<p>짧다</p>', max_chars=500)


def test_empty_input_is_empty_output():
    assert rt.to_text('') == ''
    assert rt.to_text(None) == ''
