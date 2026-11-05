"""close_guard — 결정적 검사가 막아야 하는 편집과 반영 결속."""

import json

import pytest

from close import flow, guard, locks
from us.prose_swap import ProseSwapError, extract

P1 = '유가가 2% 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'
P2 = '나스닥은 1.2% 올랐다. 반도체가 앞장섰다. 기술주 전반으로 매수세가 번지며 지수를 끌어올린 하루였다.'
P3 = '이 문단은 길게 써서 후보가 되지 않게 한 문장으로 끝까지 이어 쓰며 문맥을 주는 역할만 하도록 둔다.'


def page(*ps):
    return ('<html><body><h2>시장</h2><div class="card">%s</div></body></html>'
            % ''.join('<p>%s</p>' % p for p in ps)).encode('utf-8')


def setup(*ps):
    pre = page(*ps)
    cand = flow.scan(pre.decode())
    return pre, cand


def one(before, after):
    """편집 하나를 단독으로 검사 → (통과?, 이유)."""
    pre = page(before)
    html = pre.decode()
    _, side = extract(html)
    try:
        guard.check_edit('P001', ' '.join(before.split()), after, side['items'])
        return True, ''
    except ProseSwapError as exc:
        return False, str(exc)


def test_join_with_go_passes():
    ok, why = one(P1, '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.')
    assert ok, why


