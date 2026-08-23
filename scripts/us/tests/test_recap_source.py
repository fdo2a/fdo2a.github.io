import json
import os

import pytest

from us.recap_source import collect, post_figures, post_sections

POST = """<html><body><main>
<section id="s1"><h2>1. 시황 요약</h2>
<p>S&amp;P 500은 0.43% 올랐고 나스닥도 0.43% 상승했다. 재무부 바이백 발표가 촉매였다.</p>
<p>두 번째 문단은 리드가 아니다.</p></section>
<section id="s2"><h2>2. 채권·금리</h2>
<p>10년물은 4.35%로 3.7bp 올랐다.</p></section>
<section id="s3"><h3>3. 메모리</h3><p>마이크론이 2.1% 반등했다.</p></section>
</main></body></html>"""


def test_post_sections_takes_title_and_first_paragraph_only():
    secs = post_sections(POST)
    assert [s["title"] for s in secs] == ["1. 시황 요약", "2. 채권·금리", "3. 메모리"]
    assert secs[0]["lead"].startswith("S&P 500은 0.43% 올랐고")
    assert "두 번째 문단" not in secs[0]["lead"]


def test_post_sections_truncates_a_long_lead():
    long = "<html><body><section><h2>T</h2><p>" + ("가" * 500) + "</p></section></body></html>"
    secs = post_sections(long, max_lead=100)
    assert len(secs[0]["lead"]) <= 101          # 100자 + 말줄임 기호
    assert secs[0]["lead"].endswith("…")


def test_post_sections_is_empty_for_markup_without_sections():
    assert post_sections("<html><body><p>본문만</p></body></html>") == []


def test_post_figures_collects_numbers_and_tickers_deduped_and_sorted():
    figs = post_figures(POST)
    assert "0.43%" in figs
    assert "4.35%" in figs
    assert "3.7bp" in figs or "3.7" in figs
    assert figs == sorted(set(figs))


def _write(tmp_path, name, html):
    p = os.path.join(tmp_path, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(html)
    return p


LISTING = [{"date": "2026-08-21", "headline": "재무부 바이백 확대"},
           {"date": "2026-08-20", "headline": "PMI 4년래 최고"},
           {"date": "2026-08-14", "headline": "지난주 발행분"}]


def test_collect_gathers_only_posts_inside_the_window(tmp_path):
    for d in ("2026-08-21", "2026-08-20", "2026-08-14"):
        _write(tmp_path, f"{d}.html", POST)
    r = collect(str(tmp_path), LISTING, "2026-08-17", "2026-08-21", "weekly", "2026-W34")
    assert [p["date"] for p in r["posts"]] == ["2026-08-20", "2026-08-21"]


def test_collect_carries_headline_from_the_listing(tmp_path):
    _write(tmp_path, "2026-08-21.html", POST)
    r = collect(str(tmp_path), LISTING, "2026-08-21", "2026-08-21", "weekly", "2026-W34")
    assert r["posts"][0]["headline"] == "재무부 바이백 확대"


def test_collect_records_a_listed_post_whose_file_is_missing(tmp_path):
    # 목록에는 있는데 파일이 없다 — 조용히 빠뜨리면 그날 사건이 사라진다
    r = collect(str(tmp_path), LISTING, "2026-08-17", "2026-08-21", "weekly", "2026-W34")
    assert r["posts"] == []
    assert "2026-08-20" in r["missing"]
    assert "2026-08-21" in r["missing"]


def test_collect_raises_when_no_post_exists_in_the_window(tmp_path):
    with pytest.raises(ValueError, match="발행본"):
        collect(str(tmp_path), [], "2026-08-17", "2026-08-21", "weekly", "2026-W34")


def test_collect_sets_span_key_and_boundaries(tmp_path):
    _write(tmp_path, "2026-08-21.html", POST)
    r = collect(str(tmp_path), LISTING, "2026-08-17", "2026-08-21", "weekly", "2026-W34")
    assert r["span"] == "weekly"
    assert r["key"] == "2026-W34"
    assert r["start_date"] == "2026-08-17"
    assert r["end_date"] == "2026-08-21"
    assert r["sessions"] == 1


def test_collect_output_is_json_serialisable(tmp_path):
    _write(tmp_path, "2026-08-21.html", POST)
    r = collect(str(tmp_path), LISTING, "2026-08-21", "2026-08-21", "weekly", "2026-W34")
    json.dumps(r, ensure_ascii=False)
