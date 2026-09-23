"""§9 축 표의 「직전 대비」·「추세」 칸 게이트 (2026-09-23).

표는 작성 에이전트가 손으로 쓴다. 전에는 Actual/Previous 옆에 모멘텀 판정 하나만
붙였고, 그 판정이 무엇을 비교했는지 지면 어디에도 없었다 — 내구재 +0.58% → +1.08%
가 「악화」로 찍힌 이유(앞 3개월 평균 +2.89% 대 최근 −0.78%)를 독자가 알 길이 없었다.
이제 두 비교를 따로 싣고, 두 칸 모두 **계산된 문자열 그대로**여야 한다.

* 직전 대비 — `econ_indicators.json` 의 Actual/Previous 로 여기서 직접 계산한다.
  metrics 파일이 없거나 낡아도 이 칸은 검사된다.
* 추세 — 오늘 날짜·현행 스키마의 `macro_metrics.json` 이 있을 때만 판정을 믿는다.
  아니면 「—」만 허용한다. 검사를 끄면 어제 추세가 오늘 숫자 옆에 나간다.
* 표식 없는 행(ISM·PMI 같은 연구 자료 행)은 두 칸을 비운다. 판정 극성을 아는 것은
  정본 지표뿐이고, 표식 없이 판정을 적으면 이 게이트를 우회한 판정이 된다.

Pure — 문자열과 dict 를 받아 위반 문장 목록을 돌려준다.
"""

import html as _html
import re

from . import macro_metrics as mm
from .section import strip_tags

VS_PREV_HEADER = '직전 대비'
TREND_HEADER = '추세'
DASHES = ('', '—', '-', '–')

# 첫 적용 세션. 검토 러너(`scripts/review/corrector.py`)가 옛 발행본에 오늘의 게이트를
# 다시 돌리므로, 소급하면 이 날 이전 글의 정정이 전부 막힌다. 발행본이 표식을 쓰는지로
# 가르면 표식을 통째로 빼는 쪽으로 우회된다 — 날짜로 가른다.
FIRST_SESSION = '2026-09-23'

_TABLE = re.compile(r'(?is)<table\b[^>]*>(.*?)</table>')
_TR = re.compile(r'(?is)<tr\b([^>]*)>(.*?)</tr>')
# 행 머리를 `<th scope=row>` 로 쓰면 그것도 한 칸이다 — td 만 세면 열이 밀린다.
_TD = re.compile(r'(?is)<t([hd])\b([^>]*)>(.*?)</t\1>')
_MARK = re.compile(r'''\bdata-indicator\s*=\s*("|')(.*?)\1''')
_VS_ATTR = re.compile(r'\bdata-vs-prev\b')
_TREND_ATTR = re.compile(r'\bdata-trend\b(?!-)')
_NOTE = re.compile(r'(?is)<(\w+)\b[^>]*\bdata-trend-note\b[^>]*>(.*?)</\1\s*>')
_NUM = re.compile(r'([+-]?\d[\d,]*(?:\.(\d+))?)\s*(K|M|B|천|만|억)?')
_SUFFIX = {'K': 1e3, '천': 1e3, 'M': 1e6, 'B': 1e9, '만': 1e4, '억': 1e8}
_LEAD_LABEL = re.compile(r'^\([^)]*\)\s*')
# 접미사 없는 맨 숫자만 배율을 추정한다(「196,000」·「7,271」).
_BARE_SCALES = (1.0, 1e3)


def norm(html):
    text = _html.unescape(strip_tags(html or ''))
    text = text.replace('\xa0', ' ').replace('−', '-').replace('－', '-')
    return re.sub(r'\s+', ' ', text).strip()


def _printed(cell):
    """(값, 반올림 폭, 배율) — 칸 맨 앞 수치. 앞에 붙은 「(7월)」류 괄호는 건너뛴다."""
    m = _NUM.search(_LEAD_LABEL.sub('', norm(cell)))
    if not m:
        return None
    decimals = len(m.group(2) or '')
    return (float(m.group(1).replace(',', '')), 0.5 * 10 ** -decimals,
            _SUFFIX.get(m.group(3)))


def _matches(cell, canon, units):
    if canon is None:
        return norm(cell) in DASHES
    got = _printed(cell)
    if got is None:
        return False
    value, half, scale = got
    base = float(canon) * (1e3 if units == 'K' else 1.0)     # 정본을 기본 단위로
    if scale is not None:
        return abs(value * scale - base) <= half * scale + 1e-9
    return any(abs(value * s - base) <= half * s + 1e-9 for s in _BARE_SCALES) \
        or abs(value - float(canon)) <= half + 1e-9


def _trusted(metrics, report_date):
    return bool(metrics) and metrics.get('report_date') == report_date \
        and (metrics.get('schema') or 0) >= mm.SCHEMA


def _expected(econ, metrics, report_date):
    trend = {}
    if _trusted(metrics, report_date):
        trend = {r['name']: r.get('trend_cell_ko') for r in metrics.get('indicators') or []}
    out = {}
    for item in econ:
        name = item['name']
        out[name] = {
            'item': item,
            'vs': mm.vs_prev(name, item.get('axis'), item.get('actual'),
                             item.get('previous')) or '—',
            'trend': trend.get(name) or '—',
        }
    return out


