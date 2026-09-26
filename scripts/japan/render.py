"""일본 주간 — 표와 조립. 작성자는 절 산문만 쓰고, 표는 여기서 만든다(숫자를 손으로 옮기지 않는다).

본문 계약: `<section class="card headline-card">`(h1 하나) 뒤에 `data-section` 절 여덟 개를
SECTIONS 순서로, 표 자리에 `<!--T:이름-->`.
"""
import re

from scripts.common import post_shell as S
from scripts.common import signcolor
from scripts.common.datelabel import range_ko
from us.weekly_insight import _c, _cv, _e, _signed, _table

SECTIONS = ('core', 'boj', 'curve', 'yen', 'flows', 'equity', 'scenario', 'next')
PLACEHOLDERS = {'core': ('core',), 'curve': ('curve',), 'yen': ('yen',), 'flows': ('flows',),
                'equity': ('equity',), 'scenario': ('signals',), 'next': ('next',)}
BRAND = 'Japan Market Weekly'

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S)


def _num(v, digits=3, unit=''):
    return '—' if v is None else f'{v:.{digits}f}{unit}'


def _int(v, signed=True):
    if v is None:
        return '—'
    return f'{v:+,}' if signed else f'{v:,}'


def _t_core(d):
    c, rows = d['core'], []
    for k in ('jgb10y', 'ust10y', 'jgb2y', 'usjp2y'):
        r = c.get(k)
        if r:
            rows.append([_e(r['label']), _num(r['value'], 3, '%p' if k == 'usjp2y' else '%'),
                         _c(r['chg_1w_bp'], 'bp', 1, invert=True), _c(r['chg_4w_bp'], 'bp', 1, invert=True),
                         '—' if r.get('pctile_1y') is None else str(r['pctile_1y']),
                         _e(f"미 {r['asof_us']} · 일 {r['asof_jp']}" if r.get('asof_us') else r['asof'])])
    u = c.get('usdjpy')
    if u:
        rows.append(['엔·달러', _num(u['value'], 2), _c(u['pct_1w'], '%'), _c(u['pct_4w'], '%'),
                     '—', _e(u['asof'])])
    f = d.get('flows')
    if f:
        rows.append(['거주자 해외 중장기채(억 엔)', _cv(f['res_foreign_ltdebt_net'], _int(f['res_foreign_ltdebt_net'])), '—',
                     f"4주 합계 {_cv(f['res_foreign_ltdebt_4w'], _int(f['res_foreign_ltdebt_4w']))}", '—', f"{_e(f['week_end'])} 주"])
    p = d.get('positioning')
    if p:
        rows.append(['엔 선물 레버리지 펀드(계약)', _cv(p['lev_net'], _int(p['lev_net'])), _c(p.get('lev_net_chg'), '', 0),
                     _c(p.get('lev_net_chg_4w'), '', 0), str(p['pct_3y']), _e(p['date'])])
    return _table(['지표', '수준', '1주', '4주', '1년 백분위', '기준일'], rows,
                  '1주는 그 주 시작 전 마지막 값, 4주는 그보다 3주 앞선 마지막 값과 비교한다. '
                  'JGB는 도쿄, 미 국채는 뉴욕 마감이라 기준일이 다를 수 있다. 엔 선물 백분위는 3년 기준.')


def _t_curve(d):
    rows = [[_e(r['label']), _num(r['value'], 3, '%'), _c(r['chg_1w_bp'], 'bp', 1, invert=True),
             _c(r['chg_4w_bp'], 'bp', 1, invert=True)] for r in d['curve']]
    t = d.get('curve_10s30s')
    if t:
        rows.append([_e(t['label']), _num(t['value'], 3, '%p'), _c(t['chg_1w_bp'], 'bp', 1, invert=True),
                     _c(t['chg_4w_bp'], 'bp', 1, invert=True)])
    asof = d['curve'][0]['asof'] if d['curve'] else '—'
    return _table(['만기', '수준', '1주', '4주'], rows, f'재무성 JGB 수익률 곡선, {asof} 기준.')


