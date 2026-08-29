"""발행본의 무게중심을 재는 게이트 — 시황·가격 대 판단·포지션.

2026-08-27 실측에서 판단·포지션이 7,424자(53%)·시황·가격이 3,676자(26%)였다.
자수는 엔티티를 디코드한 뒤 센다 — stance_gate.strip_tags는 &amp;를 5자로 세므로
여기서 쓰지 않는다(2026-08-30 codex 검토).
"""
import html as _html
import re

_TAG = re.compile(r'<[^>]+>')
_CELL_MIN = 40


def _text(fragment):
    return _html.unescape(_TAG.sub('', fragment)).strip()


def section_slice(html_doc, title):
    """제목이 정확히 `title`인 <h2>가 여는 구간. 없으면 None.

    본문 폴백을 두지 않는다 — 「주식」·「채권」은 헤드라인에도 나오는 흔한 말이라
    부분일치로 찾으면 엉뚱한 구간을 잡는다(2026-08-30 codex 검토).
    """
    heads = [m.start() for m in re.finditer(r'<h2\b[^>]*>(.*?)</h2>', html_doc, re.S)
             if _text(m.group(1)) == title]
    if not heads:
        return None
    start = heads[0]
    nxt = [m.start() for m in re.finditer(r'<h2\b', html_doc) if m.start() > start]
    return html_doc[start:nxt[0] if nxt else len(html_doc)]


def prose_chars(section_html):
    """문단 + 서술형 표 칸(40자 초과)의 글자 수. 캡션은 뺀다.

    표 칸을 함께 세는 것은 산문을 표로 밀어 넣어 비율을 맞추는 우회를 막기 위해서다.
    """
    if not section_html:
        return 0
    n = 0
    for attrs, body in re.findall(r'<p([^>]*)>(.*?)</p>', section_html, re.S):
        if 'caption' in attrs:
            continue
        n += len(_text(body))
    for body in re.findall(r'<td[^>]*>(.*?)</td>', section_html, re.S):
        t = _text(body)
        if len(t) > _CELL_MIN:
            n += len(t)
    return n


SECTION_GROUPS = {
    'us': {
        'recap': ('오늘의 장', '주식', '채권', 'FX', '원자재'),
        'judgment': ('전략 코멘트', '매크로 논리', '멀티에셋 매니저 전략'),
    },
    'kr': {
        'recap': ('오늘의 장', '지수 & 장중', '환율·금리'),
        'judgment': ('전략 코멘트', '기술적 분석 & 트레이딩 전략'),
    },
}

# 「오늘의 장」은 2026-08-28 신설이라 옛 판에는 없다. 없어도 위반으로 치지 않고 0자로 센다.
OPTIONAL_SECTIONS = ('오늘의 장',)

THRESHOLDS = {
    'us': {
        'recap_min': 5500,
        'ratio_min': 0.75, 'ratio_min_abbrev': 1.00,
        'macro_max': 4600, 'macro_min': 3000,
        'macro_max_abbrev': 2400, 'macro_min_abbrev': 1200,
        'stance_min': 1800,
    },
    'kr': {'recap_min': 2200},
}


def measure(html_doc, market='us'):
    """{'sections', 'recap', 'judgment', 'ratio', 'missing'}."""
    groups = SECTION_GROUPS[market]
    sections, missing = {}, []
    for group in ('recap', 'judgment'):
        for title in groups[group]:
            seg = section_slice(html_doc, title)
            if seg is None:
                sections[title] = 0
                if title not in OPTIONAL_SECTIONS:
                    missing.append(title)
            else:
                sections[title] = prose_chars(seg)
    recap = sum(sections[t] for t in groups['recap'])
    judgment = sum(sections[t] for t in groups['judgment'])
    return {'sections': sections, 'recap': recap, 'judgment': judgment,
            'ratio': (recap / judgment) if judgment else None, 'missing': missing}


def check_volume(m, abbreviated=False, market='us'):
    t = THRESHOLDS[market]
    v = []
    for title in m['missing']:
        v.append(f'섹션 「{title}」을 찾지 못했다 — <h2>{title}</h2>가 있어야 분량을 잰다')

    if m['recap'] < t['recap_min']:
        v.append(f'시황·가격군이 {m["recap"]}자로 하한 {t["recap_min"]}자에 못 미친다')

    if market != 'us':
        return v

    floor = t['ratio_min_abbrev'] if abbreviated else t['ratio_min']
    day = '축약일' if abbreviated else '발표일'
    if m['ratio'] is not None and m['ratio'] < floor:
        v.append(f'시황·가격군 ÷ 판단군이 {m["ratio"]:.2f}로 {day} 하한 {floor:.2f}에 '
                 f'못 미친다 (시황 {m["recap"]}자 · 판단 {m["judgment"]}자)')

    macro = m['sections'].get('매크로 논리', 0)
    hi = t['macro_max_abbrev'] if abbreviated else t['macro_max']
    lo = t['macro_min_abbrev'] if abbreviated else t['macro_min']
    if macro > hi:
        v.append(f'매크로 논리가 {macro}자로 {day} 상한 {hi}자를 넘는다')
    if macro < lo:
        v.append(f'매크로 논리가 {macro}자로 {day} 하한 {lo}자에 못 미친다 — '
                 '§9를 지워 비율을 맞추지 말 것')

    stance = m['sections'].get('멀티에셋 매니저 전략', 0)
    if stance < t['stance_min']:
        v.append(f'멀티에셋 매니저 전략이 {stance}자로 하한 {t["stance_min"]}자에 못 미친다')
    return v


