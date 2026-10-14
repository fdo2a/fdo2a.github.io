"""데스크 문체(`<body data-register="da">`) 검사 — 2026-09-24 사용자 지시
「US독자는 PM으로 통일해. 어미는 다로 고정하자」."""
import subprocess
import sys
from pathlib import Path

from us.style import findings, is_desk_register

ROOT = Path(__file__).resolve().parents[3]


def desk(body):
    return f'<html><body data-register="da"><div class="doc">{body}</div></body></html>'


def plain(body):
    return f'<html><body><div class="doc">{body}</div></body></html>'


def keys(html, level=None):
    return {f['key'] for f in findings(html)
            if level is None or f.get('level', 'fail') == level}


GOOD = ('<p>코스피는 0.90% 올라 7,081로 마감했다. 반도체가 지수를 받쳤다. '
        '외국인은 4,942억원을 순매도했다. 건설은 4.66% 내렸다. 원화는 약해졌다.</p>')


def test_declaration_is_read_from_the_body_tag_only():
    assert is_desk_register(desk('<p>x</p>'))
    assert not is_desk_register(plain('<p>data-register="da"</p>'))


def test_plain_da_prose_passes_even_with_many_da_endings():
    assert findings(desk(GOOD)) == []


def test_same_two_syllable_ending_run_is_monotone():
    html = desk('<p>지수가 올랐다. 금리가 올랐다. 달러가 올랐다. 유가가 올랐다.</p>')
    assert 'monotone' in keys(html)


def test_old_monotone_rule_still_applies_without_declaration():
    assert 'monotone' in keys(plain(GOOD))


def test_hapsyo_endings_mix_is_a_failure():
    html = desk('<p>코스피가 올랐다. 반도체가 받쳤습니다. 외국인은 팔았습니다. '
                '기관만 샀죠.</p>')
    assert 'register' in keys(html, 'fail')


def test_two_polite_sentences_are_tolerated():
    html = desk('<p>코스피가 올랐다. 반도체가 받쳤습니다. 외국인은 팔았습니다.</p>')
    assert 'register' not in keys(html)


def test_register_ignores_captions():
    html = desk(GOOD + '<p class="caption">투자 권유가 아닙니다. 책임은 본인에게 있습니다. '
                '출처는 네이버입니다.</p>')
    assert 'register' not in keys(html)


def test_register_is_not_checked_without_declaration():
    html = plain('<p>올랐습니다. 받쳤습니다. 팔았습니다. 샀습니다.</p>')
    assert 'register' not in keys(html)


def test_rhetorical_questions():
    two = desk('<p>나머지 업종은 어땠을까? 대부분 내렸다. 그럼 무엇을 기다릴까? '
               '정상회담이다.</p>')
    one = desk('<p>이 상승을 넓은 위험선호로 읽을 수 있을까? 아직 아니다.</p>')
    assert 'question' in keys(two, 'fail')
    assert 'question' not in keys(one)


def test_internal_vocabulary_fails_even_in_captions():
    assert 'internal' in keys(desk('<p>판단 원장에는 직전 판단이 없다.</p>'), 'fail')
    assert 'internal' in keys(desk(GOOD + '<p class="caption">실행: python3 -c "print(1)"</p>'))
    assert 'internal' in keys(desk('<p>러셀2000은 «큼» 밴드에 들었다.</p>'))
    assert 'internal' in keys(desk('<p>상위 84.7 분위를 경계로 잰다.</p>'))
    assert 'internal' in keys(desk('<p>기계 판정은 판정불가다.</p>'))
    assert 'internal' in keys(desk('<p>kr_econ.json 의 값을 썼다.</p>'))


def test_internal_vocabulary_false_friends_pass():
    html = desk('<p>금융감독원장이 발언했다. 볼린저밴드 상단은 7,146이다. '
                '시장 분위기는 차분했다.</p>')
    assert 'internal' not in keys(html)


