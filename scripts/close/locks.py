"""판단 문장 잠금 규칙(B안) — 후보 제외와 편집 검사가 같은 규칙을 쓴다.

  Z  판단 구역    section(data-research-cycle·data-learning·data-section="review"·data-research-summary)
                  안이거나 p 가 data-hypothesis·lede·interp·alt·watch·falsifier·cause·standing
  V  판단 어휘    판단·상태·확인 기준 어휘가 든 문장
  L  원장 앵커    그날까지의 연구 원장 support·invalidation 소수 문턱, 판단(M월 D일)·deadline 날짜
  T  기간         「N일 … 까지·부터·대비·기준」
  D  지시어       이·그·같은·해당·이번·이날·당시 의 개수
  C  통제 어휘    prose_swap.CONTROLLED 의 순서

원본: 2026-11-05 수정안 507건 재연(`style-meaning-check-replay-2026-11-05/replay.py`, 레포 밖) —
판단 변경 10건을 모두 잡았다. **표본 안 성적이다**(그 10건을 보고 어휘를 만들었다).
"""

import datetime
import json
import os
import re
from collections import Counter
from html.parser import HTMLParser

from us.prose_swap import CONTROLLED, _plain

ZONE_SEC = re.compile(r'data-research-cycle|data-learning|data-section\s*=\s*"review"|data-research-summary',
                      re.I)
ZONE_P = re.compile(r'\bdata-(hypothesis|lede|interp|alt|watch|falsifier|cause|standing)\b', re.I)

_SPL = re.compile(r'(?<=[다요음임함]\.)\s+|(?<=\.)\s+(?=[가-힣A-Z0-9(])')


def sentences(text):
    """평문 → 문장 목록(공백 정리). 자리표·태그는 지운 뒤 나눈다."""
    return [' '.join(s.split()) for s in _SPL.split(_plain(text)) if s.strip()]


V_RE = re.compile(
    r'판단|해석|뒷받침|지지(?:되|한다|하|를)|약해|약화|철회|보류|결론|유효|반론|전제|가설|'
    r'출발점|확인 기준|확인일|정본|우선 설명|다음 확인|(?:고|로|라고|으로)\s*본다|(?:로|으로)\s*본\s|'
    r'쪽이다|쪽에|쪽이지만|쪽으로|가능성이 (?:커|크|높)|이르다|단정|설명(?:이|은|으로)|근거(?:가|는|로)|'
    r'넘어갔|닫혔|닫는다|기준(?:에|을|이|은|값)|조건(?:이|은|을)|확인(?:되지|하지|할)|가르지')
T_RE = re.compile(r'\d+일\s*(?:KRX |정규장 |네이버 )?(?:종가|개장|16:00|17:05)?[^.]{0,6}(?:까지|부터|대비|기준)')
DEM_RE = re.compile(r'(?<![가-힣])(이|그|같은|해당|이번|이날|당시)\s')
_CTRL = re.compile('|'.join(sorted(map(re.escape, CONTROLLED), key=len, reverse=True)))
_ZONES = {'us': 'America/New_York', 'kr': 'Asia/Seoul'}


def v_lock(sentence):
    return bool(V_RE.search(sentence))


def t_lock(sentence):
    return bool(T_RE.search(sentence))


class Ledger:
    """연구 원장의 잠금 앵커 — 글 날짜까지의 가설 기록만 본다. 원장이 없으면 L 은 아무것도 잠그지 않는다."""

    def __init__(self, records=(), market='us', post_date='2099-12-31'):
        self.nums, self.dates = set(), set()
        try:
            from zoneinfo import ZoneInfo
            local = ZoneInfo(_ZONES.get(market, 'UTC'))
        except Exception:  # zoneinfo 없는 환경 — UTC 날짜만 쓴다
            local = datetime.timezone.utc
        for r in records:
            if not isinstance(r, dict) or r.get('type') != 'hypothesis':
                continue
            if str(r.get('report_date', '')) > post_date:
                continue
            for k in ('support', 'invalidation'):
                for n in re.findall(r'\d+\.\d+\s*(?:%p|%포인트|bp)', str(r.get(k, ''))):
                    self.nums.add(n.replace(' ', '').replace('%포인트', '%p'))
            try:
                _, mo, d = str(r['report_date']).split('-')
                self.dates.add((int(mo), int(d)))
            except (KeyError, ValueError):
                pass
            try:
                dl = datetime.datetime.fromisoformat(str(r['deadline']).replace('Z', '+00:00'))
                for z in (datetime.timezone.utc, local):
                    x = dl.astimezone(z)
                    self.dates.add((x.month, x.day))
            except (KeyError, ValueError, TypeError):
                pass

    @classmethod
    def load(cls, root, market, post_date):
        path = os.path.join(root, 'research', market, 'ledger.jsonl') if root else ''
        rows = []
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8') as fh:
                for line in fh:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        return cls(rows, market, post_date)

    def lock(self, sentence):
        squeezed = sentence.replace(' ', '').replace('%포인트', '%p')
        if any(n in squeezed for n in self.nums):
            return True
        return any(re.search(r'판단\(\s*%d월 %d일\s*\)|(?<!\d)%d월 %d일 (?:KRX |정규장 |네이버 )?'
                             r'(?:종가|개장|16:00|17:05)' % (mo, d, mo, d), sentence)
                   for mo, d in self.dates)


NO_LEDGER = Ledger()


def locked(text, ledger=NO_LEDGER):
    """V·L·T 에 걸리는 문장 — 순서 있는 목록. 같아야 통과한다(바꿈·삭제·병합·분리·순서·추가 모두 걸린다)."""
    return [s for s in sentences(text) if v_lock(s) or t_lock(s) or ledger.lock(s)]


