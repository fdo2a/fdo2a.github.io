"""check_period --research-frozen — 발행 뒤 codex 문체 수정이 기간 리포트를 다시 검사할 때 (2026-10-01).

as-of 가 발행본에 남지 않아 연구 요약을 다시 렌더할 수 없다. 그 대신 요약이 원본과 바이트까지
같으면 떼고 나머지 검사를 전부 돌린다. 이 옵션이 없을 때는 요약 오류에서 바로 돌아가 수치 창작
검사까지 건너뛰었다 — 「원본과 같은 실패」로 봐주면 게이트 전체가 꺼진다.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PAGE = os.path.join(ROOT, 'kr/weekly/2026-W39.html')


def run(html_path, original):
    args = [sys.executable, os.path.join(ROOT, 'scripts/check_period.py'), '--html', html_path,
            '--agg', os.path.join(ROOT, 'kr/data/weekly/2026-W39.json'),
            '--recap', os.path.join(ROOT, 'recap_kr.json'),
            '--scorecard', os.path.join(ROOT, 'data/period_scorecard.json'),
            '--span', 'weekly', '--market', 'kr', '--research-frozen', original]
    p = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


def test_unchanged_summary_lets_the_other_checks_run():
    code, out = run(PAGE, PAGE)
    assert 'requires a verified ledger' not in out and 'changed after publishing' not in out


def test_a_changed_summary_is_a_violation(tmp_path):
    html = open(PAGE, encoding='utf-8').read().replace('검토 대상 2건', '검토 대상 3건')
    edited = tmp_path / 'p.html'
    edited.write_text(html, encoding='utf-8')
    code, out = run(str(edited), PAGE)
    assert code == 1 and 'changed after publishing' in out


def test_an_invented_number_is_still_caught(tmp_path):
    html = open(PAGE, encoding='utf-8').read()
    i = html.index('<p>', html.index('</h1>'))
    html = html[:i] + '<p>코스피는 이번 주 987.65% 올랐다.</p>' + html[i:]
    edited = tmp_path / 'p.html'
    edited.write_text(html, encoding='utf-8')
    code, out = run(str(edited), PAGE)
    assert code == 1 and '987.65' in out
