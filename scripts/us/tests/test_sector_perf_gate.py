"""섹터 기간 수익률 표가 그날 섹터 등락률과 같은 회차인가 (2026-10-12 사고)."""
import importlib
import json
import math
import subprocess
import sys

import pytest

cmd = importlib.import_module('collect_market_data')
from us import sector_perf_gate as g  # noqa: E402

RD = '2026-10-14'          # strict 적용일


def _market(pct=None, perf=None, rd=RD, dated=True):
    pct, perf = pct or {}, perf or {}
    m = {'report_date': rd, 'sectors': {}, 'sector_performance': {}}
    for i, (n, _) in enumerate(cmd.SECTORS):
        p = pct.get(n, 0.1 * (i + 1))
        m['sectors'][n] = {'pct': p, 'date': rd}
        row = {'1D': round(p, 2), '1W': 1.0 + i, '1M': -2.0 + i, '6M': 3.5, '1Y': 7.25}
        row.update(perf.get(n, {}))
        if dated:
            row['date'] = rd
        m['sector_performance'][n] = row
    return m


def _table(market, tmp_path):
    p = tmp_path / 'sp.html'
    cmd.render_sector_perf_html(market['sector_performance'], market['report_date'], str(p))
    return '<html><body>' + p.read_text() + '</body></html>'


def test_constants_match_the_collector():
    assert g.SECTORS == tuple(n for n, _ in cmd.SECTORS)
    assert g.HORIZONS == tuple((k, cmd.PERF_LABELS[k]) for k, _ in cmd.PERF_HORIZONS)
    assert g.SHORT == cmd.PERF_SHORT


def test_consistent_data_and_table_pass(tmp_path):
    m = _market(pct={'Communication Services': 0.9693782582433252})
    assert g.check(_table(m, tmp_path), m) == []


def test_display_value_is_compared_exactly():
    m = _market(pct={'Energy': 0.9694}, perf={'Energy': {'1D': 0.97}})
    assert not any('불일치' in x for x in g.check('', m))      # 0.9694 → +0.97
    m = _market(pct={'Energy': 0.97}, perf={'Energy': {'1D': 0.96}})
    assert any('불일치' in x and 'Energy' in x for x in g.check('', m))


def test_data_where_one_side_was_patched_is_caught():
    m = _market(pct={'Communication Services': 0.9694},
                perf={'Communication Services': {'1D': -1.51}})
    v = [x for x in g.check('', m) if '불일치' in x]
    assert len(v) == 1 and '-1.51' in v[0]


def test_complete_true_does_not_excuse_a_stale_row():
    m = _market()
    m['complete'] = True
    m['sector_performance']['Real Estate']['date'] = '2026-10-13'
    assert any('낡은 섹터 행' in x and 'Real Estate' in x for x in g.check('', m))


def test_undated_rows_block_from_the_strict_date_only():
    assert any('날짜가 없다' in x for x in g.check('', _market(dated=False)))
    old = _market(rd='2026-10-12', dated=False)
    assert not any('날짜가 없다' in x for x in g.check('', old))


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), 'x'])
def test_missing_or_non_finite_values_block(bad):
    m = _market()
    m['sectors']['Energy']['pct'] = bad
    assert any('Energy' in x and '누락' in x for x in g.check('', m))
    m = _market()
    m['sector_performance']['Energy']['1D'] = bad
    assert any('Energy' in x and '누락' in x for x in g.check('', m))


def test_removed_sector_row_blocks():
    m = _market()
    m['sectors']['Energy'] = None
    assert any('Energy' in x for x in g.check('', m))


def test_table_with_a_stale_value_in_any_horizon_is_caught(tmp_path):
    good = _market()
    stale = _market(perf={'Real Estate': {'1W': 1.96}})
    v = g.check(_table(stale, tmp_path), good)
    assert any('1주' in x and 'Real Estate' in x and '+1.96%' in x for x in v)


def test_abbreviated_names_are_mapped_back(tmp_path):
    good = _market(pct={'Communication Services': 0.97})
    bad = _market(pct={'Communication Services': 0.97},
                  perf={'Communication Services': {'1D': -1.51}})
    v = g.check(_table(bad, tmp_path), good)
    assert any('1일' in x and 'Communication Services' in x for x in v)


