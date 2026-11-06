import datetime as dt
import json
import os
import re

import pytest

from us import liquidity as L

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'liquidity')
HOL = {'us': {'dates': ['2026-11-26', '2026-12-25', '2027-01-01']}}


def fx(name):
    with open(os.path.join(FX, name), encoding='utf-8') as fh:
        return fh.read()


def et(y, m, d, hh=17, mm=30):
    return dt.datetime(y, m, d, hh, mm, tzinfo=L.ET)


# ── H.4.1 파싱 ────────────────────────────────────────────────────────────

def test_h41_20261105_full_regression():
    r = L.parse_h41(fx('h41_20261105.html'))
    assert (r['release_date'], r['week_ended'], r['wednesday']) == ('2026-11-05', '2026-11-04', '2026-11-04')
    rows = r['rows']
    assert rows['reserves'] == {'avg': 2930088, 'chg_wk': 36318, 'chg_yr': 67519, 'wed': 2962804}
    assert rows['tga'] == {'avg': 957175, 'chg_wk': -42552, 'chg_yr': 16196, 'wed': 936248}
    assert rows['rrp_total']['wed'] == 334503
    assert rows['rrp_foreign']['wed'] == 334278
    # 흡수 쪽 RRP 의 「Others」 — 공급 쪽 RP 의 「Others」(5·-7·-26,303·0)가 아니다(2차 검토 #9)
    assert rows['rrp_others'] == {'avg': 2745, 'chg_wk': 2523, 'chg_yr': -29849, 'wed': 225}
    assert rows['treasuries']['wed'] == 4578777 and rows['mbs']['wed'] == 1883522
    assert r['url'] == 'https://www.federalreserve.gov/releases/h41/20261105/'


def test_h41_first_week_page_with_extra_table():
    r = L.parse_h41(fx('h41_20240201.html'))
    assert r['release_date'] == '2024-02-01'
    assert r['rows']['reserves']['wed'] == 3411717
    assert r['rows']['rrp_others']['wed'] == 615379


def test_h41_identity_breaks_on_tampered_cell():
    t = fx('h41_20261105.html').replace('2,962,804', '2,962,904')
    with pytest.raises(L.ParseError) as e:
        L.parse_h41(t)
    assert e.value.code == 'identity'


def test_h41_requires_unit_header():
    t = fx('h41_20261105.html').replace('Millions', 'Billions')
    with pytest.raises(L.ParseError) as e:
        L.parse_h41(t)
    assert e.value.code == 'unit'


def test_h41_requires_title_date():
    t = re.sub(r'<title>.*?</title>', '<title>x</title>', fx('h41_20261105.html'), flags=re.S)
    with pytest.raises(L.ParseError) as e:
        L.parse_h41(t)
    assert e.value.code == 'title_date'


def test_h41_rejects_footnote_digit_in_cell():
    t = fx('h41_20261105.html').replace('>2,962,804<', '>2,962,804 3<', 1)
    with pytest.raises(L.ParseError):
        L.parse_h41(t)


# ── 금액 표시 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('m,signed,out', [
    (2962804, False, '2조 9,628억 달러'), (36318, True, '+363억 달러'), (-42552, True, '-426억 달러'),
    (225, False, '2.2억 달러'), (1000000, False, '1조 달러'), (0, True, '0달러'), (618000, False, '6,180억 달러'),
])
def test_fmt_usd(m, signed, out):
    assert L.fmt_usd(m, signed) == out


def test_printed_eok_matches_fmt():
    assert L.printed_eok(2962804) == 29628.0 and L.printed_eok(-42552) == 426.0 and L.printed_eok(225) == 2.2


# ── 세션 창·기대 회차 ────────────────────────────────────────────────────────

def test_window_skips_holiday():
    s, e = L.window(dt.date(2026, 11, 27), HOL)      # 11/26 추수감사절 휴장
    assert s == et(2026, 11, 25) and e == et(2026, 11, 27)


def test_h41_due_includes_thursday_before_effective_and_holiday_shift():
    # 첫 세션 금요일 11/27, 직전 목요일 11/26 이 추수감사절 → 예정 발표일 11/27(금)(7차 설계 #2)
    eff = L.window(dt.date(2026, 11, 27), HOL)[0]     # 11/25 17:30
    due = L.h41_due([], eff, et(2026, 11, 27, 18, 0))
    weeks = [(th.isoformat(), [d.isoformat() for d in ds]) for th, ds in due]
    assert weeks[-1] == ('2026-11-26', ['2026-11-27']) and weeks[0][0] == '2026-11-19'


