import copy

from us.stance import ASSETS, label_for
from us.stance_gate import check, parse_stance_cells, section8

REPORT_DATE = "2026-08-18"

BOOK = {
    "equities": 0, "bonds": -1, "fx": -1, "energy": 0,
    "metals": 1, "memory": 1, "ai_infra": 0,
}
LABELS = {"equities": "중립", "bonds": "숏 바이어스", "fx": "달러 소폭 숏",
          "energy": "중립", "metals": "소폭확대", "memory": "OW", "ai_infra": "중립"}


def row(asset, grade, label, held=4, trigger="VIX 22 상회", attrs=""):
    return (f'<tr{attrs}><td>{asset}</td>'
            f'<td><span data-asset="{asset}" data-grade="{grade}">{label}</span></td>'
            f'<td>{held}영업일</td><td>유지</td><td>논거</td>'
            f'<td>{trigger}</td></tr>')


def build_html(book=None, labels=None, extra_text="", **row_kwargs):
    book = book or BOOK
    labels = labels or LABELS
    rows = "".join(row(a, g, labels[a], **row_kwargs) for a, g in book.items())
    return ('<section><h2>1. 주식</h2><table><tr><td>S&P 500</td></tr></table></section>'
            f'<section><h2>8. 멀티에셋 매니저 전략</h2><p>{extra_text}</p>'
            f'<table>{rows}</table></section>'
            '<section><h2>9. 주목 섹터</h2></section>')


def stance_file(book=None, date="2026-08-17", since="2026-08-10", history=None):
    book = book or BOOK
    return {
        "report_date": date,
        "assets": {a: {"grade": g, "label": label_for(a, g), "since": since,
                       "triggers": {"increase": [], "decrease": []}}
                   for a, g in book.items()},
        "history": history or [],
    }


def eval_file(book=None, allowed=None, increase=None, bootstrap=False):
    book = book or BOOK
    return {
        "report_date": REPORT_DATE,
        "bootstrap": bootstrap,
        "assets": {a: {"grade": g,
                       "allowed_grades": (allowed or {}).get(a, [g - 1, g, g + 1]),
                       "increase": (increase or {}).get(a, [])}
                   for a, g in book.items()},
    }


def next_file(book=None, **kw):
    f = stance_file(book, date=REPORT_DATE, **kw)
    return f


METRICS = ("ust30y", "vix_close", "spx_vs_50dma_pct")


# --- section location ------------------------------------------------------

def test_section8_is_located_and_bounded():
    s = section8(build_html())
    assert "멀티에셋" in s and "주목 섹터" not in s and "S&P 500" not in s


def test_prose_mentioning_the_section_name_does_not_hijack_the_slice():
    """§8-매크로 reconciles against the stance section by name, so the word appears
    upstream in body text — the locator must key on the heading, not the first hit."""
    html = ('<section><h2>8. 매크로 논리</h2>'
            '<p>구조적으로는 우호적이나 멀티에셋 스탠스는 숏을 유지한다.</p></section>'
            + build_html())
    s = section8(html)
    assert "매크로 논리" not in s
    assert "data-asset" in s


def test_missing_section_is_the_only_violation_reported():
    assert check("<p>no section</p>", stance_file(), eval_file(), next_file()) == \
        ['§8(멀티에셋 매니저 전략) 섹션을 찾을 수 없다']


def test_parse_reads_every_asset_marker():
    cells = parse_stance_cells(section8(build_html()))
    assert set(cells) == set(ASSETS)
    assert cells["bonds"]["grade"] == -1


# --- happy path ------------------------------------------------------------

def test_a_conforming_report_passes_clean():
    assert check(build_html(), stance_file(), eval_file(), next_file(), METRICS) == []


# --- vocabulary ------------------------------------------------------------

def test_freehand_label_is_rejected():
    labels = dict(LABELS, bonds="숏~중립 듀레이션, 장기물 신중")
    v = check(build_html(labels=labels), stance_file(), eval_file(), next_file(), METRICS)
    assert any("통제 어휘" in x and "bonds" in x for x in v)


