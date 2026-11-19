"""US 숫자 출처 검사 — 일간(`posts/D.html`)과 뉴스·산업 글(`news/D.html`)의 모든 숫자를 배타 칸 하나에 (2026-11-20).

틀·문법은 `common/numsrc.py`, 칸 풀이기는 `us/facts.py`. 여기는 US 글의 자리 규칙이다:
- **T**: `us.number_audit.audit(…, trace=)` 가 같은 파서로 돌려준 흐름 항목 중 「맞춰 본 표 칸·위임 노드」(trace 'T')만.
  수량의 글자가 전부 그런 항목 안일 때만 T. owned 라도 위반이 난 칸은 T 가 아니다.
- **표식**: `span[data-ref|data-src|data-nx]` — 한 표식에 수량 정확히 하나, 부호·배율·단위까지 안에. 걸치거나 겹치거나 비면 U 「표식 오류」.
- **상속**(좁게): `p[data-summary=G]` 의 요약 원문 앞부분 → 기사 G 목록. 뒤의 연결 한 문장은 표식이 없으면 U(확장기는
  연결 문장을 이스케이프해 span 을 받지 않는다 — 확인함). 블록의 한국어 제목(`p.news-head`, 캡션 `.sub` 제외)은 그 블록의
  G 목록과 대조한다(설계는 확장기가 제목 숫자에 `data-src=news` 를 찍는 것 — 같은 대조를 분류기가 한다). `span[data-tg=ID]`
  안은 텔레그램 원글 ID 목록.
- **구역**: 쟁점 분석(`data-contested`)·편집자 노트(`data-editor-note`)는 구역째 X(건수 따로).
- 제목·메타 설명: 같은 인쇄 꼴의 수량이 본문에 있고 U·X 가 아니면 그 칸, 아니면 U.
설계: docs/superpowers/specs/2026-11-20-number-sources.md
"""
import hashlib
import json
import os
import re

from common import article_numbers as AN
from common import numsrc as S
from us import facts as F

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, 'config', 'number_sources.json')
_CODE_BLOCK_ATTRS = ('data-release', 'data-research-summary', 'data-learning', 'data-fund-board', 'data-h41-release',
                     'data-qra-table', 'data-indicator', 'data-auction-day')


def fixed_terms(path=CONFIG):
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
        return [t for t in d.get('fixed_terms') or [] if isinstance(t, str)]
    except (OSError, ValueError):
        raise S.InputError('config/number_sources.json 을 읽지 못했다')


# ── 입력 ────────────────────────────────────────────────────────────────

