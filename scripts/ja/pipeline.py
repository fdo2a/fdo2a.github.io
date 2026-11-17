"""글 하나를 끝까지 — 원본 → 뉴스 원문화 → 단위 → 번역 → 기계 검사 → 검토 → 고치기 → 조립 → 문서 검사.

`build_page(root, path, *, sidecar, translate, review, cfg)` 는 파일을 쓰지 않는다. 결과의 `sidecar` 를
저장하고 `html_ja` 를 쓰는 것은 부르는 쪽(`scripts/ja_local.py`, 다음 작업자의 러너)이다.
`translate`·`review` 는 주입한다 — 시험은 가짜, 실제는 `real_translate()`·`real_review()`.

상태:
- `ready`   — `html_ja` 가 있다. 사이드카의 이번 단위는 `reviewed`(검토를 껐으면 `translated`).
- `held`    — 사람이 봐야 한다(뉴스 기록 없음, 기계 검사·검토 지적이 남음, 확인 안 된 인명, 검토 실패,
              문서 검사 실패). `reason` 이 한 줄 이유, `detail` 이 항목.
- `pending` — 한도(또는 모델 오류)로 멈췄다. 다음에 잇는다. 반쯤 된 글은 `html_ja` 를 내지 않는다.

`detail["stop"]` 이 멈춘 까닭의 고정 코드다(러너가 재시도·알림을 가른다): news_missing · news_lang ·
news_malformed · gate · names · review_failed · blocking · fixed · missing_units · doc · limit · model · auth ·
budget. `ready` 에는 없다. 새 코드의 `reason` 은 짧은 고정 꼴 + 단위 번호까지만(지적문·오류 원문은 `detail`).
`limit`·`model` 은 오류 문구를 그대로 둔다 — 러너가 `limit` 문구에서 재개 시각을 읽는다.

한도·모델 오류·로그인 만료·예산(`Config.token_cap`)으로 멈춰도 그때까지 쓴 토큰(`Result.tokens`)과 기계 검사를
통과한 번역(`Result.sidecar`, `translated`)은 남긴다 — 번역은 묶음(`translate.batches`)마다 따로 부르고, 묶음을
부르기 전마다 누적 토큰이 `token_cap` 이상이면 더 부르지 않는다.

`live`(일본어판에 나가 있는 글 경로 집합)를 주면 집합에 없는 글로 가는 상대 링크는 한글 원문으로 보낸다
(`assemble.link_targets`). `None` 이면 전부 일본어판으로.

사이드카에 남기는 것(모든 상태): 기계 검사를 통과했고, 막는 지적이 없고, 확인 안 된 인명을 담지
않은 단위만. 검토를 통과한 것은 `reviewed`, 아닌 것은 `translated`. `state.plan` 은 상태와 무관하게
재사용하므로, `translated` 로 재사용된 단위는 이 파일이 검토 범위에 다시 넣는다.

고정 번역(`glossary`)도 기계 검사를 거친다(걸리면 `gate`). 검토 범위에는 넣지 않지만 문맥 행으로 가고, 거기에
막는 지적(誤訳·不自然)이 오면 `fixed` 로 보류한다(사유에 단위 번호 — 용어집을 고치면 러너의 재시도 키가 바뀐다).
같은 문장이 한 글에 여러 번 나오면 번역은 한 번, 검토는 **모든 출현**을 범위에 넣는다(어느 출현에 온 지적이든
그 키를 막는다).

검토 흐름: 첫 검토(글 전체가 문맥) → 고치기 고리(최대 `fix_rounds`, 재검토에는 단위의 이력 `history` 를
준다) → 그래도 막는
지적이 남은 단위만 **판정 한 번**(`review.adjudicate`, 주입한 `review` 함수의 `.adjudicate` 속성). 판정은
A(번역기의 마지막 번역)·B(검토자의 마지막 수정안) 가운데 고른다 — `A`/`both` → A, `B` → B 가 기계 검사를
통과하면 B, `neither` 또는 B 가 검사에 걸리면 보류. 판정 뒤에 다시 검토하지 않는다. 재검토에 싣는 행은
고친 단위·이웃(범위)과 그 바로 앞뒤 단위뿐이다 — 정정 때마다 글 전체를 다시 실어 codex 한도를 쓰지 않게.
`.adjudicate` 가 없는
검토 함수(시험의 가짜, 모델 없는 조립)면 판정 없이 보류한다. 호출 수는 `calls["adjudicate"]`.

목록 항목(`title`·`headline`·`label`)은 추가 단위(kind `list`)로 같은 번역·검사·검토를 거치고,
사이드카에 `list_src: {field: 한글 원문}`, `list: {field: 일본어}` 로 남는다(`ready` 일 때만).
이 계약은 `scripts/ja/lists.py`(2b)가 읽는다 — 바꾸지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import assemble, gate, glossary, news, state
from . import extract as X
from .review import BLOCKING, ReviewFailed
from .translate import AuthExpired, CapReached, LimitReached, ModelError, batches

KO_BASE = "https://fdo2a.github.io/"

# (경로, 한글 목록 json). 항목은 `date` 또는 `key` 가 파일 이름(확장자 뺀 것)과 같은 것.
LIST_SOURCES = (
    (re.compile(r"posts/[^/]+\.html"), "posts.json"),
    (re.compile(r"news/[^/]+\.html"), "news.json"),
    (re.compile(r"japan/daily/[^/]+\.html"), "japan/daily.json"),
)
LIST_FIELDS = ("title", "headline", "label")


@dataclass
class Config:
    ko_base: str = KO_BASE
    ja_base: str = assemble.JA_BASE
    model: str = "sonnet"
    strong_model: str = "opus"
    gate_retries: int = 2           # 기계 검사에 걸린 단위의 재번역 횟수
    fix_rounds: int = 2             # 검토 지적 고치기 고리
    review: bool = True
    # 확인 안 된 인명으로 보류될 글도 검토까지는 돈다 — 사람이 이름을 더할 때 지적을 한꺼번에 본다.
    review_on_names_hold: bool = True
    # 이 글에서 더 쓸 수 있는 claude 토큰(in+out). None 이면 보지 않는다 — 러너가 남은 주간 예산을 넣는다.
    token_cap: int | None = None


@dataclass
class Result:
    status: str                     # ready | held | pending
    html_ja: str | None
    sidecar: dict
    reason: str = ""
    detail: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=lambda: {"in": 0, "out": 0})
    rounds: int = 0
    calls: dict = field(default_factory=lambda: {"translate": 0, "review": 0, "adjudicate": 0})


class _Stop(Exception):
    def __init__(self, status, reason, code=None):
        super().__init__(reason)
        self.status, self.reason, self.code = status, reason, code or status


def blob_sha(data: bytes) -> str:
    """git blob 해시(git 을 부르지 않고)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def list_entry(root, path):
    """(목록 json 상대 경로, {field: 한글}) 또는 (None, None)."""
    stem = Path(path).stem
    for pat, rel in LIST_SOURCES:
        if not pat.fullmatch(path):
            continue
        obj, _why = state.read_json(Path(root) / rel)
        if not isinstance(obj, list):
            return rel, None
        for it in obj:
            if isinstance(it, dict) and stem in (it.get("date"), it.get("key")):
                return rel, {f: it[f] for f in LIST_FIELDS if isinstance(it.get(f), str) and it[f]}
        return rel, None
    return None, None


