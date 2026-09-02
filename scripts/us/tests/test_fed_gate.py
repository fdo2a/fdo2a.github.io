from us import fed_gate as fg

CORPUS = ('The Committee decided to lower the target range for the federal funds rate to '
          '4-1/4 to 4-1/2 percent. Inflation remains somewhat elevated. The Committee is '
          'attentive to the risks to both sides of its dual mandate. We are not on a '
          'preset course and will judge each meeting on the incoming data.')

EVENT = {
    'key': 'fomc-statement-20260917', 'kind': 'fomc_statement',
    'kind_ko': 'FOMC 성명', 'tier': 1, 'fresh': True, 'date': '2026-09-17',
    'sources': [{'role': 'statement', 'label': 'FOMC 성명 전문', 'ok': True,
                 'text': CORPUS}],
}


def book(events=None, diff=None):
    return {'report_date': '2026-09-17', 'events': events if events is not None else [EVENT],
            'diff': diff}


def quote_card(key, english, trans='위원회는 물가와 고용 양쪽 위험을 함께 보고 있다고 했습니다.'):
    return (f'<div class="fed-quote" data-fed-quote="{key}">'
            f'<blockquote>{english}</blockquote>'
            f'<p class="fed-trans">{trans}</p>'
            f'<p class="caption">출처: FOMC 성명 전문 · 연준</p></div>')


def idea(n, ref):
    return (f'<div data-fed-idea="{n}" data-fed-quote-ref="{ref}">'
            f'<p>{"성명이 물가를 여전히 높다고 부른 이상 금리 인하는 한 번에 끝날 일이 아닙니다. " * 4}</p>'
            f'<p data-invalidation="{n}">근원 물가가 다시 3%를 넘어서는 달이 두 번 이어지면 '
            f'이 생각은 접습니다.</p>'
            f'</div>')


def page(body):
    return ('<html><body><main><h2>주식</h2><p>앞 섹션</p>'
            '<h2>연준 이벤트 — 발언록과 해석</h2>' + body +
            '<h2>멀티에셋 매니저 전략</h2><p>뒤 섹션</p></main></body></html>')


def no_section(body=''):
    return ('<html><body><main><h2>주식</h2><p>앞 섹션</p>' + body +
            '<h2>멀티에셋 매니저 전략</h2><p>뒤 섹션</p></main></body></html>')


LEDE = '9월 FOMC 는 정책금리 상단을 4%로 내렸습니다. 성명 문장이 어디서 바뀌었는지가 오늘의 알맹이입니다. '
QUOTE_A = 'The Committee is attentive to the risks to both sides of its dual mandate.'

FULL = page(
    '<p data-fed-event="fomc-statement-20260917">' + LEDE * 3 + '</p>'
    + quote_card('fomc-statement-20260917', QUOTE_A)
    + quote_card('fomc-statement-20260917',
                 'We are not on a preset course and will judge each meeting on the incoming data.',
                 '미리 정해 둔 경로는 없고 회의마다 데이터를 보고 판단하겠다고 했습니다.')
    + idea(1, 'fomc-statement-20260917') + idea(2, 'fomc-statement-20260917'))


def test_clean_page_passes():
    assert fg.check(FULL, book()) == []


def test_silent_day_forbids_the_section():
    v = fg.check(FULL, book(events=[]))
    assert len(v) == 1 and '섹션이 실렸다' in v[0]


def test_silent_day_with_no_section_passes():
    assert fg.check(no_section(), book(events=[])) == []
    assert fg.check('<html><body></body></html>', None) == []


def test_event_day_requires_the_section():
    v = fg.check(no_section(), book())
    assert any('섹션이 없다' in e for e in v)


def test_fabricated_quote_is_blocked():
    bad = FULL.replace(QUOTE_A,
                       'We stand ready to cut rates aggressively at the next meeting.')
    v = fg.check(bad, book())
    assert any('원문에 없는 조각' in e for e in v)


def test_short_fragments_cannot_be_smuggled_past_the_check():
    # 40자를 넘기되 조각을 전부 25자 미만으로 쪼개면 예전에는 검증 대상이 사라졌다.
    bad = FULL.replace(QUOTE_A,
                       'Rates will fall now. [...] Inflation is defeated. [...] Jobs stay strong.')
    assert any('너무 짧은 조각' in e for e in fg.check(bad, book()))


def test_hidden_negation_cannot_flip_the_meaning():
    # `<span hidden>not </span>` 하나로 게이트가 읽는 문장과 독자가 보는 문장이 갈린다.
    bad = FULL.replace('<blockquote>We are not on a preset course',
                       '<blockquote>We are <span hidden>not </span>on a preset course')
    assert any('태그가 있다' in e for e in fg.check(bad, book()))