_MIN_BLOCK = 120
_BIG_BANDS = ('큼', '매우 큼')

# 섹션 ← 그 섹션이 책임지는 price_context 자산
SECTION_ASSETS = {
    'us': {
        '주식': ('S&P 500', 'Nasdaq', 'Russell 2000', 'VIX'),
        '채권': ('10Y', '30Y'),
        'FX': ('DXY', 'USD/JPY', 'USD/KRW'),
        '원자재': ('WTI', 'Gold'),
    },
    'kr': {'지수 & 장중': (), '환율·금리': ()},
}

STANDING_KEYS = {'주식': 'equities', '채권': 'bonds', 'FX': 'fx', '원자재': 'commodities',
                 '지수 & 장중': 'equities', '환율·금리': 'rates'}

# 등급 통제 어휘. 단독 「중립」은 뺀다 — 주식·원자재의 0등급 라벨이 하필 일상 어휘라
# 「거의 중립적인 하루」를 매일 오탐한다. 다어절 라벨과 OW·UW만 잡는다.
BANNED_GRADE_WORDS = (
    '비중확대', '소폭확대', '소폭축소', '비중축소',
    '숏 듀레이션', '숏 바이어스', '중립 듀레이션', '롱 바이어스', '롱 듀레이션',
    '달러 숏', '달러 소폭 숏', '달러 중립', '달러 소폭 롱', '달러 롱',
    '플래트너', '커브 중립', '스티프너', '벨리 OW',
)
_OW_UW = re.compile(r'(?<![A-Za-z])(OW|UW)(?![A-Za-z])')

VOCAB_SECTIONS = {'us': ('오늘의 장', '주식', '채권', 'FX', '원자재'),
                  'kr': ('오늘의 장', '지수 & 장중', '환율·금리')}

LEDE_ORDER = ('event', 'meaning', 'action', 'invalidation')

_TODAY_CUE = re.compile(r'오늘|전일 대비|마감|하루 변화')


def _paras(section_html):
    return [(a, _text(b)) for a, b in
            re.findall(r'<p([^>]*)>(.*?)</p>', section_html or '', re.S)]


def _marked(section_html, attr):
    """`<p data-attr="...">` 문단들의 (값, 텍스트)."""
    out = []
    for attrs, text in _paras(section_html):
        m = re.search(rf'\b{attr}\s*=\s*"([^"]*)"', attrs)
        if m:
            out.append((m.group(1), text))
    return out


def check_standing(html_doc, price_context, market='us'):
    """가격 섹션마다 「지금 어디에 있나」 문단이 있고 알맹이가 있는가.

    기준은 「이걸 본 사람이 요즘 주식·채권시장 어떠냐는 질문에 대답할 수 있는가」다.
    """
    if not price_context:
        return []
    v = []
    for title in SECTION_ASSETS[market]:
        seg = section_slice(html_doc, title)
        if seg is None:
            continue
        blocks = _marked(seg, 'data-standing')
        if not blocks:
            v.append(f'{title}: 「지금 어디에 있나」 문단이 없다 — '
                     f'<p data-standing="{STANDING_KEYS[title]}">로 시작할 것')
            continue
        text = max((t for _, t in blocks), key=len)
        if len(text) < _MIN_BLOCK:
            v.append(f'{title}: 「지금 어디에 있나」 문단이 {len(text)}자로 '
                     f'{_MIN_BLOCK}자에 못 미친다 — 위치·경로·오늘의 크기 세 층을 담을 것')
        elif not re.search(r'\d', text):
            v.append(f'{title}: 「지금 어디에 있나」 문단에 수치가 없다')
    return v


def check_cause(html_doc, price_context, market='us'):
    """크게 움직인 자산은 원인 문단을 갖는가. 미미·보통이면 면제.

    분량이 아니라 사건에 건다 — DXY가 -0.04% 움직인 날 FX에 700자를 쓰라는 것은
    패딩 지시이고 「band가 미미인 자산은 한 줄로 지나간다」와 어긋난다.
    """
    moves = (price_context or {}).get('moves') or {}
    if not moves:
        return []
    v = []
    for title, assets in SECTION_ASSETS[market].items():
        big = [a for a in assets if (moves.get(a) or {}).get('band') in _BIG_BANDS]
        if not big:
            continue
        seg = section_slice(html_doc, title)
        if seg is None:
            continue
        blocks = [t for _, t in _marked(seg, 'data-cause')
                  if len(t) >= _MIN_BLOCK and re.search(r'\d', t)]
        if not blocks:
            v.append(f'{title}: {", ".join(big)}이(가) 크게 움직였는데 원인 문단이 없다 — '
                     f'<p data-cause="...">에 {_MIN_BLOCK}자 이상, 수치 하나 이상')
    return v


