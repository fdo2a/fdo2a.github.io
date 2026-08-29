"""finalize — 원본을 교체해도 되는 순간을 기계가 판정하는가."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import humanize_prose  # noqa: E402

HTML = """<html><body>
<p>나스닥은 1.2% 올랐다. 반도체가 상승을 이끌었다.</p>
<p>국채금리는 소폭 내렸고 달러는 약세를 보였다.</p>
</body></html>"""


def _setup(tmp_path, edit=lambda s: s):
    orig = tmp_path / 'brief.html'
    copy = tmp_path / 'brief.humanizing.html'
    orig.write_text(HTML, encoding='utf-8')
    copy.write_text(HTML, encoding='utf-8')
    payload = tmp_path / 'prose_in.txt'
    sidecar = tmp_path / 'prose_map.json'
    humanize_prose.main(['extract', str(copy), '--out', str(payload), '--sidecar', str(sidecar)])
    payload.write_text(edit(payload.read_text(encoding='utf-8')), encoding='utf-8')
    return orig, copy, payload, sidecar


def _finalize(orig, copy, payload, sidecar, gates):
    argv = ['finalize', str(copy), '--original', str(orig),
            '--payload', str(payload), '--sidecar', str(sidecar)]
    for g in gates:
        argv += ['--gate', g]
    return humanize_prose.main(argv)


def test_전부_통과하면_원본을_교체하고_사본은_사라진다(tmp_path):
    orig, copy, payload, sidecar = _setup(tmp_path, lambda s: s.replace('올랐다.', '올랐습니다.'))
    assert _finalize(orig, copy, payload, sidecar, ['true']) == 0
    assert '올랐습니다' in orig.read_text(encoding='utf-8')
    assert not copy.exists()


def test_게이트가_실패하면_사본을_버리고_원본은_그대로다(tmp_path):
    orig, copy, payload, sidecar = _setup(tmp_path, lambda s: s.replace('올랐다.', '올랐습니다.'))
    assert _finalize(orig, copy, payload, sidecar, ['true', 'false']) == 1
    assert orig.read_text(encoding='utf-8') == HTML
    assert not copy.exists()


def test_되꽂기가_거부되면_원본은_그대로다(tmp_path):
    orig, copy, payload, sidecar = _setup(tmp_path, lambda s: s.replace('1.2%', '9.9%'))
    assert _finalize(orig, copy, payload, sidecar, ['true']) == 1
    assert orig.read_text(encoding='utf-8') == HTML


def test_게이트가_하나도_없으면_아예_시작하지_않는다(tmp_path):
    orig, copy, payload, sidecar = _setup(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _finalize(orig, copy, payload, sidecar, [])
    assert exc.value.code == 2
    assert orig.read_text(encoding='utf-8') == HTML
    assert copy.exists()


def test_사본과_원본이_같은_파일이면_아예_시작하지_않는다(tmp_path):
    orig, copy, payload, sidecar = _setup(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _finalize(orig, orig, payload, sidecar, ['false'])
    assert exc.value.code == 2
    assert orig.exists() and orig.read_text(encoding='utf-8') == HTML


def test_게이트는_셸을_거치지_않는다(tmp_path):
    """`--gate "cmd; rm -rf x"` 가 두 명령으로 갈라지지 않는다."""
    orig, copy, payload, sidecar = _setup(tmp_path)
    victim = tmp_path / 'victim'
    victim.write_text('x', encoding='utf-8')
    _finalize(orig, copy, payload, sidecar, ['true ; rm %s' % victim])
    assert victim.exists()
