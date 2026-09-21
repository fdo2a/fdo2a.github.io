"""Bind research output to a verified ledger; editorial metrics are advisory."""
from collections import Counter
from html import escape
from html.parser import HTMLParser
import hashlib
import json
import re


class Elements(HTMLParser):
    """Extract balanced elements by attribute, retaining source offsets."""
    def __init__(self, html, attribute):
        super().__init__(convert_charrefs=True)
        self.html, self.attribute = html, attribute
        self.offsets = [0]
        for line in html.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack, self.matches = [], []
        self.feed(html)
        if any(item[2] is not None for item in self.stack):
            raise ValueError('Unclosed research element')

    def source_offset(self):
        row, col = self.getpos()
        return self.offsets[row - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in {'br','hr','img','meta','link','input','source','wbr','area','base','embed','param','track','col'}:
            return
        attrs = dict(attrs)
        self.stack.append((tag, self.source_offset(), attrs.get(self.attribute)))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if not self.stack:
            return
        if self.stack[-1][0] != tag:
            if any(item[2] is not None for item in self.stack):
                raise ValueError('Malformed research element')
            return
        name, start, value = self.stack.pop()
        if value is not None:
            end = self.html.find('>', self.source_offset()) + 1
            self.matches.append((start, end, value, name))


def _fingerprint(summary):
    raw = json.dumps(summary, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def render_summary(summary):
    """Only derived counts/outcomes go into this immutable publication fragment."""
    c = summary['counts']
    parts = [f'<section class="card" id="research-review" data-research-summary="{_fingerprint(summary)}">',
             '<h2>연구 판단 복기</h2>',
             f'<p>검토 대상 {c["total"]}건 중 사전 기록 {c["prospective"]}건, 사후 기록 {c["retrospective"]}건입니다. '
             f'진행 중 {c["open"]}건이며 확인 기한이 지난 가설은 {c["overdue"]}건입니다.</p>']
    labels = {'supported': '지지', 'weakened': '약화', 'undecidable': '판단 유보',
              'not_reviewed': '미검토', 'open': '진행 중', 'closed': '종료',
              'watch': '관찰', 'planned': '검토 예정', 'not_taken': '미실행'}
    if summary['hypotheses']:
        parts.append('<div class="tbl-scroll"><table><thead><tr><th>가설</th><th>기록</th><th>방향</th><th>설명</th><th>상태</th><th>실행</th><th>성과</th></tr></thead><tbody>')
        for row in summary['hypotheses']:
            # A numeric performance assessment stays in the evidence until its full
            # execution/cost basis has been reviewed; missing inputs never become zero.
            perf = row['performance']
            performance = '평가 불가' if perf['status'] == 'unavailable' else '근거 기록 있음'
            fields = [row['title'], '사전' if row['prospective'] else '사후',
                      labels[row['direction']], labels[row['mechanism']], labels[row['status']],
                      labels[row['execution_status']], performance]
            parts.append('<tr>' + ''.join('<td>' + escape(str(x)) + '</td>' for x in fields) + '</tr>')
        parts.append('</tbody></table></div>')
    else:
        parts.append('<p>아직 평가할 가설 기록이 없습니다.</p>')
    parts.append('<p class="caption">방향과 설명의 타당성은 따로 평가합니다. 미실행·판단 유보를 포함하며, 이 기록만으로 반복 가능한 투자 우위가 입증되지는 않습니다.</p></section>')
    return '\n'.join(parts)


def checked_summary_body(html, summary):
    matches = Elements(html, 'data-research-summary').matches
    if len(matches) != 1:
        raise ValueError('Exactly one ledger-derived research summary is required')
    start, end, _, tag = matches[0]
    if tag != 'section' or html[start:end].strip() != render_summary(summary):
        raise ValueError('Research summary differs from the as-of ledger; regenerate it')
    return html[:start] + html[end:]


def check_daily(html, records, cycle_id, market, report_date):
    cycles = [r for r in records if r['id'] == cycle_id and r['type'] == 'cycle']
    if len(cycles) != 1:
        return ['Research cycle is missing from the verified ledger']
    cycle = cycles[0]
    if cycle['market'] != market or cycle['report_date'] != report_date:
        return ['Research cycle market/date does not match the report']
    if any(r.get('market') == market
           for r in records[records.index(cycle) + 1:]):
        return ['Research cycle is stale; append a new cycle after the latest research']
    try:
        matches = Elements(html, 'data-research-cycle').matches
        if len(matches) != 1 or matches[0][2] != cycle_id or matches[0][3] != 'section':
            return ['Report must contain one matching research cycle section']
        start, end, _, _ = matches[0]
        segment = html[start:end]
        if not re.sub(r'<[^>]*>|\s', '', segment):
            return ['Research cycle section is empty']
        required = set(cycle['candidate_ids']) | set(cycle.get('reviewed_ids', []))
        required |= {x['hypothesis_id'] for x in cycle.get('unresolved', [])}
        # reviewed_ids refers to review records; their hypothesis IDs label prose.
        by_id = {r['id']: r for r in records}
        required = {by_id[x].get('hypothesis_id', x) if x in by_id else x for x in required}
        tags = Elements(segment, 'data-hypothesis').matches
        visible = {value for a,b,value,_ in tags if re.sub(r'<[^>]*>|\s', '', segment[a:b])}
        if required - visible:
            return ['Research prose omits hypotheses: ' + ', '.join(sorted(required - visible))]
        if visible - required:
            return ['Research prose names hypotheses outside the cycle']
    except ValueError as e:
        return [str(e)]
    return []


class Prose(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack, self.paragraphs, self.current = [], [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        ignored = tag in {'script','style','table','nav','footer'} or 'data-editor-note' in attrs or 'data-editor-note-slot' in attrs
        if tag in {'br','hr','img','meta','link','input','source','wbr','area','base','embed','param','track','col'}:
            return
        self.stack.append((tag, ignored or (bool(self.stack) and self.stack[-1][1])))
        if tag == 'p' and not self.stack[-1][1] and not set(attrs.get('class', '').split()) & {'caption','source','sources','disclaimer'}:
            self.current = []

    def handle_endtag(self, tag):
        if tag == 'p' and self.current is not None:
            self.paragraphs.append(''.join(self.current).strip())
            self.current = None
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.current is not None and self.stack and not self.stack[-1][1]:
            self.current.append(data)


def editorial_metrics(html):
    paragraphs = Prose(html).paragraphs
    sentences = [re.sub(r'\s+', ' ', x).strip() for p in paragraphs
                 for x in re.split(r'(?<=[.!?])\s+|(?<=[다요][.!?])(?=[가-힣])', p) if len(x.strip()) >= 24]
    counts = Counter(sentences)
    notes = [p for p in paragraphs if re.search(r'설명할 필요는 없|설명은 하지 않|원인으로 덧붙이지 않|날짜.{0,20}정렬돼|필드명|게이트를 통과', p)]
    return {'paragraphs': len(paragraphs), 'duplicate_sentences': sum(n-1 for n in counts.values() if n > 1),
            'duplicates': [s for s,n in counts.items() if n > 1], 'internal_notes': notes}


def compare_drafts(before, after):
    return {'before': editorial_metrics(before), 'after': editorial_metrics(after),
            'manual_review': ['중심 질문에 답하는가', '문단마다 새 근거가 있는가',
                              '관측을 인과로 바꾸지 않았는가', '수치와 불확실성을 보존했는가'],
            'notice': '정확히 반복된 문장과 일부 검수 표현만 찾는 보조 검사입니다. 문체 품질이나 AI 작성 확률을 판정하지 않습니다.'}
