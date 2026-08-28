"""「오늘의 장」 발행 게이트.

두 가지를 막는다. 하나는 **침묵** — 유럽이 미국과 엇갈린 날 그 사실을 안 쓰는
것은 가격 맥락의 관계 뒤집힘·§8의 해소 문단과 같은 급의 누락이다. 다른 하나는
**채우기** — 평범한 날 「오늘은 폭이 보통이었습니다」를 한 줄 넣는 것. 그래서
참여도는 양방향으로 본다: 켜진 날 빠뜨려도 실패, 안 켜진 날 언급해도 실패.

시장별로 다른 것은 어느 필드를 보느냐뿐이라 HTML 쪽 검사는 US·KR이 공유한다.
`style.py`·`readability.py`가 이미 그렇게 쓰인다.
"""

import datetime as dt
import re

MARKERS = ('global', 'preopen', 'tape', 'causal')

PARTICIPATION_LABELS = ('고르게 오름', '소수가 끌어올림', '고르게 내림', '소수가 끌어내림')

# 이 값의 이름이 아닌 것들. 등락 종목 수를 세지 않으므로 폭이라 부를 수 없다.
MISNOMERS = ('상승 종목 비율', '등락 종목 수', '시장 폭', 'breadth')

INTERNAL = ('global_close', 'gap_pp', 'close_position', 'kr_session',
            'us_prev', 'asia_peers', 'participation', 'data-session')

STALE_SESSIONS = 3


def _sessions_between(a, b):
    """주말만 뺀 거래일 간격. 정확한 휴장 달력이 없으므로 과대평가하지 않는다."""
    try:
        d0, d1 = dt.date.fromisoformat(str(a)), dt.date.fromisoformat(str(b))
    except ValueError:
        return 0
    n, cur = 0, d0
    while cur < d1:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def _particle(word, with_final, without_final):
    """받침에 맞는 조사. 게이트 메시지는 writer가 그대로 읽는다."""
    last = (word or '')[-1:]
    if not last or not ('가' <= last <= '힣'):
        return without_final
    return with_final if (ord(last) - 0xAC00) % 28 else without_final


def _strip_style(html):
    return re.sub(r'(?is)<style\b.*?</style>', ' ', html or '')


def _text(html):
    return re.sub(r'<[^>]+>', ' ', html or '')


def _blocks(html):
    out = {}
    for m in re.finditer(r'(?s)<(\w+)[^>]*\bdata-session="([^"]+)"[^>]*>(.*?)</\1>',
                         html or ''):
        out.setdefault(m.group(2), []).append(_text(m.group(3)))
    return {k: ' '.join(v) for k, v in out.items()}


def _rows(session, market):
    if market == 'kr':
        peers = (session.get('asia_peers') or {}).get('rows') or {}
        return [{'name': n, 'pct': p, 'date': None} for n, p in peers.items()]
    out = []
    for region in ('asia', 'europe'):
        out += ((session.get('global_close') or {}).get(region) or {}).get('rows') or []
    return out


def check(html, session, market='us'):
    """위반 문자열 리스트. 빈 리스트 = 발행 가능.

    비-코어: 블록이 없는 데이터셋이면 강제할 것이 없으므로 통과한다.
    """
    if not session:
        return []
    v = []
    body = _strip_style(html or '')
    blocks = _blocks(body)
    page = _text(body)
    rows = _rows(session, market)

    for key in MARKERS:
        if key == 'global' and not rows:
            continue
        if not blocks.get(key, '').strip():
            v.append(f'「오늘의 장」 {key} 문단이 없거나 비었다 (data-session="{key}")')

    if market == 'kr':
        up = session.get('us_prev') or {}
        lag = up.get('lag_sessions') or 0
        if lag >= 2 and '미국장 기준' not in page:
            v.append(f'전일 미국장이 {lag}거래일 전({up.get("as_of")})인데 기준일 표기가 '
                     '없다 — 「N일 미국장 기준」을 밝힐 것')
    else:
        for region, ko in (('asia', '아시아'), ('europe', '유럽')):
            al = ((session.get('global_close') or {}).get(region) or {}).get('alignment')
            if al and al['label'] == '엇갈림' and '엇갈' not in blocks.get('global', ''):
                josa = _particle(ko, '이', '가')
                v.append(f'{ko}{josa} 미국과 엇갈렸는데(평균 {al["avg_pct"]:+.2f}%) '
                         '서술이 없다 — 어긋남은 허용, 침묵은 금지')

        par = session.get('participation')
        if par:
            said = [lab for lab in PARTICIPATION_LABELS if lab in page]
            if par['band'] == '중립' and said:
                v.append(f'참여도가 중립인데 「{said[0]}」이라 썼다 — 채우기 금지')
            if par['band'] != '중립' and par['band'] not in blocks.get('tape', ''):
                v.append(f'참여도 {par["band"]}({par["gap_pp"]:+.2f}%p)을 서술하지 않았다')

    # 표에 실린 값이 원본과 어긋나면 막는다. 손으로 옮겨 적은 수치는 흔들린다.
    flat = page.replace('+', '')
    for row in rows:
        if row.get('pct') is None:
            continue
        if f'{row["pct"]:.2f}' not in flat:
            v.append(f'{row["name"]}의 등락({row["pct"]:+.2f}%)이 본문·표 어디에도 없거나 '
                     '다른 값으로 적혔다')
        d, rd = row.get('date'), session.get('report_date')
        if d and rd and _sessions_between(d, rd) >= STALE_SESSIONS and str(d) not in page:
            v.append(f'{row["name"]}의 마감이 {d}로 report_date({rd})보다 이른데 기준일 '
                     '표기가 없다 — 당일 마감인 양 쓰지 않는다')

    for bad in MISNOMERS:
        if bad in page:
            v.append(f'「{bad}」{_particle(bad, "은", "는")} 이 값의 이름이 아니다 — '
                     '동일가중과 시총가중의 수익률 '
                     '차이지 종목 수가 아니다')
    for bad in INTERNAL:
        if bad in page:
            v.append(f'내부 표기 「{bad}」가 발행본에 노출됐다')
    if re.search(r'§\s*\d', page):
        v.append('「§N」 표기가 발행본에 있다 — 독자에게는 섹션 번호가 보이지 않는다. '
                 '이름으로 부르거나 주어를 바꿀 것')
    if '[확인필요]' in page:
        v.append('[확인필요] 마커가 남았다 — 없는 것은 지운다')
    return v
