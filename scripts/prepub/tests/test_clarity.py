"""발행 전 검토의 명료성 분류(2026-11-18 사용자 결정, 설계 `../design-clarity-review.md` 5판).

새 검사기가 아니다 — 지금 있는 두 길(정확성·문체)에 싣는 분류가 늘고, 풀리지 않는 것은 기록만 한다.
여기 시험은 대부분 「지금 동작이 그대로인가」를 본다.
"""
import review_gate as gate
from close import guard
from prepub import split

HTML = ('<html><body data-register="da"><div class="doc">'
        '<h2>오늘의 장</h2>'
        '<p>나스닥은 2% 내렸다. 반도체가 하락을 이끌었고 금리는 앞단 재가격으로 본다는 해석이 나왔다.</p>'
        '<p>원자재는 엇갈렸다. 금은 이분 사건을 앞둔 노출 축소 흐름에 올랐고 유가는 내렸다.</p>'
        '<p>이 차이가 이미 가격에 들어 있는지는 모른다. 기술 업종은 시장을 앞섰다.</p>'
        '<p>그는 「금리가 부담이다」라고 말했다.</p>'
        '</div></body></html>')

REVIEW = '''1. §오늘의 장 — 나스닥 등락률이 근거와 다르다(근거 -2.1%).

=== 문체 지적 ===
- [논리·사실관계 의심] 「기술 업종은 시장을 앞섰다」 — 표는 뒤처졌다고 한다 / 근거와 대조
- [용어] 「이분 사건을 앞둔 노출 축소」 — (가) 무엇이 일어났는지 알 수 없다 / 풀어 쓴다
- [번역투] 「금리는 앞단 재가격으로 본다는」 — 판단 문장 / 낱말만
- [문장 구조] 「반도체가 하락을 이끌었고 금리는」 — (나) 판단과 근거가 얽혔다 / 가른다
- [지시 대상 불명확] 「이 차이가 이미 가격에」 — (다) 대상 불명확 / 대상을 밝힌다
'''


def _kinds(items):
    return [f['kind'] for f in items]


def test_a_term_finding_takes_the_existing_style_path_under_the_same_guard():
    got = split.split(REVIEW, HTML)
    hints = [it['hint'].split(':')[0] for it in got['candidates']['items']]
    assert sorted(hints) == ['번역투', '용어']
    assert all(it['relax'] == 'translationese' for it in got['candidates']['items'])
    text = guard.writer_input(got['candidates'], '규칙')
    assert '(지적 — 용어:' in text and '(지적 — 번역투:' in text


def test_structure_and_referent_findings_are_recorded_and_never_become_candidates():
    got = split.split(REVIEW, HTML)
    assert all(it['hint'].split(':')[0] not in ('문장 구조', '지시 대상 불명확')
               for it in got['candidates']['items'])
    rec = {f['kind']: f for f in got['clarity']}
    assert rec['문장 구조']['route'] == rec['지시 대상 불명확']['route'] == 'record_only'
    assert rec['문장 구조']['placed'] == rec['지시 대상 불명확']['placed'] == ''
    # 기록만 하는 분류는 「세기만 하던」 모르는 분류와 섞지 않는다
    assert got['dropped'] == [] and got['unplaced'] == [] and got['excluded'] == []


def test_a_doubt_about_content_goes_to_the_existing_accuracy_path():
    got = split.split(REVIEW, HTML)
    assert _kinds(got['accuracy']) == ['논리·사실관계 의심']
    assert {f['kind']: f['route'] for f in got['clarity']}['논리·사실관계 의심'] == 'accuracy'
    assert all('논리' not in it['hint'] for it in got['candidates']['items'])


def test_the_reader_question_is_kept_only_as_a_closed_value():
    got = {f['kind']: f for f in split.split(REVIEW, HTML)['clarity']}
    assert got['용어']['cannot_tell'] == '가'
    assert got['문장 구조']['cannot_tell'] == '나'
    assert got['지시 대상 불명확']['cannot_tell'] == '다'
    assert got['논리·사실관계 의심']['cannot_tell'] == ''
    odd = split.split('=== 문체 지적 ===\n- [용어] 「이분 사건을 앞둔 노출 축소」 — (라) eyJhbGciOi / x\n', HTML)
    assert odd['clarity'][0]['cannot_tell'] == ''


def test_where_a_term_finding_ended_up_is_known_at_split_time():
    review = ('=== 문체 지적 ===\n'
              '- [용어] 「이분 사건을 앞둔 노출 축소」 — (가) x / y\n'
              '- [용어] 「글에 없는 낱말이다」 — (가) x / y\n'
              '- [용어] 「그는 「금리가 부담이다」라고」 — (가) x / y\n')
    got = split.split(review, HTML)
    assert [f['placed'] for f in got['clarity']] == ['candidate', 'not_located', 'protected']
    assert _kinds(got['unplaced']) == ['용어'] and _kinds(got['excluded']) == ['용어']


