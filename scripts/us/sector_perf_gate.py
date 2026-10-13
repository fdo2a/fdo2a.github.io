"""섹터 기간 수익률 표가 그날 섹터 등락률과 같은 회차인가 (US 발행 게이트).

2026-10-12 재수집에서 XLC·XLRE 일봉이 10-09 에 멈췄다. 루틴은 `sectors` 행만 첫
수집분으로 고치고 complete 를 손으로 켰고, 같은 회차의 `sector_performance`(와 그 HTML)는
10-09 값을 담은 채 발행됐다 — 한 글에서 커뮤니케이션서비스가 +0.97% 와 -1.51% 로 갈렸다.
수집기의 completeness() 는 손으로 고친 데이터를 다시 보지 않으므로 발행 시점에 셋을 본다.

1. 데이터 행 — 11개 업종 모두 `sectors.pct` 와 `sector_performance` 다섯 기간이 유한한 수로
   있고, 행 날짜가 report_date 와 같으며, 표시값(+.2f)으로 `pct` 와 「1D」가 같다.
2. 게시물 표 — 다섯 기간 블록이 각각 정확히 하나, 업종마다 정확히 한 행, 값이 JSON 과 같다.
   숨긴 블록도 센다: 숨긴 정상 표가 보이는 낡은 표를 대신 만족시키면 안 된다.
3. 비교는 렌더러와 같은 표시값 문자열로 한다. 마감 뒤 수집분은 105개 커밋에서 정확히
   일치했다(어긋난 것은 이 사고와 9/23 장중 수집분뿐).

행 날짜와 표 의무는 수집기가 날짜를 남기기 시작한 뒤의 발행본(STRICT_FROM)부터다.
"""
import math
import re
from html.parser import HTMLParser

STRICT_FROM = '2026-10-14'
SECTORS = ('Technology', 'Energy', 'Communication Services', 'Consumer Discretionary',
           'Utilities', 'Consumer Staples', 'Health Care', 'Industrials', 'Financials',
           'Materials', 'Real Estate')
HORIZONS = (('1D', '1일'), ('1W', '1주'), ('1M', '1개월'), ('6M', '6개월'), ('1Y', '1년'))
SHORT = {'Communication Services': 'Comm. Svcs', 'Consumer Discretionary': 'Consumer Disc.'}
_LONG = {v: k for k, v in SHORT.items()}
FIX = (' 정상 회차의 sector_performance 행 전체를 옮긴 뒤 그 JSON 으로'
       ' data/sector_performance.html 을 다시 만들어 통째로 넣을 것.')


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _fmt(x):
    return f'{x:+.2f}'


