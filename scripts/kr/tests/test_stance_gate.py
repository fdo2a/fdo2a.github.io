import pytest

from kr.stance_gate import check, marked, numbers, section_slice

STANCE = {"date": "2026-09-22", "exposure": "유지", "horizon": "다음 세션",
          "thesis": "기관이 밀어올린 상승이고 외국인은 아직 관망이다.",
          "gap": "금리는 정책 부담을 값매겼는데 주식은 아직 아니다.",
          "invalidation": {"metric": "KOSPI", "level": 6904, "side": "below"}}
EVAL = {"verdict": "유효", "prior_date": "2026-09-21"}

PARAS = {
    "event": "코스피가 1.65% 올라 7,008로 마감했다.",
    "gap": "국고채 3년물은 기준금리보다 105.6bp 위로 최근 2년 가운데 넓은 쪽 5% 안에 서 있다. "
           "채권은 정책 부담을 이미 값매겼다는 뜻인데, 주식은 오늘 그 부담을 값에 넣지 않았다.",
    "meaning": "기관이 지수를 밀어올렸고 외국인은 관망했다.",
    "action": "오늘 상승에는 작은 무게만 둔다. 10월 6일 첫 세션의 외국인 순매도 규모를 기다린다.",
    "invalidation": "코스피가 60일 이동평균 6,904를 내주면 판단을 다시 본다.",
    "review": "어제 세운 무효화 레벨은 오늘 종가가 깨지 않아 그 판단을 그대로 유지한다. "
              "다만 외국인 수급이 돌아오는지 보겠다던 조건은 아직 확인되지 않았고, "
              "그 대목에서는 어제보다 확신이 줄었다.",
}


def _html(paras=None, order=None, section="전략 코멘트"):
    paras = {**PARAS, **(paras or {})}
    order = order or ["event", "gap", "meaning", "action", "invalidation", "review"]
    body = "\n".join(f'<p data-lede="{k}">{paras[k]}</p>' for k in order)
    return f"<h2>{section}</h2>\n{body}\n<h2>오늘의 장</h2><p>딴 얘기</p>"


def test_clean_document_passes():
    assert check(_html(), STANCE, EVAL) == []


def test_missing_section():
    assert check("<h2>오늘의 장</h2>", STANCE, EVAL) == ["섹션 「전략 코멘트」을 찾지 못했다"]


def test_missing_block_is_reported():
    order = ["event", "meaning", "action", "invalidation", "review"]
    v = check(_html(order=order), STANCE, EVAL)
    assert v == ['§2: data-lede="gap" 문단이 없다']


def test_wrong_order_is_reported():
    order = ["event", "meaning", "gap", "action", "invalidation", "review"]
    v = check(_html(order=order), STANCE, EVAL)
    assert any("문단 순서가" in x for x in v)


def test_thin_gap_is_reported():
    v = check(_html({"gap": "기대가 다르다."}), STANCE, EVAL)
    assert any("§2 gap" in x for x in v)


def test_action_without_grade_passes():
    # 등급·시계는 원장에만 남는다(2026-10-04) — 본문이 밝힐 의무가 없다.
    assert check(_html({"action": "당분간 지켜본다."}), STANCE, EVAL) == []


@pytest.mark.parametrize("lede,text", [
    ("action", "위험 노출은 축소한다. 시계는 다음 세션이다."),
    ("invalidation", "코스피가 60일 이동평균 6,904 아래에서 마감하면 노출 유지의 전제를 거둔다."),
])
def test_grade_talk_is_a_violation(lede, text):
    v = check(_html({lede: text}), STANCE, EVAL)
    assert any("노출 등급 말투" in x for x in v)


def test_grade_talk_outside_section_two_is_caught():
    html = '<p class="muted">코스피 노출은 유지하고 정유주는 관찰한다.</p>' + _html()
    assert any("노출 등급 말투" in x for x in check(html, STANCE, EVAL))


