"""KR 일간 마감브리프 표 숫자 대조 (2026-11-13). CLI: `scripts/check_numbers.py --market kr --date D`.

네 표 — 「지수 & 장중」, 코스피·코스닥 수급(머리 `주체 | 순매수(억원)` 두 개), 「거래대금 상위 종목」,
「환율·금리」 — 의 칸마다 그 칸이 가리키는 `kr/data/*` 값과 맞춘다(작성자가 쓴 그 판). 문장 숫자는 범위 밖이라
미검증으로 센다 — KR 글은 「전수 검증」이 되지 않는다.

US 엔진(`us.number_audit`)의 문서 파서·섹션·토크나이저·결과 형식을 그대로 쓴다. 다른 점:
  - 칸은 `tokens()` 가 아니라 **열마다 정한 문법**으로 읽는다(「+416」 같은 단위 없는 정수를 `tokens()` 는 버린다).
    허용 결측 표기(`EMPTY`)만 빈 칸이고, 숫자가 섞였는데 문법에 안 맞으면 위반이다.
  - 데이터는 `Decimal` 로 읽어 원 표기 자릿수를 보존하고, 반올림은 인쇄 자릿수로 ROUND_HALF_UP **한 번**.
  - 코어 칸(지수 종가·등락률, 수급, 거래대금, 자료 있는 금리 행)은 데이터가 있는데 비우면 위반,
    선택 칸(시가·고가·저가·전일 종가)만 비우면 경고 — `kr_intraday` 가 없으면 비어야 한다.
  - 섹션별 표 개수가 정해져 있다. 표 삭제·이름 바꾼 섹션·다른 섹션으로 옮긴 표·지도 밖 표는 위반.
  - 아시아 세션 유닛 관측 블록은 같은 날 자료로 `fund.gate.check` 가 위반 0 일 때만 위임으로 센다.

When changing this: read `docs/superpowers/specs/2026-11-13-kr-number-audit.md` first.
"""

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from common.numbers import numbers_split_by_tags
from us.number_audit import (InputError, Result, _WIDE, _children, _cells, _inside, _rows, _sections,
                             _Stream, _unverified, tokens)

EFFECTIVE = '2026-11-16'          # 첫 차단 발행일(다음 거래일). 그 전 글은 입력을 읽기 전에 건너뛴다

REQUIRED = ('kr_market_data', 'kr_flows', 'kr_top_value')
OPTIONAL = ('kr_intraday', 'kr_econ')
FUND = 'kr_fund_view'

# 자동 대조하지 못한 이유 — us.number_audit.UNVERIFIED_KINDS·review.prepub_view.UNVERIFIED_KINDS 에도 있다(시험이 강제)
KIND_PROSE = 'KR 문장'
KIND_TABLE = 'KR 표(지도 밖)'
KIND_SECTOR = 'KR 업종 멀티기간'
KIND_FUND = 'KR 펀드 블록(위임 안 됨)'
UNVERIFIED_KINDS = frozenset({KIND_PROSE, KIND_TABLE, KIND_SECTOR, KIND_FUND})

# 허용 결측 표기 — 이것만 「빈 칸」이다. 그 밖의 글자는 숫자가 없어도 수치 칸에서는 위반
EMPTY = frozenset({'', '-', '–', '—', '−', 'n/a', 'N/A'})

S_INDEX, S_FLOWS, S_TOP, S_RATES = '지수 & 장중', '수급', '거래대금 상위 종목', '환율·금리'
S_SECTOR, S_FUND = '업종·섹터 멀티기간 수익률', '아시아 세션 유닛 관측'
SECTION_OF = {'index': S_INDEX, 'flows': S_FLOWS, 'top': S_TOP, 'rates': S_RATES}
TABLE_NAME = {'index': '지수', 'flows': '수급', 'top': '거래대금', 'rates': '금리'}

INDEX_ROWS = {'코스피': 'KOSPI', '코스닥': 'KOSDAQ'}
MARKET_KO = {v: k for k, v in INDEX_ROWS.items()}
INDEX_COLS = {'종가': ('m', 'close', 'level'), '등락률': ('m', 'change_pct', 'pct'),
              '시가': ('o', 'open', 'level'), '고가': ('o', 'high', 'level'), '저가': ('o', 'low', 'level'),
              '전일 종가': ('o', 'prevClose', 'level')}
FLOW_ROWS = {'개인': 'individual', '외국인': 'foreign', '기관': 'institution'}
FLOW_HEAD = ['주체', '순매수(억원)']
TOP_COLS = ('순위', '종목/ETF', '구분', '거래대금', '비고')
RATE_HEAD = ['지표', '금리', '전일比(bp)', '기준일']