def test_unmarked_blockquote_is_blocked():
    # 정상 인용 둘을 남겨 두고 창작 인용을 하나 더 놓는 우회.
    bad = FULL.replace('<div class="fed-quote"',
                       '<blockquote>We will cut rates aggressively tomorrow.</blockquote>'
                       '<div class="fed-quote"', 1)
    assert any('표식 없는 <blockquote>' in e for e in fg.check(bad, book()))


def test_empty_marker_cannot_borrow_the_next_blockquote():
    bad = FULL.replace('<div class="fed-quote" data-fed-quote="fomc-statement-20260917">',
                       '<div data-fed-quote="fomc-statement-20260917"></div><div>', 1)
    v = fg.check(bad, book())
    assert any('<blockquote>가 없다' in e for e in v)
    assert any('표식 없는 <blockquote>' in e for e in v)


def test_quote_survives_typographic_quotes_and_dashes():
    ok = FULL.replace(QUOTE_A,
                      '“the target range for the federal funds rate to 4‑1/4 to 4‑1/2 percent”')
    assert fg.check(ok, book()) == []


def test_quote_without_a_fetched_source_is_blocked():
    dark = dict(EVENT, sources=[{'role': 'statement', 'ok': False, 'note': '403'}])
    v = fg.check(FULL, book([dark]))
    assert any('원문을 받아 두지 못한' in e for e in v)


def test_missing_source_does_not_demand_quotes():
    dark = dict(EVENT, sources=[{'role': 'statement', 'ok': False}])
    body = ('<p data-fed-event="fomc-statement-20260917">' + '성명이 나왔습니다. ' * 15 + '</p>'
            + '<div data-fed-idea="1" data-fed-quote-ref="fomc-statement-20260917">x</div>')
    v = fg.check(page(body), book([dark]))
    assert not any('검증된 인용이' in e for e in v)


def test_translation_and_caption_are_required():
    v = fg.check(FULL.replace('<p class="fed-trans">위원회는 물가와 고용 양쪽 위험을 함께 보고 있다고 했습니다.</p>', ''),
                 book())
    assert any('한국어 번역' in e for e in v)
    v = fg.check(FULL.replace('<p class="caption">출처: FOMC 성명 전문 · 연준</p>', '', 1), book())
    assert any('출처 캡션' in e for e in v)


def test_two_quotes_are_required_per_event():
    one = page('<p data-fed-event="fomc-statement-20260917">' + LEDE * 3 + '</p>'
               + quote_card('fomc-statement-20260917', QUOTE_A)
               + idea(1, 'fomc-statement-20260917') + idea(2, 'fomc-statement-20260917'))
    assert any('검증된 인용이 1개' in e for e in fg.check(one, book()))


def test_ideas_must_hang_off_a_printed_quote():
    v = fg.check(FULL.replace('data-fed-quote-ref="fomc-statement-20260917"',
                              'data-fed-quote-ref="jackson-hole-20260828"'), book())
    assert any('지면에 없는 발언' in e for e in v)


def test_ideas_need_an_invalidation():
    v = fg.check(FULL.replace('근원 물가가 다시 3%를 넘어서는 달이 두 번 이어지면 이 생각은 접습니다.',
                              '확인'), book())
    assert any('무효화 조건이 비어 있다' in e for e in v)


def test_invalidation_must_sit_inside_its_own_idea():
    # 섹션 어딘가에 개수만 맞춰 두면 어느 아이디어가 무엇으로 무효화되는지 알 수 없다.
    moved = FULL.replace('<p data-invalidation="1">근원 물가가 다시 3%를 넘어서는 달이 두 번 '
                         '이어지면 이 생각은 접습니다.</p>', '')
    assert any('무효화 조건이 없다' in e for e in fg.check(moved, book()))


def test_too_few_ideas():
    v = fg.check(FULL.replace(idea(2, 'fomc-statement-20260917'), ''), book())
    assert any('투자 아이디어가 1개' in e for e in v)


def test_intro_paragraph_is_required():
    v = fg.check(FULL.replace('data-fed-event="fomc-statement-20260917"', 'class="x"'), book())
    assert any('도입 문단이 없다' in e for e in v)


# ── 성명문 변경점 ─────────────────────────────────────────────────────────────

DIFF = {'changed': [{'before': 'Inflation remains elevated.',
                     'after': 'Inflation remains somewhat elevated.'}],
        'added': [], 'removed': [], 'kept': 5}


def change_block(text):
    return f'<div data-fed-change="1"><p>{text}</p></div>'


def test_change_block_is_required_when_a_redline_exists():
    assert any('변경점' in e for e in fg.check(FULL, book(diff=DIFF)))


def test_change_block_must_carry_the_changed_sentence():
    body = FULL.replace('<h2>멀티에셋', change_block('물가 표현이 조금 바뀌었습니다. ' * 8)
                        + '<h2>멀티에셋')
    v = fg.check(body, book(diff=DIFF))
    assert any('바뀐 문장을 하나도 옮기지' in e for e in v)


