"""문체 수정 지시문 — 글을 「하나의 글」로 잇게 하고, 그러면서 지킬 한도를 실제 상수와 맞춘다.

2026-10-10 사용자 지시 「문장이 너무 뚝뚝 끊어져서 글이라고 안 느껴진다 — 주간뿐 아니라
모닝브리프도 '하나의 글'이 되도록」. 지시문은 일간·주간·월간·일본이 함께 쓴다.

지시문의 수치는 사람이 옮겨 적은 것이라, 게이트 상수가 바뀌면 조용히 낡는다. 낡은 한도를
믿고 문장을 합친 codex 는 게이트에 걸리고, 게이트 하나가 글 전체 수정을 버린다
(style_log 17건 중 7건이 지시문에 없던 규칙으로 전체 거부였다). 상수를 지시문에 꽂지 않고
여기서 맞대는 것은 러너의 import 결합을 늘리지 않으려는 것이다.
"""
import check_readability as readability
import review_gate as g
from us import prose_swap, style
from us.prose_swap import extract, reinsert_partial

PROMPT = g.STYLE_PROMPT.format(rules='')
# 「네 개」「세 번」 — 단위 앞에 오는 꼴.
COUNT = {1: '한', 2: '두', 3: '세', 4: '네', 5: '다섯', 6: '여섯', 7: '일곱'}


def test_the_prompt_asks_for_one_connected_piece():
    assert '하나의 글' in PROMPT
    assert '연결어미' in PROMPT and '접속어' in PROMPT
    assert '문단 사이' in PROMPT


def test_the_old_one_relation_rule_is_gone():
    # 「한 문장에 한 관계」는 잇기를 금지하는 것과 같았다.
    assert '한 문장에 한 관계' not in PROMPT


def test_connectives_may_not_invent_causes():
    assert '원문이 말한 관계' in PROMPT


def test_figure_limit_matches_the_strict_gate():
    # --strict 는 warn 도 반려라 FAIL 이 아니라 WARN 이 실제 한도다.
    assert f'숫자는 {COUNT[readability.FIG_WARN]} 개까지' in PROMPT


def test_whole_post_limits_match_the_style_gate():
    # 음차 용어 한도는 적지 않는다 — jargon_stack 은 COMMON 을 세지 않아서, 적으면 게이트가
    # 허용하는 「밸류에이션과 모멘텀」까지 막는다(2026-10-10 codex 설계 검토 #2).
    assert f'{COUNT[style.MAX_SAME_ENDING_RUN + 1]} 개 이어지면' in PROMPT
    assert f'문단은 글 전체에서 {COUNT[style.MAX_SAME_OPENER]} 번까지' in PROMPT
    assert f'합계 {COUNT[style.MAX_TRANSLATIONESE]} 번까지' in PROMPT


def test_the_period_gate_phrase_is_quoted_as_it_is_searched():
    # check_period 는 「표본 부족」 부분 문자열을 찾는다. W40·W41 윤문이 이 말을 흐려 통째로 버려졌다.
    assert '「표본 부족」' in PROMPT


def test_paragraph_limits_match_reinsert():
    low, high = prose_swap.LEN_RATIO
    assert f'{low:g}~{high:g}배' in PROMPT


def test_every_negation_the_checker_counts_is_named():
    # 부정어 개수가 바뀌면 그 문단이 버려진다 — 「~뿐 아니라」「~없이」가 잇는 말로 흔하다.
    # 원문에 있던 것은 지켜야 하므로 금지가 아니라 「넣거나 빼지 않는다」다.
    assert '부정어(않·아니·못·없·띄어 쓴 「안」)' in PROMPT
    assert '새로 넣거나 원문에서 빼지 않는다' in PROMPT


# 지시문이 시키는 편집이 되꽂기를 실제로 통과하는지 — 통과 못 하면 지시는 헛돈다.
PAGE = ('<html><body data-register="da"><div class="card"><p>%s</p></div></body></html>')
CHOPPY = ('10년물 금리는 주중 2002년 이후 최고까지 올랐다. 주간으로는 3bp 남짓 내렸다. '
          '연방기금금리 선물의 경로도 거의 움직이지 않았다. 할인율이 내려간 주에 장기 성장주가 밀렸다.')


def swap(before, after):
    html = PAGE % before
    text, sidecar = extract(html)
    return reinsert_partial(html, text.replace(before, after), sidecar)


def test_joining_with_endings_and_connectives_passes_reinsert():
    joined = ('10년물 금리는 주중 2002년 이후 최고까지 올랐지만 주간으로는 3bp 남짓 내렸고, '
              '연방기금금리 선물의 경로도 거의 움직이지 않았다. 그런데 할인율이 내려간 주에 '
              '장기 성장주가 밀렸다.')
    new, skipped = swap(CHOPPY, joined)
    assert skipped == []
    assert '올랐지만' in new and '그런데' in new


def test_a_new_negation_in_the_joint_is_kept_out():
    joined = ('10년물 금리는 주중 2002년 이후 최고까지 올랐을 뿐 아니라 주간으로는 3bp 남짓 내렸다. '
              '연방기금금리 선물의 경로도 거의 움직이지 않았다. 할인율이 내려간 주에 장기 성장주가 밀렸다.')
    new, skipped = swap(CHOPPY, joined)
    assert [pid for pid, _ in skipped] == ['P001']
    assert CHOPPY in new


def test_reordering_sentences_to_join_them_is_kept_out():
    joined = ('주간으로는 3bp 남짓 내렸지만 10년물 금리는 주중 2002년 이후 최고까지 올랐다. '
              '연방기금금리 선물의 경로도 거의 움직이지 않았다. 할인율이 내려간 주에 장기 성장주가 밀렸다.')
    _, skipped = swap(CHOPPY, joined)
    assert [pid for pid, _ in skipped] == ['P001']


def test_connective_spam_is_capped():
    # 2026-10-10 시험 운전: 10/09 브리프에 「다만」 0→10, 「반면」 1→9, W41 에 「실제로」 1→6.
    assert '같은 접속어' in PROMPT and '두 번까지' in PROMPT
    assert '「실제로」는 접속어가 아니다' in PROMPT


def test_the_figure_rule_says_unit_digits_count():
    # readability.figures 는 단위·부호 없는 한 자리 정수만 뺀다(codex 구현 검토 #6).
    from us import readability
    assert readability.figures('1bp 3% 7') == ['1bp', '3%']
    assert '단위·부호 없는 한 자리 정수만' in PROMPT and '「1bp」' in PROMPT


def test_the_prompt_carries_the_judgment_verb_rule_for_every_report():
    # 2026-10-17 W42 외부 문체 평가 → 「모든 레포트에 적용」(STYLE_EXEMPLARS §10-8~10).
    p = g.STYLE_PROMPT
    assert '§10-8~10' in p and '무게를 옮긴다' in p and '판단의 세기' in p