def _flags(ko, ja):
    probs = [p for p in gate.check_unit(ko, ja) if p.soft]
    d = gate.direction(ko, ja)
    return [f"{p.code}: {p.detail}" for p in probs + ([d] if d else [])]


def _pair(ko, ja):
    return hashlib.sha256((ko + "\0" + ja).encode("utf-8")).hexdigest()[:16]


def _compact(s):
    return re.sub(r"\s+", "", s or "")


class _Page:
    def __init__(self, root, path, sidecar, translate, review, cfg):
        self.root, self.path, self.cfg = Path(root), path, cfg
        self.side_in = sidecar if sidecar else state.new_sidecar()
        fo = self.side_in.get("fixed_ok")
        self.fixed_ok = set(x for x in fo if isinstance(x, str)) if isinstance(fo, list) else set()
        self.units, self.fixed = [], {}
        self.translate_fn, self.review_fn = translate, review
        self.tokens = {"in": 0, "out": 0}
        self.calls = {"translate": 0, "review": 0, "adjudicate": 0}
        self.hist = {}               # 키 → [{ja, findings}] — 막는 지적을 받은 번역의 이력(오래된 것부터)
        self.detail = {}
        self.rounds = 0
        self.unverified = []
        self.bad = set()             # 남기면 안 되는 키
        self.changed = set()         # 이번에 번역한 키
        self.reviewed_ja = {}        # 키 → 검토를 통과한 그 번역
        self.gate_failed = {}        # 키 → 문제
        self.open = set()            # 막는 지적이 열려 있는 키(고쳐 번역하면 닫힌다)
        self.fixed_failed = {}       # uid → 고정 번역의 기계 검사 문제

    # ── 준비 ──────────────────────────────────────────────────────────────
    def load(self):
        raw = (self.root / self.path).read_bytes()
        self.source_blob = blob_sha(raw)
        html = raw.decode("utf-8")
        recs = news.lookup(self.root, self.path)
        self.html2, rep = news.localize(html, recs)
        self.detail["news"] = {k: list(getattr(rep, k)) for k in
                               ("localized", "kept", "missing", "no_source", "malformed", "unsure")
                               if getattr(rep, k)}
        self.titles = [str(recs[i].get("title")) for i in rep.localized if recs.get(i, {}).get("title")]
        if rep.missing:
            raise _Stop("held", f"뉴스 기록 없음: {', '.join(rep.missing)}", "news_missing")
        seen = len(rep.localized) + len(rep.kept) + len(rep.malformed) + len(rep.unsure)
        n_attr = news.count_items(html)
        if rep.malformed or n_attr != seen:
            if n_attr != seen:
                self.detail["news"]["count"] = {"data_news": n_attr, "items": seen}
            raise _Stop("held", f"뉴스 항목 꼴 {len(rep.malformed) or abs(n_attr - seen)}건", "news_malformed")
        if rep.unsure:
            raise _Stop("held", f"뉴스 원제 언어 불확실 {len(rep.unsure)}건", "news_lang")
        doc = X.split(self.html2)
        self.n_doc = len(doc.units)
        rel, entry = list_entry(self.root, self.path)
        self.list_src = entry or {}
        if rel and entry is None:
            self.detail["list_missing"] = f"{rel} 에 이 글의 항목이 없다"
        lunits = [X.Unit(self.n_doc + i, "list", ko, -1, -1, attr=f)
                  for i, (f, ko) in enumerate(self.list_src.items())]
        self.list_uid = {u.attr: u.uid for u in lunits}
        self.doc = doc
        self.units = doc.units + lunits
        self.plan = state.plan(X.Doc(self.html2, self.units), self.side_in)
        self.key = self.plan.keys
        self.fixed = dict(self.plan.fixed)
        for u in self.units:
            if u.kind == "attr":
                v = glossary.fixed_attr(u.attr, u.ko)
                if v is not None:
                    self.fixed[u.uid] = v
        side_units = self.side_in.get("units") or {}
        self.cur = {}
        self.status_of = {}
        for uid, ja in self.plan.reused.items():
            if uid in self.fixed:
                continue
            k = self.key[uid]
            self.cur[k] = ja
            self.status_of[k] = (side_units.get(k) or {}).get("status")
        self.rep = {}
        self.occ = {}                # 키 → 그 키의 모든 출현 uid(문서 순서)
        for u in self.units:
            if u.uid not in self.fixed:
                self.rep.setdefault(self.key[u.uid], u)
                self.occ.setdefault(self.key[u.uid], []).append(u.uid)
        self.todo = [k for k in self.rep if k not in self.cur]
        self.recheck = [u.uid for u in self.plan.recheck if u.uid not in self.fixed]
        self.unreviewed = [k for k, st in self.status_of.items() if st != "reviewed"]

    def fixed_firsts(self):
        """고정 단위 가운데 이 글에서 아직 검토를 통과하지 않은 (원문, 번역) 쌍마다 첫 출현의 uid.
        통과한 쌍은 사이드카 `fixed_ok` 에 남는다 — 원문의 고정 문구가 바뀌거나 사전의 값이 바뀌면 새 쌍이라
        다시 검토받는다. 가나가 든 원문(원제로 되돌린 뉴스 머리)은 뺀다 — 일본 매체의 제목은 번역이 아니다."""
        seen, out = set(), set()
        for u in self.units:
            if u.uid not in self.fixed or gate.KANA.search(u.ko):
                continue
            h = _pair(u.ko, self.fixed[u.uid])
            if h not in seen and h not in self.fixed_ok:
                seen.add(h)
                out.add(u.uid)
        return out

    def check_fixed(self):
        """고정 번역도 기계 검사 — 사전이 틀리면 글마다 같은 틀린 번역이 검토 없이 나간다."""
        for u in self.units:
            if u.uid in self.fixed:
                hard = [p for p in gate.check_unit(u.ko, self.fixed[u.uid]) if not p.soft]
                if hard:
                    self.fixed_failed[u.uid] = "; ".join(f"{p.code}: {p.detail}" for p in hard)
        if self.fixed_failed:
            ids = list(self.fixed_failed)
            raise _Stop("held", "고정 번역이 기계 검사에 걸렸다: " + " ".join(f"#{i}" for i in ids[:5]), "gate")

    def stop_if_fixed(self):
        fx = self.detail.get("fixed_findings")
        if fx:
            ids = list(dict.fromkeys(f["id"] for f in fx))
            raise _Stop("held", "고정 번역에 막는 지적: " + " ".join(f"#{i}" for i in ids[:5]) +
                        (f" 외 {len(ids) - 5}" if len(ids) > 5 else ""), "fixed")

    def texts(self, only_doc=False):
        out = {}
        for u in self.units:
            if only_doc and u.uid >= self.n_doc:
                continue
            if u.uid in self.fixed:
                out[u.uid] = self.fixed[u.uid]
            elif self.key[u.uid] in self.cur:
                out[u.uid] = self.cur[self.key[u.uid]]
        return out

    # ── 번역 + 기계 검사 ──────────────────────────────────────────────────
    def _context(self, exclude_keys):
        t = self.texts()
        return [{"id": u.uid, "ko": u.ko,
                 **({"ja": t[u.uid]} if u.uid in t and self.key[u.uid] not in exclude_keys else {})}
                for u in self.units]

    def _names(self):
        return {"terms": dict(glossary.NAMES), "titles": list(self.titles)}

    def translate_keys(self, keys, hints=None, model=None):
        """키들을 번역해 기계 검사까지. 통과한 것은 cur 에, 남은 것은 gate_failed 에.
        묶음마다 따로 부른다 — 중간에 멈춰도 앞 묶음의 번역·토큰이 남고, 부르기 전마다 예산을 본다."""
        model = model or self.cfg.model
        hints = dict(hints or {})
        left = list(keys)
        for attempt in range(1 + self.cfg.gate_retries):
            if not left:
                break
            nxt, done = [], set()
            for batch in batches([self.rep[k] for k in left]):
                bkeys = [self.key[u.uid] for u in batch]
                self._check_cap()
                uh = {self.rep[k].uid: hints[k] for k in bkeys if k in hints}
                try:
                    out = self.translate_fn(batch, context=self._context(set(left) - done),
                                            names=self._names(), model=model, hints=uh or None)
                except (LimitReached, ModelError, CapReached) as e:
                    part = getattr(e, "partial", None)
                    if part is not None:
                        self._absorb(part, bkeys, hints, partial=True)
                    self._mark_names()
                    raise
                bad = self._absorb(out, bkeys, hints)
                nxt += bad
                done |= set(bkeys) - set(bad)
            left = nxt
        for k in left:
            self.bad.add(k)
        self._mark_names()

    def _check_cap(self):
        cap = self.cfg.token_cap
        used = self.tokens["in"] + self.tokens["out"]
        if cap is not None and used >= cap:
            raise _Stop("pending", f"글 예산 소진 {used}/{cap}", "budget")

    def _absorb(self, out, keys, hints, partial=False):
        """번역 결과 하나를 받는다. 기계 검사에 걸린 키 목록을 돌려준다. partial(예외 전까지의 결과)이면
        답이 없는 키·걸린 키는 기록하지 않는다 — 다음 시도가 다시 번역한다."""
        self.calls["translate"] += int(out.calls or 0)
        for k in ("in", "out"):
            self.tokens[k] += int((out.tokens or {}).get(k) or 0)
        for nm in out.unverified_names or []:
            if nm not in self.unverified:
                self.unverified.append(nm)
        failed = []
        for k in keys:
            u = self.rep[k]
            ja = (out.texts or {}).get(u.uid)
            if partial and ja is None:
                continue
            hard = [p for p in gate.check_unit(u.ko, ja) if not p.soft]
            if hard:
                if partial:
                    continue
                problem = "; ".join(f"{p.code}: {p.detail}" for p in hard)
                prev = hints.get(k) or {}
                hints[k] = {"prev": ja or "", "problem": "기계 검사 " + problem,
                            "suggestion": prev.get("suggestion", "")}
                self.gate_failed[k] = problem
                failed.append(k)
            else:
                self.gate_failed.pop(k, None)
                self.open.discard(k)
                self.cur[k] = ja
                self.changed.add(k)
                self.reviewed_ja.pop(k, None)
        return failed

    def _mark_names(self):
        names = [_compact(n) for n in self.unverified if _compact(n)]
        for k in self.changed:
            if any(n in _compact(self.rep[k].ko) for n in names):
                self.bad.add(k)

    # ── 검토 ──────────────────────────────────────────────────────────────
    def uids_of(self, keys):
        return {uid for k in keys for uid in self.occ.get(k, [])}

    def review_scope(self, uids, whole=True):
        """{키: [막는 지적]}. whole=False(재검토)면 범위와 그 바로 앞뒤 단위만 싣는다."""
        if not uids:
            return {}
        t = self.texts()
        want = set(uids)
        if whole:
            carry = None
        else:
            carry = set(want)
            for i, u in enumerate(self.units):
                if u.uid in want:
                    carry.update(x.uid for x in self.units[max(0, i - 1):i + 2])
        rows = []
        for u in self.units:
            if carry is not None and u.uid not in carry:
                continue
            row = {"id": u.uid, "ko": u.ko, "ja": t.get(u.uid, ""), "flags": _flags(u.ko, t.get(u.uid))}
            h = self.hist.get(self.key[u.uid]) if u.uid not in self.fixed else None
            if h:
                row["history"] = [dict(x) for x in h]
            rows.append(row)
        scope = [u.uid for u in self.units if u.uid in want]
        try:
            out = self.review_fn(rows, scope)
        except (LimitReached, CapReached) as e:
            part = getattr(e, "partial", None)
            if part is not None and hasattr(part, "findings"):
                self._take(part, t, scope)       # 끝낸 조각의 판정은 사이드카에 남긴다
            raise
        return self._take(out, t, scope)

    def _take(self, out, t, scope):
        """검토 결과 하나를 받는다 → {키: [막는 지적]}."""
        self.calls["review"] += out.calls
        # 검토마다 지적 전부를 남긴다(사람이 보류 이유를 거슬러 볼 수 있게).
        self.detail.setdefault("reviews", []).append(
            {"scope": len(scope), "findings": [_fd(f, t) for f in out.findings]})
        blocking = {}
        for f in out.findings:
            if f.uid in self.fixed:
                self.detail.setdefault("glossary_findings", []).append(_fd(f, t))
                if f.kind in BLOCKING:
                    self.detail.setdefault("fixed_findings", []).append(_fd(f, t))
                continue
            k = self.key[f.uid]
            if f.kind in BLOCKING:
                blocking.setdefault(k, []).append(f)
            else:
                self.detail.setdefault("prefs", []).append(_fd(f, t))
        flagged = {f.uid for f in out.findings if f.kind in BLOCKING}
        by = {u.uid: u for u in self.units}
        in_scope = set(scope)
        for uid in out.reviewed:
            if uid in self.fixed:
                if uid not in flagged:
                    self.fixed_ok.add(_pair(by[uid].ko, self.fixed[uid]))
                continue
            k = self.key[uid]
            # 같은 문장이 여러 번 나오면 범위에 든 출현이 **전부** 판정받아야 검토된 것이다 — 조각 중간에 멈춘
            # 부분 결과가 한 출현만 보고 「검토됨」을 남기면 나머지 출현은 검토 없이 나간다.
            if k not in blocking and k in self.cur and all(
                    o in out.reviewed for o in self.occ.get(k, []) if o in in_scope):
                self.reviewed_ja[k] = self.cur[k]
        for k, fs in blocking.items():
            self.reviewed_ja.pop(k, None)
            self.open.add(k)
            self.hist.setdefault(k, []).append(
                {"ja": self.cur.get(k, ""),
                 "findings": [{"kind": f.kind, "reason": f.reason, "suggestion": f.suggestion} for f in fs]})
        return blocking

    def neighbors(self, keys):
        """고친 단위와 그 앞뒤 이웃(고정 단위는 뺀다)."""
        order = [u for u in self.units if u.uid not in self.fixed]
        pick = set()
        for i, u in enumerate(order):
            if self.key[u.uid] in keys:
                pick.add(u.uid)
                if i > 0:
                    pick.add(order[i - 1].uid)
                if i + 1 < len(order):
                    pick.add(order[i + 1].uid)
        return pick

    def fix_loop(self, blocking):
        # 키 → 검토마다 「誤訳 이 있었나」. 같은 단위가 두 번 연속 誤訳 이면 그 단위만 강한 모델.
        history = {k: ["誤訳" in {f.kind for f in fs}] for k, fs in blocking.items()}
        for r in range(1, self.cfg.fix_rounds + 1):
            if not blocking:
                break
            self.rounds = r
            hints = {k: {"prev": self.cur.get(k, ""),
                         "problem": " / ".join(f"{f.kind}: {f.reason}" for f in fs),
                         "suggestion": fs[0].suggestion} for k, fs in blocking.items()}
            strong = [k for k in blocking if r >= 2 and history.get(k, [])[-2:] == [True, True]]
            normal = [k for k in blocking if k not in strong]
            for keys, model in ((normal, self.cfg.model), (strong, self.cfg.strong_model)):
                if keys:
                    self.translate_keys(keys, hints, model)
            if any(k in self.gate_failed for k in blocking):
                raise _Stop("held", "고친 번역이 기계 검사에 걸렸다: " + _gate_reason(self), "gate")
            fixed_keys = set(blocking)
            blocking = self.review_scope(self.neighbors(fixed_keys), whole=False)
            for k, fs in blocking.items():
                history.setdefault(k, []).append("誤訳" in {f.kind for f in fs})
            self.detail.setdefault("rounds", []).append(
                {"round": r, "fixed": len(fixed_keys), "blocking_after": len(blocking),
                 "models": {"strong": len(strong), "normal": len(normal)}})
        return blocking

    # ── 판정 ──────────────────────────────────────────────────────────────
    def adjudicate(self, blocking):
        """고리 뒤에도 남은 막는 지적 → 판정 한 번. 남은 {키: [지적]} 를 돌려준다.
        같은 문장이 여러 번 나오면 **지적받은 출현마다** 그 자리의 앞뒤를 실어 묻는다 — 첫 출현의 문맥에서
        맞다는 판정이 다른 자리의 지적을 풀지 못한다. 한 키의 출현 전부가 같은 후보를 받아들여야 통과."""
        fn = getattr(self.review_fn, "adjudicate", None)
        if not blocking:
            return blocking
        if fn is None:
            self.detail["adjudication"] = {"skipped": "판정 함수 없음"}
            return blocking
        t = self.texts()
        order = list(self.units)
        pos = {u.uid: i for i, u in enumerate(order)}
        near = lambda j: ({"ko": order[j].ko, "ja": t.get(order[j].uid, "")}
                          if 0 <= j < len(order) else None)
        items, by_uid = [], {}
        for k, fs in blocking.items():
            a = self.cur.get(k, "")
            # 판정이 고른 후보는 그 키의 모든 출현에 들어간다 — 지적받지 않은 출현에도 묻는다(B 는 거기서
            # 본 적이 없는 번역이다). 수정안은 지적이 나온 것을 쓴다.
            b = next((f.suggestion for f in fs if f.suggestion and f.suggestion != a), "")
            for uid in sorted(self.occ.get(k) or [self.rep[k].uid], key=pos.get):
                i = pos[uid]
                items.append({"id": uid, "ko": order[i].ko, "a": a, "b": b or None,
                              "history": [dict(x) for x in self.hist.get(k, [])],
                              "before": near(i - 1), "after": near(i + 1)})
                by_uid[uid] = k
        out = fn(items)
        self.calls["adjudicate"] += out.calls
        log, ok = [], {}                 # ok: 키 → 출현마다 받아들인 후보들
        for it in items:
            uid, k = it["id"], by_uid[it["id"]]
            v = out.verdicts[uid]
            row = {"id": uid, "choice": v.choice, "reason": v.reason, "a": it["a"], "b": it["b"]}
            good = []
            if v.choice in ("A", "both"):
                good.append(it["a"])
            if v.choice in ("B", "both") and it["b"]:
                hard = [p for p in gate.check_unit(self.rep[k].ko, it["b"]) if not p.soft]
                if hard:
                    if v.choice == "B":
                        row["gate"] = "; ".join(f"{p.code}: {p.detail}" for p in hard)
                else:
                    good.append(it["b"])
            ok.setdefault(k, []).append(good)
            log.append(row)
        left = {}
        for k, goods in ok.items():
            common = [c for c in goods[0] if all(c in g for g in goods[1:])]
            pick = common[0] if common else None      # A 가 먼저 — 바꾸지 않아도 되면 바꾸지 않는다
            for row in log:
                if by_uid[row["id"]] == k:
                    row["result"] = "held" if pick is None else ("A" if pick == row["a"] else "B")
            if pick is None:
                left[k] = blocking[k]
                continue
            if pick != self.cur.get(k):
                self.cur[k] = pick
                self.changed.add(k)
            self.reviewed_ja[k] = pick
            self.open.discard(k)
        self.detail["adjudication"] = log
        return left

    # ── 사이드카 ──────────────────────────────────────────────────────────
    def sidecar(self, final=False):
        keep = {}
        for k in set(self.changed) | set(self.unreviewed):
            if k in self.bad or k in self.open or k not in self.cur:
                continue
            keep[k] = self.cur[k]
        rev = {k: ja for k, ja in keep.items() if self.reviewed_ja.get(k) == ja}
        tr = {k: ja for k, ja in keep.items() if k not in rev}
        side = self.side_in
        if tr:
            side = state.record(side, self.plan, tr, status="translated", source_blob=self.source_blob)
        if rev:
            side = state.record(side, self.plan, rev, status="reviewed", source_blob=self.source_blob)
        side = json.loads(json.dumps(side))
        for k in self.open | self.bad:          # 지적이 열린 옛 기억은 재사용되면 안 된다
            (side.get("units") or {}).pop(k, None)
        side["glossary"] = glossary.VERSION
        side["source_blob"] = self.source_blob
        now = {_pair(u.ko, self.fixed[u.uid]) for u in self.units if u.uid in self.fixed}
        side["fixed_ok"] = sorted(self.fixed_ok & now)       # 이 글에 지금 있는 쌍만
        if final:
            live = set(self.key.values())
            side["units"] = {k: v for k, v in (side.get("units") or {}).items() if k in live}
            t = self.texts()
            side["list_src"] = dict(self.list_src)
            side["list"] = {f: t[uid] for f, uid in self.list_uid.items() if uid in t}
        return side