def test_provenance_block_may_hold_the_calculation():
    html = desk(GOOD + '<details data-provenance><summary>계산 근거</summary>'
                '<p>입력 kr_econ.json. 실행 python3 -c "print(round((4.689-4.006)*100,1))"</p>'
                '</details>')
    assert 'internal' not in keys(html)


def test_provenance_block_is_not_a_hiding_place_for_prose():
    long_text = '코스피는 오늘 올랐다. ' * 80
    html = desk(GOOD + f'<details data-provenance><p>{long_text}</p></details>')
    assert 'provenance' in keys(html, 'fail')


def test_bond_rally_wording_is_ambiguous_even_in_the_headline():
    assert 'bond_ambiguous' in keys(desk('<h1>국채 급등에 3대 지수 하락</h1>' + GOOD))
    assert 'bond_ambiguous' not in keys(desk('<h1>국채금리 급등에 3대 지수 하락</h1>' + GOOD))


def test_warnings_do_not_fail():
    dashes = desk('<p>' + ' '.join(f'지수가 {i}번째로 흔들렸다 — 이유는 금리였다.'
                                   for i in range(7)) + '</p>')
    assert 'emdash' in keys(dashes, 'warn')
    hedges = desk('<p>' + ' '.join(['이를 가를 자료는 없다.', '단정하지 않는다.',
                                    '판단을 유보한다.', '확정하기는 이르다.',
                                    '특정할 수 없다.', '쪼갤 수 없다.',
                                    '가리지 못한다.']) + '</p>')
    assert 'hedge' in keys(hedges, 'warn')
    repeat = desk('<p>시가는 7,154였다.</p><p>7,154가 고가였다.</p>'
                  '<p>지수는 7,154에서 밀렸다.</p><p>다시 7,154를 못 봤다.</p>')
    assert 'repeat_number' in keys(repeat, 'warn')


def test_pm_reader_needs_no_gloss_but_plain_transliterations_still_count():
    html = desk('<p>기간프리미엄이 2bp 올랐다. 브레드스가 좁았다.</p>')
    assert 'jargon_gloss' not in keys(html)
    assert 'jargon' in keys(html)
    assert 'jargon_gloss' in keys(plain('<p>기간프리미엄이 2bp 올랐다.</p>'))


def test_check_style_exit_code_ignores_warnings(tmp_path):
    f = tmp_path / 'p.html'
    verbs = ('올랐다', '내렸다', '버텼다', '밀렸다', '멈췄다', '튀었다', '꺾였다')
    f.write_text(desk('<p>' + ' '.join(f'{i}시에 지수가 {v} — 금리 탓이다.'.replace('탓이다', t)
                                       for i, (v, t) in enumerate(zip(verbs, (
                                           '탓이다', '영향이다', '때문이다', '결과다',
                                           '여파다', '반응이다', '흔적이다'))))
                      + '</p>'), encoding='utf-8')
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/check_style.py'), str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert '경고' in r.stdout
    f.write_text(desk('<p>판단 원장에는 기록이 없다.</p>'), encoding='utf-8')
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/check_style.py'), str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 1


# --- 자기 검토(codex 대신)에서 나온 우회 ---

def test_zero_width_characters_do_not_split_workflow_words():
    assert 'internal' in keys(desk('<p>판단 원​장에는 기록이 없다.</p>'))


def test_a_fake_research_summary_does_not_hide_prose():
    fake = ('<section class="card" data-research-summary="x"><h2>연구 판단 복기</h2>'
            '<p>오늘 반도체가 올랐습니다. 외국인은 팔았습니다. 기관은 샀습니다.</p>'
            '<p>판단 원장에는 기록이 없다.</p></section>')
    found = keys(desk(GOOD + fake))
    assert 'register' in found and 'internal' in found


