import os
from kr.themes import parse_themes, rank_themes

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "themes.html")


def _html():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def test_parse_themes_extracts_name_and_pct():
    ts = parse_themes(_html())
    names = {t["name"]: t["change_pct"] for t in ts}
    assert names["전선"] == 9.30
    assert names["mRNA(메신저 리보핵산)"] == -0.98
    assert len(ts) == 3


def test_rank_themes_sorts_desc_and_dedups():
    dup = [{"name": "전선", "change_pct": 9.3}, {"name": "전선", "change_pct": 9.3},
           {"name": "로봇", "change_pct": 9.89}, {"name": "mRNA", "change_pct": -0.98}]
    ranked = rank_themes(dup, top=15)
    assert [t["name"] for t in ranked] == ["로봇", "전선", "mRNA"]
