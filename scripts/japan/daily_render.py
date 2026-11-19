"""일본 일간 — 절 순서·표·조립 (2026-10-27).

작성자는 절 산문만 쓰고 표는 여기서 만든다. 본문 계약: 머리 카드(h1 하나) 뒤에 `data-section` 절을
`order(event_day)` 순서로, 표 자리에 `<!--T:이름-->`. 순서는 코드가 정한다 — 그날 major 결과 공표가
있으면 매크로 절이 전략 코멘트 바로 다음으로 온다(사용자 결정: A 배치 + C 규칙).
값마다 기준일이 다르다 — JGB 는 직전 세션, 콜은 BOJ 최신 관측일, 엔은 16:30 JST 컷. 표가 그 날짜를 단다.
"""
import re
from datetime import date

from japan import daily_calendar as CAL
from japan import daily_facts as FX
from japan import daily_rates as RT
from scripts.common import post_shell as S
from scripts.common.hidden import VOID            # 빈 요소 목록은 숨김 판정 공용 모듈과 하나다
from scripts.common import signcolor
from us.weekly_insight import _c, _e, _table

SECTIONS = ('comment', 'today', 'equity', 'bonds', 'yen', 'macro', 'news', 'next')
TITLES = {'comment': '전략 코멘트', 'today': '오늘의 장', 'equity': '주식', 'bonds': '채권',
          'yen': '엔화', 'macro': '매크로', 'news': '일본 경제 뉴스', 'next': '향후 확인 일정'}
# 텔레그램 한 채널의 일본 관련 메모(2026-11-15) — 실을 것이 있는 날만, 뉴스 절 바로 뒤에 하나.
# 모양·내용은 common/telegram_gate.py (layout 'jp') 가 본다. 제목은 그쪽 NEWS_TITLE 과 같다.
OPTIONAL = ('views',)
TITLES['views'] = '증권사 견해·시장 의견'
_VIEWS_OPEN = re.compile(r'<section\b[^>]*\bdata-section="views"[^>]*>')
PLACEHOLDERS = {'equity': ('indices', 'sectors'), 'bonds': ('jgb',), 'yen': ('fx',),
                'macro': ('macro',), 'next': ('next',)}
BRAND = 'Japan Market Daily'
BOJ_CREDIT = ('This service uses the API provided by the "Bank of Japan Time-Series Data Search." '
              'The Bank of Japan does not guarantee the content of the service.')
WEEKLY_FX_NOTE = '주간 보고서의 달러/엔은 뉴욕 16:00 기준이라 값이 다르다.'

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S)


def order(event_days):
    if not event_days:
        return SECTIONS
    rest = tuple(s for s in SECTIONS if s not in ('comment', 'macro'))
    return ('comment', 'macro') + rest


def day_ko(iso):
    """'2026-10-23' → '10월 23일'. 월간 기간('2026-09')은 '9월'."""
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', iso or ''):
        d = date.fromisoformat(iso)
        return f'{d.month}월 {d.day}일'
    if re.fullmatch(r'\d{4}-\d{2}', iso or ''):
        return f'{int(iso[5:])}월'
    return iso or '—'


def _num(v, digits=2, unit=''):
    return '—' if v is None else f'{v:,.{digits}f}{unit}'


def _t_indices(d):
    nk, tp = d['indices']['nikkei'], d['indices']['topix_etf']
    rows = [['닛케이 225', _num(nk.get('value')), _c(nk.get('chg_pct'), '%')],
            [_e(tp.get('label') or 'TOPIX ETF(1306)'), _num(tp.get('value'), 1), _c(tp.get('chg_pct'), '%')]]
    return _table(['', f'{day_ko(d["session"])} 종가', f'{day_ko(d["prev_session"])} 대비'], rows,
                  '닛케이 225 는 일본경제신문사 공표 종가. TOPIX 는 상장 ETF(1306)로 본다 — 지수 자체가 아니다.')


