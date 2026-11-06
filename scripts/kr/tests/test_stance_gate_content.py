"""KR 복기·괴리 문단은 길이가 아니라 내용으로 본다 — 2026-11-06 사용자 결정.

「60자로 충분히 설명되는 내용을 80자로 늘리면 정보량은 그대로인데 문장만 길어진다. 분량을
강제하기보다 필요한 정보가 빠졌는지 검사하는 방식이 좋다. 복기 문단에 판정 근거와 기존
전망의 수정 여부가 포함됐는지 확인하는 것은 유용하다.」

- 수정 여부 = 판정 신호(VERDICT_CUES, 전부터 있던 검사).
- 판정 근거 = 판정이 유효·무효화일 때 그 판정을 만든 값(무효화 레벨 또는 오늘 종가)이
  복기 문장에 있다. 아무 숫자나 받지 않는다(codex 설계 2차 #2). 판정불가는 근거로 댈 값이
  없으니 판정 신호만 본다(#1).
- 자리 채움 = 두 어절 이상에 「-다」로 끝나는 문장이 하나도 없는 것.
"""
from kr.stance_gate import check

STANCE = {"date": "2026-09-22", "exposure": "유지", "horizon": "다음 세션",
          "thesis": "기관이 밀어올린 상승이고 외국인은 아직 관망이다.",
          "gap": "금리는 정책 부담을 값매겼는데 주식은 아직 아니다.",
          "invalidation": {"metric": "KOSPI", "level": 6904, "side": "below"}}
KEPT = {"verdict": "유효", "prior_date": "2026-09-21", "metric": "KOSPI",
        "level": 6904.0, "side": "below", "observed": 7008.25}
BROKEN = dict(KEPT, verdict="무효화", observed=6850.4)
BOOT = {"verdict": "판정불가", "note": "직전 판단 원장이 없다"}

PARAS = {
    "event": "코스피가 1.65% 올라 7,008로 마감했다.",
    "gap": "채권은 정책 부담을 이미 값매겼고 주식은 아직이다.",
    "meaning": "기관이 지수를 밀어올렸고 외국인은 관망했다.",
    "action": "오늘 상승에는 작은 무게만 둔다. 10월 6일 외국인 순매도 규모를 기다린다.",
    "invalidation": "코스피가 60일 이동평균 6,904를 내주면 판단을 다시 본다.",
    "review": "코스피가 6,904 위에서 끝나 어제 판단을 유지한다.",
}


def _html(paras=None):
    paras = {**PARAS, **(paras or {})}
    order = ["event", "gap", "meaning", "action", "invalidation", "review"]
    body = "\n".join(f'<p data-lede="{k}">{paras[k]}</p>' for k in order)
    return f"<h2>전략 코멘트</h2>\n{body}\n<h2>오늘의 장</h2><p>딴 얘기</p>"


def test_short_but_complete_gap_and_review_pass():
    assert len(PARAS["review"]) < 80 and len(PARAS["gap"]) < 80
    assert check(_html(), STANCE, KEPT) == []


def test_review_without_the_verdict_basis_is_caught():
    v = check(_html({"review": "어제 판단은 그대로 유지한다."}), STANCE, KEPT)
    assert any("review" in x and "근거" in x for x in v)


def test_an_unrelated_number_is_not_a_basis():
    v = check(_html({"review": "외국인이 3,120억원을 팔았지만 어제 판단은 그대로 유지한다."}),
              STANCE, KEPT)
    assert any("review" in x and "근거" in x for x in v)


def test_todays_close_rounded_in_prose_is_a_basis():
    ok = _html({"review": "코스피가 7,008로 마감해 어제 판단을 유지한다."})
    assert check(ok, STANCE, KEPT) == []


def test_broken_verdict_needs_its_basis_too():
    assert check(_html({"review": "코스피가 6,850으로 마감해 어제 판단을 철회한다."}),
                 STANCE, BROKEN) == []
    v = check(_html({"review": "어제 판단은 틀렸고 철회한다."}), STANCE, BROKEN)
    assert any("근거" in x for x in v)


def test_bootstrap_review_needs_no_number():
    ok = _html({"review": "비교할 직전 판단이 없어 오늘은 판정할 수 없다."})
    assert check(ok, STANCE, BOOT) == []


def test_placeholder_is_still_caught():
    for filler in ("—", "추후 보완", "판단 유지."):
        v = check(_html({"gap": filler}), STANCE, KEPT)
        assert any("gap" in x and "문장" in x for x in v), filler


