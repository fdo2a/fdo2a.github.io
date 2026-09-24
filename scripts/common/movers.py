"""움직인 종목 — 무엇의 「왜」를 취재할지 고르고, 발행본이 다뤘는지 확인한다(US·KR 공통).

2026-09-24 사용자 결정: 「1,2를 업종으로 묶는 방법과 이상 문턱은 5%, 코스닥은 포함하지 말고
US도 적용하자」. ① 지수 기여(시총 × 등락률) 상위 2·하위 2, ② |등락| ≥ 5% 를 후보로 뽑아
(업종, 방향)으로 묶고 최대 5묶음을 남긴다. 기여 종목이 든 묶음이 먼저 자리를 잡는다.

기여도는 **선정에만** 쓴다 — 시총이 넥스트레이드 통합가·지연 값이라 근사이고, 본문에
인용할 수치가 아니다. 그래서 묶음 멤버에는 등락률·종가·거래대금만 내보낸다.

모집단 수집은 시장별이다 — KR `collect_kr_data.py`(코스피 거래대금 상위 60, KRX 종가),
US `scripts/us/movers_data.py`(S&P 500 중 달러 거래대금 상위 60).
설계: docs/superpowers/specs/2026-09-24-movers-design.md

Pure — 네트워크 없음.
"""
import re

THRESHOLD_PCT = 5.0
TOP_CONTRIB = 2
MAX_GROUPS = 5
UP, DOWN = "지수 기여 상위", "지수 기여 하위"
OUTLIER = "이상 등락"


def _score(r):
    cap = r.get("cap") or 0
    return cap * r["change_pct"] if cap > 0 else None


def select_candidates(rows, threshold=THRESHOLD_PCT, top_n=TOP_CONTRIB):
    """① 기여 상위·하위 top_n 과 ② |등락| ≥ threshold. 시총이 없는 종목은 ② 로만 뽑힌다."""
    rows = [r for r in rows if r.get("change_pct") is not None]
    scored = [(r, _score(r)) for r in rows]
    ups = sorted((x for x in scored if x[1] is not None and x[1] > 0), key=lambda x: -x[1])[:top_n]
    downs = sorted((x for x in scored if x[1] is not None and x[1] < 0), key=lambda x: x[1])[:top_n]
    reasons = {}
    for r, _ in ups:
        reasons.setdefault(r["name"], []).append(UP)
    for r, _ in downs:
        reasons.setdefault(r["name"], []).append(DOWN)
    for r in rows:
        if abs(r["change_pct"]) >= threshold:
            reasons.setdefault(r["name"], []).append(OUTLIER)
    out = []
    for r, s in scored:
        if r["name"] in reasons:
            out.append({"name": r["name"], "change_pct": r["change_pct"], "close": r.get("close"),
                        "value": r.get("value") or 0, "industry": r.get("industry"),
                        "reasons": reasons[r["name"]], "score": s})
    return out


def _is_contrib(c):
    return UP in c["reasons"] or DOWN in c["reasons"]


def group_movers(candidates, max_groups=MAX_GROUPS):
    """(업종, 방향)으로 묶는다. 업종을 모르면 그 종목 혼자 한 묶음이다."""
    groups = {}
    for c in candidates:
        direction = "up" if c["change_pct"] > 0 else "down"
        key = (c["industry"] or f'\x00{c["name"]}', direction)
        groups.setdefault(key, []).append(c)

    def member_order(c):
        return (0, -abs(c["score"] or 0)) if _is_contrib(c) else (1, -c["value"])

    def group_order(item):
        members = item[1]
        contrib = [c for c in members if _is_contrib(c)]
        if contrib:
            return (0, -max(abs(c["score"] or 0) for c in contrib))
        return (1, -sum(c["value"] for c in members))

    out = []
    for (industry, direction), members in sorted(groups.items(), key=group_order)[:max_groups]:
        members = sorted(members, key=member_order)
        reasons = []
        for c in members:
            for why in c["reasons"]:
                if why not in reasons:
                    reasons.append(why)
        out.append({"id": f"g{len(out) + 1}",
                    "industry": None if industry.startswith('\x00') else industry,
                    "direction": direction, "reasons": reasons,
                    "members": [{"name": c["name"], "change_pct": c["change_pct"],
                                 "close": c["close"], "value": c["value"]} for c in members]})
    return out


def build(report_date, universe, rows, industries=None, threshold=THRESHOLD_PCT,
          max_groups=MAX_GROUPS):
    """산출 파일 모양. `industries` 는 {종목명: 업종} — 후보만 조회해 넘긴다."""
    cands = select_candidates(rows, threshold)
    for c in cands:
        if industries is not None and not c.get("industry"):
            c["industry"] = industries.get(c["name"])
    return {"report_date": report_date, "universe": universe, "threshold_pct": threshold,
            "groups": group_movers(cands, max_groups)}


# ── 게이트 ─────────────────────────────────────────────────────────────────

_COMMENT = re.compile(r'<!--.*?-->', re.S)
_MARKED = re.compile(r'<p\b([^>]*\bdata-mover\s*=\s*["\'](g\d+)["\'][^>]*)>(.*?)</p\s*>',
                     re.S | re.I)
_HIDDEN = re.compile(r'\bhidden\b|display\s*:\s*none|visibility\s*:\s*hidden', re.I)
_TAG = re.compile(r'<[^>]+>')


def _variants(pct):
    """3.25 → {'3.25'}, 1.2 → {'1.2', '1.20'}, -5.0 → {'5', '5.0', '5.00'}."""
    a = abs(pct)
    out = {f'{a:.2f}', f'{a:.1f}' if round(a, 1) == a else f'{a:.2f}', repr(a)}
    out.add(f'{a:.2f}'.rstrip('0').rstrip('.'))
    return out


def check(html, movers, report_date):
    """묶음마다 `<p data-mover="gN">` 가 보이는 곳에 있고, 대표 종목 등락률이 그 문단에 있는가.

    파일이 없거나 묶음이 비었거나 **다른 날 파일**이면 강제하지 않는다 — 수집이 실패한 날
    어제 종목을 오늘 본문에 강요하게 된다. 숨긴 문단·주석 속 표식은 세지 않는다.
    """
    if not movers or not movers.get("groups") or movers.get("report_date") != report_date:
        return []
    visible = {}
    for attrs, gid, inner in _MARKED.findall(_COMMENT.sub(' ', html or '')):
        if _HIDDEN.search(attrs):
            continue
        visible.setdefault(gid, []).append(_TAG.sub(' ', inner))
    v = []
    for g in movers["groups"]:
        lead = g["members"][0]
        where = f'{g["id"]}({g.get("industry") or lead["name"]}, 대표 {lead["name"]})'
        texts = visible.get(g["id"])
        if not texts:
            v.append(f'움직인 종목 {where} 문단이 없다 — <p data-mover="{g["id"]}"> 로 '
                     '무엇이 움직였고 왜인지(출처 없으면 「확인된 재료 없음」)를 쓴다')
            continue
        pattern = re.compile(r'(?<![\d.])(' + '|'.join(re.escape(x) for x in
                                                        _variants(lead["change_pct"])) + r')(?![\d])')
        if not any(pattern.search(t) for t in texts):
            v.append(f'움직인 종목 {where} 문단에 대표 종목 등락률 {lead["change_pct"]}% 가 없다 — '
                     '괄호 근거로 보인다(「(현대건설 -7.77%)」)')
    return v
