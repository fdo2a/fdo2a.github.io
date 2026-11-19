"""「오늘의 장」 발행 게이트.

두 가지를 막는다. 하나는 **침묵** — 유럽이 미국과 엇갈린 날 그 사실을 안 쓰는
것은 가격 맥락의 관계 뒤집힘·§8의 해소 문단과 같은 급의 누락이다. 다른 하나는
**채우기** — 평범한 날 「오늘은 폭이 보통이었습니다」를 한 줄 넣는 것. 그래서
참여도는 양방향으로 본다: 켜진 날 빠뜨려도 실패, 안 켜진 날 언급해도 실패.

시장별로 다른 것은 어느 필드를 보느냐뿐이라 HTML 쪽 검사는 US·KR이 공유한다.
`style.py`·`readability.py`가 이미 그렇게 쓰인다.
"""

import datetime as dt
import math
import re
from html import unescape as _unescape   # 이 파일의 함수들은 `html` 을 인자 이름으로 쓴다

from .section import locate_section
from .session import band_of
from common.numbers import TAG_RE, numbers_split_by_tags

SECTION_TITLE = '오늘의 장'

MARKERS = ('global', 'preopen', 'tape', 'causal')

PARTICIPATION_LABELS = ('고르게 오름', '소수가 끌어올림', '고르게 내림', '소수가 끌어내림')

# 이 값의 이름이 아닌 것들. 등락 종목 수를 세지 않으므로 폭이라 부를 수 없다.
MISNOMERS = ('상승 종목 비율', '등락 종목 수', '시장 폭', 'breadth')

# 발행본에 나오면 안 되는 내부 표기. 영문 토큰은 단어 경계로 본다 — 「session」이
# 한국어 본문 한복판에서 부분일치로 걸리는 일을 막는다.
INTERNAL = ('global_close', 'gap_pp', 'gap_pct', 'close_position', 'kr_session',
            'us_prev', 'asia_peers', 'participation', 'data-session',
            'breadth_proxy', 'session', 'tape')

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


def _finite(x):
    return isinstance(x, (int, float)) and x == x


def _number(x):
    """유한한 수만. `_finite` 는 무한대와 bool 을 통과시킨다."""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(x)
    except OverflowError:       # float 로 못 옮기는 큰 정수 — 등락률일 수 없다
        return False


def _participation_consistency(par):
    """저장된 참여도 판정값이 함께 저장된 수치와 맞는가.

    수집 블록의 자기 일관성만 본다 — RSP·SPY 원천이 맞는지는 아니다. `spy_pct` 는
    반올림값이라 0.00 이거나 없으면 방향을 다시 낼 수 없다. 그때는 차이의 부호와 맞는
    두 이름 가운데 하나인지만 본다.
    """
    where = '참여도 판정값(수집 자료 market_data.json 의 session — 글을 고쳐 맞출 일이 아니다)'
    band, gap, cap = par.get('band'), par.get('gap_pp'), par.get('spy_pct')
    if band not in PARTICIPATION_LABELS + ('중립',):
        return [f'{where}이 정해진 다섯 값이 아니다: {band!r}']
    if not _number(gap):
        return [f'{where}의 차이 수치가 수가 아니다: {gap!r}']
    if cap is not None and not _number(cap):
        return [f'{where}의 시총가중 등락이 수가 아니다: {cap!r}']
    if cap:
        allowed = {band_of(gap, cap)}
    else:
        allowed = {band_of(gap, 1), band_of(gap, -1)}
    if band not in allowed:
        return [f'{where}이 수치와 맞지 않는다: {band} / 차이 {gap:+.2f}%p'
                + ('' if cap is None else f' · 시총가중 {cap:+.2f}%')]
    return []


_PP_UNIT = re.compile(r'\s*(?:[%％]\s*[pP]|[%％]\s*포인트|퍼센트\s*포인트)')


def _has_gap_figure(text, gap):
    """참여도 차이의 **크기**가 %p 단위로 적혔나.

    참여도를 통째로 빼먹은 글을 잡는 자리다 — 옛 검사가 판정 이름으로 보던 것을 수치로
    본다. 부호는 보지 않는다(「0.99%p 높았다」와 「-0.43%p」 둘 다 맞는 문장이다). 수치가
    있다는 것까지만 보고, 그 수치를 푼 말이 맞는지는 보지 않는다.
    """
    text = _unescape(text)              # 「&#48;.95%p」도 화면에는 0.95%p 다
    full = f'{abs(gap):.2f}'
    forms, s = {full}, full
    while s.endswith('0'):              # 0.50 → 0.5, 1.00 → 1.0 → 1
        s = s[:-1]
        forms.add(s.rstrip('.'))
    for form in forms:
        for m in re.finditer(re.escape(form), text):
            i, j = m.start(), m.end()
            if i and (text[i - 1].isdigit() or text[i - 1] == '.'):
                continue                # 더 긴 수의 일부(10.95 안의 0.95)
            if re.search(r'\d[eE][-+−]?$', text[:i]):
                continue                # 지수 표기의 지수 자리(2e-1 의 1)
            if j < len(text) and (text[j].isdigit()
                                  or (text[j] == '.' and text[j + 1:j + 2].isdigit())):
                continue
            if _PP_UNIT.match(text, j):
                return True
    return False


