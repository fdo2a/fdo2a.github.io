"""`.stance-tbl` column widths, measured in a real browser.

The 6-column proportions in post_css/us.css were written for the old multi-asset stance
table. From 2026-09-28 the writer put the class on the 8-column macro indicator tables and
the last two columns (직전 대비·추세) rendered 0px wide at 1280px — one table grew to
2,840px tall. A string test on the CSS would not have caught it; this one measures.
"""
import pytest

from scripts.common import post_shell as S

sync_playwright = pytest.importorskip('playwright.sync_api').sync_playwright

TREND = '개선(뚜렷) · 4주 평균 1,787K → 1,744K'


def _table(heads, rows):
    head = ''.join(f'<th>{h}</th>' for h in heads)
    body = ''.join(
        '<tr>' + ''.join(f'<td data-label="{h}"{" data-trend" if h == "추세" else ""}>{v}</td>'
                         for h, v in zip(heads, row)) + '</tr>'
        for row in rows)
    return (f'<div class="tbl-scroll"><table class="stance-tbl"><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


SIX = _table(['자산군', '등급', '유지', '전일대비', '논거', '다음 분기점'],
             [['주식', '중립', '33일', '—', '성장이 보합으로 올라오며 이익 쪽 힘이 커졌다.',
               'ISM 제조업 PMI 50 상회']])
EIGHT = _table(['지표', 'Actual', 'Forecast', 'Previous', '발표일', '컨센 대비', '직전 대비', '추세'],
               [['계속 실업수당 청구', '1,701,000', '—', '1,712,000', '9월 19일 주간', '', '개선',
                 TREND]])
FOUR = _table(['종목', '시장', '등락률', '기준일'],
              [['삼성전기', 'KOSPI', '+2.1%', '10월 1일']])


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _measure(browser, width, table):
    page = browser.new_page(viewport={'width': width, 'height': 900})
    page.set_content(f'<html><head><style>{S.css("us")}</style></head>'
                     f'<body><div class="doc"><div class="card">{table}</div></div></body></html>')
    out = page.evaluate("""() => {
        const t = document.querySelector('table');
        const cells = [...t.querySelectorAll('tbody tr:first-child td')];
        return {table: t.getBoundingClientRect().width,
                height: t.getBoundingClientRect().height,
                cols: [...t.querySelectorAll('thead th')].map(x => x.getBoundingClientRect().width),
                shown: cells.map(c => getComputedStyle(c).display !== 'none'),
                page: document.documentElement.scrollWidth};
    }""")
    page.close()
    return out


@pytest.mark.parametrize('table', [EIGHT, FOUR], ids=['macro-8', 'mlcc-4'])
def test_other_column_counts_get_no_zero_width_column(browser, table):
    m = _measure(browser, 1280, table)
    assert min(m['cols']) >= 40, m['cols']
    assert m['height'] < 200, m


def test_eight_column_trend_cell_is_readable(browser):
    m = _measure(browser, 1280, EIGHT)
    assert m['cols'][-1] >= 13 * 14.5 - 1, m['cols']   # td[data-trend] min-width 13em


def test_six_column_keeps_its_proportions(browser):
    m = _measure(browser, 1280, SIX)
    shares = [w / m['table'] * 100 for w in m['cols']]
    # cell padding shifts each share by up to a point
    assert all(abs(s - t) <= 1.5 for s, t in zip(shares, [8, 17, 8, 9, 31, 27])), shares


@pytest.mark.parametrize('table', [SIX, EIGHT, FOUR], ids=['six', 'macro-8', 'mlcc-4'])
def test_mobile_stacks_rows_without_page_scroll(browser, table):
    m = _measure(browser, 390, table)
    assert m['page'] == 390
    assert all(w == 0 for w in m['cols'])               # header hidden, labels take over


def test_mobile_hides_empty_cells(browser):
    m = _measure(browser, 390, EIGHT)
    assert m['shown'] == [True, True, True, True, True, False, True, True]