_GRAMMAR = {
    'level': re.compile(r'(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}'),
    'pct': re.compile(r'[+-]?\d+\.\d{2}%'),
    'int': re.compile(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)'),
    'rank': re.compile(r'\d+'),
    'jo': re.compile(r'\d+\.\d{2}조원'),
    'rate': re.compile(r'\d+\.\d+%'),
    'bp': re.compile(r'[+-]?\d+\.\d+'),
}
_MONTH_TAIL = '(전월比)'
_ISO = re.compile(r'\d{4}-\d{2}-\d{2}')
_MONTH = re.compile(r'\d{4}-\d{2}')
_MONTH_TEXT = re.compile(r'(?:(\d{4})-(\d{2})|(\d{4})년 (\d{1,2})월 기준)')
_MEMBERS = re.compile(r'(\d+)종 합산')
_H3 = re.compile(r'(코스피|코스닥)\s*(?:\((.*)\))?')


class KrResult(Result):
    """US 결과와 같은 칸. 요약 줄만 KR 범위를 말한다(문장 판정 없음)."""

    def summary(self):
        why = ', '.join(f'{k} {v}' for k, v in sorted(self.unverified_by.items(), key=lambda x: -x[1]))
        dele = ', '.join(f'{k} {v}' for k, v in sorted(self.delegated_by.items()))
        return (f'number audit: KR 표 4종 — 표 칸 {self.table_cells} 대조 · 미검증 {self.unverified}'
                f'({why or "—"}) · 위임 {self.delegated}({dele or "—"}) · '
                f'제외(접힌 계산 근거) {self.excluded} · 문장 숫자는 자동 대조 밖')


# ── 입력 ────────────────────────────────────────────────────────────────

def _read(path, decimal=True):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh, parse_float=Decimal) if decimal else json.load(fh)


def load_inputs(datadir):
    """kr/data 의 표 원천. 필수 파일이 없거나 JSON 이 깨졌으면 InputError(통과가 아니다).
    `kr_fund_view` 는 위임 증명용이라 float 로 읽는다 — 펀드 게이트가 블록을 다시 그려 바이트로 비교한다."""
    data = {}
    for k in REQUIRED:
        try:
            data[k] = _read(os.path.join(datadir, f'{k}.json'))
        except (OSError, ValueError) as e:
            raise InputError(f'{k}.json 을 읽지 못했다: {type(e).__name__}') from e
    for k in OPTIONAL:
        try:
            data[k] = _read(os.path.join(datadir, f'{k}.json'))
        except FileNotFoundError:
            data[k] = None
        except (OSError, ValueError) as e:
            raise InputError(f'{k}.json 을 읽지 못했다: {type(e).__name__}') from e
    try:
        data[FUND] = _read(os.path.join(datadir, f'{FUND}.json'), decimal=False)
    except (OSError, ValueError):
        data[FUND] = None            # 위임이 서지 않을 뿐 — 펀드 섹션 자체는 check_fund 가 막는다
    return data


def _dec(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, Decimal):
        return x
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    return None


def _ndec(d):
    e = d.as_tuple().exponent
    return -e if isinstance(e, int) and e < 0 else 0


def _q(d, places):
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _show(d, signed=False):
    if d is None:
        return '없음'
    if isinstance(d, Decimal):
        s = format(d, 'f')
        return '+' + s if signed and d > 0 else s
    return str(d)


# ── 칸 ──────────────────────────────────────────────────────────────────

def _norm(text):
    return re.sub(r'\s+', ' ', (text or '').translate(_WIDE).replace('−', '-')).strip()


def _msg(table, market, row, col, printed, want, why):
    return (f'[KR {TABLE_NAME[table]}] 시장={market or "-"} 행={row} 열={col} 인쇄=「{printed}」 '
            f'기대={want} — {why}')


@dataclass
class _Cell:
    table: str
    market: str
    row: str
    col: str


def _hidden_digits(td):
    raw = re.sub(r'\D', '', ''.join(td.raw))
    vis = re.sub(r'\D', '', ''.join(td.text))
    return raw != vis


def _blank(res, c, text, want, core, shown=None):
    if want is None:
        return
    line = _msg(c.table, c.market, c.row, c.col, text, shown or _show(want), '칸을 비웠다(데이터에 값이 있다)')
    if core:
        res.violations.append(line)
    else:
        res.warnings.append('경고(표): ' + line)