def test_the_real_generated_summary_is_still_exempt():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from common.research_gate import render_summary
    summary = {'counts': {'total': 2, 'prospective': 1, 'retrospective': 1,
                          'open': 1, 'overdue': 0},
               'hypotheses': [{'title': '원장 기록 테스트용 가설 제목', 'prospective': True,
                               'direction': 'supported', 'mechanism': 'undecidable',
                               'status': 'open', 'execution_status': 'watch',
                               'performance': {'status': 'unavailable'}}]}
    assert findings(desk(GOOD + render_summary(summary))) == []


def test_polite_endings_without_a_period_or_inside_quotes_count():
    html = desk('<p>반도체가 올랐습니다</p><p>「외국인은 팔았습니다.」</p>'
                '<p>기관은 샀습니다」</p>')
    assert 'register' in keys(html)
    qs = desk('<p>(나머지는 어땠을까?)</p><p>「무엇을 기다릴까?」</p>')
    assert 'question' in keys(qs)


# --- 판단 동사 (2026-09-24, 증권사 리포트 기준) ---

def test_strategy_comment_without_an_owned_judgment_is_warned():
    hedged = desk('<h2>전략 코멘트</h2><p>금리가 급등했다. 어느 쪽이 밀었는지는 내일 갈린다. '
                  '정책 재가격화에 가까워 보인다.</p><h2>오늘의 장</h2>' + GOOD)
    owned = desk('<h2>전략 코멘트</h2><p>금리가 급등했다. 정책 재가격화에 가깝다고 판단한다. '
                 '어느 쪽이 밀었는지는 내일 갈린다.</p><h2>오늘의 장</h2>' + GOOD)
    assert 'judgment_verb' in keys(hedged, 'warn')
    assert 'judgment_verb' not in keys(owned)
    assert 'judgment_verb' not in keys(desk(GOOD))          # 섹션이 없으면 보지 않는다


def test_watching_is_not_a_judgment():
    html = desk('<h2>전략 코멘트</h2><p>금리가 급등했다. 내일 실질금리를 지켜본다.</p><h2>x</h2>')
    assert 'judgment_verb' in keys(html, 'warn')


# ── 분석 언어 ↔ 전달 언어 (2026-10-13 사용자 문체 비평, STYLE_EXEMPLARS §10) ──────────

RESEARCH = ('<p>반도체 후보의 가격 근거는 약해졌고 CPI가 다음 시험이다. '
            '오늘 새로 연 질문은 메모리 하락이다. 금리는 관측되지 않았다.</p>')


def test_research_vocabulary_over_three_is_warned():
    html = desk(GOOD + RESEARCH)
    assert 'research_language' in keys(html, 'warn')
    assert 'research_language' not in keys(html, 'fail')


def test_three_research_words_are_tolerated():
    html = desk(GOOD + '<p>반도체 후보가 밀렸다. 이번 주 시험은 CPI다. 금리는 관측되지 않았다.</p>')
    assert 'research_language' not in keys(html)


def test_election_and_press_conference_words_are_not_research_language():
    news = ('<p>대선 후보는 후보 등록을 마쳤다. 후보 토론에서 기자 질문에 답했다. '
            '임상시험 결과가 나왔다. 정책 경로는 그대로다. 시험 생산을 시작했다.</p>')
    assert 'research_language' not in keys(desk(GOOD + news))


def test_research_language_skips_provenance_captions_and_news_summaries():
    hidden = ('<details data-provenance><p>후보 시험 질문 관측 기준선</p></details>'
              '<p class="caption">후보 시험 질문 관측 기준선</p>'
              '<p data-summary="1">후보 시험 질문 관측 기준선</p>')
    assert 'research_language' not in keys(desk(GOOD + hidden))