@pytest.mark.parametrize('after,needle', [
    ('유가가 2% 올랐다.</p><p>금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', 'HTML'),
    ('유가가 2% <a href="x">올랐다</a>. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', 'HTML'),
    ('유가가 2% 올랐다 &amp; 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '엔티티'),
    ('유가가 2% 올랐다. “금리가 내렸다.” 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '따옴표'),
    ('유가가 2% 오르면서 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '관계'),
    ('유가가 2% 오르자 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '관계'),
    ('유가가 2% 올랐지만 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '관계'),
    ('유가가 2% 올라서 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '관계'),
    ('유가가 3% 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '수치'),
    ('유가가 2% 내렸다. 금리가 올랐다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.', '방향'),
    ('유가가 2% 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다. 반등은 이르다고 본다.',
     None),
])
def test_rejected_edits(after, needle):
    ok, why = one(P1, after)
    assert not ok
    if needle:
        assert needle in why, why


def test_relation_removed_rejected():
    before = '유가가 올랐지만 금리는 그대로였다. 달러는 보합이었다. 엔화도 보합권에서 하루를 마감했다고 전해졌다.'
    ok, why = one(before, '유가가 올랐다. 금리는 그대로였다. 달러는 보합이었다. 엔화도 보합권에서 하루를 마감했다고 전해졌다.')
    assert not ok and '관계' in why


def test_noun_ja_not_relation():
    assert guard.relations('투자 심리가 살아났다. 적자 폭이 줄었다.') == {}
    assert guard.relations('발표가 나오자 금리가 내렸다.') == {'-자': 1}
    assert guard.relations('시장에서 매수가 늘었다.') == {}


# ---- 10/13 구멍 9건(replay.py A1-A9) — 후보에서 빠지거나 편집이 기각돼야 한다
M12 = ('언론은 하락을 중국과의 D램 경쟁으로 설명했지만, 우리는 AI 하드웨어 묶음 전체의 포지션 축소가 주된 동력이고 '
       'CXMT는 이름표에 가깝다고 판단한다. D램을 만들지 않는 시게이트가 마이크론과 거의 같은 폭(-3.80%)으로 '
       '내렸고, 광학주는 회사 소식 없이 더 크게 빠졌기 때문이다.')
H12 = ('우리는 AI 하드웨어 묶음의 포지션 축소가 주된 동력이라고 본다. 대안은 CXMT 진입이 D램 가격과 마이크론 '
       '이익률의 정점을 낮춘다는 경쟁 재평가다. 시험은 10월 13일 개장부터 16일 종가까지 마이크론 누적 수익률에서 '
       '시게이트·웨스턴디지털 평균을 뺀 값이다. 마이크론이 3.88%p 넘게 뒤처지면 대안이 맞다.')
L13 = ('반도체·AI 하드웨어 업종의 3개월 상대수익률은 한 주 사이 크게 나빠졌고, 이날 메모리·장비주 약세가 그 흐름을 '
       '이어 갔다. 메모리를 AI 하드웨어 관련주와 같은 위험으로 볼지 중국 D램 공급이라는 별도 위험으로 볼지는 16일 '
       '종가까지 마이크론과 HDD 두 종목의 상대 성과로 정한다.')
I13 = ('10월 12일 종가 대비 16일 종가까지의 누적 수익률에서 마이크론이 시게이트·웨스턴디지털 평균보다 3.88%p 넘게 '
       '뒤처지면, 포지션 축소라는 판단은 약해지고 D램 경쟁 재평가 쪽으로 무게를 옮긴다.')
S5 = '조선 판단(11월 2일)은 전날의 우위를 잃었다. 두산에너빌리티 판단(10월 29일)은 전날 넘었던 철회 기준 안으로 돌아왔다.'
HOLES = [
    (M12, M12.replace('언론은 하락을', '우리는 하락을').replace('우리는 AI', '언론은 AI')),
    (H12, H12.replace('16일 종가까지', '16일 종가부터')),
    (L13, L13.replace('16일 종가까지', '16일 종가부터')),
    (I13, I13.replace('약해지고', '철회되고')),
    (S5, '두산에너빌리티 판단(10월 29일)은 전날 넘었던 철회 기준 안으로 돌아왔다. 조선 판단(11월 2일)은 전날의 우위를 잃었다.'),
    ('고용은 개선이 뚜렷했고 물가는 완만한 둔화에 머물렀다. 달러는 보합이었다.',
     '고용은 개선이 완만했고 물가는 뚜렷한 둔화에 머물렀다. 달러는 보합이었다.'),
    ('한화오션은 3.83% 내려 코스피보다 0.83%포인트 약했다. 조선주가 같이 밀렸다.',
     '한화오션은 3.83% 내려 코스피보다 0.83%포인트 약했다. 조선주가 같이 밀렸다. 이 결과는 조선 판단을 뒷받침한다.'),
    (S5, '조선 판단(11월 2일)은 전날의 우위를 잃었다.'),
    ('같은 보도에 T-모바일도 내렸다. 통신주가 약했다.', '기지국 협상 소식에 T-모바일도 내렸다. 통신주가 약했다.'),
]


@pytest.mark.parametrize('before,after', HOLES)
def test_1013_holes_blocked(before, after):
    cand = flow.scan(page(before).decode())
    if not cand['items']:
        return            # 후보에서 빠졌다 — 작성자에게 넘어가지 않는다
    ok, why = one(before, after)
    assert not ok, '뚫렸다: %s' % after


# ---- 반영 결속


def run(pre, cand, edits, verdict='same', exclude=(), round_no=1):
    res = guard.build(pre, cand, edits, exclude=exclude)
    v = {'proposed_sha256': res['proposed_sha256'],
         'verdicts': {b['id']: {'verdict': verdict, 'why': 'x'} for b in res['bundles']}}
    return res, guard.decide(res, json.dumps(v), round_no)


def test_apply_same_splices_only_spans():
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    res, (status, _, _) = run(pre, cand, edits)
    assert status == 'applied'
    assert '올랐고' in res['proposed_written']
    assert P3 in res['proposed_written']


@pytest.mark.parametrize('verdict', ['changed', 'unsure', 'maybe', None])
def test_non_same_means_zero_on_single_bundle(verdict):
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    _, (status, _, _) = run(pre, cand, edits, verdict=verdict)
    assert status == 'zero'


@pytest.mark.parametrize('raw', ['', 'not json', '{"verdicts": []}', '[]'])
def test_broken_verdicts_zero(raw):
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    res = guard.build(pre, cand, edits)
    assert guard.decide(res, raw)[0] == 'zero'


def test_missing_bundle_id_is_unsure():
    pre, cand = setup(P1, P3, P2)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.',
             'C02': '나스닥은 1.2% 올랐고 반도체가 앞장섰다. 기술주 전반으로 매수세가 번지며 지수를 끌어올린 하루였다.'}
    res = guard.build(pre, cand, edits)
    assert len(res['bundles']) == 2       # 사이에 P3 — 다른 묶음
    v = {'proposed_sha256': res['proposed_sha256'], 'verdicts': {'B01': {'verdict': 'same'}}}
    status, exclude, per = guard.decide(res, v)
    assert status == 'recheck' and exclude == ['C02'] and per['B02'] == 'unsure'
    # 두 번째 판 — C02 를 빼고 다시 만든 판에서 전부 same 이면 반영
    res2, (status2, _, _) = run(pre, cand, edits, exclude=('C02',), round_no=2)
    assert status2 == 'applied' and len(res2['bundles']) == 1
    assert res2['proposed_sha256'] != res['proposed_sha256']
    # 두 번째도 아니면 편집 0
    _, (status3, _, _) = run(pre, cand, edits, verdict='changed', exclude=('C02',), round_no=2)
    assert status3 == 'zero'


def test_adjacent_edits_form_one_bundle():
    pre, cand = setup(P1, P2)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.',
             'C02': '나스닥은 1.2% 올랐고 반도체가 앞장섰다. 기술주 전반으로 매수세가 번지며 지수를 끌어올린 하루였다.'}
    res = guard.build(pre, cand, edits)
    assert [b['edits'] for b in res['bundles']] == [['C01', 'C02']]
    b = res['bundles'][0]
    assert b['title'] == '시장' and len(b['before']) == 2
    # 묶음 하나라도 same 이 아니면 묶음 전체 기각 → 단일 묶음이므로 편집 0
    assert guard.decide(res, {'proposed_sha256': res['proposed_sha256'],
                              'verdicts': {'B01': {'verdict': 'changed'}}})[0] == 'zero'


def test_context_uses_proposed_neighbours():
    pre, cand = setup(P1, P3, P2)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.',
             'C02': '나스닥은 1.2% 올랐고 반도체가 앞장섰다. 기술주 전반으로 매수세가 번지며 지수를 끌어올린 하루였다.'}
    res = guard.build(pre, cand, edits)
    assert res['bundles'][0]['next'] == P3
    assert res['bundles'][1]['prev'] == P3


def test_adjacent_swap_rejected():
    pre, cand = setup(P1, P2)
    res = guard.build(pre, cand, {'C01': P2, 'C02': P1})
    assert all(e['status'] == 'rejected' for e in res['edits'].values())
    assert res['bundles'] == []


def test_verdict_for_other_proposal_rejected():
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    res = guard.build(pre, cand, edits)
    v = {'proposed_sha256': 'f' * 64, 'verdicts': {'B01': {'verdict': 'same'}}}
    assert guard.decide(res, v)[0] == 'zero'
    v = {'proposed_sha256': res['proposed_sha256'], 'verdicts': {'B01': {'verdict': 'same'},
                                                                 'B09': {'verdict': 'same'}}}
    assert guard.decide(res, v)[0] == 'zero'


def test_candidates_from_other_version_fatal():
    pre, cand = setup(P1, P3)
    other = page(P1, P2)
    res = guard.build(other, cand, {'C01': P1})
    assert res['fatal']
    assert guard.decide(res, {})[0] == 'zero'


def test_span_hash_mismatch_fatal():
    pre, cand = setup(P1, P3)
    cand['items'][0]['inner_sha1'] = '0' * 40
    assert guard.build(pre, cand, {})['fatal']


def test_overlapping_spans_fatal():
    pre, cand = setup(P1, P2)
    cand['items'][1]['start'] = cand['items'][0]['start'] + 3
    assert guard.build(pre, cand, {})['fatal']


def test_duplicate_ids_fatal():
    pre, cand = setup(P1, P2)
    cand['items'][1]['id'] = 'C01'
    assert guard.build(pre, cand, {})['fatal']


def test_unknown_id_zeroes_everything():
    """모르는 id 가 하나라도 있으면 다른 편집도 버린다(codex 구현 검토 #6)."""
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.',
             'C99': 'x'}
    res = guard.build(pre, cand, edits)
    assert res['fatal'] and 'C99' in res['fatal'] and res['bundles'] == []
    assert guard.decide(res, {})[0] == 'zero'


def test_edits_must_be_object():
    pre, cand = setup(P1)
    with pytest.raises(guard.GuardError):
        guard.build(pre, cand, ['x'])


def test_tag_sequence_preserved_with_inline_tags():
    p = '유가가 <strong>2%</strong> 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'
    pre, cand = setup(p, P3)
    masked = cand['items'][0]['masked']
    after = masked.replace('올랐다. 금리가', '올랐고 금리가')
    res, (status, _, _) = run(pre, cand, {'C01': after})
    assert status == 'applied', res['edits']
    assert '<strong>2%</strong> 올랐고' in res['proposed_written']
    # 자리표 순서를 바꾸면 기각
    swapped = masked.replace('⟦0⟧', '⟦X⟧').replace('⟦1⟧', '⟦0⟧').replace('⟦X⟧', '⟦1⟧')
    res = guard.build(pre, cand, {'C01': swapped})
    assert res['edits']['C01']['status'] == 'rejected'


def test_write_stage_text_change_fatal():
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    res = guard.build(pre, cand, edits, write=lambda h: h.replace('금리', '채권 금리'))
    assert res['fatal'] and guard.decide(res, {})[0] == 'zero'


def test_write_stage_markup_is_bound():
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    w = lambda h: h.replace('<body>', '<body data-x="1">')   # noqa: E731
    a = guard.build(pre, cand, edits, write=w)
    b = guard.build(pre, cand, edits)
    assert a['proposed_written'].startswith('<html><body data-x="1">')
    assert a['proposed_sha256'] != b['proposed_sha256']


def test_real_write_stage_idempotent_on_real_post():
    import glob
    import os
    posts = sorted(glob.glob(os.path.join(os.path.dirname(guard.__file__), '..', '..', 'posts', '2026-1*.html')))
    if not posts:
        pytest.skip('발행본 없음')
    html = open(posts[-1], encoding='utf-8').read()
    w = guard.write_stage('us')
    assert w(w(html)) == w(html)


def test_unchanged_edit_not_applied():
    pre, cand = setup(P1, P3)
    res = guard.build(pre, cand, {'C01': P1})
    assert res['edits']['C01']['status'] == 'unchanged' and res['bundles'] == []


def test_verify_ignores_only_editor_note():
    from us.editor_note import apply_note, render_note
    approved = page(P1, P3).decode()
    approved = approved.replace('</div></body>', '</div><div data-editor-note-slot></div></body>')
    note = render_note('메모 한 줄.', '2026-11-06')
    with_note = apply_note(approved, note) if note else approved
    assert guard.same_published(approved, with_note)
    assert not guard.same_published(approved, with_note.replace('금리가', '채권이'))


def test_checker_input_has_no_original_ids_leak():
    pre, cand = setup(P1, P3)
    edits = {'C01': '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'}
    res = guard.build(pre, cand, edits)
    text = guard.checker_input(res)
    assert res['proposed_sha256'] in text and '[원문 1]' in text and 'C01' not in text


def test_locks_detect_order_swap():
    assert locks.locked(S5) != locks.locked(HOLES[4][1])
