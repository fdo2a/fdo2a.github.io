from scripts.us.session_gate import check

SESSION = {
    'report_date': '2026-08-27',
    'global_close': {
        'asia': {'rows': [{'name': '닛케이', 'pct': -0.2, 'date': '2026-08-27'},
                          {'name': '항셍', 'pct': -0.34, 'date': '2026-08-27'}],
                 'alignment': {'label': '이어감', 'mixed': False, 'avg_pct': -0.27}},
        'europe': {'rows': [{'name': 'DAX', 'pct': 0.31, 'date': '2026-08-27'},
                            {'name': 'FTSE100', 'pct': -0.79, 'date': '2026-08-27'}],
                   'alignment': {'label': '엇갈림', 'mixed': True, 'avg_pct': -0.24}},
    },
    'futures': {'contracts': {'ES': {'high': 7741.25}}, 'gap': {'S&P 500': 0.45},
                'direction': '상승 출발'},
    'participation': {'gap_pp': -0.95, 'band': '소수가 끌어올림'},
    'tape': {'Nasdaq': {'close_position': 95, 'band': '고점권 마감'}},
}

FULL = ('<section><h2>오늘의 장</h2>'
        '<p data-session="global">유럽은 미국과 엇갈렸습니다. DAX 0.31%, FTSE100 -0.79%. '
        '아시아도 닛케이 -0.20%, 항셍 -0.34%로 함께 밀렸습니다.</p>'
        '<p data-session="preopen">상승 출발이었습니다.</p>'
        '<p data-session="tape">소수가 끌어올림이었고 나스닥은 고점권 마감입니다.</p>'
        '<p data-session="causal">엔비디아 실적이 하루를 만들었습니다.</p></section>')


def test_clean_page_passes():
    assert check(FULL, SESSION) == []


def test_absent_block_is_not_enforced():
    assert check('<p>아무것도 없다</p>', None) == []


def test_missing_marker_fails():
    assert any('causal' in v for v in check(FULL.replace(' data-session="causal"', ''), SESSION))


def test_empty_marked_block_fails():
    html = FULL.replace('상승 출발이었습니다.', '')
    assert any('preopen' in v for v in check(html, SESSION))


def test_silence_on_a_divergent_region_fails():
    html = FULL.replace('유럽은 미국과 엇갈렸습니다.', '유럽도 함께 움직였습니다.')
    assert any('엇갈' in v for v in check(html, SESSION))


def test_mentioning_participation_when_neutral_fails():
    s = dict(SESSION, participation={'gap_pp': 0.1, 'band': '중립'})
    assert any('중립' in v for v in check(FULL, s))


def test_omitting_participation_when_it_fired_fails():
    html = FULL.replace('소수가 끌어올림이었고 ', '')
    assert any('소수가 끌어올림' in v for v in check(html, SESSION))


def test_calling_it_breadth_fails():
    html = FULL.replace('소수가 끌어올림이었고', '상승 종목 비율이 낮았고 소수가 끌어올림이었고')
    assert any('상승 종목 비율' in v for v in check(html, SESSION))


def test_internal_field_names_fail():
    assert any('gap_pp' in v for v in check(FULL + '<p>gap_pp는 -0.95입니다.</p>', SESSION))


def test_section_number_notation_fails_but_css_comment_passes():
    assert check('<style>/* §8 스트립 */</style>' + FULL, SESSION) == []
    assert any('§' in v for v in check(FULL + '<p>§9 포지션은 유지합니다.</p>', SESSION))


def test_table_must_carry_the_actual_closes():
    html = FULL.replace('FTSE100 -0.79%', 'FTSE100 -0.75%')
    assert any('FTSE100' in v for v in check(html, SESSION))


def test_a_stale_regional_close_must_carry_its_date():
    s = {**SESSION}
    s['global_close'] = {**SESSION['global_close'],
                         'asia': {'rows': [{'name': '닛케이', 'pct': -0.2, 'date': '2026-08-21'},
                                           {'name': '항셍', 'pct': -0.34, 'date': '2026-08-21'}],
                                  'alignment': None}}
    assert any('닛케이' in v and '기준일' in v for v in check(FULL, s))


def test_leftover_placeholder_fails():
    assert any('확인필요' in v for v in check(FULL + '<p>[확인필요]</p>', SESSION))


KR_SESSION = {
    'report_date': '2026-08-28',
    'us_prev': {'as_of': '2026-08-26', 'lag_sessions': 2, 'rows': {'S&P 500': 0.72}},
    'asia_peers': {'rows': {'닛케이': -0.2}, 'avg_pct': -0.2, 'relative_pp': 1.1},
}

KR_FULL = ('<section><h2>오늘의 장</h2>'
           '<p data-session="global">26일 미국장 기준으로 S&P 500은 올랐습니다. '
           '아시아에서는 닛케이가 -0.20%였고 코스피가 더 강했습니다.</p>'
           '<p data-session="preopen">갭 상승으로 출발했습니다.</p>'
           '<p data-session="tape">오후 들어 밀렸고 원달러는 1,374원에서 끝났습니다.</p>'
           '<p data-session="causal">외국인 매수가 하루를 만들었습니다.</p></section>')


def test_kr_page_passes_without_us_only_fields():
    assert check(KR_FULL, KR_SESSION, market='kr') == []


def test_kr_stale_us_session_must_be_labelled():
    html = KR_FULL.replace('26일 미국장 기준으로 ', '')
    assert any('미국장 기준' in v for v in check(html, KR_SESSION, market='kr'))


def test_violation_messages_use_the_right_particle():
    html = FULL.replace('유럽은 미국과 엇갈렸습니다.', '유럽도 함께 움직였습니다.')
    assert any('유럽이 미국과 엇갈렸는데' in v for v in check(html, SESSION))


def test_markers_outside_the_section_do_not_satisfy_the_gate():
    """제목 없이 문단 표식만 흩뿌려 놓고 통과시키지 않는다."""
    loose = FULL.replace('<section><h2>오늘의 장</h2>', '<section>').replace('</section>', '')
    assert any('오늘의 장' in v for v in check(loose, SESSION))


def test_preopen_may_be_omitted_when_there_is_nothing_to_say():
    s = {**SESSION, 'futures': {'contracts': {}, 'gap': {}, 'direction': None}}
    html = FULL.replace('<p data-session="preopen">상승 출발이었습니다.</p>', '')
    assert not any('preopen' in v for v in check(html, s))


def test_each_divergent_region_needs_its_own_name():
    s = {**SESSION}
    s['global_close'] = {
        'asia': {'rows': SESSION['global_close']['asia']['rows'],
                 'alignment': {'label': '엇갈림', 'mixed': False, 'avg_pct': -0.27}},
        'europe': SESSION['global_close']['europe'],
    }
    assert any('아시아' in v for v in check(FULL, s))      # 유럽만 언급했다


def test_internal_names_from_the_spec_are_blocked():
    for bad in ('gap_pct', 'close_position'):
        assert any(bad in v for v in check(FULL + f'<p>{bad}</p>', SESSION))


def test_vix_must_match_the_collected_level():
    pc = {'levels': {'VIX': {'value': 14.51}}}
    ok = FULL.replace('</section>', '<p>VIX는 14.51입니다.</p></section>')
    assert check(ok, SESSION, price_context=pc) == []
    assert any('VIX' in v for v in check(FULL, SESSION, price_context=pc))
