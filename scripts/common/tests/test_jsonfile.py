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


def test_warn_missing_is_silent(tmp_path, capsys):
    assert J.load_json_warn(str(tmp_path / 'nope.json')) is None
    assert J.load_json_warn(str(tmp_path / 'nodir' / 'x.json')) is None
    assert capsys.readouterr().err == ''


@pytest.mark.parametrize('case', ['directory', 'empty', 'bad_json', 'not_utf8', 'bom'])
def test_warn_other_failures_print_one_line(tmp_path, capsys, case):
    path = CASES_NONE[case](tmp_path)
    assert J.load_json_warn(path) is None
    err = capsys.readouterr().err
    assert err.startswith(f'WARN: could not read {path}: ') and err.count('\n') == 1


def test_warn_catches_a_bad_path_type_too(capsys):
    assert J.load_json_warn(None) is None
    assert capsys.readouterr().err.startswith('WARN: could not read None: ')


def test_warn_reads_values(tmp_path, capsys):
    assert J.load_json_warn(_w(tmp_path, 'd.json', b'{"a": 1}')) == {'a': 1}
    assert J.load_json_warn(_w(tmp_path, 'l.json', b'[1, 2]')) == [1, 2]
    assert J.load_json_warn(pathlib.Path(_w(tmp_path, 'p.json', b'{}'))) == {}
    assert capsys.readouterr().err == ''


# ── 2026-11-22 둘째 묶음: 짧은 사본 9개를 모은 네 읽기 ─────────────────────────────

load_json_if_exists, load_json_missing_none = J.load_json_if_exists, J.load_json_missing_none
load_json_path, load_json_strict = J.load_json_path, J.load_json_strict


def _files(tmp_path):
    good = tmp_path / 'good.json'
    good.write_text('{"a": 1}', encoding='utf-8')
    bad = tmp_path / 'bad.json'
    bad.write_text('{oops', encoding='utf-8')
    nonutf = tmp_path / 'nonutf.json'
    nonutf.write_bytes(b'\xff\xfe{}')
    return good, bad, nonutf, tmp_path / 'missing.json'


def test_missing_none_only_forgives_a_missing_file(tmp_path):
    good, bad, nonutf, missing = _files(tmp_path)
    assert load_json_missing_none(str(good)) == {'a': 1}
    assert load_json_missing_none(str(missing)) is None
    with pytest.raises(ValueError):
        load_json_missing_none(str(bad))
    with pytest.raises(UnicodeDecodeError):
        load_json_missing_none(str(nonutf))
    with pytest.raises(IsADirectoryError):
        load_json_missing_none(str(tmp_path))


def test_strict_raises_on_every_failure(tmp_path):
    good, bad, _, missing = _files(tmp_path)
    assert load_json_strict(str(good)) == {'a': 1}
    with pytest.raises(FileNotFoundError):
        load_json_strict(str(missing))
    with pytest.raises(ValueError):
        load_json_strict(str(bad))


def test_if_exists_skips_falsy_and_absent_paths_only(tmp_path):
    good, bad, _, missing = _files(tmp_path)
    assert load_json_if_exists(None) is None and load_json_if_exists('') is None
    assert load_json_if_exists(str(missing)) is None
    dangling = tmp_path / 'dangling.json'
    dangling.symlink_to(tmp_path / 'nope')
    assert load_json_if_exists(str(dangling)) is None      # os.path.exists follows the link
    assert load_json_if_exists(str(good)) == {'a': 1}
    with pytest.raises(ValueError):
        load_json_if_exists(str(bad))


def test_path_reader_needs_a_path_and_raises(tmp_path):
    good, bad, _, missing = _files(tmp_path)
    assert load_json_path(good) == {'a': 1} and load_json_path(str(good)) == {'a': 1}
    with pytest.raises(FileNotFoundError):
        load_json_path(missing)
    with pytest.raises(ValueError):
        load_json_path(bad)
    with pytest.raises(TypeError):
        load_json_path(None)