def _t_sectors(d):
    ok = [s for s in d.get('sectors') or [] if s.get('ok') and s.get('value') is not None]
    ok.sort(key=lambda s: -(s.get('chg_pct') if s.get('chg_pct') is not None else -999))
    rows = [[_e(s['name_ko']), _c(s.get('chg_pct'), '%')] for s in ok]
    missing = len(d.get('sectors') or []) - len(ok)
    cap = 'TOPIX 17개 업종 ETF(1617~1633) 종가 기준.'
    if missing:
        cap += f' 세션 종가를 확인하지 못한 {missing}개 업종은 뺐다.'
    if not rows:
        return f'<p class="caption">{cap}</p>'
    return _table(['업종', f'{day_ko(d["prev_session"])} 대비'], rows, cap)


def jgb_source(d):
    """실린 JGB 행들의 출처 — 전부 'naver' 면 'naver', 아니면 'mof'(옛 스냅샷은 `source` 가 없다)."""
    srcs = {r.get('source') for r in (d.get('jgb') or {}).values() if isinstance(r, dict)}
    return 'naver' if srcs == {'naver'} else 'mof'


JGB_CAPTION = {
    'mof': 'JGB 는 재무성 커브(다음 영업일 게시), 콜은 일본은행 시계열 — 오늘 값이 아니다. 금리 상승은 빨강.',
    'naver': ('JGB 는 네이버증권 지표물 도쿄 마감 호가(재무성 커브와 정의가 달라 수 bp 다를 수 있다), '
              '콜은 일본은행 시계열 최신 관측일. 금리 상승은 빨강.'),
}
JGB_CREDIT = {'mof': 'JGB 는 재무성', 'naver': 'JGB 는 네이버증권'}


def _t_jgb(d):
    rows = []
    for t in ('2Y', '5Y', '10Y', '30Y'):
        r = (d.get('jgb') or {}).get(t)
        if not r:
            continue
        rows.append([f'JGB {t[:-1]}년', _num(r['value'], 3, '%'),
                     _c(r.get('chg_bp'), 'bp', 1, invert=True), _e(day_ko(r['period']))])
    call = d.get('call_rate')
    if call:
        rows.append(['무담보 콜 O/N', _num(call['value'], 3, '%'), '—', _e(day_ko(call['period']))])
    if not rows:
        return '<p class="caption">JGB·콜금리 기준 값을 확인하지 못했다.</p>'
    return _table(['', '금리', '변화', '기준일'], rows, JGB_CAPTION[jgb_source(d)])


def _t_fx(d):
    fx = d.get('fx') or {}
    rows = []
    for key in ('usdjpy', 'eurjpy', 'krw_per_100jpy'):
        r = fx.get(key)
        if r:
            rows.append([_e(r['label']), _num(r['value'], 2), _c(r.get('chg_pct'), '%')])
    if not rows:
        return '<p class="caption">16:30 JST 환율을 확인하지 못했다.</p>'
    return _table(['', f'{day_ko(d["session"])} 16:30 JST', f'{day_ko(d["prev_session"])} 같은 시각 대비'],
                  rows, f'5분봉 16:30 JST 종가. {WEEKLY_FX_NOTE}')


