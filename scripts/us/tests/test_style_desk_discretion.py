"""데스크 문체 완화 — 2026-11-06 사용자 결정.

「수치·사실·출처는 엄격하게 통제하고, 문장·구성·리듬은 필자의 재량을 넓혀야 한다.」
발행을 막는 것은 -다 위반(register), 독자 문장의 작업 어휘(internal), 「국채 급등」
(bond_ambiguous) 셋뿐이다 — 셋 다 데스크 문서에서만 도는 검사다. 나머지 문체 지적은
모든 문서에서 경고로만 보이고, 경고는 고치라는 명령이 아니라 다시 읽어 보라는 표시다.
"""
import subprocess
import sys
from pathlib import Path

from us.style import BLOCKING, STYLE_NOTE, findings

ROOT = Path(__file__).resolve().parents[3]


def desk(body):
    return f'<html><body data-register="da"><div class="doc">{body}</div></body></html>'


def plain(body):
    return f'<html><body><div class="doc">{body}</div></body></html>'


def by_key(html):
    return {f['key']: f for f in findings(html)}


# 문체 지적을 한 문서에 몰아 넣는다 — 데스크에서는 전부 경고여야 한다.
STYLE_HEAVY = (
    '<p><strong>크로스에셋 정합성</strong> 지수가 흔들렸다.</p>'
    '<p><strong>수급 구도</strong> 외국인이 팔았다.</p>'
    '<p><strong>업종 흐름</strong> 반도체가 버텼다.</p>'
    '<p>하지만 금리가 올랐다. 이는 매파로 읽힌다. 상승으로 풀이된다. 하락으로 해석된다.</p>'
    '<p>하지만 정책에 따른 변화다. 수급에 따른 매도다. 실적에 따른 반등이다. 규제에 따른 조정이다.</p>'
    '<p>하지만 관망하는 상태다. 숨 고르는 모양새다. 방향을 찾는 국면이다.</p>'
    '<p>하지만 무엇을 기다릴까? 고용이다. 그럼 다음은 무엇일까? 물가다.</p>'
    '<p>하지만 브레드스 트리거가 약했다.</p>'
)


def test_style_findings_in_desk_documents_never_fail():
    found = by_key(desk(STYLE_HEAVY))
    for key in ('nominal_label', 'impersonal', 'translationese', 'noun_ending',
                'opener', 'question', 'jargon'):
        assert key in found, key
        assert found[key]['level'] == 'warn', key


def test_style_findings_are_notes_in_undeclared_documents_too():
    found = by_key(plain(STYLE_HEAVY))
    for key in ('nominal_label', 'impersonal', 'translationese', 'noun_ending', 'opener'):
        assert found[key]['level'] == 'warn', key
    assert by_key(plain('<p>지수가 올랐다. 금리가 올랐다. 달러가 올랐다. 유가가 올랐다.</p>'))[
        'monotone']['level'] == 'warn'


def test_only_register_workflow_words_and_bond_wording_block_desk_documents():
    assert BLOCKING == frozenset({'register', 'internal', 'bond_ambiguous'})
    html = desk('<h1>국채 급등</h1><p>판단 원장에는 기록이 없다. 지수가 올랐습니다. '
                '금리가 내렸습니다. 달러가 올랐죠.</p>')
    found = by_key(html)
    for key in BLOCKING:
        assert found[key]['level'] == 'fail', key


def test_same_ending_run_is_not_checked_in_desk_documents():
    html = desk('<p>지수가 올랐다. 금리가 올랐다. 달러가 올랐다. 유가가 올랐다. 금이 올랐다.</p>')
    assert 'monotone' not in by_key(html)


def test_same_number_repetition_is_not_checked():
    html = desk('<p>시가는 7,154였다.</p><p>7,154가 고가였다.</p>'
                '<p>지수는 7,154에서 밀렸다.</p><p>다시 7,154를 못 봤다.</p>'
                '<p>7,154는 120일선 위다.</p>')
    assert 'repeat_number' not in by_key(html)


def test_strategy_comment_needs_no_judgment_verb():
    html = desk('<h2>전략 코멘트</h2><p>단기물 금리가 더 크게 올랐다. 2년물이 8bp, 10년물이 2bp 올랐다.</p>')
    assert 'judgment_verb' not in by_key(html)


def test_large_provenance_block_is_a_note_not_a_block():
    long_text = '코스피는 오늘 올랐다. ' * 80
    found = by_key(desk(f'<p>지수가 올랐다.</p><details data-provenance><p>{long_text}</p></details>'))
    assert found['provenance']['level'] == 'warn'


def test_style_notes_ask_for_a_reread_not_a_rewrite():
    for f in findings(desk(STYLE_HEAVY)) + findings(plain(STYLE_HEAVY)):
        if f['level'] == 'warn' and f['key'] not in BLOCKING:
            assert f['message'].endswith(STYLE_NOTE), f['key']
            assert '까지)' not in f['message'], f['key']


def test_check_style_exits_zero_on_a_desk_document_full_of_style_notes(tmp_path):
    p = tmp_path / 'post.html'
    p.write_text(desk(STYLE_HEAVY), encoding='utf-8')
    r = subprocess.run([sys.executable, 'scripts/check_style.py', str(p)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


ORDERS = ('잇는다', '묶어 쓰고', '바꿔 쓴다', '나눈다', '풀어 쓴다', '끝낸다', '옮긴다', '숫자로 쓴다', '모으고', '다시 쓴다', '직접 쓴다')


def test_notes_carry_no_rewrite_orders_after_a_dash():
    # codex 구현 검토 #3 — 「. 」만 떼면 줄표 뒤 지시문이 남았다.
    html = desk('<p>' + ' '.join(f'지수가 {i}번째로 흔들렸다 — 이유는 금리였다.' for i in range(7)) + '</p>'
                '<p>' + ' '.join(['이를 가를 자료는 없다.', '단정하지 않는다.', '판단을 유보한다.',
                                  '확정하기는 이르다.', '특정할 수 없다.', '쪼갤 수 없다.', '가리지 못한다.'])
                + '</p><p>코스피는 이틀 연속 내렸다. 로이터는 반도체가 내렸다고 전했다. '
                '반도체 후보의 가격 근거는 약해졌고 CPI가 다음 시험이다. 오늘 새로 연 질문은 메모리다. '
                '금리는 관측되지 않았다. 질문을 가린다.</p>' + STYLE_HEAVY)
    for f in findings(html):
        if f['key'] in BLOCKING:
            continue
        body = f['message'][:-len(STYLE_NOTE)]
        assert not any(o in body for o in ORDERS), (f['key'], f['message'])
