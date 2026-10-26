"""일본 일간 가격 — 종가·분모·분할·엔 컷 (codex 설계 검토 #1·#2·#3·#14)."""
from japan import daily_prices as P

NK_CSV = ('Date of Data,Close,Open,High,Low\r\n'
          '"2026/10/23","62693.16","62667.05","62786.89","61462.61"\r\n'
          '"2026/10/26","62189.65","62449.96","62902.95","62094.34"\r\n'
          '"This material is a copyrightable work of Nikkei. It is prohibited without Nikkei\x81fs permission."\r\n')


def test_nikkei_official_reads_session_row():
    assert P.nikkei_official(NK_CSV, '2026-10-26') == 62189.65
    assert P.nikkei_official(NK_CSV.encode('cp932', 'replace'), '2026-10-23') == 62693.16


def test_nikkei_official_missing_session_is_none():
    assert P.nikkei_official(NK_CSV, '2026-10-27') is None


def test_nikkei_close_ok_within_tolerance():
    got = P.nikkei_close(62189.65, 62189.65)
    assert got['ok'] and got['value'] == 62189.65


def test_nikkei_close_mismatch_not_ok():
    got = P.nikkei_close(62189.65, 62285.61)       # 5분봉 마지막 봉 — 종가 경매가 빠졌다
    assert not got['ok'] and got['why']


def test_nikkei_close_without_official_not_ok():
    assert not P.nikkei_close(None, 62189.65)['ok']


def test_same_session_price_rejects_stale_bar():
    assert P.same_session_price(3117.0, '2026-10-26', '2026-10-26') == 3117.0
    assert P.same_session_price(3105.0, '2026-10-23', '2026-10-26') is None
    assert P.same_session_price(float('nan'), '2026-10-26', '2026-10-26') is None


def test_denominator_requires_exact_prev_session():
    hist = [['2026-10-23', 100.0], ['2026-10-27', 110.0]]
    assert P.denominator(hist, '2026-10-26') is None
    got = P.denominator(hist, '2026-10-23')
    assert got == {'date': '2026-10-23', 'value': 100.0, 'source': 'history'}


def test_change_none_without_denom():
    assert P.change(110.0, None) is None
    assert P.change(110.0, {'date': 'd', 'value': 100.0}) == 10.0


def test_verify_jump_small_move_ok():
    assert P.verify_jump(101.0, {'date': '2026-10-23', 'value': 100.0}, [], '2026-10-26')['ok']


def test_verify_jump_split_adjusts():
    got = P.verify_jump(283.3, {'date': '2026-03-31', 'value': 2800.0}, [['2026-04-01', 10.0]],
                        '2026-04-01')
    assert got['ok'] and got['adjusted_denom'] == 280.0


def test_verify_jump_real_move_kept():
    got = P.verify_jump(82.0, {'date': '2026-10-23', 'value': 100.0}, [], '2026-10-26')
    assert got['ok'] and got['adjusted_denom'] == 100.0


def test_verify_jump_unit_error():
    got = P.verify_jump(1.0, {'date': '2026-10-23', 'value': 100.0}, [], '2026-10-26')
    assert not got['ok'] and got['why']


def _bars(day, closes):
    """16:00 부터 5분봉 — (시작 ISO, 종가)."""
    out = []
    for i, c in enumerate(closes):
        m = i * 5
        out.append((f'{day}T16:{m:02d}:00+09:00', c))
    return out


def test_fx_cut_picks_1630_bar():
    bars = _bars('2026-10-26', [157.0, 157.1, 157.2, 157.3, 157.4, 157.5, 157.6, 157.7])
    got = P.fx_cut(bars, '2026-10-26')
    assert got['value'] == 157.5                         # 16:25 시작 → 16:30 끝
    assert got['bar_start'].startswith('2026-10-26T16:25') and got['bar_end'].startswith('2026-10-26T16:30')
    assert got['tz'] == 'Asia/Tokyo' and got['basis'] == 'bar_end_1630_jst'


def test_fx_cut_accepts_utc_timestamps():
    bars = [('2026-10-26T07:25:00+00:00', 157.55)]
    assert P.fx_cut(bars, '2026-10-26')['value'] == 157.55


def test_fx_cut_missing_bar_none():
    assert P.fx_cut(_bars('2026-10-26', [157.0, 157.1]), '2026-10-26') is None
    assert P.fx_cut(_bars('2026-10-23', [157.0] * 8), '2026-10-26') is None


def test_same_session_price_rounds_float_noise():
    assert P.same_session_price(418.3999938964844, '2026-10-26', '2026-10-26') == 418.4
