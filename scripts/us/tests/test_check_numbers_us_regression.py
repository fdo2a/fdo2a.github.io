"""`check_numbers.py` 의 US 경로 회귀 (2026-11-13, KR 표 대조를 붙이기 전 출력을 고정).

KR 분기(`--market kr`)를 더하면서 US 명령(`--market` 없음)의 종료 코드·stdout·stderr 가 한 글자도 바뀌지
않아야 한다(codex 설계 검토 #13). 고정 출력은 KR 분기를 넣기 **전** 코드로 만든 것이다
(`fixtures/number_audit/cli_golden_us.json`). 다시 만들려면 `REGEN_US_GOLDEN=1` — 정말 US 동작을 바꿀 때만.
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'number_audit', '2026-11-05')
GOLDEN = os.path.join(HERE, 'fixtures', 'number_audit', 'cli_golden_us.json')
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
KEYS = ('market_data', 'econ_indicators', 'macro_metrics', 'fund_board')


def _post():
    with open(os.path.join(FIX, 'post.html'), encoding='utf-8') as fh:
        return fh.read()


def _scenarios():
    post = _post()
    bad_table = post.replace('>4.477%<', '>4.478%<', 1)
    bad_prose = post.replace('S&amp;P는 4.36% 내린', 'S&amp;P는 4.37% 내린', 1)
    return {
        'ok_text': ('2026-11-05', post, (), []),
        'ok_json': ('2026-11-05', post, (), ['--json']),
        'table_violation_text': ('2026-11-05', bad_table, (), ['--prose', 'warn']),
        'table_violation_json': ('2026-11-05', bad_table, (), ['--prose', 'warn', '--json']),
        'prose_block_json': ('2026-11-05', bad_prose, (), ['--prose', 'block', '--json']),
        'missing_market_data': ('2026-11-05', post, ('market_data',), ['--json']),
        'date_mismatch': ('2026-11-06', post, (), ['--json']),
        'old_post_text': ('2026-09-30', post, (), []),
        'old_post_json': ('2026-09-30', post, (), ['--json']),
    }


def _run(tmp, name, date, html, drop, extra, market_flag):
    d = os.path.join(tmp, name)
    os.makedirs(os.path.join(d, 'ws'))
    p = os.path.join(d, f'morning_brief_{date}.html')
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(html)
    for k in KEYS:
        if k not in drop:
            with open(os.path.join(FIX, f'{k}.json'), encoding='utf-8') as src, \
                    open(os.path.join(d, 'ws', f'{k}.json'), 'w', encoding='utf-8') as dst:
                dst.write(src.read())
    args = [sys.executable, os.path.join(SCRIPTS, 'check_numbers.py'), '--html', p,
            '--datadir', os.path.join(d, 'ws'), *extra, *market_flag]
    r = subprocess.run(args, capture_output=True, text=True)
    norm = (lambda s: s.replace(d, '<DIR>'))
    return {'exit': r.returncode, 'stdout': norm(r.stdout), 'stderr': norm(r.stderr)}


def _all(tmp, market_flag=()):
    return {name: _run(tmp, name, *sc, market_flag)
            for name, sc in _scenarios().items()}


def test_us_cli_output_is_byte_identical_to_before_kr(tmp_path):
    got = _all(str(tmp_path))
    if os.environ.get('REGEN_US_GOLDEN') == '1':
        with open(GOLDEN, 'w', encoding='utf-8') as fh:
            json.dump(got, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write('\n')
    with open(GOLDEN, encoding='utf-8') as fh:
        want = json.load(fh)
    assert set(got) == set(want)
    for name in want:
        assert got[name] == want[name], name


def test_explicit_market_us_is_the_same_as_default(tmp_path):
    with open(GOLDEN, encoding='utf-8') as fh:
        want = json.load(fh)
    if '--market' not in open(os.path.join(SCRIPTS, 'check_numbers.py'), encoding='utf-8').read():
        pytest.skip('KR 분기 전')
    got = _all(str(tmp_path), ('--market', 'us'))
    for name in want:
        assert got[name] == want[name], name