def _read(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _try(path):
    try:
        return _read(path)
    except (OSError, ValueError):
        return None


class Inputs:
    """한 번 읽어 첫 판·최종본 분류가 같은 입력을 쓴다."""

    def __init__(self, market, date, datadir, repo, tg=None, cycle=None, ledger=None):
        self.market, self.date, self.datadir, self.repo = market, date, datadir, repo
        self.terms = fixed_terms()
        self.news = _try(os.path.join(datadir, 'news', f'{date}.json'))
        nums = _try(AN.numbers_path(datadir, 'news', date))
        summ = {str(it.get('guid')): it.get('summary_ko') or '' for it in (self.news or {}).get('items') or []
                if isinstance(it, dict)}
        self.news_summary = summ
        self.article = AN.lists_for(nums, summ)
        tgp = tg or os.path.join(datadir, 'telegram.json')
        tgd = _try(tgp)
        tsum = {str(it.get('id')): it.get('summary_ko') or '' for it in (tgd or {}).get('items') or []
                if isinstance(it, dict)}
        self.telegram = AN.lists_for(_try(AN.numbers_path(datadir, 'telegram', date)), tsum)
        self.ledger = ledger if ledger is not None else F.load_ledger(repo)
        self.cycle_arg = cycle
        self.data = {}
        if market == 'us':
            md = _try(os.path.join(datadir, 'market_data.json'))
            if not isinstance(md, dict):
                raise S.InputError('market_data.json 이 없거나 읽지 못했다')
            if md.get('report_date') != date:
                raise S.InputError(f'market_data report_date {md.get("report_date")} 가 글 날짜 {date} 와 다르다')
            self.data = {'market_data': md}
            for k in ('econ_indicators', 'macro_metrics', 'fund_board'):
                v = _try(os.path.join(datadir, f'{k}.json'))
                if v is not None:
                    self.data[k] = v
            lq = _try(os.path.join(datadir, 'liquidity', 'liquidity.json'))
            if lq is not None:
                self.data['liquidity'] = lq

    def cycle_of(self, html):
        """(cycle id | None, 못 쓰는 이유). 일간은 글 속성, 뉴스 글은 같은 날 커밋된 일간의 그 속성."""
        if self.market == 'us':
            m = re.search(r'data-research-cycle="([^"]+)"', html)
            cyc = m.group(1) if m else None
        else:
            try:
                with open(os.path.join(self.repo, 'posts', f'{self.date}.html'), encoding='utf-8') as fh:
                    m = re.search(r'data-research-cycle="([^"]+)"', fh.read())
                cyc = m.group(1) if m else None
            except OSError:
                cyc = None
        if cyc is None:
            return None, 'cycle 을 찾지 못했다'
        if self.cycle_arg and self.cycle_arg != cyc:
            return None, '--cycle 과 글의 cycle 이 다르다'
        return cyc, ''

    def web_lists(self, cycle):
        """source_id → 숫자 목록 | None. 그 cycle 기록의 sources[].snapshot 만, sha256 이 이름과 같을 때."""
        out = {}
        if not cycle or self.ledger is None:
            return out
        rec = next((r for r in self.ledger if isinstance(r, dict) and r.get('id') == cycle), None)
        if rec is None or rec.get('market') != 'us' or rec.get('report_date') != self.date:
            return out
        for src in rec.get('sources') or []:
            sid, snap, sha = src.get('id'), src.get('snapshot'), src.get('sha256')
            try:
                with open(os.path.join(self.repo, 'research', 'us', snap), 'rb') as fh:
                    raw = fh.read()
            except (OSError, TypeError):
                out[sid] = None
                continue
            if hashlib.sha256(raw).hexdigest() != sha or snap != f'evidence/{sha}':
                out[sid] = None
                continue
            text = raw.decode('utf-8', 'replace')
            out[sid] = AN._norm_list(AN.english_numbers(text) + AN.korean_numbers(text))
        return out


# ── 분류 ────────────────────────────────────────────────────────────────

def _attr(n, a):
    return n.attrs.get(a)


def _anc(stack, pred):
    return next((n for n in reversed(stack) if pred(n)), None)


class Classifier:
    def __init__(self, inp, html):
        self.inp, self.html = inp, html
        self.book = F.Book(inp.datadir, inp.date, inp.ledger, None)
        self.detail = {k: 0 for k in ('dv', 'lvl', 'abs_refs', 'stale_refs', 'invalid_refs', 'article_common',
                                      'excluded_code', 'excluded_enum', 'zone_contested', 'zone_note', 'marker_empty')}
        self.web_by = {}
        self.declared = []
        self.cycle, self.cycle_why = inp.cycle_of(html)
        self.book.cycle = self.cycle
        self.web = inp.web_lists(self.cycle)

    def run(self):
        doc, kinds = self._parse()
        blocks = S.blocks_of(doc.stream)
        items, marker_q = [], {}
        per_block = []
        for b in blocks:
            qs = S.quantities(b.text, self.inp.terms)
            per_block.append((b, qs))
            for q in qs:
                for st in S.markers_over(b, q):
                    for m in st:
                        marker_q.setdefault(id(m), set()).add((id(b), q.start))
        # 표식 안에 수량이 없는 것 — 수량이 아니라 따로 센다
        all_markers = {id(n) for n in doc.nodes if S.is_marker(n)}
        self.detail['marker_empty'] = len(all_markers - set(marker_q))
        for b, qs in per_block:
            sents = S.sentences(b.text)
            for q in qs:
                cls, why = self._one(b, q, kinds, marker_q)
                a, e = next(((x, y) for x, y in sents if x <= q.start < y), (0, len(b.text)))
                in_sent = [x for x in qs if a <= x.start < e]
                items.append(S.Item(q, cls, why, 'body', S.mask_sentence(b.text, a, e, in_sent),
                                    next(i for i, x in enumerate(in_sent) if x is q)))
        # 제목·메타 — 같은 인쇄 꼴의 본문 수량 칸을 물려받는다(U·X 이면 U)
        shown = {}
        for it in items:
            if it.cls not in ('unknown', 'excluded') and not it.q.code:
                shown.setdefault(it.q.raw.strip(), it.cls)
        # 독립 재집계(설계 §2.1 불변식) — 수량 문법과 따로, 보이는 글의 숫자열을 다시 센다. 어긋나면 검사기 결함(exit 2)
        self.run_count = sum(len(S.runs(b.text)) for b, _ in per_block)
        for where, text in doc.extra:
            text = S.norm(text)
            self.run_count += len(S.runs(text))
            qs = S.quantities(text, self.inp.terms)
            sents = S.sentences(text)
            for q in qs:
                if q.code:
                    cls, why = 'excluded', 'code'
                    self.detail['excluded_code'] += 1
                else:
                    c = shown.get(q.raw.strip())
                    cls, why = (c, '본문과 같은 수량') if c else ('unknown', '표식 없음')
                a, e = next(((x, y) for x, y in sents if x <= q.start < y), (0, len(text)))
                in_sent = [x for x in qs if a <= x.start < e]
                items.append(S.Item(q, cls, why, where, S.mask_sentence(text, a, e, in_sent),
                                    next(i for i, x in enumerate(in_sent) if x is q)))
        return items

    def _parse(self):
        from us import number_audit as N
        if self.inp.market == 'us':
            trace = {}
            try:
                N.audit(self.html, self.inp.data, trace=trace)
            except N.InputError as e:
                raise S.InputError(str(e))
            return trace['doc'], trace['kinds']
        return N._Stream(self.html), {}

    def _one(self, b, q, kinds, marker_q):
        segs = b.segs_in(q.start, q.end)
        stacks = [s.stack for s in segs]
        allnodes = [n for st in stacks for n in st]
        if any('data-contested' in n.attrs or n.attrs.get('id') == 'contested' for n in allnodes):
            self.detail['zone_contested'] += 1
            return 'excluded', 'zone_contested'
        if any('data-editor-note' in n.attrs for n in allnodes):
            self.detail['zone_note'] += 1
            return 'excluded', 'zone_note'
        if segs and all(kinds.get(s.kind[0]) == 'T' for s in segs):
            return 'table', ''
        msets = [tuple(n for n in st if S.is_marker(n)) for st in stacks]
        union = {id(n): n for ms in msets for n in ms}
        if union:
            if len({tuple(id(n) for n in ms) for ms in msets}) != 1 or len(union) != 1:
                return 'unknown', '표식 오류'
            m = next(iter(union.values()))
            if len(marker_q.get(id(m), ())) != 1:
                return 'unknown', '표식 오류'
            return self._marked(m, q, stacks[0])
        if q.code:
            self.detail['excluded_code'] += 1
            return 'excluded', 'code'
        st = stacks[0] if stacks else []
        # 상속 자리(텔레그램·요약 문단·블록 제목)는 수량의 글자 전부가 같은 조상 안일 때만 — 「…5</span>%」처럼 경계에
        # 걸치면 표식 오류다(표식 경계 규칙과 같은 갈래)
        for pred in (lambda n: 'data-tg' in n.attrs, lambda n: 'data-news' in n.attrs,
                     lambda n: n.tag == 'p' and 'data-summary' in n.attrs,
                     lambda n: n.tag == 'p' and 'news-head' in n.attrs.get('class', '').split()):
            if len({id(_anc(x, pred)) for x in stacks}) > 1:
                return 'unknown', '표식 오류'
        tg = _anc(st, lambda n: 'data-tg' in n.attrs)
        if tg is not None:
            return self._match_list(self.inp.telegram.get(_attr(tg, 'data-tg')), q, 'telegram')
        news = _anc(st, lambda n: 'data-news' in n.attrs)
        summ = _anc(st, lambda n: n.tag == 'p' and 'data-summary' in n.attrs)
        if news is not None and summ is not None:
            g = _attr(news, 'data-news')
            if _attr(summ, 'data-summary') == g:
                pre = self._summary_prefix(b, g)
                if pre is not None and q.end <= pre:
                    return self._match_list(self.inp.article.get(g), q, 'article')
            return 'unknown', '표식 없음'
        head = _anc(st, lambda n: n.tag == 'p' and 'news-head' in n.attrs.get('class', '').split())
        if news is not None and head is not None and not _anc(st, lambda n: 'sub' in n.attrs.get('class', '').split()):
            return self._match_list(self.inp.article.get(_attr(news, 'data-news')), q, 'article')
        if any(n.tag == 'table' or any(a in n.attrs for a in _CODE_BLOCK_ATTRS) for n in st):
            return 'unknown', '코드 블록(표식 없음)'
        return 'unknown', '표식 없음'

    def _summary_prefix(self, b, guid):
        want = ' '.join(S.norm(self.inp.news_summary.get(guid) or '').split())
        if not want:
            return None
        text = b.text
        # 공백을 줄인 글이 요약으로 시작하면, 원래 글에서 요약 끝 자리를 찾는다
        pos, k = 0, 0
        while pos < len(text) and text[pos].isspace():
            pos += 1
        for ch in want:
            while pos < len(text) and text[pos].isspace() and ch != ' ':
                pos += 1
            if ch == ' ':
                if pos < len(text) and text[pos].isspace():
                    while pos < len(text) and text[pos].isspace():
                        pos += 1
                    continue
                return None
            if pos >= len(text) or text[pos] != ch:
                return None
            pos += 1
            k += 1
        return pos

    def _match_list(self, lst, q, cls):
        if q.code:
            self.detail['excluded_code'] += 1
            return 'excluded', 'code'
        if lst is None:
            return 'unknown', '목록 없음'
        if AN.in_list(q, lst):
            if cls == 'article' and not q.unit and q.value is not None and float(q.value).is_integer() \
                    and abs(q.value) <= S.COMMON_MAX:
                self.detail['article_common'] += 1
            return cls, ''
        return 'unknown', '기사 목록에 없음' if cls != 'web' else '발췌에 없음'

    def _marked(self, m, q, stack):
        if 'data-ref' in m.attrs:
            return self._ref(m.attrs['data-ref'], q)
        if 'data-nx' in m.attrs:
            return self._enum(m.attrs['data-nx'], q)
        src = m.attrs.get('data-src', '')
        if src == 'news' or src.startswith('news:'):
            if src == 'news':
                news = _anc(stack, lambda n: 'data-news' in n.attrs)
                if news is None:
                    return 'unknown', '표식 오류'
                g = _attr(news, 'data-news')
            else:
                g = src[5:]
            if g not in self.inp.article:
                return 'unknown', '목록 없음'
            return self._match_list(self.inp.article.get(g), q, 'article')
        if src.startswith('web:'):
            sid = src[4:]
            if self.cycle is None:
                return 'unknown', '목록 없음'
            got = self._match_list(self.web.get(sid), q, 'web')
            if got[0] == 'web':
                self.web_by[sid] = self.web_by.get(sid, 0) + 1
            return got
        return 'unknown', '표식 오류'

    def _enum(self, kind, q):
        ok = (kind == 'enum' and q.value is not None and not q.code and q.unit in S.COUNT_WORDS
              and float(q.value).is_integer() and 0 <= q.value <= 99 and not q.sign
              and not any(c in q.raw for c in ',.%'))
        if not ok:
            return 'unknown', '선언 무효'
        self.detail['excluded_enum'] += 1
        self.declared.append(S.clip(q.raw, 20))
        return 'excluded', 'enum'

    def _ref(self, ref, q):
        name, *flags = ref.split('|')
        flags = set(flags)
        if q.value is None or q.code:
            return 'unknown', '자료와 다름'
        try:
            f = self.book.resolve(name.strip())
        except F.Miss as e:
            if e.kind == '칸 무효':
                self.detail['invalid_refs'] += 1
            return 'unknown', e.kind
        if f.status == 'invalid':
            self.detail['invalid_refs'] += 1
            return 'unknown', '칸 무효'
        if not _shown_ok(q, f, flags):
            return 'unknown', '자료와 다름'
        if name.startswith('dv:'):
            self.detail['dv'] += 1
        if 'lvl' in flags:
            self.detail['lvl'] += 1
        if 'abs' in flags:
            self.detail['abs_refs'] += 1
        if f.status == 'stale':
            self.detail['stale_refs'] += 1
        return 'data', name


def _shown_ok(q, f, flags):
    """인쇄값이 칸 값을 정직하게 보였는가 — 값(인쇄 자리 반올림)·부호·단위·배율·어림선."""
    unit = q.unit
    conv = 1.0
    if unit in f.units:
        pass
    elif unit in f.conv:
        conv = f.conv[unit]
    elif 'lvl' in flags and unit in ('선', '대') and ('' in f.units or 'p' in f.units):
        pass
    else:
        return False
    exp = f.value * f.scale * conv
    got = q.value
    if 'lvl' in flags:
        if q.sig == 0 or q.sig > 2 or got is None:
            return False
        import math
        mag = abs(got)
        if mag == 0:
            return False
        step = 10 ** (math.floor(math.log10(mag)) - q.sig + 1)
        return abs(abs(got) - abs(exp)) <= step + 1e-9
    tol = 0.5 * q.quantum + 1e-9 * max(1.0, abs(exp))
    if q.sign:
        return abs(got - exp) <= tol
    if f.signed and exp < 0 and abs(exp) > tol and 'abs' not in flags:
        return False                       # 부호 있는 음수 칸을 부호 없이 — |abs 를 단다
    return abs(abs(got) - abs(exp)) <= tol


# ── 한 판 ───────────────────────────────────────────────────────────────

def classify(inp, html):
    c = Classifier(inp, html)
    items = c.run()
    return c, items


def result(inp, html, first_html=None):
    """게이트 결과(사전) — `sources` 칸. InvariantError·InputError 는 그대로 올린다."""
    c, items = classify(inp, html)
    q, r = S.tally(items)
    if r['total'] != c.run_count:
        raise S.InvariantError(f'숫자열 {c.run_count}개 중 {r["total"]}개만 수량에 들었다')
    unknown = [it for it in items if it.cls == 'unknown']
    by = {}
    for it in unknown:
        by[it.why] = by.get(it.why, 0) + 1
    hist, first_sha = 'unverifiable', None
    why_hist = ''
    if first_html is not None:
        path_kind, d = S.canonical_of(first_html)
        want = 'posts' if inp.market == 'us' else 'news'
        if (path_kind, d) != (want, inp.date):
            why_hist = '첫 판이 이 글의 날짜·시장이 아니다'
        else:
            try:
                _, f_items = classify(inp, first_html)
                hist = S.history(f_items, items)
                first_sha = S.sha256_text(first_html)
            except (S.InputError, S.InvariantError) as e:
                why_hist = f'첫 판을 분류하지 못했다 — {e}'
    else:
        why_hist = '첫 판이 없다'
    return {
        'format': S.FORMAT, 'market': inp.market, 'date': inp.date,
        'counts': q, 'runs': r, 'detail': dict(c.detail),
        'unknown_by': {k: v for k, v in sorted(by.items(), key=lambda kv: -kv[1]) if k in S.U_REASONS},
        'web_by': dict(sorted(c.web_by.items())),
        'unknown': [{'text': S.clip(_context(it)), 'why': it.why} for it in unknown[:S.UNKNOWN_LIST]],
        'unknown_total': len(unknown),
        'declared': c.declared[:40],
        'dv_list': [S.clip(x, 80) for x in c.book.dv_used[:40]],
        'history': hist, 'history_why': why_hist, 'first_sha256': first_sha,
        'cycle': c.cycle, 'cycle_why': c.cycle_why,
    }


def _context(it):
    return it.q.raw if it.where != 'body' else it.q.raw + ' — ' + it.sentence.replace('#', '·')[:60]
