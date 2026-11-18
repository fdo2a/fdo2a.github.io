"""US 국채 16:00 ET 컷 — 발행용 커브를 주식·원자재·환율과 같은 시각에 맞춘다(2026-11-07).

**왜 바꿨나.** 네이버 「종가」(17:05 ET SIFMA 현물 마감)는 실제로 18:05-18:42 ET 에야 네 만기가
모였다(2026-11-02~06 수집 커밋) — 발행이 08:25-09:06 KST 로 밀렸다. 사용자 결정: 「16:00 ET 기준,
네이버 실시간에서」, 「10~15분 정도는 괜찮으니 16:00 값이 나오면 그 값으로」, 「수집 기준이 동일하면 괜찮아」.

**값 고르는 규칙(하나).** 각 만기에서 **16:00 ET 에 가장 가까운 스냅숏, 15:45-16:15 안**. 같은 거리면
16:00 이전 값. 네이버 장중 차트는 :09 오프셋 약 10분 간격이라 정각 값은 없다(11/06 2Y 15:38·15:59·16:09).
오늘·전일·1주 전 모두 **같은 규칙**으로 고른 값이다 — 브렌트 교훈(가격과 등락률의 기준이 달랐다).

**한 커브 한 원천.** 네 만기가 모두 네이버에서 나오면 네이버, 아니면 네 만기 모두 CNBC(Tradeweb) 5D 차트.
섞지 않는다. 둘 다 안 되면 None — 종가·야후(15:00 ET 에 끝난다)·FRED(T-1)로 채우지 않는다.

**원장.** 네이버 차트는 그날 하루치만 준다(날짜 파라미터 무시) → 전일·1주 전은 `data/yields_1600.json`
원장에서 꺼낸다. 비교 세션은 채권 달력으로 정확히 정한다 — 원장에 없다고 더 앞 날짜로 건너뛰지 않는다
(건너뛰면 「전일比」가 여러 세션 변화가 된다). 원장의 빈칸은 CNBC 5D(약 8거래일) 로만 메운다.

Pure 함수 + 얇은 fetch. 설계·검토 이력: `../plan.md` 「2026-11-07 — US 일간: 발행 직전 검토로 일원화」 v2.
"""
import datetime as dt
import json
import os

TENORS = ('2Y', '5Y', '10Y', '30Y')
NAVER_CODES = {'2Y': 'US2YT=RR', '5Y': 'US5YT=RR', '10Y': 'US10YT=RR', '30Y': 'US30YT=RR'}
CNBC_SYMBOLS = {'2Y': 'US2Y', '5Y': 'US5Y', '10Y': 'US10Y', '30Y': 'US30Y'}
NAVER_CHART = ('https://m.stock.naver.com/front-api/chart/pricesByPeriod?chartInfoType=governmentBond'
               '&scriptChartType=day&category=bond&reutersCode={code}')
CNBC_5D = 'https://ts-api.cnbc.com/harmony/app/charts/5D.json?symbol={sym}'
TARGET = '16:00'
WINDOW_MIN = 15
WEEK_BACK = 5
BASIS = 'cut_1600_et'


def _minutes(hhmm):
    h, m = hhmm.split(':')[:2]
    return int(h) * 60 + int(m)


def _seconds(stamp):
    """'HH:MM' 또는 'HH:MM:SS' → 자정부터 초. 선택 거리·창은 초까지 잰다(codex 구현 검토 13회)."""
    parts = [int(x) for x in stamp.split(':')]
    return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)


def _stamp(raw):
    """'YYYYMMDDHHMMSS' (뉴욕 현지 시각) → ('YYYY-MM-DD', 'HH:MM'). 형식이 다르면 None."""
    s = str(raw or '')
    if len(s) not in (12, 14) or not s.isdigit():
        return None
    try:   # 실제 있는 날짜·시각·초만(15:60·02-30·초 99 는 버린다 — codex 구현 검토 11·12회)
        dt.datetime(int(s[0:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]),
                    int(s[12:14]) if len(s) == 14 else 0)
    except ValueError:
        return None
    sec = s[12:14] if len(s) == 14 else '00'
    hhmm = f'{s[8:10]}:{s[10:12]}' + ('' if sec == '00' else f':{sec}')
    return f'{s[0:4]}-{s[4:6]}-{s[6:8]}', hhmm


