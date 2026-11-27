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

    def __init__(self, market, date, datadir, repo, tg=None, cycle=None, ledger=None, fill_effective=None):
        self.market, self.date, self.datadir, self.repo = market, date, datadir, repo
        # 막는 판(설계 「숫자는 코드가 채운다」 1차) — US 일간·적용일 이후 글만. us-news 와 그 전 글은 지금 판정 그대로
        self.blocking = market == 'us' and date >= (fill_effective or S.FILL_EFFECTIVE)
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
        self.blocking = getattr(inp, 'blocking', False)
        self.declared_set = []           # data-nx="set" — 작성자가 정한 문턱(조건 문단 안), 대조하지 않고 목록만
        self.zones = None
        if self.blocking:
            from us import zones as Z
            try:
                self.zones = Z.load()
            except Z.ConfigError as e:
                raise S.InputError(str(e))

    def run(self):
        doc, kinds = self._parse()
        blocks = S.blocks_of(doc.stream)
        items, marker_q = [], {}
        per_block = []
        for b in blocks:
            qs = _quantities(b.text, self.inp)
            if getattr(self.inp, 'blocking', False):
                qs = sorted(qs + S.korean_quantities(b.text), key=lambda q: q.start)
            per_block.append((b, qs))
            for q in qs:
                for st in S.markers_over(b, q):
                    for m in st:
                        marker_q.setdefault(id(m), set()).add((id(b), q.start))
        # 표식 안에 수량이 없는 것 — 수량이 아니라 따로 센다
        all_markers = {id(n) for n in doc.nodes if S.is_marker(n)}
        self.body_refs = {n.attrs.get('data-ref', '').split('|')[0].strip() for n in doc.nodes if 'data-ref' in n.attrs}
        self.detail['marker_empty'] = len(all_markers - set(marker_q))
        titles = {}
        if self.blocking:
            from us import number_audit as N
            titles = {id(n): (t or '') for n, t, _ in N._sections(doc)}
        for b, qs in per_block:
            sents = S.sentences(b.text)
            for q in qs:
                self._fact = None
                cls, why = self._one(b, q, kinds, marker_q)
                a, e = next(((x, y) for x, y in sents if x <= q.start < y), (0, len(b.text)))
                key, idx = _sent_key(b.text, a, e, [x for x in qs if a <= x.start < e], q, self.blocking)
                it = S.Item(q, cls, why, 'body', key, idx,
                            full_sentence=' '.join(b.text[a:e].split()), in_code=_in_code(b, q))
                if self.blocking:
                    self._annotate(it, b, q, titles)
                items.append(it)
        # 제목·메타 — 같은 인쇄 꼴의 본문 수량 칸을 물려받는다(U·X 이면 U)
        shown = {}
        for it in items:
            if it.cls not in ('unknown', 'excluded') and not it.q.code:
                shown.setdefault(it.q.raw.strip(), it.cls)
        # 독립 재집계(설계 §2.1 불변식) — 수량 문법과 따로, 보이는 글의 숫자열을 다시 센다. 어긋나면 검사기 결함(exit 2)
        self.run_count = sum(len(S.runs(b.text)) for b, _ in per_block)
        head = self._head_refs() if self.blocking else {}
        for where, text in doc.extra:
            text = S.norm(text)
            self.run_count += len(S.runs(text))
            qs = _quantities(text, self.inp)
            refs = head.get((where, text)) if where in ('title', 'meta') else None
            if refs is not None:
                qs = sorted(qs + S.korean_quantities(text), key=lambda q: q.start)
                vals = [q for q in qs if not q.code]
                pairs = dict(zip((id(q) for q in vals), refs)) if len(vals) == len(refs) else {}
            sents = S.sentences(text)
            for q in qs:
                self._fact = None
                if refs is not None and not q.code:
                    cls, why = self._head_one(q, text, pairs.get(id(q)))
                elif q.code:
                    cls, why = 'excluded', 'code'
                    self.detail['excluded_code'] += 1
                else:
                    c = shown.get(q.raw.strip())
                    cls, why = (c, '본문과 같은 수량') if c else ('unknown', '표식 없음')
                a, e = next(((x, y) for x, y in sents if x <= q.start < y), (0, len(text)))
                key, idx = _sent_key(text, a, e, [x for x in qs if a <= x.start < e], q, self.blocking)
                it = S.Item(q, cls, why, where, key, idx, full_sentence=' '.join(text[a:e].split()))
                if self.blocking:
                    it.detail.update(zone=self._head_zone(), ref=refs is not None and not q.code)
                    self._take_fact(it)
                    if it.detail.get('stale') and not text[q.end:].startswith(_asof_text(it.detail['stale'])):
                        it.detail['no_asof'] = True
                items.append(it)
        return items

    # ── 막는 판(숫자는 코드가 채운다 1차) ──

    def _annotate(self, it, b, q, titles):
        segs = b.segs_in(q.start, q.end)
        stack = segs[0].stack if segs else []
        sec = next((n for n in stack if n.tag == 'section'), None)
        from us import zones as Z
        name, mode = Z.zone_of(self.zones, titles.get(id(sec), '') if sec is not None else '')
        it.detail.update(zone=(name, mode))
        it.detail['ref'] = any('data-ref' in n.attrs for st in S.markers_over(b, q) for n in st)
        self._take_fact(it)
        if it.detail.get('stale') and not any(n.tag in ('td', 'th') for n in stack):
            # 관측일이 글 날짜와 다른 칸 — 숫자 바로 뒤에 코드가 찍은 기준일이 있어야 한다(fill_numbers)
            nxt = b.segs_in(q.end, q.end + 1)
            ok = bool(nxt) and any(n.attrs.get('data-asof') == it.detail['stale'] for n in nxt[0].stack) and \
                b.text[q.end:].startswith(_asof_text(it.detail['stale']))
            if not ok:
                it.detail['no_asof'] = True

    def _take_fact(self, it):
        f = getattr(self, '_fact', None)
        if f is None or it.cls not in ('data', 'level'):
            return
        name = self._fact_ref
        it.detail['fill'] = {'ref': name, 'asset': f.asset, 'group': '.'.join(str(x) for x in f.group[1:2]),
                             'field': f.fld, 'date': f.date[:10] if isinstance(f.date, str) else None,
                             'value': f.value, 'text': it.q.raw}
        # 기준일은 관측일이 글 날짜와 다를 때만 — 계산값(dv)은 첫 칸의 날짜를 지니므로 그 날짜가 글 날짜면 찍지 않는다
        if f.status == 'stale' and isinstance(f.date, str) and f.date[:10] != self.inp.date:
            it.detail['stale'] = f.date[:10]

    def _head_zone(self):
        from us import zones as Z
        return Z.zone_of(self.zones, '')

    def _head_refs(self):
        """(자리, 글) → 이름표 목록 — fill_numbers 가 og:title·og:description meta 의 `data-refs` 에 적은 것."""
        from us import fill as FL
        out = {}
        m, ogt = FL._TITLE.search(self.html), FL._OGT.search(self.html)
        if m and ogt:
            refs = FL.head_refs(ogt.group('attrs'))
            if refs is not None:
                out[('title', S.norm(S.unescape(m.group('text'))))] = refs
        m = FL._OGD.search(self.html)
        if m:
            refs = FL.head_refs(m.group('attrs'))
            if refs is not None:
                out[('meta', S.norm(S.unescape(m.group('text'))))] = refs
        self.head_ref_names = [r for v in out.values() for r in v]
        return out

    def _head_one(self, q, text, ref):
        if ref is None:
            return 'unknown', '표식 오류'          # 숫자 수와 이름표 수가 다르다
        return self._ref(ref, q)

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
        in_table = bool(segs) and all(kinds.get(s.kind[0]) == 'T' for s in segs)
        # 표식이 있으면 표 대조(T)보다 **먼저** 표식을 본다(codex 구현 1회 #2·#3·#6) — 표 칸이 맞았다고 깨진 표식
        # (개수·겹침·경계)이나 없는 칸을 가리키는 표식이 「표 대조」로 묻히지 않게. 맞는 표식이 표 칸에 있으면 T 다
        # (표 칸 대조가 더 강한 확인 — 표식 쪽 내역은 세지 않는다). 단 어림선(`|lvl`)은 표 칸에서도 배타 칸 level 로
        # 남긴다(codex 구현 2회 #16) — 작성자가 어림이라고 표시한 숫자를 「자료로 확인」에 섞지 않는다
        msets = [tuple(n for n in st if S.is_marker(n)) for st in stacks]
        union = {id(n): n for ms in msets for n in ms}
        if union:
            if len({tuple(id(n) for n in ms) for ms in msets}) != 1 or len(union) != 1:
                return 'unknown', '표식 오류'
            m = next(iter(union.values()))
            if len(marker_q.get(id(m), ())) != 1:
                return 'unknown', '표식 오류'
            saved = (dict(self.detail), dict(self.web_by), list(self.declared), list(self.book.dv_used))
            got = self._marked(m, q, stacks[0])
            if got[0] in ('unknown', 'level') or not in_table:
                return got
            self.detail, self.web_by, self.declared, self.book.dv_used = (
                saved[0], saved[1], saved[2], saved[3])
            return 'table', ''
        if in_table:
            return 'table', ''
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
        if _code_node(st):
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
            if self.blocking and m.attrs['data-nx'] == 'set':
                return self._set(q, stack)
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
        # 배율(천·만·억·조, K·M·B)이 붙은 값은 나열 수가 아니다(codex 구현 1회 #7 — 「0천개」)
        ok = (kind == 'enum' and q.value is not None and not q.code
              and (q.unit in S.COUNT_WORDS or (q.korean and q.unit in S.KO_COUNTERS + ('',)))
              and float(q.value).is_integer() and 0 <= q.value <= 99 and not q.sign and q.scale == 1.0
              and (len(q.runs) == 1 or q.korean) and not re.search(r'[,.%천만억조KMB]', q.raw))
        if not ok:
            return 'unknown', '선언 무효'
        self.detail['excluded_enum'] += 1
        self.declared.append(S.clip(q.raw, 20))
        return 'excluded', 'enum'

    def _set(self, q, stack):
        """작성자가 정한 문턱(「30년물이 5.05%를 밑돌면」) — 조건 문단(`data-falsifier`·`data-macro-group`) 안에서만.
        대조하지 않는다(자료 값이 아니다) — 목록을 기록에 싣는다."""
        cond = any('data-falsifier' in n.attrs or 'data-macro-group' in n.attrs for n in stack)
        if not cond or q.value is None or q.code:
            return 'unknown', '선언 무효'
        self.detail['excluded_set'] = self.detail.get('excluded_set', 0) + 1
        self.declared_set.append(S.clip(q.raw, 20))
        return 'excluded', 'set'

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
        if not _shown_ok(q, f, flags) or (self.blocking and not _strict_ok(q, f, flags)):
            return 'unknown', '자료와 다름'
        self._fact, self._fact_ref = f, ref
        if name.startswith('dv:'):
            self.detail['dv'] += 1
        if 'lvl' in flags:
            self.detail['lvl'] += 1
        if 'abs' in flags:
            self.detail['abs_refs'] += 1
        if f.status == 'stale':
            self.detail['stale_refs'] += 1
        # 어림선(「7,000선」)은 쓰게 두되 「자료로 확인」에 섞지 않는다 — 그 확인은 자릿수 범위뿐이다(11/21 사용자)
        return ('level' if 'lvl' in flags else 'data'), name


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
        # 부호까지 본다(codex 구현 1회 범위 밖 제안) — 「-7,000선」이 양수 칸에 맞지 않게. 부호 없는 인쇄는 양수로 읽는다
        return abs(got - exp) <= step + 1e-9
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


