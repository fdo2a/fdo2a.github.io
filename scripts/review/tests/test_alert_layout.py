"""발행 건별 알림의 배치(2026-11-19 사용자 결정) — 「발행 상태 / 볼 것 / 검증 범위」 세 덩어리.

막는 것: 정상 칸을 줄줄이 나열, 검사기 내부 이름·작성 지시문을 그대로 싣기, 경고 문장 중간 자르기,
권고와 참고를 같은 무게로 세기, 오늘의 경고와 상시 검증 한계를 한 묶음으로 두기, 고정 숫자 문구.
판정·지문은 그대로다 — 문구만 바뀐다.
"""
import copy
import json
import os

import pytest

from review import prepub_view as V
from review.tests import prepub_fixture as F
from verification import record as R

KR_DATE = '2026-11-18'
# 11/18 KR 실제 기록(verification/kr/2026-11-18.json)의 경고 두 검사기 모양 그대로
WEIGHT_ITEMS = ['분량: 본문 7101자 · 뉴스 요약 0자 · 전체 7101자 (공백 제외)',
                '경고: 서술형 본문이 7101자다(평상시 4,000~5,000자) — 큰 사건이 있는 날이 아니면 반복 해석·장중 시각·'
                '변화 없는 판단부터 덜어낸다. 중요한 분석은 지우지 않는다',
                '경고: 시황군 1619자 < 판단군 1878자 — 중요한 분석이 몰린 날이 아니면 주요 자산의 움직임·큰 변동의 원인·'
                '자산 간 연결이 빠졌는지 점검한다(비율을 맞추려고 시황을 덧붙이지 않는다)',
                'OK — 무게중심 게이트 통과 (발표일)']
STYLE_ITEMS = ['경고 1건(발행은 막지 않는다) — <html>',
               '· 날수를 고유어로 썼다 — 「이틀」, 「이틀」, 「이틀」 — 다시 읽어 보고, 자연스러우면 그대로 둔다']
NUMBERS = {'table_cells': 55, 'prose_judged': 0, 'unverified': 250,
           'unverified_by': {'KR 문장': 159, 'KR 업종 멀티기간': 78, 'KR 표(지도 밖)': 13}}


@pytest.fixture()
def kr_repo(tmp_path, monkeypatch):
    cfg = copy.deepcopy(F.CONFIG)
    cfg['markets']['kr']['gates'] = [{'name': n, 'script': 'scripts/g1.py'} for n in
                                     ('unconfirmed', 'check_session', 'check_weight', 'check_kr_stance', 'check_movers',
                                      'check_telegram', 'check_fund', 'check_research', 'check_style',
                                      'check_readability')] + [{'name': 'check_numbers', 'script': 'scripts/g2.py'}]
    monkeypatch.setattr(F, 'CONFIG', cfg)
    repo = F.init(tmp_path)
    F.write(repo, 'config/prepub_gates.json', json.dumps(cfg))
    F.commit(repo, 'kr gates')
    return repo


def _rewrite(repo, fn, market='kr', date=KR_DATE):
    p = os.path.join(str(repo), R.record_path(market, date))
    rec = json.load(open(p, encoding='utf-8'))
    fn(rec)
    F.write(repo, R.record_path(market, date), json.dumps(rec, ensure_ascii=False))
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')


def _warn(rec, name, items):
    g = next(g for g in rec['gates'] if g['name'] == name)
    g.update(status='warn', items=items)
    rec['summary']['warned'].append(name)
    rec['summary']['status'] = 'pass_with_warnings'


def _nov18(repo, numbers=NUMBERS, weight=WEIGHT_ITEMS, style=STYLE_ITEMS):
    F.publish(repo, 'kr', KR_DATE, workspace=False, numbers=numbers)

    def fn(rec):
        if weight:
            _warn(rec, 'check_weight', weight)
        if style:
            _warn(rec, 'check_style', style)
    _rewrite(repo, fn)
    return V.view(str(repo), 'HEAD', 'kr', KR_DATE)


def test_nov18_kr_matches_the_agreed_layout(kr_repo):
    text = V.render_publish(_nov18(kr_repo), who=V.GITHUB)
    lines = text.split('\n')
    assert lines[0] == '[발행] KR 일간 11/18 · 발행 통과 · 검토 1건 · 참고 1건'      # 미리보기는 첫 줄만 보인다
    assert '■ 발행 상태' in lines and '■ 볼 것' in lines and '■ 검증 범위' in lines
    assert lines.index('■ 발행 상태') < lines.index('■ 볼 것') < lines.index('■ 검증 범위')
    assert '필수 검사 11/11 기록상 통과 · 발행본과 검사 기록 일치(GitHub 대조)' in text
    assert ('1. [검토 권고] 본문 7,101자(평소 4,000~5,000자), 시황 1,619자 < 판단 1,878자. '
            '반복된 해석부터 덜고, 주요 시장 움직임·원인 설명이 빠졌는지 확인') in text
    assert '2. [참고] 「이틀」 3회. 자연스러우면 수정 불필요' in text
    assert ('표 55칸 자동 대조 · 숫자 250개 범위 밖(문장 159 · 업종 기간별 78 · 기타 표 13). '
            '오류 250건이라는 뜻은 아님') in text
    assert text.endswith('※ GitHub은 기록 일치만 확인. 검사 재실행이나 전체 내용의 사실 검증은 아님')


def test_internal_words_stay_out(kr_repo):
    text = V.render_publish(_nov18(kr_repo), who=V.GITHUB)
    for word in ('check_weight', 'check_style', '루틴 파이썬', '지도 밖', 'KR 업종 멀티기간', '글 지문', '검사기 목록',
                 '덜어낸다', '점검한다', '…', '판정 통과(경고 있음)', '시황군', '판단군'):
        assert word not in text, word


def test_numbers_come_from_the_record_not_fixed_text(kr_repo):
    nums = {'table_cells': 31, 'prose_judged': 0, 'unverified': 7, 'unverified_by': {'KR 문장': 7}}
    text = V.render_publish(_nov18(kr_repo, numbers=nums, style=None))
    assert '표 31칸 자동 대조 · 숫자 7개 범위 밖(문장 7). 오류 7건이라는 뜻은 아님' in text
    assert '55' not in text and '250' not in text
    assert text.split('\n')[0].endswith('· 발행 통과 · 검토 1건')                       # 없는 갈래는 세지 않는다


