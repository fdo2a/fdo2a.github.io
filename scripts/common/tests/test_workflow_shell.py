"""워크플로 `run:` 블록의 셸 문법 검사 (2026-09-24).

뉴스 단계 끝에 따옴표 하나가 더 붙어(`--date "$RD""`) 그 단계가 매 실행 문법 오류로
죽을 뻔했다. `continue-on-error` 라 실행은 노랗게 지나가고, 뉴스 파일만 조용히 사라진다.
YAML 이 유효해도 셸은 틀릴 수 있다 — 그 사이를 여기서 막는다.
"""
import glob
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
WORKFLOWS = sorted(glob.glob(os.path.join(ROOT, '.github', 'workflows', '*.yml')))
_RUN = re.compile(r'^(\s*)(?:-\s+)?run:\s*(.*)$')
_EXPR = re.compile(r'\$\{\{.*?\}\}')


def run_blocks(text):
    lines = text.split('\n')
    out, i = [], 0
    while i < len(lines):
        m = _RUN.match(lines[i])
        if not m:
            i += 1
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if rest in ('|', '|-', '>', '>-'):
            body, i = [], i + 1
            while i < len(lines) and (not lines[i].strip()
                                      or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body.append(lines[i])
                i += 1
            out.append('\n'.join(body))
        else:
            out.append(rest)
            i += 1
    return [_EXPR.sub('X', b) for b in out]


@pytest.mark.skipif(not shutil.which('bash'), reason='bash 없음')
@pytest.mark.parametrize('path', WORKFLOWS, ids=os.path.basename)
def test_every_run_block_is_valid_bash(path):
    with open(path, encoding='utf-8') as fh:
        blocks = run_blocks(fh.read())
    assert blocks, path
    for n, block in enumerate(blocks):
        r = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
        assert r.returncode == 0, f'{os.path.basename(path)} run #{n}: {r.stderr}\n{block}'


def test_the_extractor_catches_the_bug_that_prompted_it():
    bad = '    steps:\n      - name: x\n        run: |\n          echo "$RD""\n'
    [block] = run_blocks(bad)
    assert subprocess.run(['bash', '-n'], input=block, text=True).returncode != 0
