"""일본 일간 v2 B — 「평소와의 차이」(N거래일 수익률·평소 대비 배수·업종 상대성과·JGB N일 변화) (2026-11-28).

원칙(사용자, 2026-11-19): 계산 가능한 사실은 코드가 쓰고 작성자는 해석만 한다. 수집기가 후보를 만들 때 한 번
계산해 `facts.items` 에 `b.` 항목으로 넣는다 — 계산에 쓴 끝점(`ends`)이 후보와 함께 입력 고정(`--pin`)·발행
스냅샷으로 얼어붙고, 조립·게이트는 다시 계산하지 않는다.

과거 값은 새 쓰기 경로 없이 레포 파일에서 읽는다 — 필드마다 (1) 발행 스냅샷 (2) 미발행 세션의 schema 2·complete
후보 (3) 다음 거래일 파일의 검증된 JPX 분모(TOPIX·업종) (4) 씨앗 `japan/data/history/jp_b_seed.json`.
값이 있는 곳끼리 다르면 그 칸은 계산하지 않고 diag 줄을 남긴다(자동 교정 없음).

Pure — 네트워크 없음. 설계: design-drafts/jp-daily-v2/B_design_v6.md.
"""
import json
import math
import os
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from japan import daily_index as IX
from japan import daily_rates as RT

SEED = os.path.join('japan', 'data', 'history', 'jp_b_seed.json')
DAILY_DIR = os.path.join('japan', 'data', 'daily')
RET_N = (5, 20, 60)
BP_N = (5, 20)
USUAL_N = 20
ASSETS = ('topix', 'nikkei')
_CENT, _TENTH = Decimal('0.01'), Decimal('0.1')


class OutOfCalendar(Exception):
    """휴장일 파일 범위 밖 — B 전체를 계산하지 않는다."""


# ── 거래일 ─────────────────────────────────────────────────────────────

def calendar(holidays_doc):
    """`data/market_holidays.json` 의 `jp` → (휴장일 집합, valid_through)."""
    jp = (holidays_doc or {}).get('jp') or {}
    return set(jp.get('dates') or ()), jp.get('valid_through')


def is_trading(day, hol):
    return day.weekday() < 5 and day.isoformat() not in hol


def back(session, n, hol):
    """휴장일·주말을 뺀 달력에서 정확히 n 칸 앞(미발행·결측과 무관)."""
    d = date.fromisoformat(session)
    while n:
        d -= timedelta(days=1)
        if is_trading(d, hol):
            n -= 1
    return d.isoformat()


def forward(session, hol):
    d = date.fromisoformat(session) + timedelta(days=1)
    while not is_trading(d, hol):
        d += timedelta(days=1)
    return d.isoformat()


# ── 과거 값 읽기 ───────────────────────────────────────────────────────

def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _facts(d):
    return {it['field_id']: it for it in ((d or {}).get('facts') or {}).get('items') or []}


def _own_value(d, s, field):
    """한 스냅샷(발행본·후보) 안의 세션 s 값. TOPIX·업종 = facts current 종가, 닛케이 = 공식 종가, JGB = 당일 네이버."""
    if not d or d.get('session') != s:
        return None
    if field == 'nikkei':
        v = ((d.get('indices') or {}).get('nikkei') or {}).get('value')
        return v if _finite(v) else None
    if field.startswith('jgb.'):
        r = (d.get('jgb') or {}).get(field[4:])
        if isinstance(r, dict) and r.get('period') == s and r.get('source') == 'naver' and _finite(r.get('value')):
            return r['value']
        return None
    if d.get('schema') != 2:
        return None                       # 옛 형식에는 TOPIX·업종 지수가 없다(ETF 뿐)
    it = _facts(d).get(f'{field}.close')
    if it and it.get('status') == 'current' and it.get('observation_date') == s and _finite(it.get('value')):
        return it['value']
    return None


def _denom_value(d, s, field):
    """다음 세션 스냅샷의 변화율 분모 — 날짜가 s 이고 JPX 원천인 것만(TOPIX·업종)."""
    if not d or d.get('schema') != 2 or not (field == 'topix' or field.startswith('sector.')):
        return None
    it = _facts(d).get(f'{field}.chg_pct') or {}
    den = it.get('denom') or {}
    if it.get('status') == 'current' and den.get('date') == s and str(den.get('source_id') or '').startswith('jpx:') \
            and _finite(den.get('value')):
        return den['value']
    return None


def _round_cmp(field, v):
    return round(v, 4 if field.startswith('jgb.') else 2)


