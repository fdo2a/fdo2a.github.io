"""발행 전 검토의 「번역투」 후보(relax) — 판단 문장의 낱말은 고치되 판단 뼈대는 그대로여야 한다.

10/13 반영 중지의 원인이 된 편집(`test_guard.HOLES`)은 relax 에서도 전부 막혀야 한다.
"""
import pytest

from close import guard
from close.tests.test_guard import HOLES, page
from us.prose_swap import ProseSwapError, extract


def check(before, after, relax):
    html = page(before).decode()
    _, side = extract(html)
    try:
        guard.check_edit('P001', ' '.join(before.split()), after, side['items'], relax=relax)
        return True, ''
    except ProseSwapError as exc:
        return False, str(exc)


@pytest.mark.parametrize('before,after', HOLES)
def test_the_1013_holes_stay_blocked_when_judgment_words_may_change(before, after):
    ok, _ = check(before, after, relax=True)
    assert not ok, '뚫렸다: %s' % after


CTX = (' 2년물은 8bp, 10년물은 2bp 올라 커브가 평평해졌다. 고용보고서가 예상보다 강했고 달러도 함께 올랐다.'
       ' 주식은 장 초반 밀렸다가 오후에 낙폭을 줄였고 거래량은 평소 수준이었다.')
J = '단기물 금리가 먼저 오른 것은 12월 인상이 기본 경로로 굳어지는 앞단 재가격으로 본다.' + CTX


def test_translationese_inside_a_judgment_sentence_can_be_fixed():
    ok, why = check(J, '단기물 금리가 먼저 오른 것은 가까운 만기부터 12월 인상을 기본 경로로 다시 값매겼다는 뜻으로 본다.' + CTX, True)
    assert ok, why


def test_the_same_edit_is_refused_without_relax():
    ok, _ = check(J, '단기물 금리가 먼저 오른 것은 가까운 만기부터 12월 인상을 기본 경로로 다시 값매겼다는 뜻으로 본다.' + CTX, False)
    assert not ok


@pytest.mark.parametrize('after', [
    '단기물 금리가 먼저 오른 것은 12월 인상이 기본 경로로 굳어지는 앞단 재가격이다.' + CTX,      # 본다 → 단정
    '단기물 금리가 먼저 오른 것은 12월 인상이 기본 경로다. 앞단 재가격으로 본다.' + CTX,          # 쪼갬
    '단기물 금리가 먼저 오른 것은 1월 인상이 기본 경로로 굳어지는 앞단 재가격으로 본다.' + CTX,    # 날짜
])
def test_strength_split_and_dates_are_still_refused(after):
    ok, _ = check(J, after, True)
    assert not ok, after


def test_in_an_opened_paragraph_only_non_judgment_sentences_change():
    before = '금리가 올랐다. 이는 정책 부담으로 본다. 달러는 보합권에서 움직였다는 점이 눈에 띄었다.'
    ok, why = check(before, '금리가 올랐다. 이는 정책 부담으로 본다. 달러는 보합권에서 움직였다.', False)
    assert ok, why
    ok, _ = check(before, '금리가 올랐다. 이는 정책 부담 때문으로 본다. 달러는 보합권에서 움직였다.', False)
    assert not ok


def check_scope(before, after, relax):
    html = page(before).decode()
    _, side = extract(html)
    try:
        guard.check_edit('P001', ' '.join(before.split()), after, side['items'], relax=relax, scope=True)
        return True, ''
    except ProseSwapError as exc:
        return False, str(exc)


@pytest.mark.parametrize('before,after,relax', [
    ('반등은 일시적인 현상으로 본다.' + CTX, '반등은 지속적인 현상으로 본다.' + CTX, True),
    ('매도는 일부 업종에서 나왔다고 본다.' + CTX, '매도는 모든 업종에서 나왔다고 본다.' + CTX, True),
    ('수요가 버텼다. 다만 공급 요인은 불확실하다. 이는 정책 부담으로 본다.' + CTX,
     '수요가 버텼다. 공급 요인은 확실하다. 이는 정책 부담으로 본다.' + CTX, False),
])
def test_scope_and_limit_words_cannot_move_in_opened_paragraphs(before, after, relax):
    """codex 구현 검토 #5 — 판단 문장을 그대로 둔 채 범위·세기·한계를 바꾸는 편집."""
    ok, _ = check_scope(before, after, relax)
    assert not ok, after


def test_swapping_what_a_quantifier_covers_is_refused():
    """codex 구현 재검토 #5."""
    before = '일부 업종은 강세였다. 모든 종목은 부진했다고 본다.' + CTX
    ok, _ = check_scope(before, '일부 종목은 강세였다. 모든 업종은 부진했다고 본다.' + CTX, True)
    assert not ok


def test_swapping_a_longer_quantified_phrase_is_refused():
    """codex 구현 재검토 3차 #2 — 수식어가 낀 수량어 명사구."""
    before = '일부 반도체 업종은 강세였다. 모든 반도체 종목은 부진했다고 본다.' + CTX
    ok, _ = check_scope(before, '일부 반도체 종목은 강세였다. 모든 반도체 업종은 부진했다고 본다.' + CTX, True)
    assert not ok


def test_a_genitive_does_not_cut_the_quantified_phrase():
    """codex 구현 재검토 4차 #2."""
    before = '일부 미국의 반도체 업종은 강세였다. 모든 미국의 반도체 종목은 부진했다고 본다.' + CTX
    ok, _ = check_scope(before, '일부 미국의 반도체 종목은 강세였다. 모든 미국의 반도체 업종은 부진했다고 본다.' + CTX, True)
    assert not ok


def test_the_writer_is_shown_the_marks_the_guard_will_hold():
    # 11/06 US 시험: 작성자가 「앞단 재가격」을 풀며 「쪽으로」를 새로 써 뼈대에서 기각됐다 — 무엇이 표지인지 몰랐다
    text = ('우리는 이 평탄화를 앞단 재가격으로 본다. 임금이 올라 연준이 미룰 근거가 줄었다. '
            '가장 강한 반론은 2년물이 일부 되돌아왔다는 설명이다.')
    cand = {'items': [{'id': 'C01', 'hint': '번역투: 풀어 쓴다', 'relax': 'translationese', 'masked': text}]}
    shown = guard.writer_input(cand, '규칙')
    for mark in ('「으로 본다」', '「근거가」', '「반론」', '「우리」', '「일부」', '「가장」'):
        assert mark in shown
    assert '새로 쓰지 않는다' in shown and '문장 수' in shown


def test_the_writer_is_shown_what_a_quantifier_covers():
    """codex 구현 #3 — guard 는 「일부:반도체 업종은」을 비교한다. 대상 명사구까지 보여야 그것을 고치지 않는다."""
    text = '일부 반도체 업종은 앞단 재가격 끝에 내렸다고 본다.'
    cand = {'items': [{'id': 'C01', 'hint': '번역투: 풀어 쓴다', 'relax': 'translationese', 'masked': text}]}
    assert '「일부 반도체 업종은」' in guard.writer_input(cand, '규칙')
