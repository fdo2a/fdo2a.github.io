"""번역 기억(사이드카)과 원장 — 파일 형식과 판정만. git·모델 호출은 2차.

사이드카 `ja/_tm/<경로>.json`:
    {source_blob, renderer, glossary, deps: {path: blob}, units: {key: {ko, ja, status}}}
원장 `ja/state.json`:
    {version, pages: {path: {source_blob, text_hash, status, reason, updated, rounds, deps, renderer}}}
    status ∈ published | held | pending | notice. (deps·renderer 는 classify 가 비교하려고 덧붙였다.)

단위 키 = sha256(NFC(ko) + "\\0" + glossary.VERSION) 앞 16자.
읽기·쓰기는 원자적(임시 파일 + rename). 깨진 JSON 은 예외 대신 (None, 사유).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import glossary

LEDGER_VERSION = 1
STATUSES = ("published", "held", "pending", "notice")
UNIT_STATUSES = ("translated", "reviewed")


def key(ko: str) -> str:
    s = unicodedata.normalize("NFC", ko) + "\0" + glossary.VERSION
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def text_hash(doc) -> str:
    """단위 키 열의 해시 — 뼈대(태그·공백)가 바뀌어도 단위 문자열이 같으면 같다."""
    h = hashlib.sha256()
    for u in doc.units:
        h.update(key(u.ko).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()[:16]


# ── 파일 ──────────────────────────────────────────────────────────────────

def read_json(path):
    """(객체, None) 또는 (None, 사유). 예외를 내지 않는다."""
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"{p} 없음"
    except OSError as e:
        return None, f"{p} 읽기 실패: {e}"
    try:
        return json.loads(raw), None
    except ValueError as e:
        return None, f"{p} 깨진 JSON: {e}"


def write_json(path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── 사이드카 ──────────────────────────────────────────────────────────────

def sidecar_path(repo_root, post_path: str) -> Path:
    return Path(repo_root) / "ja" / "_tm" / (post_path + ".json")


def new_sidecar() -> dict:
    return {"source_blob": None, "renderer": None, "glossary": glossary.VERSION, "deps": {}, "units": {}}


def load_sidecar(repo_root, post_path: str):
    """(사이드카, 사유). 없거나 깨졌으면 빈 사이드카와 사유."""
    obj, why = read_json(sidecar_path(repo_root, post_path))
    if obj is None:
        return new_sidecar(), why
    if not isinstance(obj, dict) or not isinstance(obj.get("units"), dict):
        return new_sidecar(), "사이드카 형식이 아니다(units 없음)"
    return obj, None


def save_sidecar(repo_root, post_path: str, sidecar: dict) -> None:
    write_json(sidecar_path(repo_root, post_path), sidecar)


# ── 계획 ──────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    doc: object
    keys: dict                                   # uid → key
    fixed: dict = field(default_factory=dict)    # uid → ja (glossary)
    reused: dict = field(default_factory=dict)   # uid → ja (사이드카)
    todo: list = field(default_factory=list)     # 모델에 보낼 단위(키로 중복 제거, 첫 출현)
    recheck: list = field(default_factory=list)  # 재사용했지만 이웃이 todo 인 단위

    def uids_of(self, unit) -> list:
        k = self.keys[unit.uid]
        return [uid for uid, kk in self.keys.items() if kk == k and uid not in self.fixed and uid not in self.reused]

    def texts(self, translations=None) -> dict:
        """uid → ja. translations 는 key → ja(todo 의 답)."""
        out = dict(self.reused)
        out.update(self.fixed)
        for uid, k in self.keys.items():
            if uid not in out and translations and translations.get(k) is not None:
                out[uid] = translations[k]
        return out

    def complete(self, texts) -> bool:
        return all(u.uid in texts for u in self.doc.units)


def plan(doc, sidecar) -> Plan:
    """단위마다 ① glossary.fixed ② 사이드카의 같은 키 ③ todo."""
    units = (sidecar or {}).get("units") or {}
    p = Plan(doc, {u.uid: key(u.ko) for u in doc.units})
    seen = set()
    for u in doc.units:
        k = p.keys[u.uid]
        ja = glossary.fixed(u.ko)
        if ja is not None:
            p.fixed[u.uid] = ja
            continue
        rec = units.get(k)
        if isinstance(rec, dict) and rec.get("ja") is not None and rec.get("ko") == u.ko:
            p.reused[u.uid] = rec["ja"]
            continue
        if k not in seen:
            seen.add(k)
            p.todo.append(u)
    todo_uids = {uid for uid in p.keys if uid not in p.fixed and uid not in p.reused}
    text_units = [u for u in doc.units if u.kind == "text"]
    for i, u in enumerate(text_units):
        if u.uid not in p.reused:
            continue
        near = text_units[max(0, i - 1):i] + text_units[i + 1:i + 2]
        if any(n.uid in todo_uids for n in near):
            p.recheck.append(u)
    return p


def record(sidecar, plan_: Plan, translations: dict, *, status: str, source_blob=None,
           renderer=None, deps=None) -> dict:
    """번역 결과(key → ja)를 사이드카에 담는다. 새 dict 를 돌려준다."""
    if status not in UNIT_STATUSES:
        raise ValueError(f"unit status {status!r}")
    side = json.loads(json.dumps(sidecar)) if sidecar else new_sidecar()
    side["glossary"] = glossary.VERSION
    if source_blob is not None:
        side["source_blob"] = source_blob
    if renderer is not None:
        side["renderer"] = renderer
    if deps is not None:
        side["deps"] = dict(deps)
    ko_of = {plan_.keys[u.uid]: u.ko for u in plan_.doc.units}
    for k, ja in translations.items():
        if k in ko_of and ja is not None:
            side["units"][k] = {"ko": ko_of[k], "ja": ja, "status": status}
    return side


# ── 원장 ──────────────────────────────────────────────────────────────────

def ledger_path(repo_root) -> Path:
    return Path(repo_root) / "ja" / "state.json"


def load_ledger(repo_root):
    obj, why = read_json(ledger_path(repo_root))
    if obj is None:
        return {"version": LEDGER_VERSION, "pages": {}}, why
    if not isinstance(obj, dict) or not isinstance(obj.get("pages"), dict):
        return {"version": LEDGER_VERSION, "pages": {}}, "원장 형식이 아니다(pages 없음)"
    return obj, None


def save_ledger(repo_root, ledger: dict) -> None:
    write_json(ledger_path(repo_root), ledger)


def set_page(ledger: dict, path: str, *, source_blob, text_hash, status, reason="", deps=None,
             renderer=None, now=None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status {status!r} ∉ {STATUSES}")
    if now is None:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
    old = ledger["pages"].get(path) or {}
    entry = {"source_blob": source_blob, "text_hash": text_hash, "status": status, "reason": reason,
             "updated": now, "rounds": int(old.get("rounds") or 0) + 1,
             "deps": dict(deps if deps is not None else old.get("deps") or {}),
             "renderer": renderer if renderer is not None else old.get("renderer")}
    ledger["pages"][path] = entry
    return entry


def classify(entry, source_blob, deps, text_hash, renderer) -> str:
    """new | fresh | reassemble | retranslate. 상태(held 등)는 보지 않는다 — 2차가 정한다."""
    if not entry:
        return "new"
    if entry.get("text_hash") != text_hash:
        return "retranslate"
    if (entry.get("source_blob") != source_blob or dict(entry.get("deps") or {}) != dict(deps or {})
            or entry.get("renderer") != renderer):
        return "reassemble"
    return "fresh"