# 판단의 주인 — 누가 그렇게 봤나·말했나. 10/13 「언론은 … 우리는 …」 맞바꾸기가 판단 어휘만으로는 안 걸렸다.
ATTR_RE = re.compile(r'우리|언론|보도|시장(?:은|이|에서는)|증권가|애널리스트|연준|의장|정부|당국|회사|'
                     r'전했다|밝혔다|말했다|설명했다|주장했다|보도했다|평가했다|분석했다|판단한다')


def judgment_skeleton(text, ledger=NO_LEDGER):
    """판단 문장의 뼈대 — (판단 문장 수, 판단 어휘·기간·원장 앵커가 나온 순서).

    발행 전 codex 검토의 「번역투」 후보만 이것으로 본다(`guard.check_edit(relax=True)`): 판단 문장의 낱말은
    고칠 수 있되, 판단 문장을 합치거나 쪼개지 않고 판단을 싣는 표지(본다·쪽이다·약해·철회·확인 기준 …,
    「N일 … 까지」, 원장 문턱·날짜, 판단의 주인 — 우리·언론·보도·전했다 …)를 같은 순서·개수로 남겨야 한다.
    「약해진다→철회한다」·「본다→다」·「언론은 … 우리는 …」 맞바꾸기는 여기서 걸린다. 그 밖의 뼈대(수치·이름·방향·부정·비교·인과·한계·판단 어휘·지시어)는 guard 가 따로 본다.
    """
    marks = []
    sents = locked(text, ledger)
    for sent in sents:
        hits = [(m.start(), m.group(0)) for m in V_RE.finditer(sent)]
        hits += [(m.start(), 'T:' + m.group(0)) for m in T_RE.finditer(sent)]
        hits += [(m.start(), 'A:' + m.group(0)) for m in ATTR_RE.finditer(sent)]
        squeezed = sent.replace(' ', '').replace('%포인트', '%p')
        hits += [(10 ** 6, 'L:' + n) for n in sorted(ledger.nums) if n in squeezed]
        marks.extend(h for _, h in sorted(hits))
    return len(sents), marks


# 범위·세기·한계 낱말 — 판단 문단(발행 전 검토가 연 문단)에서는 문단 전체에서 순서·개수가 같아야 한다.
# 「일시적→지속적」「일부→모든」「다만 … 불확실하다 → … 확실하다」가 판단 문장을 그대로 둔 채 뜻을 바꿨다
# (codex 구현 검토 #5). 「불확실」은 「확실」보다 먼저 맞춘다.
SCOPE_RE = re.compile(r'일부|모든|전부|전체|대부분|대체로|일시적|일시|지속적|지속|불확실|확실|아직|이미|여전히|'
                      r'다만|반면|그러나|하지만|그래도|적어도|최소|최대|상당|소폭|크게|다소|약간|가장|'
                      r'가능성|우려|기대|예상|추정|잠정')


# 수량어 + 조사가 붙는 데까지의 명사구(네 어절까지) — 「일부 반도체 업종은」 전체가 한 표지다(재검토 3차 #2).
_QUANT = re.compile(r'(일부|모든|전부|전체|대부분)\s*((?:[^\s.,]+\s+){0,3}?[^\s.,]*?'
                    r'(?:은|는|이|가|을|를|에서|에|도|만)(?=[\s.,]|$)|[^\s.,]+)?')   # 「의」「과·와」는 명사구 안이다


def scope_marks(text):
    """범위·세기·한계 낱말의 순서 — 수량어(일부·모든·전부·전체·대부분)는 바로 뒤 낱말까지 붙인다.

    「일부 업종은 … 모든 종목은」 → 「일부 종목은 … 모든 업종은」 대상 맞바꾸기(codex 구현 재검토 #5).
    """
    plain = _plain(text)
    marks = SCOPE_RE.findall(plain)
    quants = [f'{q}:{w or ""}' for q, w in _QUANT.findall(plain)]
    return marks + quants


def demonstratives(text):
    return Counter(DEM_RE.findall(_plain(text)))


def ctrl_order(text):
    return _CTRL.findall(_plain(text))


_ZONE_NAMES = ('data-research-cycle', 'data-learning', 'data-research-summary')


def zone_attrs(attrs):
    """파싱된 속성으로 판정 — 따옴표 꼴(큰·작은·없음)에 상관없이(codex 구현 검토 #8)."""
    for k, v in attrs:
        k = (k or '').lower()
        if k in _ZONE_NAMES or (k == 'data-section' and (v or '').strip().lower() == 'review'):
            return True
    return False


class _Zones(HTMLParser):
    """판단 구역(Z)의 (시작, 끝) 문자 오프셋. 못 닫힌 구역은 문서 끝까지 — 덜 거는 쪽이 안전하다."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        for line in html.split('\n'):
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.stack, self.spans = [], []
        self.feed(html)
        self.close()
        self.spans.extend((start, len(html)) for _, start, z in self.stack if z)

    def _here(self):
        row, col = self.getpos()
        return self.offsets[row - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag != 'section':
            return
        self.stack.append((tag, self._here(), zone_attrs(attrs)))

    def handle_endtag(self, tag):
        if tag != 'section' or not self.stack:
            return
        end = self._here() + len('</section>')
        _, start, z = self.stack.pop()
        if z:
            self.spans.append((start, end))


def zone_spans(html):
    try:
        return _Zones(html).spans
    except Exception:
        return [(0, len(html))]


def zone_p(p_attrs):
    return bool(ZONE_P.search(p_attrs or ''))