def test_no_warnings_folds_the_look_block(kr_repo):
    text = V.render_publish(_nov18(kr_repo, weight=None, style=None))
    assert text.split('\n')[0] == '[발행] KR 일간 11/18 · 발행 통과'
    assert '■ 볼 것' not in text and '■ 검증 범위' in text                         # 범위는 매일 보인다
    assert text.endswith('※ 맥은 기록 일치만 확인. 검사 재실행이나 전체 내용의 사실 검증은 아님')


@pytest.mark.parametrize('items,want', [
    (['경고: 서술형 본문이 7101자다(평상시 4,000~5,000자) — 큰 사건이…'],
     '본문 7,101자(평소 4,000~5,000자). 반복 해석·장중 시각·변화 없는 판단부터 덜기(중요한 분석은 유지)'),
    (['경고: 시황군 1619자 < 판단군 1878자 — 중요한…'],
     '시황 1,619자 < 판단 1,878자. 주요 시장 움직임·원인 설명이 빠졌는지 확인(비율을 맞추려고 시황을 덧붙이지 않기)'),
    (['경고: 서술형 본문이 6200자다(평상시 4,000~5,000자, 뉴스 요약 900자 별도) — x'],
     '본문 6,200자(평소 4,000~5,000자, 뉴스 요약 900자 별도)'),
    (['경고: 매크로가 2600자로 평소 상한 2,000자를 넘는다 — 발표가 몰린 날이면 괜찮다.'],
     '매크로 2,600자(평소 상한 2,000자). 발표가 몰린 날이 아니면 반복 해석부터 덜기'),
])
def test_weight_variants_keep_numbers_and_direction(kr_repo, items, want):
    text = V.render_publish(_nov18(kr_repo, weight=items, style=None))
    assert want in text


def test_unknown_weight_sentence_falls_back_whole(kr_repo):
    odd = '경고: 처음 보는 분량 경고다. 둘째 문장이 있다'
    text = V.render_publish(_nov18(kr_repo, weight=[odd], style=None))
    assert '[검토 권고] 분량: 처음 보는 분량 경고다. 둘째 문장이 있다' in text


def test_style_day_word_count_and_cap(kr_repo):
    four = ['· 날수를 고유어로 썼다 — 「이틀」, 「사흘」, 「이틀」, 「나흘」 — 다시 읽어 보고, 자연스러우면 그대로 둔다']
    text = V.render_publish(_nov18(kr_repo, weight=None, style=four))
    # 검사기는 앞 4개까지만 적는다 — 넷이 찍혔으면 그 이상일 수 있다
    assert '[참고] 「이틀」 2회 · 「사흘」 1회 · 「나흘」 1회(4회 이상일 수 있음). 자연스러우면 수정 불필요' in text


def test_other_style_hint_is_note_not_review(kr_repo):
    text = V.render_publish(_nov18(kr_repo, weight=None, style=['경고 1건 — <html>', '· 문단이 길다 — 다시 읽어 본다']))
    assert '1. [참고] 문체: 문단이 길다 — 다시 읽어 본다' in text and '검토 1건' not in text


def test_long_fallback_reason_is_cut_at_a_sentence(kr_repo):
    long = '경고: ' + '첫 문장이다. ' + '가' * 300
    text = V.render_publish(_nov18(kr_repo, weight=[long], style=None))
    line = next(x for x in text.split('\n') if '[검토 권고]' in x)
    assert line.endswith('첫 문장이다. (이하 기록 파일)')


