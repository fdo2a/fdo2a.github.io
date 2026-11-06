"""§2 전략 코멘트 게이트 — 판단이 원장과 같은 말을 하는가.

2026-09-22 사용자 지시로 §2 가 네 문단에서 여섯으로 늘었다. 늘린 이유는 서식을 하나
더 채우려는 게 아니라, **판단을 다음 날이 검산할 수 있게 만들려는 것**이다. 그래서
게이트가 보는 것은 문단 개수가 아니라 **산문과 원장의 일치**다.

  · 여섯 블록이 순서대로 있는가
  · 본문에 노출 등급 말투가 없는가 — 등급·시계는 원장에만 남는다(2026-10-04 사용자 결정,
    `kr.grade_talk`). 전에는 action 이 등급과 시계를 밝히고 원장과 같아야 했는데, 그 계약이
    「코스피 노출은 다음 세션까지 유지한다」라는 독자가 읽을 수 없는 문장을 매일 만들었다.
  · `invalidation` 산문에 적힌 레벨이 원장의 level 과 같은 수인가
  · `review` 가 어제 판정(kr_stance_eval.json)을 실제로 반영했는가

마지막 항목이 핵심이다. 「대체로 맞았다」를 막으려고 레벨을 수로 남기게 했는데,
산문이 그 판정을 무시하면 원장은 장식이 된다 — 게이트가 읽는 문장과 독자가 보는
문장이 갈리는 자리다.

Pure — HTML 문자열과 dict 둘을 받아 위반 목록을 돌려준다.
"""
import datetime
import re

from fund.gate import _Doc, _hidden   # 숨김·주석·엔티티를 브라우저처럼 — 펀드 게이트와 같은 규칙
from kr import grade_talk

ORDER = ("event", "gap", "meaning", "action", "invalidation", "review")   # 옛 배치(v1)
SECTION = "전략 코멘트"
# 2026-10-20 배치(v2) — 외부 평가(10/19 발행본)가 「같은 결론을 네다섯 곳에서 되풀이하고 복기가 뉴스
# 뒤로 밀렸다」고 짚었다. §2 는 다섯 문단, 어제 판단의 판정(review)은 「시장 판단과 복기」 첫
# 문단으로 가서 연구 가설의 기간 검증과 한자리에서 갈린다(10/19 「무효화됐다」와 「10월 21일에
# 판정한다」가 두 섹션에 갈라져 모순처럼 읽혔다). 다음 확인 일정은 「향후 확인 일정」 표 한 장.
ORDER_V2 = ORDER[:-1]
LEARNING = "시장 판단과 복기"
SCHEDULE = "향후 확인 일정"
NEWS = "오늘의 뉴스"
LAYOUT_V2_FROM = "2026-10-20"
# 표의 첫 칸은 독자가 달력에 옮길 수 있는 시점이어야 한다 — 「곧」「다음에」는 일정이 아니다.
_WHEN = re.compile(r"\d{1,2}월|\d{1,2}/\d{1,2}|\d{4}-\d{2}|이달|다음 달|다음 주|이번 주|월말|연내|연말|"
                   r"분기|실적 발표|일정 미확정|마감|개장")