def test_change_block_with_the_verbatim_sentence_passes():
    body = FULL.replace('<h2>멀티에셋', change_block(
        '물가 문장에 한 낱말이 붙었습니다. Inflation remains somewhat elevated. '
        '이 「somewhat」이 이번 성명의 신호입니다. ' * 3) + '<h2>멀티에셋')
    assert fg.check(body, book(diff=DIFF)) == []


# ── 수치·누출 ────────────────────────────────────────────────────────────────

def test_number_from_the_statement_itself_is_allowed():
    # 「4%」는 성명문의 4-1/4~4-1/2 에서 온 값이다 — 데이터 파일엔 없지만 원문엔 있다.
    assert fg.check(FULL, book()) == []


def test_invented_number_is_blocked():
    v = fg.check(FULL.replace('상단을 4%로', '상단을 7.75%로'), book())
    assert any('수치 창작 금지' in e for e in v)


def test_market_data_number_is_allowed():
    ok = FULL.replace('오늘의 알맹이입니다.', '오늘의 알맹이입니다. S&P 500 은 1.42% 올랐습니다.')
    assert any('수치 창작 금지' in e for e in fg.check(ok, book()))
    assert fg.check(ok, book(), {'indices': {'sp500': {'change_pct': 1.42}}}) == []


def test_internal_terms_are_blocked():
    v = fg.check(FULL.replace('9월 FOMC 는', 'research_notes 에 따르면 9월 FOMC 는'), book())
    assert any('내부 용어' in e for e in v)


def test_number_split_by_a_tag_is_caught():
    v = fg.check(FULL.replace('상단을 4%로', '상단을 4<span></span>0%로'), book())
    assert any('태그가 끼어' in e for e in v)


def test_invalidation_may_set_a_forward_threshold():
    # 「3%를 넘으면 접는다」의 3% 는 우리가 거는 문턱이지 데이터가 준 값이 아니다.
    assert '3%' in FULL and fg.check(FULL, book()) == []


def test_prose_after_the_invalidation_is_still_swept():
    # 무효화 문단을 닫은 뒤 본문에 거짓 수치를 넣는 우회.
    bad = FULL.replace('이 생각은 접습니다.</p>',
                       '이 생각은 접습니다.</p><p>10년물은 근거 없이 6.66%까지 갑니다.</p>', 1)
    assert any('6.66' in e for e in fg.check(bad, book()))


def test_idea_body_may_not_smuggle_an_invented_number():
    bad = FULL.replace('금리 인하는 한 번에 끝날 일이 아닙니다.',
                       '10년물은 6.66%까지 갈 수 있습니다.')
    assert any('6.66' in e for e in fg.check(bad, book()))


def test_korean_percent_is_measured_too():
    # 「6퍼센트」로 쓰면 수치 검사가 통째로 비켜 가던 구멍.
    bad = FULL.replace('오늘의 알맹이입니다.', '오늘의 알맹이입니다. 10년물은 근거 없이 6퍼센트입니다.')
    assert any('6.0' in e for e in fg.check(bad, book()))


# ── 대소문자 (HTML 은 태그·속성 이름의 대소문자를 가리지 않는다) ──────────────

FAKE_UPPER = ('<BLOCKQUOTE>We will cut rates aggressively tomorrow regardless of '
              'inflation.</BLOCKQUOTE>')


def test_uppercase_orphan_blockquote_is_caught():
    """브라우저에는 보이는데 검사에서만 사라지는 마크업이 있으면 안 된다."""
    bad = FULL.replace('<h2>멀티에셋', FAKE_UPPER + '<h2>멀티에셋', 1)
    assert any('표식 없는 <blockquote>' in e for e in fg.check(bad, book()))


def test_uppercase_markup_still_verifies_normally():
    ok = FULL.replace('<div class="fed-quote" data-fed-quote=',
                      '<DIV class="fed-quote" DATA-FED-QUOTE=')
    assert fg.check(ok, book()) == []


def test_uppercase_hidden_span_is_caught():
    bad = FULL.replace('<blockquote>We are not on a preset',
                       '<blockquote>We are <SPAN HIDDEN>not </SPAN>on a preset', 1)
    assert any('태그가 있다' in e for e in fg.check(bad, book()))


def test_entity_written_markup_is_not_a_hiding_place():
    # 엔티티로 쓴 태그는 브라우저가 글자로 보여 주므로 숨김이 아니다 — 대신 그 글자가
    # 원문에 없으니 대조에서 걸린다.
    bad = FULL.replace('<blockquote>We are not on a preset',
                       '<blockquote>We are &lt;span hidden&gt;not &lt;/span&gt;on a preset', 1)
    assert any('원문에 없는 조각' in e for e in fg.check(bad, book()))


def test_zero_width_character_in_a_quote_is_caught():
    bad = FULL.replace('We are not on a preset', 'We are​ not on a preset', 1)
    assert fg.check(bad, book())