def test_required_failure_is_check_needed(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        g = next(g for g in rec['gates'] if g['name'] == 'check_fund')
        g.update(status='fail', items=['위반: 펀드 블록 표가 없다'])
        rec['summary'].update(blocking=['check_fund'], publish_ok=False, status='fail', verified=False)
    _rewrite(kr_repo, fn)
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    head = text.split('\n')[0]
    assert head == '[발행] KR 일간 11/18 · 확인 필요 · 확인 1건'
    assert '필수 검사 10/11 기록상 통과 · 기록상 발행 불가' in text
    assert '1. [확인 필요] 펀드 실패 — 위반: 펀드 블록 표가 없다' in text


def test_gaps_go_to_scope_not_look(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS,
              summ=F.summary(verified=False, not_run=['check_research']), gate_status={'check_research': 'not_run'})
    _rewrite(kr_repo, lambda rec: next(g for g in rec['gates'] if g['name'] == 'check_research').update(
        reason='적용일 전 글이라 검사하지 않았다'))
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    scope = text.split('■ 검증 범위')[1]
    assert '실행 안 함: 리서치 — 적용일 전 글이라 검사하지 않았다' in scope
    assert '■ 볼 것' not in text and text.split('\n')[0] == '[발행] KR 일간 11/18 · 발행 통과 · 검사 빈칸 1건'


def test_us_workspace_inputs_are_scope(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, numbers={'table_cells': 40, 'prose_judged': 12, 'unverified': 0, 'unverified_by': {}})
    text = V.render_publish(V.view(str(repo), 'HEAD', 'us', '2026-11-09'), who=V.GITHUB)
    assert '발행본과 검사 기록 일치(GitHub 대조, 작업 공간 입력 제외)' in text
    scope = text.split('■ 검증 범위')[1]
    assert '표 40칸·문장 12개 자동 대조 · 범위 밖 숫자 없음' in scope
    assert '작업 공간 전용 입력 1개는 원본을 보관하지 않아 대조 못 함(지문만 남음): macro_next.json' in scope
    assert text.split('\n')[0] == '[발행] US 일간 11/09 · 발행 통과'


def test_mismatch_expands_the_failed_category(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.write(repo, 'posts/2026-11-09.html', '<p>바꿔치기</p>')
    F.git(repo, 'add', '-A')
    F.git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--amend', '--no-edit')
    text = V.render_publish(V.view(str(repo), 'HEAD', 'us', '2026-11-09'))
    assert text.split('\n')[0].startswith('[발행] US 일간 11/09 · 확인 필요')
    assert '발행본과 검사 기록 불일치(맥 대조)' in text
    assert ' · 글 지문: 불일치' in text                                      # 어긋난 칸만 이름과 함께 펼친다


def test_display_names_cover_every_unverified_kind():
    assert set(V.UNVERIFIED_SHOWN) == set(V.UNVERIFIED_KINDS)
    assert V.UNVERIFIED_SHOWN['KR 표(지도 밖)'] == '기타 표'


def test_digest_uses_display_names(kr_repo):
    lines = '\n'.join(V.digest_lines(_nov18(kr_repo)))
    assert '문장 159 · 업종 기간별 78 · 기타 표 13' in lines and '지도 밖' not in lines


def test_layout_does_not_touch_judgments(kr_repo):
    v = _nov18(kr_repo)
    assert V.clean(v) and not V.fully_verified(v)
    assert json.loads(V.fingerprint(v))[4] == 'pass_with_warnings'


def test_gaps_show_on_the_first_line(kr_repo):
    # 휴대폰 미리보기는 첫 줄만 보인다 — 돌지 않은 검사가 문체 힌트보다 덜 보이면 안 된다(advisor 11/19)
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS,
              summ=F.summary(verified=False, not_run=['check_research'], status='pass_with_gaps'),
              gate_status={'check_research': 'not_run', 'check_fund': 'partial'})
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert text.split('\n')[0] == '[발행] KR 일간 11/18 · 발행 통과 · 검사 빈칸 2건'
    assert ' · 일부만 검사: 펀드 — 이유가 기록에 없어요' in text


def test_not_verified_without_listed_gap_is_still_counted(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS, summ=F.summary(verified=False))
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert text.split('\n')[0].endswith('· 검사 빈칸 1건')
    assert ' · 설정된 검사 완료 아님(이유가 기록에 없어요)' in text


def test_correction_line_is_plain(kr_repo):
    v = _nov18(kr_repo)
    v['corrections'] = {'typeset': 0, 'other': 1, 'unknown': 0}
    text = V.render_publish(v)
    assert ' · 발행 뒤 수정 1회(조판 0회 · 조판 외 1회 · 판별 못 함 0회) — 위 검사는 기록을 처음 담은 판 기준' in text
    assert '몫' not in text and '그 뒤' not in text
    assert any(x.startswith('   - 발행 뒤 수정 1회') for x in V.digest_lines(v))


def test_overflow_drops_gap_reasons_before_check_items(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        for g in rec['gates']:
            if g['name'] in ('check_fund', 'check_movers', 'check_telegram'):
                g.update(status='fail', items=['위반: ' + '나' * 150 + '. ' + '다' * 150])
            elif g['name'] != 'check_numbers':
                g.update(status='not_run', reason='라' * 150 + '. ' + '마' * 150)
        rec['summary'].update(blocking=['check_fund', 'check_movers', 'check_telegram'], publish_ok=False,
                              status='fail', verified=False,
                              not_run=[g['name'] for g in rec['gates'] if g['status'] == 'not_run'])
        rec['inputs']['files'] += [{'path': f'<datadir>/{"n" * 55}{i}.json', 'sha256': 'x', 'ref': 'workspace-only'}
                                   for i in range(8)]
    _rewrite(kr_repo, fn)
    v = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)
    full = V.render_publish(v)
    assert len(full) <= V.TEXT_LIMIT
    assert full.count('[확인 필요]') == 3                         # 실패 셋은 남는다
    assert '표 55칸 자동 대조' in full and full.endswith(V.FOOTER)


# ── codex 구현 검토 1회 지적의 재현 ─────────────────────────────────────────

def _gate(rec, name, **kw):
    g = next(g for g in rec['gates'] if g['name'] == name)
    g.update(kw)
    return g


def test_note_allowed_and_indeterminate_keep_their_own_state(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_numbers', status='fail', items=['위반: 표 칸이 다르다'])
        _gate(rec, 'check_style', status='fail', items=['위반: 형식'])
        _gate(rec, 'check_fund', status='indeterminate', reason='입력을 읽지 못했다')
        rec['summary'].update(note_numbers=['check_numbers'], note_format=['check_style'], blocking=['check_fund'],
                              publish_ok=False, status='fail', verified=False)
    _rewrite(kr_repo, fn)
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert '[확인 필요] 펀드 판정 불가 — 입력을 읽지 못했다' in text
    assert '[검토 권고] 숫자 대조 실패(노트로 숫자 실패 허용) — 위반: 표 칸이 다르다' in text
    assert '[참고] 문체 실패(노트로 형식 실패 허용) — 위반: 형식' in text
    assert '펀드 실패' not in text and '숫자 대조 실패 —' not in text


def test_integrity_survives_many_failures_and_marker_is_not_a_checker(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)
    names = ['unconfirmed', 'check_session', 'check_weight', 'check_kr_stance', 'check_movers', 'check_telegram',
             'check_fund', 'check_research', 'check_readability']

    def fn(rec):
        for n in names:
            _gate(rec, n, status='fail', items=['위반: 짧다'])
        rec['summary'].update(blocking=names + ['integrity'], integrity=['검사 중에 원본 글이 바뀌었다 — 다시'],
                              publish_ok=False, status='fail', verified=False)
    _rewrite(kr_repo, fn)
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert '1. [확인 필요] 무결성 경보: 검사 중에 원본 글이 바뀌었다 — 다시' in text
    assert 'integrity 실패' not in text and text.count('[확인 필요]') == 10 and '외 ' not in text


def test_failure_reason_is_the_violation_not_the_info_line(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_weight', status='fail',
              items=['분량: 본문 7101자', '경고: 서술형 본문이 7101자다', '섹션 「매크로」를 찾지 못했다'])
        rec['summary'].update(blocking=['check_weight'], publish_ok=False, status='fail', verified=False)
    _rewrite(kr_repo, fn)
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert '[확인 필요] 분량 실패 — 섹션 「매크로」를 찾지 못했다' in text and '분량: 본문' not in text


def test_corrupt_table_cells_are_not_echoed(kr_repo):
    nums = dict(NUMBERS, table_cells='55칸 조작\n임의 문구', unverified=0, unverified_by={})
    v = _nov18(kr_repo, numbers=nums, weight=None, style=None)
    text, digest = V.render_publish(v), '\n'.join(V.digest_lines(v))
    assert '표 대조 칸 수 모름 자동 대조 · 범위 밖 숫자 없음' in text
    assert '조작' not in text + digest and '표 대조 칸 수 모름' in digest


def test_long_reason_without_sentence_end_is_cut_between_words():
    x = ' '.join(['낱말이다'] * 60)
    out = V._show(x)
    assert out.endswith('낱말이다 (이하 기록 파일)') and len(out) <= V.SHOW_LEN + 12


def test_real_overflow_drops_gap_reasons_then_note_items(kr_repo, monkeypatch):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS,
              gate_status={'check_research': 'not_run', 'check_movers': 'partial'})

    def fn(rec):
        _gate(rec, 'check_research', reason='가 ' * 70)
        _gate(rec, 'check_movers', reason='나 ' * 70)
        _gate(rec, 'check_fund', status='fail', items=['위반: 펀드 표가 없다'])
        rec['summary'].update(blocking=['check_fund'], publish_ok=False, status='fail', verified=False)
        _warn(rec, 'check_style', STYLE_ITEMS)
        _warn(rec, 'check_weight', WEIGHT_ITEMS)
    _rewrite(kr_repo, fn)
    v = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)
    full = V.render_publish(v)
    monkeypatch.setattr(V, 'TEXT_LIMIT', len(full) - 50)       # 실제로 넘치게
    text = V.render_publish(v)
    assert V._size(text) <= V.TEXT_LIMIT
    assert '검사 빈칸의 이유는 길이 제한으로 뺐어요' in text and ' · 실행 안 함: 리서치' in text and '가 가' not in text
    assert '[확인 필요] 펀드 실패' in text and '표 55칸 자동 대조' in text and text.endswith(V.FOOTER)
    monkeypatch.setattr(V, 'TEXT_LIMIT', V._size(text) - 40)
    text2 = V.render_publish(v)
    assert '[참고]' not in text2 and '[확인 필요] 펀드 실패' in text2 and '길이 제한으로 줄였어요' in text2


