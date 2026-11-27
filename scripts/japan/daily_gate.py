"""일본 일간 발행 게이트. CLI: scripts/check_japan_daily.py (2026-10-27).

전역 숫자 집합만으로는 만기·단위·주체가 바뀐 문장(「JGB 2년 1.5%, 10년 0.75%」, 「1.5엔」)이 통과한다
(codex 설계 검토 #7 재현). 그래서 핵심 값(닛케이·JGB·콜·엔)은 산문에서 `<span data-ref="필드 경로">` 로
스냅샷 필드에 묶고, 값·단위·기준일을 그 필드와 대조한다. 묶지 않은 채 핵심 값을 쓰면 막는다.
나머지 숫자는 스냅샷 집합 검사(주간 게이트와 같은 정규화). 뉴스 절은 뉴스 게이트가 따로 본다.

막는 것: complete 아님·세션/파일명 불일치·코어 값 없음, da 표식 없음, 미완 표식, 절 순서(코드가 정한
`order()`), data-ref 불일치, 기준일이 다른 값의 날짜 누락, 「오늘 콜」·「오늘 JGB」(MOF 폴백일 때), 창작 수치, 예상·컨센서스 비교,
주간 신호 어휘, 「지수 기여」, BOJ 크레디트 누락, 움직인 종목 문단, buy-side.

「증권사 견해·시장 의견」 절(2026-11-15, 텔레그램 한 채널) — 내용은 `common.telegram_gate` (layout 'jp') 가
그 항목의 요약과 대조한다. 여기서는 그 절이 **하나의 유효한 절**일 때에만(`views_node`, 뉴스 절 바로 뒤,
`_SEC` 가 보는 범위와 글자 그대로 같음) 스냅샷 수치 검사·산문 검사에서 그 범위만 뺀다. 쓸 수 있는 파일이
없는데 표식이 있으면 막는다(`tg_news.py strip` 으로 뺀다). 설계: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md
"""
import html as html_mod
import math
import re
import unicodedata

from common import cb_gate as CBG
from common import cb_quote as CBQ
from common import movers as CM
from common import telegram_gate as TG
from common.numbers import strip_comments
from japan import daily_facts as FX
from japan import daily_render as R
from japan.gate import _jo_eok, _text_figures, title_source
from us.news_expand import caption as news_caption
from us.macro_gate import BANNED_LABELS
from us.period_gate import _numbers, _united_numbers
from us.post_check import body_text

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_P = re.compile(r'<p\b(?![^>]*class="caption")([^>]*)>(.*?)</p>', re.S)
_TABLE = re.compile(r'<table\b.*?</table>', re.S)
_TAG = re.compile(r'<[^>]+>')
_REF = re.compile(r'<span\b[^>]*\bdata-ref="([^"]+)"[^>]*>(.*?)</span>', re.S)
_NUM = re.compile(r'-?\d[\d,]*(?:\.\d+)?')
_TIME = re.compile(r'\b\d{1,2}:\d{2}\b')
_UNITS = ('%p', '%', 'bp', '엔', '원', '포인트')
_CONSENSUS = re.compile(r'컨센서스|예상치|시장\s*예상|전망치|예상(?:을|보다|과|에)\s*(?:크게\s*)?(?:상회|하회|웃|밑)')
_SIGNALS = re.compile(r'[AB]\s*경로|신호\s*집계|임계값|인상\s*지속\s*쪽|인상\s*중단\s*쪽')
# 「오늘」 은 **문장 단위**로 본다 — 거리·동사 목록 정규식은 두 차례 검토에서 미탐·오탐을 번갈아 냈다
# (구현 검토 #1·#4, 재검토 #1·#2). 콜은 늘 지난 관측일이라 콜이 든 문장에 「오늘」 금지, JGB·국채가 든 문장은
# 네이버 당일 행(period == session)일 때만 허용 — MOF 폴백 날에는 **문단 단위**(「…2.837%다. 오늘 올랐다.」 처럼
# 주어를 생략한 다음 문장, 재검토 2차 #1). 「JGB와 오늘 증시」 같은 오탐은 감수한다 — 작성자가 문단을 나누면 되지만
# 미탐은 틀린 기준일이 그대로 나간다. 소수점(2.837)은 문장 끝이 아니다. 이 검사는 태그를 공백 없이 지운다
# (`J<span>GB</span>`, 재검토 2차 #2). 남은 한계: 콜은 문장 단위라 주어를 생략한 다음 문장은 못 본다.
# 문장 끝·콜 판정은 origin/main 규칙과 같은 문자로 — 그보다 좁히면(「?」 분리, 「리콜」 제외) 붙여 쓴
# 「무담보콜금리」 처럼 옛 규칙이 막던 입력이 샌다(재검토 5차). 「리콜」 오탐은 옛 규칙과 같다.
_SENT_END = re.compile(r'。|\.(?!\d)')
_CALL = re.compile(r'콜')
_JGB_NAME = re.compile(r'JGB|국채')
# 태그를 공백으로 바꾼 판과 이어 붙인 판을 **둘 다** 검사한다 — 이어 붙이면 `오늘<br>콜금리`·`<wbr>`·`<img>` 가
# 콜 앞 경계를 지우고(재검토 3·4차), 공백으로 바꾸면 `J<span>GB</span>` 가 끊긴다(2차 #2). 태그 목록은 늘 샌다.


