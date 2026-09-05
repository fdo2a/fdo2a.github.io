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