def test_reference_failure_is_not_a_gap(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    _rewrite(repo, lambda rec: (rec['gates'][0].update(status='fail', required=False, items=['위반: 색']),
                                rec['summary'].update(verified=False)), market='us', date='2026-11-09')
    text = V.render_publish(V.view(str(repo), 'HEAD', 'us', '2026-11-09'))
    assert '[검토 권고]' in text and '실패(참고 검사)' in text and '검사 빈칸' not in text


def test_unknown_status_and_missing_parts_say_check_needed(kr_repo):
    v = _nov18(kr_repo, weight=None, style=None)
    v2 = dict(v, recorded=dict(v['recorded'], status='unexpected'))
    assert V.render_publish(v2).split('\n')[0] == '[발행] KR 일간 11/18 · 확인 필요'
    v3 = dict(v, recorded=None, check=None, same_commit=None)
    text = V.render_publish(v3)
    assert '기록 요약이 없어요' in text and '대조하지 못했어요' in text and '같은 커밋에 들어갔는지 확인 불가' in text


def test_size_counts_utf16_units(kr_repo, monkeypatch):
    v = _nov18(kr_repo, weight=['경고: ' + '😀 ' * 150 + '.'] * 3, style=None)
    monkeypatch.setattr(V, 'TEXT_LIMIT', 600)
    text = V.render_publish(v)
    assert len(text.encode('utf-16-le')) // 2 <= 600


# ── codex 구현 검토 2회 지적의 재현 ─────────────────────────────────────────

import random
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BAD_HTML = ('<html><body data-register="da"><section><p>오늘 코스피는 외국인 순매수에 힘입어 1.2% 올랐고 반도체가 지수를 '
            '끌어올린 하루였습니다.</p><p>국채 급등이 이어졌다. 원장 회차를 확인했다. 금리는 3.45%로 내렸고 달러는 약세였다.</p>'
            '<p>지수는 이틀 연속 올랐다. 과연 이 흐름은 이어질 것인가?</p></section></body></html>')


def _real_items(tmp_path, *argv):
    """검사기를 실제로 돌려 기록이 남기는 모양(R.items_of) 그대로 — 손으로 쓴 items 는 머리·통계 줄을 빠뜨린다."""
    html = tmp_path / 'bad.html'
    html.write_text(BAD_HTML, encoding='utf-8')
    out = subprocess.run([sys.executable, *argv, str(html)], capture_output=True, text=True, cwd=SCRIPTS)
    assert out.returncode == 1
    return R.items_of(out.stdout + '\n' + out.stderr, {'html': str(html)})


def _fail(repo, name, items):
    F.publish(repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, name, status='fail', items=items)
        rec['summary'].update(blocking=[name], publish_ok=False, status='fail', verified=False)
    _rewrite(repo, fn)
    return V.render_publish(V.view(str(repo), 'HEAD', 'kr', KR_DATE))


def test_readability_failure_shows_the_fail_line_not_header_or_stats(kr_repo, tmp_path):
    items = _real_items(tmp_path, 'check_readability.py', '--strict')
    assert items[0].startswith('== ') and any(x.startswith('문장 ') for x in items)      # 기록에는 머리·통계가 앞에 있다
    text = _fail(kr_repo, 'check_readability', items)
    line = next(x for x in text.split('\n') if '[확인 필요] 가독성 실패' in x)
    assert line.endswith('가독성 실패 — 조판 오버라이드 미적용 — apply_readability.py를 돌릴 것')
    assert '== ' not in text and '중앙' not in text and 'repair' not in text and '세는 대상' not in text


def test_style_failure_shows_both_violations_and_counts_no_hint(kr_repo, tmp_path):
    items = _real_items(tmp_path, 'check_style.py')
    assert items[0].startswith('고칠 것 2건') and any(x.startswith('· ') for x in items)
    text = _fail(kr_repo, 'check_style', items)
    line = next(x for x in text.split('\n') if '문체 실패' in x)
    assert '독자 문장에 작업 어휘가 있다 — 원장' in line and '「국채 급등」은 국채 가격이 움직였다로 읽힌다' in line
    assert '고칠 것' not in line and '(외 ' not in line and '날수를' not in line          # 힌트는 생략 건수에 섞이지 않는다


@pytest.mark.parametrize('items', [
    ['== <html>', '문장 6 · 중앙 17자 · P90 24자', 'note 문장당 수치가 많다'],
    ['고칠 것 1건 — <html>'],
])
def test_failure_with_only_headers_says_reason_missing(kr_repo, items):
    text = _fail(kr_repo, 'check_readability', items)
    assert '[확인 필요] 가독성 실패 — 이유가 기록에 없어요' in text


def test_strict_warn_only_failure_still_shows_the_warn_line(kr_repo):
    text = _fail(kr_repo, 'check_readability', ['== <html>', '문장 6 · 중앙 17자', 'warn 표가 .tbl-scroll 밖에 있다'])
    assert '가독성 실패 — warn 표가 .tbl-scroll 밖에 있다' in text


def test_mismatch_reason_is_not_hidden_by_an_unknown_reason(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_session', argv='invalid')                # 대조 불가 — 문장에 「다르다」가 들어 있다
        _gate(rec, 'check_fund', script_sha256='0' * 64)           # 실제 불일치
    _rewrite(kr_repo, fn)
    v = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)
    assert v['check']['cats']['scripts'] == '불일치' and len(v['check']['cat_why']['scripts']) == 2
    text = V.render_publish(v)
    assert ' · 검사 코드: 불일치 — 검사 코드가 기록과 다르다 — 펀드 (외 1건)' in text


def test_category_detail_mirrors_cat_why(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_session', argv='invalid')
        _gate(rec, 'check_fund', script_sha256='0' * 64)
        rec['post']['sha256'] = '0' * 64
    _rewrite(kr_repo, fn)
    chk = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)['check']
    assert {k: [d['text'] for d in ds] for k, ds in chk['cat_detail'].items()} == chk['cat_why']
    assert [d['state'] for d in chk['cat_detail']['scripts']] == ['대조 불가', '불일치']
    assert chk['cat_detail']['post'][0]['state'] == '불일치'


def test_label_goes_only_in_the_checker_name_slot(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)
    _rewrite(kr_repo, lambda rec: _gate(rec, 'check_weight', argv=['scripts/test-data/check_weight.py']))
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert '그 커밋에 검사 코드 파일이 없다 — 분량(scripts/test-data/check_weight.py)' in text
    assert '분량.py' not in text
    assert V._name_slot('입력 참조 종류를 모른다 — repo:scripts/check_weight.py') == '입력 참조 종류를 모른다 — repo:scripts/check_weight.py'
    assert V._name_slot('기록에 실행 정보가 없다 — check_fund') == '기록에 실행 정보가 없다 — 펀드'


def _many_gaps(kr_repo, n, width=45):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_fund', status='fail', items=['위반: 펀드 블록 표가 없다'])
        rec['summary'].update(blocking=['check_fund'], publish_ok=False, status='fail', verified=False)
    _rewrite(kr_repo, fn)
    v = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)
    names = [f'check_{"x" * width}_{i}' for i in range(n)]
    v['recorded']['not_run'] = names[::2]
    v['recorded']['partial'] = names[1::2]
    v['recorded']['reasons'].update({nm: ['가나다 ' * 20] for nm in names})
    return v