# 막는 판의 위반(설계 「숫자는 코드가 채운다」 §2) — 어느 구역이든 칸을 단 숫자가 칸과 맞지 않는 것,
# block 구역에서는 칸 없이 쓴 자료 숫자도. 기사·텔레그램·검색 발췌 대조(목록에 없음 등)는 지금처럼 막지 않는다
V_ANYWHERE = frozenset({'자료와 다름', '표식 오류', '칸 무효'})
V_BLOCK = frozenset({'표식 없음', '코드 블록(표식 없음)', '칸 없음', '선언 무효'})


def violations(items, c, f_items=None, removed=()):
    """→ (위반 줄 목록, 지운 숫자 요약). 막는 판에서만 부른다."""
    out = []

    def line(kind, it):
        zone = (it.detail.get('zone') or ('', ''))[0]
        where = '' if it.where == 'body' else f'({it.where}) '
        return f'{kind} [{zone}] {where}{it.q.raw} — {S.clip(it.full_sentence, 80)}'
    for it in items:
        zone, mode = it.detail.get('zone') or ('', 'warn')
        if it.cls == 'unknown' and (it.why in V_ANYWHERE or (mode == 'block' and it.why in V_BLOCK)):
            out.append(line(it.why, it))
        if it.detail.get('no_asof'):
            out.append(line('기준일 없음', it))
    for r in getattr(c, 'head_ref_names', []):
        if r.split('|')[0].strip() not in c.body_refs:
            out.append(f'본문에 없는 이름표 [제목·설명] {r} — 제목·설명의 칸은 본문에도 칸으로 있어야 한다')
    removal = None
    if f_items is not None:
        removal = {'followed': 0, 'gone': 0, 'ambiguous_absent': 0, 'listed': len(removed), 'matched': 0,
                   'unlisted': [], 'reasons': {}, 'wanted': []}
        for x in removed:
            removal['reasons'][x['reason']] = removal['reasons'].get(x['reason'], 0) + 1
        pool = {}
        for x in removed:
            k = S.removed_key(x['number'], x['sentence'])
            pool[k] = pool.get(k, 0) + 1
        final_raw = {it.q.raw.strip() for it in items}
        follow = lambda it: it.cls == 'unknown' or it.detail.get('ref')     # noqa: E731
        for it, fate in S.fates(f_items, items, follow):
            removal['followed'] += 1
            need = fate == 'gone' or (fate == 'ambiguous' and it.q.raw.strip() not in final_raw)
            if not need:
                continue
            removal['gone' if fate == 'gone' else 'ambiguous_absent'] += 1
            k = S.removed_key(it.q.raw, it.full_sentence)
            if pool.get(k):
                pool[k] -= 1
                removal['matched'] += 1
                continue
            removal['unlisted'].append(S.clip(it.q.raw, 20))
            # 작성자가 removed.json 에 그대로 옮길 짝(첫 판 문장 — 검사 출력에만, 기록기는 옮기지 않는다)
            removal['wanted'].append({'number': it.q.raw, 'sentence': it.full_sentence})
            # 첫 판 문장은 싣지 않는다(공개된 적 없는 초안 — 설계 2026-11-20 §7.3). 숫자와 구역만
            zone = (it.detail.get('zone') or ('', ''))[0]
            out.append(f'적지 않은 삭제 [{zone}] {it.q.raw} — 첫 판에 있던 숫자가 사라졌는데 removed 목록에 없다')
        removal['unlisted'] = removal['unlisted'][:40]
    return out, removal