# gap·review 는 길이가 아니라 내용으로 본다(2026-11-06 사용자 결정 「60자로 충분히 설명되는
# 내용을 80자로 늘리면 문장만 길어진다」 — 옛 하한은 각 80자). 자리 채움은 「두 어절 이상에
# -다 로 끝나는 문장」이 하나도 없는 것이고, 판정 근거는 아래 `_basis_violation` 이 본다.
PROSE_KEYS = ("gap", "review")
# 「-다」 앞에 글자가 있어야 하고(「시장 다」는 문장이 아니다), 닫는 따옴표·괄호와 꼬리 괄호
# (「…부담이다」.·「…이다(추정).」)는 받는다(codex 구현 검토 #1).
_SENTENCE = re.compile(r"\S+\s+\S*[가-힣]다[.!]?[」』\"'’”)\]]*(?:\([^)]*\))?[.!]?(?=\s|$)")
# 판정 근거는 지수 레벨이다 — 금액·비율·건수 단위가 붙은 수는 레벨이 아니다
# (「외국인 6,904억원 매도」가 6,904 레벨로 통과하던 길, codex 구현 검토 #2). 「6,904일 때」의
# 「일」은 날수가 아니다(codex 5차).
_LEVEL_NUM = re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)(?![\d,]|\.\d)(?!\s*(?:억|조|만|천|원|%|bp|배|주|건|명|달러|엔|위안|개|곳|일(?!\s*(?:때|경우))|거래일|종목))")
METRIC_NAMES = {"KOSPI": ("코스피", "KOSPI"), "KOSDAQ": ("코스닥", "KOSDAQ"),
                "KOSPI200": ("코스피200", "KOSPI200")}
# 레벨이 지수와 같은 자릿수일 수 있는 다른 시장 — 기준선 단어만 있는 문장이 이 이름을 부르면
# 그 수는 판정한 지수의 값으로 받지 않는다(codex 최종 검토 C 「미국 증시는 전일 고점 6,904」).
# 금리·유가는 자릿수가 달라 넣지 않는다.
OTHER_MARKETS = ("미국", "뉴욕", "S&P", "나스닥", "다우", "러셀", "필라델피아", "SOX", "유럽",
                 "유로스톡스", "DAX", "닥스", "FTSE", "닛케이", "니케이", "토픽스", "TOPIX", "일본",
                 "상하이", "중국", "항셍", "홍콩", "대만", "자취안", "인도", "환율", "원달러",
                 "달러", "엔화", "위안")
# 「코스피 200」「코스닥 150」처럼 띄어 쓴 하위 지수를 붙여 쓴 꼴로 맞춘다.
_SUB_INDEX = re.compile(r"(코스피|KOSPI|코스닥|KOSDAQ)\s+(200|150|100|50)(?![\d,])")
# 기준선을 부르는 말 — 「무효화 선」「철회 기준」「60일 이동평균」「볼린저 밴드 하단」「20일 저점」.
LEVEL_CUES = ("무효화", "철회 기준", "반증", "기준선", "이동평균", "밴드", "전환선", "저점", "고점", "선인", "선을", "선 ")
# 반올림한 산문 값을 받는다 — 지수는 정수로 쓴다(STYLE_EXEMPLARS 「산문 수치는 반올림」).
BASIS_TOLERANCE = 0.5
_TAG = re.compile(r"<[^>]+>")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 판정이 「유효」면 유지·수정, 「무효화」면 수정·폐기를 말해야 한다. 어느 쪽이든
# 판정 자체를 입에 담지 않고 지나가는 것이 제일 흔한 회피다.
VERDICT_CUES = {
    "유효": ("유효", "지켰", "유지", "그대로", "이어간다", "수정", "조정"),
    "무효화": ("무효", "폐기", "수정", "바꾼다", "접는다", "틀렸", "철회"),
    "판정불가": ("첫", "판정할 수 없", "비교할 직전"),
}
# 「철회」는 2026-10-13 추가 — 보고서 문체(STYLE_EXEMPLARS §10)가 「접는다」 대신 권하는 말이다.
# 「원장」「부트스트랩」은 신호에서 뺐다(2026-09-24) — 작업 어휘를 신호로 받아 주면 작성자가
# 본문에 원장 이야기를 쓴다. 데스크 문서의 작업 어휘는 check_style 이 막는다.


def section_slice(html_doc: str, title: str = SECTION):
    """제목이 `title` 인 h2 다음부터 다음 h2 까지. 번호는 섹션이 늘면 밀린다."""
    m = re.search(r"<h2[^>]*>\s*%s\s*</h2>" % re.escape(title), html_doc)
    if not m:
        return None
    rest = html_doc[m.end():]
    nxt = re.search(r"<h2[\s>]", rest)
    return rest[: nxt.start()] if nxt else rest


