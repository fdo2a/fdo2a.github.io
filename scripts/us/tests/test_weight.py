from us.weight import (THRESHOLDS, check_volume, measure, prose_chars,  # noqa: F401
                       section_slice)

DOC = '''<h1>주식이 오른 하루</h1>
<section><h2>주식</h2><p>본문 열두 글자입니다</p>
<p class="caption">캡션은 세지 않는다</p>
<table><tr><td>짧은칸</td><td>이것은 마흔 글자를 넘기는 서술형 칸이라서 자수에 포함되어야 마땅한 칸이다</td></tr></table>
</section>
<section><h2>채권</h2><p>AT&amp;T</p></section>'''


def test_section_slice_uses_h2_not_headline():
    seg = section_slice(DOC, '주식')
    assert '본문 열두 글자입니다' in seg
    assert '오른 하루' not in seg


def test_section_slice_returns_none_when_absent():
    assert section_slice(DOC, '원자재') is None


def test_prose_chars_counts_paragraphs_and_long_cells_only():
    n = prose_chars(section_slice(DOC, '주식'))
    assert n == len('본문 열두 글자입니다') + len(
        '이것은 마흔 글자를 넘기는 서술형 칸이라서 자수에 포함되어야 마땅한 칸이다')


def test_prose_chars_decodes_entities():
    assert prose_chars(section_slice(DOC, '채권')) == len('AT&T')


def _doc(sizes):
    return '\n'.join(f'<section><h2>{t}</h2><p>{"가" * n}</p></section>'
                     for t, n in sizes.items())


US_FULL = {'오늘의 장': 800, '주식': 1900, '채권': 2000, 'FX': 650, '원자재': 750,
           '전략 코멘트': 400, '매크로 논리': 4400, '멀티에셋 매니저 전략': 2200}


def test_measure_groups_and_ratio():
    m = measure(_doc(US_FULL), 'us')
    assert m['recap'] == 800 + 1900 + 2000 + 650 + 750
    assert m['judgment'] == 400 + 4400 + 2200
    assert round(m['ratio'], 3) == round(m['recap'] / m['judgment'], 3)
    assert m['missing'] == []


def test_missing_section_is_a_violation_not_a_pass():
    doc = _doc({k: v for k, v in US_FULL.items() if k != '채권'})
    m = measure(doc, 'us')
    assert '채권' in m['missing']
    assert any('채권' in x for x in check_volume(m, market='us'))


def test_full_day_passes_thresholds():
    assert check_volume(measure(_doc(US_FULL), 'us'), False, 'us') == []


def test_measured_2026_08_27_shape_is_blocked():
    sizes = {'오늘의 장': 0, '주식': 1278, '채권': 1581, 'FX': 360, '원자재': 457,
             '전략 코멘트': 392, '매크로 논리': 4788, '멀티에셋 매니저 전략': 2244}
    v = check_volume(measure(_doc(sizes), 'us'), False, 'us')
    assert any('비율' in x or '÷' in x for x in v)
    assert any('매크로 논리' in x for x in v)


def test_abbreviated_day_caps_macro_and_raises_ratio_floor():
    v = check_volume(measure(_doc(US_FULL), 'us'), True, 'us')
    assert any('매크로 논리' in x and '2400' in x for x in v)
    ok = dict(US_FULL, **{'매크로 논리': 2000})
    assert check_volume(measure(_doc(ok), 'us'), True, 'us') == []


def test_deleting_judgment_to_game_the_ratio_is_blocked():
    sizes = dict(US_FULL, **{'매크로 논리': 500})
    v = check_volume(measure(_doc(sizes), 'us'), False, 'us')
    assert any('매크로 논리' in x and '3000' in x for x in v)


def test_kr_has_floor_but_no_ratio():
    sizes = {'오늘의 장': 700, '지수 & 장중': 900, '환율·금리': 700,
             '전략 코멘트': 700, '기술적 분석 & 트레이딩 전략': 500}
    assert check_volume(measure(_doc(sizes), 'kr'), market='kr') == []
    thin = dict(sizes, **{'지수 & 장중': 300})
    assert any('시황·가격군' in x
               for x in check_volume(measure(_doc(thin), 'kr'), market='kr'))
