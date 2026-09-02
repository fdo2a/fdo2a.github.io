"""「지금 어디에 서 있나」를 사람이 알아듣는 말로 바꾼다.

`백분위`는 계산에는 맞는 말이지만 읽는 사람에게는 아무 그림도 그려 주지 않는다.
「10년물 4.76%, 99.3 백분위」를 보고 무슨 뜻인지 아는 독자는 이 리포트가 상정한
독자가 아니다(2026-09-02 사용자 지적 — 「그렇게 쓰면 아무도 못 알아들을 것 같다」).

같은 사실을 **세어 볼 수 있는 말**로 옮긴다.

    99.3 백분위 (522거래일)  ->  최근 2년(522거래일) 가운데 이보다 높았던 날은 나흘뿐
    80.0 백분위 (504거래일)  ->  최근 2년(504거래일) 가운데 높은 쪽 20% 안
    41.0 백분위 (504거래일)  ->  최근 2년(504거래일)의 한가운데쯤

가장자리는 **날짜 수**로, 가장자리가 아니면 **상위·하위 몇 %**로 부른다. 백분위 96 을
「높은 쪽 4% 안」이라고만 하면 여전히 손에 안 잡히는데, 「이보다 높았던 날은 20일뿐」은
누구나 센다. 반대로 백분위 80 을 「이보다 높았던 날은 101일」이라고 쓰면 많아 보여서
오히려 신호가 죽는다 — 그래서 두 갈래다.

문장이 인쇄하는 숫자(`days`·`share_pct`)를 **수로도 함께 돌려준다.** 발행 게이트는
데이터 안의 수만 인용 가능한 값으로 치기 때문에, 산문에만 있는 숫자는 창작으로 걸린다
(2026-08-31 채권 게이트 규칙). 말을 바꾸는 김에 숫자를 손으로 적게 만들면 안 된다.

Pure — 수 둘을 받아 dict 하나를 돌려준다.
"""

import math

MIN_SESSIONS_FOR_YEARS = {5: 1260, 3: 756, 2: 504, 1: 252}

# 이보다 짧은 표본으로는 「어디에 서 있다」는 말을 하지 않는다. 2거래일 표본에
# 「한가운데쯤」이라고 쓰면 문장은 성립하는데 아무 뜻도 없다(2026-09-02 codex 검토).
# 값은 `us/price_context.level_percentile` 이 이미 쓰던 하한과 같다.
MIN_SESSIONS = 30

# 이 아래는 「이보다 높았던 날은 며칠뿐」으로 세고, 위는 「높은 쪽 몇 % 안」으로 부른다.
EXTREME = 10.0
MID = 25.0

# 며칠까지는 세는 말로 부른다. 「1일뿐」보다 「하루뿐」이 사람 말이다.
_DAYS_KO = {1: '하루', 2: '이틀', 3: '사흘', 4: '나흘', 5: '닷새',
            6: '엿새', 7: '이레', 8: '여드레', 9: '아흐레', 10: '열흘'}

# (그쪽이었던, 반대쪽이었던, 그쪽인, 반대쪽인)
WORDS = {
    'level': ('높았던', '낮았던', '높은', '낮은'),
    'spread': ('넓었던', '좁았던', '넓은', '좁은'),
}


def window_label(sessions):
    """표본 길이에 걸맞은 기간 이름. 모자라면 「N거래일」로 정직하게 부른다."""
    for years, need in sorted(MIN_SESSIONS_FOR_YEARS.items(), reverse=True):
        if sessions >= need:
            return f'{years}년'
    return f'{sessions}거래일'


def _days_ko(d):
    return _DAYS_KO.get(d, f'{d}일')


# 기간 이름은 아래로 반올림된다 — 497거래일이 「1년」으로 불린다(짧은 표본에 「2년
# 최저」라고 쓰지 않으려는 규칙). 그 이름과 거래일 수를 나란히 인쇄하면 「최근
# 1년(497거래일)」처럼 자기모순이 되므로, 이름이 표본을 이만큼 밑돌면 이름을 버리고
# 거래일 수로만 부른다.
SPAN_TOLERANCE = 1.1


def _span(window, sessions):
    """「최근 2년(522거래일)」. 이름이 표본과 어긋나면 거래일 수로만 부른다."""
    if window.endswith('거래일'):
        return f'최근 {window}'
    nominal = MIN_SESSIONS_FOR_YEARS.get(int(window.rstrip('년')))
    if nominal and sessions > nominal * SPAN_TOLERANCE:
        return f'최근 {sessions}거래일'
    return f'최근 {window}({sessions}거래일)'