def test_federal_holiday_schedule_matches_archive():
    # 아카이브 실측: 휴일 주 발표일
    for th, rel in (('2024-07-04', '2024-07-05'), ('2024-11-28', '2024-11-29'), ('2025-06-19', '2025-06-20'),
                    ('2025-11-27', '2025-11-28'), ('2026-01-01', '2026-01-02'), ('2025-12-25', '2025-12-26')):
        assert L.h41_scheduled(dt.date.fromisoformat(th)).isoformat() == rel
    assert L.h41_scheduled(dt.date(2026, 11, 12)) == dt.date(2026, 11, 12)


def test_h41_not_due_before_release_time_or_when_held():
    eff = et(2026, 11, 6)
    prior = [{'release_date': '2026-11-05'}]                           # 적용 직전 주는 이력(백필)에 있다
    assert L.h41_due(prior, eff, et(2026, 11, 12, 16, 0)) == []       # 16:30 전
    assert len(L.h41_due(prior, eff, et(2026, 11, 12, 17, 30))) == 1
    held = prior + [{'release_date': '2026-11-12'}]
    assert L.h41_due(held, eff, et(2026, 11, 13)) == []
    assert L.h41_next_release(et(2026, 11, 12, 17, 30)) == '2026-11-19'
    assert L.h41_next_release(et(2026, 11, 20)) == '2026-11-27'           # 추수감사절 주


def hist_row(release, wed_val=1000000, tga=900000, rrp=200, k=0):
    rd = dt.date.fromisoformat(release)
    wed = (rd - dt.timedelta(days=1)).isoformat()
    rows = {key: {'avg': 0, 'chg_wk': 0, 'chg_yr': 0, 'wed': 0} for key in L.TABLE_ROWS}
    rows['reserves']['wed'] = wed_val
    rows['tga']['wed'] = tga
    rows['rrp_others']['wed'] = rrp
    return {'release_date': release, 'week_ended': wed, 'wednesday': wed, 'rows': rows,
            'url': L.h41_url(release)}


def weekly(start, n):
    d = dt.date.fromisoformat(start)
    return [(d + dt.timedelta(days=7 * i)).isoformat() for i in range(n)]


def test_candidates_late_round_carried_and_cap():
    hist = [hist_row(d) for d in weekly('2026-10-08', 6)]   # 10/8 … 11/12
    eff = et(2026, 10, 7)
    c, overdue = L.h41_candidates(hist, set(), dt.date(2026, 11, 13), HOL, eff)
    assert [x['release_date'] for x in c] == ['2026-10-08', '2026-10-15', '2026-10-22']
    assert all(x['late'] for x in c)
    assert '2026-10-08' in overdue
    c2, _ = L.h41_candidates(hist, {'2026-10-08', '2026-10-15', '2026-10-22', '2026-10-29', '2026-11-05'},
                             dt.date(2026, 11, 12), HOL, eff)
    assert [(x['release_date'], x['late']) for x in c2] == [('2026-11-12', False)]
    c3, _ = L.h41_candidates(hist, {'2026-10-08', '2026-10-15', '2026-10-22', '2026-10-29', '2026-11-05'},
                             dt.date(2026, 11, 13), HOL, eff)
    assert [(x['release_date'], x['late']) for x in c3] == [('2026-11-12', True)]


def test_candidates_effective_is_window_start_so_same_day_counts():
    hist = [hist_row('2026-11-12')]
    eff = L.window(dt.date(2026, 11, 12), HOL)[0]
    c, _ = L.h41_candidates(hist, set(), dt.date(2026, 11, 12), HOL, eff)
    assert [x['release_date'] for x in c] == ['2026-11-12']
    c, _ = L.h41_candidates(hist, set(), dt.date(2026, 11, 12), HOL, et(2026, 11, 12))
    assert c == []


def test_candidates_release_after_cutoff_waits():
    hist = [hist_row('2026-11-13')]                       # 금요일 발표(휴일 주 가정)
    c, _ = L.h41_candidates(hist, set(), dt.date(2026, 11, 12), HOL, et(2026, 11, 1))
    assert c == []


# ── 이례적 판정 ──────────────────────────────────────────────────────────