def _both_views(inner):
    # 셋째 판 `_plain` 은 origin/main 규칙이 보던 그대로다(엔티티를 풀지 않는다) — 새 검사가 옛 규칙의
    # 상위집합이 되도록: 옛 창 `오늘[^.。]{0,15}이름` 은 마침표가 없으니 한 문장 안에 있다.
    return {html_mod.unescape(re.sub(r'<[^>]+>', sep, inner)) for sep in (' ', '')} | {_plain(inner)}


def _sentences(text):
    return [x for x in _SENT_END.split(text) if x.strip()]
_UNVERIFIED = ('[확인필요]', '확인 필요]', 'TODO', 'TBD', '{{')
_EXTRA_OK = {'225', '17', '1617', '1633', '1306'}   # 지수 이름·업종 ETF 코드 범위(표 캡션)
# 2판 세션: ETF 코드 예외를 끈다(R12) — ETF 를 싣지 않으니 「1306」「1617」 은 창작 수치다
_EXTRA_OK_V2 = {'225', '17'}


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


_TITLE_SPAN = re.compile(r'<tl-s>([^<]*)</tl-s>')


def _plain(fragment):
    # 제목 문장 원소 `<tl-s>`(readability v6)는 글자 사이에 공백을 넣지 않는다 — 「받아…외국인」.
    return re.sub(r'\s+', ' ', _TAG.sub(' ', _TITLE_SPAN.sub(r'\1', fragment))).strip()


def resolve(snap, path):
    cur = snap
    for part in path.split('.'):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _period_of(snap, path):
    head = path.split('.')
    if head[0] == 'jgb' and len(head) > 1:
        return (resolve(snap, f'jgb.{head[1]}') or {}).get('period')
    if head[0] == 'call_rate':
        return (snap.get('call_rate') or {}).get('period')
    if head[0] == 'macro' and len(head) > 1:
        return (resolve(snap, f'macro.{head[1]}') or {}).get('period')
    return snap.get('session')


def _allowed_units(path, snap=None):
    last, head = path.split('.')[-1], path.split('.')[0]
    if last == 'chg_bp':
        return {'bp'}
    if last in ('chg_pct', 'yoy'):
        return {'%'}
    if head in ('jgb', 'call_rate'):
        return {'%'}
    if head == 'fx':
        return {'원'} if 'krw' in path else {'엔'}
    if head == 'indices':
        return {'포인트'}
    if head == 'macro' and snap is not None:
        unit = ((resolve(snap, '.'.join(path.split('.')[:2])) or {}).get('unit') or '').lower()
        if '%' in unit:
            return {'%'}
        if 'yen' in unit:
            return {'엔'}
        return set()          # 지수(CY2020=100 등) — 단위를 붙이지 않는다
    return set(_UNITS)


def _date_forms(period):
    out = {period, R.day_ko(period)}
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', period or ''):
        y, m, d = period.split('-')
        out.add(f'{int(m)}/{int(d)}')
    return out


def _num(text):
    m = _NUM.search((text or '').replace('−', '-'))
    return float(m.group(0).replace(',', '')) if m else None


def _matches(shown, value):
    nd = len(shown.split('.')[1]) if '.' in shown else 0
    return round(abs(value), nd) == abs(float(shown.replace(',', '')))


_SIGNED = re.compile(r'([+\-−])?\s*(\d[\d,]*(?:\.\d+)?)')


def _unit_of(text):
    t = text.lstrip()
    return next((u for u in _UNITS if t.startswith(u)), None)


def _check_refs(paras, snap, session):
    v = []
    for p in paras:
        for m in _REF.finditer(p):
            path, inner = m.group(1), m.group(2)
            value = resolve(snap, path)
            text = _plain(inner)
            if not _finite(value):
                v.append(f'data-ref="{path}" 는 스냅샷에 값이 없다 — 「{text}」')
                continue
            n = _SIGNED.search(text)
            if not n or not _matches(n.group(2), value):
                v.append(f'data-ref="{path}" 값이 다르다 — 본문 「{text}」, 스냅샷 {value}')
            elif n.group(1) and value != 0 and (n.group(1) == '+') != (value > 0):
                v.append(f'data-ref="{path}" 부호가 반대다 — 본문 「{text}」, 스냅샷 {value}')
            after = _plain(p[m.end():m.end() + 40])
            unit = next((u for u in _UNITS if u in text), None) or _unit_of(after)
            allowed = _allowed_units(path, snap)
            if unit and unit not in allowed:
                v.append(f'data-ref="{path}" 단위가 틀렸다 — 「{text}」 뒤 「{after[:6]}」'
                         f'(허용 {"·".join(sorted(allowed)) or "단위 없음"})')
            if path.startswith('macro.'):
                item = resolve(snap, '.'.join(path.split('.')[:2])) or {}
                if item.get('status') != 'released':
                    v.append(f'data-ref="{path}" 는 오늘 발표(released) 값이 아니다 — 「{text}」')
            period = _period_of(snap, path)
            if period and period != session and not any(f in _plain(p) for f in _date_forms(period)):
                v.append(f'data-ref="{path}" 는 {R.day_ko(period)} 기준 값이다 — 그 문단에 날짜를 밝힌다')
    return v