def _num(v):
    """유한한 수만 — NaN·Infinity 는 None(그 포인트를 버린다, codex 구현 검토 10회 #2)."""
    import math
    try:
        f = float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_naver_chart(payload):
    """네이버 `chart/pricesByPeriod` → [(date, 'HH:MM', value)]. `priceInfos`·`lastPriceInfos` 모두.

    날짜는 각 포인트의 뉴욕 날짜다 — 응답이 어느 날로 넘어갔는지에 기대지 않고 포인트마다 대조한다
    (codex 설계 검토 2회 #3).
    """
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ('priceInfos', 'lastPriceInfos') and isinstance(v, list):
                    for p in v:
                        st = _stamp((p or {}).get('localDateTime'))
                        val = _num((p or {}).get('currentPrice'))
                        if st and val is not None:
                            out.append((st[0], st[1], val))
                else:
                    walk(v)
    walk(payload)
    return sorted(set(out))


def parse_cnbc_5d(payload):
    """CNBC `charts/5D.json` → [(date, 'HH:MM', close)]. `tradeTime` 은 ET 로 본다(17:05 마지막 봉이 SIFMA 마감과 맞는다)."""
    bars = (((payload or {}).get('barData') or {}).get('priceBars')) or []
    out = []
    for b in bars:
        st = _stamp((b or {}).get('tradeTime'))
        val = _num((b or {}).get('close'))
        if st and val is not None:
            out.append((st[0], st[1], val))
    return sorted(set(out))


def pick(points, session, target=TARGET, window=WINDOW_MIN):
    """`session` 날짜의 포인트 가운데 `target` 에 가장 가까운 것(±window 분). 같은 거리면 이전 값.

    → {'value', 'stamp'} 또는 None.
    """
    t0 = _seconds(target)
    best = None
    for d, hhmm, v in points or ():
        if d != session:
            continue
        diff = _seconds(hhmm) - t0
        if abs(diff) > window * 60:
            continue
        key = (abs(diff), diff > 0)
        if best is None or key < best[0]:
            best = (key, hhmm, v)
    if best is None:
        return None
    return {'value': round(best[2], 4), 'stamp': best[1]}


def curve(session, naver, cnbc=None, target=TARGET):
    """네 만기를 한 원천에서. naver/cnbc = {tenor: [(date, hhmm, v)]}. → {'source', 'tenors'} 또는 None."""
    for source, pts in (('naver', naver), ('cnbc', cnbc)):
        if not pts:
            continue
        got = {t: pick(pts.get(t), session, target) for t in TENORS}
        if all(got.values()):
            return {'source': source, 'target': target, 'tenors': got}
    return None


def sessions_before(session, n, closed):
    """`session` 직전의 국채 세션 n 개(가까운 것부터). 주말·`closed` 를 건너뛴다."""
    out = []
    d = dt.date.fromisoformat(session)
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in closed:
            out.append(d.isoformat())
    return out


def needed(session, closed):
    """원장에 있어야 하는 날짜: 오늘, 전일, 1주(5세션) 전."""
    prev = sessions_before(session, WEEK_BACK, closed)
    return [session, prev[0], prev[-1]]


class LedgerCorrupt(ValueError):
    """원장 파일이 있는데 읽을 수 없다 — 빈 원장으로 보면 저장할 때 지난 기록을 지운다."""