def _number(res, c, td, kind, want, core, min_dec=None, month_tail=False, expect_fmt=None):
    """수치 칸 하나. want 는 비교할 Decimal(이미 인쇄 자릿수로 반올림한 값) 또는 None(데이터 없음)."""
    shown = _show(want, signed=kind in ('pct', 'int', 'bp'))
    if _hidden_digits(td):
        res.violations.append(_msg(c.table, c.market, c.row, c.col, td.plain(), shown,
                                   '칸 안에 숨긴 숫자·그림 속 숫자가 있다'))
    text = _norm(td.plain())
    if text in EMPTY:
        _blank(res, c, text, want, core, shown)
        return
    if not re.search(r'\d', text):
        res.violations.append(_msg(c.table, c.market, c.row, c.col, text, shown,
                                   '허용 결측 표기(–)도 수치도 아니다'))
        return
    res.table_cells += 1
    body = text
    if month_tail and body.endswith(_MONTH_TAIL):
        body = body[:-len(_MONTH_TAIL)].rstrip()
    if not _GRAMMAR[kind].fullmatch(body):
        res.violations.append(_msg(c.table, c.market, c.row, c.col, text, shown,
                                   f'형식이 이 열의 표기({expect_fmt or kind})가 아니다'))
        return
    if want is None:
        res.violations.append(_msg(c.table, c.market, c.row, c.col, text, '없음', '데이터에 값이 없다'))
        return
    num = re.sub(r'[,%조원]', '', body)
    try:
        got = Decimal(num)
    except InvalidOperation:
        res.violations.append(_msg(c.table, c.market, c.row, c.col, text, shown, '형식'))
        return
    if min_dec is not None and _ndec(got) < min_dec:
        res.violations.append(_msg(c.table, c.market, c.row, c.col, text, shown,
                                   f'자릿수가 데이터 표기보다 적다(소수 {min_dec}자리 이상)'))
        return
    if got != want:
        res.violations.append(_msg(c.table, c.market, c.row, c.col, text, shown, '데이터와 다르다'))


# ── 표 ──────────────────────────────────────────────────────────────────

def _head(table, kids):
    rows = _rows(table, kids)
    head = [r for r in rows if _cells(r, kids) and all(c.tag == 'th' for c in _cells(r, kids))]
    body = [r for r in rows if r not in head and _cells(r, kids)]
    return head, body


def _raw_text(n):
    return re.sub(r'\s+', ' ', ''.join(n.raw)).strip()


def _signature(table, kids):
    """표 머리로 어느 지도 표인지 — 숨긴 표도 머리 글자(raw)로 알아본다."""
    head, _ = _head(table, kids)
    if not head:
        return None
    ths = [_raw_text(c) for c in _cells(head[0], kids)]
    if not ths:
        return None
    if ths[0] == '지수' and '종가' in ths:
        return 'index'
    if ths[0] == '주체' and any('순매수' in x for x in ths):
        return 'flows'
    if ths[0] == '순위' and any('종목' in x for x in ths):
        return 'top'
    if ths[0] == '지표' and '금리' in ths:
        return 'rates'
    return None


def _structure_ok(res, kind, table, kids, market=None):
    head, body = _head(table, kids)
    name = TABLE_NAME[kind]
    if len(head) != 1:
        res.violations.append(f'[KR {name}] 시장={market or "-"} — 표 머리 행이 {len(head)}개다(정확히 1개)')
        return None
    for r in _rows(table, kids):
        for c in _cells(r, kids):
            if c.attrs.get('colspan', '1') not in ('', '1') or c.attrs.get('rowspan', '1') not in ('', '1'):
                res.violations.append(f'[KR {name}] 시장={market or "-"} — 표에 colspan·rowspan 이 있다')
                return None
    ths = [c.plain() for c in _cells(head[0], kids)]
    return ths, body


