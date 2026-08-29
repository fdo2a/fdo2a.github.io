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
