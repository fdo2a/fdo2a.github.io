#!/usr/bin/env python3
"""KR 지수 등락률 검증 — 순수 판정 + 설정 읽기 + 관찰 보고(2026-11-12).

같은 basic 응답 안의 종가(C)·등락률(R)·전일 대비(D)로 R 을 다시 계산해 대조한다(1차). 보합(R≈0)은 R·D 가
함께 0 으로 오는 실패와 구분되지 않으므로 integration 의 전일 종가로 한 번 더 확인한다. 못 읽었거나 검증하지
못한 날은 발행하지 않는다(complete=false) — 계산값으로 채우지 않는다. **원장은 판정에 쓰지 않는다**
(직전 거래일임을 증명할 수 없고, 하루 결측이 그 뒤 날을 막으면 안 된다 — 2026-10-17 기각한 연속성 검사).
`mismatch` 차단은 관찰 뒤 사람이 `config/kr_index_check.json` 을 `block` 으로 바꿔 켠다(자동 전환 없음).

spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.normpath(os.path.join(HERE, "..", "..", "config", "kr_index_check.json"))
FORMAT = "kr-index-check/1"
MODES = ("warn", "block")
TOL = 0.01                 # %p — R 반올림 반폭 0.005 + C·D 반올림분 ≈ 0.0065
FLAT = 0.01                # |R| < 0.01 이면 보합(둘째 자리 반올림 값이라 사실상 0.00)
WITNESS = 0.01             # 보합 증인: |C − Pi| ≤ 0.01pt
EPS = 1e-9
ALWAYS_BLOCKING = frozenset({"ratio_missing", "unverified", "flat_unverified", "flat_contradicted"})
BLOCKING = ALWAYS_BLOCKING            # + mode == "block" 이면 mismatch
STATUSES = ALWAYS_BLOCKING | {"mismatch", "ok", "ok_flat", "fetch_error"}


def _fin(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _usable(p):
    p = _fin(p)
    return p is not None and p > 0


def _derived(C, P):
    try:
        v = (C / P - 1) * 100
    except (ZeroDivisionError, OverflowError, TypeError):
        return None
    return v if math.isfinite(v) else None


def is_blocking(status, mode):
    return status in ALWAYS_BLOCKING or (status == "mismatch" and mode == "block") or status == "fetch_error"


def check_pct(C, R, D, integ, report_date, mode):
    """→ {status, naver_pct, derived_pct, prev_close, prev_source, integ_prev, matched, cross_note}.

    integ = fetch_index_ohlc 결과(prevClose·high·low·flow_bizdate) 또는 None. 판정 순서는 spec 의 표.
    `matched`(integration 이 이 세션 값인 듯한 표식)는 차단 상태의 이름만 고른다 — 통과 여부를 바꾸지 않는다.
    """
    C, R, D = _fin(C), _fin(R), _fin(D)
    ig = integ if isinstance(integ, dict) else {}
    Pi = _fin(ig.get("prevClose"))
    hi, lo = _fin(ig.get("high")), _fin(ig.get("low"))
    rd = (report_date or "").replace("-", "")
    matched = bool(ig and ig.get("flow_bizdate") == rd and rd and C is not None
                   and hi is not None and lo is not None and lo - 0.01 <= C <= hi + 0.01)
    Pb = (C - D) if (C is not None and D is not None) else None
    Pb = _fin(Pb)
    rec = {"status": None, "naver_pct": R, "derived_pct": None, "prev_close": None, "prev_source": None,
           "integ_prev": Pi, "matched": matched, "cross_note": False}
    if _usable(Pb) and _usable(Pi) and matched and abs(Pb - Pi) > WITNESS + EPS:
        rec["cross_note"] = True                 # 기준 시점이 다를 수 있다 — 경고만
    if R is None:
        rec["status"] = "ratio_missing"
        return rec
    P, src, der = None, None, None
    for cand, name in ((Pb, "basic"), (Pi, "integration")):
        if C is not None and _usable(cand):
            d = _derived(C, cand)
            if d is not None:
                P, src, der = cand, name, d
                break
    if P is None:
        rec["status"] = "unverified"
        return rec
    rec.update(prev_close=round(P, 4), prev_source=src, derived_pct=round(der, 4))
    if abs(R - der) > TOL + EPS:
        rec["status"] = "mismatch"
        return rec
    if abs(R) >= FLAT:
        rec["status"] = "ok"
        return rec
    if _usable(Pi) and abs(C - Pi) <= WITNESS + EPS:
        rec["status"] = "ok_flat"
    elif _usable(Pi) and matched:
        rec["status"] = "flat_contradicted"
    else:
        rec["status"] = "flat_unverified"
    return rec


def load_mode(path=None):
    """→ (mode, config_status). 없으면 warn, 깨졌거나 모르는 값이면 block(오타가 차단을 조용히 끄지 않게)."""
    path = path or CONFIG
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        print(f"::warning::kr_index_check 설정 파일이 없다({os.path.basename(path)}) — mismatch 는 경고만(warn)")
        return "warn", "missing_default"
    except (OSError, UnicodeDecodeError):              # 비 UTF-8 도 깨진 설정 → block(구현 검토 1회 #5)
        raw = None
    try:
        cfg = json.loads(raw) if raw is not None else None
    except ValueError:
        cfg = None
    if (isinstance(cfg, dict) and cfg.get("format") == FORMAT and cfg.get("mismatch") in MODES):
        return cfg["mismatch"], "ok"
    print("::warning::kr_index_check 설정을 읽을 수 없다(형식·값 확인) — mismatch 를 차단(block)으로 읽는다")
    return "block", "invalid_block"


# ── 관찰 보고(읽기 전용) ─────────────────────────────────────────────────

_RUN_MANIFEST = re.compile(r"^versions/kr/(\d{4}-\d{2}-\d{2})/runs/([^/]+)/manifest\.json$")


def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=120)


def run_manifests(root, rev="origin/main", dates=None):
    """→ [(거래일, run_id, manifest | None)] — `versions/kr/*/runs/*/manifest.json`. 읽기 실패는 None."""
    r = _git(root, "ls-tree", "-r", "--name-only", rev, "versions/kr/")
    if r.returncode != 0:
        raise RuntimeError("versions/kr 목록을 읽지 못했다")
    out = []
    for path in r.stdout.decode().split("\n"):
        m = _RUN_MANIFEST.match(path.strip())
        if not m or (dates is not None and m.group(1) not in dates):
            continue
        b = _git(root, "show", f"{rev}:{path.strip()}")
        man = None
        if b.returncode == 0:
            try:
                man = json.loads(b.stdout)
            except ValueError:
                man = None
        out.append((m.group(1), m.group(2), man if isinstance(man, dict) else None))
    return sorted(out, key=lambda x: (x[0], x[1]))


VALID = STATUSES - {"fetch_error"}      # 이 실행이 그 지수를 실제로 검사했다


def report_rows(manifests):
    """manifest 목록 → 거래일·실행별 행. `checks` 가 없는 옛 manifest 는 건너뛴다.

    못 읽은 manifest·`checks={"error": ...}`·두 지수 중 하나라도 유효한 검사 status 가 없는 실행은
    `unreadable=True` 로 남긴다 — 관찰 일수에 세지 않는다(codex 구현 검토 1회 #3)."""
    rows = []
    for date, rid, man in manifests:
        if man is None:
            rows.append({"date": date, "run_id": rid, "unreadable": True, "mode": None, "config_status": None,
                         **{k: v for i in ("KOSPI", "KOSDAQ")
                            for k, v in ((i, None), (f"{i}_cross_note", False), (f"{i}_diff", None))}})
            continue
        ck = man.get("checks")
        if not isinstance(ck, dict):
            continue
        ip = ck.get("index_pct") if isinstance(ck.get("index_pct"), dict) else {}
        row = {"date": date, "run_id": rid, "mode": ip.get("mode"), "config_status": ip.get("config_status")}
        for idx in ("KOSPI", "KOSDAQ"):
            e = ip.get(idx) if isinstance(ip.get(idx), dict) else {}
            row[idx] = e.get("status")
            row[f"{idx}_cross_note"] = bool(e.get("cross_note"))
            row[f"{idx}_diff"] = (round(abs(e["naver_pct"] - e["derived_pct"]), 4)
                                  if _fin(e.get("naver_pct")) is not None and _fin(e.get("derived_pct")) is not None
                                  else None)
        row["unreadable"] = "error" in ck or not all(row[i] in VALID for i in ("KOSPI", "KOSDAQ"))
        rows.append(row)
    return rows


def summary(rows):
    """관찰 거래일 = 두 지수 모두 유효한 검사가 있는 실행이 하나라도 있는 날. 읽지 못한 날은 따로."""
    ok = [r for r in rows if not r.get("unreadable")]
    days = sorted({r["date"] for r in ok})
    bad = [r for r in ok if "mismatch" in (r["KOSPI"], r["KOSDAQ"])
           or r["KOSPI_cross_note"] or r["KOSDAQ_cross_note"]]
    unread = [r for r in rows if r.get("unreadable")]
    return {"trade_days": len(days), "runs": len(ok), "mismatch_or_cross_note_runs": len(bad),
            "mismatch_or_cross_note_days": sorted({r["date"] for r in bad}),
            "unreadable_runs": len(unread),
            "unreadable_days": sorted({r["date"] for r in unread} - set(days))}


def main(argv=None):
    ap = argparse.ArgumentParser(description="KR 지수 등락률 검증 관찰 보고(읽기 전용)")
    ap.add_argument("--report", action="store_true", required=True)
    ap.add_argument("--root", default=os.path.normpath(os.path.join(HERE, "..", "..")))
    ap.add_argument("--rev", default="origin/main")
    a = ap.parse_args(argv)
    try:
        rows = report_rows(run_manifests(a.root, a.rev))
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        print(f"읽기 실패: {e}", file=sys.stderr)
        return 1
    print("date        run_id                               mode/config        KOSPI(diff,cross)          KOSDAQ(diff,cross)")
    for r in rows:
        if r.get("unreadable") and r["KOSPI"] is None and r["KOSDAQ"] is None:
            print(f"{r['date']}  {r['run_id'][:36]:36s} 읽지 못함(관찰에 세지 않음)")
            continue
        cells = [f"{r[i]}({r[i + '_diff']},{'X' if r[i + '_cross_note'] else '-'})" for i in ("KOSPI", "KOSDAQ")]
        print(f"{r['date']}  {r['run_id'][:36]:36s} {str(r['mode'])}/{str(r['config_status']):14s} "
              f"{cells[0]:26s} {cells[1]}" + ("  ← 검사 불완전(관찰에 세지 않음)" if r.get("unreadable") else ""))
    s = summary(rows)
    print(f"관찰 거래일 {s['trade_days']} · 실행 {s['runs']} · mismatch/cross_note 실행 {s['mismatch_or_cross_note_runs']}"
          + (f" ({', '.join(s['mismatch_or_cross_note_days'])})" if s["mismatch_or_cross_note_days"] else "")
          + f" · 읽지 못한 실행 {s['unreadable_runs']} · 읽지 못한 날 {len(s['unreadable_days'])}"
          + (f" ({', '.join(s['unreadable_days'])})" if s["unreadable_days"] else ""))
    print("block 전환은 사람이 판단한다 — 10거래일 이상 0건이면 config/kr_index_check.json 의 mismatch 를 block 으로.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