REAL_REVIEWS = {   # kr/posts 의 실제 복기 — 「노출 등급은 유지하되」만 지운다
    "2026-09-28": "9월 23일 판단은 유효하다. 그날 정한 무효화 선인 코스피 6,881은 오늘 종가로 지켜졌다. 다만 여유는 9포인트뿐이었고, 판단의 전제는 빗나갔다. 우리는 반도체가 지수를 떠받친다고 봤는데 오늘 지수를 끌어내린 것이 바로 반도체였다. 휴장 중 기다린 미·중 정상회담은 상호 관세 인하와 휴전 연장으로 정리됐지만, 오늘 가격을 움직인 것은 그사이 오른 미국 장기금리였다. 촉매를 정상회담으로 좁혀 보고 금리 경로를 놓친 것이 우리의 실수다. 기다린 외국인 순매수 복귀도 오지 않았다. 노출 등급은 유지하되, 근거를 반도체 주도에서 반도체 밖의 상승 폭으로 바꾼다.",
    "2026-09-29": "9월 28일 판단은 유효하다. 그날 정한 무효화 선인 코스피 6,832는 종가로 지켜졌고 여유는 39포인트였다. 다만 장중 저가는 그 선보다 49포인트 아래까지 내려가, 선을 지킨 것은 마지막 한 시간의 반등 덕이었다. 기다린 조건은 오지 않았다. 미국 10년물은 내려오지 않고 더 올랐고, 9월 수출입동향은 아직 나오지 않았다. 노출 등급은 유지하되 두 가지를 고친다. 무효화 선을 오늘의 60일선으로 옮기고, 대형주 매도를 금리 이월 하나로 읽던 근거에 대형주 고유 요인을 함께 올린다.",
    "2026-09-30": "9월 29일 판단은 유효하다. 그날 정한 무효화 선인 코스피 6,808은 종가로 지켜졌고 여유는 30포인트였으며, 장중 저가도 그 선 위였다. 기다린 조건은 아직 오지 않았다. 미국 8월 PCE와 9월 수출입동향은 이 보고서 마감 뒤에 나오고, 외국인 순매도는 2조원대로 기준을 크게 넘었다. 노출 등급은 유지하되 두 가지를 고친다. 무효화 선을 오늘의 60일선으로 옮기고, 매도 해석의 무게를 금리 이월에서 대형주 고유 요인 쪽으로 한 걸음 더 옮긴다.",
    "2026-10-01": "9월 30일 판단은 유효하다. 코스피 종가는 그날 정한 무효화 선인 6,795를 지켰고 여유는 176포인트였다. 장중 저가는 그 선을 잠시 밑돌았지만 기준은 종가다. 기다린 조건은 절반만 왔다. 마이크론 실적과 9월 반도체 수출은 반도체에 우호적으로 나왔고 외국인 순매도도 1조원 아래로 줄었지만, 미국 10년물은 8월 PCE 뒤에도 내려오지 않고 더 올랐다. 노출 등급은 유지하되 두 가지를 고친다. 무효화 선을 20일선으로 올리고, 질문을 외국인 매도의 원인에서 이익 재료가 금리 부담을 이기는가로 옮긴다. 어제 대형 반도체 고유 요인 쪽에 무게를 둔 해석은, 금리가 오른 날 두 대형주가 함께 반등하면서 힘을 잃었다.",
}


@pytest.mark.parametrize("date", sorted(REAL_REVIEWS))
def test_real_review_still_flags_grade_talk_then_passes_without_it(date):
    original = REAL_REVIEWS[date]
    assert any("노출 등급 말투" in x for x in check(_html({"review": original}), STANCE, EVAL))
    stripped = original.replace("노출 등급은 유지하되, ", "").replace("노출 등급은 유지하되 ", "")
    assert "노출" not in stripped
    assert check(_html({"review": stripped}), STANCE, EVAL) == []


@pytest.mark.parametrize("review", [
    "10월 1일 판단은 유효하다. 코스피 종가는 그날 정한 무효화 선인 6,855를 넉넉히 지켰다. "
    "기다린 조건은 일부만 왔다. 판단은 그대로 두고 두 가지를 고친다.",
])
def test_review_without_grade_wording_still_speaks_the_verdict(review):
    assert check(_html({"review": review}), STANCE, EVAL) == []


def test_invalidation_level_must_appear_in_prose():
    v = check(_html({"invalidation": "60일선을 내주면 판단을 다시 본다."}), STANCE, EVAL)
    assert any("원장 레벨 6,904" in x for x in v)