def test_coined_metaphors_are_warned():
    for phrase in ('AI 하드웨어 매도가 하루를 정했다.', 'CXMT는 이름표에 가깝다.',
                   'CPI 전에는 시계를 늘리지 않는다.', '달러가 한 칸 올라선 셈이다.',
                   '가격 신호는 위험선호 쪽이다.', '그때는 판단을 거둔다.'):
        assert 'figurative' in keys(desk(GOOD + f'<p>{phrase}</p>'), 'warn'), phrase
    assert 'figurative' not in keys(desk(GOOD))


def test_research_language_warning_keeps_exit_code_zero(tmp_path):
    f = tmp_path / 'p.html'
    f.write_text(desk(GOOD + RESEARCH + '<p>CXMT는 이름표에 가깝다.</p>'), encoding='utf-8')
    r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'check_style.py'), str(f)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ordinary_market_terms_are_not_research_language():
    # codex 구현 검토 #4 재현 문장들 + 사용자 2차 피드백의 정상 용어(2026-10-13).
    ordinary = ('<p>종가는 일목균형표 기준선 위에 있고 전환선과 기준선이 모두 올랐다. '
                '관측 시각은 15:30이다. 한국장 시간대 마지막 관측으로 잰다. '
                '금리 장중 경로는 V자였다. 관측된 상관관계는 -0.39다. '
                '통화정책 파급경로가 좁아졌다. 달러 강세가 수입물가를 통해 물가에 닿는 경로도 있다. '
                '정책금리 경로는 그대로다.</p>')
    assert 'research_language' not in keys(desk(GOOD + ordinary))
    from us.style import _research_hits
    import re as _re
    assert _research_hits(_re.sub('<[^>]+>', ' ', ordinary)) == []


def test_research_forms_codex_found_missing_are_counted():
    from us.style import _research_hits
    assert _research_hits('반도체 후보군의 상대 성과가 약해졌다.') == ['후보']
    assert _research_hits('CPI가 이 질문에 답한다.') == ['질문']
    assert _research_hits('대안 쪽 관측이다. 금리차 경로는 오늘 확인할 수 없다. 기준선을 고정했다.') \
        == ['관측', '경로', '기준선']


def test_research_allowance_grows_with_length():
    from us.style import research_allowance
    assert research_allowance('가' * 1000) == 3
    assert research_allowance('가' * 12500) == 5
    four = '<p>반도체 후보가 밀렸다. 이번 주 시험은 CPI다. 새 관측이 없다. 메모리 질문은 이어진다.</p>'
    assert 'research_language' in keys(desk(GOOD + four), 'warn')
    filler = '<p>' + '지수는 좁은 범위에서 움직였다. ' * 900 + '</p>'
    assert 'research_language' not in keys(desk(GOOD + four + filler))


def test_settled_finance_figures_are_not_flagged():
    settled = ('<p>금리 인상 압력이 커졌다. 대형주가 지수 하락을 방어했다. '
               '코스피는 숨고르기에 들어갔고 장은 전강후약이었다. 매수세가 유입됐다.</p>')
    assert 'figurative' not in keys(desk(GOOD + settled))
    assert 'figurative' in keys(desk(GOOD + '<p>AI 공급망 질문은 TSMC 실적에서 가린다.</p>'), 'warn')


def test_politics_interview_and_deal_contexts_are_not_research_language():
    # codex 구현 재검토 #2 — 실제 KR 발행본 문장(10/06·10/02·10/08)의 꼴.
    from us.style import _research_hits
    assert _research_hits('다카이치는 자민당 총재 선거에서 당 추천을 받은 후보로 나섰다.') == []
    assert _research_hits('타임 인터뷰에서 그는 관세에 대한 질문에 협상이 길어질 수 있다고 말했다.') == []
    assert _research_hits('클럽메드 인수전에는 다른 후보도 거론된다.') == []
    assert _research_hits('반도체 후보의 가격 근거가 약해졌다.') == ['후보', '가격 근거']