def _audit_index(res, table, kids, data, owned):
    got = _structure_ok(res, 'index', table, kids)
    if got is None:
        return
    ths, body = got
    md = data['kr_market_data']
    indices = md.get('indices') if isinstance(md.get('indices'), dict) else {}
    intr = data.get('kr_intraday') if isinstance(data.get('kr_intraday'), dict) else {}
    cols = []
    for th in ths[1:]:
        if th not in INDEX_COLS:
            res.violations.append(f'[KR 지수] — 알 수 없는 열 「{th}」')
        elif th in cols:
            res.violations.append(f'[KR 지수] — 열 「{th}」 이 두 번 있다')
        cols.append(th)
    for need in ('종가', '등락률'):
        if need not in cols:
            res.violations.append(f'[KR 지수] — 필수 열 「{need}」 이 없다')
    seen = set()
    for tr in body:
        cells = _cells(tr, kids)
        label = _norm(cells[0].plain())
        key = INDEX_ROWS.get(label)
        if key is None:
            res.violations.append(f'[KR 지수] 시장=- 행={label} — 알 수 없는 행')
            continue
        if key in seen:
            res.violations.append(f'[KR 지수] 시장=- 행={label} — 행이 두 번 있다')
            continue
        seen.add(key)
        if len(cells) - 1 != len(cols):
            res.violations.append(f'[KR 지수] 시장=- 행={label} — 칸 수({len(cells) - 1})가 열 수({len(cols)})와 다르다')
        m = indices.get(key) if isinstance(indices.get(key), dict) else {}
        o = intr.get(f'{key}_ohlc') if isinstance(intr.get(f'{key}_ohlc'), dict) else {}
        for th, td in zip(cols, cells[1:]):
            spec = INDEX_COLS.get(th)
            if spec is None:
                continue
            src, field, gram = spec
            raw = _dec((m if src == 'm' else o).get(field))
            want = None if raw is None else _q(raw, 2)
            owned.add(id(td))
            _number(res, _Cell('index', '-', label, th), td, gram, want, core=(src == 'm'),
                    expect_fmt='소수 둘째 자리' + ('%' if gram == 'pct' else ''))
    for label, key in INDEX_ROWS.items():
        m = indices.get(key) if isinstance(indices.get(key), dict) else {}
        if key not in seen and (_dec(m.get('close')) is not None or _dec(m.get('change_pct')) is not None):
            res.violations.append(f'[KR 지수] 시장=- 행={label} — 행이 없다(데이터에는 있다)')


def _meaning(label):
    s = re.sub(r'\s', '', label or '')
    if '전거래일' in s:
        return 'stale'
    if '잠정' in s:
        return 'provisional'
    if '확정' in s:
        return 'confirmed'
    return None


_MEANING_KO = {'stale': '전 거래일 기준', 'provisional': '당일 잠정', 'confirmed': '당일 확정'}


def _flows_market(table, section, doc, tables):
    """같은 블록의 h3 — 표에서 위로 올라가며 h3 가 처음 나오는 조상(블록)에 h3 도, 수급 표도 정확히 하나여야
    한다. 한 블록에 h3 둘(시장 둘)이나 수급 표 둘(한쪽 h3 를 지운 경우)이면 시장을 정할 수 없다."""
    a = table.parent
    while a is not None:
        hs = [n for n in doc.nodes if n.tag == 'h3' and _inside(n, a)]
        if hs:
            n_tables = sum(1 for t in tables if _inside(t, a))
            return hs[0] if len(hs) == 1 and n_tables == 1 else 'ambiguous'
        if a is section:
            return None
        a = a.parent
    return None


def _flows_inputs(data, date):
    md, fl = data['kr_market_data'], data['kr_flows']
    if not isinstance(fl, dict):
        raise InputError('kr_flows.json 이 객체가 아니다')
    out = {}
    for key, ko in MARKET_KO.items():
        fd = (md.get('flows_date') or {}).get(key) if isinstance(md.get('flows_date'), dict) else None
        if not isinstance(fd, str) or not _ISO.fullmatch(fd):
            raise InputError(f'kr_market_data.flows_date.{key} 가 없다 — 수급 표를 대조할 수 없다')
        prov = (md.get('flows_provisional') or {}).get(key) if isinstance(md.get('flows_provisional'), dict) else None
        f = fl.get(key) if isinstance(fl.get(key), dict) else {}
        # 두 파일이 같은 수집판인지 — 필드가 있을 때만(옛 판에는 없다)
        if 'flows_date' in f and f['flows_date'] != fd:
            raise InputError(f'kr_flows.{key}.flows_date {f["flows_date"]} 가 kr_market_data 의 {fd} 와 다르다')
        if 'flows_provisional' in f and prov is not None and bool(f['flows_provisional']) != bool(prov):
            raise InputError(f'kr_flows.{key}.flows_provisional 이 kr_market_data 와 다르다')
        rows = [r for r in (f.get('rows') or []) if isinstance(r, dict) and r.get('date') == fd]
        if len(rows) != 1:
            raise InputError(f'kr_flows.{key} 에 flows_date {fd} 행이 {len(rows)}개다(정확히 1개)')
        expect = 'stale' if fd != date else ('provisional' if prov else 'confirmed')
        out[key] = {'date': fd, 'row': rows[0], 'expect': expect, 'label': f.get('label')}
    return out


