"""이력 종가 비교 — 알림만(2026-11-27 「숫자는 코드가 채운다」 1차 §7)."""
import json

from us import close_check as CC
from us.history import market_record

ROW = {'report_date': '2026-11-24', 'indices': {'S&P 500': 7200.0, 'Nasdaq': 23700.0},
       'sectors': {'Technology': 157.09}, 'fx': {'DXY': 103.8},
       'dates': {'indices': {'S&P 500': '2026-11-24', 'Nasdaq': '2026-11-24'}, 'sectors': {'Technology': '2026-11-24'},
                 'fx': {'DXY': '2026-11-24'}}}
TICK = {'indices': {'S&P 500': '^GSPC', 'Nasdaq': '^IXIC'}, 'sectors': {'Technology': 'XLK'}, 'fx': {'DXY': 'DX-Y.NYB'}}


def test_history_row_carries_per_asset_observation_date():
    row = market_record({'report_date': '2026-11-25',
                         'indices': {'S&P 500': {'last': 7182.78, 'date': '2026-11-25'}},
                         'session': {}, 'yields': {}})
    assert row['indices'] == {'S&P 500': 7182.78} and row['dates'] == {'indices': {'S&P 500': '2026-11-25'}}


def test_previous_row_needs_dates():
    assert CC.previous_row([ROW, {'report_date': '2026-11-25'}], '2026-11-25') is ROW
    assert CC.previous_row([{'report_date': '2026-11-24', 'indices': {}}], '2026-11-25') is None


def test_compare_same_date_bar_only_and_skips_dividends():
    bars = {'^GSPC': (['2026-11-21', '2026-11-24', '2026-11-25'], [7100.0, 7200.0, 7182.78], set()),
            '^IXIC': (['2026-11-21', '2026-11-25'], [23000.0, 23585.8], set()),          # 11/24 봉 없음 → 견주지 않음
            'XLK': (['2026-11-24', '2026-11-25'], [156.80, 155.79], {'2026-11-25'})}      # 그 뒤 배당 → 견주지 않음
    mism, checked, skipped = CC.compare(ROW, bars, TICK)
    assert mism == [] and checked == 1 and skipped == {'같은 날짜 봉 없음': 1, '배당·분할': 1}
    bars['^GSPC'] = (['2026-11-24'], [7210.5], set())
    mism, _, _ = CC.compare(ROW, bars, TICK)
    assert mism == [{'group': 'indices', 'asset': 'S&P 500', 'date': '2026-11-24', 'stored': 7200.0, 'fresh': 7210.5}]


def test_find_posts_uses_fills_and_says_what_it_could_not_read(tmp_path):
    (tmp_path / 'posts').mkdir()
    (tmp_path / 'verification' / 'us').mkdir(parents=True)
    for d in ('2026-11-24', '2026-11-25', '2026-11-20'):
        (tmp_path / 'posts' / f'{d}.html').write_text('x', encoding='utf-8')
    fills = [{'ref': 'md:indices.SP500.last', 'asset': 'S&P 500', 'group': 'indices', 'field': 'last',
              'date': '2026-11-24', 'value': 7200.0, 'text': '7,200.00'}]
    rec = {'gates': [{'name': 'check_number_sources', 'sources': {'fills': fills}}]}
    (tmp_path / 'verification' / 'us' / '2026-11-24.json').write_text(json.dumps(rec), encoding='utf-8')
    (tmp_path / 'verification' / 'us' / '2026-11-25.json').write_text(json.dumps({'gates': []}), encoding='utf-8')
    mism = [{'group': 'indices', 'asset': 'S&P 500', 'date': '2026-11-24', 'stored': 7200.0, 'fresh': 7210.5}]
    unreadable = CC.find_posts(str(tmp_path), mism, '2026-11-25')
    assert mism[0]['posts'] == [{'post': 'posts/2026-11-24.html', 'ref': 'md:indices.SP500.last', 'text': '7,200.00'}]
    assert unreadable == [{'post': 'posts/2026-11-20.html', 'why': '레포에 검증 기록이 없다'},
                          {'post': 'posts/2026-11-25.html', 'why': '기록에 fills 없음'}]
    row, lines = CC.report('2026-11-25', mism, 3, {}, unreadable)
    assert lines[0].startswith('::warning::이력 종가 불일치 S&P 500 2026-11-24: 저장 7200.0000 · 다시 받은 값 7210.5000')
    assert 'posts/2026-11-24.html 「7,200.00」' in lines[0] and '조회 불가' in lines[1]


def test_no_post_used_the_value():
    mism = [{'group': 'indices', 'asset': 'S&P 500', 'date': '2026-11-24', 'stored': 1.0, 'fresh': 2.0, 'posts': []}]
    _, lines = CC.report('2026-11-25', mism, 1, {}, [])
    assert '그 값을 쓴 글 없음(최근 14일 기록 기준)' in lines[0]


def test_collector_step_never_raises(tmp_path, capsys):
    import collect_market_data as cmd
    h = tmp_path / 'history'
    h.mkdir()
    (h / 'market.jsonl').write_text(json.dumps(ROW) + '\n', encoding='utf-8')
    bars = {'^GSPC': (['2026-11-24'], [7210.5], set())}
    cmd.close_check_step(str(h), {'report_date': '2026-11-25'}, bars, repo=str(tmp_path))
    out = capsys.readouterr().out
    assert '불일치 1' in out and '::warning::이력 종가 불일치 S&P 500' in out
    row = json.loads((h / 'close_check.jsonl').read_text(encoding='utf-8').strip())
    assert row['report_date'] == '2026-11-25' and row['compared_row'] == '2026-11-24'
    cmd.close_check_step(str(h), {'report_date': '2026-11-25'}, None, repo=str(tmp_path))     # 봉 없음 — 죽지 않는다
