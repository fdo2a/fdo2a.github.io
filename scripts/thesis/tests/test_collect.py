"""collect_thesis_data.main() — 네트워크는 바꿔 끼우고 이름표·병합·이력·뉴스룸만 본다.

실제 사례(2026-11-23 조사)를 그대로 쓴다: 11-16 20:04 KST 수동 수집 뒤 11-17 03:52 KST 의
늦은 예약분이 KR 11-13 봉만 받아 다음날 키로 옛 값을 열었다.
"""
import datetime
import json

import pytest

import collect_thesis_data as C
from thesis import history as H

KST = datetime.timezone(datetime.timedelta(hours=9))
KR = {'2026-11-13': 206000.0, '2026-11-16': 196800.0}
MU = {'2026-11-13': 778.31, '2026-11-16': 719.02}


def fake_ticker(bars):
    def collect(symbol, name, currency, session, now):
        series = KR if symbol.endswith('.KS') else MU
        days = [d for d in sorted(series) if d <= session and d in bars.get(symbol, series)]
        if not days:
            return None
        day = days[-1]
        return {'name': name, 'currency': currency, 'price': series[day], 'price_date': day,
                'observed_at': now.isoformat(), 'chg_20d_pct': 0.0,
                'pct_from_52w_high': -10.0, 'eps_fy1': 100.0, 'bvps': 50.0}
    return collect


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(C, 'apply_dart_book_value', lambda t, d: None)
    monkeypatch.setattr(C.D, 'collect', lambda *a: {'as_of': a[2], 'tickers': {}, 'missing': []})
    monkeypatch.setattr(C.SEC, 'collect', lambda *a: {'tickers': {}, 'missing': []})
    monkeypatch.setattr(C.SEC, 'merge', lambda d, s: None)
    monkeypatch.setattr(C.V, 'fair_value', lambda s, r: None)
    newsroom = []
    monkeypatch.setattr(C.NR, 'collect', lambda prev, now: newsroom.append(now) or
                        {'collected_at': now.isoformat(), 'items': [], 'missing': []})

    def go(when, bars=None, consumer=''):
        monkeypatch.setattr(C, '_now', lambda: datetime.datetime.fromisoformat(when))
        monkeypatch.setattr(C, 'collect_ticker', fake_ticker(bars or {}))
        argv = ['--out', str(tmp_path)] + (['--consumer', consumer] if consumer else [])
        assert C.main(argv) == 0
        return json.loads((tmp_path / 'watch.json').read_text())
    go.dir, go.newsroom = tmp_path, newsroom
    return go


def test_late_scheduled_run_does_not_open_a_new_row_with_an_older_price(run):
    w = run('2026-11-16T20:04:52+09:00', consumer='publisher')
    assert (w['as_of'], w['complete']) == ('2026-11-16', True)
    # 11-17 03:52 KST — Yahoo 가 KR 11-16 봉을 빠뜨렸다(실제 11-17 행의 11-13 206,000)
    w = run('2026-11-17T03:52:25+09:00', bars={'005930.KS': ['2026-11-13'],
                                                '000660.KS': ['2026-11-13']})
    assert w['as_of'] == '2026-11-16'                 # 다음날 키가 아니다
    assert w['tickers']['005930.KS']['price'] == 196800.0
    rows = H.load(run.dir / 'history.jsonl')
    assert [r['date'] for r in rows] == ['2026-11-16']
    assert rows[0]['tickers']['005930.KS']['price'] == 196800.0


def test_missing_latest_kr_bar_is_stale_and_writes_no_row(run):
    w = run('2026-11-16T16:05:00+09:00', bars={'005930.KS': ['2026-11-13'],
                                                '000660.KS': ['2026-11-13']})
    assert w['complete'] is False
    assert any('005930.KS' in r for r in w['stale'])
    assert not (run.dir / 'history.jsonl').exists()


def test_friday_scheduled_run_on_saturday_is_collected(run):
    KR['2026-11-20'], MU['2026-11-19'] = 183100.0, 690.44
    try:
        w = run('2026-11-21T02:13:29+09:00')          # 예전엔 「주말 — 건너뜀」
    finally:
        del KR['2026-11-20'], MU['2026-11-19']
    assert w['as_of'] == '2026-11-20'
    assert w['tickers']['MU']['price_date'] == '2026-11-19'


def test_only_publisher_collections_write_the_newsroom(run):
    run('2026-11-16T20:04:52+09:00', consumer='publisher')
    assert len(run.newsroom) == 1
    before = (run.dir / 'events.json').read_text()
    run('2026-11-17T03:52:25+09:00')
    assert len(run.newsroom) == 1
    assert (run.dir / 'events.json').read_text() == before


def test_calendar_gap_writes_nothing(run, monkeypatch, tmp_path):
    monkeypatch.setattr(C, '_now', lambda: datetime.datetime(2028, 1, 3, 16, 30, tzinfo=KST))
    assert C.main(['--out', str(tmp_path / 'x')]) == 1
    assert not (tmp_path / 'x').exists()