def test_dividing_a_research_question_is_figurative_but_dividing_explanations_is_not():
    # codex 구현 재검토 #3 — US 10/09 「CPI가 앞쪽 금리 질문을 가르고 TSMC가 AI 공급망 질문을 가른다」.
    hit = desk(GOOD + '<p>CPI가 앞쪽 금리 질문을 가르고 TSMC가 AI 공급망 질문을 가른다.</p>')
    assert 'figurative' in keys(hit, 'warn')
    assert 'figurative' not in keys(desk(GOOD + '<p>두 설명은 다음 주 수출 통계에서 갈린다. TSMC 실적이 두 설명을 가른다.</p>'))


def test_kr_news_item_summaries_are_not_counted_as_research_language():
    # codex 구현 재검토 3차 #3 — KR 10/08 오늘의 뉴스 클럽메드 기사 요약(실제 문장).
    item = ('<div class="news-item" data-news="011-0004669536"><p class="news-head">클럽메드</p>'
            '<p>글로벌 레저 기업 클럽메드가 휘닉스중앙 인수를 추진 중이다. 한화그룹과 소노그룹도 '
            '후보로 거론되지만 클럽메드가 가장 유력하다. 후보 질문 시험 관측이 없다.</p></div>')
    assert 'research_language' not in keys(desk(GOOD + item))


def test_deal_context_in_an_earlier_sentence_of_the_same_paragraph_counts():
    from us.style import _research_hits
    para = ('클럽메드가 휘닉스중앙 인수를 추진 중이다. 삼일PwC 자문을 받았다. '
            '한화그룹과 소노그룹도 후보로 거론되지만 클럽메드가 가장 유력하다.')
    assert _research_hits(para) == []


def test_native_day_counts_warn_but_haru_and_compounds_do_not():
    # 2026-10-13 사용자 지시 — 「아흐레째」가 아니라 「9일째」.
    hit = desk(GOOD + '<p>골디락스 판단을 아흐레째 유지한다. 매도가 나흘째 이어졌다.</p>')
    assert 'native_days' in keys(hit, 'warn')
    calm = GOOD + '<p>골디락스 판단을 9일째 유지한다. 하루 낙폭이 컸다. 하루이틀 사이 결론을 내지 않는다.</p>'
    assert 'native_days' not in keys(desk(calm))


# 2026-10-14 사용자 지시: 출처는 문장에 달지 말고 섹션 끝에 한 번.
def test_parenthetical_outlet_tag_is_flagged():
    html = desk('<p>보도가 유가를 받쳤다(oilprice.com). 지수는 0.4% 올랐다.</p>')
    assert 'inline_source' in keys(html, 'warn')


def test_outlet_as_subject_is_flagged():
    html = desk('<p>로이터는 공급 차질 우려가 커졌다고 전했다. 지수는 올랐다.</p>')
    assert 'inline_source' in keys(html, 'warn')
    html = desk('<p>Newsquawk는 원인으로 한국장의 급락을 들었다.</p>')
    assert 'inline_source' in keys(html, 'warn')


def test_section_end_source_caption_and_actors_are_not_flagged():
    html = desk('<p>BMO는 주택시장이 한동안 부진할 것으로 봤다. 월러 이사는 장기금리 상승이 '
                '긴축을 대신한다고 말했다. 닛케이는 0.5% 내렸다.</p>'
                '<p class="caption" data-sources>출처: Reuters, oilprice.com</p>')
    assert 'inline_source' not in keys(html)


def test_inline_source_is_a_warning_not_a_block():
    html = desk('<p>보도가 유가를 받쳤다(Reuters).</p>')
    assert 'inline_source' not in keys(html, 'fail')


def test_outlet_name_that_is_also_a_common_noun_is_only_flagged_in_brackets():
    assert 'inline_source' not in keys(desk('<p>한국경제는 수출 회복에도 내수가 부진하다.</p>'))
    assert 'inline_source' in keys(desk('<p>내수가 부진하다는 분석이 나왔다(한국경제).</p>'), 'warn')