def test_translationese_keeps_its_own_list_so_the_weekly_digest_does_not_count_twice():
    got = split.split(REVIEW, HTML)
    assert _kinds(got['style']) == ['번역투']
    assert '번역투' not in _kinds(got['clarity'])


# ── 상한: 고치는 길에 들어가는 양은 지금 최대(8)와 같다 ──────────────────────────────

def _lines(kind, n, quote='나스닥은 2% 내렸다'):
    return ''.join(f'- [{kind}] 「{quote}」 — (가) x / y\n' for _ in range(n))


def test_record_only_lines_cannot_push_accuracy_findings_out():
    review = ('=== 문체 지적 ===\n' + _lines('문장 구조', 40)
              + '- [판단 세기 흐림] 「반도체가 하락을 이끌었고」 — 단정 / 근거만큼\n')
    got = split.split(review, HTML)
    assert _kinds(got['accuracy']) == ['판단 세기 흐림']
    assert len([f for f in got['clarity'] if f['kind'] == '문장 구조']) == split.RECORD_MAX == 5
    assert got['meta']['over_cap'] == 35


def test_the_two_fix_paths_share_todays_cap_and_accuracy_fills_first():
    assert split.FIX_MAX == gate.STYLE_FINDINGS_MAX == 8
    review = ('=== 문체 지적 ===\n' + _lines('번역투', 6, '금리는 앞단 재가격으로 본다는')
              + _lines('판단 세기 흐림', 5, '반도체가 하락을 이끌었고'))
    got = split.split(review, HTML)
    assert len(got['accuracy']) == 5 and len(got['style']) == 3   # 옛 코드는 앞 8줄(번역투 6·판단 2)을 읽었다
    assert got['meta']['over_cap'] == 3


def test_an_answer_within_the_old_cap_is_read_exactly_as_before():
    old = ('1. 사실 지적.\n\n=== 문체 지적 ===\n'
           '- [번역투] 「금리는 앞단 재가격으로 본다는」 — 판단 문장 / 낱말만\n'
           '- [판단 세기 흐림] 「반도체가 하락을 이끌었고」 — 근거 없는 주체 단정 / 근거만큼\n'
           '- [번역투] 「그는 「금리가 부담이다」라고」 — 인용 / 잇는다\n'
           '- [번역투] 「본문에 없는 문장이다」 — 없다 / 없다\n'
           '- [반복] 「나스닥은 2% 내렸다」 — 되풀이 / 줄인다\n'
           '- [새로 지은 분류] 「유가는 내렸다」 — 기타 / 기타\n')
    facts, findings = gate.split_style_findings(old)
    got = split.split(old, HTML)
    assert got['facts'] == facts
    assert got['accuracy'] == [f for f in findings if f['kind'] in ('판단 세기 흐림', '원문에 없는 관계')]
    assert got['style'] == [f for f in findings if f['kind'] == '번역투']
    assert got['dropped'] == [f for f in findings if f['kind'] in ('반복', '기타')]
    assert got['clarity'] == []
    assert len(got['candidates']['items']) == 1 and len(got['unplaced']) == 1 and len(got['excluded']) == 1


# ── 답이 없거나 꼴이 깨졌을 때 — 지금과 같다 ───────────────────────────────────

def test_no_marker_sends_everything_to_the_fact_check_as_today():
    got = split.split('지적 없음', HTML)
    assert got['facts'] == '지적 없음' and got['candidates']['items'] == []
    assert got['accuracy'] == [] and got['clarity'] == []
    assert got['meta'] == {'marker': False, 'lines_skipped': 0, 'over_cap': 0}


def test_none_is_a_clean_zero_and_unreadable_lines_are_counted():
    clean = split.split('=== 문체 지적 ===\n없음\n', HTML)
    assert clean['meta'] == {'marker': True, 'lines_skipped': 0, 'over_cap': 0}
    broken = split.split('=== 문체 지적 ===\n1. [용어] 「이분 사건」 — x / y\n\n용어가 어렵다\n', HTML)
    assert broken['clarity'] == [] and broken['meta']['lines_skipped'] == 2


def test_an_unknown_kind_is_only_counted_as_before():
    got = split.split('=== 문체 지적 ===\n- [아무 분류] 「유가는 내렸다」 — x / y\n', HTML)
    assert _kinds(got['dropped']) == ['기타'] and got['clarity'] == [] and got['candidates']['items'] == []