def _t_yen(d):
    c, p = d['core'], d.get('positioning')
    rows = []
    if c.get('usdjpy') and c.get('usjp2y'):
        rows.append(['엔·달러', _c(c['usdjpy']['pct_1w'], '%'), _c(c['usdjpy']['pct_4w'], '%')])
        rows.append(['미·일 2년 금리차', _c(c['usjp2y']['chg_1w_bp'], 'bp', 1, invert=True),
                     _c(c['usjp2y']['chg_4w_bp'], 'bp', 1, invert=True)])
    t = _table(['', '1주', '4주'], rows, '금리차가 좁혀지는데 엔·달러가 오르면 금리 밖의 힘이 환율을 움직인 것이다.')
    if p:
        rows2 = [['레버리지 펀드 순포지션', _cv(p['lev_net'], _int(p['lev_net'])), _c(p.get('lev_net_chg'), '', 0),
                  _c(p.get('lev_net_chg_4w'), '', 0), str(p['pct_3y'])]]
        if p.get('nc_net') is not None:
            rows2.append(['비상업(투기) 순포지션', _cv(p['nc_net'], _int(p['nc_net'])), '—', '—', '—'])
        t += _table(['CFTC 엔 선물(계약)', '순포지션', '전주 대비', '4주 변화', '3년 백분위'], rows2,
                    f"{p['date']} 기준(화요일). 금요일에 공개돼 수요일 이후 움직임은 반영돼 있지 않다. "
                    '+ 가 엔 매수 쪽이다.')
    return t


def _t_flows(d):
    f, h = d.get('flows'), d.get('hedged')
    out = ''
    if f:
        rows = [[_e(r['week_end']), _cv(r['bonds'], _int(r['bonds'])), _cv(r['jp_equity'], _int(r['jp_equity']))]
                for r in f['recent']]
        rows.append(['4주 합계', _cv(f['res_foreign_ltdebt_4w'], _int(f['res_foreign_ltdebt_4w'])),
                     _cv(f['nonres_jp_equity_4w'], _int(f['nonres_jp_equity_4w']))])
        out += _table(['주(끝나는 날)', '거주자 해외 중장기채', '비거주자 일본 주식'], rows,
                      '재무성 대외·대내 증권투자(주간, 지정 보고기관 기준), 억 엔. + 는 순매수다 — '
                      '거주자의 해외채권 순매수는 자금 유출, 순매도가 귀환 쪽이다.')
    if h:
        rows = [['미 국채 10년', f"{h['ust_10y']:.3f}%"],
                ['헤지 비용 근사(미 3개월 − JGB 1년)', f"{h['hedge_cost']:.3f}%p"],
                ['헤지 후 미 국채 10년(근사)', f"{h['hedged_ust10']:.3f}%"],
                ['JGB 10년', f"{h['jgb_10y']:.3f}%"],
                ['헤지 후 미 국채 − JGB', _signed(h['gap_vs_jgb10'], '%p', 3)]]
        out += _table(['헤지 후 비교', ''], rows,
                      '근사다. 실제 헤지 비용은 선물환 포인트와 통화 베이시스를 포함해 이보다 수십 bp 벌어질 수 있다.')
    return out or '<p class="caption">자금흐름 자료를 받지 못했다.</p>'


def _t_equity(d):
    rows = [[_e(e['label']), _num(e['value'], 1), _c(e['pct_1w'], '%'), _c(e['pct_4w'], '%'),
             _c(e.get('rel_topix_4w'), '%p')] for e in d['equities']]
    return _table(['', '종가', '1주', '4주', 'TOPIX 대비 4주'], rows,
                  'TOPIX·은행·REIT·자동차는 상장 ETF(1306·1615·1343·1622)로 본다. 지수 자체가 아니다.')


_SIDE = {'A': '인상 지속 쪽', 'B': '인상 중단 쪽', '중립': '중립'}


