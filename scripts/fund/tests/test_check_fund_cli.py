import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(__file__), '..', '..', 'check_fund.py')


def run(tmp_path, name, *extra):
    html = tmp_path / name
    html.write_text('<main><section><h2>매크로</h2><p>x</p></section></main>')
    (tmp_path / 'fund_board.json').write_text(json.dumps(
        {'status': 'ok', 'report_date': '2026-10-08', 'units': []}))
    return subprocess.run([sys.executable, SCRIPT, '--html', str(html), '--datadir', str(tmp_path),
                           *extra], capture_output=True, text=True)


def test_owed_section_missing_fails(tmp_path):
    assert run(tmp_path, 'morning_brief_2026-10-08.html').returncode == 1


def test_date_cannot_override_filename(tmp_path):
    p = run(tmp_path, 'morning_brief_2026-10-08.html', '--date', '2026-10-01')
    assert p.returncode == 1 and '파일명 날짜' in p.stdout


def test_date_used_only_when_filename_has_none(tmp_path):
    assert run(tmp_path, 'brief.html', '--date', '2026-10-01').returncode == 0
    assert run(tmp_path, 'brief.html', '--date', '2026-10-08').returncode == 1


def test_print_block_renders_from_the_day_json(tmp_path):
    from fund import render
    from fund.tests.test_core_render import build
    board = build()
    (tmp_path / 'fund_board.json').write_text(json.dumps(board, ensure_ascii=False))
    name = f"morning_brief_{board['report_date']}.html"
    p = subprocess.run([sys.executable, SCRIPT, '--html', name, '--datadir', str(tmp_path),
                        '--print-block'], capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout == render.board_html(board)
    wrong = subprocess.run([sys.executable, SCRIPT, '--html', 'morning_brief_2099-01-01.html',
                            '--datadir', str(tmp_path), '--print-block'], capture_output=True, text=True)
    assert wrong.returncode == 1


def test_print_block_unavailable_fails(tmp_path):
    (tmp_path / 'fund_board.json').write_text('{"status": "unavailable"}')
    p = subprocess.run([sys.executable, SCRIPT, '--html', 'x.html', '--datadir', str(tmp_path),
                        '--print-block'], capture_output=True, text=True)
    assert p.returncode == 1
