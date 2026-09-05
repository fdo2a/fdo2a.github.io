"""임베드된 차트를 파일 참조로 되돌리는 백필.

무손실 근거(2026-09-06 실측): US 38편 전부, 임베드 PNG 가 `assets/yield_curve_{date}.png`
와 SHA-256 바이트 동일이었다(38/38). 그래서 「해시가 맞을 때만 치환」이 규칙이 된다.
KR 은 대응 파일이 없어(무날짜 이름이라 덮어써짐) 임베드분을 **추출**해 만든다.
차트 종류는 alt 가 아니라 **PNG IHDR 높이**로 가린다 — 53장 중 11장은 alt 가 없고
표기도 8종이라 alt 로는 전수 분류가 불가능하다(codex 검토 6.1).
"""
import base64
import struct
import zlib

from scripts import backfill_chart_assets as B


def _png(w, h):
    """유효한 IHDR 를 가진 최소 PNG."""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
    chunk += struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk + b"\x00" * 300


DAILY, FLOWS = _png(1505, 861), _png(1505, 469)


def _doc(*srcs):
    imgs = "".join('<img class="chart" src="%s">' % s for s in srcs)
    return ("<html><body><div class='card'><p>코스피는 20일선을 웃돌아 마감했다.</p>"
            "%s</div></body></html>" % imgs)


def _inline(raw):
    return "data:image/png;base64," + base64.b64encode(raw).decode()


# --- 차트 종류 판별 ---

def test_png_size_reads_ihdr():
    assert B.png_size(DAILY) == (1505, 861)
    assert B.png_size(FLOWS) == (1505, 469)


def test_kind_splits_on_height():
    assert B.chart_kind(DAILY) == "kr_charts"
    assert B.chart_kind(FLOWS) == "kr_flows_intraday"


def test_kind_rejects_unknown_shape():
    assert B.chart_kind(_png(800, 600)) is None


# --- US: 해시가 맞을 때만 치환 ---

def test_us_swaps_when_hash_matches(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "posts").mkdir()
    (tmp_path / "assets" / "yield_curve_2026-09-04.png").write_bytes(DAILY)
    post = tmp_path / "posts" / "2026-09-04.html"
    post.write_text(_doc(_inline(DAILY)), encoding="utf-8")

    plan = B.plan_us(tmp_path)
    assert len(plan) == 1 and plan[0].ok
    assert plan[0].swaps == [("posts/2026-09-04.html", "../assets/yield_curve_2026-09-04.png")]


def test_us_refuses_when_hash_differs(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "posts").mkdir()
    (tmp_path / "assets" / "yield_curve_2026-09-04.png").write_bytes(FLOWS)
    post = tmp_path / "posts" / "2026-09-04.html"
    post.write_text(_doc(_inline(DAILY)), encoding="utf-8")

    plan = B.plan_us(tmp_path)
    assert not plan[0].ok and "해시" in plan[0].why


def test_us_refuses_when_asset_missing(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "posts").mkdir()
    post = tmp_path / "posts" / "2026-09-04.html"
    post.write_text(_doc(_inline(DAILY)), encoding="utf-8")
    assert not B.plan_us(tmp_path)[0].ok


def test_apply_leaves_refused_files_untouched(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "posts").mkdir()
    (tmp_path / "assets" / "yield_curve_2026-09-04.png").write_bytes(FLOWS)
    post = tmp_path / "posts" / "2026-09-04.html"
    before = _doc(_inline(DAILY))
    post.write_text(before, encoding="utf-8")
    B.apply(B.plan_us(tmp_path), tmp_path)
    assert post.read_text(encoding="utf-8") == before


def test_apply_result_is_reversible(tmp_path):
    """되감아 옛 판이 그대로 나와야 한다 — 원장이 쓰는 판정과 같은 불변식."""
    import sys, os
    sys.path.insert(0, os.path.join(str(tmp_path), ".."))
    from review import prose
    (tmp_path / "assets").mkdir()
    (tmp_path / "posts").mkdir()
    (tmp_path / "assets" / "yield_curve_2026-09-04.png").write_bytes(DAILY)
    post = tmp_path / "posts" / "2026-09-04.html"
    before = _doc(_inline(DAILY))
    post.write_text(before, encoding="utf-8")
    B.apply(B.plan_us(tmp_path), tmp_path)
    after = post.read_text(encoding="utf-8")
    assert after != before
    assert prose.asset_externalized(
        before, after, lambda rel: (post.parent / rel).resolve().read_bytes()) is True


# --- KR: 임베드분을 추출해 날짜별 파일로 ---

def test_kr_extracts_both_charts(tmp_path):
    (tmp_path / "kr" / "posts").mkdir(parents=True)
    post = tmp_path / "kr" / "posts" / "2026-09-03.html"
    post.write_text(_doc(_inline(DAILY), _inline(FLOWS)), encoding="utf-8")

    plan = B.plan_kr(tmp_path)
    assert plan[0].ok
    assert [s[1] for s in plan[0].swaps] == [
        "../assets/kr_charts_2026-09-03.png",
        "../assets/kr_flows_intraday_2026-09-03.png"]


def test_kr_refuses_two_of_the_same_kind(tmp_path):
    (tmp_path / "kr" / "posts").mkdir(parents=True)
    post = tmp_path / "kr" / "posts" / "2026-09-03.html"
    post.write_text(_doc(_inline(DAILY), _inline(DAILY)), encoding="utf-8")
    plan = B.plan_kr(tmp_path)
    assert not plan[0].ok and "중복" in plan[0].why


def test_kr_refuses_unknown_shape(tmp_path):
    (tmp_path / "kr" / "posts").mkdir(parents=True)
    post = tmp_path / "kr" / "posts" / "2026-09-03.html"
    post.write_text(_doc(_inline(_png(800, 600))), encoding="utf-8")
    assert not B.plan_kr(tmp_path)[0].ok


def test_kr_reuses_identical_existing_file_and_stops_on_conflict(tmp_path):
    """같은 해시면 재사용, 다르면 중단(codex 검토 6.3)."""
    (tmp_path / "kr" / "posts").mkdir(parents=True)
    (tmp_path / "kr" / "assets").mkdir(parents=True)
    post = tmp_path / "kr" / "posts" / "2026-09-03.html"
    post.write_text(_doc(_inline(DAILY)), encoding="utf-8")

    (tmp_path / "kr" / "assets" / "kr_charts_2026-09-03.png").write_bytes(DAILY)
    assert B.plan_kr(tmp_path)[0].ok

    (tmp_path / "kr" / "assets" / "kr_charts_2026-09-03.png").write_bytes(FLOWS)
    plan = B.plan_kr(tmp_path)
    assert not plan[0].ok and "충돌" in plan[0].why


def test_truncated_png_does_not_abort_the_whole_plan(tmp_path):
    """잘린 PNG 하나에 `struct.error` 가 나면 계획 수립 자체가 멈춰,
    「그 편만 건너뛴다」는 계약이 지켜지지 않는다(2026-09-06 codex 검토)."""
    (tmp_path / "kr" / "posts").mkdir(parents=True)
    (tmp_path / "kr" / "posts" / "2026-09-02.html").write_text(
        _doc(_inline(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")), encoding="utf-8")
    (tmp_path / "kr" / "posts" / "2026-09-03.html").write_text(
        _doc(_inline(DAILY)), encoding="utf-8")

    plan = B.plan_kr(tmp_path)          # 예외 없이 끝나야 한다
    assert [p.ok for p in plan] == [False, True]


def test_png_size_of_a_truncated_header_is_none():
    assert B.png_size(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") is None