def _t_signals(d):
    s = d['signals']
    rows = []
    for i in s['items']:
        v = i['value']
        val = '—' if v is None else _cv(v, f'{v:+,}' if i['unit'] == '계약' else f"{v:+.2f}{i['unit']}",
                                        invert=i['key'] in ('jgb2y_4w', 'usjp2y_4w'))
        thr = '증감 부호' if i['unit'] == '계약' else f"±{abs(i['threshold']):g}{i['unit']}"
        rows.append([_e(i['label']), val, thr, _SIDE[i['side']]])
    t = s['tally']
    return _table(['신호', '이번 값', '기준', '가리키는 쪽'], rows,
                  f"인상 지속 {t['A']}개 · 인상 중단 {t['B']}개 · 중립 {t['중립']}개. 기준은 미리 정해 둔 값이다.")


def _t_next(d):
    rows = [[_e(e['date']), _e(e.get('time_jst') or '—'), _e(e['name_ko']), _e(e.get('watch') or '')]
            for e in d['next_events']]
    if not rows:
        return '<p class="caption">앞으로 2주 안에 확인된 일본 일정이 없다.</p>'
    return _table(['날짜', '시각(JST)', '일정', '볼 것'], rows, '일본은행 공표 일정 기준.')


def render_tables(d):
    return {'core': _t_core(d), 'curve': _t_curve(d), 'yen': _t_yen(d), 'flows': _t_flows(d),
            'equity': _t_equity(d), 'signals': _t_signals(d), 'next': _t_next(d)}


def validate_body(body):
    errs = []
    low = body.lower()
    for tag in ('<!doctype', '<html', '<head', '<body'):
        if tag in low:
            errs.append(f'본문에 {tag}> 가 있다 — 문서 껍데기는 조립이 만든다')
    if len(re.findall(r'<h1\b', body)) != 1:
        errs.append('<h1> 은 머리 카드에 하나만 둔다')
    found = _SEC.findall(body)
    names = [n for n, _ in found]
    for s in SECTIONS:
        if s not in names:
            errs.append(f'data-section="{s}" 절이 없다')
    present = [n for n in names if n in SECTIONS]
    if present != [s for s in SECTIONS if s in present]:
        errs.append(f'절 순서가 다르다: {" → ".join(present)}')
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
    links, n = [], 0

    def _id(m):
        nonlocal n
        n += 1
        h = _H2.search(m.group(0))
        if h:
            links.append(f'<a href="#read-{n}">{S.plain(h.group(1))}</a>')
        return m.group(0).replace('<section', f'<section id="read-{n}"', 1)

    body = _SEC.sub(_id, body)
    # 「빠른 이동」 목차는 apply_readability.py(reading-map-v1)가 넣는다. 여기서도 만들면 두 번 나온다.
    key, start, end = d['key'], d['start_date'], d['end_date']
    url = f'https://fdo2a.github.io/japan/posts/{key}.html'
    title, summary = S.escape(meta['title'].strip()), S.escape(meta['summary'].strip())
    back = ('<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;">'
            '<a href="../index.html" style="text-decoration:none;font-size:13px;font-weight:700;'
            'color:#0064FF;">‹ 일본 시장 목록</a></div>')
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{title}</title>\n<meta name="description" content="{summary}">\n'
        f'<link rel="canonical" href="{url}">\n<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{BRAND} — {range_ko(start, end)}">\n'
        f'<meta property="og:url" content="{url}">\n<meta property="og:description" content="{summary}">\n'
        f'{S.ADSENSE}\n<style>\n{S.css("us")}{signcolor.CSS}\n</style>\n{S.ANALYTICS}\n</head>\n'
        '<body data-layout="prose" data-register="da">\n'
        f'<div class="topbar"><span class="brand">{BRAND}</span>'
        f'<span class="date">일본 시장 주간 · {range_ko(start, end)}</span></div>\n{back}\n'
        f'<div class="container">\n{body}\n'
        '<footer class="disclaimer"><p>재무성(JGB 금리·대외 증권투자), CFTC, FRED, 일본은행 공표 일정과 '
        '거래소 종가로 계산했다. 헤지 후 금리는 근사다. 투자 판단의 참고 자료이며 투자 권유가 아니다.</p></footer>\n'
        '</div>\n</body>\n</html>\n')