def _audit_flows(res, tables, section, doc, kids, flows, owned):
    by_market = {}
    for t in tables:
        h3 = _flows_market(t, section, doc, tables)
        if h3 is None or h3 == 'ambiguous':
            res.violations.append('[KR 수급] 시장=- — 표의 시장을 정할 수 없다(같은 블록에 h3 가 정확히 하나여야 한다)')
            continue
        text = _norm(h3.plain())
        m = _H3.fullmatch(text)
        if not m:
            res.violations.append(f'[KR 수급] 시장=- — 표의 시장을 정할 수 없다(제목 「{text}」)')
            continue
        by_market.setdefault(INDEX_ROWS[m.group(1)], []).append((t, m.group(2), text))
    for key, ko in MARKET_KO.items():
        found = by_market.get(key, [])
        if len(found) != 1:
            res.violations.append(f'[KR 수급] 시장={ko} — 표가 {len(found)}개다(시장마다 정확히 1개)')
            continue
        table, label, title = found[0]
        info = flows[key]
        got = _meaning(label)
        if got != info['expect']:
            res.violations.append(f'[KR 수급] 시장={ko} — 제목 라벨 「{label or ""}」 이 자료와 다르다'
                                  f'(자료: {_MEANING_KO[info["expect"]]}, flows_date {info["date"]})')
        else:
            dates = _ISO.findall(label or '')
            if info['expect'] == 'stale' and any(d != info['date'] for d in dates):
                res.violations.append(f'[KR 수급] 시장={ko} — 제목 라벨 「{label}」 의 날짜가 flows_date '
                                      f'{info["date"]} 와 다르다')
            elif info.get('label') and label != info['label']:
                res.warnings.append(f'경고(표): [KR 수급] 시장={ko} — 제목 라벨 「{label}」 이 자료 라벨 '
                                    f'「{info["label"]}」 과 글자가 다르다(뜻은 같다)')
        got_s = _structure_ok(res, 'flows', table, kids, ko)
        if got_s is None:
            continue
        ths, body = got_s
        if [_norm(x) for x in ths] != FLOW_HEAD:
            res.violations.append(f'[KR 수급] 시장={ko} — 표 머리가 「{" | ".join(FLOW_HEAD)}」 가 아니다')
            continue
        seen = set()
        for tr in body:
            cells = _cells(tr, kids)
            who = _norm(cells[0].plain())
            field = FLOW_ROWS.get(who)
            if field is None:
                res.violations.append(f'[KR 수급] 시장={ko} 행={who} — 알 수 없는 행')
                continue
            if field in seen:
                res.violations.append(f'[KR 수급] 시장={ko} 행={who} — 행이 두 번 있다')
                continue
            seen.add(field)
            if len(cells) != 2:
                res.violations.append(f'[KR 수급] 시장={ko} 행={who} — 칸 수가 2가 아니다')
                continue
            owned.add(id(cells[1]))
            _number(res, _Cell('flows', ko, who, FLOW_HEAD[1]), cells[1], 'int', _dec(info['row'].get(field)),
                    core=True, expect_fmt='부호·쉼표 정수')
        for who, field in FLOW_ROWS.items():
            if field not in seen and _dec(info['row'].get(field)) is not None:
                res.violations.append(f'[KR 수급] 시장={ko} 행={who} — 행이 없다(데이터에는 있다)')