def result(inp, html, first_html=None, removed=()):
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
    first_items = None
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
                first_items = f_items
            except (S.InputError, S.InvariantError) as e:
                why_hist = f'첫 판을 분류하지 못했다 — {e}'
    else:
        why_hist = '첫 판이 없다'
    extra = {}
    if c.blocking:
        viols, removal = violations(items, c, first_items, removed)
        extra = {'blocking': True, 'violations': viols, 'removal': removal,
                 'declared_set': c.declared_set[:40],
                 'fills': [it.detail['fill'] for it in items if it.detail.get('fill')],
                 'zones': _zone_counts(items)}
    return {**extra,
        'format': S.FORMAT, 'market': inp.market, 'date': inp.date,
        'counts': q, 'runs': r, 'detail': dict(c.detail),
        'unknown_by': {k: v for k, v in sorted(by.items(), key=lambda kv: -kv[1]) if k in S.U_REASONS},
        'web_by': dict(sorted(c.web_by.items())),
        'unknown': [{'text': S.clip(_context(it)), 'why': it.why} for it in unknown[:S.UNKNOWN_LIST]],
        'unknown_total': len(unknown),
        'unknown_all': _unknown_all(unknown),
        'declared': c.declared[:40],
        'dv_list': [S.clip(x, 80) for x in c.book.dv_used[:40]],
        'history': hist, 'history_why': why_hist, 'first_sha256': first_sha,
        'cycle': c.cycle, 'cycle_why': c.cycle_why,
    }


