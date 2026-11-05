import json
import os

from review import style_digest as d


def _rec(root, name, at, findings):
    folder = os.path.join(root, d.FOLDER)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), 'w', encoding='utf-8') as fh:
        json.dump({'at': at, 'path': 'posts/%s.html' % name[:10], 'findings': findings}, fh, ensure_ascii=False)


def test_digest_groups_by_kind_and_window(tmp_path):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    _rec(tmp_path, '2026-11-05.json', now.isoformat(), [
        {'kind': '끊긴 흐름', 'quote': 'a', 'note': 'b'}, {'kind': '번역투', 'quote': 'c', 'note': 'd'},
        {'kind': '끊긴 흐름', 'quote': 'e', 'note': 'f'}])
    _rec(tmp_path, '2026-10-01.json', (now - timedelta(days=30)).isoformat(), [{'kind': '반복'}])
    _rec(tmp_path, 'broken.json', 'x', [{'kind': '반복'}])
    rows = d.collect(str(tmp_path), d._since('7d'))
    assert len(rows) == 3
    text = d.digest(rows)
    assert text.splitlines()[0] == '문체 지적 묶음 — 3건, 글 1편'
    assert text.index('[끊긴 흐름] 2건') < text.index('[번역투] 1건')
    assert '반복' not in text


def test_digest_cli_empty(tmp_path, capsys):
    assert d.main(['--root', str(tmp_path)]) == 0
    assert '0건' in capsys.readouterr().out
