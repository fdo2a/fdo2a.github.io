"""일본 일간 매크로 — 그날 달력 일정과 BOJ 시계열을 맞춘다 (2026-10-27).

「오늘 발표」 는 달력에 그날 공표가 있고 **API 에 직전 스냅샷보다 새 기간이 들어왔을 때만**
(`released`). 달력엔 있는데 API 가 아직 옛 기간이면 `pending` — 옛 값을 오늘 발표처럼 쓰지 않는다
(codex 설계 검토 #4). 직전 기간을 모르는 첫 실행도 `pending`. 컨센서스는 없으니 비교는 직전
발표치와 전년 같은 기간뿐이다.

v1 시리즈는 BOJ 시계열 API 의 것만(e-Stat 은 appId 가 생기면 v2). 코드는 이름으로 찾되
기준연도만 다른 시리즈가 겹치면 가장 새 기준연도를 고른다(`resolve_latest_base`).

Pure — 네트워크 없음.
"""
import math
import re

SERIES = {
    'cgpi': {'db': 'PR01', 'pattern': r'^\[Producer Price Index\] All commodities$',
             'name_ko': '기업물가지수(전체)'},
    'sppi': {'db': 'PR02', 'pattern': r'^\[Basic grouping index\] All items$',
             'name_ko': '기업 서비스가격지수(전체)'},
    'money_stock': {'db': 'MD02', 'pattern': r'^M2/Average Amounts Outstanding/Money Stock$',
                    'name_ko': '통화량 M2(평잔)'},
    'monetary_base': {'db': 'MD01', 'pattern': r'^Monetary Base/Average Amounts Outstanding$',
                      'name_ko': '본원통화(평잔)'},
}
_BASE = re.compile(r'CY(\d{4}) average=100')


def resolve_latest_base(meta_resp, name_pattern):
    pat = re.compile(name_pattern)
    hits = [r for r in (meta_resp or {}).get('RESULTSET') or []
            if r.get('SERIES_CODE') and pat.search(r.get('NAME_OF_TIME_SERIES') or '')]
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]['SERIES_CODE']
    years = [_BASE.search(r.get('UNIT') or '') for r in hits]
    if not all(years):
        raise ValueError(f'{name_pattern!r} 가 기준연도로 가를 수 없는 시리즈 {len(hits)}개에 맞는다')
    return max(zip(years, hits), key=lambda p: int(p[0].group(1)))[1]['SERIES_CODE']


def latest_periods(series_values):
    return {k: s['points'][-1][0] for k, s in (series_values or {}).items() if s and s.get('points')}


def _year_ago(period):
    if re.fullmatch(r'\d{4}-\d{2}', period):
        return f'{int(period[:4]) - 1}{period[4:]}'
    if re.fullmatch(r'\d{4}Q\d', period):
        return f'{int(period[:4]) - 1}{period[4:]}'
    return None


def _yoy(points, period, value):
    ago = _year_ago(period)
    base = next((v for p, v in points if p == ago), None)
    if base is None or not isinstance(base, (int, float)) or base == 0 or not math.isfinite(base):
        return None
    return round((value / base - 1) * 100, 1)


def macro_items(events_today, series_values, session, prev_periods):
    out = []
    for e in events_today or []:
        if e.get('kind') != 'release':
            continue
        key = e.get('series')
        item = {'name_ko': e.get('name_ko'), 'series': key, 'status': 'event', 'period': None,
                'value': None, 'prev_period': None, 'prev_value': None, 'yoy': None,
                'released': None, 'unit': None, 'source': e.get('source')}
        if key:
            s = (series_values or {}).get(key)
            pts = (s or {}).get('points') or []
            known = (prev_periods or {}).get(key)
            item['status'] = 'pending'
            if pts and known and pts[-1][0] > known:
                period, value = pts[-1]
                prev = pts[-2] if len(pts) > 1 else [None, None]
                item.update(status='released', period=period, value=value, prev_period=prev[0],
                            prev_value=prev[1], yoy=_yoy(pts, period, value), released=session,
                            unit=s.get('unit'))
        out.append(item)
    return out
