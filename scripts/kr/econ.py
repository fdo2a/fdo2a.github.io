"""한국은행 ECOS 경제통계 수집 (국고채·기준금리·단기금리).

CLAUDE.md의 열린 항목이던 **국고채 소스**를 닫는 모듈. 브리프 §9 환율·금리에서
외국인 수급 ↔ 원화 ↔ 금리 연계를 서술할 근거가 된다.

보안: ECOS는 인증키를 **URL 경로에** 넣는다(`/api/StatisticSearch/{KEY}/json/...`).
따라서 예외 메시지·로그에 URL이 그대로 나가면 키가 샌다. 외부로 나갈 수 있는 모든
문자열은 반드시 `scrub()`를 통과시킨다. 키는 os.environ에서만 읽고 산출물에 담지 않는다.

항목 코드는 하드코딩하지 않고 `StatisticItemList`에서 **이름으로 해석**한다 —
ECOS 항목 코드는 통계표 개편 때 바뀌고, 잘못된 코드는 INFO-200(데이터 없음)으로
조용히 실패해 원인 추적이 어렵다.
"""
import datetime
import json
import os
import re
import urllib.request

BASE = "https://ecos.bok.or.kr/api"
# /api/{서비스}/{인증키}/... — 키 자리를 패턴으로 가린다. env 값에 의존하지 않으므로
# 키가 설정돼 있지 않거나 다른 값이어도 URL이 로그에 그대로 나가는 일이 없다.
_KEY_IN_URL = re.compile(r"(/api/[A-Za-z]+/)([^/\s]+)")

# (표시명, 통계표코드, ECOS 항목명, 주기). 항목명은 StatisticItemList의 ITEM_NAME과 정확히 대조.
SPECS = [
    ("국고채 3년", "817Y002", "국고채(3년)", "D"),
    ("국고채 10년", "817Y002", "국고채(10년)", "D"),
    ("CD 91일", "817Y002", "CD(91일)", "D"),
    ("회사채 AA- 3년", "817Y002", "회사채(3년, AA-)", "D"),
    ("한국은행 기준금리", "722Y001", "한국은행 기준금리", "M"),
]
_LOOKBACK = {"D": 45, "M": 12}  # 연휴·미갱신을 감안해 최근 관측 2개를 확보할 만큼


def time_range(cycle: str, today=None):
    """ECOS 검색 시작·종료 일자. 주기별 포맷이 다르고 **빈 값은 허용되지 않는다** —
    빈 경로 세그먼트로 호출하면 조용히 빈 결과가 돌아온다(2026-07-29 실패 원인)."""
    today = today or datetime.date.today()
    n = _LOOKBACK.get(cycle, 45)
    if cycle == "D":
        return (today - datetime.timedelta(days=n)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
    if cycle == "M":
        y, m = today.year, today.month - n
        while m <= 0:
            y, m = y - 1, m + 12
        return f"{y}{m:02d}", today.strftime("%Y%m")
    if cycle == "Q":
        return f"{today.year - 2}Q1", f"{today.year}Q{(today.month - 1) // 3 + 1}"
    return str(today.year - n), str(today.year)


def scrub(text: str) -> str:
    """인증키를 마스킹한다. 로그·예외로 나가는 모든 문자열에 적용.

    URL 경로 패턴과 환경변수 값을 둘 다 지운다 — 어느 한쪽만으로는 구멍이 남는다.
    """
    s = _KEY_IN_URL.sub(r"\1***", str(text))
    key = os.environ.get("ECOS_API_KEY")
    return s.replace(key, "***") if key else s


def _url(key: str, service: str, fmt: str, lang: str, start: int, end: int, *rest) -> str:
    parts = [BASE, service, key, fmt, lang, str(start), str(end)] + [str(p) for p in rest]
    return "/".join(parts)


def _get_json(url: str, timeout: int = 15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _rows(payload, root: str) -> list:
    """ECOS 성공 응답에서 row 목록을 꺼낸다. 오류 응답(RESULT)이면 빈 목록."""
    if not isinstance(payload, dict):
        return []
    return (payload.get(root) or {}).get("row") or []


def resolve_item_code(payload, item_name: str):
    """StatisticItemList 응답에서 항목명으로 ITEM_CODE를 찾는다. 없으면 None."""
    target = item_name.strip()
    for r in _rows(payload, "StatisticItemList"):
        if (r.get("ITEM_NAME") or "").strip() == target:
            return r.get("ITEM_CODE")
    return None


def _norm_time(t: str) -> str:
    """ECOS TIME(YYYYMMDD/YYYYMM/YYYY)을 ISO 유사 표기로."""
    t = (t or "").strip()
    if len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:]}"
    if len(t) == 6:
        return f"{t[:4]}-{t[4:]}"
    return t