class History:
    """세션별 과거 값. `today` = 지금 만드는 후보(세션 `session`) — 다음 세션 분모 원천으로도 쓴다."""

    def __init__(self, root, session, today, hol, seed=None):
        self.root, self.session, self.today, self.hol = root, session, today, hol
        self.seed = seed if seed is not None else (_load(os.path.join(root, SEED)) or {})
        self._cache = {}
        self.mismatch = []                # diag 줄(드러내는 장치)

    def _file(self, s):
        """(발행본 또는 적격 후보 | None, 어느 쪽인가)."""
        if s == self.session:
            return self.today, 'today'
        if s not in self._cache:
            pub = _load(os.path.join(self.root, DAILY_DIR, f'{s}.json'))
            if pub is not None:
                self._cache[s] = (pub, 'snapshot')
            else:
                cand = _load(os.path.join(self.root, DAILY_DIR, 'candidate', f'{s}.json'))
                ok = cand is not None and cand.get('schema') == 2 and cand.get('complete') is True
                self._cache[s] = (cand if ok else None, 'candidate')
        return self._cache[s]

    def _seed_value(self, s, field):
        if field.startswith('jgb.'):
            v = ((self.seed.get('jgb') or {}).get(field[4:]) or {}).get(s)
        elif field in ('topix', 'nikkei'):
            v = (self.seed.get(field) or {}).get(s)
        else:
            v = None
        return v if _finite(v) else None

    def value(self, s, field):
        """-> (값 | None, 출처 | None). 원천끼리 다르면 (None, None) + mismatch 줄."""
        if s == self.session:
            v = _own_value(self.today, s, field)
            return (v, 'today') if v is not None else (None, None)
        found = []
        d, kind = self._file(s)
        v = _own_value(d, s, field)
        if v is not None:
            found.append((v, kind))
        nxt = forward(s, self.hol)
        nd, _ = self._file(nxt)
        v = _denom_value(nd, s, field)
        if v is not None:
            found.append((v, f'denom:{nxt}'))
        v = self._seed_value(s, field)
        if v is not None:
            found.append((v, 'seed'))
        if not found:
            return None, None
        first = _round_cmp(field, found[0][0])
        bad = [f'{src} {x}' for x, src in found[1:] if _round_cmp(field, x) != first]
        if bad:
            line = f'B 원천 불일치 — {s} {field} {found[0][1]} {found[0][0]} / {" / ".join(bad)}'
            if line not in self.mismatch:
                self.mismatch.append(line)
            return None, None
        return found[0]


# ── 계산 ───────────────────────────────────────────────────────────────

def _dec(v):
    return Decimal(repr(v))


def _sign(d):
    return IX.sign(d)


def _q(d, unit):
    return float(d.quantize(_TENTH if unit in ('bp', '배') else _CENT, rounding=ROUND_HALF_UP))


def _item(fid, session, unit, value=None, direction=None, ends=None, why=None):
    out = {'field_id': fid, 'observation_date': session, 'value': value, 'unit': unit, 'source_id': 'b',
           'status': 'current' if value is not None else 'invalid'}
    if value is not None:
        out['direction'] = direction
        out['ends'] = ends
    else:
        out['why'] = why
    return out


def _end(s, v, src):
    return {'date': s, 'value': v, 'from': src}


def field_ids():
    """B 항목 전체(계산 순서 = 저장 순서)."""
    out = []
    for a in ASSETS:
        out += [(f'b.{a}.ret{n}', '%') for n in RET_N] + [(f'b.{a}.usual', '배')]
    for key in IX.SECTOR_KEYS:
        out += [(f'b.sector.{key}.rel{n}', '%p') for n in RET_N]
    for t in RT.TENORS:
        out += [(f'b.jgb.{t}.chg{n}', 'bp') for n in BP_N]
    for seg, _, _ in RT.SEGMENTS:
        out += [(f'b.curve.{seg}.chg{n}', 'bp') for n in BP_N]
    return out


def all_invalid(session, why):
    return [_item(fid, session, unit, why=why) for fid, unit in field_ids()]


def _ret(h, field, n):
    """-> (raw Decimal % | None, ends, 사유)."""
    s = h.session
    a, sa = h.value(s, field)
    b_day = back(s, n, h.hol)
    b, sb = h.value(b_day, field)
    if a is None or b is None or b == 0:
        return None, None, f'끝점 없음({s if a is None else b_day})'
    return (_dec(a) / _dec(b) - 1) * 100, [_end(b_day, b, sb), _end(s, a, sa)], None


