from close import guard
from prepub import split

HTML = ('<html><body data-register="da"><div class="doc">'
        '<h2>오늘의 장</h2>'
        '<p>나스닥은 2% 내렸다. 반도체가 하락을 이끌었고 금리는 앞단 재가격으로 본다는 해석이 나왔다.</p>'
        '<p>원자재는 엇갈렸다. 금은 앞단 재가격 흐름에 올랐고 유가는 내렸다.</p>'
        '<p>그는 「금리가 부담이다」라고 말했다.</p>'
        '</div></body></html>')

REVIEW = '''1. §오늘의 장 — 나스닥 등락률이 근거와 다르다(근거 -2.1%).

=== 문체 지적 ===
- [번역투] 「금은 앞단 재가격 흐름에」 — 압축이 심하다 / 풀어 쓴다
- [번역투] 「금리는 앞단 재가격으로 본다는」 — 판단 문장 / 낱말만
- [판단 세기 흐림] 「반도체가 하락을 이끌었고」 — 근거 없는 주체 단정 / 근거만큼
- [번역투] 「그는 「금리가 부담이다」라고」 — 인용 / 잇는다
- [번역투] 「본문에 없는 문장이다」 — 없다 / 없다
- [반복] 「나스닥은 2% 내렸다」 — 되풀이 / 줄인다
- [끊긴 흐름] 「원자재는 엇갈렸다」 — 흐름 / 옮긴다
- [기타] 「유가는 내렸다」 — 기타 / 기타
'''


def test_accuracy_kinds_go_to_the_fact_check_not_the_style_path():
    got = split.split(REVIEW, HTML)
    assert [f['kind'] for f in got['accuracy']] == ['판단 세기 흐림']
    assert '나스닥 등락률' in got['facts']
    assert all('판단 세기' not in it['hint'] for it in got['candidates']['items'])


def test_a_style_finding_becomes_a_guarded_candidate_with_its_hint():
    got = split.split(REVIEW, HTML)
    items = got['candidates']['items']
    assert [it['hint'].split(':')[0] for it in items] == ['번역투', '번역투']
    raw = HTML.encode('utf-8')
    assert guard._validate_candidates(raw, got['candidates']) is None


def test_quoted_paragraphs_and_unfound_quotes_are_reported_not_edited():
    got = split.split(REVIEW, HTML)
    assert [f['why'] for f in got['excluded']] == ['quote']
    assert [(f['kind'], f['why']) for f in got['unplaced']] == [('번역투', 'not_found')]


def test_a_judgment_paragraph_is_opened_but_marked():
    got = split.split(REVIEW, HTML)
    opened = [it for it in got['candidates']['items'] if it['opened'] == 'locked']
    assert len(opened) == 1 and '판단 문장' in guard.writer_input(got['candidates'], '규칙')


def test_only_translationese_may_touch_judgment_sentences():
    got = split.split(REVIEW, HTML)
    assert all(it.get('relax') == 'translationese' for it in got['candidates']['items'])


def test_the_writer_sees_the_finding_for_each_candidate():
    got = split.split(REVIEW, HTML)
    text = guard.writer_input(got['candidates'], '규칙')
    assert '(지적 — 번역투:' in text and '짚은 문체 문제' in text


def test_flow_candidates_keep_the_old_writer_prompt():
    cand = {'items': [{'id': 'C01', 'masked': '짧다. 짧다.'}]}
    text = guard.writer_input(cand, '규칙')
    assert text.startswith('문체 마감(STEP 2.6)') and '지적 —' not in text


def test_no_findings_marker_means_no_candidates():
    got = split.split('지적 없음', HTML)
    assert got['candidates']['items'] == [] and got['accuracy'] == []