def parse_series(payload):
    """최신 관측과 직전 관측을 뽑는다. 값이 빈 행은 버린다. 데이터 없으면 None.

    ECOS는 오래된 것부터 반환하므로 마지막 두 개가 최신·직전이다.
    """
    obs = []
    for r in _rows(payload, "StatisticSearch"):
        v = (r.get("DATA_VALUE") or "").strip()
        if not v:
            continue
        try:
            obs.append((r.get("TIME"), float(v), r.get("UNIT_NAME"), r.get("ITEM_NAME1")))
        except ValueError:
            continue
    if not obs:
        return None
    t, val, unit, name = obs[-1]
    prev_t, prev_val = (obs[-2][0], obs[-2][1]) if len(obs) >= 2 else (None, None)
    # 금리(연%)는 bp가 읽기 편하다. 그 외 단위는 bp를 매기지 않는다.
    bp = round((val - prev_val) * 100, 2) if (prev_val is not None and unit and "%" in unit) else None
    return {"value": val, "date": _norm_time(t), "unit": unit, "item_name": name,
            "prev": prev_val, "prev_date": _norm_time(prev_t) if prev_t else None, "bp": bp}


def result_note(payload) -> str:
    """ECOS 오류 응답(RESULT)을 진단 문자열로. 성공 응답이면 빈 문자열."""
    if isinstance(payload, dict) and "RESULT" in payload:
        r = payload["RESULT"] or {}
        return f"{r.get('CODE')} {r.get('MESSAGE')}"
    return ""


def _fetch_one(key: str, stat_code: str, item_name: str, cycle: str, item_cache: dict):
    """(관측, 진단문자열)을 돌려준다. 실패 원인을 삼키지 않고 호출자가 로그로 남긴다."""
    if stat_code not in item_cache:
        item_cache[stat_code] = _get_json(_url(key, "StatisticItemList", "json", "kr",
                                               1, 1000, stat_code))
    items = item_cache[stat_code]
    code = resolve_item_code(items, item_name)
    if not code:
        note = result_note(items) or f"후보 {len(_rows(items, 'StatisticItemList'))}개 중 이름 불일치"
        return None, f"항목 '{item_name}' 해석 실패 (표 {stat_code}): {note}"
    start, end = time_range(cycle)
    payload = _get_json(_url(key, "StatisticSearch", "json", "kr", 1, 200,
                             stat_code, cycle, start, end, code))
    row = parse_series(payload)
    if row:
        return row, ""
    note = result_note(payload) or f"관측 0건 ({start}~{end})"
    return None, f"조회 실패 (표 {stat_code} 항목 {code} 주기 {cycle}): {note}"


def collect() -> dict:
    """키가 없으면 기존 스텁을 그대로 반환(비-코어라 발행을 막지 않는다).

    개별 지표 실패는 삼켜서 missing에만 남긴다 — ECOS 한 항목 때문에 KR 브리프
    전체 수집이 중단되면 안 된다.
    """
    key = os.environ.get("ECOS_API_KEY")
    if not key:
        return {"pending": True, "note": "ECOS_API_KEY 미설정 — GitHub Actions 시크릿 확인"}

    series, missing, item_cache = {}, [], {}
    for label, stat_code, item_name, cycle in SPECS:
        try:
            row, note = _fetch_one(key, stat_code, item_name, cycle, item_cache)
        except Exception as e:
            row, note = None, f"{type(e).__name__}: {e}"
        if row:
            series[label] = row
        else:
            missing.append(label)
            print(f"  econ {label}: {scrub(note)}")
    return {"source": "ECOS (한국은행 경제통계시스템)", "series": series, "missing": missing}
