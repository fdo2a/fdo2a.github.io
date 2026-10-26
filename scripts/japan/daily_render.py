"""일본 일간 — 절 순서·표·조립 (2026-10-27).

작성자는 절 산문만 쓰고 표는 여기서 만든다. 본문 계약: 머리 카드(h1 하나) 뒤에 `data-section` 절을
`order(event_day)` 순서로, 표 자리에 `<!--T:이름-->`. 순서는 코드가 정한다 — 그날 major 결과 공표가
있으면 매크로 절이 전략 코멘트 바로 다음으로 온다(사용자 결정: A 배치 + C 규칙).
값마다 기준일이 다르다 — JGB 는 직전 세션, 콜은 BOJ 최신 관측일, 엔은 16:30 JST 컷. 표가 그 날짜를 단다.
"""
import re
from datetime import date

from scripts.common import post_shell as S
from scripts.common import signcolor
from us.weekly_insight import _c, _e, _table

SECTIONS = ('comment', 'today', 'equity', 'bonds', 'yen', 'macro', 'news', 'next')
TITLES = {'comment': '전략 코멘트', 'today': '오늘의 장', 'equity': '주식', 'bonds': '채권',
          'yen': '엔화', 'macro': '매크로', 'news': '일본 경제 뉴스', 'next': '향후 확인 일정'}
PLACEHOLDERS = {'equity': ('indices', 'sectors'), 'bonds': ('jgb',), 'yen': ('fx',),
                'macro': ('macro',), 'next': ('next',)}
BRAND = 'Japan Market Daily'
BOJ_CREDIT = ('This service uses the API provided by the "Bank of Japan Time-Series Data Search." '
              'The Bank of Japan does not guarantee the content of the service.')
WEEKLY_FX_NOTE = '주간 보고서의 달러/엔은 뉴욕 16:00 기준이라 값이 다르다.'

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S)


def order(event_days):
    if not event_days:
        return SECTIONS
    rest = tuple(s for s in SECTIONS if s not in ('comment', 'macro'))
    return ('comment', 'macro') + rest


def day_ko(iso):
    """'2026-10-23' → '10월 23일'. 월간 기간('2026-09')은 '9월'."""
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', iso or ''):
        d = date.fromisoformat(iso)
        return f'{d.month}월 {d.day}일'
    if re.fullmatch(r'\d{4}-\d{2}', iso or ''):
        return f'{int(iso[5:])}월'
    return iso or '—'


def _num(v, digits=2, unit=''):
    return '—' if v is None else f'{v:,.{digits}f}{unit}'


def _t_indices(d):
    nk, tp = d['indices']['nikkei'], d['indices']['topix_etf']
    rows = [['닛케이 225', _num(nk.get('value')), _c(nk.get('chg_pct'), '%')],
            [_e(tp.get('label') or 'TOPIX ETF(1306)'), _num(tp.get('value'), 1), _c(tp.get('chg_pct'), '%')]]
    return _table(['', f'{day_ko(d["session"])} 종가', f'{day_ko(d["prev_session"])} 대비'], rows,
                  '닛케이 225 는 일본경제신문사 공표 종가. TOPIX 는 상장 ETF(1306)로 본다 — 지수 자체가 아니다.')


def _t_sectors(d):
    ok = [s for s in d.get('sectors') or [] if s.get('ok') and s.get('value') is not None]
    ok.sort(key=lambda s: -(s.get('chg_pct') if s.get('chg_pct') is not None else -999))
    rows = [[_e(s['name_ko']), _c(s.get('chg_pct'), '%')] for s in ok]
    missing = len(d.get('sectors') or []) - len(ok)
    cap = 'TOPIX 17개 업종 ETF(1617~1633) 종가 기준.'
    if missing:
        cap += f' 세션 종가를 확인하지 못한 {missing}개 업종은 뺐다.'
    if not rows:
        return f'<p class="caption">{cap}</p>'
    return _table(['업종', f'{day_ko(d["prev_session"])} 대비'], rows, cap)


def _t_jgb(d):
    rows = []
    for t in ('2Y', '5Y', '10Y', '30Y'):
        r = (d.get('jgb') or {}).get(t)
        if not r:
            continue
        rows.append([f'JGB {t[:-1]}년', _num(r['value'], 3, '%'),
                     _c(r.get('chg_bp'), 'bp', 1, invert=True), _e(day_ko(r['period']))])
    call = d.get('call_rate')
    if call:
        rows.append(['무담보 콜 O/N', _num(call['value'], 3, '%'), '—', _e(day_ko(call['period']))])
    if not rows:
        return '<p class="caption">JGB·콜금리 기준 값을 확인하지 못했다.</p>'
    return _table(['', '금리', '변화', '기준일'], rows,
                  'JGB 는 재무성 커브(다음 영업일 게시), 콜은 일본은행 시계열 — 오늘 값이 아니다. 금리 상승은 빨강.')