def _core_values(snap):
    out = []
    nk = (snap.get('indices') or {}).get('nikkei') or {}
    out.append(('indices.nikkei.value', nk.get('value')))
    for t, r in (snap.get('jgb') or {}).items():
        if isinstance(r, dict):
            out.append((f'jgb.{t}.value', r.get('value')))
    out.append(('call_rate.value', (snap.get('call_rate') or {}).get('value')))
    for k, r in (snap.get('fx') or {}).items():
        out.append((f'fx.{k}.value', (r or {}).get('value')))
    for i, m in enumerate(snap.get('macro') or []):
        if m.get('status') == 'released':
            out.append((f'macro.{i}.value', m.get('value')))
    return [(p, x) for p, x in out if _finite(x)]


def _forms(x):
    """(형태, 단위 문맥이 있어야만 잡는가). 1자리 반올림은 흔한 숫자라 단위가 붙을 때만 본다(codex 구현 #6)."""
    out = {(f'{x:,.2f}', False), (f'{x:.2f}', False), (f'{x:.3f}', False), (f'{x:.1f}', True)}
    if abs(x) >= 1000:
        out |= {(f'{x:,.0f}', False), (f'{x:,.1f}', False)}
    return {(f, u) for f, u in out if f.strip('0.,') != ''}


def _check_unbound(paras, snap):
    v = []
    core = _core_values(snap)
    for p in paras:
        rest = _plain(_REF.sub(' ', p))
        for path, x in core:
            units = _allowed_units(path, snap) or {''}
            for f, need_unit in _forms(x):
                tail = (r'\s*(?:' + '|'.join(re.escape(u) for u in units if u) + r')') if need_unit and units != {''} else ''
                if need_unit and not tail:
                    continue
                if re.search(r'(?<![\d.,])' + re.escape(f) + r'(?![\d])' + tail, rest):
                    v.append(f'핵심 값 {f}({path})을 data-ref 없이 썼다 — <span data-ref="{path}"> 로 묶는다')
                    break
    return v


# 허용 수치 집합에서 뺄 메타데이터 — 해시·시각·사유 문장·시리즈 코드의 숫자를 본문이 「인용」하지 못하게.
_META_KEYS = {'version', 'ran_at', 'scheduled_at', 'published', 'fetched_at', 'bar_start', 'bar_end',
              'why', 'fetch_status', 'source', 'news_file', 'code', 'basis', 'tz', 'cut', 'checked_at',
              'resolved_at', 'time_jst', 'period', 'prev_period', 'date', 'session', 'prev_session',
              'released', 'name', 'reasons', 'universe', 'jgb_recollect'}


def _data_only(obj):
    if isinstance(obj, dict):
        return {k: _data_only(v) for k, v in obj.items() if k not in _META_KEYS}
    if isinstance(obj, list):
        return [_data_only(v) for v in obj]
    return obj


def _figures_of(fragment):
    t = _TIME.sub(' ', _plain(_jo_eok(fragment)))
    return _text_figures(t)


def _views(html, tg, news, session, pairs, skip=()):
    """-> (위반, 검사에서 뺄 절의 원문 | None). `skip` = 바이트 대조를 통과한 생성 요소·코드 표(2판)."""
    doc = strip_comments(html)
    if tg is None:
        # 단어 규칙은 파일이 없는 날에도 돈다 — 발행본에 「텔레그램」·채널 이름이 없다는 약속은 파일과
        # 무관하고, US·KR 게이트도 파일 없이 같은 검사를 한다(구현 검토 1회 #6)
        v = TG.word_violations(doc, jp=True)
        node, got = TG.views_node(doc)
        if node or got or TG.elements(doc) or re.search(r'\bdata-tg(?:-section)?\b', doc, re.I):
            v.append(f'「{TG.NEWS_TITLE}」 절이나 data-tg 표식이 있는데 쓸 수 있는 텔레그램 파일이 없다 — '
                     f'`python3 scripts/tg_news.py strip --html <파일>` 로 절을 뺀다')
        return v, None
    got = []
    v = TG.check(html, tg, layout='jp', news=news, session=session, pairs=pairs, views=got, skip=skip)
    if not got:
        return v, None
    src = got[0]['source']
    secs = list(_SEC.finditer(html))
    i = next((k for k, m in enumerate(secs) if m.group(1) == TG.VIEWS), None)
    if (html.count(src) != 1 or i is None or i == 0 or secs[i].group(0) != src or secs[i - 1].group(1) != 'news'
            or html[secs[i - 1].end():secs[i].start()].strip()):
        return v + [f'「{TG.NEWS_TITLE}」 절이 제자리에 없다 — 일본 경제 뉴스 절 바로 뒤에, 주석 없이 한 번만 둔다'], None
    return v, src