def test_a_quote_inside_a_judgment_zone_stays_excluded():
    """codex 구현 검토 #3 — 판단 구역을 열어도 따옴표 문단은 열지 않는다."""
    html = ('<html><body data-register="da"><div class="doc"><h2>채권</h2>'
            '<p data-standing>그는 「금리가 부담이다」라고 말했다. 이는 정책 부담으로 본다.</p></div></body></html>')
    review = '=== 문체 지적 ===\n- [번역투] 「그는 금리가 부담이라고」 — 어색하다 / 고친다\n- [번역투] 「이는 정책 부담으로 본다」 — x / y\n'
    got = split.split(review, html)
    assert got['candidates']['items'] == [] and {f['why'] for f in got['excluded']} == {'quote'}


# 2026-11-07 사용자 결정 「번역투 고치는것만 검토하는걸로 하자」 — 반복·끊긴 흐름·기타는 발행 전에 고치지 않는다
def test_only_translationese_becomes_a_style_candidate():
    got = split.split(REVIEW, HTML)
    assert {it['hint'].split(':')[0] for it in got['candidates']['items']} == {'번역투'}
    assert sorted(f['kind'] for f in got['dropped']) == ['기타', '끊긴 흐름', '반복']


def test_dropped_kinds_are_not_reported_as_unplaced_or_excluded():
    got = split.split(REVIEW, HTML)
    assert all(f['kind'] == '번역투' for f in got['unplaced'] + got['excluded'])


SHORT = ('<html><body data-register="da"><div class="doc"><h2>금리</h2>'
         '<p>10년물은 앞단 재가격 끝에 내렸다. 달러도 약했다.</p>'
         '<p>유가는 올랐다. 수요 우려는 줄었다.</p></div></body></html>')


def test_a_short_translationese_quote_is_placed_when_it_is_unique():
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    got = split.split(review, SHORT)
    assert len(got['candidates']['items']) == 1 and got['unplaced'] == []


def test_a_quote_found_in_two_paragraphs_is_not_guessed():
    review = '=== 문체 지적 ===\n- [번역투] 「유가는 올랐다」 — 예 / 예\n'
    html = SHORT.replace('달러도 약했다', '유가는 올랐다')
    got = split.split(review, html)
    assert got['candidates']['items'] == [] and [f['why'] for f in got['unplaced']] == ['ambiguous']


def test_a_quote_shorter_than_four_letters_is_not_placed():
    review = '=== 문체 지적 ===\n- [번역투] 「앞단」 — 예 / 예\n'
    got = split.split(review, SHORT)
    assert got['candidates']['items'] == [] and [f['why'] for f in got['unplaced']] == ['short']