def test_a_hidden_good_block_does_not_cover_a_visible_stale_one(tmp_path):
    good = _market()
    stale = _market(perf={'Energy': {'1D': 9.99}})
    good_html, stale_html = _table(good, tmp_path), _table(stale, tmp_path)
    doc = good_html.replace('<body>', '<body><div style="display:none">', 1) \
        .replace('</body>', '</div>' + stale_html[len('<html><body>'):-len('</body></html>')] + '</body>')
    v = g.check(doc, good)
    assert any('블록이 2개' in x for x in v)


def test_duplicate_and_unknown_rows_block(tmp_path):
    m = _market()
    html = _table(m, tmp_path)
    dup = html.replace('<span class="spf-name">Utilities</span>', '<span class="spf-name">Energy</span>', 1)
    assert any('두 번' in x for x in g.check(dup, m))
    unk = html.replace('<span class="spf-name">Utilities</span>', '<span class="spf-name">Utilitiez</span>', 1)
    v = g.check(unk, m)
    assert any('알 수 없는' in x for x in v) and any('Utilities 행이 없다' in x for x in v)


def test_renamed_or_removed_block_is_caught(tmp_path):
    m = _market()
    html = _table(m, tmp_path).replace('>1일 수익률<', '>하루 수익률<', 1)
    assert any('「1일 수익률」 블록이 0개' in x for x in g.check(html, m))


def test_post_without_the_table_blocks_from_the_strict_date():
    assert any('블록이 0개' in x for x in g.check('<p>표 없음</p>', _market()))
    assert g.check('<p>표 없음</p>', _market(rd='2026-10-12', dated=False)) == []


def _git_json(rev, path):
    return json.loads(subprocess.check_output(['git', 'show', f'{rev}:{path}']))


def test_the_10_12_incident():
    try:
        bad = _git_json('5457d76', 'data/market_data.json')
        good = _git_json('d1480b5', 'data/market_data.json')
        tbl = subprocess.check_output(['git', 'show', '5457d76:data/sector_performance.html']).decode()
    except subprocess.CalledProcessError:
        pytest.skip('history not available')
    v = g.check('', bad)
    assert sorted(x.split(':')[1].split()[0] for x in v) == ['Communication', 'Real']
    assert g.check('', good) == []
    v = g.check(tbl, good)
    # 낡은 두 업종이 다섯 기간 모두에서 어긋난다(1W 의 XLC 처럼 우연히 같은 값은 없었다)
    assert {('Communication Services' in x) or ('Real Estate' in x) for x in v} == {True}
    assert len(v) >= 8


def test_cli_exit_codes(tmp_path):
    m = _market()
    (tmp_path / 'market_data.json').write_text(json.dumps(m))
    post = tmp_path / 'p.html'
    post.write_text(_table(m, tmp_path))
    run = lambda *a: subprocess.run([sys.executable, 'scripts/check_sector_perf.py', *a],
                                    capture_output=True, text=True).returncode
    assert run('--html', str(post), '--datadir', str(tmp_path)) == 0
    m['sectors']['Energy']['pct'] = 5.0
    (tmp_path / 'market_data.json').write_text(json.dumps(m))
    assert run('--html', str(post), '--datadir', str(tmp_path)) == 1
    assert run('--html', str(post), '--datadir', str(tmp_path / 'nope')) == 2
    (tmp_path / 'market_data.json').write_text('{broken')
    assert run('--html', str(post), '--datadir', str(tmp_path)) == 2


@pytest.mark.parametrize('rd', [None, '', '20261014', 7])
def test_missing_or_malformed_report_date_blocks(rd):
    m = _market()
    m['report_date'] = rd
    assert any('report_date' in x for x in g.check('', m))


def test_data_from_before_the_period_table_existed_is_exempt():
    # 2026-07-15(fab354b) 자료에는 sector_performance 필드가 없었다.
    m = _market(rd='2026-07-15', dated=False)
    del m['sector_performance']
    assert g.check('<p>옛 글</p>', m) == []
    m = _market()
    del m['sector_performance']
    assert g.check('', m)          # 적용일 뒤에는 없으면 막는다


def test_real_july_data_is_exempt():
    try:
        m = _git_json('fab354b', 'data/market_data.json')
    except (subprocess.CalledProcessError, ValueError):
        pytest.skip('history not available')
    assert g.check('', m) == []


def test_cli_without_report_date_exits_2(tmp_path):
    m = _market()
    del m['report_date']
    (tmp_path / 'market_data.json').write_text(json.dumps(m))
    post = tmp_path / 'p.html'
    post.write_text('<p></p>')
    r = subprocess.run([sys.executable, 'scripts/check_sector_perf.py', '--html', str(post),
                        '--datadir', str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 2