@pytest.mark.parametrize('n', [90, 400, 3000])
def test_very_long_gap_list_keeps_failure_reason_scope_and_footer(kr_repo, n, monkeypatch):
    v = _many_gaps(kr_repo, n)
    fit = V._fit
    monkeypatch.setattr(V, '_fit', lambda lines, foot, limit: fit(lines, foot, 10 ** 9))   # 마지막 안전망에 기대지 않는다
    text = V.render_publish(v)
    assert V._size(text) <= V.TEXT_LIMIT
    assert '1. [확인 필요] 펀드 실패 — 위반: 펀드 블록 표가 없다' in text
    assert '표 55칸 자동 대조' in text and text.endswith(V.FOOTER)
    assert f' · 검사 빈칸 {n}건(실행 안 함 {n // 2}건 · 일부만 검사 {n // 2}건)' in text
    assert text.split('\n')[0].endswith(f'· 확인 1건 · 검사 빈칸 {n}건')
    if n == 90:
        assert ': check_xxx' in text and '(외 85건)' in text          # 이름은 앞 몇 개 + 건수
    assert '길이 제한으로 줄였어요' in text


def test_gap_ladder_steps_down_one_rung_at_a_time(kr_repo, monkeypatch):
    v = _many_gaps(kr_repo, 6, width=10)
    sizes = [V._size('\n'.join(V.scope_lines(v, b))) for b in (V.FULL, V.BRIEF, V.NAMES, V.COUNT)]
    assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == 4
    full = V.render_publish(v)
    assert ' · 실행 안 함: check_xxxxxxxxxx_0 — 가나다' in full and '길이 제한' not in full
    monkeypatch.setattr(V, 'TEXT_LIMIT', V._size(full) - 10)
    assert '검사 빈칸의 이유는 길이 제한으로 뺐어요' in V.render_publish(v)


def _views(kr_repo):
    v = _nov18(kr_repo, weight=None, style=None)
    assert V.render_publish(v).split('\n')[0] == '[발행] KR 일간 11/18 · 발행 통과'
    chk = v['check']
    yield dict(v, check=None)
    yield dict(v, check={})
    yield dict(v, recorded=None)
    yield dict(v, same_commit=False)
    yield dict(v, same_commit=None)
    yield dict(v, recorded={'readable': False, 'unreadable_why': 'x'})
    yield dict(v, recorded=dict(v['recorded'], publish_ok=False))
    yield dict(v, recorded=dict(v['recorded'], status='unexpected'))
    yield dict(v, recorded=dict(v['recorded'], status='fail'))             # 요약만 실패라고 하는 어긋난 기록
    yield dict(v, recorded=dict(v['recorded'], status='indeterminate'))
    for k in chk['cats']:
        for st in ('불일치', '대조 불가'):
            cats = dict(chk['cats'], **{k: st})
            yield dict(v, check=dict(chk, cats=cats, overall=V.C.overall(cats),
                                     unknown=[c for c, s in cats.items() if s == '대조 불가']))
    yield dict(v, check=dict(chk, overall=V.C.UNKNOWN, cats={'record': '대조 불가'}, unknown=['record']))
    yield dict(v, kind=V.NO_RECORD, check=None, recorded=None)
    yield dict(v, kind=V.AMBIGUOUS, check=None, recorded=None, why=['글을 추가한 커밋이 2개'])