def _zone_counts(items):
    """구역마다 (모드, 숫자 수, 확인 불가 수) — 알림·시운전 보고용."""
    out = {}
    for it in items:
        zone, mode = it.detail.get('zone') or ('', 'warn')
        z = out.setdefault(zone, {'mode': mode, 'total': 0, 'unknown': 0, 'data': 0})
        z['total'] += 1
        z['unknown'] += it.cls == 'unknown'
        z['data'] += it.cls in ('data', 'level')
    return out


_ASOF_RX = re.compile(r'\(\d{1,2}월 \d{1,2}일 기준\)')


def _sent_key(text, a, e, in_sent, q, blocking):
    """(가린 문장, 문장 안 몇째 수량) — 수정 이력 대응 열쇠. 막는 판에서는 코드가 찍은 기준일 「(M월 D일 기준)」을 문장
    열쇠와 순번에서 뺀다 — 첫 판(채우기 전 초안)과 채운 최종본이 같은 문장으로 짝지어지게."""
    if not blocking:
        return S.mask_sentence(text, a, e, in_sent), next(i for i, x in enumerate(in_sent) if x is q)

    def stamp(x):
        return x.code == 'date' and x.start > 0 and _ASOF_RX.match(text, x.start - 1) is not None
    kept = [x for x in in_sent if not stamp(x)]
    key = _ASOF_RX.sub('', S.mask_sentence(text, a, e, kept))
    return ' '.join(key.split()), next((i for i, x in enumerate(kept) if x is q), -1)