def _fd(f, texts):
    return {"id": f.uid, "kind": f.kind, "reason": f.reason, "suggestion": f.suggestion,
            "ja": texts.get(f.uid, "")}


def _gate_reason(pg):
    rows = []
    for k, prob in pg.gate_failed.items():
        rows.append(f"#{pg.rep[k].uid} {prob}")
    return " | ".join(rows[:5]) + (f" 외 {len(rows) - 5}건" if len(rows) > 5 else "")


def build_page(root, path, *, sidecar, translate, review, cfg=None, live=None) -> Result:
    cfg = cfg or Config()
    pg = _Page(root, path, sidecar, translate, review, cfg)

    def result(status, html_ja=None, reason="", final=False):
        if status != "ready":
            html_ja = None
        side = pg.sidecar(final=final) if hasattr(pg, "plan") else (sidecar or state.new_sidecar())
        if pg.gate_failed or getattr(pg, "fixed_failed", None):
            pg.detail["gate_failed"] = {**{str(pg.rep[k].uid): v for k, v in pg.gate_failed.items()},
                                        **{str(i): v for i, v in pg.fixed_failed.items()}}
        if pg.unverified:
            pg.detail["unverified_names"] = list(pg.unverified)
        if hasattr(pg, "plan"):
            t = pg.texts()
            soft = [{"id": u.uid, "flags": _flags(u.ko, t[u.uid])} for u in pg.units
                    if u.uid not in pg.fixed and u.uid in t and _flags(u.ko, t[u.uid])]
            if soft:
                pg.detail["soft"] = soft
        pg.detail["calls"] = dict(pg.calls)
        return Result(status, html_ja, side, reason, pg.detail, dict(pg.tokens), pg.rounds, dict(pg.calls))

    try:
        pg.load()
        pg.check_fixed()
        if pg.todo:
            pg.translate_keys(pg.todo)
        if pg.gate_failed:
            raise _Stop("held", "기계 검사가 남았다: " + _gate_reason(pg), "gate")
        names_hold = bool(pg.unverified)
        if names_hold and not cfg.review_on_names_hold:
            raise _Stop("held", "확인 안 된 인명: " + ", ".join(pg.unverified), "names")
        if cfg.review:
            scope = pg.uids_of(pg.changed) | set(pg.recheck) | pg.uids_of(k for k in pg.unreviewed if k in pg.rep)
            scope |= pg.fixed_firsts()        # 고정 번역도 그 글의 문맥에서 검토받는다(새 쌍만, 첫 출현 하나)
            try:
                blocking = pg.review_scope(scope) if scope else {}
                pg.stop_if_fixed()            # 어차피 보류될 글 — 고치기 고리의 호출을 쓰지 않는다
                blocking = pg.fix_loop(blocking)
                blocking = pg.adjudicate(blocking)
            except ReviewFailed as e:
                raise _Stop("held", f"검토 실패: {e}", "review_failed")
            pg.stop_if_fixed()
            if blocking:
                for k in blocking:
                    pg.bad.add(k)
                t = pg.texts()
                pg.detail["blocking"] = [_fd(f, t) for fs in blocking.values() for f in fs]
                adj = {r["id"]: r for r in pg.detail.get("adjudication") or [] if isinstance(r, dict)}
                why = "; ".join(
                    f"#{f.uid} {f.kind} {f.reason}" for fs in list(blocking.values())[:5] for f in fs)
                verd = ", ".join(f"#{i} {r['choice']}" + (" (B 기계 검사)" if r.get("gate") else "")
                                 for i, r in adj.items() if r.get("result") == "held")
                raise _Stop("held", "검토 지적이 남았다: " + why + (f" — 판정 {verd}" if verd else ""), "blocking")
        else:
            pg.detail["review_skipped"] = True
        if pg.unverified:
            raise _Stop("held", "확인 안 된 인명: " + ", ".join(pg.unverified), "names")
        texts = pg.texts(only_doc=True)
        lack = [u.uid for u in pg.doc.units if u.uid not in texts]
        if lack:
            raise _Stop("held", f"번역이 빠진 단위 {lack[:10]}", "missing_units")
        html_ja = assemble.build(pg.html2, path, texts, ko_url=cfg.ko_base + path, ja_base=cfg.ja_base,
                                 live=live)
        probs = gate.check_doc(html_ja, pg.html2)
        if probs:
            pg.detail["doc_problems"] = [f"{p.code}: {p.detail}" for p in probs]
            raise _Stop("held", "문서 검사: " + "; ".join(p.code for p in probs), "doc")
        if not cfg.review:
            pg.reviewed_ja = {}
        return result("ready", html_ja, final=True)
    except _Stop as s:
        pg.detail["stop"] = s.code
        return result(s.status, reason=s.reason)
    except CapReached as e:                  # 러너의 상한 — 그때까지의 번역은 사이드카에 남는다
        pg.detail["stop"] = e.code
        return result("pending", reason=e.reason)
    except LimitReached as e:
        pg.detail["stop"] = "limit"
        pg.detail["error"] = str(e)[:300]
        return result("pending", reason=f"한도: {str(e)[:200]}")   # 러너가 여기서 재개 시각을 읽는다
    except AuthExpired as e:
        pg.detail["stop"] = "auth"
        pg.detail["error"] = str(e)[:300]
        return result("pending", reason="로그인 만료")
    except ModelError as e:
        pg.detail["stop"] = "model"
        pg.detail["error"] = str(e)[:300]
        return result("pending", reason=f"모델 오류: {str(e)[:200]}")


def text_hash_of(root, path):
    """(text_hash, None) 또는 (None, 사유). 모델을 부르지 않는다 — `build_page` 와 같은 단위(목록 단위 포함)로 잰다."""
    pg = _Page(root, path, None, None, None, Config())
    try:
        pg.load()
    except _Stop as s:
        return None, s.reason
    return state.text_hash(X.Doc(pg.html2, pg.units)), None


# ── 실제 호출 ─────────────────────────────────────────────────────────────

def real_translate():
    from . import translate as T

    def call(units, *, context, names, model, hints=None):
        return T.translate(units, context=context, names=names, model=model, hints=hints)
    return call


def real_review():
    from . import review as RV

    def call(units, scope):
        return RV.review(units, scope)

    def adjudicate(items):
        return RV.adjudicate(items)
    call.adjudicate = adjudicate
    return call