def _t_macro(d):
    rows, sched = [], False
    for m in d.get('macro') or []:
        if m['status'] == 'released':
            rows.append([_e(m['name_ko']), _e(day_ko(m['period'])), _num(m['value'], 2),
                         _num(m.get('prev_value'), 2), _c(m.get('yoy'), '%', 1)])
        elif m['status'] == 'pending':
            rows.append([_e(m['name_ko']), '—', '발표 예정·시계열 미반영', '—', '—'])
        elif m['status'] == 'fetch_failed':
            rows.append([_e(m['name_ko']), '—', '시계열 조회 실패', '—', '—'])
        else:
            rows.append([_e(m['name_ko']), '—', '일정', '—', '—'])
            sched = True
    if not rows:
        # 빈 표는 「일본에 발표가 없었다」가 아니다 — 행은 확인해 둔 일정표(calendar_daily.json)의 오늘 release 행에서만
        # 나오고, BOJ 조회가 실패해도 그 행은 남는다(collect_japan_daily._macro). 그 범위를 넘어 단정하면 내각부
        # 경기동향지수가 나온 날 본문과 모순된다(2026-11-09 발행본). 옛 수집기는 조회 실패 때 행을 비웠으므로
        # 일정표에 오늘 발표가 있는데 행이 없으면 「없다」고 쓰지 않는다(옛 스냅샷 재조립).
        if any(e.get('kind') == 'release' for e in (d.get('calendar') or {}).get('today') or []):
            return '<p class="caption">오늘 일정표에 잡힌 발표를 이 표에 싣지 못했다.</p>'
        return '<p class="caption">확인해 둔 발표 일정표에 오늘 잡힌 일본 지표가 없다.</p>'
    # 일정 행(series 없음)은 총무성 CPI·내각부 GDP 처럼 일본은행 밖 발표일 수 있다 — 값의 출처와 일정의 출처를 가른다
    note = ('값은 일본은행 시계열, 「일정」 행은 각 기관 공표 일정 기준.' if sched else '일본은행 시계열 기준.')
    return _table(['지표', '기간', '값', '직전', '전년 대비'], rows, note + ' 시장 예상치는 싣지 않는다.')


def _t_next(d):
    rows = [[_e(day_ko(e['date'])), _e(e.get('time_jst') or '—'), _e(e['name_ko'])]
            for e in (d.get('calendar') or {}).get('upcoming') or []]
    if not rows:
        # 「일정이 없다」고 단정하지 않는다 — 일정표는 원출처에서 확인한 것만 담고 결산·부처 발표는 빠질 수 있다.
        # 본문이 13일 결산을 적은 바로 뒤에 「일정이 없다」가 붙어 앞뒤가 어긋났다(2026-11-12 발행본).
        return '<p class="caption">확인해 둔 발표 일정표에는 앞으로 2주 안에 잡힌 일본 지표가 없다.</p>'
    return _table(['날짜', '시각(JST)', '일정'], rows, '원출처 공표 일정 기준.')


def render_tables(d):
    if FX.is_v2(d):
        return {'indices': _t_indices_v2(d), 'sectors': _t_sectors_v2(d), 'jgb': _t_jgb_v2(d), 'fx': _t_fx(d),
                'macro': _t_macro_v2(d), 'next': _t_next_v2(d)}
    return {'indices': _t_indices(d), 'sectors': _t_sectors(d), 'jgb': _t_jgb(d), 'fx': _t_fx(d),
            'macro': _t_macro(d), 'next': _t_next(d)}


# ── 2판(`schema: 2`) 표 — TOPIX·업종·스프레드는 `facts` 에서만 (2026-11-19) ─────────────
# 옛 스냅샷(schema 없음)은 위의 옛 함수 그대로다 — 다시 조립해도 바이트가 같다(시험이 고정한다).
# 부호와 색은 표시값이 아니라 `direction`(반올림 전 차의 부호)을 따른다 — −0.00% 도 내린 것이다(13회차).

def _cd(value, direction, unit, digits, invert=False, color=True):
    if value is None:
        return '—'
    mark = '+' if direction and direction > 0 else '-' if direction and direction < 0 else ''
    text = f'{mark}{abs(value):.{digits}f}{unit}'
    if not color or not direction:
        return text
    cls = 'pos' if (direction > 0) != invert else 'neg'
    return f'<span class="{cls}">{text}</span>'


