"""한국어·일본어 원문 인용 대조 — 실제 원문(2026-11-26 한은 기자간담회 자막, 2026-11-02 공개 일본은행 총재 회견 기록,
공표문)에서 옮긴 인용으로 본다. 픽스처는 시험에 쓰는 단락만 담았다."""
import os

from common import cb_quote as CQ

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'cb')


def _read(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as fh:
        return fh.read()


KR = _read('bok_presser_1126_excerpt.txt')
JA = _read('boj_kaiken_1102_excerpt.txt')
STMT = _read('boj_stmt_1030_excerpt.txt')


def test_normalize_strips_every_space_and_folds_fullwidth():
    assert CQ.normalize_cjk('１．２５％ 程度') == '1.25%程度'
    assert CQ.normalize_cjk('국내경 제는 <b>성장</b>&nbsp;세') == '국내경제는성장세'


def test_kr_quote_copied_from_the_subtitle_passes():
    q = '그만큼 맞게 운영을 하기 때문에 물가가 그렇게 우리 목표치에서 크게 이탈하지 않고 내년에는 근원물가가 2.6% 정도로 관리될 것이다'
    assert CQ.verify_quote(q, KR, 'ko') is None


def test_kr_quote_with_one_changed_word_fails():
    q = '그만큼 맞게 운영을 하기 때문에 물가가 그렇게 우리 목표치에서 크게 이탈하지 않고 내년에는 근원물가가 2.8% 정도로 관리될 것이다'
    assert '원문에 없는 조각' in CQ.verify_quote(q, KR, 'ko')
    q = '저희는 실물경제의 어떤 가장 중요한 지표를 토대로 가끔 전망을 하기 때문에'
    assert '원문에 없는 조각' in CQ.verify_quote(q, KR, 'ko')


def test_kr_elision_that_hides_the_negation_fails():
    # 「이탈하지 않고」 의 「않고」 만 생략 표시로 지우면 앞뒤 조각은 둘 다 길고 원문 그대로다 — 뜻은 정반대
    q = '물가가 그렇게 우리 목표치에서 크게 이탈하지 […] 내년에는 근원물가가 2.6% 정도로 관리될 것이다'
    assert '생략 표시가 원문' in CQ.verify_quote(q, KR, 'ko')
    # 미국 칸과 같은 짧은 조각 규칙도 산다
    q = '우리가 통화정책을 적절히 […] 사용한다는 그런 가정이 있기 때문에 그렇습니다'
    assert '너무 짧은 조각' in CQ.verify_quote(q, KR, 'ko')


def test_kr_reversed_order_fails():
    q = ('내년에는 근원물가가 2.6% 정도로 관리될 것이다 이렇게 전망을 하고 있습니다 ... '
         '짧게 답변드리면 그것은 우리가 통화정책을 적절히 사용한다는 그런 가정이 있기 때문에 그렇습니다')
    assert '순서를 뒤집었다' in CQ.verify_quote(q, KR, 'ko')


def test_kr_legit_elision_inside_one_answer_passes():
    q = ('짧게 답변드리면 그것은 우리가 통화정책을 적절히 사용한다는 그런 가정이 있기 때문에 그렇습니다. … '
         '내년에는 근원물가가 2.6% 정도로 관리될 것이다 이렇게 전망을 하고 있습니다')
    assert CQ.verify_quote(q, KR, 'ko') is None


def test_kr_gap_overflow_joins_two_answers_and_fails():
    # 첫째 답변의 머리와 셋째 답변의 꼬리를 잇는다 — 사이에 다른 질문에 대한 답이 있다
    q = ('그 질문은 이렇게 답변드리겠습니다. 제가 아까 기자님께 국민소득에 대해서 답변드렸는데 […] '
         '가장 시의적절한 전망을 토대로 정책을 펴기 위해서는 자주 해야 된다')
    miss = CQ.verify_quote(q, KR, 'ko')
    assert miss and '떨어진 조각' in miss


def test_ja_quote_without_pdf_spaces_passes_and_spaced_form_too():
    q = '金融市場調節方針ですが、無担保コールレート・オーバーナイト物を1.25%程度で推移するよう促す、というこれまでの方針を維持することを賛成多数で決定しました。'
    assert CQ.verify_quote(q, JA, 'ja') is None
    assert CQ.verify_quote('無担保コールレート（オーバーナイト物）を、１．２５％程度で推移するよう促す。', STMT, 'ja') is None


def test_ja_changed_word_and_negation_elision_fail():
    q = '金融市場調節方針ですが、無担保コールレート・オーバーナイト物を1.5%程度で推移するよう促す、というこれまでの方針'
    assert '원문에 없는 조각' in CQ.verify_quote(q, JA, 'ja')
    q = '高田委員は、基調物価が「物価安定の目標」に達した中 ... 反対多数で否決されました'
    assert CQ.verify_quote(q, JA, 'ja') is None or '떨어진' not in CQ.verify_quote(q, JA, 'ja')


def test_ja_gap_is_tighter_than_ko():
    assert CQ.SEGMENT_GAP_MAX['ja'] < CQ.SEGMENT_GAP_MAX['ko']
    far = '総裁は' + 'あ' * 1000
    corpus = '今日の決定会合ですが金融市場調節方針を決定しました。' + far + '物価の見通しについてご説明します。'
    q = '今日の決定会合ですが金融市場調節方針を決定しました … 物価の見通しについてご説明します'
    assert '떨어진 조각' in CQ.verify_quote(q, corpus, 'ja')
    assert CQ.verify_quote(q, corpus, 'ko') is None


def test_too_many_elisions_fail():
    q = '짧게 답변드리면 그것은 우리가 […] 그런 가정이 있기 때문에 그렇습니다 […] 우리가 전망을 할 때 우리 통화정책을 […] 거기에 내포돼 있거든요'
    assert '생략이 3번' in CQ.verify_quote(q, KR, 'ko')


def test_source_numbers_take_unit_values_from_the_korean_text():
    nums = CQ.source_numbers('기준금리를 현재의 3.00%에서 3.25%로 0.25%p 인상, 국민소득 3,000조, 8,600억원, 2∼3%')
    assert {3.0, 3.25, 0.25, 3000.0, 8600.0, 2.0, 3.0} <= nums
    assert 2026.0 not in CQ.source_numbers('2026년 11월 26일')


def test_ja_source_text_maps_oku_and_cho():
    assert CQ.ja_source_text('年間２兆 4,600億円') == '年間2조 4,600억円'
