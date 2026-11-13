"""KR 표 숫자 대조를 발행 전 기록(`run_gates`)으로 돌린다 — 실제 `check_numbers.py --market kr` (2026-11-13).

- 편집자 노트에만 있는 틀린 표 숫자는 US 와 같은 `kind: numbers` 처리: 발행은 되지만 「노트 수치 불일치」로
  설정된 검사 완료가 아니다(record.py 에 새 코드 없이 — codex 설계 검토 #12).
- 적용일 전 글은 not_run, `{date}` 가 글 날짜로 들어간다(#11).
고정 자료는 KR 시험의 11/12 판(적용일 전이라 시험 설정에서만 `--effective` 로 연다 — 실제 목록은 쓰지 않는다).
"""
import json
import os
import shutil

import pytest

from verification import record as R

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
FIX = os.path.join(SCRIPTS, 'kr', 'tests', 'fixtures', 'number_audit', '2026-11-12')
NOTE = ('<section id="editor-note" data-editor-note="2026-11-12"><h2>에디터 노트</h2><table><thead><tr>'
        '<th>지수</th><th>종가</th></tr></thead><tbody><tr><td>코스피</td><td>5,999.99</td></tr></tbody></table>'
        '</section>')


def _cfg(tmp_path, effective=True):
    argv = ['scripts/check_numbers.py', '--html', '{html}', '--datadir', '{datadir}', '--market', 'kr',
            '--date', '{date}'] + (['--effective', '2026-01-01'] if effective else [])
    cfg = {'format': 'prepub-gates/1', 'disabled': {},
           'markets': {'kr': {'post': 'kr/posts/{date}.html',
                              'gates': [{'name': 'check_numbers', 'argv': argv, 'kind': 'numbers',
                                         'required': True, 'json': True}]}}}
    p = tmp_path / 'gates.json'
    p.write_text(json.dumps(cfg), encoding='utf-8')
    return R.load_config(str(p))


def _run(tmp_path, html, effective=True):
    ws = tmp_path / 'ws'
    if not ws.exists():
        ws.mkdir()
        for n in os.listdir(FIX):
            if n.endswith('.json'):
                shutil.copy(os.path.join(FIX, n), ws / n)
    post = tmp_path / 'post' / '2026-11-12.html'
    post.parent.mkdir(exist_ok=True)
    post.write_text(html, encoding='utf-8')
    ctx = dict(html=str(post), datadir=str(ws), repo=ROOT, date='2026-11-12')
    return R.run_gates(_cfg(tmp_path, effective), 'kr', ctx, timeout=120, total=300)


@pytest.fixture(scope='module')
def post():
    with open(os.path.join(FIX, 'post.html'), encoding='utf-8') as fh:
        return fh.read()


def test_clean_post_records_numbers(tmp_path, post):
    r = _run(tmp_path, post)
    g = r['gates'][0]
    assert g['status'] == 'pass', g
    assert g['numbers']['table_cells'] == 54 and g['numbers']['prose_judged'] == 0
    assert 'KR 문장' in g['numbers']['unverified_by']
    assert r['summary']['publish_ok']


def test_note_only_table_number_is_note_numbers(tmp_path, post):
    html = post.replace('</main>', NOTE + '</main>', 1) if '</main>' in post else post.replace('</body>', NOTE + '</body>', 1)
    r = _run(tmp_path, html)
    g = r['gates'][0]
    assert g['status'] == 'fail' and g['note']['stripped_status'] == 'pass', g
    assert r['summary']['publish_ok'] and r['summary']['note_numbers'] == ['check_numbers']
    assert not r['summary']['verified']


def test_body_table_error_blocks(tmp_path, post):
    r = _run(tmp_path, post.replace('<td class="up">+416</td>', '<td class="up">+417</td>', 1))
    assert r['gates'][0]['status'] == 'fail' and not r['summary']['publish_ok']
    assert any('시장=코스닥 행=기관' in x for x in r['gates'][0]['items'])


def test_before_effective_is_not_run(tmp_path, post):
    r = _run(tmp_path, post, effective=False)
    assert r['gates'][0]['status'] == 'not_run'
    assert r['summary']['publish_ok'] and r['summary']['not_run'] == ['check_numbers']