def _audit_top(res, table, kids, data, owned):
    got = _structure_ok(res, 'top', table, kids)
    if got is None:
        return
    ths, body = got
    ths = [_norm(x) for x in ths]
    for th in ths:
        if th not in TOP_COLS:
            res.violations.append(f'[KR 거래대금] — 알 수 없는 열 「{th}」')
    for need in ('순위', '종목/ETF', '거래대금'):
        if ths.count(need) != 1:
            res.violations.append(f'[KR 거래대금] — 필수 열 「{need}」 이 정확히 하나가 아니다')
            return
    top = data['kr_top_value']
    if not isinstance(top, list):
        raise InputError('kr_top_value.json 이 목록이 아니다')
    idx = {th: i for i, th in enumerate(ths)}
    for i, tr in enumerate(body):
        cells = _cells(tr, kids)
        if len(cells) != len(ths):
            res.violations.append(f'[KR 거래대금] 시장=- 행={i + 1}번째 줄 — 칸 수({len(cells)})가 열 수({len(ths)})와 다르다')
            continue
        rank_td = cells[idx['순위']]
        rank = _norm(rank_td.plain())
        owned.add(id(rank_td))
        res.table_cells += 1
        if _hidden_digits(rank_td) or rank != str(i + 1):
            res.violations.append(_msg('top', '-', f'{i + 1}번째 줄', '순위', rank, i + 1,
                                       '순위는 1부터 빈틈없이 데이터 순서대로다'))
            continue
        row = f'{rank}위'
        if i >= len(top):
            res.violations.append(f'[KR 거래대금] 시장=- 행={row} — 데이터에 없는 행(데이터 {len(top)}행)')
            continue
        rec = top[i] if isinstance(top[i], dict) else {}
        name_td = cells[idx['종목/ETF']]
        owned.add(id(name_td))
        name = _norm(name_td.plain())
        if name != _norm(str(rec.get('label') or '')) or _hidden_digits(name_td):
            res.violations.append(_msg('top', '-', row, '종목/ETF', name, rec.get('label'), '종목 이름이 데이터와 다르다'))
        v = _dec(rec.get('value'))
        want = None if v is None else _q(v / Decimal(1000000), 2)
        val_td = cells[idx['거래대금']]
        owned.add(id(val_td))
        _number(res, _Cell('top', '-', row, '거래대금'), val_td, 'jo', want, core=True,
                expect_fmt='소수 둘째 자리 + 「조원」')
        if '비고' in idx:
            note_td = cells[idx['비고']]
            owned.add(id(note_td))
            note = _norm(note_td.plain())
            n = len(rec.get('members') or [])
            if _hidden_digits(note_td):
                res.violations.append(_msg('top', '-', row, '비고', note, f'{n}종', '칸 안에 숨긴 숫자가 있다'))
            elif re.search(r'\d', note):
                res.table_cells += 1
                mm = _MEMBERS.fullmatch(note)
                if not mm:
                    res.violations.append(_msg('top', '-', row, '비고', note, f'{n}종 합산',
                                               '비고의 숫자는 「N종 합산」 뿐이다'))
                elif int(mm.group(1)) != n:
                    res.violations.append(_msg('top', '-', row, '비고', note, f'{n}종 합산', '묶은 종목 수가 데이터와 다르다'))
    if len(body) < len(top):
        res.violations.append(f'[KR 거래대금] 시장=- — 표 행이 {len(body)}개다(데이터 {len(top)}행, 행이 없다)')


def _econ_series(data):
    e = data.get('kr_econ')
    if not isinstance(e, dict) or e.get('pending'):
        return {}, []
    s = e.get('series') if isinstance(e.get('series'), dict) else {}
    miss = e.get('missing') if isinstance(e.get('missing'), list) else []
    return s, miss


def _audit_rates(res, table, kids, data, owned):
    got = _structure_ok(res, 'rates', table, kids)
    if got is None:
        return
    ths, body = got
    if [_norm(x) for x in ths] != RATE_HEAD:
        res.violations.append(f'[KR 금리] — 표 머리가 「{" | ".join(RATE_HEAD)}」 가 아니다')
        return
    series, missing = _econ_series(data)
    seen = set()
    for tr in body:
        cells = _cells(tr, kids)
        label = _norm(cells[0].plain())
        if label in seen:
            res.violations.append(f'[KR 금리] 시장=- 행={label} — 행이 두 번 있다')
            continue
        seen.add(label)
        if label not in series:
            why = 'missing 항목이라 행이 없어야 한다' if label in missing else '알 수 없는 행'
            res.violations.append(f'[KR 금리] 시장=- 행={label} — {why}')
            continue
        if len(cells) != 4:
            res.violations.append(f'[KR 금리] 시장=- 행={label} — 칸 수가 4가 아니다')
            continue
        s = series[label] if isinstance(series[label], dict) else {}
        val, bp, dt = _dec(s.get('value')), _dec(s.get('bp')), s.get('date')
        monthly = isinstance(dt, str) and bool(_MONTH.fullmatch(dt))
        for td in cells[1:]:
            owned.add(id(td))
        _number(res, _Cell('rates', '-', label, '금리'), cells[1], 'rate', val, core=True,
                min_dec=None if val is None else max(2, _ndec(val)), expect_fmt='소수 둘째 자리 이상 %')
        _number(res, _Cell('rates', '-', label, '전일比(bp)'), cells[2], 'bp', bp, core=True,
                min_dec=None if bp is None else max(1, _ndec(bp)), month_tail=monthly,
                expect_fmt='소수 첫째 자리 이상' + (', 「(전월比)」 꼬리 허용' if monthly else ''))
        _date_cell(res, label, cells[3], dt, monthly)
    for label, s in series.items():
        if label not in seen and isinstance(s, dict) and _dec(s.get('value')) is not None:
            res.violations.append(f'[KR 금리] 시장=- 행={label} — 행이 없다(데이터에는 있다)')


