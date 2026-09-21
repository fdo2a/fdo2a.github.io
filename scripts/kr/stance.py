"""판단 원장 — 어제 무엇을 판단했고 그게 맞았는지.

KR 브리프는 2026-09-21까지 **판단을 다음 날로 넘기는 장치가 없었다.** 그래서 매일
처음부터 다시 판단했고, 「어제 판단을 유지·수정·폐기한다」는 문장을 쓸 근거가 없었다.
US 는 `stance.json`·`stance_eval.json` 이 그 일을 한다 — 이 모듈이 KR 판이다.

핵심은 **무효화 조건을 기계가 검산할 수 있는 모양으로 적어 두는 것**이다. 2026-09-21
발행본은 「코스피가 60일 이동평균(6,904)을 지키는 동안 유효」라고 썼다. 레벨과 방향을
숫자로 남겨 두면 다음 날 종가 하나로 판정이 끝난다. 산문으로만 적어 두면 다음 날
작성자가 제 기억으로 「대체로 맞았다」를 쓰게 되고, 그건 복기가 아니다.

Pure — 파일 입출력은 collect_kr_data.py 가 맡는다.
"""

EXPOSURES = ("확대", "유지", "축소")
HORIZONS = ("다음 세션", "2~6주")
SIDES = ("below", "above")
METRICS = ("KOSPI", "KOSDAQ")
# 판단 한 줄·기대 차이 한 줄이 이보다 짧으면 내용이 없는 것이다.
MIN_TEXT = 20
# 산문이 아니라 필드로 남기는 것들. 대안 설명(C)과 실행 조건(E)이 여기 들어온다.
# 산문에만 적어 두면 다음 회차가 「대체로 그랬다」로 넘어간다 — 무효화 레벨을 수로
# 남기게 한 것과 같은 이유다.
TEXT_FIELDS = ("thesis", "gap", "alternative", "distinguisher")
# 관찰만 하는 날도 정상이다. 그때 instrument 는 비우고 wait_for 에 기다릴 조건을 쓴다
# (2026-09-22 사용자 지시 — 「아이디어를 매일 억지로 만들지 않는다」).
WATCH_ONLY = "관찰"


def validate(stance) -> list:
    """작성자가 낸 다음 회차 판단이 원장에 들어갈 모양인가. 위반을 한 줄씩."""
    v = []
    if not isinstance(stance, dict):
        return ["판단 원장이 객체가 아니다"]
    if not stance.get("date"):
        v.append("date 가 없다")
    if stance.get("exposure") not in EXPOSURES:
        v.append(f"exposure 는 {'·'.join(EXPOSURES)} 중 하나여야 한다 — {stance.get('exposure')!r}")
    if stance.get("horizon") not in HORIZONS:
        v.append(f"horizon 은 {'·'.join(HORIZONS)} 중 하나여야 한다 — {stance.get('horizon')!r}")
    for key in TEXT_FIELDS:
        text = (stance.get(key) or "").strip()
        if len(text) < MIN_TEXT:
            v.append(f"{key} 가 {MIN_TEXT}자에 못 미친다 — 판단을 한 줄로 적는다")
    v += _check_expression(stance)
    inv = stance.get("invalidation")
    if not isinstance(inv, dict):
        v.append("invalidation 이 없다 — 틀렸다고 볼 조건을 숫자로 남긴다")
        return v
    if inv.get("metric") not in METRICS:
        v.append(f"invalidation.metric 은 {'·'.join(METRICS)} 중 하나여야 한다 — {inv.get('metric')!r}")
    if inv.get("side") not in SIDES:
        v.append(f"invalidation.side 는 below·above 중 하나여야 한다 — {inv.get('side')!r}")
    try:
        float(inv["level"])
    except (KeyError, TypeError, ValueError):
        v.append("invalidation.level 이 수가 아니다 — 산문의 레벨을 그대로 적는다")
    return v


def _check_expression(stance) -> list:
    """실행 조건 — 어떤 상품으로 표현하고, 무엇을 기다리는가.

    상품을 대면 **유동성 근거를 수로** 함께 낸다. 거래대금 없이 종목만 적는 것은
    데스크 정보를 흉내 내는 것이고, 관측할 수 없는 것을 관측한 척하지 않는 게 이
    리포트의 규율이다. 상품을 안 대는 날(관찰만)도 정상이라 instrument 는 비워도
    되지만, 그때는 wait_for 가 무엇을 기다리는지 반드시 말해야 한다.
    """
    exp = stance.get("expression")
    wait = (stance.get("wait_for") or "").strip()
    v = []
    if len(wait) < MIN_TEXT:
        v.append(f"wait_for 가 {MIN_TEXT}자에 못 미친다 — "
                 "진입을 기다릴 조건이나 관찰만 하는 이유를 적는다")
    if exp in (None, {}, ""):
        return v                       # 관찰만 하는 날 — 상품을 대지 않는다
    if not isinstance(exp, dict):
        return v + ["expression 이 객체가 아니다"]
    if not (exp.get("instrument") or "").strip():
        v.append("expression.instrument 가 비었다 — 상품을 대지 않을 거면 expression 을 뺀다")
    try:
        if float(exp["value"]) <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        v.append("expression.value 가 수가 아니다 — 그 상품의 거래대금(백만원)을 "
                 "kr_top_value·kr_index_etf 에서 그대로 옮긴다")
    return v


def evaluate(prior, indices) -> dict:
    """어제 판단의 무효화 조건을 오늘 종가로 판정한다.

    판정은 셋뿐이다. `유효`(조건 미발동) · `무효화`(발동) · `판정불가`(원장이 없거나
    지수가 결측). **「대체로 맞았다」는 없다** — 조건을 숫자로 적어 둔 이유가 그거다.
    """
    if not prior:
        return {"verdict": "판정불가", "note": "직전 판단 원장이 없다 — 이번 회차가 첫 기록이다"}
    inv = (prior or {}).get("invalidation") or {}
    metric, side = inv.get("metric"), inv.get("side")
    try:
        level = float(inv["level"])
    except (KeyError, TypeError, ValueError):
        return {"verdict": "판정불가", "prior_date": prior.get("date"),
                "note": "직전 원장에 무효화 레벨이 수로 남아 있지 않다"}
    close = ((indices or {}).get(metric) or {}).get("close")
    if close is None:
        return {"verdict": "판정불가", "prior_date": prior.get("date"),
                "metric": metric, "level": level, "side": side,
                "note": f"{metric} 종가가 결측이라 판정할 수 없다"}
    broken = close < level if side == "below" else close > level
    where = "아래로" if side == "below" else "위로"
    kept = "밑돌아" if side == "below" else "웃돌아"
    return {
        "verdict": "무효화" if broken else "유효",
        "prior_date": prior.get("date"),
        "prior_exposure": prior.get("exposure"),
        "prior_horizon": prior.get("horizon"),
        "prior_thesis": prior.get("thesis"),
        "metric": metric, "level": level, "side": side, "observed": close,
        "note": (f"{metric} 종가 {close:,.2f} 가 {level:,.2f} 를 {kept} 무효화 조건이 발동했다"
                 if broken else
                 f"{metric} 종가 {close:,.2f} 로 {level:,.2f} 를 {where} 깨지 않았다"),
    }
