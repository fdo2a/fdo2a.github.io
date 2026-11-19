"""일본 일간 v2 — JPX TOPIX·TOPIX-17 업종지수: 슬롯 고르기·쌍 읽기·연쇄 검산·네이버 대조 (2026-11-19).

JPX 실시간 지수 페이지의 값 파일 `indices_stock_price3{,.1~.5}.txt` 에는 날짜가 없다 — 같은 번호의
`.time.txt` 가 그 판의 시각(`YYYYMMDDHHMM`, JST)이다. 그래서 파일 번호가 아니라 **시각의 날짜**로
세션(target)과 직전 세션(prev) 슬롯을 하나씩 고르고, 시각 → 값 → 시각으로 읽어 그 사이에 판이 바뀌지
않았는지 본다. 숫자는 `Decimal` 로만 읽는다 — `float` 반올림은 경계(−3.175)에서 원천과 갈린다.

검증이 하나라도 실패하면 그 블록은 `invalid` 다. 다른 원천·ETF·전일 값으로 물러서지 않는다.
사유 글자에는 데이터 숫자를 넣지 않는다(실패한 숫자는 스냅샷 어디에도 남기지 않는다).

네트워크는 주입한다: `get(url) -> (status, headers, bytes)`, `sleep(sec)`. Pure 계산만 여기 있다.
설계: design-drafts/jp-daily-v2/jp_daily_v2_design.md §2·§3 (spec 으로 옮겨질 예정).
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime

JST = timezone(timedelta(hours=9))
BASE = 'https://www.jpx.co.jp/market/indices/indices_stock_price3'
SLOTS = ('', '.1', '.2', '.3', '.4', '.5')
FINAL_FROM = '1630'            # 계산에 쓰는 두 슬롯 모두 16:30 JST 이후 판(실측 마지막 판 16:59)
STABLE_MIN = 30                # 현재 슬롯: 값 응답 Date − Last-Modified ≥ 30분(장중은 1분마다 갱신)
LM_TOL_SEC = 2                 # 값 응답과 뒤 시각 응답의 Last-Modified 차
PAIR_TRIES = 3                 # 쌍 읽기 — 2초 간격 3번
TABLE_TRIES = 3                # 표부터 다시 — 처음 + 2번
TOL = Decimal('0.01')
CENT = Decimal('0.01')

# TOPIX-17 업종지수 — JPX 키(값 파일 `IndustryTypeStockIndex`)와 한국어 이름. 순서 = JPX 순서 = NEXT FUNDS 1617~1633.
SECTORS = (
    ('Topix17Food', '식품'), ('Topix17Energy', '에너지자원'), ('Topix17BuildingMaterial', '건설·자재'),
    ('Topix17MaterialChemistry', '소재·화학'), ('Topix17nostrum', '의약품'), ('Topix17CarTransport', '자동차·수송기'),
    ('Topix17SteelNonferrous', '철강·비철'), ('Topix17Machine', '기계'), ('Topix17ElectricalPrecision', '전기·정밀'),
    ('Topix17InformationService', '정보통신·서비스'), ('Topix17ElectricPowerGas', '전력·가스'),
    ('Topix17TransportationLogistics', '운수·물류'), ('Topix17TradingWholesale', '상사·도매'),
    ('Topix17Retail', '소매'), ('Topix17Bank', '은행'), ('Topix17Finance', '금융(은행 제외)'),
    ('Topix17RealEstate', '부동산'),
)
SECTOR_KEYS = tuple(k for k, _ in SECTORS)
SECTOR_NAMES = dict(SECTORS)


def value_url(slot):
    return f'{BASE}{slot}.txt'


def time_url(slot):
    return f'{BASE}{slot}.time.txt'


def source_id(slot):
    return f'jpx:price3{slot}'


# ── 읽기 ────────────────────────────────────────────────────────────────

def parse_stamp(body):
    """시각 파일 글자 → 'YYYYMMDDHHMM' 또는 None. 실재하는 일시여야 한다(R2 — 202613011659 는 읽지 못한 것)."""
    try:
        s = (body.decode('ascii') if isinstance(body, bytes) else str(body)).strip()
    except UnicodeDecodeError:
        return None
    if not re.fullmatch(r'\d{12}', s):
        return None
    try:
        t = datetime.strptime(s, '%Y%m%d%H%M')
    except ValueError:
        return None
    return s if t.strftime('%Y%m%d%H%M') == s else None


def stamp_date(stamp):
    return f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}'


def _header(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _http_time(raw):
    if not raw:
        return None
    try:
        t = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    return t if t and t.tzinfo else None


def _no_dup(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError('중복 키')
        out[k] = v
    return out


def parse_values(body):
    """값 파일 → dict. utf-8-sig, 중복 키 거부."""
    data = json.loads(body.decode('utf-8-sig'), object_pairs_hook=_no_dup)
    if not isinstance(data, dict):
        raise ValueError('JSON 객체가 아니다')
    return data


def _pair_once(get, slot):
    t1 = get(time_url(slot))
    v = get(value_url(slot))
    t2 = get(time_url(slot))
    if any(r[0] != 200 for r in (t1, v, t2)):
        return None, '응답 코드가 정상이 아니다'
    s1, s2 = parse_stamp(t1[2]), parse_stamp(t2[2])
    if not s1 or s1 != s2:
        return None, '앞뒤 시각이 다르거나 형식이 아니다'
    lm_v, lm_t = _http_time(_header(v[1], 'Last-Modified')), _http_time(_header(t2[1], 'Last-Modified'))
    if lm_v is None or lm_t is None:
        return None, 'Last-Modified 가 없다'
    if abs((lm_v - lm_t).total_seconds()) > LM_TOL_SEC:
        return None, '값과 시각의 Last-Modified 가 어긋난다'
    try:
        data = parse_values(v[2])
    except (ValueError, UnicodeDecodeError):
        return None, '값 파일이 중복 없는 JSON 이 아니다'
    served = _http_time(_header(v[1], 'Date'))
    return {'slot': slot, 'stamp': s1, 'date': stamp_date(s1),
            'last_modified': lm_v.astimezone(timezone.utc).isoformat(),
            'served_at': served.astimezone(timezone.utc).isoformat() if served else None,
            'sha256': hashlib.sha256(v[2]).hexdigest(), 'data': data}, None


def read_pair(get, slot, sleep, tries=PAIR_TRIES):
    """시각 → 값 → 시각. 어긋나면 2초 간격으로 `tries` 번까지. -> (읽은 것 | None, 사유)."""
    why = None
    for i in range(tries):
        if i:
            sleep(2)
        got, why = _pair_once(get, slot)
        if got:
            return got, None
    return None, why


def slot_table(get, slots=SLOTS):
    """{슬롯: 시각}. 404·형식이 다른 슬롯은 뺀다."""
    out = {}
    for s in slots:
        status, _, body = get(time_url(s))
        if status == 200:
            st = parse_stamp(body)
            if st:
                out[s] = st
    return out


def select(get, session, prev, sleep):
    """세션·직전 세션 슬롯을 시각의 날짜로 하나씩 고르고 쌍으로 읽는다. -> (target, prev, 사유).

    고른 뒤 쌍 읽기의 시각이 표의 시각과 글자 그대로 같고 날짜가 각각 맞는지 다시 본다(R1 — 09:00 JST 에
    슬롯이 밀리면 `.1` 이 다른 날이 된다). 겹치거나 다르면 표부터 다시, 그래도 안 되면 실패."""
    why = None
    for i in range(TABLE_TRIES):
        if i:
            sleep(2)
        table = slot_table(get)
        by_date = {}
        for s, st in table.items():
            by_date.setdefault(stamp_date(st), []).append(s)
        t_slots, p_slots = by_date.get(session, []), by_date.get(prev, [])
        if len(t_slots) > 1 or len(p_slots) > 1:
            why = '같은 날짜의 슬롯이 둘 이상이다'
            continue
        if not t_slots:
            return None, None, '세션 날짜의 슬롯이 없다'
        if not p_slots:
            return None, None, '직전 세션 날짜의 슬롯이 없다'
        tgt, w1 = read_pair(get, t_slots[0], sleep)
        prv, w2 = read_pair(get, p_slots[0], sleep)
        if tgt is None or prv is None:
            return None, None, f'슬롯을 읽지 못했다({w1 or w2})'
        if (tgt['stamp'] != table[t_slots[0]] or prv['stamp'] != table[p_slots[0]]
                or tgt['date'] != session or prv['date'] != prev):
            why = '읽는 사이 슬롯이 밀렸다'
            continue
        return tgt, prv, None
    return None, None, why


def final_problem(tgt, prv):
    """마감 뒤 갱신이 멈춘 최종판인가(R8). 문제가 없으면 None."""
    for r in (tgt, prv):
        if r['stamp'][8:] < FINAL_FROM:
            return '마감 전(16:30 JST 이전) 판이다'
    if tgt['slot'] == '':
        lm, served = tgt['last_modified'], tgt['served_at']
        if not served:
            return '현재 슬롯 응답에 Date 가 없다'
        gap = datetime.fromisoformat(served) - datetime.fromisoformat(lm)
        if gap < timedelta(minutes=STABLE_MIN):
            return '현재 슬롯이 아직 갱신 중일 수 있다(마지막 갱신 뒤 30분 미만)'
    return None


# ── 값과 검산 ───────────────────────────────────────────────────────────

def dec(raw):
    """원문 글자 → 유한한 Decimal 또는 None. 쉼표를 지우고 float 를 거치지 않는다."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        return None                          # float 로 온 값은 받지 않는다 — 원문 글자가 아니다
    try:
        d = Decimal(str(raw).replace(',', '').strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def ratio_of(cur, prev):
    """(cur/prev − 1) × 100 을 소수 둘째까지 ROUND_HALF_UP(절댓값 기준 사사오입)."""
    return ((cur / prev - 1) * 100).quantize(CENT, rounding=ROUND_HALF_UP)


def sign(x):
    return (x > 0) - (x < 0)


def chain(cur_entry, prev_entry):
    """한 지수의 당일 항목과 직전 슬롯 항목 → ({close, denom, ratio, direction}, None) 또는 (None, 사유)."""
    if not isinstance(cur_entry, dict) or not isinstance(prev_entry, dict):
        return None, '항목이 없다'
    cur, cmp_, ratio = (dec(cur_entry.get(k)) for k in ('currentPrice', 'previousDayComparison', 'previousDayRatio'))
    denom = dec(prev_entry.get('currentPrice'))
    if None in (cur, cmp_, ratio, denom):
        return None, '값이 수가 아니다'
    if cur <= 0 or denom <= 0:
        return None, '종가가 양수가 아니다'
    if abs(cur - cmp_ - denom) > TOL:
        return None, '전일비 연쇄 검산 불일치'
    if ratio_of(cur, denom) != ratio:
        return None, '등락률 검산 불일치'
    return {'close': cur, 'denom': denom, 'ratio': ratio, 'direction': sign(cur - denom)}, None


def topix_entry(data):
    return ((data or {}).get('Topix') or {}).get('Topix')


def sector_entries(data):
    return (data or {}).get('IndustryTypeStockIndex')


# ── 네이버 독립 대조 ────────────────────────────────────────────────────

def xcheck_basic(text, session, close, denom):
    """target 이 현재 슬롯일 때 — `/index/.TOPX/basic` 만(R4). -> (근거, None) 또는 (None, 사유)."""
    try:
        d = json.loads(text) if isinstance(text, (str, bytes)) else text
    except ValueError:
        return None, '네이버 basic 응답이 JSON 이 아니다'
    raw_t = str((d or {}).get('localTradedAt') or '')
    try:
        t = datetime.fromisoformat(raw_t)
    except ValueError:
        return None, '네이버 basic 시각을 읽지 못했다'
    if t.tzinfo is None:
        return None, '네이버 basic 시각에 오프셋이 없다'
    if t.astimezone(JST).date().isoformat() != session:
        return None, '네이버 basic 시각이 세션 날짜가 아니다'
    if d.get('marketStatus') != 'CLOSE':
        return None, '네이버 basic 이 마감 상태가 아니다'
    n_close, n_chg = dec(d.get('closePrice')), dec(d.get('compareToPreviousClosePrice'))
    if n_close is None or n_chg is None:
        return None, '네이버 basic 값이 수가 아니다'
    if abs(n_close - close) > TOL or abs((n_close - n_chg) - denom) > TOL:
        return None, '네이버 basic 과 JPX 가 다르다'
    return {'via': 'naver:basic', 'close': float(n_close), 'prev_close': float(n_close - n_chg),
            'traded_at': raw_t}, None


def xcheck_day(text, session, prev, close, denom):
    """target 이 `.N` 일 때 — `/chart/foreign/index/.TOPX/day` 만. 두 날 행이 각각 정확히 하나."""
    try:
        rows = json.loads(text, parse_float=Decimal) if isinstance(text, (str, bytes)) else text
    except ValueError:
        return None, '네이버 day 응답이 JSON 이 아니다'
    if not isinstance(rows, list):
        return None, '네이버 day 응답이 목록이 아니다'

    def on(day):
        want = day.replace('-', '')
        return [r for r in rows if isinstance(r, dict) and str(r.get('localDate')) == want]
    s_rows, p_rows = on(session), on(prev)
    if len(s_rows) != 1 or len(p_rows) != 1:
        return None, '네이버 day 의 세션·직전 세션 행이 각각 하나가 아니다'
    sc, pc = s_rows[0].get('closePrice'), p_rows[0].get('closePrice')
    sc = sc if isinstance(sc, Decimal) else dec(sc) if isinstance(sc, (str, int)) else None
    pc = pc if isinstance(pc, Decimal) else dec(pc) if isinstance(pc, (str, int)) else None
    if sc is None or pc is None or not sc.is_finite() or not pc.is_finite():
        return None, '네이버 day 값이 수가 아니다'
    if abs(sc - close) > TOL or abs(pc - denom) > TOL:
        return None, '네이버 day 와 JPX 가 다르다'
    return {'via': 'naver:day', 'close': float(sc), 'prev_close': float(pc), 'traded_at': None}, None


# ── 한 번에 ─────────────────────────────────────────────────────────────

def _evidence(r):
    return {'slot': r['slot'], 'jpx_time': r['stamp'], 'last_modified': r['last_modified'], 'sha256': r['sha256']}


def collect(get, session, prev, sleep, naver_basic=None, naver_day=None):
    """-> {'topix': 블록, 'sectors': 블록}. 블록 = {status: current|invalid, why, ...}.

    `naver_basic()`·`naver_day()` 는 응답 글자를 돌려준다(경로는 JPX 슬롯이 정한다 — 하나만 부른다).
    공통 조건(쌍 읽기·슬롯 고르기·최종판)이 실패하면 두 블록 모두 invalid. 업종 키·값 결함은 업종만(9회차 #3)."""
    bad = lambda why: {'status': 'invalid', 'why': why}  # noqa: E731
    tgt, prv, why = select(get, session, prev, sleep)
    if tgt is None:
        return {'topix': bad(why), 'sectors': bad(why)}
    why = final_problem(tgt, prv)
    if why:
        return {'topix': bad(why), 'sectors': bad(why)}
    slots = [_evidence(tgt), _evidence(prv)]
    t_src, p_src = source_id(tgt['slot']), source_id(prv['slot'])

    got, why = chain(topix_entry(tgt['data']), topix_entry(prv['data']))
    if got is None:
        topix = bad(f'TOPIX {why}')
    else:
        try:
            if tgt['slot'] == '':
                xc, why = xcheck_basic(naver_basic(), session, got['close'], got['denom'])
            else:
                xc, why = xcheck_day(naver_day(), session, prev, got['close'], got['denom'])
        except Exception as e:  # noqa: BLE001 — 대조 실패는 그 블록만 invalid
            xc, why = None, f'네이버 대조 실패({type(e).__name__})'
        topix = bad(f'TOPIX {why}') if xc is None else dict(
            got, status='current', why=None, slots=slots, xcheck=xc, source_id=t_src, denom_source_id=p_src)

    if topix['status'] != 'current':
        sectors = bad('TOPIX 가 검증되지 않아 업종도 싣지 않는다')
    else:
        cur_s, prev_s = sector_entries(tgt['data']), sector_entries(prv['data'])
        if (not isinstance(cur_s, dict) or not isinstance(prev_s, dict)
                or set(cur_s) != set(SECTOR_KEYS) or set(prev_s) != set(SECTOR_KEYS)):
            sectors = bad('업종 키가 정해진 17개와 다르다')
        else:
            rows, why = [], None
            for key in SECTOR_KEYS:
                r, w = chain(cur_s[key], prev_s[key])
                if r is None:
                    why = f'업종 {SECTOR_NAMES[key]} {w}'
                    break
                rows.append(dict(r, key=key, name_ko=SECTOR_NAMES[key]))
            sectors = bad(why) if why else {'status': 'current', 'why': None, 'rows': rows, 'slots': slots,
                                            'source_id': t_src, 'denom_source_id': p_src}
    return {'topix': topix, 'sectors': sectors}