def test_check_none_alone_is_not_headed_passed(kr_repo):
    v = _nov18(kr_repo, weight=None, style=None)
    for bad in (None, {}):
        text = V.render_publish(dict(v, check=bad))
        assert text.split('\n')[0] == '[발행] KR 일간 11/18 · 확인 필요' and '대조하지 못했어요' in text
    assert V.anomalies(dict(v, check=None)) == V.anomalies(v) and V.fingerprint(dict(v, check={})) == V.fingerprint(dict(v, check=None))


def test_head_never_says_passed_when_status_block_reports_a_problem(kr_repo):
    words = ('못했어요', '없어요', '불일치', '대조 불가', '발행 불가', '확인 불가', '달라요', '판정 불가', '모르는 판정', '기록 없음', '기록 판정')
    seen = 0
    for v in _views(kr_repo):
        text = V.render_publish(v)
        status = text.split('■ 발행 상태')[1].split('■')[0]
        if any(w in status for w in words):
            seen += 1
            assert '· 확인 필요' in text.split('\n')[0], status
    assert seen >= 22


def test_show_never_cuts_at_the_status_cause_separator():
    x = '필수 입력이 없어 검사하지 못했다 — ' + '텔레그램 입력 자료가 준비되지 않아 인용을 대조하지 못했다 ' * 6
    out = V._show(x)
    assert out.startswith('필수 입력이 없어 검사하지 못했다 — 텔레그램 입력 자료가 준비되지 않아') and out.endswith(V.MORE)
    y = '첫 문장이다. 상태다 — ' + '원인을 길게 적는다 ' * 20
    assert V._show(y).startswith('첫 문장이다. 상태다 — 원인을 길게')              # 구분자 앞의 문장 끝에서도 끊지 않는다


def test_show_marks_an_overlong_token_instead_of_slicing_it():
    assert V._show('가' * 170) == V.OMIT
    assert V._show('상태다 — ' + '가' * 170 + ' 뒤 낱말') == '상태다 — ' + V.OMIT
    assert V._show('짧은 낱말 ' + '가' * 170) == '짧은 낱말' + V.MORE


def _prefix_ok(part, whole):
    """part 가 whole 의 앞부분이고 낱말 경계에서 끝나는가(꼬리 쉼표는 떼어도 된다)."""
    return bool(part) and whole.startswith(part) and (len(part) == len(whole) or whole[len(part)] in ' ,')


def test_show_output_is_always_a_token_boundary_prefix():
    rnd = random.Random(7)
    pieces = ['가나다', '검사하지', '못했다', '—', 'check_x.py', '낱말이다.', '원인;', '쉼표,', '가' * 50, '😀' * 30, '나' * 200]
    kept = 0
    for _ in range(4000):
        x = ' '.join(rnd.choice(pieces) for _ in range(rnd.randint(1, 40)))
        for n in (40, 120, V.SHOW_LEN):
            out = V._show(x, n)
            if out == x:
                assert len(x) <= n
                continue
            assert '…' not in out and len(out) <= n + len(' (중략)') + len(V.OMIT) + 3, (x, out)
            sep = x.find(' — ')
            if sep <= 0:                                               # 구분자 없는 한 문장
                assert out == V.OMIT or (out.endswith(V.MORE) and _prefix_ok(out[:-len(V.MORE)], x)), (x, out)
                continue
            status, cause = x[:sep], x[sep + 3:]
            gone = '(앞부분 생략) — '
            left, _, right = out.partition(' — ') if not out.startswith(gone) else ('(앞부분 생략)', '', out[len(gone):])
            assert left == status or left == '(앞부분 생략)' or (
                left.endswith(' (중략)') and _prefix_ok(left[:-len(' (중략)')], status)), (x, out)
            # 원인은 줄표가 어디에 있든 남는다 — 첫 낱말이 예산(절반)보다 길 때만 통째로 생략 표시
            if right == V.OMIT:
                assert len(cause.split(' ')[0].rstrip(',')) > n // 2 or cause.startswith('— '), (x, out)
            else:
                kept += 1
                assert right == cause or (right.endswith(V.MORE) and _prefix_ok(right[:-len(V.MORE)], cause)), (x, out)
    assert kept > 1000


def test_show_keeps_the_cause_when_the_separator_is_beyond_the_limit():
    x = '확인할 대상을 설명한다. ' * 12 + '— 명시적인 실패 원인'
    assert x.find(' — ') >= V.SHOW_LEN
    out = V._show(x)
    assert out.endswith('(중략) — 명시적인 실패 원인') and out.startswith('확인할 대상을 설명한다. 확인할')
    for at in (V.SHOW_LEN - 4, V.SHOW_LEN - 3, V.SHOW_LEN, V.SHOW_LEN + 1, 400):      # 줄표가 상한 바로 앞·같은 자리·뒤
        status = ('낱말 ' * 200)[:at].rstrip()
        out = V._show(status + ' — 원인은 이것이다 ' + '그리고 더 길게 ' * 30)
        assert ' — 원인은 이것이다' in out and '(중략)' in out, out