def test_label_from_the_wrong_grade_is_rejected():
    labels = dict(LABELS, equities="비중확대")   # grade 0 must read 중립
    v = check(build_html(labels=labels), stance_file(), eval_file(), next_file(), METRICS)
    assert any("equities" in x and "중립" in x for x in v)


def test_missing_asset_marker_is_reported():
    book = {k: g for k, g in BOOK.items() if k != "fx"}
    labels = {k: v for k, v in LABELS.items() if k != "fx"}
    nxt = next_file()
    v = check(build_html(book, labels), stance_file(), eval_file(), nxt, METRICS)
    assert any("data-asset 표식이 없는 자산군" in x and "fx" in x for x in v)


# --- movement discipline ---------------------------------------------------

def test_grade_outside_allowed_grades_is_rejected():
    moved = dict(BOOK, equities=1)
    labels = dict(LABELS, equities="소폭확대")
    ev = eval_file(allowed={"equities": [0]})
    v = check(build_html(moved, labels), stance_file(), ev, next_file(moved), METRICS)
    assert any("허용 범위" in x and "equities" in x for x in v)


def test_the_july_29_to_30_flip_is_caught():
    """-1 -> +1 in one session: outside allowed_grades, which never spans a sign flip."""
    prev = stance_file(dict(BOOK, equities=-1))
    ev = eval_file(dict(BOOK, equities=-1), allowed={"equities": [-2, -1, 0]})
    flipped = dict(BOOK, equities=1)
    labels = dict(LABELS, equities="소폭확대")
    v = check(build_html(flipped, labels), prev, ev, next_file(flipped), METRICS)
    assert any("허용 범위" in x for x in v)


def test_increase_must_quote_the_met_triggers_actual_value():
    moved = dict(BOOK, bonds=-2)
    labels = dict(LABELS, bonds="숏 듀레이션")
    ev = eval_file(moved, allowed={"bonds": [-2, -1]},
                   increase={"bonds": [{"status": "MET", "metric": "ust30y", "actual": 5.43}]})
    nxt = next_file(moved, since=REPORT_DATE,
                    history=[{"asset": "bonds", "date": REPORT_DATE, "from": -1, "to": -2}])
    v = check(build_html(moved, labels), stance_file(), ev, nxt, METRICS)
    assert any("실측값" in x and "bonds" in x for x in v)

    ok = check(build_html(moved, labels, extra_text="30Y가 5.43%까지 올라 조건을 채웠다"),
               stance_file(), ev, nxt, METRICS)
    assert ok == []


def test_increase_on_an_event_trigger_needs_the_evidence_marker():
    moved = dict(BOOK, energy=1)
    labels = dict(LABELS, energy="소폭확대")
    ev = eval_file(moved, allowed={"energy": [0, 1]})
    nxt = next_file(moved, since=REPORT_DATE,
                    history=[{"asset": "energy", "date": REPORT_DATE, "from": 0, "to": 1}])
    v = check(build_html(moved, labels), stance_file(), ev, nxt, METRICS)
    assert any('data-evidence="event"' in x for x in v)


def test_de_risking_needs_no_trigger_evidence():
    moved = dict(BOOK, metals=0)
    labels = dict(LABELS, metals="중립")
    ev = eval_file(moved, allowed={"metals": [0, 1]})
    nxt = next_file(moved, since=REPORT_DATE,
                    history=[{"asset": "metals", "date": REPORT_DATE, "from": 1, "to": 0}])
    assert check(build_html(moved, labels), stance_file(), ev, nxt, METRICS) == []


def test_bootstrap_day_skips_the_evidence_requirement():
    moved = dict(BOOK, equities=1)
    labels = dict(LABELS, equities="소폭확대")
    ev = eval_file(moved, bootstrap=True)
    nxt = next_file(moved, since=REPORT_DATE,
                    history=[{"asset": "equities", "date": REPORT_DATE, "from": 0, "to": 1}])
    assert check(build_html(moved, labels), stance_file(), ev, nxt, METRICS) == []


