"""영업일 세기 — US 매크로 레짐 잠금(`us/macro.py`)이 쓴다.

원래는 승계되는 등급의 이동 규율(트리거 판정·하루 한 단계·N 영업일 잠금) 코어였다.
그 규율을 쓰던 멀티에셋 스탠스(`us/stance.py`)와 채권 뷰가 없어져(채권 2026-09-04 폐기)
2026-11-21 감사에서 `Discipline`·`evaluate_trigger`·`increase_directions` 를 지웠고,
레짐 잠금이 쓰는 영업일 세기만 남았다.
"""

from datetime import date, timedelta


def business_days_inclusive(start, end):
    """Weekdays in [start, end], both ends counted. Never less than 1.

    Holidays are ignored — a lock that runs one session long on a holiday week is a
    far smaller error than the whipsaw this exists to prevent.
    """
    a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if b < a:
        return 1
    n, cur = 0, a
    while cur <= b:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return max(n, 1)
