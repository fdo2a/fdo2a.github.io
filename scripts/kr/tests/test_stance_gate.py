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
    "action": "위험 노출은 유지한다. 시계는 다음 세션이다.",
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


def test_action_must_name_grade_and_horizon():
    v = check(_html({"action": "당분간 지켜본다."}), STANCE, EVAL)
    assert any("노출을" in x for x in v) and any("시계" in x for x in v)


def test_action_grade_must_match_ledger():
    v = check(_html({"action": "위험 노출은 축소한다. 시계는 다음 세션이다."}), STANCE, EVAL)
    assert any("원장은 유지" in x for x in v)


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