def _head(table):
    """머리행 = 칸이 전부 `<th>` 인 첫 행. 행 머리 `<th scope=row>` 는 섞이지 않는다."""
    for _, body in _TR.findall(table):
        cells = _TD.findall(body)
        if cells and all(kind == 'h' for kind, _, _ in cells):
            return [b for _, _, b in cells]
    return []


def _key(text):
    return re.sub(r'\s+', '', norm(re.sub(r'(?is)<su[pb]\b[^>]*>.*?</su[pb]\s*>', '', text)))


def _header_index(head, label):
    for i, h in enumerate(head):
        if _key(h) == _key(label):
            return i
    return None


def check_tables(section, econ, metrics, report_date):
    if not econ or not report_date or report_date < FIRST_SESSION:
        return []
    want = _expected(econ, metrics, report_date)
    stale = not _trusted(metrics, report_date)
    v, seen = [], {}

    for table in _TABLE.findall(section or ''):
        head = _head(table)
        i_vs, i_tr = _header_index(head, VS_PREV_HEADER), _header_index(head, TREND_HEADER)
        i_act, i_prev = _header_index(head, 'Actual'), _header_index(head, 'Previous')
        if i_act is not None and (i_vs is None or i_tr is None):
            v.append('§9 표: Actual 열이 있는 지표 표에 「직전 대비」·「추세」 열이 없다 — '
                     '옛 형식 표로 판정을 싣지 않는다')
        for attrs, body in _TR.findall(table):
            cells = [(a, b) for kind, a, b in _TD.findall(body)]
            if not cells or all(kind == 'h' for kind, _, _ in _TD.findall(body)):
                continue
            mark = _MARK.search(attrs)
            if not mark:
                if i_vs is None and i_tr is None:
                    continue
                for i in (i_vs, i_tr):
                    if i is not None and i < len(cells) and norm(cells[i][1]) not in DASHES:
                        v.append(f'§9 표: 표식 없는 행({norm(cells[0][1])})의 「{norm(head[i])}」'
                                 f' 칸은 비워야 한다 — 판정은 data-indicator 행에만 쓴다')
                if any(_VS_ATTR.search(a) or _TREND_ATTR.search(a) for a, _ in cells):
                    v.append(f'§9 표: 표식 없는 행({norm(cells[0][1])})에 data-vs-prev/'
                             f'data-trend 칸이 있다')
                continue

            name = mark.group(2)
            if name not in want:
                v.append(f'§9 표: data-indicator="{name}" 는 econ_indicators.json 에 없는 지표다')
                continue
            seen[name] = seen.get(name, 0) + 1
            exp = want[name]
            _check_row(name, cells, head, i_vs, i_tr, i_act, i_prev, exp, stale, v)

    for name in want:
        n = seen.get(name, 0)
        if n == 0:
            v.append(f'§9 표: {name} 행(data-indicator)이 없다 — 정본 지표는 모두 싣는다')
        elif n > 1:
            v.append(f'§9 표: {name} 행이 {n}번 — 두 번 이상 실을 수 없다')

    if seen:
        notes = [norm(m.group(2)) for m in _NOTE.finditer(section or '')]
        if norm(mm.TREND_NOTE_KO) not in notes:
            v.append('§9 표: data-trend-note 캡션이 없거나 문구가 다르다 — '
                     'macro_metrics.TREND_NOTE_KO 를 그대로 싣는다')
    return v


def _same(cell, want):
    got = norm(cell)
    if want == '—':
        return got in DASHES
    return got == norm(want)


def _check_row(name, cells, head, i_vs, i_tr, i_act, i_prev, exp, stale, v):
    vs_at = [i for i, (a, _) in enumerate(cells) if _VS_ATTR.search(a)]
    tr_at = [i for i, (a, _) in enumerate(cells) if _TREND_ATTR.search(a)]
    for label, at, idx in (('직전 대비', vs_at, i_vs), ('추세', tr_at, i_tr)):
        if len(at) != 1:
            v.append(f'§9 표: {name} 행의 「{label}」 칸 표식이 {len(at)}개 — 정확히 하나')
        elif idx is None or at[0] != idx:
            v.append(f'§9 표: {name} 행의 「{label}」 칸이 같은 이름의 열 아래에 있지 않다')
    if len(vs_at) == 1 and not _same(cells[vs_at[0]][1], exp['vs']):
        v.append(f'§9 표: {name} 직전 대비 「{norm(cells[vs_at[0]][1])}」 — '
                 f'계산값은 「{exp["vs"]}」')
    if len(tr_at) == 1 and not _same(cells[tr_at[0]][1], exp['trend']):
        why = (' (macro_metrics.json 이 오늘 것이 아니거나 구 스키마라 「—」만 허용)'
               if stale else '')
        v.append(f'§9 표: {name} 추세 「{norm(cells[tr_at[0]][1])}」 — '
                 f'계산값은 「{exp["trend"]}」{why}')
    item = exp['item']
    for label, idx, canon in (('Actual', i_act, item.get('actual')),
                              ('Previous', i_prev, item.get('previous'))):
        if idx is None or idx >= len(cells):
            v.append(f'§9 표: {name} 행에서 「{label}」 열을 찾지 못했다')
        elif not _matches(cells[idx][1], canon, item.get('units')):
            v.append(f'§9 표: {name} {label} 「{norm(cells[idx][1])}」 가 정본 값 {canon} 과 다르다')