def test_a_quote_also_in_a_caption_is_not_guessed():
    """codex 구현 #1 — 후보가 아닌 캡션에도 같은 인용이 있으면 codex 가 캡션을 짚었을 수 있다."""
    html = SHORT.replace('</h2>', '</h2><p class="caption">앞단 재가격 기준 표</p>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    got = split.split(review, html)
    assert got['candidates']['items'] == [] and [f['why'] for f in got['unplaced']] == ['ambiguous']


def test_a_quote_whose_tail_is_not_in_the_text_is_not_placed():
    """codex 구현 #2 — 앞머리만 맞고 뒤가 다른 인용(본문에 없는 말)은 그 문단에 붙이지 않는다."""
    review = '=== 문체 지적 ===\n- [번역투] 「10년물은 앞단 재가격 끝에 내렸다가 반등했다」 — 예 / 예\n'
    got = split.split(review, SHORT)
    assert got['candidates']['items'] == [] and [f['why'] for f in got['unplaced']] == ['not_found']


def test_the_writer_is_shown_marks_that_only_the_ledger_locks():
    """codex 구현 #4 — 원장 문턱이 든 문장도 판단 문장으로 잠긴다. 원장 없이 세면 그 문장의 주인이 빠진다."""
    from close import locks
    html = ('<html><body data-register="da"><div class="doc"><h2>금리</h2>'
            '<p>연준 경로는 0.35%p 차이로 벌어졌다. 우리는 이를 앞단 재가격으로 본다.</p></div></body></html>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    led = locks.Ledger([{'type': 'hypothesis', 'report_date': '2026-11-01', 'support': '0.35%p 넘게'}])
    with_ledger = guard.writer_input(split.split(review, html, led)['candidates'], '규칙')
    without = guard.writer_input(split.split(review, html)['candidates'], '규칙')
    assert '「연준」' in with_ledger and '「0.35%p」' in with_ledger
    assert '「연준」' not in without


def test_an_entity_spelled_duplicate_still_counts_as_a_duplicate():
    """codex 구현 재검토 #1 — 캡션의 「앞단&nbsp;재가격」도 독자에겐 같은 말이다."""
    html = SHORT.replace('</h2>', '</h2><p class="caption">앞단&nbsp;재가격 기준 표</p>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    assert [f['why'] for f in split.split(review, html)['unplaced']] == ['ambiguous']


def test_overlapping_repeats_are_counted():
    """재검토 #2 — 「금리 금리 금리」 안의 「금리 금리」는 두 자리다."""
    html = SHORT.replace('달러도 약했다', '금리 금리 금리였다')
    review = '=== 문체 지적 ===\n- [번역투] 「금리 금리」 — 예 / 예\n'
    assert [f['why'] for f in split.split(review, html)['unplaced']] == ['ambiguous']


def test_text_from_two_blocks_does_not_join_into_a_fake_duplicate():
    """재검토 #3 — 제목 끝과 다음 캡션 첫머리가 붙어 인용처럼 보이면 안 된다."""
    html = SHORT.replace('<h2>금리</h2>', '<h2>금리 앞단</h2><p class="caption">재가격 표</p>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    got = split.split(review, html)
    assert len(got['candidates']['items']) == 1 and got['unplaced'] == []


def test_a_quote_split_by_an_inline_tag_or_entity_is_found():
    """codex 구현 재검토 3회 #1 — 찾기는 보이는 글로, 고치기는 자리표가 든 글로."""
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    for frag in ('앞단 <strong>재가격</strong>', '앞단&nbsp;재가격'):
        got = split.split(review, SHORT.replace('앞단 재가격', frag))
        items = got['candidates']['items']
        assert len(items) == 1 and got['unplaced'] == [], frag
    assert '⟦0⟧' in split.split(review, SHORT.replace('앞단 재가격', '앞단 <strong>재가격</strong>'))[
        'candidates']['items'][0]['masked']


def test_hidden_script_text_does_not_make_a_duplicate():
    """재검토 3회 #2 — 스크립트·주석 안의 글은 독자가 보지 않는다."""
    html = SHORT.replace('<h2>', '<script>var s="앞단 재가격";</script><!-- 앞단 재가격 --><h2>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    got = split.split(review, html)
    assert len(got['candidates']['items']) == 1 and got['unplaced'] == []


def test_a_paragraph_inside_a_script_string_is_never_a_candidate():
    """codex 구현 재검토 4회 #1 — 화면엔 캡션에만 있는 말이 스크립트 속 가짜 문단으로 후보가 됐다."""
    html = ('<html><body data-register="da"><div class="doc"><h2>금리</h2>'
            '<script>var t="<p>앞단 재가격 흐름이다.</p>";</script>'
            '<p class="caption">앞단 재가격 표</p><p>유가는 올랐다.</p></div></body></html>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    got = split.split(review, html)
    assert got['candidates']['items'] == [] and [f['why'] for f in got['unplaced']] == ['not_found']


def test_a_paragraph_holding_a_script_is_never_a_candidate():
    """codex 구현 재검토 5회 #1 — 문단 안 스크립트의 「가격」을 고쳐도 guard 를 지났다."""
    html = ('<html><body data-register="da"><div class="doc"><h2>금리</h2>'
            '<p>앞단 재가격 흐름이다.<script>var 가격=1;</script></p></div></body></html>')
    review = '=== 문체 지적 ===\n- [번역투] 「앞단 재가격」 — 명사 나열 / 풀어 쓴다\n'
    got = split.split(review, html)
    assert got['candidates']['items'] == []
