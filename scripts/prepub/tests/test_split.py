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
- [기타] 「금리는 앞단 재가격으로 본다는」 — 판단 문장 / 손대지 않는다
- [판단 세기 흐림] 「반도체가 하락을 이끌었고」 — 근거 없는 주체 단정 / 근거만큼
- [끊긴 흐름] 「그는 「금리가 부담이다」라고」 — 인용 뒤 흐름 / 잇는다
- [반복] 「본문에 없는 문장이다」 — 없다 / 없다
'''


def test_accuracy_kinds_go_to_the_fact_check_not_the_style_path():
    got = split.split(REVIEW, HTML)
    assert [f['kind'] for f in got['accuracy']] == ['판단 세기 흐림']
    assert '나스닥 등락률' in got['facts']
    assert all('판단 세기' not in it['hint'] for it in got['candidates']['items'])


def test_a_style_finding_becomes_a_guarded_candidate_with_its_hint():
    got = split.split(REVIEW, HTML)
    items = got['candidates']['items']
    assert [it['hint'].split(':')[0] for it in items] == ['기타', '번역투']
    raw = HTML.encode('utf-8')
    assert guard._validate_candidates(raw, got['candidates']) is None


def test_quoted_paragraphs_and_unfound_quotes_are_reported_not_edited():
    got = split.split(REVIEW, HTML)
    assert [f['why'] for f in got['excluded']] == ['quote']
    assert [f['kind'] for f in got['unplaced']] == ['반복']


def test_a_judgment_paragraph_is_opened_but_marked():
    got = split.split(REVIEW, HTML)
    opened = [it for it in got['candidates']['items'] if it['opened'] == 'locked']
    assert len(opened) == 1 and '판단 문장' in guard.writer_input(got['candidates'], '규칙')


def test_only_translationese_may_touch_judgment_sentences():
    got = split.split(REVIEW, HTML)
    relaxed = [it for it in got['candidates']['items'] if it.get('relax')]
    assert [it['hint'].split(':')[0] for it in relaxed] == ['번역투']


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
