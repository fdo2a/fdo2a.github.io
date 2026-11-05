"""흐름 후보 스캐너 — 무엇이 후보가 되고 무엇이 빠지는가."""

import json
import os
import subprocess
import sys

import pytest

from close import flow, locks

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORT2 = '유가가 2% 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'


def page(*ps, wrap=None):
    body = ''.join(ps)
    if wrap:
        body = wrap % body
    return '<html><body><div class="card">%s</div></body></html>' % body


def ids(html, **kw):
    return [i['masked'] for i in flow.scan(html, **kw)['items']]


def test_two_short_sentences_is_candidate():
    out = flow.scan(page('<p>%s</p>' % SHORT2))
    assert len(out['items']) == 1
    item = out['items'][0]
    raw = page('<p>%s</p>' % SHORT2).encode('utf-8')
    assert raw[item['start']:item['end']].decode() == SHORT2
    assert item['inner_sha1'] == flow.sha1(SHORT2.encode())
    assert out['source_sha256'] == flow.sha256(raw)


def test_one_short_sentence_is_not():
    text = '유가가 2% 올랐다. 금리는 이번 주 내내 좁은 범위에서 오르내리다가 소폭 낮아진 채로 마감했다.'
    assert ids(page('<p>%s</p>' % text)) == []


def test_byte_offsets_with_multibyte_prefix():
    html = page('<p>앞 문단은 길게 써서 후보가 아니도록 충분한 길이를 가진 문장 하나로 둔다.</p>',
                '<p>%s</p>' % SHORT2)
    item = flow.scan(html)['items'][0]
    assert html.encode()[item['start']:item['end']].decode() == SHORT2


@pytest.mark.parametrize('wrap', [
    '<blockquote>%s</blockquote>', '<section data-contested="x">%s</section>',
    '<div data-editor-note="1">%s</div>', '<table><tr><td>%s</td></tr></table>',
    '<section data-research-cycle="c1">%s</section>', '<section data-learning>%s</section>',
    '<section data-section="review">%s</section>', "<section data-section='review'>%s</section>",
    '<section data-section=review>%s</section>', '<section DATA-LEARNING>%s</section>',
])
def test_protected_and_zone_regions_excluded(wrap):
    assert ids(page('<p>%s</p>' % SHORT2, wrap=wrap)) == []


@pytest.mark.parametrize('attr', ['data-hypothesis', 'data-lede', 'data-interp', 'data-alt', 'data-watch',
                                  'data-falsifier', 'data-cause', 'data-standing'])
def test_zone_paragraph_attrs_excluded(attr):
    assert ids(page('<p %s="x">%s</p>' % (attr, SHORT2))) == []


def test_inline_protected_excluded():
    assert ids(page('<p>유가가 올랐다. <q>금리가 내렸다</q>. 달러는 보합이었다.</p>')) == []


@pytest.mark.parametrize('q', ['“', '”', '‘', '「', '』', '"', "'", '&ldquo;', '&#34;', '&#x22;', '&quot;'])
def test_any_quote_excluded(q):
    assert ids(page('<p>유가가 %s올랐다. 금리가 내렸다. 달러는 보합이었다.</p>' % q)) == []


@pytest.mark.parametrize('sent', ['우리는 반등이 이르다고 판단한다.', '16일 종가까지 본다.',
                                  '뒷받침 쪽이다.', '가설은 유효하다.'])
def test_locked_sentence_excludes_paragraph(sent):
    assert ids(page('<p>유가가 올랐다. 금리가 내렸다. %s</p>' % sent)) == []


def test_ledger_anchor_locks():
    led = locks.Ledger([{'type': 'hypothesis', 'report_date': '2026-10-12', 'support': 'x 3.88%p 넘게',
                         'invalidation': '', 'deadline': '2026-10-16T20:00:00Z'}], 'us', '2026-10-13')
    text = '마이크론이 3.88%p 뒤처졌다. 금리가 내렸다. 달러는 보합이었다.'
    assert ids(page('<p>%s</p>' % text), ledger=led) == []
    assert len(ids(page('<p>%s</p>' % text))) == 1          # 원장이 없으면 잠그지 않는다
    later = locks.Ledger([{'type': 'hypothesis', 'report_date': '2026-10-20', 'support': '3.88%p'}],
                         'us', '2026-10-13')
    assert len(ids(page('<p>%s</p>' % text), ledger=later)) == 1   # 글 뒤 원장은 보지 않는다


def test_caption_and_summary_excluded():
    assert ids(page('<p class="caption">%s</p>' % SHORT2, '<p data-summary="1">%s</p>' % SHORT2)) == []


def _run(*args, env=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'scan_translationese.py'), *args],
                          capture_output=True, text=True, env=env)


def test_cli_writes_candidates(tmp_path):
    src = tmp_path / 'pre.html'
    src.write_text(page('<p>%s</p>' % SHORT2), encoding='utf-8')
    out = tmp_path / 'candidates.json'
    r = _run('--flow', str(src), '--out', str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().splitlines()[-1] == 'flow: candidates 1'
    assert len(json.loads(out.read_text())['items']) == 1


def test_cli_exit_2_on_missing_input(tmp_path):
    r = _run('--flow', str(tmp_path / 'nope.html'), '--out', str(tmp_path / 'c.json'))
    assert r.returncode == 2
    assert not (tmp_path / 'c.json').exists()


def test_cli_exit_2_on_repo_output(tmp_path):
    src = tmp_path / 'pre.html'
    src.write_text(page('<p>%s</p>' % SHORT2), encoding='utf-8')
    target = os.path.join(os.path.dirname(SCRIPTS), 'candidates_leak.json')
    r = _run('--flow', str(src), '--out', target)
    assert r.returncode == 2
    assert not os.path.exists(target)


def test_cli_exit_2_outside_close_dir(tmp_path):
    src = tmp_path / 'pre.html'
    src.write_text(page('<p>%s</p>' % SHORT2), encoding='utf-8')
    (tmp_path / 'cd').mkdir()
    env = dict(os.environ, CLOSE_DIR=str(tmp_path / 'cd'))
    assert _run('--flow', str(src), '--out', str(tmp_path / 'c.json'), env=env).returncode == 2
    assert _run('--flow', str(src), '--out', str(tmp_path / 'cd' / 'c.json'), env=env).returncode == 0


def test_default_mode_unchanged_exit_0(tmp_path):
    assert _run(str(tmp_path / 'nope.html')).returncode == 0