def _date_cell(res, label, td, dt, monthly):
    text = _norm(td.plain())
    c = _Cell('rates', '-', label, '기준일')
    if _hidden_digits(td):
        res.violations.append(_msg('rates', '-', label, '기준일', text, dt, '칸 안에 숨긴 숫자가 있다'))
    if text in EMPTY:
        _blank(res, c, text, dt if isinstance(dt, str) and dt else None, core=True)
        return
    res.table_cells += 1
    if not isinstance(dt, str) or not dt:
        res.violations.append(_msg('rates', '-', label, '기준일', text, '없음', '데이터에 기준일이 없다'))
        return
    if monthly:
        m = _MONTH_TEXT.fullmatch(text)
        ok = bool(m) and (int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))) == (int(dt[:4]), int(dt[5:7]))
        if not ok:
            res.violations.append(_msg('rates', '-', label, '기준일', text, dt,
                                       '월 기준일은 「YYYY-MM」 또는 「YYYY년 M월 기준」으로 같은 달이어야 한다'))
        return
    if text != dt:
        res.violations.append(_msg('rates', '-', label, '기준일', text, dt, '기준일이 데이터와 다르다'))


# ── 위임 ────────────────────────────────────────────────────────────────

def _fund_delegated(html, doc, by_title, data, date):
    """펀드 블록 노드 — 같은 날 자료·적용일·블록 하나·검사 위반 0 이 모두일 때만(codex 설계 검토 #8)."""
    from fund.gate import EFFECTIVE as F_EFF, _owed, check as fund_check
    secs = by_title.get(S_FUND) or []
    fv = data.get(FUND)
    if len(secs) != 1 or not isinstance(fv, dict) or date < F_EFF or not _owed(fv, date):
        return None
    blocks = [n for n in doc.nodes if 'data-fund-kr' in n.attrs]
    if len(blocks) != 1 or not _inside(blocks[0], secs[0]):
        return None
    if fund_check(html, fv, 'kr', date):
        return None
    return blocks[0]


# ── 본체 ────────────────────────────────────────────────────────────────