def _numbers(text):
    """비교용 수치 토큰. 콤마를 걷고 유니코드 마이너스를 통일한다.

    연도·시각·한 자리 수는 뺀다 — 「8/26」·「09:30」·「2026년」이 우연히 겹치면
    가격 중복이 아닌데도 걸린다.
    """
    t = text.replace(',', '').replace('−', '-')
    out = set()
    for m in re.finditer(r'\d+\.?\d*', t):
        tok = m.group(0)
        if len(tok.replace('.', '')) < 3:
            continue
        if tok.isdigit() and 1900 <= int(tok) <= 2100:
            continue
        out.add(tok)
    return out


# 경로 그룹 ← 그 경로의 가격을 인쇄하는 자산 섹션
GROUP_SECTIONS = {
    'rates': ('채권', '원자재'),
    'demand': ('주식', '원자재'),
    'dollar': ('FX',),
    'ai_cycle': ('메모리/DRAM', 'AI 인프라'),
}


def check_macro_prices(html_doc, market_data=None):
    """§9 경로 블록이 자산 섹션에 이미 있는 그날 가격을 되풀이하지 않는가.

    market_data와 대조하지 않는다 — 발행본 표기가 원천값과 어긋나는 일이 흔하다
    (2026-08-27 실측: 금 4,641.3 대 본문 4,663, DXY 99.114 대 99.13). 중복의 정의는
    「같은 숫자가 두 자리에 있다」이므로 두 자리를 직접 맞댄다.

    수치 중복만 본다 — 「달러는 소폭 내렸다」 같은 말바꿈은 잡지 못한다.
    """
    seg = section_slice(html_doc, '매크로 논리')
    if seg is None:
        return []
    printed = {}
    for group, titles in GROUP_SECTIONS.items():
        nums = set()
        for title in titles:
            sec = section_slice(html_doc, title)
            if sec:
                nums |= _numbers(' '.join(t for _, t in _paras(sec)))
        printed[group] = nums

    v = []
    for m in re.finditer(r'<div[^>]*data-macro-group="([a-z_]+)"[^>]*>(.*?)</div>',
                         seg, re.S):
        key, text = m.group(1), _text(m.group(2))
        for sent in re.split(r'(?<=다)\.\s*', text):
            if not _TODAY_CUE.search(sent):
                continue
            hit = _numbers(sent) & printed.get(key, set())
            if hit:
                v.append(f'§9 {key}: 자산 섹션에 이미 있는 그날 가격'
                         f'({", ".join(sorted(hit))})을 되풀이했다 — '
                         '여기에는 경로 논리와 확인 지표만 쓸 것')
                break
    return v


def check_position_vocab(html_doc, market='us'):
    """가격 섹션이 스탠스 등급을 되풀이하지 않는가."""
    v = []
    for title in VOCAB_SECTIONS[market]:
        seg = section_slice(html_doc, title)
        if seg is None:
            continue
        text = ' '.join(t for _, t in _paras(seg))
        found = [w for w in BANNED_GRADE_WORDS if w in text]
        if _OW_UW.search(text):
            found.append('OW/UW')
        if found:
            v.append(f'{title}: 포지션 등급 어휘({", ".join(sorted(set(found)))})가 나왔다 — '
                     '스탠스는 멀티에셋 섹션에서만 말한다')
    return v


def check_lede(html_doc):
    """§2가 사건 → 의미 → 행동 → 무효화 순인가."""
    seg = section_slice(html_doc, '전략 코멘트')
    if seg is None:
        return ['섹션 「전략 코멘트」를 찾지 못했다']
    got = [k for k, _ in _marked(seg, 'data-lede')]
    v = [f'§2: data-lede="{k}" 문단이 없다' for k in LEDE_ORDER if k not in got]
    if not v and got != list(LEDE_ORDER):
        v.append(f'§2: data-lede 순서가 {" → ".join(got)}이다 — '
                 f'{" → ".join(LEDE_ORDER)} 순이어야 한다')
    return v


def check(html_doc, market='us', market_data=None, macro_eval=None):
    """모든 검사를 돌려 위반 문자열 리스트를 낸다. 빈 리스트면 발행 가능."""
    abbreviated = bool((macro_eval or {}).get('abbreviated'))
    pc = (market_data or {}).get('price_context') or {}
    v = []
    v += check_volume(measure(html_doc, market), abbreviated, market)
    v += check_standing(html_doc, pc, market)
    v += check_cause(html_doc, pc, market)
    v += check_position_vocab(html_doc, market)
    v += check_lede(html_doc)
    if market == 'us':
        v += check_macro_prices(html_doc)
    return v
