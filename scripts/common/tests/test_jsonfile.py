"""공용 JSON 읽기 도우미 — 흡수한 사본들과 같은 동작(없는 파일·깨진 JSON·빈 파일·인코딩)을 지키는가."""
import pathlib

import pytest

from scripts.common import jsonfile as J


def _w(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


CASES_NONE = {
    'missing': lambda t: str(t / 'nope.json'),
    'missing_parent': lambda t: str(t / 'nodir' / 'x.json'),
    'directory': lambda t: str(t),
    'empty': lambda t: _w(t, 'e.json', b''),
    'bad_json': lambda t: _w(t, 'b.json', b'{"a": '),
    'not_utf8': lambda t: _w(t, 'u.json', b'{"a": "\xff"}'),
    'bom': lambda t: _w(t, 'bom.json', '﻿{"a": 1}'.encode('utf-8')),
}


@pytest.mark.parametrize('case', sorted(CASES_NONE))
def test_or_none_returns_none_quietly(tmp_path, capsys, case):
    assert J.load_json_or_none(CASES_NONE[case](tmp_path)) is None
    assert capsys.readouterr().err == ''


def test_or_none_reads_values(tmp_path):
    assert J.load_json_or_none(_w(tmp_path, 'd.json', b'{"a": 1.5, "a": [1]}')) == {'a': [1]}
    assert J.load_json_or_none(_w(tmp_path, 'l.json', b'[1, 2]')) == [1, 2]
    assert J.load_json_or_none(_w(tmp_path, 's.json', b'3')) == 3
    assert J.load_json_or_none(_w(tmp_path, 'n.json', b'null')) is None
    assert J.load_json_or_none(pathlib.Path(_w(tmp_path, 'p.json', b'{}'))) == {}


def test_or_none_lets_a_bad_path_type_raise():
    with pytest.raises(TypeError):
        J.load_json_or_none(None)

