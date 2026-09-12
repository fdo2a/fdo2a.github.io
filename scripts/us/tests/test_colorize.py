"""수치 칸 방향색 — scripts/us/colorize.py."""
import re

from scripts.us import colorize as C


def _doc(body, head='<style>/* readability-v5 */\n</style>'):
    return f'<html><head>{head}</head><body><main>{body}</main></body></html>'


def _row(*cells):
    return '<tr>' + ''.join(f'<td data-label="{k}">{v}</td>' for k, v in cells) + '</tr>'


def _table(*rows):
    return '<div class="tbl-scroll"><table>' + ''.join(rows) + '</table></div>'


def _cls(html, label):
    """그 열의 (셀 class or None) 목록."""
    out = []
    for attrs in re.findall(r'<td\b([^>]*)>', html):
        if f'data-label="{label}"' not in attrs:
            continue
        m = re.search(r'class="([^"]*)"', attrs)
        out.append(m.group(1) if m else None)
    return out


EQUITIES = '<h2>주식</h2>' + _table(
    _row(('자산', 'S&P 500'), ('종가', '6,500.00'), ('전일 대비', '+0.42%')),
    _row(('자산', '나스닥'), ('종가', '21,000.00'), ('전일 대비', '-1.10%')),
    _row(('자산', '러셀'), ('종가', '2,400.00'), ('전일 대비', '-0.00%')))


def test_sign_colours_gain_green_loss_red_flat_none():
    out = C.apply(_doc(EQUITIES))
    assert _cls(out, '전일 대비') == [C.POS, C.NEG, None]


def test_sign_leaves_other_columns_alone():
    out = C.apply(_doc(EQUITIES))
    assert _cls(out, '종가') == [None, None, None]


def test_session_table_uses_등락():
    body = '<h2>오늘의 장</h2>' + _table(
        _row(('지수', 'DAX'), ('등락', '-1.66%')),
        _row(('지수', 'VIX'), ('등락', '+8.38%')))
    out = C.apply(_doc(body))
    assert _cls(out, '등락') == [C.NEG, C.POS]


BONDS = '<h2>채권</h2>' + _table(
    _row(('만기', '2Y'), ('9/10 금리', '4.586%'), ('전일 변화', '+15.0bp'),
         ('주간 변화', '-2.0bp')))


def test_bond_yield_is_inverted():
    """금리가 올랐으면 빨강, 떨어졌으면 초록 (2026-09-12 사용자 지시 4)."""
    out = C.apply(_doc(BONDS))
    assert _cls(out, '전일 변화') == [C.NEG]
    assert _cls(out, '주간 변화') == [C.POS]


def test_inversion_is_scoped_to_the_bond_section():
    """같은 이름의 열이 다른 섹션에 생겨도 거꾸로 칠하지 않는다."""
    body = '<h2>원자재</h2>' + _table(_row(('자산', 'WTI'), ('주간 변화', '+3.0%')))
    out = C.apply(_doc(body))
    assert _cls(out, '주간 변화') == [None]


def test_bond_section_still_colours_전일_대비_by_sign():
    body = '<h2>채권</h2>' + _table(_row(('자산', 'TLT'), ('전일 대비', '+0.30%')))
    assert _cls(C.apply(_doc(body)), '전일 대비') == [C.POS]


MACRO = '<h2>매크로</h2>' + _table(
    _row(('지표', 'CPI YoY'), ('최근', '3.54 %'), ('이전', '3.73 %')),
    _row(('지표', 'Initial Jobless Claims'), ('최근', '206,000.00 '),
         ('이전', '207,000.00 ')),
    _row(('지표', 'Nonfarm Payrolls (chg)'), ('최근', '162.00 K'), ('이전', '21.00 K')),
    _row(('지표', 'Unemployment Rate'), ('최근', '4.10 %'), ('이전', '4.10 %')),
    _row(('지표', 'Core PCE YoY'), ('최근', '3.40 %'), ('이전', '3.34 %')),
    _row(('지표', 'Made Up Index'), ('최근', '5.00'), ('이전', '1.00')))


def test_macro_uses_indicator_polarity_not_raw_sign():
    """물가 둔화·실업수당 감소·고용 증가는 초록, 물가 재가속은 빨강."""
    assert _cls(C.apply(_doc(MACRO)), '최근') == [
        C.POS,   # CPI 3.73 -> 3.54 둔화
        C.POS,   # 신규 실업수당 감소
        C.POS,   # NFP 증가
        None,    # 실업률 변화 없음
        C.NEG,   # Core PCE 재가속
        None,    # 극성을 모르는 지표
    ]


def test_macro_previous_column_is_not_coloured():
    assert _cls(C.apply(_doc(MACRO)), '이전') == [None] * 6


def test_css_is_injected_once_into_head():
    out = C.apply(_doc(EQUITIES))
    assert out.count(C.MARKER) == 1
    assert out.index(C.MARKER) < out.index('</head>')
    assert C.apply(out) == out