def test_the_route_table_is_one_constant():
    """`용어` 를 기록만 하는 쪽으로 돌리는 것은 이 표의 한 줄이다 — 그 결정은 사용자 몫."""
    assert split.ROUTES == {'번역투': 'style_path', '용어': 'style_path',
                            '문장 구조': 'record_only', '지시 대상 불명확': 'record_only',
                            '판단 세기 흐림': 'accuracy', '원문에 없는 관계': 'accuracy',
                            '논리·사실관계 의심': 'accuracy'}


def test_a_reader_mark_written_inside_the_quote_is_moved_out():
    """과거 초안 엿새로 새 질문을 돌려 보니 이틀은 검토자가 표식을 인용 안에 넣었다(「(나) 이분 사건…」) —
    그대로 두면 인용이 글과 맞지 않아 자리를 못 찾는다(2026-11-18 측정)."""
    review = ('=== 문체 지적 ===\n'
              '- [용어] 「(나) 이분 사건을 앞둔 노출 축소」 — 무엇을 줄였는지 알 수 없다 / 풀어 쓴다\n'
              '- [지시 대상 불명확] 「(다)이 차이가 이미 가격에」 — 대상 불명확 / 밝힌다\n'
              '- [번역투] 「(가) 금리는 앞단 재가격으로 본다는」 — 판단 문장 / 낱말만\n')
    got = split.split(review, HTML)
    term, ref = got['clarity']
    assert (term['quote'], term['cannot_tell'], term['placed']) == ('이분 사건을 앞둔 노출 축소', '나', 'candidate')
    assert (ref['quote'], ref['cannot_tell']) == ('이 차이가 이미 가격에', '다')
    # 표식은 명료성 분류의 것이다 — 번역투 줄은 옛 읽기 그대로(글에 「(가)」로 시작하는 문장이 있을 수 있다)
    assert got['style'][0]['quote'] == '(가) 금리는 앞단 재가격으로 본다는'


def test_a_mark_in_the_note_wins_over_one_in_the_quote():
    review = '=== 문체 지적 ===\n- [용어] 「(나) 이분 사건을 앞둔 노출 축소」 — (가) 무엇인지 모른다 / 풀어 쓴다\n'
    assert split.split(review, HTML)['clarity'][0]['cannot_tell'] == '가'


# ── 옛 읽기와 달라지는 곳은 셋뿐이다 — 이름을 붙여 둔다(codex 구현 검토 1회차) ──────────────────

def test_the_three_intended_differences_from_the_old_reader():
    """① 8줄을 넘는 답: 옛 읽기는 앞 8줄에서 끊었다. 새 읽기는 끝까지 읽고 정확성을 먼저 채운다
    (`test_the_two_fix_paths_share_todays_cap_and_accuracy_fills_first`).
    ② 새 분류 이름: 옛 읽기는 모르는 이름이라 `기타`로 세기만 했다. 이제는 제 길로 간다.
    ③ 길이 없는 분류(반복·기타)도 8건까지만 센다 — 옛 읽기의 「앞 8줄」과 같은 크기로 묶어 둔다."""
    line = '- [문장 구조] 「반도체가 하락을 이끌었고 금리는」 — (가) 이유\n'
    _, old = gate.split_style_findings('=== 문체 지적 ===\n' + line)
    assert [f['kind'] for f in old] == ['기타']
    got = split.split('=== 문체 지적 ===\n' + line, HTML)
    assert got['dropped'] == [] and _kinds(got['clarity']) == ['문장 구조']
    many = split.split('=== 문체 지적 ===\n' + ''.join(
        f'- [아무 분류 {n}] 「유가는 내렸다」 — x / y\n' for n in range(9)), HTML)
    assert len(many['dropped']) == 8 and many['meta']['over_cap'] == 1


def test_an_answer_without_new_kinds_and_within_eight_lines_matches_the_old_reader_for_every_old_kind():
    kinds = list(gate.STYLE_KINDS) + ['처음 보는 분류']
    for a in kinds:
        for b in kinds:
            review = ('앞 지적.\n=== 문체 지적 ===\n'
                      f'- [{a}] 「금리는 앞단 재가격으로 본다는」 — x / y\n- [{b}] 「유가는 내렸다」 — x / y\n없음\n')
            facts, old = gate.split_style_findings(review)
            got = split.split(review, HTML)
            assert got['facts'] == facts, (a, b)
            assert got['accuracy'] == [f for f in old if f['kind'] in ('판단 세기 흐림', '원문에 없는 관계')], (a, b)
            assert got['style'] == [f for f in old if f['kind'] == '번역투'], (a, b)
            assert got['dropped'] == [f for f in old if f['kind'] not in ('판단 세기 흐림', '원문에 없는 관계', '번역투')], (a, b)
            assert got['clarity'] == [], (a, b)