# ── 2판(`schema: 2`) — 생성 요소 대조와 작성자가 쓸 수 없는 것 (2026-11-19) ─────────────────────
# 코드가 쓴 문장·표는 `render(facts)` 출력과 **바이트로** 같아야 하고, 그 요소만 작성자 산문 검사에서 빠진다.
# 작성자 산문에서는 TOPIX·업종지수·커브·업종 개수·일정 부재를 말하는 글자를 막는다 — 그 사실은 바로 옆
# 생성 문장이 말한다. 글자 목록이라 동의어로 샐 수 있지만 새는 것은 숫자 없는 정성 서술뿐이다(§5 끝).
_GEN_OPEN = re.compile(r'<([a-zA-Z][\w-]*)\b[^>]*\bdata-gen\b[^>]*>', re.I)
_IDX_WORDS = re.compile(r'TOPIX|토픽스|업종지수', re.I)
_IDX_SOURCE = re.compile(r'TOPIX|トピックス|東証株価指数|업종지수|業種別', re.I)
_CURVE_ANY = re.compile(r'곡선|커브|기울기|장단기|스티프|플래트|steepen|flatten', re.I)
# ⓑ 의 주어 글자에 채권 만기 꼴 「N년」 을 더했다 — 설계 §11-6 의 「10-30년 구간은 가팔라졌다」 는 §5-2 ⓑ 의
# 글자(금리·국채·JGB·수익률·년물)가 없어 그대로는 지나간다. 만기는 한두 자리 숫자다 — 네 자리 달력 연도(「2026년」)와
# 기간 말(「3년 만에」「5년 전」)은 만기가 아니다(codex 구현 1회 #9). 「플랫폼」 은 「플랫」 으로 치지 않는다.
_MATURITY = r'(?<![\d,.])\d{1,2}\s*년(?!\s*(?:만|전|째|간|동안|대|도|치|이상|이내|후|뒤|새|래|연속))'
_CURVE_SUBJ = re.compile(r'금리|국채|JGB|수익률|년물|' + _MATURITY)
_CURVE_WORD = re.compile(r'가팔라|가파르|가파른|평탄|플랫(?!폼)|스프레드')
_GAP = re.compile(r'금리차|격차')
_GAP_SPAN = re.compile(_MATURITY + r'|\d+s\d+s')
_SECTOR_COUNT = re.compile(r'\d+\s*개')
_ABSENT = re.compile(r'없다|없었|없는|없어|없고|없으|부재')
_SCHEDULE = re.compile(r'지표|발표|일정|통계')
_BLOCK_TAG = re.compile(r'</?(?:p|h[1-6]|li|ul|ol|div|section|article|header|footer|nav|table|tr|td|th|thead|tbody|'
                        r'caption|figcaption|details|summary|blockquote|dl|dt|dd|br)\b[^>]*>', re.I)
# 제목의 날짜 표기(`title_source` 가 가린다)와 글의 달·날 표기 — 「날짜」 와 「기간」 을 따로 본다(codex 구현 3회):
# 발표일 「3日」 이 「3일 연속」 을 허락하지 않는다. (수, 단위, 기간인가) 가 같을 때만 같은 표기다.
_JA_MD = re.compile(r'(?<![\d.,])0?(\d{1,2})\s*([月日])(連続|続伸|続落|続騰|連騰|連敗|連勝|ぶり|振り|間|目|連)?')
_KO_MD = re.compile(r'(?<![\d.,])0?(\d{1,2})(월|거래일|영업일|일(?!본))'
                    r'(\s*(?:연속|째|간|만에|만의|동안|새|차|치|내내|내리|잇달아|잇따라|연달아|계속|줄곧|거푸|연거푸))?')


def _ko_md(m):
    unit = m.group(2)
    return m.group(1), ('월' if unit == '월' else '일'), bool(m.group(3)) or unit in ('거래일', '영업일')


_BAD_REF = re.compile(r'data-ref\s*=\s*["\']([^"\']*)["\']', re.I)