def _t_indices_v2(d):
    nk = d['indices']['nikkei']
    it = FX.items(d)
    ok = FX.blocks(d).get('topix') == 'current'
    close, chg = it.get('topix.close') or {}, it.get('topix.chg_pct') or {}
    rows = [['닛케이 225', _num(nk.get('value')), _c(nk.get('chg_pct'), '%')],
            ['TOPIX', _num(close.get('value')) if ok else '—',
             _cd(chg.get('value'), chg.get('direction'), '%', 2) if ok else '—']]
    return _table(['', f'{day_ko(d["session"])} 종가', f'{day_ko(d["prev_session"])} 대비'], rows,
                  '닛케이 225 는 일본경제신문사, TOPIX 는 일본거래소그룹(JPX) 공표 종가(네이버증권과 대조).')


def _t_sectors_v2(d):
    try:
        rows = FX.sector_rows(d)
    except (KeyError, TypeError):
        rows = []          # 블록은 current 인데 항목이 빠진 스냅샷 — 생성 문장도 「확인하지 못해」로 간다
    if not rows:
        return ''          # 업종 블록이 무효면 표를 싣지 않는다 — 생성 문장이 「확인하지 못해 싣지 않는다」를 말한다
    body = [[_e(r['name_ko']), _num(r['close']), _cd(r['chg_pct'], r['direction'], '%', 2)] for r in rows]
    return _table(['업종', f'{day_ko(d["session"])} 종가', f'{day_ko(d["prev_session"])} 대비'], body,
                  'TOPIX-17 업종지수(일본거래소그룹 공표) 기준.')


def _t_jgb_v2(d):
    rows = []
    for t in RT.TENORS:
        r = (d.get('jgb') or {}).get(t)
        if not r:
            continue
        rows.append([f'JGB {t[:-1]}년', _num(r['value'], 3, '%'),
                     _c(r.get('chg_bp'), 'bp', 1, invert=True), _e(day_ko(r['period']))])
    call = d.get('call_rate')
    if call:
        rows.append(['무담보 콜 O/N', _num(call['value'], 3, '%'), '—', _e(day_ko(call['period']))])
    if not rows:
        return '<p class="caption">JGB·콜금리 기준 값을 확인하지 못했다.</p>'
    it, b = FX.items(d), FX.blocks(d).get('curve') or {}
    for seg, _, _ in RT.SEGMENTS:
        lvl, chg = it.get(f'curve.{seg}.spread_bp') or {}, it.get(f'curve.{seg}.chg_bp') or {}
        st = b.get(seg, 'invalid')
        if st == 'invalid' or lvl.get('value') is None:
            rows.append([f'{RT.SEGMENT_KO[seg]} 스프레드', '—', '—', '—'])
            continue
        move = _cd(chg.get('value'), chg.get('direction'), 'bp', 1, color=False) if st == 'current' else '—'
        rows.append([f'{RT.SEGMENT_KO[seg]} 스프레드', f'{lvl["value"]:.1f}bp', move, _e(day_ko(lvl['observation_date']))])
    return _table(['', '금리', '변화', '기준일'], rows, JGB_CAPTION[jgb_source(d)])


def _missing_caption(names, ahead=False):
    # 오늘·앞날 캡션은 글자가 달라야 한다 — 게이트가 코드 표 조각마다 「정확히 한 번」 을 센다
    head = '앞으로 2주 발표 일정표 미확인 계열' if ahead else '발표 일정표 미확인 계열'
    return f'{head}: {"·".join(names)}.' if names else ''


def _join(*parts):
    return ' '.join(p for p in parts if p)