def test_flags_uses_only_prior_changes_and_threshold():
    ds = weekly('2025-09-04', 60)
    vals = [1000000 + (i % 2) * 20000 for i in range(59)] + [1000000 + 20000 * 0 + 200000]
    hist = [hist_row(d, wed_val=v) for d, v in zip(ds, vals)]
    f = L.flags(hist, ds[-1])
    assert f['rows']['reserves']['big'] is True
    assert f['window']['n'] == 52
    f_mid = L.flags(hist, ds[50])
    assert f_mid['rows']['reserves']['big'] is False


def test_flags_insufficient_history_is_undecided():
    ds = weekly('2026-01-01', 10)
    hist = [hist_row(d, wed_val=1000000 + i * 5000) for i, d in enumerate(ds)]
    f = L.flags(hist, ds[-1])
    assert f['rows']['reserves']['z'] is None and f['rows']['reserves']['big'] is False


def test_flags_gap_week_makes_change_null():
    ds = weekly('2026-01-01', 5)
    del ds[3]
    hist = [hist_row(d) for d in ds]
    f = L.flags(hist, ds[3])
    assert f['rows']['reserves']['wed_chg'] is None


def test_upsert_history_dedupes_and_sorts():
    a = L.parse_h41(fx('h41_20261105.html'))
    b = L.parse_h41(fx('h41_20261029.html'))
    h = L.upsert_history([], a)
    h = L.upsert_history(h, b)
    h = L.upsert_history(h, a)
    assert [r['release_date'] for r in h] == ['2026-10-29', '2026-11-05']
    ch = L.wed_changes(h)
    assert ch[0][2]['reserves'] == 2962804 - 2895236


# ── QRA ─────────────────────────────────────────────────────────────────

def test_landing_round_times_links():
    land = L.parse_landing(fx('qra_landing_2026q4.html'))
    assert land['round'] == '2026Q4'
    assert land['times']['borrowing'] == '2026-11-02T15:00:00-05:00'
    assert land['times']['refunding'] == '2026-11-04T08:30:00-05:00'
    assert land['links']['refunding'].endswith('/sb0678')
    assert land['next'] == {'borrowing': '2027-02-01', 'refunding': '2027-02-03'}


def test_borrowing_fields():
    b = L.parse_borrowing(fx('qra_borrowing_2026q4.html'), '2026Q4')
    assert (b['borrow_bn'], b['cash_bn']) == (618.0, 850.0)
    assert b['next'] == {'quarter': 'January–March 2027', 'borrow_bn': 800.0, 'cash_bn': 1000.0}
    assert b['vs_prior'] == {'diff_bn': 10.0, 'direction': 'lower', 'month': 'August', 'year': 2026}


def test_refunding_same_month_15th_regression():
    # 11/4 성명 = 11/15 차환(1차 검토 #4 — 「다음 달 15일」은 오류였다)
    r = L.parse_refunding(fx('qra_refunding_2026q4.html'), '2026Q4')
    assert (r['total_bn'], r['refund_bn'], r['new_cash_bn']) == (125.0, 97.0, 28.0)
    assert r['sizes_bn'] == {'3': 58.0, '10': 42.0, '30': 25.0}
    assert r['guidance'].startswith('Treasury anticipates maintaining nominal coupon')


def test_refunding_wrong_round_rejected():
    with pytest.raises(L.ParseError):
        L.parse_refunding(fx('qra_refunding_2026q4.html'), '2026Q3')


def test_tbac_is_view():
    t, body = L.parse_tbac(fx('qra_tbac_2026q4.html'), '2026Q4')
    assert t['view'] is True and 'Dear Mr. Secretary' in body


def test_guidance_change_at_least_dropped():
    q3 = L.parse_refunding(fx('qra_refunding_2026q3.html'), '2026Q3')['guidance']
    q4 = L.parse_refunding(fx('qra_refunding_2026q4.html'), '2026Q4')['guidance']
    assert L.guidance_change(q3, q4) == ('changed', ['at', 'least'])
    assert L.guidance_change(q4, q4) == ('same', [])
    assert L.guidance_change(None, q4) == ('unknown', [])


def test_prior_round_never_self():
    assert L.prior_round({'2026Q3': {}, '2026Q4': {}}, '2026Q4') == '2026Q3'
    assert L.prior_round({'2026Q4': {}}, '2026Q4') is None


def qround():
    b = L.parse_borrowing(fx('qra_borrowing_2026q4.html'), '2026Q4')
    r = L.parse_refunding(fx('qra_refunding_2026q4.html'), '2026Q4')
    t, _ = L.parse_tbac(fx('qra_tbac_2026q4.html'), '2026Q4')
    return {'round': '2026Q4', 'round_name': '2026 - 4th Quarter',
            'docs': {'borrowing': dict(b, ok=True), 'refunding': dict(r, ok=True), 'tbac': dict(t, ok=True)}}


