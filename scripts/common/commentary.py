"""해석 문단 검사 — 주간 글이 「정리」로 끝나지 않게 한다.

2026-09-26 사용자 지시: 「단순 정리에 가깝다, 해설을 붙여」 → 이어서 「해설 상자를 따로 넣지
말고 하나의 완성된 글로」. 그래서 해설은 본문 흐름 안의 문단이다. 게이트가 셀 수 있게 해석을
담은 문단에 **보이지 않는 표시** `<p data-interp>` 를 단다 — 독자에게는 그냥 문단이다.

해석 문단은 표와 수치를 되풀이하는 자리가 아니라 **그래서 무엇을 뜻하나** — 메커니즘, 다른
시장으로의 전달, 무엇이 이 해석을 깨는가, 운용상 조건부 함의. 게이트는 존재와 분량만 센다.
"""
import re

MIN_CHARS = 120
_P = re.compile(r'<p\b([^>]*)>(.*?)</p>', re.S)
_TAG = re.compile(r'<[^>]+>')


def interp_sizes(section_html):
    return [len(re.sub(r'\s+', '', _TAG.sub(' ', inner)))
            for attrs, inner in _P.findall(section_html) if re.search(r'\bdata-interp\b', attrs)]


def check(sections, required):
    """sections: {이름: 절 HTML}. required: 해석 문단이 있어야 하는 절 이름들."""
    v = []
    for name in required:
        sizes = interp_sizes(sections.get(name, ''))
        if not sizes:
            v.append(f'「{name}」 절에 해석 문단(<p data-interp>)이 없다 — 표와 수치를 정리하는 데서 끝내지 말고 '
                     '그래서 무엇을 뜻하는지, 어디로 번지는지, 무엇이 이 해석을 깨는지를 본문 안에 쓴다')
        elif max(sizes) < MIN_CHARS:
            v.append(f'「{name}」 절의 해석 문단이 {max(sizes)}자다({MIN_CHARS}자 이상) — 한 줄 요약이 아니라 해석을 쓴다')
    return v