def _t_macro_v2(d):
    """부재는 코드 캡션만 말한다(§7): 그날 행이 0 이고 미확인 계열이 없을 때만 「없다」."""
    cal = d.get('calendar') or {}
    miss = (cal.get('coverage') or {}).get('today_missing')
    miss = list(CAL.REQUIRED_NAMES.values()) if miss is None else miss
    if d.get('macro'):
        table = _t_macro(d)            # 행이 있으면 옛 표 그대로 — 캡션 끝에 미확인 계열만 덧붙인다
        head, sep, cap = table.rpartition('<p class="caption">')
        return head + sep + _join(cap[:-len('</p>')], _missing_caption(miss)) + '</p>'
    today = cal.get('today') or []
    meetings = [e for e in today if e.get('kind') == 'meeting']
    if any(e.get('kind') == 'release' for e in today):
        text = _join('오늘 일정표에 잡힌 발표를 이 표에 싣지 못했다.', _missing_caption(miss))
    elif meetings:
        text = _join('오늘 일정표에는 회의 일정만 있다: ' + '·'.join(_e(e['name_ko']) for e in meetings) + '.',
                     _missing_caption(miss))
    elif miss:
        text = _missing_caption(miss)
    else:
        text = f'확인해 둔 발표 일정표(필수 {len(CAL.REQUIRED)}개 계열)에 오늘 잡힌 일본 지표가 없다.'
    return f'<p class="caption">{text}</p>'


def _t_next_v2(d):
    cal = d.get('calendar') or {}
    miss = (cal.get('coverage') or {}).get('upcoming_missing')
    miss = list(CAL.REQUIRED_NAMES.values()) if miss is None else miss
    rows = [[_e(day_ko(e['date'])), _e(e.get('time_jst') or '—'), _e(e['name_ko'])] for e in cal.get('upcoming') or []]
    if rows:
        return _table(['날짜', '시각(JST)', '일정'], rows, _join('원출처 공표 일정 기준.', _missing_caption(miss, True)))
    if miss:
        return f'<p class="caption">{_missing_caption(miss, True)}</p>'
    return (f'<p class="caption">확인해 둔 발표 일정표(필수 {len(CAL.REQUIRED)}개 계열)에는 앞으로 2주 안에 잡힌 '
            '일본 지표가 없다.</p>')


# ── 구조(2판) — 생성 요소를 넣는 자리를 조립기가 통제한다(11·12회차) ─────────────────────────
GEN_PLACEHOLDERS = {'equity': ('topix', 'sectors'), 'bonds': ('curve',)}
_TOKEN = re.compile(r'<!--.*?-->|<(/?)([a-zA-Z][\w-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)>', re.S)
_RAW = re.compile(r'(?is)<(script|style)\b')


def section_tag_re(name):
    """생성 요소·코드 표의 부모로 허용하는 절 여는 태그. 조립(`assemble`)과 조판이 붙이는 `id="read-N"` 만 허용."""
    return re.compile(r'<section(?: id="read-\d+")? class="card" data-section="' + re.escape(name)
                      + r'"(?: id="read-\d+")?>')


def walk(html):
    """(종류, 이름, 시작, 끝, 부모 여는 태그들) — 종류: open/close/comment/text. script·style 안의 글은 건너뛴다.
    주석은 `<!--` 부터 처음 나오는 `-->` 까지 한 토큰이다 — 그 안의 태그·자리표시자는 원소가 아니다."""
    stack, pos = [], 0
    while True:
        m = _TOKEN.search(html, pos)
        if not m:
            break
        if m.start() > pos and html[pos:m.start()].strip():
            yield 'text', None, pos, m.start(), tuple(stack)
        pos = m.end()
        tok = m.group(0)
        if tok.startswith('<!--'):
            yield 'comment', None, m.start(), m.end(), tuple(stack)
            continue
        closing, name = m.group(1), m.group(2).lower()
        if closing:
            idx = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == name), None)
            if idx is not None:
                del stack[idx:]
            yield 'close', name, m.start(), m.end(), tuple(stack)
            continue
        yield 'open', name, m.start(), m.end(), tuple(stack)
        if name in ('script', 'style'):
            end = re.compile(rf'(?i)</{name}\s*>').search(html, pos)
            pos = end.start() if end else len(html)
            continue
        # 브라우저와 같은 규칙: `/>` 는 빈 요소(VOID)에만 뜻이 있다. `<details/>` 는 닫히지 않은 <details> 다
        # (codex 구현 검토 1회 #5 — `/>` 를 닫힘으로 읽으면 뒤의 생성 문장이 절의 바로 아래로 판정됐다)
        if name not in VOID:
            stack.append((name, tok))
    if html[pos:].strip():
        yield 'text', None, pos, len(html), tuple(stack)


