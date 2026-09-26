"""기간을 한국어 날짜로 — 「2026-W39」만으로는 언제인지 알 수 없다(2026-09-26 사용자 지시).

    range_ko('2026-09-21', '2026-09-25') -> '2026년 9월 21일~25일'
    range_ko('2026-09-28', '2026-10-02') -> '2026년 9월 28일~10월 2일'
    range_ko('2026-12-28', '2027-01-01') -> '2026년 12월 28일~2027년 1월 1일'
"""
from datetime import date


def range_ko(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    head = f'{a.year}년 {a.month}월 {a.day}일'
    if a.year != b.year:
        return f'{head}~{b.year}년 {b.month}월 {b.day}일'
    if a.month != b.month:
        return f'{head}~{b.month}월 {b.day}일'
    return f'{head}~{b.day}일'