def _usual(h, field):
    s = h.session
    days = [s]
    for _ in range(USUAL_N + 1):
        days.append(back(days[-1], 1, h.hol))
    closes = []
    for dd in days:
        v, src = h.value(dd, field)
        if v is None:
            return None, None, f'연속 종가 {USUAL_N + 2}개 중 {dd} 없음'
        closes.append((dd, v, src))
    rets = [abs(_dec(closes[i][1]) / _dec(closes[i + 1][1]) - 1) for i in range(USUAL_N + 1)]
    mean = sum(rets[1:], Decimal(0)) / USUAL_N
    if mean <= 0:
        return None, None, '직전 20거래일 평균 등락폭이 0'
    ends = [_end(dd, v, src) for dd, v, src in reversed(closes)]
    return rets[0] / mean, ends, None


def _bp(h, field, n):
    s = h.session
    a, sa = h.value(s, field)
    b_day = back(s, n, h.hol)
    b, sb = h.value(b_day, field)
    if a is None or b is None:
        return None, None, f'끝점 없음({s if a is None else b_day})'
    return (_dec(a) - _dec(b)) * 100, [_end(b_day, b, sb), _end(s, a, sa)], None


def _spread(h, day, short, long_):
    a, sa = h.value(day, f'jgb.{long_}')
    b, sb = h.value(day, f'jgb.{short}')
    if a is None or b is None:
        return None, None
    return (_dec(a) - _dec(b)) * 100, [_end(day, b, sb), _end(day, a, sa)]


def compute(session, today, root, holidays_doc, seed=None):
    """-> (b. 항목 목록, diag 줄 목록). 예외·달력 밖이면 전부 invalid(A 는 그대로 발행)."""
    hol, through = calendar(holidays_doc)
    if not through or session > through:
        why = f'휴장일 파일 범위 밖({through})'
        return all_invalid(session, why), [f'B 계산 안 함 — {why}']
    h = History(root, session, today, hol, seed)
    out = []
    raw_ret = {}
    for a in ASSETS:
        for n in RET_N:
            r, ends, why = _ret(h, a, n)
            raw_ret[(a, n)] = (r, ends)
            out.append(_item(f'b.{a}.ret{n}', session, '%', _q(r, '%') if r is not None else None,
                             _sign(r) if r is not None else None, ends, why))
        m, ends, why = _usual(h, a)
        out.append(_item(f'b.{a}.usual', session, '배', _q(m, '배') if m is not None else None, 1 if m else 0,
                         ends, why))
    for key in IX.SECTOR_KEYS:
        for n in RET_N:
            r, ends, why = _ret(h, f'sector.{key}', n)
            t, tends = raw_ret[('topix', n)]
            if r is not None and t is None:
                r, why = None, 'TOPIX 같은 기간 수익률 없음'
            rel = r - t if r is not None else None
            out.append(_item(f'b.sector.{key}.rel{n}', session, '%p', _q(rel, '%p') if rel is not None else None,
                             _sign(rel) if rel is not None else None, (ends or []) + (tends or []), why))
    for t in RT.TENORS:
        for n in BP_N:
            r, ends, why = _bp(h, f'jgb.{t}', n)
            out.append(_item(f'b.jgb.{t}.chg{n}', session, 'bp', _q(r, 'bp') if r is not None else None,
                             _sign(r) if r is not None else None, ends, why))
    for seg, short, long_ in RT.SEGMENTS:
        now, e1 = _spread(h, session, short, long_)
        for n in BP_N:
            b_day = back(session, n, hol)
            then, e0 = _spread(h, b_day, short, long_)
            if now is None or then is None:
                out.append(_item(f'b.curve.{seg}.chg{n}', session, 'bp',
                                 why=f'끝점 없음({session if now is None else b_day})'))
                continue
            r = now - then
            out.append(_item(f'b.curve.{seg}.chg{n}', session, 'bp', _q(r, 'bp'), _sign(r), e0 + e1))
    return out, list(h.mismatch)


# ── 읽기(조립·게이트) ───────────────────────────────────────────────────

def has_b(d):
    """B 가 있는 스냅샷 = `facts.items` 에 `b.` 항목이 하나라도 있는 것. 옛 글은 전부 거짓 — 바이트 그대로."""
    return any(str(it.get('field_id', '')).startswith('b.')
               for it in ((d or {}).get('facts') or {}).get('items') or [])


def get(d, fid):
    """current 인 B 항목 또는 None."""
    it = _facts(d).get(fid)
    return it if it and it.get('status') == 'current' and it.get('value') is not None else None


def status_line(d):
    """diag 한 줄 — 계산된 칸 수와 비운 칸 수."""
    items = [it for it in ((d or {}).get('facts') or {}).get('items') or [] if str(it['field_id']).startswith('b.')]
    ok = sum(1 for it in items if it['status'] == 'current')
    return f'평소와의 차이(B) — {ok}/{len(items)}칸 계산'