def open_tokens(html):
    """{실제 여는 태그의 시작 위치: 부모 여는 태그 글자 | None}. 주석·script 안의 「태그」는 들지 않는다."""
    return {start: (stack[-1][1] if stack else None) for kind, _, start, _, stack in walk(html) if kind == 'open'}


def validate_v2(body):
    """2판 본문의 구조 — 자리표시자는 그 절 <section> 의 바로 아래 자식, 맨 바깥은 <section> 만,
    숨기는 속성·style·script·data-gen 금지(11회차 (b)2·12회차). 오류 목록."""
    errs = []
    if re.search(r'data-gen', body, re.I):
        errs.append('본문에 data-gen 이 있다 — 생성 문장은 조립이 넣는다(<!--G:이름--> 자리만 둔다)')
    if _RAW.search(body):
        errs.append('본문에 <style>·<script> 가 있다')
    for m in _TOKEN.finditer(body):
        if m.group(0).startswith('<!--') or m.group(1):
            continue
        attrs = m.group(3)
        if re.search(r'(?i)(?:^|\s)hidden\b', attrs):
            errs.append(f'본문의 <{m.group(2)}> 에 hidden 속성이 있다 — 독자에게 안 보이는 글은 쓰지 않는다')
        if re.search(r'(?i)\bstyle\s*=', attrs):
            errs.append(f'본문의 <{m.group(2)}> 에 style= 가 있다 — 모양은 조립과 조판이 정한다')
    for kind, name, start, end, stack in walk(body):
        if stack:
            continue
        if kind == 'text':
            errs.append(f'절 밖 맨 바깥에 글이 있다: 「{_plain_text(body[start:end])[:30]}」')
        elif kind == 'open' and name != 'section':
            errs.append(f'본문의 맨 바깥에 <{name}> 가 있다 — 머리 카드와 절 <section> 만 나열한다')
    wanted = {}
    for sec, names in GEN_PLACEHOLDERS.items():
        for n in names:
            wanted[f'<!--G:{n}-->'] = sec
    for sec, names in PLACEHOLDERS.items():
        for n in names:
            wanted[f'<!--T:{n}-->'] = sec
    comments = [(body[a:b], stack) for kind, _, a, b, stack in walk(body) if kind == 'comment']
    for tag, sec in wanted.items():
        n = body.count(tag)
        if n != 1:
            errs.append(f'{tag} 가 {n}번 있다 — 한 번, {sec} 절 바로 아래에 둔다')
            continue
        own = [stack for text, stack in comments if text == tag]
        if len(own) != 1:
            errs.append(f'{tag} 가 다른 주석 안에 있다 — 주석 하나로 그대로 둔다(독자에게 안 보이게 된다)')
            continue
        parent, depth = (own[0][-1][1] if own[0] else None), len(own[0])
        if depth != 1 or not parent or not section_tag_re(sec).fullmatch(parent):
            errs.append(f'{tag} 는 <section class="card" data-section="{sec}"> 의 바로 아래 자식이어야 한다'
                        f'(지금 부모 {parent or "없음"})')
    return list(dict.fromkeys(errs))


def _plain_text(fragment):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment)).strip()


