"""일본 일간 — 절 순서·표·조립 (설계 §3·§13)."""
import copy

from japan import daily_render as R

S, P = '2026-10-26', '2026-10-23'
SNAP = {
    'session': S, 'prev_session': P, 'cut': '16:30', 'complete': True, 'fetch_status': {},
    'indices': {'nikkei': {'value': 62189.65, 'chg_pct': -0.8, 'ok': True,
                           'denom': {'date': P, 'value': 62693.16}},
                'topix_etf': {'value': 418.4, 'chg_pct': 0.5, 'ok': True, 'label': 'TOPIX ETF(1306)'}},
    'sectors': [{'code': '1631', 'name_ko': '은행', 'value': 37300.0, 'chg_pct': 0.4, 'ok': True},
                {'code': '1625', 'name_ko': '전기·정밀', 'value': None, 'chg_pct': None, 'ok': False,
                 'why': '세션 봉 없음'}],
    'movers': {'report_date': S, 'groups': []},
    'jgb': {'2Y': {'value': 1.872, 'period': P, 'prev_period': '2026-10-22', 'chg_bp': 1.2, 'unit': '%'},
            '10Y': {'value': 2.837, 'period': P, 'prev_period': '2026-10-22', 'chg_bp': -7.7, 'unit': '%'},
            '5Y': None, '30Y': None},
    'call_rate': {'value': 1.227, 'period': '2026-10-22', 'unit': '%'},
    'fx': {'usdjpy': {'value': 157.074, 'chg_pct': 0.05, 'label': 'USD/JPY', 'bar_end': f'{S}T16:30:00+09:00'},
           'krw_per_100jpy': {'value': 839.6, 'chg_pct': -0.34, 'label': '100엔당 원',
                              'bar_end': f'{S}T16:30:00+09:00'}},
    'macro': [], 'calendar': {'version': 'abc', 'today': [], 'event_day': [],
                              'upcoming': [{'date': '2026-10-30', 'time_jst': None, 'name_ko': 'BOJ 금융정책 결정문'}]},
}


def body(order=R.SECTIONS):
    parts = ['<section class="card headline-card"><h1>제목</h1><p>요약</p></section>']
    for s in order:
        tables = ''.join(f'<!--T:{t}-->' for t in R.PLACEHOLDERS.get(s, ()))
        parts.append(f'<section class="card" data-section="{s}"><h2>{R.TITLES[s]}</h2><p>본문.</p>{tables}</section>')
    return '\n'.join(parts)


def test_order_normal_day():
    assert R.order([]) == R.SECTIONS
    assert R.SECTIONS[0] == 'comment' and R.SECTIONS.index('macro') > R.SECTIONS.index('yen')


def test_order_event_day_macro_second():
    got = R.order([{'name_ko': 'BOJ 금융정책 결정문'}])
    assert got[:2] == ('comment', 'macro') and sorted(got) == sorted(R.SECTIONS)


def test_validate_body_checks_order():
    assert R.validate_body(body(), R.SECTIONS) == []
    errs = R.validate_body(body(), R.order([{'x': 1}]))
    assert any('순서' in e for e in errs)


def test_validate_body_placeholder_outside_section():
    b = body().replace('<!--T:jgb-->', '') + '<!--T:jgb-->'
    assert any('jgb' in e for e in R.validate_body(b, R.SECTIONS))


def test_jgb_table_shows_period_label():
    t = R.render_tables(SNAP)['jgb']
    assert '10월 23일' in t and '2.837' in t and '-7.7' in t
    assert '1.227' in t and '10월 22일' in t


def test_fx_table_shows_cut_and_weekly_note():
    t = R.render_tables(SNAP)['fx']
    assert '16:30' in t and '157.07' in t and '839.6' in t and '뉴욕 16:00' in t


def test_missing_noncore_block_omitted_with_note():
    t = R.render_tables(SNAP)['sectors']
    assert '은행' in t and '전기·정밀' not in t and '1개 업종' in t


def test_macro_table_without_items():
    assert '발표된' in R.render_tables(SNAP)['macro']


def test_macro_pending_row():
    snap = copy.deepcopy(SNAP)
    snap['macro'] = [{'name_ko': '기업 서비스가격지수(전체)', 'status': 'pending', 'value': None,
                      'period': None, 'yoy': None, 'prev_value': None, 'prev_period': None}]
    t = R.render_tables(snap)['macro']
    assert '미반영' in t


def test_credit_footer_verbatim():
    html = R.assemble(body(), {'title': '일본 증시 마감', 'summary': '요약'}, SNAP)
    assert R.BOJ_CREDIT in html
    assert 'This service uses the API provided by the "Bank of Japan Time-Series Data Search."' in html
    assert 'data-register="da"' in html
    assert 'https://fdo2a.github.io/japan/daily/2026-10-26.html' in html
    assert '<!--T:' not in html


def _root(tmp_path, snap=SNAP):
    import json
    d = tmp_path / 'japan' / 'data' / 'daily' / 'candidate'
    d.mkdir(parents=True)
    (d / f'{S}.json').write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
    n = tmp_path / 'japan' / 'data' / 'news' / 'daily'
    n.mkdir(parents=True)
    (n / f'{S}.json').write_text(json.dumps({'report_date': S, 'items': []}), encoding='utf-8')
    return tmp_path


def test_build_diag_prints_order(tmp_path, capsys):
    import build_japan_daily as B
    root = _root(tmp_path)
    assert B.main(['diag', '--session', S, '--root', str(root)]) == 0
    out = capsys.readouterr().out
    assert 'comment → today → equity' in out and 'complete=True' in out


def test_build_diag_refuses_incomplete(tmp_path, capsys):
    import build_japan_daily as B
    snap = copy.deepcopy(SNAP)
    snap['complete'] = False
    assert B.main(['diag', '--session', S, '--root', str(_root(tmp_path, snap))]) == 1


def test_build_assemble(tmp_path):
    import json
    import build_japan_daily as B
    root = _root(tmp_path)
    (root / 'b.html').write_text(body(), encoding='utf-8')
    (root / 'm.json').write_text(json.dumps({'title': 't', 'summary': 's'}), encoding='utf-8')
    out = root / 'o.html'
    assert B.main(['assemble', '--session', S, '--root', str(root), '--body', str(root / 'b.html'),
                   '--meta', str(root / 'm.json'), '--out', str(out)]) == 0
    assert R.BOJ_CREDIT in out.read_text(encoding='utf-8')
    bad = body(R.order([{'x': 1}]))
    (root / 'b.html').write_text(bad, encoding='utf-8')
    assert B.main(['assemble', '--session', S, '--root', str(root), '--body', str(root / 'b.html'),
                   '--meta', str(root / 'm.json'), '--out', str(out)]) == 1


def test_jgb_caption_and_footer_follow_source():
    old = R.render_tables(SNAP)['jgb']
    assert R.JGB_CAPTION['mof'] in old          # 출처 없는 옛 스냅샷은 문구가 그대로다
    nav = copy.deepcopy(SNAP)
    for t in ('2Y', '10Y'):
        nav['jgb'][t].update(period=S, source='naver')
    assert R.JGB_CAPTION['naver'] in R.render_tables(nav)['jgb']
    page = R.assemble(body(), {'title': 't', 'summary': 's'}, nav)
    assert 'JGB 는 네이버증권' in page and 'JGB 는 재무성' not in page
    mixed = copy.deepcopy(nav)
    mixed['jgb']['2Y']['source'] = 'mof'
    assert R.jgb_source(mixed) == 'mof'