def _entry_problem(d, e):
    """원장 한 행의 구조 — 날짜 키, {source, tenors{네 만기: {value: 수, stamp}}}. 문제가 없으면 None."""
    import math
    import re
    if not isinstance(d, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d):
        return '날짜 키가 아니다'      # save() 는 YYYY-MM-DD 만 남긴다 — 다른 꼴은 다음 저장에서 사라진다
    try:
        dt.date.fromisoformat(d)
    except ValueError:
        return '날짜 키가 아니다'
    if not isinstance(e, dict) or e.get('source') not in ('naver', 'cnbc'):
        return 'source 없음'
    target = e.get('target', TARGET)
    if target != TARGET:
        return f'target 이 {TARGET} 이 아니다'   # 이 원장은 16:00 ET 컷만 담는다(10회 #1)
    ten = e.get('tenors')
    if not isinstance(ten, dict) or set(ten) != set(TENORS):
        return '네 만기가 아니다'
    for t, v in ten.items():
        val = v.get('value') if isinstance(v, dict) else None
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            return f'{t} 값 형식'
        st = v.get('stamp')
        if not isinstance(st, str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?', st):
            return f'{t} 시각 형식'
        if abs(_seconds(st) - _seconds(target)) > WINDOW_MIN * 60:
            return f'{t} 시각이 창 밖'
    return None


def load(path, strict=False):
    """원장. 파일이 없으면 {}(첫 실행). 있는데 깨졌으면 `strict` 일 때 LedgerCorrupt, 아니면 {}."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as fh:
            got = json.load(fh)
        if not isinstance(got, dict):
            raise ValueError('not an object')
        for d, e in got.items():
            problem = _entry_problem(d, e)
            if problem:
                raise ValueError(f'{d}: {problem}')
        return got
    except (OSError, ValueError) as e:
        if strict:
            raise LedgerCorrupt(f'{path}: {e}') from e
        return {}


def save(path, ledger, keep=40):
    """최근 `keep` 세션만 남긴다(1주 전 비교에 5세션이면 충분, 여유를 둔다)."""
    dates = sorted(d for d in ledger if len(d) == 10)[-keep:]
    body = {d: ledger[d] for d in dates}
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(body, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write('\n')


def record(ledger, session, got):
    """원장에 한 세션을 적는다. 이미 네이버 값이 있으면 덮지 않는다(같은 규칙·같은 원천이면 값도 같아야
    하고, 다르면 늦은 회차가 아니라 첫 기록이 그날 16:00 에 더 가깝다). CNBC 기록은 네이버로 올린다.
    → 바뀌었으면 True.
    """
    if not got:
        return False
    have = ledger.get(session)
    if have and (have.get('source') == 'naver' or have.get('source') == got.get('source')):
        return False
    ledger[session] = got
    return True


def window_closed(session, now_et, target=TARGET, window=WINDOW_MIN):
    """`now_et`(뉴욕 현지 naive datetime 또는 None=닫힌 것으로 본다)가 그 세션의 창 끝(16:15)을 지났나."""
    if now_et is None:
        return True
    end = dt.datetime.fromisoformat(session) + dt.timedelta(minutes=_minutes(target) + window)
    return now_et >= end


def update(ledger, session, closed, naver, cnbc_fetch=None, target=TARGET, now_et=None):
    """오늘(네이버 → CNBC)과 원장에 빈 비교일(CNBC 만)을 채운다. `cnbc_fetch()` 는 필요할 때만 부른다.

    → 바뀐 날짜 목록. 전일·1주 전을 네이버로 채우지 않는 이유: 네이버 차트는 그날 하루치만 준다.
    **오늘 값은 창이 닫힌 뒤(16:15 ET)에만 적는다** — 장중에 15:48 을 먼저 적으면 네이버 기록은 덮지
    않으므로 더 가까운 15:59 가 와도 남는다(codex 구현 검토 1회 #1).
    """
    changed = []
    cache = {}

    def cnbc():
        if 'v' not in cache:
            cache['v'] = cnbc_fetch() if cnbc_fetch else None
        return cache['v']

    if window_closed(session, now_et, target):
        today = curve(session, naver, None, target)
        if not today:
            today = curve(session, None, cnbc(), target)
        if record(ledger, session, today):
            changed.append(session)
    for d in needed(session, closed)[1:]:
        if d in ledger:
            continue
        got = curve(d, None, cnbc(), target)
        if record(ledger, d, got):
            changed.append(d)
    return changed


def bootstrap(ledger, cnbc, closed, before):
    """원장이 처음이거나 짧을 때 CNBC 5D 에 있는 지난 세션(`before` 이전)을 모두 적는다 — 전환 첫 주의
    1주 전 비교와 이력 소급(`history.backfill_yield_cut`)용. → 적은 날짜."""
    days = sorted({d for p in (cnbc or {}).values() for d, _, _ in (p or ())})
    out = []
    for d in days:
        if d >= before or d in closed or dt.date.fromisoformat(d).weekday() >= 5:
            continue
        if d not in ledger and record(ledger, d, curve(d, None, cnbc)):
            out.append(d)
    return out


def rows(session, ledger, closed):
    """원장 → 발행 커브 {tenor: row}. 오늘이 없으면 None. 비교일이 없으면 그 칸만 None(완성 게이트가 막는다)."""
    today = ledger.get(session)
    if not today:
        return None
    _, prev, week = needed(session, closed)
    p, w = ledger.get(prev), ledger.get(week)
    out = {}
    for t in TENORS:
        cur = (today.get('tenors') or {}).get(t) or {}
        lv = cur.get('value')
        if lv is None:
            return None
        pv = ((p or {}).get('tenors') or {}).get(t, {}).get('value')
        wv = ((w or {}).get('tenors') or {}).get(t, {}).get('value')
        out[t] = {
            'level': round(lv, 3), 'date': session, 'stamp_et': cur.get('stamp'),
            'bp': (lv - pv) * 100 if pv is not None else None,
            'prev_date': prev if pv is not None else None,
            'prev_source': (p or {}).get('source') if pv is not None else None,
            'week_ago': round(wv, 3) if wv is not None else None,
            'week_ago_date': week if wv is not None else None,
            'week_ago_source': (w or {}).get('source') if wv is not None else None,
            'source': today.get('source'), 'basis': BASIS,
        }
    return out


def fetch_json(url, ssl_ctx=None, timeout=25):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def fetch_naver(ssl_ctx=None, get=fetch_json):
    """{tenor: points} — 한 만기라도 못 받으면 그 만기는 빈 목록(curve 가 네이버를 통째로 버린다)."""
    import urllib.parse
    out = {}
    for t, code in NAVER_CODES.items():
        try:
            out[t] = parse_naver_chart(get(NAVER_CHART.format(code=urllib.parse.quote(code, safe='')), ssl_ctx))
        except Exception:  # noqa: BLE001 — 네트워크·형식 실패는 「없음」
            out[t] = []
    return out


def fetch_cnbc(ssl_ctx=None, get=fetch_json):
    out = {}
    for t, sym in CNBC_SYMBOLS.items():
        try:
            out[t] = parse_cnbc_5d(get(CNBC_5D.format(sym=sym), ssl_ctx))
        except Exception:  # noqa: BLE001
            out[t] = []
    return out


def merge(base, other):
    """`other` 원장의 세션을 `base` 에 `record` 규칙으로 합친다(네이버 기록은 덮지 않는다). → 바뀐 날짜."""
    return [d for d in sorted(other or {}) if len(d) == 10 and record(base, d, other[d])]


def _cli(argv):
    """`python3 scripts/us/yield_cut.py merge <대상 원장> <합칠 원장>` — 실패 시 원장 보존용(scripts/ci)."""
    if len(argv) != 3 or argv[0] != 'merge':
        print('usage: yield_cut.py merge TARGET SOURCE')
        return 2
    target, source = argv[1], argv[2]
    # 어느 쪽이든 깨진 원장을 빈 것으로 보면 원격 기록을 지우거나 「보존했다」고 거짓으로 끝난다
    # (codex 구현 검토 3회 #1·#2). 파일 없음(첫 실행)만 빈 원장이다.
    try:
        base, other = load(target, strict=True), load(source, strict=True)
    except LedgerCorrupt as e:
        print(f'yield_cut merge: 깨진 원장 — {e}')
        return 1
    if not other:
        print('yield_cut merge: 합칠 원장이 비었다')
        return 0
    got = merge(base, other)
    if got:
        save(target, base)
    print(f'yield_cut merge: {len(got)} 세션 ({", ".join(got)})')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(_cli(sys.argv[1:]))