def test_qra_candidates_split_days_and_tbac_not_alone():
    eff = et(2026, 10, 1)
    mon = L.qra_candidates(qround(), set(), dt.date(2026, 11, 2), HOL, eff)
    assert set(mon) == {'borrowing'}
    wed = L.qra_candidates(qround(), {'2026Q4:borrowing'}, dt.date(2026, 11, 4), HOL, eff)
    assert set(wed) == {'refunding', 'tbac'}
    only_tbac = L.qra_candidates(qround(), {'2026Q4:borrowing', '2026Q4:refunding'}, dt.date(2026, 11, 5), HOL, eff)
    assert only_tbac == {}


def test_qra_late_doc_goes_to_next_post():
    eff = et(2026, 10, 1)
    late = L.qra_candidates(qround(), set(), dt.date(2026, 11, 9), HOL, eff)
    assert set(late) == {'borrowing', 'refunding', 'tbac'} and all(d['late'] for d in late.values())


# ── 원장 ────────────────────────────────────────────────────────────────

def test_ledger_excludes_current_and_comments(tmp_path):
    posts = tmp_path / 'posts'
    posts.mkdir()
    (posts / '2026-11-06.html').write_text('<table data-h41-release="2026-11-05"></table>'
                                           '<p data-qra-doc="2026Q4:borrowing"></p>')
    (posts / '2026-11-09.html').write_text('<table data-h41-release="2026-10-29"></table>')
    (posts / '2026-11-10.html').write_text('<!-- <table data-h41-release="2026-10-22"> -->')
    (posts / 'index.html').write_text('<table data-h41-release="2026-10-15"></table>')
    h, q = L.ledger_from_posts(str(tmp_path), '2026-11-09')
    assert h == {'2026-11-05'} and q == {'2026Q4:borrowing'}
    h, _ = L.ledger_from_posts(str(tmp_path), '2026-11-12')
    assert h == {'2026-11-05', '2026-10-29'}          # 날짜 역순 발행본도 본다(5차 #1)


# ── 표 ──────────────────────────────────────────────────────────────────

def test_render_tables_markers_and_cells():
    a = L.parse_h41(fx('h41_20261105.html'))
    a['late'] = True
    a['flags'] = {'rows': {'reserves': {'wed_chg': 67568}}, 'window': None}
    book = {'h41': {'candidates': [a]}, 'qra': {'round': '2026Q4', 'round_name': '2026 - 4th Quarter',
                                                'candidates': {'borrowing': qround()['docs']['borrowing']}}}
    html = L.render_tables(book)
    assert 'data-h41-release="2026-11-05"' in html and 'data-qra-table="2026Q4"' in html
    assert '2조 9,628억 달러' in html and '+676억 달러' in html
    assert '지난 발표분 —' in html
    assert L.h41_cells(a, 'tga')[2] == '—'


def test_korean_labels():
    assert L.quarter_ko('October–December 2026') == '2026년 10-12월'
    assert L.round_ko('2026 - 4th Quarter') == '2026년 4분기'
    rows = dict(L.qra_rows({'borrowing': qround()['docs']['borrowing']}))
    assert rows['borrow'] == ['2026년 10-12월 순차입 추정', '6,180억 달러']


def test_prior_mismatch_flagged_not_called_revision():
    a = L.parse_h41(fx('h41_20261029.html'))
    b = L.parse_h41(fx('h41_20261105.html'))
    h = L.upsert_history(L.upsert_history([], a), b)
    assert L.flags(h, '2026-11-05')['prior_mismatch'] == []
    h[0]['rows']['reserves']['avg'] += 1000
    assert L.flags(h, '2026-11-05')['prior_mismatch'] == ['reserves']


def test_ledger_reads_marker_spellings_wider_than_gate(tmp_path):
    posts = tmp_path / 'posts'
    posts.mkdir()
    (posts / '2026-11-06.html').write_text("<table data-h41-release = '2026-11-05'></table>"
                                           '<p DATA-QRA-DOC="2026q4:Borrowing"></p>')
    h, q = L.ledger_from_posts(str(tmp_path), '2026-11-09')
    assert h == {'2026-11-05'} and q == {'2026Q4:borrowing'}