def test_review_must_speak_the_verdict():
    v = check(_html({"review": "지난 회차는 반도체 이야기를 했다. 오늘도 반도체가 주도했다."}),
              STANCE, EVAL)
    assert any("§2 review" in x for x in v)


def test_review_accepts_broken_verdict_language():
    broken = {"verdict": "무효화", "prior_date": "2026-09-21"}
    ok = _html({"review": "어제 세운 6,904 무효화 조건이 오늘 발동해 그 판단은 폐기한다. "
                          "기관 순매수가 이어진다고 본 것이 틀렸고, 다시 세운 근거는 "
                          "아래 무효화 문단에 레벨과 함께 적었다."})
    assert check(ok, STANCE, broken) == []


def test_bootstrap_verdict_language():
    boot = {"verdict": "판정불가"}
    ok = _html({"review": "어제와 비교할 직전 판단이 없어 오늘은 판정할 수 없다. "
                          "오늘 적은 판단이 첫 기록이고, 무효화 레벨이 실제로 지켜지는지는 "
                          "다음 거래일부터 복기한다."})
    assert check(ok, STANCE, boot) == []


def test_bootstrap_cue_is_not_ledger_jargon():
    """「원장」은 작업 어휘다 — 판정 신호로 받아 주면 작성자가 본문에 원장 이야기를 쓴다
    (2026-09-23 「판단 원장에는 오늘과 비교할 직전 판단이 없다」)."""
    boot = {"verdict": "판정불가"}
    jargon = _html({"review": "판단 원장에는 기록이 남아 있지 않다. 부트스트랩 상태라 "
                              "기계 채점은 내일부터 이뤄지고 오늘은 판단을 그대로 둔다."})
    assert any("판정불가" in x for x in check(jargon, STANCE, boot))


def test_helpers():
    seg = section_slice(_html())
    assert "딴 얘기" not in seg
    assert [k for k, _ in marked(seg)][0] == "event"
    assert numbers("6,904를 7,007.72 로") == {6904.0, 7007.72}


# --- 실행 조건의 유동성 근거 (2026-09-22) ---

from kr.stance_gate import check_expression, liquidity_index  # noqa: E402

TOP = [{"label": "반도체 테마 ETF", "value": 1533260,
        "members": ["KODEX 반도체", "TIGER 반도체"]},
       {"label": "삼성전자", "value": 6043124, "members": ["삼성전자"]}]
IDX_ETF = [{"name": "KODEX 200", "value": 2120429}]
LIQ = liquidity_index(TOP, IDX_ETF)


def test_liquidity_index_covers_labels_members_and_index_etfs():
    assert LIQ["반도체 테마 ETF"] == 1533260
    assert LIQ["KODEX 반도체"] == 1533260      # 구성종목은 묶인 합계를 가리킨다
    assert LIQ["KODEX 200"] == 2120429


def test_expression_matching_collected_value_passes():
    st = {**STANCE, "expression": {"instrument": "KODEX 200", "value": 2120429}}
    assert check_expression(st, LIQ) == []


def test_expression_with_invented_value_is_caught():
    st = {**STANCE, "expression": {"instrument": "KODEX 200", "value": 3000000}}
    v = check_expression(st, LIQ)
    assert any("수집값은 2,120,429" in x for x in v)


def test_expression_with_unknown_instrument_is_caught():
    st = {**STANCE, "expression": {"instrument": "KODEX 코스닥150", "value": 1}}
    assert any("거래대금 자료에 없다" in x for x in check_expression(st, LIQ))


def test_expression_skipped_on_watch_only_day():
    assert check_expression(STANCE, LIQ) == []


def test_expression_skipped_when_liquidity_data_missing():
    st = {**STANCE, "expression": {"instrument": "KODEX 200", "value": 1}}
    assert check_expression(st, {}) == []


def test_check_threads_liquidity_through():
    st = {**STANCE, "expression": {"instrument": "KODEX 200", "value": 999}}
    assert any("§2 action" in x for x in check(_html(), st, EVAL, LIQ))
    assert check(_html(), {**st, "expression": {"instrument": "KODEX 200",
                                                "value": 2120429}}, EVAL, LIQ) == []