def parse_day(value):
    """「YYYY-MM-DD」 달력 날짜만 date 로, 아니면 None."""
    text = str(value or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def layout(html_doc: str, report_date=None) -> str:
    """'v1'(§2 여섯 문단) 또는 'v2'(§2 다섯 + 복기 첫 문단 review).

    적용일부터는 **날짜가 정한다** — 작성자가 옛 배치로 돌아가 review 를 §2 에 남기면 막힌다.
    그 전 글은 생김새로 고른다: 정정 러너가 옛 글을 다시 검사해도 새 계약으로 막지 않는다.
    """
    if report_date:
        day = parse_day(report_date)
        # 형식이 틀린 날짜는 새 계약으로 — 문자열 비교로는 「2026-10-19junk」가 옛 배치를 골랐다
        if day is None or day >= parse_day(LAYOUT_V2_FROM):
            return "v2"
    seg = section_slice(html_doc) or ""
    return "v1" if any(k == "review" for k, _ in marked(seg)) else "v2"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _headed(doc, title):
    """[(h2, 그 h2 를 감싼 section)] — 제목은 숨겨져 있어도 찾는다(숨김은 따로 판정)."""
    out = []
    for n in doc.nodes:
        if n.tag == "h2" and _norm("".join(n.raw)) == title:
            out.append((n, next((a for a in n.ancestors() if a.tag == "section"), None)))
    return out


def _inside(node, sec):
    """가장 가까운 section 이 `sec` 인가 — 안에 끼운 하위 section 의 문단·표는 그 섹션 것이 아니다
    (codex 2차 구현 검토 2026-10-20 #2)."""
    return next((a for a in node.ancestors() if a.tag == "section"), None) is sec


def _owned(doc, node, head, sec):
    """`head` 제목이 거느린 요소인가 — 같은 section 안, 그 제목 뒤, 다음 h2 앞(codex 3차 #1)."""
    if not _inside(node, sec) or node.start <= head.start:
        return False
    return not any(n.tag == "h2" and n is not head and head.start < n.start < node.start
                   and any(a is sec for a in n.ancestors()) for n in doc.nodes)


def _one_section(doc, title, v, what):
    found = _headed(doc, title)
    if not found:
        v.append(f"섹션 「{title}」{what}")
        return None, None
    if len(found) > 1:
        v.append(f"「{title}」 제목이 {len(found)}개다 — 섹션은 하나")
    h, sec = found[0]
    if sec is None:
        v.append(f"「{title}」 제목이 <section> 안에 있지 않다")
        return None, None
    if _hidden(h) or _hidden(sec):
        v.append(f"「{title}」 섹션이 독자에게 보이지 않는다(숨김·접힘)")
    return h, sec


def check_layout_v2(html_doc: str) -> tuple:
    """(위반, review 본문). v2 배치의 위치·표 계약.

    **브라우저가 읽는 대로 읽는다**(fund.gate 의 파서 — 주석은 버리고, 엔티티를 풀고, hidden·
    display:none·닫힌 details·template 조상을 숨김으로 본다). 정규식 구간(다음 h2 까지)으로 읽던
    첫 판은 주석 속 review, 다음 형제 section 으로 밀어낸 표, `&nbsp;` 칸을 통과시켰다
    (codex 구현 검토 2026-10-20 #1~#3).
    """
    v = []
    doc = _Doc(html_doc, "data-no-block")
    # 같은 속성이 두 번이면 브라우저는 첫 값을, 파서는 끝 값을 쓴다 — `style="display:none" style=""` 로
    # 숨긴 review 가 보이는 것으로 읽혔다(codex 2차 구현 검토 #1). 두 섹션과 그 조상에서는 받지 않는다.
    for title in (LEARNING, SCHEDULE):
        for h, sec in _headed(doc, title):
            if sec is None:
                continue
            scope = [n for n in doc.nodes if any(a is sec for a in n.ancestors())]
            if any(n.dup for n in scope + list(sec.ancestors())):
                v.append(f"「{title}」: 같은 속성이 두 번 붙은 요소가 있다 — 브라우저와 해석이 갈린다")
    learn_h, learn = _one_section(doc, LEARNING, v, "를 찾지 못했다 — 어제 판단의 판정(review)이 들어갈 자리다")
    review = ""
    if learn is not None:
        marks = [n for n in doc.nodes if n.tag == "p" and n.attrs.get("data-lede") == "review"]
        mine = [n for n in marks if _owned(doc, n, learn_h, learn)]
        seen = [n for n in mine if not _hidden(n)]
        if any(_hidden(n) for n in mine):
            v.append(f"「{LEARNING}」: review 문단이 독자에게 보이지 않는다(숨김·접힘) — 펼친 본문 문단으로 쓴다")
        if not seen:
            v.append(f"「{LEARNING}」: data-lede=\"review\" 문단이 없다 — 어제 판단의 판정을 "
                     "이 섹션 첫 문단에 쓴다")
        elif len(seen) > 1:
            v.append(f"「{LEARNING}」: review 문단이 {len(seen)}개다 — 어제 판단의 판정은 문단 하나로")
        else:
            review = seen[0].plain()
            first = next((n for n in doc.nodes
                          if n.tag == "p" and _owned(doc, n, learn_h, learn) and not _hidden(n) and n.plain()
                          and not set(n.attrs.get("class", "").split()) & {"caption", "muted", "sub"}),
                         None)
            if first is not seen[0]:
                v.append(f"「{LEARNING}」: review 문단이 첫 문단이 아니다 — 어제 판단이 어떻게 됐는지를 "
                         "먼저 말하고 열린 가설을 잇는다")
    sched_h, sched = _one_section(doc, SCHEDULE, v, "이 없다 — 다음 확인 일정은 표 한 장으로 모은다")
    if sched is not None:
        tables = [n for n in doc.nodes if n.tag == "table" and _owned(doc, n, sched_h, sched) and not _hidden(n)]
        rows = []
        if tables:
            t = tables[0]
            for tr in (n for n in doc.nodes if n.tag == "tr" and any(x is t for x in n.ancestors())):
                if any(a.tag == "thead" for a in tr.ancestors()):
                    continue
                cells = [n for n in doc.nodes if n.tag in ("td", "th") and n.parent is tr]
                if not cells or all(c.tag == "th" for c in cells):
                    continue                    # thead 없이 쓴 머리 행
                rows.append([c.plain() for c in cells])
        if not rows:
            v.append(f"「{SCHEDULE}」: 표 본문 행이 없다 — `시점 | 확인할 것 | 가르는 판단` 표(<table>)로 쓴다")
        elif not 2 <= len(rows) <= 6:
            v.append(f"「{SCHEDULE}」: 본문 행이 {len(rows)}개다 — 2~6행(가장 가까운 결정적 확인부터)")
        for cells in rows:
            if len(cells) != 3:
                v.append(f"「{SCHEDULE}」: 「{cells[0]}」 행이 {len(cells)}칸이다 — 세 칸(시점·확인할 것·가르는 판단)")
            elif not all(cells):
                v.append(f"「{SCHEDULE}」: 「{cells[0]}」 행에 빈 칸이 있다")
            if not cells[0] or not _WHEN.search(cells[0]):
                v.append(f"「{SCHEDULE}」: 첫 칸 「{cells[0]}」이 시점이 아니다 — 날짜·「이달 말」·"
                         "「일정 미확정」처럼 쓴다")
    news = _headed(doc, NEWS)
    news_sec = news[0][1] if news and news[0][1] is not None else None
    if news_sec is not None:
        for t, sec in ((LEARNING, learn), (SCHEDULE, sched)):
            if sec is not None and sec.start > news_sec.start:
                v.append(f"「{t}」{'는' if t == LEARNING else '은'} 「{NEWS}」보다 앞에 둔다 — "
                         "판단과 확인 일정이 본문, 뉴스는 참고 자료다")
    if learn is not None and sched is not None:
        between = [n for n in doc.nodes if n.tag == "section"
                   and learn.end <= n.start < sched.start]
        if sched.start < learn.end or between:
            v.append(f"「{SCHEDULE}」은 「{LEARNING}」 바로 뒤에 둔다")
    return v, review


def marked(seg: str) -> list:
    """[(표식, 본문텍스트)] — 문서에 나온 순서대로."""
    out = []
    for m in re.finditer(r'<p[^>]*data-lede="([a-z]+)"[^>]*>(.*?)</p>', seg, re.S):
        out.append((m.group(1), _TAG.sub("", m.group(2)).strip()))
    return out


def _names_re(names, longer):
    """이름 정규식 — 「코스피」는 「코스피200」의 앞부분일 때 잡지 않는다."""
    parts = []
    for n in sorted(names, key=len, reverse=True):
        tails = [e[len(n):] for e in longer if e != n and e.startswith(n)]
        parts.append(re.escape(n) + "".join(f"(?!{re.escape(t)})" for t in tails))
    return re.compile("|".join(parts) or r"(?!)")


def _market_patterns(metric):
    """(판정한 지수 이름, 다른 시장 이름) 정규식."""
    mine = METRIC_NAMES.get(metric, ())
    others = [n for k, ns in METRIC_NAMES.items() if k != metric for n in ns if n not in mine]
    others += OTHER_MARKETS
    return _names_re(mine, others), _names_re(others, mine)


def _basis_violation(where: str, review: str, stance_eval: dict) -> list:
    """유효·무효화 판정이면 그 판정을 만든 값(무효화 레벨·오늘 종가)이 복기에 있어야 한다.

    아무 숫자나 받지 않는다 — 「외국인 3,120억원」은 판정의 근거가 아니다(codex 설계 2차 #2).
    판정불가는 댈 값이 없으므로 보지 않는다(#1). 평가에 값이 없으면(옛 원장) 보지 않는다.
    """
    if (stance_eval or {}).get("verdict") not in ("유효", "무효화"):
        return []
    refs = {}
    for key, name in (("level", "무효화 레벨"), ("observed", "오늘 종가")):
        try:
            refs[name] = float(stance_eval[key])
        except (KeyError, TypeError, ValueError):
            continue
    if not refs:
        return []
    # 그 수가 판정한 지수나 그 기준선을 말하는 문장에 있어야 한다 — 「원달러 환율은 6,904로
    # 마감했다」는 근거가 아니다(codex 구현 재검토 #1).
    # 판정한 지수 이름이 있는 문장, 또는 기준선 단어가 있고 다른 시장을 부르지 않는 문장의 수만
    # 받는다. 문장 안에서 수의 주인까지 가리지는 않는다 — 이 검사는 근거를 빠뜨린 복기를 잡는
    # 것이고, 다른 시장의 수가 판정 값과 ±0.5 안에서 같은 문장에 오는 우연까지 막으려다 정상
    # 문장(「코스피는 미국 증시와 달리 6,904에 마감했다」)을 막았다(codex 4차, 사용자 원칙
    # 「문장은 필자의 재량」).
    mine, other = _market_patterns(stance_eval.get("metric"))
    said = set()
    for sentence in re.split(r"(?<=[.!?])\s+", review):
        sentence = _SUB_INDEX.sub(r"\1\2", sentence)
        if not (mine.search(sentence)
                or (any(c in sentence for c in LEVEL_CUES) and not other.search(sentence))):
            continue
        for tok in _LEVEL_NUM.findall(sentence):
            try:
                said.add(float(tok.replace(",", "")))
            except ValueError:
                continue
    if any(abs(n - r) <= BASIS_TOLERANCE for n in said for r in refs.values()):
        return []
    shown = " 이나 ".join(f"{name} {r:,.0f}" for name, r in refs.items())
    return [f"{where} review: 판정 근거가 없다 — {shown} 를 문장에 쓴다"]


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


_NEWS_LEFTOVER = ((re.compile(r"\bdata-news\s*=", re.I), "`data-news` 기사 블록"),
                  (re.compile(r"\bdata-summary\s*=", re.I), "`data-summary` 기사 요약 문단"),
                  (re.compile(r"<!--\s*CONTESTED\s*-->", re.I), "쟁점 분석 표식"),
                  (re.compile(r"\bdata-contested\s*=", re.I), "쟁점 분석 섹션"),
                  (re.compile(r"contested-(?:pending|omitted)", re.I), "쟁점 분석 자리표시"))


def news_split_violations(html_doc: str, report_date=None) -> list:
    """2026-11-06 부터 「오늘의 뉴스」와 쟁점 분석은 뉴스 글(kr/news) 몫이다 — 마감브리프에 다시 들어오면 막는다.
    속성은 HTML 이 허용하는 공백·대소문자까지 본다(codex 구현 검토 2026-11-06 #7). 그 전 글(정정 러너가 다시
    검사하는 옛 글)은 예전 계약 그대로다. 날짜가 없으면 새 계약으로 본다."""
    from kr.news import brief_carries_news
    if report_date and brief_carries_news(report_date):
        return []
    doc = html_doc or ""
    v = [f"마감브리프에 {what}이 있다 — {NEWS}·쟁점 분석은 뉴스 글에 싣는다"
         for rx, what in _NEWS_LEFTOVER if rx.search(doc)]
    if _headed(_Doc(doc, "data-no-block"), NEWS):
        v.append(f"마감브리프에 「{NEWS}」 섹션이 있다 — 뉴스 글에 싣는다")
    return v


def check(html_doc: str, stance: dict, stance_eval: dict, liquidity=None,
          report_date=None) -> list:
    seg = section_slice(html_doc)
    if seg is None:
        return [f"섹션 「{SECTION}」을 찾지 못했다"]
    got = marked(seg)
    keys = [k for k, _ in got]
    v2 = layout(html_doc, report_date) == "v2"
    order = ORDER_V2 if v2 else ORDER
    v = [f"§2: data-lede=\"{k}\" 문단이 없다" for k in order if k not in keys]
    if v:
        return v
    if v2 and "review" in keys:
        # 옛 배치로 쓴 날 — 옮길 자리(복기·일정)의 위반도 한 번에 보여 줘야 루틴이 한 바퀴에 고친다
        v.append(f"§2 에 review 문단이 남아 있다 — {LAYOUT_V2_FROM} 부터 어제 판단의 판정은 "
                 f"「{LEARNING}」 첫 문단에 쓴다")
        keys = [k for k in keys if k != "review"]
    ordered = [k for k in keys if k in order]
    if ordered != list(order):
        v.append(f"§2: 문단 순서가 {'→'.join(order)} 가 아니다 — {'→'.join(ordered)}")

    body = dict(got)
    if v2:
        lv, body["review"] = check_layout_v2(html_doc)
        v += lv
    where = LEARNING if v2 else "§2"
    for key in PROSE_KEYS:
        if key == "review" and v2 and not body.get(key):
            continue                    # 없는 것은 위에서 이미 말했다
        if not _SENTENCE.search(body.get(key, "")):
            label = f"「{LEARNING}」 review" if key == "review" and v2 else f"§2 {key}"
            v.append(f"{label}: 문장이 없다 — 자리만 채웠다")

    v += grade_talk.violations(html_doc, exempt_news=True)
    v += news_split_violations(html_doc, report_date)

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
        if review and not any(cue in review for cue in VERDICT_CUES.get(verdict, ())):
            v.append(f"{where} review: 어제 판정이 「{verdict}」인데 산문이 그것을 말하지 않는다")
        elif review:
            v += _basis_violation(where, review, stance_eval)
        elif not review and not v2:
            v.append(f"§2 review: 어제 판정이 「{verdict}」인데 산문이 그것을 말하지 않는다")
    return v