def test_suffixed_name_is_one_item_with_the_label(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_weight', status='fail', items=['섹션 「매크로」를 찾지 못했다'])
        _gate(rec, 'check_movers', status='not_run', reason='묶음 없음')
        rec['summary'].update(blocking=['check_weight (추가 설명)'], publish_ok=False, status='fail', verified=False,
                              warned=['check_style(힌트)', 'check_style'])
        _gate(rec, 'check_style', status='warn', items=STYLE_ITEMS)
    _rewrite(kr_repo, fn)
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert text.count('분량 실패 — 섹션 「매크로」를 찾지 못했다') == 1 and 'check_weight' not in text
    assert text.split('\n')[0] == '[발행] KR 일간 11/18 · 확인 필요 · 확인 1건 · 참고 1건 · 검사 빈칸 1건'
    assert text.count('「이틀」 3회') == 1 and 'check_style' not in text


def test_correction_line_does_not_claim_publish_time_or_commit_order(kr_repo):
    v = _nov18(kr_repo)
    v['corrections'] = {'typeset': 0, 'other': 1, 'unknown': 0}
    for same, want in ((False, '글을 추가한 커밋과 기록을 담은 커밋이 달라요(다른 커밋 — 기록 커밋 기준으로 대조)'),
                       (None, '글과 기록이 같은 커밋에 들어갔는지 확인 불가')):
        text = V.render_publish(dict(v, same_commit=same))
        assert want in text and '뒤 커밋' not in text and '발행 당시' not in text
        assert '위 검사는 기록을 처음 담은 판 기준' in text
    none = V.render_publish(dict(v, kind=V.NO_RECORD, check=None, recorded=None))
    assert '발행 뒤 수정 1회' in none and '위 검사는' not in none            # 기록이 없으면 검사 기준을 말하지 않는다
    assert '달라요' not in V.render_publish(v) and '확인 불가' not in V.render_publish(v)


def test_gap_names_outlive_review_and_note_items_but_not_check_items(kr_repo, monkeypatch):
    # 남기는 우선순위: 확인 필요 항목과 이유 > 빈칸 이름 > 검토·참고 항목
    v = _many_gaps(kr_repo, 6, width=10)
    v['recorded']['warned'] = ['check_weight', 'check_style']
    v['recorded']['reasons'].update(check_weight=[x[4:] for x in WEIGHT_ITEMS[1:3]], check_style=[STYLE_ITEMS[1][2:]])
    full = V.render_publish(v)
    assert '[검토 권고]' in full and '[참고]' in full
    brief = '\n'.join(V.scope_lines(v, V.BRIEF))
    monkeypatch.setattr(V, 'TEXT_LIMIT', V._size(full) - (V._size('\n'.join(V.scope_lines(v))) - V._size(brief)) - 40)
    text = V.render_publish(v)
    assert '[확인 필요] 펀드 실패 — 위반: 펀드 블록 표가 없다' in text and ' · 일부만 검사: check_xxxxxxxxxx_5' in text
    assert '[참고]' not in text and '외 ' in text


# ── codex 구현 검토 3회 지적의 재현 ─────────────────────────────────────────

def _fund_failed(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_fund', status='fail', items=['위반: 펀드 블록 표가 없다'])
        rec['summary'].update(blocking=['check_fund'], publish_ok=False, status='fail', verified=False)
    return fn


@pytest.mark.parametrize('path', ['<' + '가' * 3900 + '>/input.json', '<datadir>/' + '나' * 3900 + '.json', '다' * 3900])
def test_long_workspace_input_name_does_not_push_out_the_failure(kr_repo, path, monkeypatch):
    fn = _fund_failed(kr_repo)
    _rewrite(kr_repo, lambda rec: (fn(rec), rec['inputs']['files'].append(
        {'path': path, 'sha256': 'x', 'ref': 'workspace-only'})))
    fit = V._fit
    monkeypatch.setattr(V, '_fit', lambda lines, foot, limit: fit(lines, foot, 10 ** 9))
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert V._size(text) <= V.TEXT_LIMIT and '1. [확인 필요] 펀드 실패 — 위반: 펀드 블록 표가 없다' in text
    assert '표 55칸 자동 대조' in text and text.endswith(V.FOOTER) and '작업 공간 전용 입력 1개' in text
    assert all(len(V._input_name(p)) <= 100 for p in (path, '<' + 'x' * 500 + '>/' + 'y' * 500))


def test_huge_free_text_anywhere_keeps_the_required_failure(kr_repo, monkeypatch):
    # 기록의 자유 문장 칸마다 아주 긴 값을 넣어도 — 필수 실패 이유·숫자 범위·맺음말은 남는다(같은 갈래의 이웃 경로)
    big = '긴값' * 2000
    fn = _fund_failed(kr_repo)

    def more(rec):
        fn(rec)
        _gate(rec, 'check_movers', status='not_run', reason=big)
        _gate(rec, 'check_research', status='partial', reason='일부를 건너뛰었다 — ' + big)
        _gate(rec, 'check_style', status='warn', items=['· ' + big])
        rec['summary']['warned'] = ['check_style', big]
        rec['summary']['integrity'] = ['검사 중에 원본 글이 바뀌었다 — ' + big]
        rec['inputs']['files'] += [{'path': f'<{big}>/{big}{i}', 'sha256': 'x', 'ref': 'workspace-only'} for i in range(12)]
        rec['inputs']['files'].append({'path': 'x', 'sha256': 'x', 'ref': big})
    _rewrite(kr_repo, more)
    fit = V._fit
    monkeypatch.setattr(V, '_fit', lambda lines, foot, limit: fit(lines, foot, 10 ** 9))
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert V._size(text) <= V.TEXT_LIMIT and '[확인 필요] 펀드 실패 — 위반: 펀드 블록 표가 없다' in text
    assert '표 55칸 자동 대조' in text and text.endswith(V.FOOTER)
    assert max(len(x) for x in text.split('\n')) <= 1000


def _us_reference(tmp_path, status, **kw):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def fn(rec):
        rec['gates'][0].update(status=status, required=False, **kw)
        rec['summary'] = dict(R.summarize(rec['gates']), integrity=[])
    _rewrite(repo, fn, market='us', date='2026-11-09')
    return V.view(str(repo), 'HEAD', 'us', '2026-11-09')


@pytest.mark.parametrize('status,word,kw', [
    ('indeterminate', '판정 불가', {'reason': '입력을 읽지 못했다'}), ('fail', '실패', {'items': ['위반: 색']})])
def test_reference_only_status_is_explained_in_scope_not_status(tmp_path, status, word, kw):
    v = _us_reference(tmp_path, status, **kw)
    assert v['recorded']['status'] == status and v['recorded']['publish_ok'] and not V.anomalies(v)
    text = V.render_publish(v)
    block = text.split('■ 발행 상태')[1].split('■')[0]
    assert text.split('\n')[0].startswith('[발행] US 일간 11/09 · 발행 통과') and '기록 판정' not in block and word not in block
    scope = text.split('■ 검증 범위')[1]
    assert f' · 기록 판정은 「{word}」 — 참고 검사 때문이에요(필수 검사는 모두 기록상 통과)' in scope
    assert ('판정 불가(참고 검사): ' in scope and '입력을 읽지 못했다' in scope) if status == 'indeterminate' else '실패(참고 검사)' in text


@pytest.mark.parametrize('ref', ['fail', 'indeterminate'])
@pytest.mark.parametrize('gap', ['not_run', 'partial'])
def test_reference_only_does_not_claim_required_passed_when_one_did_not_run(tmp_path, ref, gap):
    # 참고 검사 실패·판정 불가 + 필수 검사 미실행·일부만 → 「필수 검사는 모두 기록상 통과」라고 쓰지 않는다(codex 구현 4회)
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)

    def fn(rec):
        g = dict(rec['gates'][0])
        rec['gates'][0].update(status=ref, required=False, reason='입력을 읽지 못했다', items=['위반: 색'])
        rec['gates'].append(dict(g, name='check_fund', status=gap, required=True))
        rec['summary'] = dict(R.summarize(rec['gates']), integrity=[])
    _rewrite(repo, fn, market='us', date='2026-11-09')
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    text = V.render_publish(v)
    assert '필수 검사는 모두 기록상 통과' not in text
    if V._ref_only(v['recorded']):
        assert '참고 검사 때문이에요' in text
    assert '펀드' in text.split('■ 검증 범위')[1]


def test_required_indeterminate_still_shows_in_status(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_fund', status='indeterminate', reason='입력을 읽지 못했다')
        rec['summary'].update(blocking=['check_fund'], publish_ok=False, status='indeterminate', verified=False)
    _rewrite(kr_repo, fn)
    text = V.render_publish(V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE))
    assert '기록 판정 판정 불가' in text and '· 확인 필요 ·' in text.split('\n')[0] and '참고 검사 때문' not in text


def test_label_only_for_confirmed_checker_names_in_the_scripts_category(kr_repo):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)
    _rewrite(kr_repo, lambda rec: rec['inputs']['files'].insert(0, {'path': 'x', 'sha256': 'x', 'ref': 'check_weight'}))
    v = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)
    assert v['check']['cat_detail']['repo_inputs'][0] == {'state': '대조 불가', 'text': '입력 참조 종류를 모른다 — check_weight',
                                                          'gate': None}
    assert '입력 참조 종류를 모른다 — check_weight' in V.render_publish(v)
    chk = {'cat_why': {'scripts': ['기록에 실행 정보가 없다 — check_fund'], 'post': ['다르다 — check_fund']},
           'cat_detail': {'scripts': [{'state': '대조 불가', 'text': '기록에 실행 정보가 없다 — check_fund', 'gate': None}]}}
    assert V._cat_reasons(chk, 'scripts', '대조 불가') == ['기록에 실행 정보가 없다 — check_fund']      # 이름이 확인되지 않았다
    assert V._cat_reasons(chk, 'post', '불일치') == ['다르다 — check_fund']                          # 검사 코드 칸이 아니다
    chk['cat_detail']['scripts'][0]['gate'] = 'check_fund'
    assert V._cat_reasons(chk, 'scripts', '대조 불가') == ['기록에 실행 정보가 없다 — 펀드']