def test_same_digits_with_a_money_unit_are_not_the_level():
    # codex 구현 검토 #2 — 레벨과 같은 숫자의 거래대금이 판정 근거로 통과하던 길.
    v = check(_html({"review": "어제 판단을 유지한다. 외국인은 6,904억원을 매도했다."}), STANCE, KEPT)
    assert any("근거" in x for x in v)
    assert check(_html({"review": "코스피가 6,904선 위에서 끝나 어제 판단을 유지한다."}), STANCE, KEPT) == []


def test_sentences_ending_in_quotes_or_brackets_count():
    # codex 구현 검토 #1
    for gap in ("시장은 「금리가 부담이다」.", "금리는 아직 부담이다(추정)."):
        assert check(_html({"gap": gap}), STANCE, KEPT) == [], gap
    assert any("gap" in x for x in check(_html({"gap": "시장 다"}), STANCE, KEPT))


def test_same_number_for_another_market_is_not_the_basis():
    # codex 구현 재검토 #1
    v = check(_html({"review": "어제 판단을 유지한다. 원달러 환율은 6,904로 마감했다."}), STANCE, KEPT)
    assert any("근거" in x for x in v)


def test_a_level_at_the_end_of_a_sentence_counts():
    # codex 구현 재검토 #2
    assert check(_html({"review": "어제 판단을 유지한다. 지킨 무효화 선은 코스피 6,904."}), STANCE, KEPT) == []


def test_period_inside_closing_quote_is_a_sentence():
    # codex 구현 재검토 #3
    assert check(_html({"gap": "시장은 「반도체가 올랐다.」"}), STANCE, KEPT) == []


# codex 최종 검토 C — 기준선 단어만 있으면 다른 시장의 같은 수치도 근거로 받았다.
def test_another_market_with_a_level_word_is_not_a_basis():
    for review in ("어제 판단은 유지한다. 미국 증시는 전일 고점 6,904를 넘었다.",
                   "어제 판단은 유지한다. 원달러 환율은 저점 6,904에서 반등했다.",
                   "어제 판단은 유지한다. 코스피200 은 60일 이동평균 6,904 위에 있다.",
                   "어제 판단은 유지한다. 나스닥은 6,904로 마감했다.",
                   "어제 판단은 유지한다. 코스피 200은 6,904를 넘었다.",
                   "어제 판단은 유지한다. 유로스톡스는 전일 고점 6,904를 넘었다."):
        v = check(_html({"review": review}), STANCE, KEPT)
        assert any("review" in x and "근거" in x for x in v), review


def test_the_evaluated_index_after_another_market_is_still_a_basis():
    for review in ("환율이 올랐지만 코스피는 6,904 위에서 끝나 어제 판단을 유지한다.",
                   "어제 판단을 유지한다. 6,904선을 지켰다.",
                   "미국 증시가 흔들렸어도 코스피 무효화 선 6,904를 지켜 판단을 유지한다.",
                   "어제 판단은 유지한다. 코스피는 미국 증시와 달리 6,904에 마감했다."):
        assert check(_html({"review": review}), STANCE, KEPT) == [], review


def test_a_same_sentence_coincidence_is_a_known_residual():
    # 같은 문장에 판정 지수와 다른 시장이 함께 나오고, 다른 시장의 수가 판정 값과 ±0.5 안에서
    # 같을 때는 통과한다 — 수의 주인을 가리려던 규칙이 정상 문장을 막아 되돌렸다(codex 4차 #2·#3).
    # 이 검사는 근거를 빠뜨린 복기를 잡는 것이다.
    r = "어제 판단은 유지한다. 6,904를 넘은 나스닥과 달리 코스피는 하락했다."
    assert check(_html({"review": r}), STANCE, KEPT) == []


def test_level_followed_by_il_ttae_is_a_basis():
    # codex 5차 — 「일」을 날수 단위로만 보아 「6,904일 때」를 근거 없음으로 막았다.
    for r in ("코스피가 6,904일 때 판단을 유지한다.", "코스피가 6,904일 경우를 지켜 판단을 유지한다."):
        assert check(_html({"review": r}), STANCE, KEPT) == [], r
    v = check(_html({"review": "코스피는 6904일 동안 판단을 유지한다."}), STANCE, KEPT)
    assert any("근거" in x for x in v)


def test_day_counts_and_dates_are_not_levels():
    # codex 6차 — 「20일 지나도」「11월 6일까지」의 수를 레벨로 받던 길.
    low = dict(KEPT, level=20.0, observed=6.0)
    for r in ("코스피 무효화 선을 20일 지나도 지켜 판단을 유지한다.",
              "코스피는 11월 6일까지 판단을 유지한다."):
        assert any("근거" in x for x in check(_html({"review": r}), STANCE, low)), r