def validate_body(body, want, schema=None):
    errs = []
    low = body.lower()
    for tag in ('<!doctype', '<html', '<head', '<body'):
        if tag in low:
            errs.append(f'본문에 {tag}> 가 있다 — 문서 껍데기는 조립이 만든다')
    if len(re.findall(r'<h1\b', body)) != 1:
        errs.append('<h1> 은 머리 카드에 하나만 둔다')
    if re.search(r'<table\b', body, re.I):
        errs.append('본문에 표(<table>)가 있다 — 표는 조립이 스냅샷으로 만든다')
    found = _SEC.findall(body)
    names = [n for n, _ in found]
    for s in SECTIONS:
        if names.count(s) != 1:
            errs.append(f'data-section="{s}" 절이 {names.count(s)}번 있다 — 한 번')
    if [n for n in names if n in SECTIONS] != list(want):
        errs.append(f'절 순서가 다르다: {" → ".join(names)} (기대 {" → ".join(want)})')
    if names.count('views') > 1:
        errs.append(f'data-section="views" 절이 {names.count("views")}번 있다 — 실을 메모가 있는 날만 한 번')
    elif 'views' in names:
        i = names.index('views')
        if i == 0 or names[i - 1] != 'news':
            errs.append('data-section="views"(증권사 견해·시장 의견) 절은 일본 경제 뉴스 절 바로 뒤에 둔다')
        if not all('data-tg-section' in m.group(0) for m in _VIEWS_OPEN.finditer(body)):
            errs.append('data-section="views" 절에 data-tg-section 표식이 없다 — '
                        '<section class="card" data-section="views" data-tg-section>')
    inner = dict(found)
    for sec, phs in PLACEHOLDERS.items():
        for ph in phs:
            tag = f'<!--T:{ph}-->'
            n = body.count(tag)
            if n != 1:
                errs.append(f'{tag} 가 {n}번 있다 — 한 번, {sec} 절 안에 둔다')
            elif sec in inner and tag not in inner[sec]:
                errs.append(f'{tag} 가 {sec} 절 밖에 있다')
    if schema == FX.SCHEMA:
        errs += [e for e in validate_v2(body) if e not in errs]
    return errs


def _credits(d):
    if FX.is_v2(d):
        return (f'닛케이 225 종가는 일본경제신문사, TOPIX·업종지수는 일본거래소그룹(JPX), {JGB_CREDIT[jgb_source(d)]}, '
                '콜금리·지표는 일본은행, 종목·환율은 거래소 체결가(yfinance) 기준이다.')
    return (f'닛케이 225 종가는 일본경제신문사, {JGB_CREDIT[jgb_source(d)]}, 콜금리·지표는 일본은행, '
            '업종·종목·환율은 거래소 체결가(yfinance) 기준이다.')


def assemble(body, meta, d):
    for name, frag in render_tables(d).items():
        body = body.replace(f'<!--T:{name}-->', frag)
    if FX.is_v2(d):
        for name, frag in FX.generated(d).items():
            body = body.replace(f'<!--G:{name}-->', frag)
    n = 0

    def _id(m):
        nonlocal n
        n += 1
        return m.group(0).replace('<section', f'<section id="read-{n}"', 1)

    body = _SEC.sub(_id, body)
    s = d['session']
    url = f'https://fdo2a.github.io/japan/daily/{s}.html'
    title, summary = S.escape(meta['title'].strip()), S.escape(meta['summary'].strip())
    wd = S.WEEKDAYS[date.fromisoformat(s).weekday()]
    back = S.crumbs([('일본 시장', '../index.html'), ('일간', None)])
    return (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{title}</title>\n<meta name="description" content="{summary}">\n'
        f'<link rel="canonical" href="{url}">\n<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{BRAND} — {s}">\n'
        f'<meta property="og:url" content="{url}">\n<meta property="og:description" content="{summary}">\n'
        f'{S.FONT_LINK}\n<style>\n{S.css("us")}{signcolor.CSS}\n</style>\n{S.ANALYTICS}\n</head>\n'
        '<body data-layout="prose" data-register="da">\n'
        f'<div class="topbar"><span class="brand">{BRAND}</span>'
        f'<span class="date">일본 시장 마감 · {day_ko(s)}({wd})</span></div>\n{back}\n'
        f'<div class="container">\n{body}\n'
        f'<footer class="disclaimer"><p>{_credits(d)} 투자 판단의 참고 자료이며 투자 권유가 아니다.</p>'
        f'<p lang="en">{_e(BOJ_CREDIT)}</p></footer>\n'
        '</div>\n</body>\n</html>\n')
