"""glossary — 전부 아니면 전무, 뜻이 하나인 것만."""
import re

import pytest

from scripts.ja import extract as X
from scripts.ja import glossary as G
from scripts.ja import news as N
from scripts.ja import state as S
from scripts.ja.tests.corpus import ROOT, read


@pytest.mark.parametrize("ko,ja", [
    ("현재 위치", "現在位置"),
    ("⟦a⟧US Market Brief⟦/a⟧ · 2026년 11월 12일(목) 마감 기준", "⟦a⟧US Market Brief⟦/a⟧ · 2026年11月12日(木) 取引終了時点"),
    ("⟦a⟧미국 시장⟦/a⟧⟦b⟧›⟦/b⟧⟦c⟧일간⟦/c⟧", "⟦a⟧米国市場⟦/a⟧⟦b⟧›⟦/b⟧⟦c⟧日次⟦/c⟧"),
    ("⟦a⟧原題⟦/a⟧⟦b⟧ロイター · 11월 12일⟦/b⟧", "⟦a⟧原題⟦/a⟧⟦b⟧ロイター · 11月12日⟦/b⟧"),
    ("11월 12일", "11月12日"),
    ("CPI YoY(9월)", "CPI YoY(9月)"),
    ("실업률(10월)", "失業率(10月)"),
    ("미시간대 소비자심리(9월 확정)", "ミシガン大学消費者信頼感指数(9月確報)"),
    ("9영업일째", "9営業日目"),
    ("12영업일", "12営業日"),
    ("2026-11-05 (10월 31일 주간)", "2026-11-05 (10月31日の週)"),
    ("2026-09 기준월", "2026-09基準月"),
    ("2026년 3분기", "2026年第3四半期"),
    ("변동성:", "ボラティリティ:"),
    ("  종가  ", "  終値  "),
    ("(금요일)", "(金曜日)"),
])
def test_fixed(ko, ja):
    assert G.fixed(ko) == ja


@pytest.mark.parametrize("ko", [
    "엔비디아가 4.34% 내렸다.",          # 문장은 모델
    "미국 증시 모닝브리프 — 2026년 11월 12일 (목요일)",   # 일부만 풀리면 None
    "강세",                               # 애매 — 넣지 않았다
    "우호",
    "5개 중 2개",
    "S&P 500",                             # 한글이 없으면 fixed 의 일이 아니다
])
def test_not_fixed(ko):
    assert G.fixed(ko) is None


def test_dict_has_no_sentences():
    for ko in G.DICT:
        assert not re.search(r"(다|요)\.?$", ko), ko
        assert len(ko) <= 30


def test_dict_values_have_no_hangul_and_keep_digits():
    for ko, ja in G.DICT.items():
        assert not G.HANGUL.search(ja), ko
        assert re.findall(r"\d+", ko) == re.findall(r"\d+", ja), ko


def test_latin_map_and_names_shape():
    assert all(isinstance(v, tuple) and v for v in G.LATIN_MAP.values())
    assert G.LATIN_MAP["Fed"][0] == "FRB"
    assert all(not G.HANGUL.search(v) for v in G.NAMES.values())


def test_candidates_cli_runs():
    rows = G.candidates(ROOT, recent=3, min_docs=3)
    assert rows and all(n >= 3 for n, _ in rows)
    assert any(seg == "현재 위치" for _, seg in rows)


def test_localized_japan_daily_news_heads_never_reach_the_model():
    """localize → split → plan: 일본어 원문 항목 안의 단위는 todo 가 하나도 없다."""
    path = "japan/daily/2026-11-12.html"
    html, rep = N.localize(read(path), N.lookup(ROOT, path))
    doc = X.split(html)
    plan = S.plan(doc, None)
    todo_uids = {u.uid for u in plan.todo}
    in_items = [u for u in doc.units if _inside_news_item(html, u.start)]
    assert in_items and not [u.ko for u in in_items if u.uid in todo_uids]
    # 원제는 고정 번역 뒤에도 그대로 남는다
    out = X.join(doc, plan.texts())
    recs = N.lookup(ROOT, path)
    for nid in rep.localized:
        import html as H
        assert H.escape(H.unescape(recs[nid]["title"]), quote=False) in out


def _inside_news_item(html, pos):
    i = html.rfind('<div class="news-item"', 0, pos)
    return i >= 0 and html.find("</div>", i) > pos


def test_every_fixed_answer_in_the_corpus_passes_the_unit_gate():
    """고정 번역은 다시 번역할 길이 없다 — 검사에 걸리면 그 글은 영영 보류된다."""
    from scripts.ja import gate as GT
    from scripts.ja.tests.corpus import target_paths
    bad = []
    for path in target_paths():
        html, _ = N.localize(read(path), N.lookup(ROOT, path))
        for u in X.split(html).units:
            ja = G.fixed(u.ko)
            if ja is not None:
                bad += [(path, u.ko, ja, p.code) for p in GT.check_unit(u.ko, ja) if not p.soft]
    assert not bad[:5]


def test_names_are_confirmed_in_repo_titles():
    """NAMES 의 값은 레포의 일본어 원제(japan/data/news/**)에 그대로 있어야 한다."""
    import json
    import unicodedata
    titles = []

    def walk(x):                      # items 밖(region_filter 등)의 title 도 원제다
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "title" and isinstance(v, str):
                    titles.append(unicodedata.normalize("NFKC", v))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for p in (ROOT / "japan/data/news").rglob("*.json"):
        try:
            walk(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            continue
    assert titles
    blob = "\n".join(titles)
    missing = [ja for ja in G.NAMES.values() if ja not in blob]
    assert missing == []


def test_fixed_attr_closed_vocabulary():
    from scripts.fund import regime
    for st in regime.STATES + ("미판정",):
        assert G.fixed_attr("data-regime", st)
    assert G.fixed_attr("data-regime", "새 국면") is None
    assert G.fixed_attr("data-label", "강세") is None
    assert G.fixed("강세") is None                 # 본문의 「강세」는 여전히 모델 몫


# ── 1회차 codex 구현 검토 ─────────────────────────────────────────────────

def test_every_dictionary_and_attr_pair_passes_the_hard_gate():
    # A3 ③: 고정 번역도 기계 검사를 거친다 — 사전 자체가 막히면 그 사전을 쓰는 글이 전부 멈춘다
    from scripts.ja import gate as GT
    bad = []
    for ko, ja in list(G.DICT.items()) + [(k, v) for d in G.ATTR_VALUES.values() for k, v in d.items()]:
        bad += [(ko, ja, p.code) for p in GT.check_unit(ko, ja) if not p.soft]
        if G.fixed(ko) is not None:
            bad += [(ko, G.fixed(ko), p.code) for p in GT.check_unit(ko, G.fixed(ko)) if not p.soft]
    assert not bad


@pytest.mark.parametrize("ko,ja", [
    ("산업재", "資本財・サービス"),                                       # C1: GICS 「Industrials」
    ("2026년 10월 1일(목) 마감 기준", "2026年10月1日(木) 取引終了時点"),   # C7
    ("5거래일째", "5営業日目"),                                           # C2 은 안 받음 — 일본 시황 관용
])
def test_codex_r1_glossary_fixes(ko, ja):
    assert G.fixed(ko) == ja
