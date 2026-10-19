"""2026-10-20 배치 — §2 는 다섯 문단, 어제 판단의 판정은 「시장 판단과 복기」 첫 문단,
다음 확인 일정은 표 한 장으로 모은다(외부 평가: 같은 결론을 여러 곳에서 되풀이하고,
복기가 뉴스 뒤로 밀렸다)."""
import pytest

from kr.stance_gate import LAYOUT_V2_FROM, check, layout

from .test_stance_gate import EVAL, PARAS, STANCE

V2 = ["event", "gap", "meaning", "action", "invalidation"]
SCHEDULE = ('<section><h2>향후 확인 일정</h2><div class="tbl-scroll"><table>'
            '<thead><tr><th>시점</th><th>확인할 것</th><th>가르는 판단</th></tr></thead><tbody>'
            '<tr><td>10월 21일 마감</td><td>외국인 세 세션 수급</td><td>매도 소진 여부</td></tr>'
            '<tr><td>이달 말</td><td>SK하이닉스 3분기 실적</td><td>반도체 이익</td></tr>'
            '</tbody></table></div></section>')
NEWS = '<section><h2>오늘의 뉴스</h2><div class="news-item" data-news="1"><p>기사</p></div></section>'


def _doc(paras=None, order=None, review=True, schedule=SCHEDULE, tail=NEWS, review_first=True):
    paras = {**PARAS, **(paras or {})}
    order = order or V2
    lede = "\n".join(f'<p data-lede="{k}">{paras[k]}</p>' for k in order)
    hyp = '<p data-hypothesis="h1">사전에 정한 세 세션 검증은 10월 21일 마감까지 이어진다.</p>'
    rev = f'<p data-lede="review">{paras["review"]}</p>' if review else ''
    learn = (rev + hyp) if review_first else (hyp + rev)
    return (f'<section><h2>전략 코멘트</h2>\n{lede}\n</section>'
            '<section><h2>오늘의 장</h2><p>딴 얘기</p></section>'
            f'<section class="card" data-learning="daily"><h2>시장 판단과 복기</h2>{learn}</section>'
            f'{schedule}{tail}')


def test_v2_document_passes():
    assert check(_doc(), STANCE, EVAL, report_date=LAYOUT_V2_FROM) == []


def test_layout_detection():
    assert layout(_doc(), None) == "v2"
    six = _doc(order=V2 + ["review"])
    assert layout(six, "2026-10-19") == "v1"           # 옛 글은 옛 계약으로
    assert layout(six, LAYOUT_V2_FROM) == "v2"          # 적용일부터는 날짜가 정한다