class _Blocks(HTMLParser):
    """spf-block 마다 (제목, [(업종 표기, 값 표기)]) — 숨김 여부와 무관하게 전부."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self._field, self._buf = [], None, ''

    def handle_starttag(self, tag, attrs):
        cls = (dict(attrs).get('class') or '').split()
        if 'spf-block' in cls:
            self.blocks.append({'title': '', 'rows': []})
        elif self.blocks and ({'spf-title', 'spf-name', 'spf-val'} & set(cls)):
            self._field = next(c for c in ('spf-title', 'spf-name', 'spf-val') if c in cls)
            self._buf = ''

    def handle_data(self, data):
        if self._field:
            self._buf += data

    def handle_endtag(self, tag):
        if not self._field or tag not in ('div', 'span'):
            return
        text, b = self._buf.strip(), self.blocks[-1]
        if self._field == 'spf-title':
            b['title'] = text
        elif self._field == 'spf-name':
            b['rows'].append([text, None])
        elif b['rows'] and b['rows'][-1][1] is None:
            b['rows'][-1][1] = text
        else:
            b['rows'].append([None, text])
        self._field = None


def _data(market, strict):
    v, rd = [], market.get('report_date')
    sectors = market.get('sectors') or {}
    perf = market.get('sector_performance') or {}
    for n in SECTORS:
        s, p = sectors.get(n) or {}, perf.get(n) or {}
        pct = _num(s.get('pct'))
        if pct is None:
            v.append(f'섹터 등락률 누락: {n} 의 sectors.pct 가 없다(또는 수가 아니다).')
        need = HORIZONS if strict else HORIZONS[:3]
        bad = [k for k, _ in need if _num(p.get(k)) is None]
        if bad:
            v.append(f'섹터 기간 수익률 누락: {n} 의 {"·".join(bad)} 가 없다(또는 수가 아니다).')
        for label, row in (('sectors', s), ('sector_performance', p)):
            d = row.get('date')
            if d and rd and d != rd:
                v.append(f'낡은 섹터 행: {label}/{n} 이 {d} 것인데 발행일은 {rd} 다.' + FIX)
            elif strict and not d and label == 'sector_performance':
                v.append(f'섹터 기간 수익률 {n} 행에 날짜가 없다 — 어느 회차 값인지 알 수 없다.' + FIX)
        one = _num(p.get('1D'))
        if pct is not None and one is not None and _fmt(pct) != _fmt(one):
            v.append(f'섹터 데이터 불일치: {n} 의 그날 등락률은 {_fmt(pct)}% 인데 기간 수익률의'
                     f' 1일은 {_fmt(one)}% 다 — 한쪽만 다른 회차 값이다.' + FIX)
    return v


def _table(doc, market, strict):
    parser = _Blocks()
    parser.feed(doc or '')
    blocks = parser.blocks
    if not blocks and not strict:
        return []
    v = []
    perf = market.get('sector_performance') or {}
    for key, label in HORIZONS:
        title = f'{label} 수익률'
        hits = [b for b in blocks if b['title'] == title]
        if len(hits) != 1:
            v.append(f'섹터 기간 수익률 표의 「{title}」 블록이 {len(hits)}개다(정확히 1개여야 한다).' + FIX)
            continue
        seen = {}
        for name, val in hits[0]['rows']:
            full = _LONG.get(name, name)
            if full not in SECTORS:
                v.append(f'「{title}」에 알 수 없는 업종 행이 있다: {name!r}.' + FIX)
                continue
            if full in seen:
                v.append(f'「{title}」에 {full} 행이 두 번 있다.' + FIX)
                continue
            seen[full] = val
        for n in SECTORS:
            want = _num((perf.get(n) or {}).get(key))
            got = seen.get(n)
            if want is None:
                if got is not None:
                    v.append(f'「{title}」의 {n} 값이 데이터에 없는데 표에 있다.' + FIX)
                continue
            if got is None:
                v.append(f'「{title}」에 {n} 행이 없다.' + FIX)
            elif got.replace('−', '-') != _fmt(want) + '%':
                v.append(f'섹터 기간 수익률 표 값이 다르다: 「{title}」 {n} 표 {got}, 데이터 {_fmt(want)}%.' + FIX)
    return v


_ISO = re.compile(r'\d{4}-\d{2}-\d{2}$')


def check(doc, market):
    rd = market.get('report_date')
    # 날짜를 지우면 적용일 판단이 「옛 자료」로 기운다 — 모르면 막는다(codex 구현 검토 #1).
    if not isinstance(rd, str) or not _ISO.match(rd):
        return [f'market_data.json 의 report_date 가 없거나 날짜가 아니다({rd!r}) — 섹터 표를 판정할 수 없다.']
    strict = rd >= STRICT_FROM
    # 기간 수익률이 수집되기 전(2026-07 초기 자료)에는 필드 자체가 없었다. 그 글의 정정을
    # 고칠 수 없는 근거 데이터로 막지 않는다(codex 구현 검토 #2). 적용일 뒤에는 없으면 막는다.
    if 'sector_performance' not in market and not strict:
        return []
    return _data(market, strict) + _table(doc, market, strict)
