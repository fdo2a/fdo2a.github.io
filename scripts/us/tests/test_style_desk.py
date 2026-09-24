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
