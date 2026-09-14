"""`--no-inline-images` 는 파이프라인별로 켠다.

KR 은 A-2(수집기 날짜별 파일화)가 끝나기 전까지 임베드가 유일한 아카이브 수단이라,
공통 게이트에서 무조건 켜면 KR 발행이 그날로 막힌다(2026-09-06 codex 검토 5.1).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / "scripts" / "check_readability.py"
B64 = "iVBORw0KGgoAAAANSUhEUg" + "A" * 2000


def _post(tmp_path, body):
    from scripts.us import readability as R
    html = R.inject_css(
        "<html><head></head><body><div class='card'><h1>제목</h1>"
        "<p>코스피는 20일선을 웃돌아 마감했다.</p>%s</div></body></html>" % body)
    p = tmp_path / "post.html"
    p.write_text(html, encoding="utf-8")
    return p


def _run(path, *flags):
    return subprocess.run([sys.executable, str(GATE), *flags, str(path)],
                          capture_output=True, text=True, cwd=str(ROOT))


def test_inline_image_passes_without_the_flag(tmp_path):
    p = _post(tmp_path, '<img src="data:image/png;base64,%s">' % B64)
    assert _run(p).returncode == 0


def test_inline_image_fails_with_the_flag(tmp_path):
    p = _post(tmp_path, '<img src="data:image/png;base64,%s">' % B64)
    r = _run(p, "--no-inline-images")
    assert r.returncode == 1
    assert "base64" in r.stdout


def test_external_reference_passes_with_the_flag(tmp_path):
    p = _post(tmp_path, '<img src="../assets/yield_curve_2026-09-04.png" alt="커브">')
    assert _run(p, "--no-inline-images").returncode == 0


def test_zero_prose_document_reports_instead_of_crashing(tmp_path):
    """산문이 없는 문서에서 요약 출력이 KeyError 로 죽으면, 그 아래 FAIL 이 한 줄도
    안 찍힌다. 종료 코드 1 만 남아 「검사가 걸렀다」와 구별되지 않는다."""
    p = _post(tmp_path, '<img src="data:image/png;base64,%s">' % B64)
    # 산문 문단을 지워 문장 0개로 만든다
    p.write_text(p.read_text(encoding="utf-8").replace(
        "<p>코스피는 20일선을 웃돌아 마감했다.</p>", ""), encoding="utf-8")
    r = _run(p, "--no-inline-images")
    assert "Traceback" not in r.stderr
    assert "base64" in r.stdout
    assert r.returncode == 1


def test_a_long_sentence_no_longer_blocks_publishing(tmp_path):
    """2026-09-14 사용자 지시 — 길이는 재서 보여 주되 막지 않는다.

    `--strict` 에서 경고는 곧 발행 중단이므로, 길이가 `warns` 로 남아 있으면 이
    변경은 아무것도 바꾸지 못한다. 그래서 문구가 아니라 종료 코드로 검사한다.
    """
    long_one = '나스닥은 ' + '개장 직후 밀렸다가 오후 내내 되돌리며 ' * 8 + '마감했습니다.'
    assert len(long_one) > 160
    p = _post(tmp_path, '<p>%s</p>' % long_one)
    r = _run(p, '--strict')
    assert r.returncode == 0, r.stdout
    assert '자 문장' in r.stdout and 'info' in r.stdout
    assert 'FAIL' not in r.stdout


def test_figure_density_still_blocks(tmp_path):
    """길이는 풀되 수치 밀도는 남긴다 — 기사도 한 문장에 수치 여섯이면 안 읽힌다."""
    dense = ('S&P 500은 6,584.29로 0.85% 올랐고 나스닥은 22,141.10으로 0.72%, '
             '다우는 45,883.45로 1.36%, 러셀은 2,391.05로 2.11%, '
             '10년물은 4.06%로 3.2bp 움직였습니다.')
    p = _post(tmp_path, '<p>%s</p>' % dense)
    r = _run(p, '--strict')
    assert r.returncode == 1, r.stdout
    assert '수치' in r.stdout


def test_the_headline_figure_rule_did_not_move_with_the_body(tmp_path):
    """본문 임계를 넷 → 여섯으로 풀 때 제목 규칙이 딸려 풀렸었다 (2026-09-14).

    계약은 제목 수치 넷 이내 그대로다.
    """
    from scripts.us import readability as R
    html = R.inject_css(
        "<html><head></head><body><div class='card'>"
        "<h1>S&P 6,584 · 나스닥 22,141 · 다우 45,883 · 러셀 2,391 · 10년물 4.06%</h1>"
        "<p>코스피는 20일선을 웃돌아 마감했다.</p></div></body></html>")
    p = tmp_path / "h1.html"
    p.write_text(html, encoding="utf-8")
    r = _run(p, "--strict")
    assert "헤드라인 수치" in r.stdout, r.stdout


def test_a_decoy_headline_cannot_take_the_real_one_out_of_scope(tmp_path):
    """첫 h1 만 보면 짧은 미끼를 앞에 두는 것으로 제목 검사를 통째로 피한다."""
    from scripts.us import readability as R
    html = R.inject_css(
        "<html><head></head><body><div class='card'>"
        "<h1>시황</h1>"
        "<h1>S&P 6,584 · 나스닥 22,141 · 다우 45,883 · 러셀 2,391 · 10년물 4.06%</h1>"
        "<p>코스피는 20일선을 웃돌아 마감했다.</p></div></body></html>")
    p = tmp_path / "decoy.html"
    p.write_text(html, encoding="utf-8")
    r = _run(p, "--strict")
    assert "헤드라인 수치" in r.stdout, r.stdout