def test_review_left_in_section_two_after_cutoff_is_caught():
    v = check(_doc(order=V2 + ["review"]), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("§2 에 review" in x for x in v)


def test_old_six_paragraph_post_still_passes_before_cutoff():
    # 정정 러너가 옛 글을 다시 볼 때 새 계약으로 막으면 안 된다
    six = (f'<h2>전략 코멘트</h2>'
           + "".join(f'<p data-lede="{k}">{PARAS[k]}</p>' for k in V2 + ["review"])
           + '<h2>오늘의 장</h2><p>딴 얘기</p>')
    assert check(six, STANCE, EVAL, report_date="2026-10-16") == []


def test_review_missing_from_learning_section():
    v = check(_doc(review=False), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("review" in x and "시장 판단과 복기" in x for x in v)


def test_review_must_open_learning_section():
    v = check(_doc(review_first=False), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("첫 문단" in x for x in v)


def test_review_still_must_speak_verdict():
    v = check(_doc({"review": "지난 회차는 반도체 이야기를 했다. 오늘도 반도체가 주도했다. "
                              "그 밖에는 달라진 것이 없고 다음 세션에서 이어 본다."}),
              STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("review" in x and "유효" in x for x in v)


def test_thin_review_is_caught():
    v = check(_doc({"review": "판단은 그대로 유지한다."}), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("review" in x and "80자" in x for x in v)


def test_schedule_section_required():
    v = check(_doc(schedule=""), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("향후 확인 일정" in x for x in v)


def test_schedule_needs_a_table_row():
    empty = '<section><h2>향후 확인 일정</h2><p>10월 21일을 본다.</p></section>'
    v = check(_doc(schedule=empty), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("표" in x for x in v)


@pytest.mark.parametrize("when", ["다음에", "곧", ""])
def test_schedule_row_needs_a_time(when):
    bad = SCHEDULE.replace("이달 말", when)
    v = check(_doc(schedule=bad), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("시점" in x for x in v)


@pytest.mark.parametrize("when", ["10월 22일", "10/22", "이달 말", "일정 미확정", "11월 중", "다음 주", "3분기 실적 발표"])
def test_schedule_time_forms(when):
    ok = SCHEDULE.replace("이달 말", when)
    assert check(_doc(schedule=ok), STANCE, EVAL, report_date=LAYOUT_V2_FROM) == []


def test_learning_and_schedule_come_before_news():
    late = (_doc(schedule="", tail="")
            .replace('<section class="card"', NEWS + '<section class="card"', 1)) + SCHEDULE
    v = check(late, STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("보다 앞에 둔다" in x for x in v)


def test_schedule_after_learning():
    swapped = _doc(schedule="").replace('<section class="card"', SCHEDULE + '<section class="card"', 1)
    v = check(swapped, STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("바로 뒤" in x for x in v)


# --- codex 설계 검토 2026-10-19 #3: 존재만 보면 빈 표·숨긴 문단이 통과한다 ---

def test_schedule_needs_two_to_six_rows_of_three_filled_cells():
    one = ('<section><h2>향후 확인 일정</h2><table><tbody>'
           '<tr><td>일정 미확정</td></tr></tbody></table></section>')
    v = check(_doc(schedule=one), STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("2~6행" in x for x in v)
    assert any("세 칸" in x for x in v)
    blank = SCHEDULE.replace("<td>반도체 이익</td>", "<td> </td>")
    assert any("빈 칸" in x for x in check(_doc(schedule=blank), STANCE, EVAL, report_date=LAYOUT_V2_FROM))
    seven = SCHEDULE.replace("</tbody>", "<tr><td>10월 23일</td><td>a</td><td>b</td></tr>" * 5 + "</tbody>")
    assert any("2~6행" in x for x in check(_doc(schedule=seven), STANCE, EVAL, report_date=LAYOUT_V2_FROM))


@pytest.mark.parametrize("wrap", ['<p hidden data-lede="review">{}</p>',
                                  '<details><summary>복기</summary><p data-lede="review">{}</p></details>',
                                  '<p data-lede="review" style="display:none">{}</p>'])
def test_hidden_review_does_not_count(wrap):
    doc = _doc(review=False).replace('<h2>시장 판단과 복기</h2>',
                                     '<h2>시장 판단과 복기</h2>' + wrap.format(PARAS["review"]))
    v = check(doc, STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("보이" in x for x in v)


def test_two_review_paragraphs_are_caught():
    doc = _doc().replace('<p data-hypothesis', f'<p data-lede="review">{PARAS["review"]}</p><p data-hypothesis')
    v = check(doc, STANCE, EVAL, report_date=LAYOUT_V2_FROM)
    assert any("하나" in x for x in v)


# --- codex 구현 검토 2026-10-20 #1~#3: 정규식 구간은 주석·숨김·섹션 밖·표 모양을 못 본다 ---

def _bad(doc):
    return check(doc, STANCE, EVAL, report_date=LAYOUT_V2_FROM)


@pytest.mark.parametrize("wrap", ['<!--{}-->', '<div hidden>{}</div>', '<template>{}</template>'])
def test_commented_or_hidden_review_fails(wrap):
    rev = f'<p data-lede="review">{PARAS["review"]}</p>'
    assert _bad(_doc().replace(rev, wrap.format(rev)))


def test_fake_attribute_review_fails():
    rev = f'<p data-lede="review">{PARAS["review"]}</p>'
    assert _bad(_doc().replace(rev, f"<p title='data-lede=\"review\"'>{PARAS['review']}</p>"))


def test_review_moved_to_sibling_section_fails():
    assert _bad(_doc().replace('<h2>시장 판단과 복기</h2>', '<h2>시장 판단과 복기</h2></section><section>'))


def test_schedule_rows_in_sibling_section_fail():
    assert _bad(_doc().replace('<h2>향후 확인 일정</h2>', '<h2>향후 확인 일정</h2></section><section>'))


def test_hidden_schedule_fails():
    assert _bad(_doc().replace('<section><h2>향후 확인 일정</h2>', '<section hidden><h2>향후 확인 일정</h2>'))


def test_schedule_without_table_tag_fails():
    assert _bad(_doc().replace('<table>', '').replace('</table>', ''))


def test_four_cell_row_fails():
    assert _bad(_doc().replace('<td>반도체 이익</td>', '<td>반도체 이익</td><td>덤</td>'))


def test_nbsp_cell_fails():
    assert _bad(_doc().replace('<td>반도체 이익</td>', '<td>&nbsp;</td>'))


def test_row_header_cell_and_no_thead_pass():
    ok = (SCHEDULE.replace('<td>10월 21일 마감</td>', '<th scope="row">10월 21일 마감</th>')
          .replace('<thead><tr><th>시점</th><th>확인할 것</th><th>가르는 판단</th></tr></thead>', ''))
    assert check(_doc(schedule=ok), STANCE, EVAL, report_date=LAYOUT_V2_FROM) == []


def test_schedule_with_caption_still_passes():
    ok = SCHEDULE.replace('</table>', '</table><p class="caption">일정은 바뀔 수 있다.</p>')
    assert check(_doc(schedule=ok), STANCE, EVAL, report_date=LAYOUT_V2_FROM) == []


@pytest.mark.parametrize("bad", ["2026-10-19junk", "2026-10-020", "garbage"])
def test_malformed_date_is_treated_as_new_layout(bad):
    six = _doc(order=V2 + ["review"])
    assert layout(six, bad) == "v2"


# --- codex 2차 구현 검토 2026-10-20 #1·#2 ---

def test_duplicate_attribute_hiding_fails():
    rev = '<p data-lede="review">'
    assert _bad(_doc().replace(rev, '<p data-lede="review" style="display:none" style="">'))
    assert _bad(_doc().replace('<section class="card" data-learning="daily">',
                               '<section class="card" data-learning="daily" hidden hidden>'))


def test_review_in_nested_subsection_fails():
    rev = f'<p data-lede="review">{PARAS["review"]}</p>'
    assert _bad(_doc().replace(rev, f'<section><h2>별도 참고 자료</h2>{rev}</section>'))


def test_schedule_table_in_nested_subsection_fails():
    nested = SCHEDULE.replace('<table>', '<section><h2>별도</h2><table>', 1).replace('</table>', '</table></section>', 1)
    assert _bad(_doc(schedule=nested))


# --- codex 3차 구현 검토 2026-10-20 ---

def test_review_under_another_heading_in_same_section_fails():
    rev = f'<p data-lede="review">{PARAS["review"]}</p>'
    assert _bad(_doc().replace(f'<h2>시장 판단과 복기</h2>{rev}',
                               f'<h2>별도 참고 자료</h2>{rev}<h2>시장 판단과 복기</h2>'))


def test_schedule_table_before_its_heading_fails():
    moved = SCHEDULE.replace('<h2>향후 확인 일정</h2>', '').replace('</table></div>', '</table></div><h2>향후 확인 일정</h2>')
    assert _bad(_doc(schedule=moved))