def _asof_text(date):
    return f'({int(date[5:7])}월 {int(date[8:10])}일 기준)'


def _strict_ok(q, f, flags):
    """막는 판의 대조 — 채우기(`us/fill.py`)와 따로 짠 같은 규칙: 칸 값을 쓴 자리로 half-up 한 번 반올림한 값이 쓴 값과
    **같아야** 한다(반 자리 허용 없음). `|abs` 는 음수 칸에만, 0 이 아닌 값이 0 으로 찍히면 아님, 어림선은 쓴 유효 자리로 내림."""
    from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
    import math
    unit = q.unit
    conv = 1.0 if unit in f.units else f.conv.get(unit, 1.0)
    exp = f.value * f.scale * conv
    if 'abs' in flags:
        if not exp < 0 or q.sign:
            return False
        exp = -exp
    elif exp < 0 and not q.sign:
        return False
    if q.korean:
        return float(q.value) == exp
    if len(q.runs) != 1:
        return False
    a, b = q.runs[0]
    run = q.raw[a - q.start:b - q.start]
    written = Decimal(('0' + run) if run.startswith('.') else run.replace(',', ''))
    dec = len(run.split('.')[1]) if '.' in run else 0
    mag = Decimal(repr(abs(exp) / (q.scale or 1.0)))
    if 'lvl' in flags:
        if mag == 0 or not 1 <= q.sig <= 2:
            return False
        step = Decimal(10) ** (math.floor(math.log10(float(mag))) - q.sig + 1)
        want = (mag / step).to_integral_value(rounding=ROUND_FLOOR) * step
    else:
        want = mag.quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
        if want == 0 and mag != 0:
            return False
    if q.sign and want != 0 and (q.sign == '-') != (exp < 0):
        return False
    return written == want


def _quantities(text, inp):
    """끈 판은 지금 문법 그대로, 막는 판은 기간 이름(「1주 전」「3개월」)도 세지 않는 숫자로."""
    if getattr(inp, 'blocking', False):
        return S.quantities(text, inp.terms, periods=True)
    return S.quantities(text, inp.terms)


def _code_node(stack):
    return any(n.tag == 'table' or any(a in n.attrs for a in _CODE_BLOCK_ATTRS) for n in stack)


def _in_code(b, q):
    """1 = 수량의 글자가 표·코드 블록 안(이유 「코드 블록(표식 없음)」과 같은 조상 판정 — 그 판정은 첫 글자 조각만 본다)."""
    segs = b.segs_in(q.start, q.end)
    return 1 if segs and _code_node(segs[0].stack) else 0


def _unknown_all(unknown):
    """대조 못 한 숫자 **전부**, 글 순서(본문 흐름 → 제목·메타·대체 문구) — 배열 자리가 곧 순번이다(2026-11-27 설계 v3 §H).
    `n` 인쇄 꼴 · `s` 가리지 않은 문장(표·코드 블록이면 그 블록 글) · `why` · `w` 자리(body·title·meta·alt) · `t` 표·코드 블록."""
    return [{'n': it.q.raw, 's': S.clip(it.full_sentence, S.UNKNOWN_ALL_LEN), 'why': it.why, 'w': it.where,
             't': it.in_code} for it in unknown]


def _context(it):
    return it.q.raw if it.where != 'body' else it.q.raw + ' — ' + it.sentence.replace('#', '·')[:60]