def _without_v2(snap):
    """허용 수치 집합용 — `facts` 를 통째로 빼고, 어디에 있든 `denom` 을 뺀다."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ('facts', 'denom')}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return strip(snap)


def verify_generated(html, snap):
    """-> (위반, 대조를 통과한 조각들). 생성 문장은 종류마다 정확히 하나·정해진 절의 바로 아래·바이트 동일,
    코드 표(`render_tables`)는 비지 않은 조각마다 정확히 한 번·그 절의 바로 아래·바이트 동일."""
    v, ok = [], []
    want = FX.generated(snap)
    real = R.open_tokens(html)          # 주석·script 안에 든 「요소」는 독자에게 안 보인다 — 실제 여는 태그여야 한다
    seen = {}
    for m in _GEN_OPEN.finditer(html):
        tag = m.group(0)
        kind = re.search(r'data-gen\s*=\s*"([^"]*)"', tag)
        kind = kind.group(1) if kind else None
        if tag != f'<p data-gen="{kind}">' or kind not in want:
            v.append(f'data-gen 요소의 꼴이 다르다 — 「{tag[:60]}」(조립이 넣은 <p data-gen="종류"> 만 허용)')
            continue
        seen.setdefault(kind, []).append(m.start())
    for kind, frag in want.items():
        at = seen.get(kind, [])
        if len(at) != 1:
            v.append(f'생성 문장 data-gen="{kind}" 가 {len(at)}번 있다 — 정확히 한 번(조립이 넣는다)')
            continue
        if not html.startswith(frag, at[0]):
            v.append(f'생성 문장 data-gen="{kind}" 이 코드 출력과 다르다 — 고치지 않는다(본문에는 <!--G:{kind}--> 자리만)')
            continue
        sec = FX.GEN_SECTION[kind]
        if at[0] not in real:
            v.append(f'생성 문장 data-gen="{kind}" 이 주석 안에 있다 — 독자에게 보이지 않는다')
            continue
        parent = real[at[0]]
        if not parent or not R.section_tag_re(sec).fullmatch(parent):
            v.append(f'생성 문장 data-gen="{kind}" 이 {sec} 절의 바로 아래에 있지 않다(부모 {parent or "없음"})')
            continue
        ok.append(frag)
    where = {t: sec for sec, names in R.PLACEHOLDERS.items() for t in names}
    for name, frag in R.render_tables(snap).items():
        if not frag:
            continue
        n = html.count(frag)
        if n != 1:
            v.append(f'코드 표 {name} 가 코드 출력과 같은 꼴로 {n}번 있다 — 정확히 한 번(표를 고치지 않는다)')
            continue
        at = html.index(frag)
        if at not in real:
            v.append(f'코드 표 {name} 가 주석 안에 있다 — 독자에게 보이지 않는다')
            continue
        parent = real[at]
        if not parent or not R.section_tag_re(where[name]).fullmatch(parent):
            v.append(f'코드 표 {name} 가 {where[name]} 절의 바로 아래에 있지 않다(부모 {parent or "없음"})')
            continue
        ok.append(frag)
    return v, ok


def _head_texts(html):
    out = [html_mod.unescape(t) for t in re.findall(r'<title>(.*?)</title>', html, re.S)]
    out += [html_mod.unescape(t) for t in re.findall(r'<meta name="description" content="([^"]*)"', html)]
    return out


def _units(fragment):
    """마크업 조각 → 블록 경계·문장 끝에서 자른 보이는 글 조각."""
    t = re.sub(r'<!--.*?-->', ' ', fragment, flags=re.S)
    t = _BLOCK_TAG.sub('\n', _TITLE_SPAN.sub(r'\1', t))
    t = html_mod.unescape(_TAG.sub('', t))
    out = []
    for line in t.split('\n'):
        for sent in _SENT_END.split(line):
            sent = re.sub(r'\s+', ' ', sent).strip()
            if sent:
                out.append(sent)
    return out


def _banned(sent, index_ok=False):
    """한 문장 → 위반 사유 또는 None."""
    if not index_ok and _IDX_WORDS.search(sent):
        return 'TOPIX·업종지수는 생성 문장이 말한다 — 작성자는 이름 없이 해석한다'
    if _CURVE_ANY.search(sent) or (_CURVE_SUBJ.search(sent) and _CURVE_WORD.search(sent)) \
            or (_GAP.search(sent) and _GAP_SPAN.search(sent)):
        return '금리 곡선·스프레드는 생성 문장이 말한다 — 작성자가 쓰지 않는다'
    if '업종' in sent and _SECTOR_COUNT.search(sent):
        return '업종 개수는 생성 문장이 센다 — 작성자가 세지 않는다'
    if _ABSENT.search(sent) and _SCHEDULE.search(sent):
        return '일정 부재는 코드 캡션만 말한다 — 「발표가 없다」를 쓰지 않는다'
    return None


def _news_writer_pieces(sec_html, news):
    """뉴스 절 → ([(글, 그 기사 | None)], 기사 블록 밖 작성자 글). 코드가 찍은 수집 요약과 출처 줄만 뺀다(15회차)."""
    by = {str(it.get('guid')): it for it in (news or {}).get('items') or []}
    pieces = []
    block = re.compile(r'<div class="news-item" data-news="([^"]*)">(.*?)</div>', re.S)
    std = re.compile(r'<p class="news-head">(.*?)<span class="sub">(.*?)</span></p><p data-summary="([^"]*)">(.*?)</p>',
                     re.S)

    def one(m):
        guid, inner = html_mod.unescape(m.group(1)), m.group(2)
        it = by.get(guid)
        s = std.fullmatch(inner)
        summ = html_mod.escape((it or {}).get('summary_ko') or '', quote=False).strip()
        if (it is not None and s and html_mod.unescape(s.group(3)) == guid and summ
                and s.group(2) == html_mod.escape(news_caption(it), quote=False) and s.group(4).startswith(summ)):
            pieces.append((s.group(1), it))                         # 한국어 제목 — 작성자 글
            link = s.group(4)[len(summ):]
            if link.strip():
                pieces.append((link, it))                           # 연결 문장 — 작성자 글
        else:
            pieces.append((inner, it))                              # 손으로 쓴 블록 — 통째로 작성자 글
        return ' '
    outside = block.sub(one, sec_html)
    return pieces, outside


def _check_v2_prose(html, snap, news, exempt, verified, invented):
    v = []
    for m in _BAD_REF.finditer(html):
        parts = m.group(1).split('.')
        if parts[0] in ('facts', 'curve') or 'denom' in parts:
            v.append(f'data-ref="{m.group(1)}" — TOPIX·업종·스프레드·분모 숫자는 작성자가 인용하지 않는다(생성 문장이 말한다)')
    start = html.find('<div class="container">')
    end = html.find('<footer class="disclaimer">')
    region = html[start:end] if start != -1 and end > start else html
    if exempt:
        region = region.replace(exempt, ' ', 1)
    for frag in verified:
        region = region.replace(frag, ' ', 1)
    region = re.sub(r'<nav class="reading-map".*?</nav>', ' ', region, flags=re.S)
    news_sec = re.search(r'<section\b[^>]*\bdata-section="news"[^>]*>.*?</section>', region, re.S)
    pieces, outside_news = [], ''
    if news_sec:
        pieces, outside_news = _news_writer_pieces(news_sec.group(0), news)
        region = region.replace(news_sec.group(0), ' ', 1)
    texts = _units(region) + _units(outside_news) + [u for t in _head_texts(html) for u in _units(t)]
    for sent in texts:
        why = _banned(sent)
        if why:
            v.append(f'{why}: 「{sent[:50]}」')
    v += invented(outside_news)
    for frag, it in pieces:
        fields = ' '.join(str((it or {}).get(k) or '') for k in ('title', 'summary_ko'))
        index_ok = bool(it) and bool(_IDX_SOURCE.search(fields))
        for sent in _units(frag):
            why = _banned(sent, index_ok=index_ok)
            if why:
                v.append(f'뉴스 블록의 작성자 글 — {why}: 「{sent[:50]}」')
        # 그 기사(제목·요약)에 있는 수치만 — 크기·단위와 무관하다. 「12 이하 정수」 면제를 두면 「TOPIX 7 상승」 이
        # 지나간다(codex 구현 1회 #7 → 2회). 다른 기사에 있는 수도 안 된다(이 블록의 출처 줄은 한 기사다).
        # 제목의 「9月」「3日」 은 날짜로 가려져 원천 수치가 아니다 — 글의 「9월」「3일」 만 같은 달·날 표기로 보고
        # 뺀다(「9%」「TOPIX 3 상승」 은 아니다).
        own = _text_figures(((it or {}).get('summary_ko') or '') + ' ' + title_source((it or {}).get('title')))
        md = {(n, {'月': '월', '日': '일'}[u], bool(dur))
              for n, u, dur in _JA_MD.findall(unicodedata.normalize('NFKC', str((it or {}).get('title') or '')))}
        text = _KO_MD.sub(lambda m: ' ' if _ko_md(m) in md else m.group(0),
                          unicodedata.normalize('NFKC', frag))
        for n in sorted(_figures_of(text) - own):
            v.append(f'뉴스 블록의 제목·연결 문장에 그 기사 수집 필드에 없는 수치 {n} 이 있다')
    return v


def _check_boj(html, boj, session, invented):
    """일본은행 절 — 공용 칸 검사 + 수치(무효화 블록 밖): 스냅샷 ∪ 그날 원문의 숫자 토큰. 원문이 없는 날은 숫자 금지."""
    due = boj['due']
    extra = _boj_figures(due)

    def numbers(scope, _due):
        if not extra:
            out = []
            for n in sorted(_figures_of(scope)):
                try:
                    x = abs(float(n))
                except ValueError:
                    continue
                if (x <= 12 and x == int(x)) or (2020 <= x <= 2035 and x == int(x)):
                    continue
                out.append(f'일본은행: 원문을 받지 못한 날의 절에 수치 {n} 을 썼다 — 결정 사실만 기사 귀속으로 쓴다')
            return out
        return [x.replace('어느 원본에도 없는 수치가 본문에 있다', '일본은행 절: 스냅샷에도 원문에도 없는 수치가 있다')
                for x in invented(scope, extra)]
    return CBG.check(html, 'boj', due, session, diffs=(boj.get('diff'), boj.get('outlook_diff')), numbers=numbers)


def _boj_figures(due):
    """그날 실을 일본은행 이벤트 원문의 숫자 토큰 전부 — 이 게이트와 같은 정규화(`_text_figures`)로. PDF 는 글자
    사이에 공백이 들어가(「１． ５％」) 공백을 둔 판과 지운 판을 둘 다 넣는다. 兆·億 은 조·억으로 바꿔 번역문
    (「8,600억 엔」·「2조 4,600억 엔」)과 같은 꼴이 되게 한다(설계 2절 v4 — 10/30 공표문의 1.25%·約8,600億円)."""
    out = set()
    for e in due:
        text = CBG.corpus(e)
        if not text:
            continue
        body = '\n'.join(line for line in text.split('\n') if not line.startswith('# '))   # 수집기 머리줄(주소) 제외
        ja = CBQ.ja_source_text(body)
        out |= _text_figures(ja) | _text_figures(re.sub(r'\s+', '', ja))
    return out


def check(html, snap, session, filename=None, news=None, tg=None, pairs=None, boj=None):
    """`tg` = 쓸 수 있는(`usable`) 텔레그램 파일 내용 또는 None, `pairs` 는 (id, 문단, 요약)을 받는다.
    `boj` = `build_japan_daily.boj_state` 결과(None 이면 실을 이벤트 없음 — 일본은행 절이 있으면 막힌다)."""
    v = []
    boj = boj or {'due': [], 'diff': None, 'outlook_diff': None}
    boj_secs = [m.group(0) for m in _SEC.finditer(html) if m.group(1) == 'boj']
    if not snap.get('complete'):
        v.append('스냅샷 complete 가 거짓이다 — 닛케이 공식 종가를 확인하지 못한 세션은 발행하지 않는다')
    if snap.get('session') != session:
        v.append(f'스냅샷 세션 {snap.get("session")} ≠ 발행 세션 {session}')
    if filename and not filename.endswith(f'{session}.html'):
        v.append(f'파일 이름 {filename} 이 세션 {session} 과 다르다')
    if not _finite(((snap.get('indices') or {}).get('nikkei') or {}).get('value')):
        v.append('코어 값(닛케이 종가)이 없다')
    if 'data-register="da"' not in html:
        v.append('<body data-register="da"> 가 없다 — -다 로 쓰는 데스크 문서다')
    for mark in _UNVERIFIED:
        if mark in html:
            v.append(f'미완 표식 「{mark}」 이 남았다')
    if R.BOJ_CREDIT not in html:
        v.append('일본은행 API 크레디트 문구가 없다(이용 고지 필수)')

    found = _SEC.findall(html)
    names = [n for n, _ in found]
    want = list(R.order((snap.get('calendar') or {}).get('event_day'), boj=bool(boj['due'])))
    if [n for n in names if n in R.SECTIONS or n == 'boj'] != want:
        v.append(f'절 순서가 다르다: {" → ".join(names)} (기대 {" → ".join(want)})')
    for s in R.SECTIONS:
        if names.count(s) != 1:
            v.append(f'data-section="{s}" 절이 {names.count(s)}번 있다')

    v2 = FX.is_v2(snap)
    verified = []
    if v2:
        gen_v, verified = verify_generated(html, snap)
        v += gen_v
    tg_v, exempt = _views(html, tg, news, session, pairs, skip=tuple(verified))
    v += tg_v
    # 일본은행 절은 작성자 산문 어휘 검사(컨센서스·신호·「오늘+콜」·「오늘+JGB」)와 data-ref 묶기에서 뺀다 — 번역은
    # 「전망치」「무담보 콜금리」를 그대로 옮겨야 한다(codex 설계 5회차 #6, 10/30 실제 요약 문장). 대신 아래에서
    # 일본은행 칸 검사(common/cb_gate)와 원문 숫자를 더한 수치 검사만 받는다.
    prose_secs = [(n, b) for n, b in found if n not in ('news', 'boj') and not (n == TG.VIEWS and exempt)]
    paras, movers, mover_src = [], [], []
    for _, b in prose_secs:
        for m in _P.finditer(_TABLE.sub(' ', b)):
            attrs, inner = m.group(1), m.group(2)
            if v2 and m.group(0) in verified:
                continue                    # 코드 출력 — 작성자 산문 검사 밖(대조를 통과한 그 요소만)
            if 'data-mover' in attrs:
                movers.append((attrs, inner))
                mover_src.append(m.group(0))
            else:
                paras.append((attrs, inner))
    head = re.search(r'<section class="card headline-card">(.*?)</section>', html, re.S)
    head_html = head.group(1) if head else ''
    for _, inner in _P.findall(head_html):
        paras.append(('', inner))
    for h in re.findall(r'<h1\b[^>]*>(.*?)</h1>', head_html, re.S):
        paras.append(('', h))
    allp = [inner for _, inner in paras + movers]
    v += _check_refs(allp, snap, session)
    v += _check_unbound(allp, snap)
    rows = [r for r in (snap.get('jgb') or {}).values() if isinstance(r, dict)]
    jgb_today = bool(rows) and all(r.get('period') == session for r in rows)
    for p in allp:
        t = _plain(p)
        if _CONSENSUS.search(t):
            v.append(f'예상·컨센서스와 비교했다 — 원천이 없다: 「{t[:50]}」')
        if _SIGNALS.search(t):
            v.append(f'주간 보고서의 신호 어휘다 — 일간은 서술만 한다: 「{t[:50]}」')
        views = _both_views(p)
        hit = next((x for view in views for x in _sentences(view) if '오늘' in x and _CALL.search(x)), None)
        if hit:
            v.append(f'콜금리는 오늘 값이 아니다 — 콜이 든 문장에 「오늘」 을 쓰지 않는다: 「{hit.strip()[:50]}」')
        if not jgb_today and any('오늘' in view and _JGB_NAME.search(view) for view in views):
            v.append(f'JGB 는 오늘 값이 아니다(직전 세션) — JGB 가 든 문단에 「오늘」 을 쓰지 않는다: 「{t[:50]}」')
        if '지수 기여' in t or '기여도' in t:
            v.append(f'「지수 기여」 는 쓰지 않는다(표본 시총 계산은 지수 기여가 아니다): 「{t[:50]}」')

    if v2:
        # facts(TOPIX·업종·스프레드·근거)와 모든 분모는 작성자 허용 수치가 아니다(§5-3) — 숫자를 쓸 길이 없다
        allowed = _numbers(_data_only(_without_v2(snap))) | _EXTRA_OK_V2 | {str(y) for y in range(2020, 2036)}
    else:
        allowed = _numbers(_data_only(snap)) | _EXTRA_OK | {str(y) for y in range(2020, 2036)}
        # 업종 ETF 코드는 표 캡션·이름에 나올 수 있다 — 코드 값만 따로 허용한다(옛 스냅샷만, R12)
        allowed |= {str(r.get('code')) for r in snap.get('sectors') or [] if r.get('code')}
    by_guid = {str(it.get('guid')): it for it in (news or {}).get('items') or []}
    united = _united_numbers(_jo_eok(html))

    def _invented(fragment, extra=frozenset()):
        out = []
        for n in sorted(_figures_of(fragment) - allowed - set(extra)):
            try:
                x = abs(float(n))
            except ValueError:
                continue
            if x <= 12 and x == int(x) and n not in united:
                continue
            out.append(f'어느 원본에도 없는 수치가 본문에 있다: {n} — 스냅샷 값만 쓴다')
        return out

    # 뉴스 절과 움직인 종목 문단을 뺀 보이는 글 전부 — 머리 카드·소제목·표 포함(codex 구현 검토 #5)
    # 빼는 것은 **검사한 것만** — 견해·의견 절은 텔레그램 게이트가, 움직인 종목 문단은 아래에서 본 문단만.
    # 그 밖의 자리에 data-mover 를 단 문단은 수치 검사를 피하는 구멍이었다(2026-11-15 설계 검토).
    rest = html.replace(exempt, ' ', 1) if exempt else html
    for frag in verified + boj_secs:
        rest = rest.replace(frag, ' ', 1)
    rest = re.sub(r'<section\b[^>]*\bdata-section="news"[^>]*>.*?</section>', ' ', rest, flags=re.S)
    for src in mover_src:
        rest = rest.replace(src, ' ', 1)
    for inner in re.findall(r'<p\b[^>]*\bdata-mover\b[^>]*>(.*?)</p>', rest, flags=re.S):
        v.append(f'움직인 종목 문단(data-mover)이 본문 절 밖에 있다 — 주식 절 등 산문 절 안에만 쓴다: 「{_plain(inner)[:40]}」')
    rest = re.sub(r'<(script|style|head)\b.*?</\1>', ' ', rest, flags=re.S)
    v += _invented(rest)
    if v2:
        v += _invented(' '.join(_head_texts(html)))      # <title>·meta description 도 작성자 글이다
        v += _check_v2_prose(html, snap, news, exempt, verified + boj_secs, _invented)
    # 움직인 종목 — 원인은 인용한 기사(data-cite) 요약에서만, 아니면 「확인된 재료 없음」(codex 구현 검토 #8)
    for attrs, inner in movers:
        cite = re.search(r'data-cite="([^"]+)"', attrs)
        t = _plain(inner)
        if cite:
            it = by_guid.get(cite.group(1))
            if it is None:
                v.append(f'data-cite="{cite.group(1)}" 는 일간 뉴스 파일에 없다 — 「{t[:40]}」')
                v += _invented(inner)
            else:
                v += _invented(inner, _text_figures(it.get('summary_ko') or ''))
        else:
            if '확인된 재료 없음' not in t:
                v.append(f'움직인 종목 문단에 원인 근거가 없다 — data-cite="guid" 를 달거나 「확인된 재료 없음」: 「{t[:40]}」')
            v += _invented(inner)
    v += _check_boj(html, boj, session, _invented)
    v += CM.check(html, snap.get('movers'), session)
    low = body_text(html).lower()
    for word in BANNED_LABELS:
        if word in low:
            v.append(f'buy-side 표기("{word}")가 남았다')
    return list(dict.fromkeys(v))
