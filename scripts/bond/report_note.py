"""커브 표 캡션을 **실제 행에서** 만든다.

손으로 적은 캡션은 소스가 바뀌는 순간 거짓이 된다 — 2026-09-04 에 발행용 미국
커브를 네이버 종가로 바꿨을 때, 행의 출처 칸은 Naver 인데 캡션은 「5·10·30년은
야후 스팟, 나머지는 FRED」를 그대로 인쇄하고 있었다. 「논거 문장에 수치를 손으로
적지 않는다」와 같은 규율이고, 출처·기준일도 수치와 다르지 않다.
"""

ORDER = ['3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y', '40Y', '50Y']


def _label(tenor):
    """'10Y' -> '10', '3M' -> '3개월' — 나열할 때 단위를 한 번만 쓰기 위해."""
    return tenor[:-1] if tenor.endswith('Y') else tenor.replace('M', '개월')


def source_note(node):
    """' · 전 만기 Naver 2026-09-02 동일 기준일' 같은 캡션 조각. 빈 커브면 빈 문자열."""
    tenors = ((node or {}).get('tenors') or {})
    seen = [(t, r.get('source') or '?', r.get('date') or '')
            for t in ORDER for r in [tenors.get(t)] if r]
    if not seen:
        return ''
    groups = {}
    for tenor, source, date in seen:
        groups.setdefault((source, date), []).append(tenor)
    if len(groups) == 1:
        (source, date), _ = next(iter(groups.items()))
        return f' · 전 만기 {source} {date} 동일 기준일'
    parts = []
    for (source, date), tenors_in in groups.items():
        years = [_label(t) for t in tenors_in]
        suffix = '년은' if tenors_in[-1].endswith('Y') else '은'
        parts.append(f'{"·".join(years)}{suffix} {source} {date}')
    return ' · ' + ', '.join(parts)