# --- row completeness ------------------------------------------------------

def test_missing_hold_count_is_reported():
    html = build_html().replace("4영업일", "")
    v = check(html, stance_file(), eval_file(), next_file(), METRICS)
    assert any("유지 일수" in x for x in v)


def test_a_next_checkpoint_without_a_number_is_reported():
    html = build_html(trigger="추이 확인 필요")
    v = check(html, stance_file(), eval_file(), next_file(), METRICS)
    assert any("다음 분기점에 수치가 없다" in x for x in v)


# --- stance_next.json ------------------------------------------------------

def test_absent_next_stance_is_fatal():
    v = check(build_html(), stance_file(), eval_file(), None, METRICS)
    assert any("stance_next.json이 없다" in x for x in v)


def test_next_stance_must_be_dated_today():
    nxt = next_file()
    nxt["report_date"] = "2026-08-17"
    v = check(build_html(), stance_file(), eval_file(), nxt, METRICS)
    assert any("report_date가" in x for x in v)


def test_next_stance_grade_must_match_the_table():
    nxt = next_file(dict(BOOK, fx=0))
    nxt["assets"]["fx"]["label"] = "달러 중립"
    v = check(build_html(), stance_file(), eval_file(), nxt, METRICS)
    assert any("§8 표의" in x and "fx" in x for x in v)


def test_moved_row_without_a_history_entry_is_reported():
    moved = dict(BOOK, metals=0)
    labels = dict(LABELS, metals="중립")
    ev = eval_file(moved, allowed={"metals": [0, 1]})
    nxt = next_file(moved, since=REPORT_DATE)     # no history
    v = check(build_html(moved, labels), stance_file(), ev, nxt, METRICS)
    assert any("history에 오늘 기록이 없다" in x for x in v)


def test_moved_row_must_reset_since():
    moved = dict(BOOK, metals=0)
    labels = dict(LABELS, metals="중립")
    ev = eval_file(moved, allowed={"metals": [0, 1]})
    nxt = next_file(moved, since="2026-08-10",
                    history=[{"asset": "metals", "date": REPORT_DATE, "from": 1, "to": 0}])
    v = check(build_html(moved, labels), stance_file(), ev, nxt, METRICS)
    assert any("since가" in x for x in v)


def test_trigger_naming_a_metric_we_never_collect_is_rejected():
    nxt = next_file()
    nxt["assets"]["bonds"]["triggers"]["increase"] = [
        {"kind": "metric", "metric": "ust30y_typo", "op": ">", "value": 5.4}]
    v = check(build_html(), stance_file(), eval_file(), nxt, METRICS)
    assert any("stance_metrics.json에 없다" in x for x in v)


def test_neutral_asset_needs_a_direction_on_its_increase_trigger():
    nxt = next_file()
    nxt["assets"]["equities"]["triggers"]["increase"] = [
        {"kind": "metric", "metric": "vix_close", "op": ">", "value": 22}]
    v = check(build_html(), stance_file(), eval_file(), nxt, METRICS)
    assert any("toward" in x for x in v)

    nxt2 = copy.deepcopy(nxt)
    nxt2["assets"]["equities"]["triggers"]["increase"][0]["toward"] = "-"
    assert check(build_html(), stance_file(), eval_file(), nxt2, METRICS) == []


def test_bond_curve_outside_the_vocabulary_is_rejected():
    nxt = next_file()
    nxt["assets"]["bonds"]["curve"] = "벨리~단기 중심"
    v = check(build_html(), stance_file(), eval_file(), nxt, METRICS)
    assert any("curve" in x for x in v)


def test_next_stance_label_must_match_its_grade():
    nxt = next_file()
    nxt["assets"]["memory"]["label"] = "비중확대"
    v = check(build_html(), stance_file(), eval_file(), nxt, METRICS)
    assert any("label은" in x and "memory" in x for x in v)
