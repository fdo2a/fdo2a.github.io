import json

from fund import publish


def test_writes_json_and_html(tmp_path):
    publish.write(tmp_path, 'a.json', 'a.html', {'status': 'ok'}, '<div>x</div>')
    assert json.loads((tmp_path / 'a.json').read_text())['status'] == 'ok'
    assert (tmp_path / 'a.html').read_text() == '<div>x</div>'


def test_unavailable_removes_yesterdays_html(tmp_path):
    (tmp_path / 'a.html').write_text('<div>old</div>')
    publish.write(tmp_path, 'a.json', 'a.html', publish.failed('2026-10-07', 't', 'boom'), None)
    assert not (tmp_path / 'a.html').exists()
    d = json.loads((tmp_path / 'a.json').read_text())
    assert d['status'] == 'unavailable' and 'boom' in d['missing'][0]


def test_failed_json_keeps_the_common_header():
    d = publish.failed('2026-10-07', 't', 'boom', universe=True)
    for k in ('schema_version', 'calculation_version', 'universe_version', 'report_date',
              'generated_at', 'status', 'missing', 'source_dates'):
        assert k in d
    assert 'universe_version' not in publish.failed('2026-10-07', 't', 'boom')