def _t_fx(d):
    fx = d.get('fx') or {}
    rows = []
    for key in ('usdjpy', 'eurjpy', 'krw_per_100jpy'):
        r = fx.get(key)
        if r:
            rows.append([_e(r['label']), _num(r['value'], 2), _c(r.get('chg_pct'), '%')])
    if not rows:
        return '<p class="caption">16:30 JST 환율을 확인하지 못했다.</p>'
    return _table(['', f'{day_ko(d["session"])} 16:30 JST', f'{day_ko(d["prev_session"])} 같은 시각 대비'],
                  rows, f'5분봉 16:30 JST 종가. {WEEKLY_FX_NOTE}')


def _t_macro(d):
    rows = []
    for m in d.get('macro') or []:
        if m['status'] == 'released':
            rows.append([_e(m['name_ko']), _e(day_ko(m['period'])), _num(m['value'], 2),
                         _num(m.get('prev_value'), 2), _c(m.get('yoy'), '%', 1)])
        elif m['status'] == 'pending':
            rows.append([_e(m['name_ko']), '—', '발표 예정·시계열 미반영', '—', '—'])
        else:
            rows.append([_e(m['name_ko']), '—', '일정', '—', '—'])
    if not rows:
        return '<p class="caption">오늘 발표된 일본 지표가 없다.</p>'
    return _table(['지표', '기간', '값', '직전', '전년 대비'], rows,
                  '일본은행 시계열 기준. 시장 예상치는 싣지 않는다.')


def _t_next(d):
    rows = [[_e(day_ko(e['date'])), _e(e.get('time_jst') or '—'), _e(e['name_ko'])]
            for e in (d.get('calendar') or {}).get('upcoming') or []]
    if not rows:
        return '<p class="caption">앞으로 2주 안에 확인된 일본 일정이 없다.</p>'
    return _table(['날짜', '시각(JST)', '일정'], rows, '원출처 공표 일정 기준.')


def render_tables(d):
    return {'indices': _t_indices(d), 'sectors': _t_sectors(d), 'jgb': _t_jgb(d), 'fx': _t_fx(d),
            'macro': _t_macro(d), 'next': _t_next(d)}


def validate_body(body, want):
    errs = []
    low = body.lower()
    for tag in ('<!doctype', '<html', '<head', '<body'):
        if tag in low:
            errs.append(f'본문에 {tag}> 가 있다 — 문서 껍데기는 조립이 만든다')
    if len(re.findall(r'<h1\b', body)) != 1:
        errs.append('<h1> 은 머리 카드에 하나만 둔다')
    if re.search(r'<table\b', body, re.I):
        errs.append('본문에 표(<table>)가 있다 — 표는 조립이 스냅샷으로 만든다')
    found = _SEC.findall(body)
    names = [n for n, _ in found]
    for s in SECTIONS:
        if names.count(s) != 1:
            errs.append(f'data-section="{s}" 절이 {names.count(s)}번 있다 — 한 번')
    if [n for n in names if n in SECTIONS] != list(want):
        errs.append(f'절 순서가 다르다: {" → ".join(names)} (기대 {" → ".join(want)})')
    inner = dict(found)
    for sec, phs in PLACEHOLDERS.items():
        for ph in phs:
            tag = f'<!--T:{ph}-->'
            n = body.count(tag)
            if n != 1:
                errs.append(f'{tag} 가 {n}번 있다 — 한 번, {sec} 절 안에 둔다')
            elif sec in inner and tag not in inner[sec]:
                errs.append(f'{tag} 가 {sec} 절 밖에 있다')
    return errs


def assemble(body, meta, d):
    for name, frag in render_tables(d).items():
        body = body.replace(f'<!--T:{name}-->', frag)
    n = 0

    def _id(m):
        nonlocal n
        n += 1
        return m.group(0).replace('<section', f'<section id="read-{n}"', 1)

    body = _SEC.sub(_id, body)
    s = d['session']
    url = f'https://fdo2a.github.io/japan/daily/{s}.html'
    title, summary = S.escape(meta['title'].strip()), S.escape(meta['summary'].strip())
    wd = S.WEEKDAYS[date.fromisoformat(s).weekday()]
    back = S.crumbs([('일본 시장', '../index.html'), ('일간', None)])
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{title}</title>\n<meta name="description" content="{summary}">\n'
        f'<link rel="canonical" href="{url}">\n<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{BRAND} — {s}">\n'
        f'<meta property="og:url" content="{url}">\n<meta property="og:description" content="{summary}">\n'
        f'{S.ADSENSE}\n{S.FONT_LINK}\n<style>\n{S.css("us")}{signcolor.CSS}\n</style>\n{S.ANALYTICS}\n</head>\n'
        '<body data-layout="prose" data-register="da">\n'
        f'<div class="topbar"><span class="brand">{BRAND}</span>'
        f'<span class="date">일본 시장 마감 · {day_ko(s)}({wd})</span></div>\n{back}\n'
        f'<div class="container">\n{body}\n'
        '<footer class="disclaimer"><p>닛케이 225 종가는 일본경제신문사, JGB 는 재무성, 콜금리·지표는 일본은행, '
        '업종·종목·환율은 거래소 체결가(yfinance) 기준이다. 투자 판단의 참고 자료이며 투자 권유가 아니다.</p>'
        f'<p lang="en">{_e(BOJ_CREDIT)}</p></footer>\n'
        '</div>\n</body>\n</html>\n')