@pytest.mark.parametrize('gate_name,blocking', [
    ('check_weight (추가 설명)', ['check_weight', 'check_weight (추가 설명)']),
    ('check_weight (추가 설명)', ['check_weight (추가 설명)']),
    ('check_weight', ['check_weight (추가 설명)', 'check_weight', 'check_weight(다른 꼬리)']),
])
def test_suffix_on_the_gate_entry_itself_is_still_one_item(kr_repo, gate_name, blocking):
    F.publish(kr_repo, 'kr', KR_DATE, workspace=False, numbers=NUMBERS)

    def fn(rec):
        _gate(rec, 'check_weight').update(name=gate_name, status='fail', items=['섹션 「매크로」를 찾지 못했다'])
        rec['summary'].update(blocking=blocking, publish_ok=False, status='fail', verified=False)
    _rewrite(kr_repo, fn)
    v = V.view(str(kr_repo), 'HEAD', 'kr', KR_DATE)
    before = (V.fingerprint(v), V.anomalies(v), list(v['recorded']['required_failed']))
    text = V.render_publish(v)
    assert text.count('분량 실패 — 섹션 「매크로」를 찾지 못했다') == 1 and 'check_weight' not in text
    assert '이유가 기록에 없어요' not in text and ' · 확인 1건' in text.split('\n')[0]
    assert before == (V.fingerprint(v), V.anomalies(v), [gate_name])              # 판정이 읽는 원래 이름은 그대로


def test_names_use_one_key_for_reasons_items_gaps_and_hints():
    rec = {'readable': True, 'allowed': frozenset({'check_weight'}), 'not_run': ['g1 (a)', 'g1'], 'partial': ['g2 (x)'],
           'indeterminate': [], 'required_indeterminate': [], 'warned': ['check_style (힌트)'], 'blocking': [],
           'reasons': {'check_weight (추가)': ['a'], 'check_weight': ['a', 'b'], 'g1 (a)': ['c'], 'g2 (x)': ['d']}}
    key, reasons = V._names(rec)
    assert reasons == {'check_weight': ['a', 'b'], 'g1': ['c'], 'g2 (x)': ['d']}      # 모르는 꼬리 이름은 그대로
    assert key('check_style (힌트)') == 'check_style' and key('g1 (a)') == 'g1' and key('g2 (x)') == 'g2 (x)'
    assert V._gaps(rec) == [('실행 안 함', 'g1'), ('일부만 검사', 'g2 (x)')]


def test_first_add_of_the_post_is_not_counted_as_a_correction(tmp_path):
    repo = F.init(tmp_path)
    base = F.git(repo, 'rev-parse', 'HEAD')                    # 글이 아직 없는 판 — 기록이 글보다 먼저 들어간 경우의 기준점
    F.write(repo, 'posts/2026-11-09.html', '<p>첫 글이다.</p>')
    first = F.commit(repo, 'post')
    assert V.corrections(str(repo), first, 'posts/2026-11-09.html', base) == {'typeset': 0, 'other': 0, 'unknown': 0}
    F.write(repo, 'posts/2026-11-09.html', '<p>고친 글이다.</p>')
    F.commit(repo, 'fix')
    got = V.corrections(str(repo), 'HEAD', 'posts/2026-11-09.html', base)
    assert sum(got.values()) == 1 and got == V.corrections(str(repo), 'HEAD', 'posts/2026-11-09.html', first)
