"""§2 전략 코멘트 게이트 — 판단이 원장과 같은 말을 하는가.

2026-09-22 사용자 지시로 §2 가 네 문단에서 여섯으로 늘었다. 늘린 이유는 서식을 하나
더 채우려는 게 아니라, **판단을 다음 날이 검산할 수 있게 만들려는 것**이다. 그래서
게이트가 보는 것은 문단 개수가 아니라 **산문과 원장의 일치**다.

  · 여섯 블록이 순서대로 있는가
  · `action` 이 노출 등급과 시계를 밝혔고 원장의 exposure·horizon 과 같은가
  · `invalidation` 산문에 적힌 레벨이 원장의 level 과 같은 수인가
  · `review` 가 어제 판정(kr_stance_eval.json)을 실제로 반영했는가

마지막 항목이 핵심이다. 「대체로 맞았다」를 막으려고 레벨을 수로 남기게 했는데,
산문이 그 판정을 무시하면 원장은 장식이 된다 — 게이트가 읽는 문장과 독자가 보는
문장이 갈리는 자리다.

Pure — HTML 문자열과 dict 둘을 받아 위반 목록을 돌려준다.
"""
import re

from kr.stance import EXPOSURES, HORIZONS

ORDER = ("event", "gap", "meaning", "action", "invalidation", "review")
SECTION = "전략 코멘트"
MIN_CHARS = {"gap": 80, "review": 80}
_TAG = re.compile(r"<[^>]+>")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 판정이 「유효」면 유지·수정, 「무효화」면 수정·폐기를 말해야 한다. 어느 쪽이든
# 판정 자체를 입에 담지 않고 지나가는 것이 제일 흔한 회피다.
VERDICT_CUES = {
    "유효": ("유지", "그대로", "이어간다", "수정", "조정"),
    "무효화": ("무효", "폐기", "수정", "바꾼다", "접는다", "틀렸"),
    "판정불가": ("첫", "원장", "판정할 수 없", "비교할 직전", "부트스트랩"),
}


def section_slice(html_doc: str):
    """§2 구간만 잘라낸다. 제목으로 찾는다 — 번호는 섹션이 늘면 밀린다."""
    m = re.search(r"<h2>\s*%s\s*</h2>" % re.escape(SECTION), html_doc)
    if not m:
        return None
    rest = html_doc[m.end():]
    nxt = re.search(r"<h2>", rest)
    return rest[: nxt.start()] if nxt else rest


def marked(seg: str) -> list:
    """[(표식, 본문텍스트)] — 문서에 나온 순서대로."""
    out = []
    for m in re.finditer(r'<p[^>]*data-lede="([a-z]+)"[^>]*>(.*?)</p>', seg, re.S):
        out.append((m.group(1), _TAG.sub("", m.group(2)).strip()))
    return out


def numbers(text: str) -> set:
    """산문의 수를 float 집합으로. 천단위 콤마를 걷어낸다."""
    out = set()
    for tok in _NUM.findall(text or ""):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            continue
    return out


def liquidity_index(top_value, index_etf) -> dict:
    """{상품명: 거래대금} — 상위 표의 라벨·구성종목과 지수·해외 ETF 를 한데 모은다.

    실행 조건이 대는 상품의 유동성 근거는 **수집된 값이어야 한다.** 이 대조가 없으면
    작성자가 거래대금을 지어내도 게이트가 통과시키고, 그러면 「유동성 근거를 수로
    낸다」는 규율은 장식이 된다.
    """
    out = {}
    for row in (top_value or []):
        value = row.get("value")
        if value is None:
            continue
        for name in [row.get("label")] + list(row.get("members") or []):
            if name:
                out.setdefault(name, value)
    for row in (index_etf or []):
        if row.get("name") and row.get("value") is not None:
            out.setdefault(row["name"], row["value"])
    return out


def check_expression(stance: dict, liquidity: dict) -> list:
    """실행 조건이 댄 상품과 거래대금이 수집된 값과 맞는가.

    구성종목으로 묶인 줄은 라벨이 합계라, 구성종목 이름을 대면 그 종목의 몫이 아니라
    합계가 잡힌다 — 그래서 라벨을 먼저 심고 `setdefault` 로 덮어쓰지 않는다.
    """
    exp = (stance or {}).get("expression")
    if not isinstance(exp, dict) or not exp.get("instrument"):
        return []                       # 관찰만 하는 날 — 댈 상품이 없다
    if not liquidity:
        return []                       # 거래대금 자료가 결측인 날은 대조하지 않는다
    name = exp["instrument"].strip()
    if name not in liquidity:
        return [f"§2 action: 상품 「{name}」이 거래대금 자료에 없다 — "
                "kr_top_value·kr_index_etf 에 있는 이름으로 댄다"]
    try:
        given = float(exp.get("value"))
    except (TypeError, ValueError):
        return [f"§2 action: 「{name}」의 거래대금이 수가 아니다"]
    actual = float(liquidity[name])
    if abs(given - actual) > 0.5:
        return [f"§2 action: 「{name}」 거래대금이 원장 {given:,.0f} 인데 "
                f"수집값은 {actual:,.0f} 이다 — 수집된 값을 그대로 옮긴다"]
    return []


def check(html_doc: str, stance: dict, stance_eval: dict, liquidity=None) -> list:
    seg = section_slice(html_doc)
    if seg is None:
        return [f"섹션 「{SECTION}」을 찾지 못했다"]
    got = marked(seg)
    keys = [k for k, _ in got]
    v = [f"§2: data-lede=\"{k}\" 문단이 없다" for k in ORDER if k not in keys]
    if v:
        return v
    ordered = [k for k in keys if k in ORDER]
    if ordered != list(ORDER):
        v.append(f"§2: 문단 순서가 {'→'.join(ORDER)} 가 아니다 — {'→'.join(ordered)}")

    body = dict(got)
    for key, need in MIN_CHARS.items():
        if len(body.get(key, "")) < need:
            v.append(f"§2 {key}: {need}자에 못 미친다 — 자리만 채웠다")

    action = body.get("action", "")
    grade = [g for g in EXPOSURES if g in action]
    if not grade:
        v.append(f"§2 action: 노출을 {'·'.join(EXPOSURES)} 중 하나로 밝히지 않았다")
    elif stance and stance.get("exposure") and stance["exposure"] not in grade:
        v.append(f"§2 action: 산문은 {grade} 인데 원장은 {stance['exposure']} 다")
    if not any(h in action for h in HORIZONS):
        v.append(f"§2 action: 시계({'·'.join(HORIZONS)})를 밝히지 않았다")

    level = ((stance or {}).get("invalidation") or {}).get("level")
    if level is not None:
        try:
            level = float(level)
        except (TypeError, ValueError):
            v.append("원장 invalidation.level 이 수가 아니다")
            level = None
    if level is not None and level not in numbers(body.get("invalidation", "")):
        v.append(f"§2 invalidation: 원장 레벨 {level:,.0f} 이 산문에 없다 — 둘이 갈리면 검산이 안 된다")

    v += check_expression(stance, liquidity or {})

    verdict = (stance_eval or {}).get("verdict")
    if verdict:
        review = body.get("review", "")
        if not any(cue in review for cue in VERDICT_CUES.get(verdict, ())):
            v.append(f"§2 review: 어제 판정이 「{verdict}」인데 산문이 그것을 말하지 않는다")
    return v