def plain(percentile, sessions, window=None, kind='level', above=None, below=None):
    """백분위 -> 사람 말. 못 만들면 None(빈 자리는 비워 두고 문장을 접는다).

    `above`·`below` 는 **원자료에서 직접 센** 날 수다. 주면 그것을 쓰고, 없으면
    백분위에서 되돌린다. 되돌린 값은 반올림된 백분위에서 나오므로 가장자리에서
    거짓말을 한다 — 504개 표본의 최댓값이 백분위 99.9 로 반올림되면 「이보다 높았던
    날이 하루뿐」이 되는데 실제로는 0일이다(2026-09-02 codex 검토). 셀 수 있으면 센다.

    반환: side('high'|'mid'|'low') · days(가장자리일 때만) · share_pct(아닐 때만) ·
    text(그대로 문장에 넣는 조각) · short(기간 이름을 뗀 짧은 꼴 — 표 칸처럼 기간이
    이미 머리글에 적힌 자리) · percentile·sessions(원래 값, 추적용).
    """
    if percentile is None or not sessions:
        return None
    pct = float(percentile)
    n = int(sessions)
    if n < MIN_SESSIONS:
        return None
    win = window or window_label(n)
    span = _span(win, n)
    same, other, same_adj, other_adj = WORDS.get(kind, WORDS['level'])

    out = {'percentile': round(pct, 1), 'sessions': n, 'window': win,
           'days': None, 'share_pct': None}

    if pct >= 100 - EXTREME or pct <= EXTREME:
        high = pct >= 50
        counted = above if high else below
        days = (int(counted) if counted is not None
                else int(round(n * ((100.0 - pct) if high else pct) / 100.0)))
        verb, adj = (same, same_adj) if high else (other, other_adj)
        out['side'] = 'high' if high else 'low'
        out['days'] = days
        out['short'] = (f'통틀어 가장 {adj} 자리' if days == 0
                        else f'이보다 {verb} 날이 {_days_ko(days)}뿐')
        out['text'] = (f'{span}을 통틀어 가장 {adj} 자리' if days == 0
                       else f'{span} 가운데 이보다 {verb} 날이 {_days_ko(days)}뿐')
        return out

    if MID < pct < 100 - MID:
        out['side'] = 'mid'
        out['short'] = '한가운데쯤'
        out['text'] = f'{span}의 한가운데쯤'
        return out

    high = pct >= 50
    counted = above if high else below
    # 「N% 안」은 상한 주장이므로 **올림**한다. 10.4% 를 반올림해 「10% 안」이라 쓰면
    # 실제보다 좁게 말하는 것이다(2026-09-02 codex 검토). 그리고 상위 0.4% 를
    # 「0% 안」이라 쓰면 아무 말도 아니므로 최소 1%.
    raw = (counted / n * 100.0) if counted is not None else (
        (100.0 - pct) if high else pct)
    share = max(1, int(math.ceil(raw - 1e-9)))
    out['side'] = 'high' if high else 'low'
    out['share_pct'] = share
    out['short'] = f'{same_adj if high else other_adj} 쪽 {share}% 안'
    out['text'] = f'{span} 가운데 {out["short"]}'
    return out


# ── 문장에 붙이기 ──────────────────────────────────────────────────────────
#
# 조각이 「…뿐」·「…자리」·「…쯤」·「…% 안」 넷으로 끝나는데, 뒤에 붙는 서술격
# 조사가 받침에 따라 달라진다(자리예요 / 뿐이에요). 렌더러가 매번 손으로 고르면
# 언젠가 「자리이에요」가 지면에 나간다.

_ENDINGS = {'formal': ('입니다', '입니다'),
            'soft': ('예요', '이에요'),
            'and': ('고요', '이고요'),
            'clause': ('고', '이고'),
            'plain': ('다', '이다')}


def _has_batchim(ch):
    if not ('가' <= ch <= '힣'):
        return True  # 숫자·영문 뒤에는 안전한 쪽(받침 있음)으로 붙인다
    return (ord(ch) - 0xAC00) % 28 != 0


def say(plain_dict, form='formal', short=False):
    """`plain()` 결과를 종결까지 붙여 돌려준다. 없으면 빈 문자열."""
    t = ((plain_dict or {}).get('short' if short else 'text')) or ''
    if not t:
        return ''
    vowel, cons = _ENDINGS.get(form, _ENDINGS['formal'])
    return t + (cons if _has_batchim(t[-1]) else vowel)
