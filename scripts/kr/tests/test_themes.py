from kr.themes import rank_themes


def test_rank_themes_sorts_desc_and_dedups():
    dup = [{"name": "전선", "change_pct": 9.3}, {"name": "전선", "change_pct": 9.3},
           {"name": "로봇", "change_pct": 9.89}, {"name": "mRNA", "change_pct": -0.98}]
    ranked = rank_themes(dup, top=15)
    assert [t["name"] for t in ranked] == ["로봇", "전선", "mRNA"]
