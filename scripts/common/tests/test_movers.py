"""움직인 종목 선정·묶기와 발행 게이트 — 2026-09-24 사용자 결정
「1,2를 업종으로 묶는 방법과 이상 문턱은 5%, 코스닥은 포함하지 말고 US도 적용하자」."""
from scripts.common import movers as M


def row(name, chg, cap=0, value=0, industry=None):
    return {"name": name, "change_pct": chg, "close": 100, "value": value,
            "cap": cap, "industry": industry}


# 9/23 코스피에서 가져온 모양(시총은 단순화)
ROWS = [
    row("삼성전자", 3.25, cap=1700, value=5504, industry="반도체"),
    row("SK하이닉스", 1.2, cap=1300, value=5365, industry="반도체"),
    row("SK스퀘어", 5.03, cap=160, value=753, industry="증권"),
    row("두산에너빌리티", -5.55, cap=52, value=377, industry="전기장비"),
    row("한화에어로스페이스", -3.41, cap=52, value=133, industry="우주항공과국방"),
    row("신한지주", -3.45, cap=50, value=90, industry="은행"),
    row("현대건설", -7.77, cap=6, value=120, industry="건설"),
    row("GS건설", -7.61, cap=3, value=83, industry="건설"),
    row("OCI홀딩스", 9.57, cap=2, value=60, industry="화학"),
    row("KB금융", -1.42, cap=70, value=118, industry="은행"),
]


def test_candidates_are_top_contributors_and_big_moves():
    cands = {c["name"]: c["reasons"] for c in M.select_candidates(ROWS)}
    assert cands["삼성전자"] == ["지수 기여 상위"]
    assert cands["SK하이닉스"] == ["지수 기여 상위"]
    assert cands["두산에너빌리티"] == ["지수 기여 하위", "이상 등락"]
    assert "한화에어로스페이스" in cands and "신한지주" not in cands   # 기여 하위는 둘까지
    assert "현대건설" in cands and "OCI홀딩스" in cands and "SK스퀘어" in cands
    assert "KB금융" not in cands


def test_threshold_is_inclusive_at_five_percent():
    names = {c["name"] for c in M.select_candidates([row("A", 5.0), row("B", -4.99)])}
    assert names == {"A"}


def test_groups_bundle_by_industry_and_direction_contributors_first():
    groups = M.group_movers(M.select_candidates(ROWS), max_groups=5)
    assert [g["id"] for g in groups] == ["g1", "g2", "g3", "g4", "g5"]
    first = groups[0]
    assert first["industry"] == "반도체" and first["direction"] == "up"
    assert [m["name"] for m in first["members"]] == ["삼성전자", "SK하이닉스"]
    # 기여 묶음(반도체·전기장비·우주항공)이 먼저, 그 뒤 거래대금 합이 큰 이상 등락 묶음
    assert [g["industry"] for g in groups[:3]] == ["반도체", "전기장비", "우주항공과국방"]
    assert groups[3]["industry"] == "증권"            # SK스퀘어 753
    assert groups[4]["industry"] == "건설"            # 현대건설+GS건설 203 > OCI 60
    assert [m["name"] for m in groups[4]["members"]] == ["현대건설", "GS건설"]
    # 기여도는 선정에만 쓴다 — 본문에 인용할 필드로 내보내지 않는다
    assert "cap" not in groups[0]["members"][0] and "score" not in groups[0]["members"][0]


def test_missing_industry_groups_by_the_stock_itself():
    groups = M.group_movers(M.select_candidates([row("A", 6.0, value=5), row("B", 7.0, value=4)]))
    assert [g["industry"] for g in groups] == [None, None]
    assert [len(g["members"]) for g in groups] == [1, 1]


def test_no_cap_means_no_contribution_but_big_moves_still_count():
    names = {c["name"] for c in M.select_candidates([row("A", 1.0), row("B", -6.0)])}
    assert names == {"B"}


# --- 게이트 ---

MOVERS = {"report_date": "2026-09-23", "groups": [
    {"id": "g1", "industry": "반도체", "direction": "up",
     "members": [{"name": "삼성전자", "change_pct": 3.25}]},
    {"id": "g2", "industry": "건설", "direction": "down",
     "members": [{"name": "현대건설", "change_pct": -7.77}]}]}


def page(body):
    return f'<html><body data-register="da"><div class="doc">{body}</div></body></html>'


def test_gate_passes_when_every_group_has_a_marked_paragraph_with_the_lead_move():
    html = page('<p data-mover="g1">반도체가 지수를 끌었다(삼성전자 +3.25%).</p>'
                '<p data-mover="g2">건설은 대미투자 보고 뒤 매물이 나왔다(현대건설 -7.77%).</p>')
    assert M.check(html, MOVERS, "2026-09-23") == []


def test_gate_catches_a_missing_group_and_a_paragraph_without_the_number():
    html = page('<p data-mover="g1">반도체가 지수를 끌었다.</p>')
    v = M.check(html, MOVERS, "2026-09-23")
    assert any("g1" in x and "3.25" in x for x in v)
    assert any("g2" in x for x in v)


def test_gate_does_not_enforce_stale_or_empty_files():
    assert M.check(page(''), MOVERS, "2026-09-24") == []
    assert M.check(page(''), {"report_date": "2026-09-23", "groups": []}, "2026-09-23") == []
    assert M.check(page(''), None, "2026-09-23") == []


def test_gate_ignores_hidden_or_commented_markers():
    html = page('<!-- <p data-mover="g1">삼성전자 +3.25%</p> -->'
                '<p data-mover="g2" hidden>현대건설 -7.77%</p>')
    v = M.check(html, MOVERS, "2026-09-23")
    assert any("g1" in x for x in v) and any("g2" in x for x in v)


def test_cli_reads_the_market_files(tmp_path):
    import json
    from scripts import check_movers as C
    (tmp_path / 'kr_movers.json').write_text(json.dumps(MOVERS, ensure_ascii=False))
    (tmp_path / 'kr_market_data.json').write_text('{"report_date": "2026-09-23"}')
    post = tmp_path / 'p.html'
    post.write_text(page('<p data-mover="g1">삼성전자 +3.25%</p>'), encoding='utf-8')
    assert C.main(['--html', str(post), '--datadir', str(tmp_path), '--market', 'kr']) == 1
    post.write_text(page('<p data-mover="g1">삼성전자 +3.25%</p>'
                         '<p data-mover="g2">현대건설 -7.77%</p>'), encoding='utf-8')
    assert C.main(['--html', str(post), '--datadir', str(tmp_path), '--market', 'kr']) == 0
    # US 폴더에는 KR 파일이 없다 — 강제하지 않는다
    assert C.main(['--html', str(post), '--datadir', str(tmp_path)]) == 0