def test_idempotent_and_recolours_a_stale_class():
    """값이 바뀌어 다시 돌면 예전 색이 남지 않는다."""
    once = C.apply(_doc(EQUITIES))
    flipped = once.replace('+0.42%', '-0.42%')
    assert _cls(C.apply(flipped), '전일 대비')[0] == C.NEG


def test_existing_classes_on_the_cell_survive():
    body = '<h2>주식</h2><table><tr><td class="num" data-label="전일 대비">+1.0%</td></tr></table>'
    out = C.apply(_doc(body))
    assert 'class="num %s"' % C.POS in out


def test_numbers_and_tags_are_untouched():
    def visible(html):
        return re.sub(r'<[^>]+>', '', re.sub(r'(?is)<style\b.*?</style>', '', html))

    src = _doc(EQUITIES + BONDS + MACRO)
    assert visible(C.apply(src)) == visible(src)


def test_unicode_minus_reads_as_negative():
    body = '<h2>FX</h2>' + _table(_row(('자산', 'DXY'), ('전일 대비', '−0.32%')))
    assert _cls(C.apply(_doc(body)), '전일 대비') == [C.NEG]


def test_unparsable_cell_is_left_colourless():
    body = '<h2>FX</h2>' + _table(_row(('자산', 'DXY'), ('전일 대비', 'n/a')))
    assert _cls(C.apply(_doc(body)), '전일 대비') == [None]


def test_head_without_style_still_gets_the_rules():
    out = C.apply(_doc(EQUITIES, head=''))
    assert C.MARKER in out
    assert out.index(C.MARKER) < out.index('</head>')


# --- 실제 발행본의 형태 (2026-09-12 codex 구현 검토) ---

MACRO_NEW = '<h2>매크로</h2>' + _table(
    _row(('지표', 'CPI 전월비'), ('Actual', '0.40%='), ('Forecast', '0.40%(다우존스)'),
         ('Previous', '0.07%'), ('판정', '뚜렷한 둔화')),
    _row(('지표', '신규 실업수당 청구'), ('Actual', '206,000'), ('Forecast', '—'),
         ('Previous', '207,000'), ('판정', '완만한 악화')),
    _row(('지표', '신규주택 판매'), ('Actual', '607천'), ('Forecast', '—'),
         ('Previous', '678천'), ('판정', '미미한 보합')))


def test_macro_reads_the_verdict_column_instead_of_recomputing():
    """판정은 이미 계산돼 온다 — 원시 부호로 다시 읽으면 정반대로 칠한다."""
    out = C.apply(_doc(MACRO_NEW))
    assert _cls(out, 'Actual') == [C.POS, C.NEG, None]
    assert _cls(out, 'Previous') == [None, None, None]
    assert _cls(out, 'Forecast') == [None, None, None]


def test_the_stance_step_column_is_never_painted():
    """「전일대비」는 가격이 아니라 등급 이동이다 — ▼1단계가 초록이 됐던 자리."""
    body = ('<h2>멀티에셋 전략·포트폴리오</h2>'
            + _table(_row(('자산', '주식'), ('전일대비', '▼1단계')),
                     _row(('자산', '채권'), ('전일대비', '유지'))))
    assert _cls(C.apply(_doc(body)), '전일대비') == [None, None]


def test_hand_written_colours_in_old_posts_are_left_alone():
    """옛 발행본은 표에 손으로 넣은 class 를 쓴다 — 소급이 그것을 지웠다."""
    body = ('<h2>주식</h2><table><tr><td class="pos">+0.29%</td>'
            '<td class="neg">-1.10%</td></tr></table>')
    out = C.apply(_doc(body))
    assert 'class="pos"' in out and 'class="neg"' in out


def test_a_footnote_marker_does_not_become_the_value():
    body = ('<h2>주식</h2><table><tr>'
            '<td data-label="전일 대비"><sup>1</sup>-0.32%</td></tr></table>')
    assert _cls(C.apply(_doc(body)), '전일 대비') == [C.NEG]


def test_a_commented_out_heading_does_not_break_the_bond_scope():
    body = ('<h2>채권</h2><!-- <h2>주식</h2> -->'
            + _table(_row(('만기', '2Y'), ('전일 변화', '+1.0bp'))))
    assert _cls(C.apply(_doc(body)), '전일 변화') == [C.NEG]


def test_a_fake_row_inside_a_style_element_is_not_painted():
    body = ('<h2>주식</h2><style>.x::after{content:\'<tr>'
            '<td data-label="전일 대비">+1%</td></tr>\'}</style>')
    out = C.apply(_doc(body))
    assert not re.search(r'<td[^>]*class="sc-', out)


def test_a_marker_string_in_the_body_does_not_suppress_the_css():
    body = '<!-- %s --><h2>주식</h2>' % C.MARKER + _table(
        _row(('자산', 'S&P 500'), ('전일 대비', '+0.42%')))
    out = C.apply(_doc(body, head=''))
    assert 'td.%s' % C.POS in out