def _particle(word, with_final, without_final):
    """받침에 맞는 조사. 게이트 메시지는 writer가 그대로 읽는다."""
    last = (word or '')[-1:]
    if not last or not ('가' <= last <= '힣'):
        return without_final
    return with_final if (ord(last) - 0xAC00) % 28 else without_final


def _strip_style(html):
    return re.sub(r'(?is)<style\b.*?</style>', ' ', html or '')


def _text(html):
    # 주석·속성값 안의 `>` 까지 한 토큰으로 읽는다 — 정본은 common/numbers.py.
    # 제 정규식을 쓰면 필수 문구를 `<!-- … -->` 안에 숨겨도 본문으로 읽힌다
    # (2026-09-01 codex 검토에서 실증).
    return TAG_RE.sub(' ', html or '')


def _blocks(html):
    out = {}
    for m in re.finditer(r'(?s)<(\w+)[^>]*\bdata-session="([^"]+)"[^>]*>(.*?)</\1>',
                         html or ''):
        out.setdefault(m.group(2), []).append(_text(m.group(3)))
    return {k: ' '.join(v) for k, v in out.items()}


def _has_figure(page, pct):
    """그 수치가 **부호까지 맞게** 본문에 있나.

    부분문자열로만 보면 +0.31을 「-0.31」로 적은 판이 통과한다 — 방향이 뒤집힌
    발행본을 게이트가 승인하는 것이고, 이 레포가 과거 FX 방향·유가 등락률에서
    실제로 겪은 오류다. 더 긴 수치의 일부(-10.79 안의 0.79)도 걸러낸다.
    """
    body = f'{abs(pct):.2f}'
    for m in re.finditer(re.escape(body), page):
        i, j = m.start(), m.end()
        if i and (page[i - 1].isdigit() or page[i - 1] == '.'):
            continue
        if j < len(page) and page[j].isdigit():
            continue
        negative = bool(re.search(r'[-−–]\s*$', page[max(0, i - 2):i]))
        if negative == (pct < 0):
            return True
    return False


def _date_forms(date):
    """ISO와 한국어 표기를 함께 인정한다 — 「8월 21일 기준」은 올바른 문장이다."""
    forms = {str(date)}
    try:
        d = dt.date.fromisoformat(str(date))
    except ValueError:
        return forms
    forms |= {f'{d.month}월 {d.day}일', f'{d.month:02d}월 {d.day:02d}일',
              f'{d.year}년 {d.month}월 {d.day}일'}
    return forms


def _rows(session, market):
    if market == 'kr':
        block = session.get('asia_peers') or {}
        dates = block.get('dates') or {}
        return [{'name': n, 'pct': p, 'date': dates.get(n)}
                for n, p in (block.get('rows') or {}).items()]
    out = []
    for region in ('asia', 'europe'):
        out += ((session.get('global_close') or {}).get(region) or {}).get('rows') or []
    return out


