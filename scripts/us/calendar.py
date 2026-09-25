#!/usr/bin/env python3
"""다음 열흘에 무엇이 오는가 — 「오늘 하루를 준비한다」의 재료.

리포트가 어제를 설명하는 데는 서른 개가 넘는 필드를 쓰면서, 앞을 보는 값은
`forward_5y5y` 하나뿐이었다. 「앞으로」를 담당하던 두 재료(FedWatch 확률과 §9 말미
「다음 발표 일정」 카드)는 **둘 다 에이전트 웹서치 산문**이라 전일 값도 없고 게이트도
검사하지 않았다(`macro_gate.py` 전수 grep 0건). 그래서 있으면 있고 없으면 없었다.

이 모듈은 그중 **출처가 필요 없는 부분**만 맡는다 — 지수 만기는 순수 계산이고, 연준
블랙아웃은 회의일만 주어지면 계산식이다. 경제지표 일정(FRED)과 국채 입찰(Treasury)은
네트워크가 필요해 수집 단계에 붙는다.

**회의일은 여기서 만들지 않는다.** 레포에 있는 FOMC 날짜는 웹서치 산문 한 줄뿐이라
(`macro.json` 의 「9월 16일 FOMC」), 나머지를 채우면 그것은 수집이 아니라 창작이다.
표가 비었거나 낡았으면 그 항목을 **빼고 `missing` 에 적는다** — 삭제가 창작보다 낫다.
"""

import datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
KST = ZoneInfo('Asia/Seoul')

HORIZON_DAYS = 10

# FOMC 성명 발표 시각. 회의 이틀째 14:00 ET 가 오래 고정돼 있다. 기자회견은 그 30분
# 뒤라 시각이 다르다 — 둘을 한 시각으로 뭉치면 한국 독자는 03:00 과 03:30 중 틀린 쪽에
# 깨어 있게 된다. 이벤트는 성명 시각으로 잡고 기자회견은 볼 것에 적는다.
FOMC_TIME_ET = '14:00'
# 경제전망요약(SEP·점도표)은 분기 회의에만 나온다. 매번 나오는 것처럼 적으면
# 여덟 번 중 네 번은 없는 자료를 기다리게 만든다.
SEP_MONTHS = (3, 6, 9, 12)


def to_kst(day, time_et):
    """ET 벽시계 → KST datetime. 시각을 모르면 None.

    **시차를 상수로 박지 않는다.** ET 는 3월과 11월에 한 시간씩 움직이고 KST 는 안
    움직여서, +13/+14 중 하나를 고르면 매년 두 번 틀린 시각을 인쇄한다. 한국 독자에게
    「밤 10시 30분」과 「밤 9시 30분」은 준비 시점이 다른 얘기다.
    """
    if not time_et:
        return None
    hh, mm = (int(x) for x in time_et.split(':'))
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=ET).astimezone(KST)


def _fmt_kst(day, time_et):
    got = to_kst(day, time_et)
    return got.strftime('%Y-%m-%d %H:%M') if got else None


def monthly_expiry(year, month):
    """그 달 세 번째 금요일.

    ponytail: 휴장일 보정은 없다. 셋째 금요일이 휴장이면 실제 만기는 하루 앞당겨진다.
    셋째 금요일은 언제나 15~21일이라 여기에 닿는 휴장일은 둘뿐이고, 2026~2040 을 전수로
    세어 보면 **네 번** 어긋난다 — 2030-04-19·2033-04-15(성금요일), 2037-06-19(준틴스).
    (2026-06-19 도 준틴스였으나 이미 지났다.) 가장 이른 것이 3년 반 뒤라 휴장 달력을
    들이지 않는다. 그 주만 사람이 보고, 더 일찍 필요해지면 그때 넣는다.
    """
    first = dt.date(year, month, 1)
    first_friday = first + dt.timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + dt.timedelta(days=14)


def quad_witching(year):
    """분기 말 만기 넷. 지수선물·지수옵션·개별선물·개별옵션이 같은 날 만난다."""
    return [monthly_expiry(year, m) for m in (3, 6, 9, 12)]