def audit(html, data, date, effective=None):
    eff = effective or EFFECTIVE
    if not isinstance(date, str) or not _ISO.fullmatch(date):
        raise InputError(f'글 날짜가 YYYY-MM-DD 가 아니다({date!r})')
    res = KrResult()
    if date < eff:
        res.skipped = True
        return res
    md = data.get('kr_market_data')
    if not isinstance(md, dict):
        raise InputError('kr_market_data.json 이 없거나 객체가 아니다')
    if md.get('report_date') != date:
        raise InputError(f'kr_market_data report_date {md.get("report_date")} 가 글 날짜 {date} 와 다르다')
    flows = _flows_inputs(data, date)
    series, _ = _econ_series(data)

    doc = _Stream(html)
    kids = _children(doc)
    sections = _sections(doc)
    by_title = {}
    for n, title, _ in sections:
        if title:
            by_title.setdefault(title, []).append(n)

    body_at = html.find('<body')
    for s in numbers_split_by_tags(html[body_at:] if body_at >= 0 else html):
        res.violations.append(f'수치가 태그·보이지 않는 문자로 쪼개져 있다({s[:30]!r}) — 화면과 검사가 다른 숫자를 읽는다')
    hidden = [t for d in doc.hidden_text for t in tokens(d)]
    for t in hidden:
        res.violations.append(f'숨긴 요소 안에 수치 「{t.raw}」 — 독자에게 안 보이는 수치는 싣지 않는다')
    svg = [t for d in doc.svg_text for t in tokens(d)]
    for t in svg:
        res.violations.append(f'SVG 안에 수치 「{t.raw}」 — 그림 속 글자는 대조할 수 없다')

    # 섹션 — 지도 섹션은 정확히 하나씩, 그 제목이 다른 섹션의 소제목이면 경계를 정할 수 없다
    mapped_titles = set(SECTION_OF.values())
    for n, title, titles in sections:
        for t in titles[1:]:
            if t in mapped_titles:
                res.violations.append(f'「{t}」 이 다른 섹션({title}) 안 소제목으로 있다 — 섹션 경계를 정할 수 없다')
    sec_of = {}
    for kind, name in SECTION_OF.items():
        secs = by_title.get(name, [])
        if len(secs) != 1:
            res.violations.append(f'「{name}」 섹션이 {len(secs)}개다 — 정확히 1개여야 한다(제목은 「{name}」 그대로)')
        else:
            sec_of[kind] = secs[0]

    def top_section(node):
        for n, title, _ in sections:
            if _inside(node, n):
                return n, title
        return None, None

    found = {k: [] for k in SECTION_OF}
    for t in (n for n in doc.nodes if n.tag == 'table'):
        kind = _signature(t, kids)
        sec, title = top_section(t)
        hid = any(a.self_hidden for a in t.ancestors())
        home = next((k for k, s in sec_of.items() if s is sec), None)
        if hid:
            if kind:
                res.violations.append(f'[KR {TABLE_NAME[kind]}] — 지도 표가 숨긴·접힌 곳에 있다({title or "섹션 밖"})')
            continue
        if home is not None:
            if kind == home:
                found[home].append(t)
            else:
                res.violations.append(f'[KR {TABLE_NAME[home]}] — 「{SECTION_OF[home]}」 섹션에 지도에 없는 표가 있다'
                                      f'(머리 「{_raw_text(_head(t, kids)[0][0]) if _head(t, kids)[0] else "없음"}」)')
        elif kind:
            res.violations.append(f'[KR {TABLE_NAME[kind]}] — 지도 표가 다른 섹션({title or "섹션 밖"})에 있다')

    owned = set()
    want_n = {'index': 1, 'flows': 2, 'top': 1, 'rates': 1 if series else 0}
    for kind in ('index', 'top', 'rates'):
        if kind not in sec_of:
            continue
        if len(found[kind]) != want_n[kind]:
            why = '' if kind != 'rates' else (' — kr_econ 에 금리 자료가 있다' if series else ' — kr_econ 에 금리 자료가 없다')
            res.violations.append(f'[KR {TABLE_NAME[kind]}] — 표가 {len(found[kind])}개다(정확히 {want_n[kind]}개){why}')
            continue
        if want_n[kind]:
            {'index': _audit_index, 'top': _audit_top, 'rates': _audit_rates}[kind](
                res, found[kind][0], kids, data, owned)
    if 'flows' in sec_of:
        _audit_flows(res, found['flows'], sec_of['flows'], doc, kids, flows, owned)

    fund_node = _fund_delegated(html, doc, by_title, data, date)
    fund_blocks = [n for n in doc.nodes if 'data-fund-kr' in n.attrs]
    sector_secs = by_title.get(S_SECTOR) or []

    # 스트림 — 소유 칸 밖 수치를 한 곳씩 분류한다
    block, ctx = [], None
    owned_tokens = [0]

    def flush():
        nonlocal block, ctx
        if not block:
            return
        n = len(tokens(''.join(block)))
        kind = ctx
        if kind == 'owned':
            owned_tokens[0] += n
        elif kind == 'details':
            res.excluded += n
        elif kind == 'deleg':
            res.delegated += n
            if n:
                res.delegated_by['check_fund'] = res.delegated_by.get('check_fund', 0) + n
        elif n:
            _unverified(res, kind, n)
        block, ctx = [], None

    for item in doc.stream:
        if item is None:
            flush()
            continue
        text, stack, kind = item
        if kind is None:
            if any(id(n) in owned for n in stack):
                kind = 'owned'
            elif fund_node is not None and any(n is fund_node for n in stack):
                kind = 'deleg'
            elif any(any(n is b for b in fund_blocks) for n in stack):
                kind = KIND_FUND
            elif any(any(n is s for s in sector_secs) for n in stack):
                kind = KIND_SECTOR
            elif any(n.tag == 'table' for n in stack):
                kind = KIND_TABLE
            else:
                kind = KIND_PROSE
        if ctx is not None and ctx != kind:
            flush()
        ctx = kind
        block.append(text)
    flush()
    extra = sum(len(tokens(t)) for _, t in doc.extra)
    if extra:
        _unverified(res, KIND_PROSE, extra)

    res.tokens_seen = res.table_cells + res.unverified + res.delegated + res.excluded
    # 독립 집계: 파서가 본 모든 글 조각의 tokens() 수 = 분류된 수 + 소유 칸 안 tokens() + 숨김 + SVG
    indep = doc.raw_tokens + extra
    res.independent = indep
    classified = res.unverified + res.delegated + res.excluded + owned_tokens[0] + len(hidden) + len(svg)
    if indep != classified:
        res.violations.append(f'수치 집계가 맞지 않는다(분류 {classified} · 원문 {indep}) — 검사기 결함이거나 '
                              f'블록 경계를 넘어 붙은 수치다')
    return res
