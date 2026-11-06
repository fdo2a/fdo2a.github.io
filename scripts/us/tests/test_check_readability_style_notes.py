"""가독성 게이트의 문체 참고는 발행을 막지 않는다 — 2026-11-06 사용자 결정.

「경고 문구가 아니라 발행 차단 조건을 바꿔야 한다. 작성자가 자연스럽다고 판단해 그대로
두었는데 발행이 막힌다면 결국 수정할 수밖에 없다.」 모든 발행 경로가 `--strict` 로 돌기
때문에 경고가 곧 반려였다. 그래서 문구가 아니라 종료 코드로 검사한다. 막는 것은 조판이
깨지는 구조 문제(섹션 div 경계·인라인 이미지·조판 미적용)뿐이다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / "scripts" / "check_readability.py"


def _post(tmp_path, body, h1="제목"):
    from scripts.us import readability as R
    html = R.inject_css(
        "<html><head></head><body><div class='card'><h1>%s</h1>"
        "<p>코스피는 20일선을 웃돌아 마감했다.</p>%s</div></body></html>" % (h1, body))
    p = tmp_path / "post.html"
    p.write_text(html, encoding="utf-8")
    return p


def _strict(path):
    return subprocess.run([sys.executable, str(GATE), "--strict", "--no-inline-images", str(path)],
                          capture_output=True, text=True, cwd=str(ROOT))


def test_nine_figures_in_a_sentence_is_a_note(tmp_path):
    dense = ('<p>S&P 500은 6,584로 0.85%, 나스닥은 22,141로 0.72%, 다우는 45,883으로 1.36%, '
             '러셀은 2,391로 2.11%, 10년물은 4.06%로 3.2bp 움직였다.</p>')
    r = _strict(_post(tmp_path, dense))
    assert r.returncode == 0, r.stdout
    assert "note" in r.stdout and "수치" in r.stdout
    assert not [ln for ln in r.stdout.splitlines() if ln.startswith("   FAIL ")]


def test_long_headline_and_headline_figures_are_notes(tmp_path):
    h1 = "S&P 6,584 · 나스닥 22,141 · 다우 45,883 · 러셀 2,391 · 10년물 4.06% " + "긴 제목 " * 20
    r = _strict(_post(tmp_path, "", h1=h1))
    assert r.returncode == 0, r.stdout
    assert "헤드라인" in r.stdout


def test_overprecise_prose_figure_is_a_note(tmp_path):
    r = _strict(_post(tmp_path, "<p>삼성전자 종가는 2,043,967.25원이었다.</p>"))
    assert r.returncode == 0, r.stdout
    assert "과잉 정밀" in r.stdout


def test_repeated_figures_are_not_checked(tmp_path):
    echo = "".join("<p>코스피는 오늘 7,017 에서 마감했고 거래가 이어졌다 %d.</p>" % i for i in range(5))
    r = _strict(_post(tmp_path, echo))
    assert r.returncode == 0, r.stdout
    assert "되풀이" not in r.stdout


def test_structure_problems_still_block(tmp_path):
    broken = _post(tmp_path, "<section id='s3'><div class='card'><p>열린 채 끝난다.</p></section>")
    assert _strict(broken).returncode == 1
    p = tmp_path / "raw.html"
    p.write_text("<html><body><p>조판을 안 거친 글이다.</p></body></html>", encoding="utf-8")
    assert _strict(p).returncode == 1


def test_the_legend_says_notes_do_not_block(tmp_path):
    dense = "<p>지수는 1.1%, 2.2%, 3.3%, 4.4%, 5.5%, 6.6%, 7.7% 움직였고 모두 기록됐다.</p>"
    out = _strict(_post(tmp_path, dense)).stdout
    assert "막지 않는다" in out
    assert "자연스러우면 그대로" in out
