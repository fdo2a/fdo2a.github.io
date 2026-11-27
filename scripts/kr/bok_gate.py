"""KR 마감브리프 「한국은행 금통위」 칸 게이트 (2026-11-27). CLI: scripts/check_bok.py.

검사 항목은 공용 `common/cb_gate.check`(미국 연준 칸과 같은 항목)이고, 여기서는 KR 의 칸 수치 규칙만 정한다:
칸 안의 수치(무효화 블록 밖, 단위를 단 값·소수 둘째 자리·천 단위 — `common.numbers.measure_numbers`)는
KR 데이터 파일 값 또는 **그날 실을 이벤트 원문이 단위와 함께 적은 값**(`cb_quote.source_numbers`)이어야 한다.
원문을 못 받은 결정일(일정표 의무)의 칸에는 수치를 쓰지 않는다 — 허용 집합에 더할 원문이 없다.
"""
from common import cb_gate as G
from common import cb_quote as CQ
from common.numbers import measure_numbers, numeric_tokens, text_of

SECTION = 'bok'
TITLE = G.CONFIG['bok']['title']


def numbers_check(data_blobs):
    def run(scope_html, due):
        corpora = [G.corpus(e) for e in due if G.corpus(e)]
        found = sorted(measure_numbers(text_of(scope_html)))
        v = []
        if not corpora:
            for n in found:
                v.append(f'BOK 금통위: 원문을 받지 못한 날의 칸에 수치 {n} 을 썼다 — 결정 사실(동결·인상·인하, 표결)만 '
                         '기사 귀속으로 쓰고 금리 수준은 쓰지 않는다')
            return v
        allowed = numeric_tokens(*data_blobs)
        for c in corpora:
            allowed |= CQ.source_numbers(c)
        for n in found:
            if n not in allowed:
                v.append(f'BOK 금통위: 데이터에도 원문에도 없는 수치 {n} — 수치 창작 금지(문턱값은 무효화 블록 안에만)')
        return v
    return run


def check(html_doc, due, report_date, diff=None, data_blobs=()):
    return G.check(html_doc, SECTION, due, report_date, diffs=(diff,), numbers=numbers_check(data_blobs))