def check(html, session, market='us', price_context=None):
    """위반 문자열 리스트. 빈 리스트 = 발행 가능.

    비-코어: 블록이 없는 데이터셋이면 강제할 것이 없으므로 통과한다.
    """
    if not session:
        return []
    v = []
    body = _strip_style(html or '')
    # 화면에 한 숫자로 보이는데 검사에는 둘로 들어가는 마크업을 원문에서 잡는다.
    for run in numbers_split_by_tags(html or '')[:4]:
        v.append(f'수치 사이에 태그가 끼어 있다({run.strip()[:40]}) — '
                 f'검사를 피해 가므로 허용하지 않는다')
    section = locate_section(body, SECTION_TITLE)
    if not section:
        return [f'「{SECTION_TITLE}」 섹션이 없다 — 표식만 흩어 놓는 것으로는 안 된다']
    blocks = _blocks(section)
    page = _text(body)
    rows = _rows(session, market)

    fut = session.get('futures') or {}
    optional = set()
    if not rows:
        optional.add('global')
    if market == 'us' and not (fut.get('contracts') or fut.get('gap')):
        optional.add('preopen')          # 할 말이 없는 날은 비워도 된다
    par_band = (session.get('participation') or {}).get('band')
    if (market == 'us' and par_band in (None, '중립')
            and not any((session.get('tape') or {}).values())):
        optional.add('tape')

    for key in MARKERS:
        if key in optional:
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
            if not (al and al['label'] == '엇갈림'):
                continue
            # 두 지역이 함께 엇갈린 날, 한쪽만 쓰고 넘어가지 못하게 **같은 문장 안에**
            # 지역 이름과 엇갈림이 함께 있는지 본다.
            named = any('엇갈' in sent and ko in sent
                        for sent in re.split(r'(?<=[.!?])\s+|(?<=다)\s+',
                                             blocks.get('global', '')))
            if not named:
                josa = _particle(ko, '이', '가')
                v.append(f'{ko}{josa} 미국과 엇갈렸는데(평균 {al["avg_pct"]:+.2f}%) '
                         '서술이 없다 — 어긋남은 허용, 침묵은 금지')

        par = session.get('participation')
        if par:
            said = [lab for lab in PARTICIPATION_LABELS if lab in page]
            if par.get('band') == '중립' and said:
                v.append(f'참여도가 중립인데 「{said[0]}」이라 썼다 — 채우기 금지')
            # 판정 이름을 본문에 요구하지 않는다(2026-11-17) — 이름은 내부 값이고 글은 그 뜻을
            # 독자의 말로 쓴다. 기계가 보는 것은 판정값이 제 수치와 맞는지뿐이다. 본문이 판정과
            # 같은 뜻인지는 여기서 보증하지 않는다.
            v += _participation_consistency(par)
            # 판정이 켜진 날 참여도를 통째로 빼먹지 못하게 — 이름 대신 차이 수치가 tape 문단에
            # 있는지 본다(2026-11-18). 옛 글은 그날의 판정 이름으로 이 자리를 채웠으므로 이름도
            # 받는다(다시 검사해도 떨어지지 않게). 있는지만 본다 — 풀이가 맞는지는 아니다.
            band, gap = par.get('band'), par.get('gap_pp')
            if band in PARTICIPATION_LABELS and _number(gap):
                tape = blocks.get('tape', '')
                if not (_has_gap_figure(tape, gap) or band in tape):
                    v.append('참여도 판정이 켜진 날인데 tape 문단에 두 지수의 수익률 차이'
                             f'({abs(gap):.2f}%p)가 없다 — 동일가중과 시총가중 지수의 '
                             '수익률 차이를 %p 로 적는다')

    # 표에 실린 값이 원본과 어긋나면 막는다. 손으로 옮겨 적은 수치는 흔들린다.
    for row in rows:
        if row.get('pct') is None:
            continue
        if not _has_figure(page, row['pct']):
            v.append(f'{row["name"]}의 등락({row["pct"]:+.2f}%)이 본문·표 어디에도 없거나 '
                     '다른 값(부호 포함)으로 적혔다')
        d, rd = row.get('date'), session.get('report_date')
        if (d and rd and _sessions_between(d, rd) >= STALE_SESSIONS
                and not (_date_forms(d) & {f for f in _date_forms(d) if f in page})):
            v.append(f'{row["name"]}의 마감이 {d}로 report_date({rd})보다 이른데 기준일 '
                     '표기가 없다 — 당일 마감인 양 쓰지 않는다')

    vix = ((price_context or {}).get('levels') or {}).get('VIX') or {}
    if _finite(vix.get('value')) and f'{vix["value"]:.2f}' not in page:
        v.append(f'VIX({vix["value"]:.2f})가 표에도 본문에도 없다 — 「오늘의 장」 표에 싣는다')

    for bad in MISNOMERS:
        if bad in page:
            v.append(f'「{bad}」{_particle(bad, "은", "는")} 이 값의 이름이 아니다 — '
                     '동일가중과 시총가중의 수익률 '
                     '차이지 종목 수가 아니다')
    for bad in INTERNAL:
        # 한글 조사가 붙으면(「gap_pp는」) \b가 깨진다 — 경계를 ASCII 기준으로 잡는다.
        if re.search(r'(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])' % re.escape(bad), page):
            v.append(f'내부 표기 「{bad}」가 발행본에 노출됐다')
    if re.search(r'§\s*\d', page):
        v.append('「§N」 표기가 발행본에 있다 — 독자에게는 섹션 번호가 보이지 않는다. '
                 '이름으로 부르거나 주어를 바꿀 것')
    if '[확인필요]' in page:
        v.append('[확인필요] 마커가 남았다 — 없는 것은 지운다')
    return v