def blackout_window(meeting):
    """(시작, 끝) — 회의 **2주 전 토요일**부터 회의 **다음 목요일**까지.

    연준 위원들이 통화정책을 공개적으로 말하지 않는 구간이다. 「이번 주에는 연준에서
    새 발언이 나오지 않는다」는 그 자체로 준비에 쓰이는 정보이고, 계산에 드는 비용이 0이다.
    """
    # 회의 직전 토요일까지 물러난 뒤 한 주 더 — 그래서 「두 번째 앞선 토요일」이다.
    days_back = (meeting.weekday() - 5) % 7 or 7
    return meeting - dt.timedelta(days=days_back + 7), meeting + dt.timedelta(
        days=(3 - meeting.weekday()) % 7 or 7)


def in_blackout(day, meetings):
    """그날을 덮는 회의일, 없으면 None."""
    for m in meetings or ():
        start, end = blackout_window(m)
        if start <= day <= end:
            return m
    return None


def event(key, kind, name_ko, day, *, time_et=None, status='scheduled',
           source='', assets=(), watch=''):
    return {'key': key, 'kind': kind, 'name_ko': name_ko,
            'date': day.isoformat(), 'time_et': time_et,
            'time_kst': _fmt_kst(day, time_et), 'status': status,
            'source': source, 'assets': list(assets), 'watch': watch}


def expiry_events(start, end):
    """구간 안의 지수 만기. 출처가 필요 없다 — 날짜 규칙이 전부다."""
    out, year, month = [], start.year, start.month
    while (year, month) <= (end.year, end.month):
        day = monthly_expiry(year, month)
        if start <= day <= end:
            quad = day in quad_witching(year)
            out.append(event(
                f'expiry-{day:%Y%m}', 'expiry',
                '쿼드러플 위칭(분기 만기)' if quad else '지수 옵션 만기', day,
                status='confirmed', source='셋째 금요일 규칙',
                assets=['주식'],
                watch='만기 주간의 거래량과 되돌림' if quad else '만기 당일 수급'))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def fomc_events(meetings, start, end):
    """구간 안의 FOMC. **주어진 표에서만** 만든다."""
    out = []
    for m in sorted(meetings or ()):
        if not start <= m <= end:
            continue
        watch = '성명 문구 변화, 30분 뒤 기자회견'
        if m.month in SEP_MONTHS:
            watch += ', 경제전망요약(점도표)'
        out.append(event(f'fomc-{m:%Y%m%d}', 'fomc', 'FOMC 성명', m,
                          time_et=FOMC_TIME_ET, status='confirmed',
                          source='연준 공표 일정', assets=['금리', '달러', '주식'],
                          watch=watch))
    return out


def build(report_date, *, meetings=(), horizon_days=HORIZON_DAYS, extra=(),
          missing=(), auctions=()):
    """-> calendar.json 본문.

    `extra` 는 수집 단계(`upcoming.py`)가 붙이는 경제지표·입찰 일정이고, `missing` 은
    그 단계가 실패한 재료의 이름이다. 못 받은 것은 없는 대로 남긴다 — 비-코어 계약이
    이 파이프라인 전체에서 같은 모양이다.

    `auctions` 는 **일정이 아니라 직전 입찰의 수요**다. 채권 섹션이 수급을 원인 후보로
    들 때 쓰라고 같은 파일에 싣는다.
    """
    start = report_date + dt.timedelta(days=1)
    end = report_date + dt.timedelta(days=horizon_days)

    meetings = sorted(meetings or ())
    # 마지막 회의일이 이미 지났으면 그 표는 낡은 것이다. 낡은 표를 조용히 쓰면 다음
    # 회의가 없는 것처럼 보이고, 그게 블랙아웃 판정까지 틀리게 만든다.
    fresh = bool(meetings) and meetings[-1] >= report_date
    gaps = list(missing) + ([] if fresh else ['fomc'])

    events = expiry_events(start, end)
    if fresh:
        events += fomc_events(meetings, start, end)
    events += list(extra)
    events.sort(key=lambda e: (e['date'], e.get('time_et') or '', e['key']))

    covering = in_blackout(report_date, meetings) if fresh else None
    blackout = {'active': covering is not None,
                'meeting': covering.isoformat() if covering else None,
                'until': blackout_window(covering)[1].isoformat() if covering else None}

    return {'report_date': report_date.isoformat(),
            'generated': dt.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
            'horizon_days': horizon_days, 'events': events,
            'recent_auctions': list(auctions),
            'blackout': blackout, 'missing': sorted(set(gaps)), 'complete': not gaps}
