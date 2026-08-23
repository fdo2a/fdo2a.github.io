# 주간·월간 정리와 주간 코멘트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** US·KR 주간/월간 정리 4종과 US·KR 통합 주간 코멘트 1종을 자동 발행하고, 스탠스·레짐 판단을 누적 적중률로 채점한다.

**Architecture:** 기존 GitHub Actions 수집기 둘을 확장해 기간 키(`2026-W34`/`2026-08`)로 나뉜 집계 파일과 승계 책 append-only 로그를 커밋한다. 순수 계산 모듈(`period.py`·`scorecard.py`)은 네트워크 없이 dated series를 입력받아 TDD로 검증하고, 수집기는 다운로드와 파일 쓰기만 맡는다. 클라우드 루틴 트리거 2개(`weekly`·`monthly`)가 오케스트레이터 파일을 읽어 서브에이전트에 작성을 위임하고, 발행 게이트가 수치를 집계 파일과 대조한다.

**Tech Stack:** Python 3 (stdlib + yfinance + pandas), pytest, GitHub Actions, Claude Code 클라우드 루틴

**Spec:** `docs/superpowers/specs/2026-08-23-period-reports-design.md`

## Global Constraints

- 작업 디렉터리는 레포 클론 `site/` (= `fdo2a/fdo2a.github.io`). 모든 경로는 그 루트 기준
- 테스트 실행: 레포 루트에서 `python3 -m pytest scripts/us/tests/test_X.py -q`. `scripts/conftest.py`가 `scripts/`를 `sys.path`에 넣으므로 import는 `from us.period import ...` / `from kr.period import ...`
- **순수 모듈은 네트워크를 타지 않는다.** yfinance/HTTP 호출은 `scripts/collect_*.py`에만 둔다 (기존 `stance_metrics.py` / `collect_histories()` 분리 관례)
- 기간 키 형식: 주간 `f"{y}-W{w:02d}"` (ISO), 월간 `"YYYY-MM"`
- 금지 어휘 `buy-side` / `buy side` / `buyside` / `바이사이드` — `scripts/us/macro_gate.py`의 `BANNED_LABELS`를 재사용한다
- 발행본에 `[확인필요]` 금지. 수치 창작 금지 — 집계 파일에 없는 숫자는 게이트가 막는다
- KR 수급은 **확정치만** 합산한다 (`flows_provisional` 참인 날 제외)
- 커밋은 태스크마다. 푸시는 태스크 묶음이 끝날 때 (`git pull --rebase` 먼저)

---

### Task 1: 승계 책 append-only 로그 코어

**Files:**
- Create: `scripts/us/history.py`
- Test: `scripts/us/tests/test_history.py`

**Interfaces:**
- Consumes: 없음
- Produces: `stance_record(stance: dict) -> dict`, `macro_record(macro: dict) -> dict`, `append_jsonl(path: str, record: dict, key: str = 'report_date') -> bool`, `read_jsonl(path: str) -> list[dict]`

- [ ] **Step 1: Write the failing test**

`scripts/us/tests/test_history.py`:

```python
import json
import os

from us.history import append_jsonl, macro_record, read_jsonl, stance_record

STANCE = {
    "report_date": "2026-08-21",
    "horizon": "2-6주",
    "assets": {
        "equities": {
            "grade": 1, "label": "소폭확대", "since": "2026-08-21",
            "thesis": "브레드스 확산 트리거 충족.",
            "tilt": "소재·헬스케어 확대",
            "triggers": {"increase": [{"kind": "metric", "metric": "spx_vs_50dma_pct",
                                       "op": ">", "value": 4.0, "toward": "+",
                                       "desc": "추세 확장 추가 확인"}],
                         "decrease": []},
        }
    },
}

MACRO = {
    "report_date": "2026-08-21",
    "regime": {"growth": 0, "inflation": 0, "since": "2026-08-17",
               "name": "교착", "thesis": "축 점수가 컷포인트 안쪽."},
    "policy_path": {"next_move": "인하", "timing": "2026-10", "prob": 0.62},
}


def test_stance_record_keeps_grades_and_drops_trigger_prose():
    r = stance_record(STANCE)
    assert r["report_date"] == "2026-08-21"
    eq = r["assets"]["equities"]
    assert eq["grade"] == 1
    assert eq["label"] == "소폭확대"
    assert eq["since"] == "2026-08-21"
    assert eq["thesis"] == "브레드스 확산 트리거 충족."
    # 트리거는 발동 판정에 필요한 필드만 남는다 — desc 산문은 버린다
    t = eq["triggers"]["increase"][0]
    assert t == {"kind": "metric", "metric": "spx_vs_50dma_pct",
                 "op": ">", "value": 4.0, "toward": "+"}


def test_macro_record_keeps_regime_and_policy():
    r = macro_record(MACRO)
    assert r["regime"]["growth"] == 0
    assert r["regime"]["name"] == "교착"
    assert r["policy_path"]["timing"] == "2026-10"


def test_append_jsonl_is_idempotent_on_report_date(tmp_path):
    p = os.path.join(tmp_path, "stance.jsonl")
    assert append_jsonl(p, stance_record(STANCE)) is True
    assert append_jsonl(p, stance_record(STANCE)) is False  # 같은 날짜 두 번 → 무시
    rows = read_jsonl(p)
    assert len(rows) == 1


def test_append_jsonl_keeps_rows_sorted_by_date(tmp_path):
    p = os.path.join(tmp_path, "stance.jsonl")
    append_jsonl(p, {"report_date": "2026-08-21", "v": 2})
    append_jsonl(p, {"report_date": "2026-08-19", "v": 1})
    assert [r["report_date"] for r in read_jsonl(p)] == ["2026-08-19", "2026-08-21"]


def test_read_jsonl_missing_file_is_empty(tmp_path):
    assert read_jsonl(os.path.join(tmp_path, "nope.jsonl")) == []


def test_read_jsonl_skips_corrupt_line(tmp_path):
    p = os.path.join(tmp_path, "x.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"report_date": "2026-08-19"}) + "\n")
        fh.write("{ not json\n")
        fh.write(json.dumps({"report_date": "2026-08-20"}) + "\n")
    assert len(read_jsonl(p)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_history.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.history'`

- [ ] **Step 3: Write minimal implementation**

`scripts/us/history.py`:

```python
"""Append-only 이력 — stance.json / macro.json 은 매일 덮어쓰기라 과거 판단이 남지 않는다.

주간·월간 복기가 이 로그를 소비하지만, 로그 자체는 그것과 무관하게 있어야 할 자산이다.
쓰기는 멱등이다 — 같은 report_date 를 두 번 넣어도 한 줄이다.
"""

import json
import os

# 발동 판정에 필요한 필드만 — desc 산문은 매일 바뀌어 이력을 부풀리기만 한다
_TRIGGER_KEYS = ('kind', 'metric', 'op', 'value', 'toward')
_ASSET_KEYS = ('grade', 'label', 'since', 'thesis', 'tilt', 'curve')


def _trigger(t):
    return {k: t[k] for k in _TRIGGER_KEYS if k in t}


def stance_record(stance):
    assets = {}
    for key, a in (stance.get('assets') or {}).items():
        row = {k: a[k] for k in _ASSET_KEYS if k in a}
        trig = a.get('triggers') or {}
        row['triggers'] = {d: [_trigger(t) for t in (trig.get(d) or [])]
                           for d in ('increase', 'decrease')}
        assets[key] = row
    return {'report_date': stance.get('report_date'),
            'horizon': stance.get('horizon'),
            'assets': assets}


def macro_record(macro):
    return {'report_date': macro.get('report_date'),
            'horizon': macro.get('horizon'),
            'regime': macro.get('regime'),
            'policy_path': macro.get('policy_path')}


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # 손상된 줄 하나가 이력 전체를 못 읽게 만들지 않는다
    return rows


def append_jsonl(path, record, key='report_date'):
    """Returns True if written, False if a row with the same key already existed."""
    val = record.get(key)
    if val is None:
        return False
    rows = read_jsonl(path)
    if any(r.get(key) == val for r in rows):
        return False
    rows.append(record)
    rows.sort(key=lambda r: r.get(key) or '')
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_history.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/history.py scripts/us/tests/test_history.py
git commit -m "승계 책 이력을 append-only 로그로 남긴다"
```

---

### Task 2: git 히스토리 백필 스크립트

**Files:**
- Create: `scripts/backfill_history.py`
- Test: `scripts/us/tests/test_backfill_history.py`

**Interfaces:**
- Consumes: `us.history.append_jsonl`, `us.history.stance_record`, `us.history.macro_record`
- Produces: `backfill(blobs: list[str], record_fn, out_path: str) -> int` — `blobs`는 오래된 것부터 정렬된 JSON 문자열 목록, 반환값은 새로 쓴 줄 수

- [ ] **Step 1: Write the failing test**

`scripts/us/tests/test_backfill_history.py`:

```python
import json
import os

from backfill_history import backfill
from us.history import read_jsonl, stance_record


def _blob(date, grade):
    return json.dumps({"report_date": date, "horizon": "2-6주",
                       "assets": {"equities": {"grade": grade, "label": "중립",
                                               "since": date, "thesis": "t",
                                               "triggers": {"increase": [], "decrease": []}}}})


def test_backfill_writes_each_distinct_date(tmp_path):
    out = os.path.join(tmp_path, "stance.jsonl")
    n = backfill([_blob("2026-08-19", 0), _blob("2026-08-20", 1)], stance_record, out)
    assert n == 2
    assert [r["report_date"] for r in read_jsonl(out)] == ["2026-08-19", "2026-08-20"]


def test_backfill_is_idempotent(tmp_path):
    out = os.path.join(tmp_path, "stance.jsonl")
    blobs = [_blob("2026-08-19", 0), _blob("2026-08-20", 1)]
    backfill(blobs, stance_record, out)
    assert backfill(blobs, stance_record, out) == 0
    assert len(read_jsonl(out)) == 2


def test_backfill_skips_unparsable_blob(tmp_path):
    out = os.path.join(tmp_path, "stance.jsonl")
    n = backfill(["{ not json", _blob("2026-08-20", 1)], stance_record, out)
    assert n == 1


def test_backfill_dedupes_repeated_date_within_one_run(tmp_path):
    out = os.path.join(tmp_path, "stance.jsonl")
    # 같은 날짜가 여러 커밋에 걸쳐 나타난다 (그날 두 번 커밋된 경우)
    n = backfill([_blob("2026-08-20", 0), _blob("2026-08-20", 1)], stance_record, out)
    assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_backfill_history.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backfill_history'`

- [ ] **Step 3: Write minimal implementation**

`scripts/backfill_history.py`:

```python
#!/usr/bin/env python3
"""stance.json / macro.json 의 과거 판단을 git 히스토리에서 1회 백필한다.

두 파일은 매일 덮어쓰기라 이력이 커밋에만 남아 있다. 이 스크립트는 각 커밋의 blob 을
읽어 data/history/*.jsonl 로 옮긴다. 여러 번 돌려도 안전하다 (report_date 로 멱등).

  python3 scripts/backfill_history.py --repo . --outdir data/history
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.history import append_jsonl, macro_record, stance_record  # noqa: E402


def backfill(blobs, record_fn, out_path):
    written = 0
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except ValueError:
            continue
        try:
            rec = record_fn(obj)
        except Exception:
            continue
        if append_jsonl(out_path, rec):
            written += 1
    return written


def git_blobs(repo, path):
    """Every committed version of `path`, oldest first."""
    rev = subprocess.run(['git', '-C', repo, 'log', '--format=%H', '--reverse', '--', path],
                         capture_output=True, text=True, check=True)
    out = []
    for sha in rev.stdout.split():
        show = subprocess.run(['git', '-C', repo, 'show', f'{sha}:{path}'],
                              capture_output=True, text=True)
        if show.returncode == 0:
            out.append(show.stdout)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='.')
    ap.add_argument('--outdir', default='data/history')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for src, fn, name in (('data/stance.json', stance_record, 'stance.jsonl'),
                          ('data/macro.json', macro_record, 'macro.jsonl')):
        blobs = git_blobs(args.repo, src)
        n = backfill(blobs, fn, os.path.join(args.outdir, name))
        print(f'{src}: {len(blobs)} commits -> {n} new rows in {name}')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_backfill_history.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the backfill for real and inspect**

```bash
python3 scripts/backfill_history.py --repo . --outdir data/history
wc -l data/history/*.jsonl
head -c 300 data/history/stance.jsonl
```

Expected: `stance.jsonl` 6줄 안팎, `macro.jsonl` 비슷한 규모. 줄 수가 0이면 `git log -- data/stance.json`을 직접 확인할 것.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_history.py scripts/us/tests/test_backfill_history.py data/history
git commit -m "과거 스탠스·레짐 판단을 git 히스토리에서 백필"
```

---

### Task 3: 수집기에 승계 로그 append 연결

**Files:**
- Modify: `scripts/collect_market_data.py` (main() 끝, `market_data.json` 쓰기 직후)
- Test: 없음 (Task 1이 로직을 덮는다 — 여기는 배선만)

**Interfaces:**
- Consumes: `us.history.append_jsonl`, `stance_record`, `macro_record`
- Produces: `data/history/stance.jsonl`, `data/history/macro.jsonl` 갱신

- [ ] **Step 1: 배선 코드 추가**

`scripts/collect_market_data.py`의 `main()`에서 `json.dump(data, open(md_path, ...))` 바로 뒤에 넣는다:

```python
    # 승계 책 이력 — 오늘 커밋돼 있는 stance/macro 를 로그에 밀어 넣는다.
    # 어제까지의 판단이 대상이다 (오늘 것은 아직 writer 가 만들지 않았다).
    try:
        from us.history import append_jsonl, macro_record, stance_record
        hdir = os.path.join(args.outdir, 'history')
        for name, fn, out in (('stance.json', stance_record, 'stance.jsonl'),
                              ('macro.json', macro_record, 'macro.jsonl')):
            src = os.path.join(args.outdir, name)
            if not os.path.exists(src):
                continue
            book = json.load(open(src, encoding='utf-8'))
            if append_jsonl(os.path.join(hdir, out), fn(book)):
                print(f"history: appended {book.get('report_date')} to {out}")
    except Exception as e:
        print(f'history append failed: {e}', file=sys.stderr)
```

`except`로 감싸는 이유는 기존 관례와 같다 — 비-코어 산출물의 실패가 시장데이터 수집 전체를 죽이면 안 된다.

- [ ] **Step 2: 로컬에서 배선만 확인**

```bash
python3 - <<'PY'
import json, os, sys
sys.path.insert(0, 'scripts')
from us.history import append_jsonl, stance_record
book = json.load(open('data/stance.json', encoding='utf-8'))
print('append?', append_jsonl('/tmp/probe.jsonl', stance_record(book)))
print('again? ', append_jsonl('/tmp/probe.jsonl', stance_record(book)))
PY
```

Expected: `append? True` / `again?  False`

- [ ] **Step 3: 워크플로가 history 를 커밋하는지 확인**

`.github/workflows/collect-market-data.yml`의 `git add` 라인을 열어 `data/` 전체를 담는지 확인한다. 개별 파일을 나열하고 있으면 `data/history` 를 추가한다.

```bash
grep -n "git add" .github/workflows/collect-market-data.yml
```

- [ ] **Step 4: Commit**

```bash
git add scripts/collect_market_data.py .github/workflows/collect-market-data.yml
git commit -m "수집기가 매일 승계 책을 이력에 밀어 넣는다"
```

---

### Task 4: US 기간 집계 코어

**Files:**
- Create: `scripts/us/period.py`
- Test: `scripts/us/tests/test_period.py`

**Interfaces:**
- Consumes: 없음 (순수 계산)
- Produces:
  - `week_key(d: str) -> str` — `"2026-08-21"` → `"2026-W34"`
  - `month_key(d: str) -> str` — `"2026-08-21"` → `"2026-08"`
  - `slice_series(series: list[tuple[str, float]], start: str, end: str) -> list[tuple[str, float]]`
  - `pct_change(series, start, end) -> float | None`
  - `build(span: str, key: str, closes: dict[str, dict[str, list]], yields_hist: dict, daily_headlines: list[dict]) -> dict`
    - `closes` = `{group: {name: [(date, close), ...]}}`, group ∈ `indices/sectors/fx/commodities/memory/ai_infra`
    - `yields_hist` = `{tenor: [(date, level_pct), ...]}`
    - 반환은 스펙 §데이터 계약의 집계 스키마

- [ ] **Step 1: Write the failing test**

`scripts/us/tests/test_period.py`:

```python
import pytest

from us.period import build, month_key, pct_change, slice_series, week_key


def test_week_key_is_iso_and_zero_padded():
    assert week_key("2026-08-21") == "2026-W34"
    assert week_key("2026-01-02") == "2026-W01"


def test_week_key_uses_iso_year_not_calendar_year():
    # 2027-01-01 은 금요일 → ISO 로는 2026년 53주차
    assert week_key("2027-01-01") == "2026-W53"


def test_month_key():
    assert month_key("2026-08-21") == "2026-08"


SPX = [("2026-08-14", 100.0), ("2026-08-17", 101.0), ("2026-08-18", 102.0),
       ("2026-08-19", 103.0), ("2026-08-20", 104.0), ("2026-08-21", 110.0)]


def test_slice_series_is_inclusive_both_ends():
    got = slice_series(SPX, "2026-08-17", "2026-08-19")
    assert [d for d, _ in got] == ["2026-08-17", "2026-08-18", "2026-08-19"]


def test_pct_change_measures_from_the_close_before_the_window():
    # 주간 수익률은 직전 주 마지막 종가 대비다 — 창 안 첫 종가 대비가 아니다
    assert pct_change(SPX, "2026-08-17", "2026-08-21") == pytest.approx(10.0)


def test_pct_change_returns_none_without_a_prior_close():
    assert pct_change(SPX, "2026-08-14", "2026-08-21") is None


def test_pct_change_returns_none_when_window_is_empty():
    assert pct_change(SPX, "2026-09-01", "2026-09-05") is None


def _closes():
    def s(v0, v1):
        return [("2026-08-14", v0), ("2026-08-17", v0), ("2026-08-21", v1)]
    return {
        "indices": {"S&P 500": s(100.0, 110.0), "Nasdaq": s(100.0, 105.0)},
        "sectors": {"Technology": s(100.0, 120.0), "Energy": s(100.0, 90.0)},
        "fx": {"DXY": s(100.0, 99.0)},
        "commodities": {"WTI": s(100.0, 101.0)},
        "memory": {"Micron": s(100.0, 130.0), "Nvidia": s(100.0, 110.0)},
        "ai_infra": {"Marvell": s(100.0, 105.0)},
    }


YIELDS = {"10Y": [("2026-08-14", 4.20), ("2026-08-17", 4.25), ("2026-08-21", 4.35)],
          "2Y": [("2026-08-14", 4.10), ("2026-08-21", 4.15)]}

HEADLINES = [{"date": "2026-08-21", "headline": "재무부 바이백 확대"}]


def test_build_sets_span_key_and_boundaries():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    assert r["span"] == "weekly"
    assert r["key"] == "2026-W34"
    assert r["start_date"] == "2026-08-17"
    assert r["end_date"] == "2026-08-21"
    assert r["sessions"] == 2


def test_build_ranks_sectors_best_first():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    assert r["sectors"]["Technology"]["rank"] == 1
    assert r["sectors"]["Technology"]["pct"] == pytest.approx(20.0)
    assert r["sectors"]["Energy"]["rank"] == 2


def test_build_computes_basket_excess_over_spx():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    # 메모리 바스켓 = (30 + 10) / 2 = 20%, S&P 500 = 10% → 초과 10%p
    assert r["memory"]["basket_pct"] == pytest.approx(20.0)
    assert r["memory"]["basket_excess_pct"] == pytest.approx(10.0)
    assert r["ai_infra"]["basket_excess_pct"] == pytest.approx(-5.0)


def test_build_reports_yield_change_in_bp():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    assert r["yields"]["10Y"]["chg_bp"] == pytest.approx(15.0)


def test_build_computes_curve_spread_change():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    # 2s10s: 시작 (4.20-4.10)=10bp, 끝 (4.35-4.15)=20bp
    assert r["curve"]["spread_2s10s_bp"]["chg"] == pytest.approx(10.0)


def test_build_flags_incomplete_when_a_series_is_missing():
    c = _closes()
    c["indices"]["Dow"] = []
    r = build("weekly", "2026-W34", c, YIELDS, HEADLINES)
    assert r["complete"] is False
    assert "indices.Dow" in r["missing"]


def test_build_carries_daily_headlines_ascending():
    r = build("weekly", "2026-W34", _closes(), YIELDS,
              [{"date": "2026-08-21", "headline": "b"}, {"date": "2026-08-17", "headline": "a"}])
    assert [x["date"] for x in r["daily"]] == ["2026-08-17", "2026-08-21"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_period.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.period'`

- [ ] **Step 3: Write minimal implementation**

`scripts/us/period.py`:

```python
"""기간(주/월) 집계 — 순수 계산.

일간 data/*.json 은 매일 덮어쓰기라 기간 수익률이 없다. 여기서 dated close series 를
받아 다시 계산한다. 네트워크는 collect_market_data.py 가 맡는다.

기간 파일은 **기간 키로 나뉘어** 저장되므로(2026-W34.json / 2026-08.json) 주·달이 넘어가면
지난 기간 파일이 저절로 확정본이 된다 — 휴장 달력도, 동결 단계도 필요 없다.
"""

from datetime import date

GROUPS = ('indices', 'sectors', 'fx', 'commodities', 'memory', 'ai_infra')
BASKETS = ('memory', 'ai_infra')
BENCHMARK = 'S&P 500'


def _d(s):
    y, m, dd = (int(x) for x in s.split('-'))
    return date(y, m, dd)


def week_key(d):
    y, w, _ = _d(d).isocalendar()
    return f'{y}-W{w:02d}'


def month_key(d):
    return d[:7]


def slice_series(series, start, end):
    return [(d, v) for d, v in series if start <= d <= end]


def pct_change(series, start, end):
    """직전 종가 대비 기간 수익률(%). 창 앞 종가가 없으면 None."""
    window = slice_series(series, start, end)
    if not window:
        return None
    before = [v for d, v in series if d < start]
    if not before:
        return None
    base, last = before[-1], window[-1][1]
    if not base:
        return None
    return (last / base - 1) * 100


def level_change(series, start, end):
    """금리처럼 레벨을 그대로 쓰는 계열 — (start_level, end_level, 변화)."""
    window = slice_series(series, start, end)
    if not window:
        return None, None, None
    before = [v for d, v in series if d < start]
    base = before[-1] if before else window[0][1]
    return base, window[-1][1], window[-1][1] - base


def _bounds(closes, key, span):
    """기간에 실제로 존재한 거래일에서 start/end 를 뽑는다 — 날짜 산술을 쓰지 않는다."""
    keyer = week_key if span == 'weekly' else month_key
    dates = sorted({d for g in GROUPS for s in (closes.get(g) or {}).values()
                    for d, _ in (s or []) if keyer(d) == key})
    return (dates[0], dates[-1], len(dates)) if dates else (None, None, 0)


def build(span, key, closes, yields_hist, daily_headlines):
    start, end, sessions = _bounds(closes, key, span)
    out = {'span': span, 'key': key, 'start_date': start, 'end_date': end,
           'sessions': sessions, 'complete': True, 'missing': []}
    if start is None:
        out['complete'] = False
        out['missing'].append('no sessions in period')
        return out

    for g in GROUPS:
        rows = {}
        for name, series in (closes.get(g) or {}).items():
            p = pct_change(series or [], start, end)
            if p is None:
                out['complete'] = False
                out['missing'].append(f'{g}.{name}')
                rows[name] = None
                continue
            window = slice_series(series, start, end)
            before = [v for d, v in series if d < start]
            rows[name] = {'start': before[-1], 'end': window[-1][1], 'pct': round(p, 4)}
        out[g] = rows

    # 섹터 순위 — 좋은 것부터. 게이트가 이 rank 와 대조하므로 여기서 확정한다.
    ranked = sorted(((n, r['pct']) for n, r in (out.get('sectors') or {}).items() if r),
                    key=lambda x: -x[1])
    for i, (n, _) in enumerate(ranked, 1):
        out['sectors'][n]['rank'] = i

    spx = (out.get('indices') or {}).get(BENCHMARK)
    for g in BASKETS:
        vals = [r['pct'] for r in (out.get(g) or {}).values() if r]
        if vals:
            b = sum(vals) / len(vals)
            out[g]['basket_pct'] = round(b, 4)
            out[g]['basket_excess_pct'] = round(b - spx['pct'], 4) if spx else None

    yields = {}
    for tenor, series in (yields_hist or {}).items():
        s0, s1, chg = level_change(series or [], start, end)
        if chg is None:
            out['complete'] = False
            out['missing'].append(f'yields.{tenor}')
            continue
        yields[tenor] = {'start': s0, 'end': s1, 'chg_bp': round(chg * 100, 2)}
    out['yields'] = yields

    curve = {}
    for name, (short, long_) in (('spread_2s10s_bp', ('2Y', '10Y')),
                                 ('spread_5s30s_bp', ('5Y', '30Y'))):
        a, b = yields.get(short), yields.get(long_)
        if a and b:
            s0 = (b['start'] - a['start']) * 100
            s1 = (b['end'] - a['end']) * 100
            curve[name] = {'start': round(s0, 2), 'end': round(s1, 2), 'chg': round(s1 - s0, 2)}
    out['curve'] = curve

    out['daily'] = sorted((x for x in (daily_headlines or []) if start <= x['date'] <= end),
                          key=lambda x: x['date'])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_period.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/period.py scripts/us/tests/test_period.py
git commit -m "US 기간 집계 — 주·월 키로 나뉘는 수익률 계산"
```

---

### Task 5: US 수집기에 기간 집계 연결

**Files:**
- Modify: `scripts/collect_market_data.py` (신규 함수 + `main()` 배선)
- Modify: `.github/workflows/collect-market-data.yml` (커밋 대상에 `data/weekly` `data/monthly`)

**Interfaces:**
- Consumes: `us.period.build`, `us.period.week_key`, `us.period.month_key`, 기존 `GROUPS`, `fred_series`
- Produces: `data/weekly/<key>.json`, `data/monthly/<key>.json`

- [ ] **Step 1: 다운로드 함수 추가**

`scripts/collect_market_data.py`의 `collect_histories()` 아래에 넣는다:

```python
def collect_dated_closes(period='3mo'):
    """{group: {name: [(date, close), ...]}} — 기간 집계용. 3개월이면 주·월 모두 덮는다."""
    import yfinance as yf
    tickers = [t for _, pairs in GROUPS for _, t in pairs]

    def dl():
        df = yf.download(tickers, period=period, interval='1d', group_by='ticker',
                         auto_adjust=True, progress=False, threads=False)
        return df if df is not None and len(df) else None

    df = retry(dl)
    out = {}
    for group, pairs in GROUPS:
        out[group] = {}
        for name, t in pairs:
            try:
                closes = df[t]['Close'].dropna()
                out[group][name] = [(str(i.date()), float(v)) for i, v in closes.items()]
            except Exception:
                out[group][name] = []
    return out


def yield_histories():
    """{tenor: [(date, level_pct), ...]} — FRED 일별. 기간 bp 변화는 이 계열로 잰다.

    발행용 스팟(야후)과 달리 기간 변화는 만기별 기준일이 섞이면 안 되므로 FRED 로 통일한다.
    """
    out = {}
    for tenor, sid in (('2Y', 'DGS2'), ('5Y', 'DGS5'), ('10Y', 'DGS10'), ('30Y', 'DGS30')):
        try:
            out[tenor] = [(d, v) for d, v in fred_series(sid) if v is not None]
        except Exception as e:
            print(f'yield history {tenor} failed: {e}', file=sys.stderr)
            out[tenor] = []
    return out


def daily_headlines(repo_root):
    """posts.json 에서 (date, headline) 회수 — 그 주의 촉매는 일간이 이미 확정했다."""
    p = os.path.join(repo_root, 'posts.json')
    if not os.path.exists(p):
        return []
    try:
        posts = json.load(open(p, encoding='utf-8'))
    except Exception:
        return []
    return [{'date': x['date'], 'headline': x.get('headline', '')} for x in posts if x.get('date')]
```

`fred_series(sid)`는 `[(date, value), ...]`를 오래된 것부터 돌려주고 `.` 행을 이미 버린다 (`scripts/collect_market_data.py:231` 확인 완료) — 위 컴프리헨션이 그대로 맞는다.

- [ ] **Step 2: main() 배선**

`json.dump(data, open(md_path, ...))` 뒤, Task 3의 history 블록 옆에 넣는다:

```python
    # 기간 집계 — 기간 키로 나눠 쓰므로 주/달이 넘어가면 지난 파일이 곧 확정본이다.
    try:
        from us.period import build as period_build, month_key, week_key
        dated = collect_dated_closes()
        yh = yield_histories()
        heads = daily_headlines(os.path.dirname(os.path.abspath(args.outdir)) or '.')
        for span, keyer, sub in (('weekly', week_key, 'weekly'), ('monthly', month_key, 'monthly')):
            k = keyer(report_date)
            agg = period_build(span, k, dated, yh, heads)
            d = os.path.join(args.outdir, sub)
            os.makedirs(d, exist_ok=True)
            json.dump(agg, open(os.path.join(d, f'{k}.json'), 'w'),
                      indent=2, default=str, ensure_ascii=False)
            print(f"{span} {k}: {agg['sessions']} sessions, "
                  f"complete={agg['complete']}")
    except Exception as e:
        print(f'period aggregation failed: {e}', file=sys.stderr)
```

- [ ] **Step 3: 로컬 스모크 — 네트워크로 실제 한 번 돌린다**

```bash
python3 - <<'PY'
import sys, json, os
sys.path.insert(0, 'scripts')
import collect_market_data as C
from us.period import build, week_key
dated = C.collect_dated_closes(period='1mo')
yh = C.yield_histories()
heads = C.daily_headlines('.')
k = week_key(json.load(open('data/market_data.json'))['report_date'])
agg = build('weekly', k, dated, yh, heads)
print(k, agg['start_date'], agg['end_date'], agg['sessions'], agg['complete'], agg['missing'][:5])
print('SPX', agg['indices'].get('S&P 500'))
print('memory excess', agg['memory'].get('basket_excess_pct'))
PY
```

Expected: 키가 `2026-Wxx`, `sessions`가 5(정상 주간), `complete: True`, S&P 500 주간 수익률이 그럴듯한 한 자릿수. `missing`이 차 있으면 그 티커의 다운로드 실패이므로 원인을 먼저 잡는다.

- [ ] **Step 4: 워크플로 커밋 대상 확인**

```bash
grep -n "git add" .github/workflows/collect-market-data.yml
```

`data/` 전체가 아니면 `data/weekly data/monthly data/history` 를 추가한다.

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_market_data.py .github/workflows/collect-market-data.yml
git commit -m "수집기가 주·월 집계를 기간 키로 커밋한다"
```

---

### Task 6: KR 기간 집계 코어

**Files:**
- Create: `scripts/kr/period.py`
- Test: `scripts/kr/tests/test_period.py`

**Interfaces:**
- Consumes: `us.period.week_key`·`month_key` (재사용 — 같은 ISO 규칙)
- Produces:
  - `upsert_session(agg: dict, session: dict) -> dict` — 날짜 키로 갈아끼운다 (중복 합산 방지)
  - `session_from(kr_market: dict, kr_flows: dict, kr_industry: list, kr_top_value: list) -> dict`
  - `finalize(agg: dict, index_closes: dict) -> dict` — 합계·순위·수익률을 확정

- [ ] **Step 1: Write the failing test**

`scripts/kr/tests/test_period.py`:

```python
import pytest

from kr.period import finalize, session_from, upsert_session

MARKET = {"report_date": "2026-08-21",
          "indices": {"KOSPI": {"close": 6912.95, "change_pct": 0.88},
                      "KOSDAQ": {"close": 801.94, "change_pct": -4.63}}}

FLOWS = {"KOSPI": {"rows": [{"date": "2026-08-21", "foreign": -1760,
                             "institution": 2481, "individual": -11652},
                            {"date": "2026-08-20", "foreign": 17068,
                             "institution": -4895, "individual": -22712}],
                   "flows_provisional": False},
         "KOSDAQ": {"rows": [{"date": "2026-08-21", "foreign": 100,
                              "institution": -50, "individual": -50}],
                    "flows_provisional": False}}

INDUSTRY = [{"name": "생명보험", "change_pct": 8.88, "breadth": 0.25, "leading": True},
            {"name": "손해보험", "change_pct": 4.8, "breadth": 0.5, "leading": False}]

TOPVAL = [{"label": "삼성전자", "kind": "stock", "value": 7682302},
          {"label": "SK하이닉스", "kind": "stock", "value": 7384023}]


def _agg():
    return {"span": "weekly", "key": "2026-W34", "sessions": {}}


def test_session_from_collects_one_days_contribution():
    s = session_from(MARKET, FLOWS, INDUSTRY, TOPVAL)
    assert s["date"] == "2026-08-21"
    assert s["flows"]["KOSPI"]["foreign"] == -1760
    assert s["top_value"]["삼성전자"] == 7682302
    assert s["leading_industries"] == ["생명보험"]


def test_session_from_drops_provisional_flows():
    f = {"KOSPI": {"rows": [{"date": "2026-08-21", "foreign": 1, "institution": 2,
                             "individual": 3}], "flows_provisional": True},
         "KOSDAQ": {"rows": [], "flows_provisional": True}}
    s = session_from(MARKET, f, INDUSTRY, TOPVAL)
    assert s["flows"] == {}          # 잠정치는 담지 않는다
    assert s["flows_note"] == "잠정치 제외"


def test_session_from_backfills_older_confirmed_flow_rows():
    # kr_flows.json 은 10일치를 들고 있다 — 지난 날짜도 같이 회수해 월간을 자가치유시킨다
    s = session_from(MARKET, FLOWS, INDUSTRY, TOPVAL)
    assert "2026-08-20" in s["extra_flow_dates"]
    assert s["extra_flows"]["2026-08-20"]["KOSPI"]["foreign"] == 17068


def test_upsert_replaces_same_date_instead_of_double_counting():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-21", "flows": {"KOSPI": {"foreign": 100}}})
    a = upsert_session(a, {"date": "2026-08-21", "flows": {"KOSPI": {"foreign": 200}}})
    assert len(a["sessions"]) == 1
    assert a["sessions"]["2026-08-21"]["flows"]["KOSPI"]["foreign"] == 200


def test_finalize_sums_flows_over_confirmed_sessions_only():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-20",
                           "flows": {"KOSPI": {"foreign": 10, "institution": 1,
                                               "individual": -11}}})
    a = upsert_session(a, {"date": "2026-08-21",
                           "flows": {"KOSPI": {"foreign": -4, "institution": 2,
                                               "individual": 2}}})
    a = upsert_session(a, {"date": "2026-08-19", "flows": {}})   # 잠정치라 비었던 날
    r = finalize(a, {})
    assert r["flows"]["KOSPI"]["foreign"] == 6
    assert r["flows_sessions"] == 2       # 3일이 아니라 2일 — 확정치만 센다
    assert r["sessions"] == 3


def test_finalize_computes_index_returns_from_dated_closes():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-21", "flows": {}})
    closes = {"KOSPI": [("2026-08-14", 6000.0), ("2026-08-21", 6900.0)]}
    r = finalize(a, closes)
    assert r["indices"]["KOSPI"]["pct"] == pytest.approx(15.0)


def test_finalize_ranks_industries_by_mean_change():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-20", "flows": {},
                           "industry": {"생명보험": 2.0, "손해보험": 6.0}})
    a = upsert_session(a, {"date": "2026-08-21", "flows": {},
                           "industry": {"생명보험": 8.0, "손해보험": 0.0}})
    r = finalize(a, {})
    assert r["industry"]["생명보험"]["pct"] == pytest.approx(5.0)
    assert r["industry"]["생명보험"]["rank"] == 1


def test_finalize_sums_top_value_across_sessions():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-20", "flows": {}, "top_value": {"삼성전자": 100}})
    a = upsert_session(a, {"date": "2026-08-21", "flows": {},
                           "top_value": {"삼성전자": 50, "SK하이닉스": 300}})
    r = finalize(a, {})
    assert r["top_value"][0] == {"name": "SK하이닉스", "value": 300}
    assert r["top_value"][1] == {"name": "삼성전자", "value": 150}


def test_finalize_sets_boundaries_from_session_dates():
    a = _agg()
    for d in ("2026-08-21", "2026-08-17", "2026-08-19"):
        a = upsert_session(a, {"date": d, "flows": {}})
    r = finalize(a, {})
    assert r["start_date"] == "2026-08-17"
    assert r["end_date"] == "2026-08-21"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/kr/tests/test_period.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'kr.period'`

- [ ] **Step 3: Write minimal implementation**

`scripts/kr/period.py`:

```python
"""KR 기간 집계 — 세션 단위로 누적한다.

US 와 달리 업종·거래대금은 그날 스냅샷만 있고 과거 계열이 없다. 그래서 기간 파일이
날짜 키로 세션을 담고, 매 실행이 그날치를 **갈아끼운다**(upsert). 두 번 돌아도 두 번
더해지지 않고, 실패한 날은 다음 실행이 메운다.

수급은 확정치만 담는다. 잠정치를 섞으면 나중에 정정되면서 수치가 조용히 틀려진다
(2026-08-05 실측: 장중 +15,116 vs 확정 +14,464).
"""

MARKETS = ('KOSPI', 'KOSDAQ')
SIDES = ('foreign', 'institution', 'individual')


def session_from(kr_market, kr_flows, kr_industry, kr_top_value):
    date = (kr_market or {}).get('report_date')
    out = {'date': date, 'flows': {}, 'industry': {}, 'top_value': {},
           'leading_industries': [], 'extra_flows': {}, 'extra_flow_dates': []}

    for mkt in MARKETS:
        blk = (kr_flows or {}).get(mkt) or {}
        for row in (blk.get('rows') or []):
            d = row.get('date')
            if d is None:
                continue
            if d == date and blk.get('flows_provisional'):
                continue                      # 당일 잠정치는 버린다
            vals = {s: row.get(s) for s in SIDES}
            if d == date:
                out['flows'][mkt] = vals
            else:
                out['extra_flows'].setdefault(d, {})[mkt] = vals
    out['extra_flow_dates'] = sorted(out['extra_flows'])
    if not out['flows']:
        out['flows_note'] = '잠정치 제외'

    for row in (kr_industry or []):
        if row.get('name') is not None:
            out['industry'][row['name']] = row.get('change_pct')
    out['leading_industries'] = [r['name'] for r in (kr_industry or []) if r.get('leading')]

    for row in (kr_top_value or []):
        if row.get('label') is not None:
            out['top_value'][row['label']] = row.get('value') or 0
    return out


def upsert_session(agg, session):
    agg.setdefault('sessions', {})
    d = session.get('date')
    if d is None:
        return agg
    agg['sessions'][d] = {k: v for k, v in session.items() if k != 'date'}
    return agg


def _pct(series, start, end):
    window = [(d, v) for d, v in series if start <= d <= end]
    before = [v for d, v in series if d < start]
    if not window or not before or not before[-1]:
        return None
    return (window[-1][1] / before[-1] - 1) * 100


def finalize(agg, index_closes):
    sess = agg.get('sessions') or {}
    dates = sorted(sess)
    out = {'span': agg.get('span'), 'key': agg.get('key'),
           'start_date': dates[0] if dates else None,
           'end_date': dates[-1] if dates else None,
           'sessions': len(dates), 'complete': bool(dates), 'missing': []}

    flows, n_flow = {}, 0
    for d in dates:
        f = (sess[d].get('flows') or {})
        if not f:
            continue
        n_flow += 1
        for mkt, vals in f.items():
            tgt = flows.setdefault(mkt, dict.fromkeys(SIDES, 0))
            for s in SIDES:
                if vals.get(s) is not None:
                    tgt[s] += vals[s]
    out['flows'] = flows
    out['flows_sessions'] = n_flow
    out['flows_note'] = '확정치만 합산'
    if n_flow < len(dates):
        out['missing'].append(f'flows: {len(dates) - n_flow}일 잠정/결측')

    ind = {}
    for d in dates:
        for name, pct in (sess[d].get('industry') or {}).items():
            if pct is not None:
                ind.setdefault(name, []).append(pct)
    rows = {n: {'pct': round(sum(v) / len(v), 4), 'sessions': len(v)} for n, v in ind.items()}
    for i, (n, _) in enumerate(sorted(rows.items(), key=lambda x: -x[1]['pct']), 1):
        rows[n]['rank'] = i
    out['industry'] = rows

    tv = {}
    for d in dates:
        for name, val in (sess[d].get('top_value') or {}).items():
            tv[name] = tv.get(name, 0) + (val or 0)
    out['top_value'] = [{'name': n, 'value': v}
                        for n, v in sorted(tv.items(), key=lambda x: -x[1])]

    idx = {}
    for name, series in (index_closes or {}).items():
        p = _pct(series or [], out['start_date'], out['end_date']) if dates else None
        if p is None:
            out['complete'] = False
            out['missing'].append(f'indices.{name}')
            continue
        idx[name] = {'pct': round(p, 4), 'end': series[-1][1]}
    out['indices'] = idx

    out['daily'] = [{'date': d,
                     'leading_industries': sess[d].get('leading_industries') or []}
                    for d in dates]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/kr/tests/test_period.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/kr/period.py scripts/kr/tests/test_period.py
git commit -m "KR 기간 집계 — 세션 upsert 로 중복 합산을 막는다"
```

---

### Task 7: KR 수집기에 기간 집계 연결

**Files:**
- Modify: `scripts/collect_kr_data.py` (`main()` 끝, `_write` 호출부 뒤)
- Modify: `.github/workflows/collect-kr-data.yml` (커밋 대상)

**Interfaces:**
- Consumes: `kr.period.session_from/upsert_session/finalize`, `us.period.week_key/month_key`
- Produces: `kr/data/weekly/<key>.json`, `kr/data/monthly/<key>.json`

- [ ] **Step 1: 배선 코드 추가**

`scripts/collect_kr_data.py`의 `main()` 마지막 `_write(...)` 호출들 뒤에 넣는다:

```python
    # 기간 집계 — 세션 upsert. 과거 확정 수급 행도 함께 메워 월간이 자가치유된다.
    try:
        import yfinance as _yf
        from kr.period import finalize, session_from, upsert_session
        from us.period import month_key, week_key

        sess = session_from(bundle_market, flows_out, industry_rows, top_value)

        closes = {}
        for name, tk in (("KOSPI", "^KS11"), ("KOSDAQ", "^KQ11")):
            try:
                df = _yf.download(tk, period="3mo", progress=False, auto_adjust=True)
                if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                    df.columns = df.columns.get_level_values(0)
                closes[name] = [(str(i.date()), float(v))
                                for i, v in df["Close"].dropna().items()]
            except Exception as e:
                print(f"kr index history {name} failed: {e}", file=sys.stderr)
                closes[name] = []

        for span, keyer, sub in (("weekly", week_key, "weekly"),
                                 ("monthly", month_key, "monthly")):
            k = keyer(report_date)
            d = os.path.join(outdir, sub)
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{k}.json")
            agg = {"span": span, "key": k, "sessions": {}}
            if os.path.exists(path):
                prev = json.load(open(path, encoding="utf-8"))
                agg["sessions"] = prev.get("_sessions") or {}
            agg = upsert_session(agg, sess)
            # 과거 확정 수급 행 — 같은 기간에 속하는 것만 메운다
            for ed, mkts in (sess.get("extra_flows") or {}).items():
                if keyer(ed) == k:
                    prior = agg["sessions"].get(ed) or {}
                    prior_flows = dict(prior.get("flows") or {})
                    prior_flows.update(mkts)
                    agg = upsert_session(agg, {"date": ed, **prior, "flows": prior_flows})
            final = finalize(agg, closes)
            final["_sessions"] = agg["sessions"]     # 다음 실행이 이어 쓸 원장
            _write(d, f"{k}.json", final)
            print(f"kr {span} {k}: {final['sessions']} sessions, "
                  f"flows {final['flows_sessions']}일")
    except Exception as e:
        print(f"kr period aggregation failed: {e}", file=sys.stderr)
```

**주의:** `bundle_market` / `industry_rows` / `top_value` / `outdir` 는 `main()` 안의 실제 변수명으로 바꿔야 한다. 먼저 확인한다:

```bash
grep -n "_write(" scripts/collect_kr_data.py
grep -n "industry\|top_value\|indices" scripts/collect_kr_data.py | head -20
```

- [ ] **Step 2: `_sessions` 원장이 리포트에 새지 않게 게이트에 등록**

`_sessions`는 내부 원장이다. Task 9의 게이트 내부 용어 목록에 `_sessions`를 넣는다 (해당 태스크에서 처리).

- [ ] **Step 3: 로컬 스모크**

```bash
python3 - <<'PY'
import sys, json
sys.path.insert(0, 'scripts')
from kr.period import session_from, upsert_session, finalize
from us.period import week_key
m = json.load(open('kr/data/kr_market_data.json'))
f = json.load(open('kr/data/kr_flows.json'))
ind = json.load(open('kr/data/kr_industry.json'))
tv = json.load(open('kr/data/kr_top_value.json'))
s = session_from(m, f, ind, tv)
print('date', s['date'], 'flows', list(s['flows']), 'extra', s['extra_flow_dates'][:4])
a = finalize(upsert_session({'span':'weekly','key':week_key(s['date']),'sessions':{}}, s), {})
print('sessions', a['sessions'], 'flows_sessions', a['flows_sessions'])
print('top3', a['top_value'][:3])
PY
```

Expected: `date`가 최신 KR 거래일, `flows`에 KOSPI/KOSDAQ(확정일 때), `extra`에 지난 날짜들, `top3`에 삼성전자·SK하이닉스급 이름.

- [ ] **Step 4: 워크플로 커밋 대상 확인**

```bash
grep -n "git add" .github/workflows/collect-kr-data.yml
```

`kr/data/` 전체가 아니면 `kr/data/weekly kr/data/monthly` 를 추가한다.

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_kr_data.py .github/workflows/collect-kr-data.yml
git commit -m "KR 수집기가 주·월 집계를 세션 단위로 누적한다"
```

---

### Task 8: 복기 스코어카드

**Files:**
- Create: `scripts/us/scorecard.py`
- Test: `scripts/us/tests/test_scorecard.py`

**Interfaces:**
- Consumes: `us.history.read_jsonl`, Task 4의 집계 파일 스키마
- Produces:
  - `realized(agg: dict) -> dict[str, float | None]` — 자산군 키 → 부호 규칙이 적용된 실현치
  - `segments(stance_rows: list[dict], start: str, end: str) -> dict[str, list[dict]]`
  - `score(stance_rows, agg) -> dict` — 자산군별·전체 가중 점수, 무판정·무포지션 집계
  - `regime_check(macro_rows, macro_metrics, start, end) -> dict`
  - `trigger_hygiene(stance_rows, end, stale_days: int = 20) -> dict`
  - `rollup(history_rows: list[dict], spans: tuple = (4, 12)) -> dict`

- [ ] **Step 1: Write the failing test**

`scripts/us/tests/test_scorecard.py`:

```python
import pytest

from us.scorecard import realized, regime_check, rollup, score, segments, trigger_hygiene

AGG = {
    "start_date": "2026-08-17", "end_date": "2026-08-21",
    "indices": {"S&P 500": {"pct": 2.0}},
    "yields": {"10Y": {"chg_bp": -12.0}},
    "fx": {"DXY": {"pct": -1.5}},
    "commodities": {"WTI": {"pct": 3.0}, "Gold": {"pct": 0.2}},
    "memory": {"basket_excess_pct": 4.0},
    "ai_infra": {"basket_excess_pct": -0.3},
}


def test_realized_maps_each_asset_to_its_series():
    r = realized(AGG)
    assert r["equities"] == pytest.approx(2.0)
    assert r["fx"] == pytest.approx(-1.5)
    assert r["energy"] == pytest.approx(3.0)
    assert r["metals"] == pytest.approx(0.2)
    assert r["memory"] == pytest.approx(4.0)
    assert r["ai_infra"] == pytest.approx(-0.3)


def test_realized_flips_the_sign_for_bonds():
    # 롱 듀레이션(+등급) = 금리 하락 베팅. 10Y −12bp 는 채권에게 플러스다.
    assert realized(AGG)["bonds"] == pytest.approx(12.0)


def _rows(*pairs):
    return [{"report_date": d, "assets": {k: {"grade": g} for k, g in grades.items()}}
            for d, grades in pairs]


def test_segments_uses_the_grade_in_force_at_period_start():
    rows = _rows(("2026-08-14", {"equities": 1}), ("2026-08-21", {"equities": 2}))
    segs = segments(rows, "2026-08-17", "2026-08-21")
    assert segs["equities"][0]["grade"] == 1


def test_segments_splits_when_the_grade_changes_mid_period():
    rows = _rows(("2026-08-14", {"equities": 1}),
                 ("2026-08-19", {"equities": -1}),
                 ("2026-08-21", {"equities": -1}))
    segs = segments(rows, "2026-08-17", "2026-08-21")
    assert [s["grade"] for s in segs["equities"]] == [1, -1]


def test_score_counts_a_matching_sign_as_a_hit():
    rows = _rows(("2026-08-14", {"equities": 2}))
    r = score(rows, AGG)
    assert r["assets"]["equities"]["verdict"] == "적중"
    assert r["weighted"] == pytest.approx(1.0)


def test_score_penalises_conviction_more_than_a_light_tilt():
    strong = score(_rows(("2026-08-14", {"equities": 2, "fx": 1})), AGG)
    # equities +2 적중(+2), fx +1 이지만 DXY −1.5 → 미스(−1) → (2−1)/3
    assert strong["weighted"] == pytest.approx(1 / 3)


def test_score_treats_small_moves_as_unjudged():
    rows = _rows(("2026-08-14", {"ai_infra": 1}))     # 실현 −0.3%p, 임계 0.5 미만
    r = score(rows, AGG)
    assert r["assets"]["ai_infra"]["verdict"] == "무판정"
    assert r["judged"] == 0


def test_score_uses_a_bp_threshold_for_bonds():
    agg = {**AGG, "yields": {"10Y": {"chg_bp": -2.0}}}   # 2bp < 3bp 임계
    r = score(_rows(("2026-08-14", {"bonds": 1})), agg)
    assert r["assets"]["bonds"]["verdict"] == "무판정"


def test_score_excludes_neutral_from_the_denominator_but_reports_it():
    rows = _rows(("2026-08-14", {"equities": 2, "bonds": 0, "fx": 0}))
    r = score(rows, AGG)
    assert r["weighted"] == pytest.approx(1.0)      # 중립 둘은 분모 밖
    assert r["neutral"] == 2
    assert r["neutral_share"] == pytest.approx(2 / 3)


def test_score_is_none_when_nothing_was_judged():
    r = score(_rows(("2026-08-14", {"bonds": 0})), AGG)
    assert r["weighted"] is None
    assert r["note"] == "판정 가능한 포지션 없음"


def test_regime_check_agrees_when_most_new_prints_match():
    macro = [{"report_date": "2026-08-21", "regime": {"growth": -1, "inflation": 0}}]
    metrics = {"indicators": [
        {"key": "PAYEMS", "axis": "labor", "direction": "악화", "released": "2026-08-19"},
        {"key": "ICSA", "axis": "labor", "direction": "악화", "released": "2026-08-20"},
        {"key": "RSAFS", "axis": "consumption", "direction": "개선", "released": "2026-08-20"}]}
    r = regime_check(macro, metrics, "2026-08-17", "2026-08-21")
    assert r["verdict"] == "정합"
    assert r["prints"] == 3


def test_regime_check_is_undecidable_without_new_prints():
    macro = [{"report_date": "2026-08-21", "regime": {"growth": 0, "inflation": 0}}]
    r = regime_check(macro, {"indicators": []}, "2026-08-17", "2026-08-21")
    assert r["verdict"] == "판정불가"


def test_trigger_hygiene_flags_long_dormant_conditions():
    rows = [{"report_date": f"2026-07-{d:02d}",
             "assets": {"equities": {"grade": 0, "triggers": {
                 "increase": [{"metric": "spx_vs_50dma_pct", "op": ">", "value": 4.0}],
                 "decrease": []}}}}
            for d in range(1, 29)]
    r = trigger_hygiene(rows, "2026-07-28", stale_days=20)
    assert any(t["metric"] == "spx_vs_50dma_pct" for t in r["dormant"])


def test_rollup_averages_recent_periods():
    hist = [{"key": f"2026-W{w}", "weighted": w / 10, "judged": 2} for w in (30, 31, 32, 33, 34)]
    r = rollup(hist, spans=(4,))
    assert r["last_4"]["periods"] == 4
    assert r["last_4"]["weighted"] == pytest.approx((3.1 + 3.2 + 3.3 + 3.4) / 4)
    assert r["all"]["periods"] == 5


def test_rollup_marks_thin_samples():
    r = rollup([{"key": "2026-W34", "weighted": 0.5, "judged": 2}], spans=(4, 12))
    assert r["last_4"]["insufficient"] is True
    assert r["last_12"]["insufficient"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_scorecard.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.scorecard'`

- [ ] **Step 3: Write minimal implementation**

`scripts/us/scorecard.py`:

```python
"""복기 스코어카드 — 스탠스 등급 부호를 실현치로 채점한다.

등급이 곧 방향 베팅이다. 메모리·AI 인프라는 «주식 대비 상대비중»이므로 절대수익이 아니라
초과수익으로 채점한다 — 절대수익으로 재면 그 판단이 아니라 시장 방향을 채점하게 된다.

여기서 나온 숫자는 작성 에이전트가 만지지 않는다 (macro_metrics 의 z 와 같은 규율).
"""

ASSET_KEYS = ('equities', 'bonds', 'fx', 'energy', 'metals', 'memory', 'ai_infra')
PCT_THRESHOLD = 0.5      # 이보다 작은 움직임은 잡음 — 점수를 주지 않는다
BP_THRESHOLD = 3.0


def realized(agg):
    """자산군 → 등급 부호와 같은 방향으로 정렬된 실현치."""
    def g(d, *path):
        cur = d
        for p in path:
            cur = (cur or {}).get(p)
        return cur

    tenner = g(agg, 'yields', '10Y', 'chg_bp')
    return {
        'equities': g(agg, 'indices', 'S&P 500', 'pct'),
        # 롱 듀레이션(+) = 금리 하락 베팅이므로 부호를 뒤집는다
        'bonds': (-tenner) if tenner is not None else None,
        'fx': g(agg, 'fx', 'DXY', 'pct'),
        'energy': g(agg, 'commodities', 'WTI', 'pct'),
        'metals': g(agg, 'commodities', 'Gold', 'pct'),
        'memory': g(agg, 'memory', 'basket_excess_pct'),
        'ai_infra': g(agg, 'ai_infra', 'basket_excess_pct'),
    }


def _grade_at(rows, key, when):
    """`when` 시점에 유효했던 등급 — 그 날짜 이하의 마지막 기록."""
    prior = [r for r in rows if (r.get('report_date') or '') <= when]
    if not prior:
        return None
    a = (prior[-1].get('assets') or {}).get(key) or {}
    return a.get('grade')


def segments(stance_rows, start, end):
    """자산군별 [{grade, from, to}] — 기간 중 등급이 바뀌면 쪼갠다."""
    rows = sorted(stance_rows, key=lambda r: r.get('report_date') or '')
    out = {}
    for key in ASSET_KEYS:
        opening = _grade_at(rows, key, start)
        if opening is None:
            continue
        segs, cur, since = [], opening, start
        for r in rows:
            d = r.get('report_date') or ''
            if not (start < d <= end):
                continue
            g = ((r.get('assets') or {}).get(key) or {}).get('grade')
            if g is not None and g != cur:
                segs.append({'grade': cur, 'from': since, 'to': d})
                cur, since = g, d
        segs.append({'grade': cur, 'from': since, 'to': end})
        out[key] = segs
    return out


def _threshold(key):
    return BP_THRESHOLD if key == 'bonds' else PCT_THRESHOLD


def score(stance_rows, agg):
    real = realized(agg)
    segs = segments(stance_rows, agg.get('start_date'), agg.get('end_date'))
    assets, num, den, judged, neutral, total = {}, 0.0, 0.0, 0, 0, 0

    for key in ASSET_KEYS:
        if key not in segs:
            continue
        total += 1
        r = real.get(key)
        # 구간별 실현치를 따로 재려면 일별 계열이 필요하다. 기간 집계만 있는 지금은
        # 기간 실현치를 모든 구간에 공통으로 적용하고, 가중치만 |등급| 로 나눈다.
        units = []
        for s in segs[key]:
            gr = s['grade']
            if gr == 0:
                continue
            if r is None or abs(r) < _threshold(key):
                units.append({'grade': gr, 'verdict': '무판정', 'weight': 0.0})
                continue
            hit = (r > 0) == (gr > 0)
            units.append({'grade': gr, 'verdict': '적중' if hit else '미스',
                          'weight': float(abs(gr)), 'signed': (1 if hit else -1) * abs(gr)})
        if not units:
            neutral += 1
            assets[key] = {'grade': 0, 'realized': r, 'verdict': '중립', 'segments': segs[key]}
            continue
        w = sum(u['weight'] for u in units)
        if w == 0:
            assets[key] = {'grade': units[0]['grade'], 'realized': r,
                           'verdict': '무판정', 'segments': segs[key]}
            continue
        signed = sum(u.get('signed', 0) for u in units)
        judged += 1
        num += signed
        den += w
        assets[key] = {'grade': units[-1]['grade'], 'realized': r,
                       'verdict': '적중' if signed > 0 else '미스',
                       'score': round(signed / w, 4), 'segments': segs[key]}

    out = {'start_date': agg.get('start_date'), 'end_date': agg.get('end_date'),
           'key': agg.get('key'), 'assets': assets, 'judged': judged,
           'neutral': neutral, 'total': total,
           'neutral_share': round(neutral / total, 4) if total else None,
           'weighted': round(num / den, 4) if den else None}
    if not den:
        out['note'] = '판정 가능한 포지션 없음'
    return out


_AXIS_SIGN = {'개선': 1, '악화': -1, '보합': 0}


def regime_check(macro_rows, macro_metrics, start, end):
    prints = [i for i in ((macro_metrics or {}).get('indicators') or [])
              if start <= (i.get('released') or '') <= end]
    rows = sorted(macro_rows or [], key=lambda r: r.get('report_date') or '')
    regime = (rows[-1].get('regime') if rows else None) or {}
    if not prints:
        return {'verdict': '판정불가', 'prints': 0, 'regime': regime,
                'note': '기간 중 신규 발표 없음'}
    growth = regime.get('growth') or 0
    agree = 0
    for i in prints:
        s = _AXIS_SIGN.get(i.get('direction'), 0)
        if s == 0:
            continue
        # 성장축이 마이너스면 악화 프린트가 정합, 플러스면 개선이 정합, 0이면 상쇄가 정합
        if growth == 0 or (s > 0) == (growth > 0):
            agree += 1
    ratio = agree / len(prints)
    verdict = '정합' if ratio >= 0.5 else '불일치'
    return {'verdict': verdict, 'prints': len(prints), 'agree': agree,
            'ratio': round(ratio, 4), 'regime': regime}


def trigger_hygiene(stance_rows, end, stale_days=20):
    """발동한 트리거와, 오래 잠들어 있는(=임계가 너무 빡빡한) 조건."""
    rows = sorted(stance_rows or [], key=lambda r: r.get('report_date') or '')
    recent = [r for r in rows if (r.get('report_date') or '') <= end]
    dormant, seen = [], {}
    for r in recent:
        for key, a in (r.get('assets') or {}).items():
            for direction in ('increase', 'decrease'):
                for t in ((a.get('triggers') or {}).get(direction) or []):
                    sig = (key, direction, t.get('metric'), t.get('op'), t.get('value'))
                    seen.setdefault(sig, 0)
                    seen[sig] += 1
    for (key, direction, metric, op, value), days in seen.items():
        if days >= stale_days:
            dormant.append({'asset': key, 'direction': direction, 'metric': metric,
                            'op': op, 'value': value, 'days': days})
    dormant.sort(key=lambda x: -x['days'])
    return {'dormant': dormant, 'stale_days': stale_days}


def rollup(history_rows, spans=(4, 12)):
    rows = [r for r in (history_rows or []) if r.get('weighted') is not None]
    rows.sort(key=lambda r: r.get('key') or '')
    out = {}
    for n in spans:
        tail = rows[-n:]
        out[f'last_{n}'] = {
            'periods': len(tail),
            'weighted': round(sum(r['weighted'] for r in tail) / len(tail), 4) if tail else None,
            'insufficient': len(tail) < n,
        }
    out['all'] = {'periods': len(rows),
                  'weighted': round(sum(r['weighted'] for r in rows) / len(rows), 4)
                  if rows else None,
                  'insufficient': len(rows) < 2}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_scorecard.py -q`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/scorecard.py scripts/us/tests/test_scorecard.py
git commit -m "복기 스코어카드 — 스탠스 등급 부호를 가중 적중률로 채점"
```

---

### Task 9: 발행 게이트

**Files:**
- Create: `scripts/us/period_gate.py`
- Create: `scripts/check_period.py`
- Test: `scripts/us/tests/test_period_gate.py`

**Interfaces:**
- Consumes: `us.post_check.data_tokens`, `us.macro_gate.BANNED_LABELS`
- Produces: `check(html: str, agg: dict, scorecard: dict | None, span: str, kind: str = 'report', sources: list[str] | None = None) -> list[str]` — 위반 문자열 목록, 빈 목록이면 발행 가능

- [ ] **Step 1: Write the failing test**

`scripts/us/tests/test_period_gate.py`:

```python
from us.period_gate import check

AGG = {"span": "weekly", "key": "2026-W34", "start_date": "2026-08-17",
       "end_date": "2026-08-21", "sessions": 5,
       "indices": {"S&P 500": {"pct": 2.0}},
       "sectors": {"Technology": {"pct": 20.0, "rank": 1}},
       "yields": {"10Y": {"chg_bp": -12.0}}}

SC = {"weighted": 0.33, "judged": 3, "neutral": 2, "neutral_share": 0.4,
      "assets": {"equities": {"verdict": "적중"}}}


def _html(body):
    return f"<html><body><main>{body}</main></body></html>"


GOOD = _html(
    "<p>2026-08-17부터 2026-08-21까지 5거래일. S&amp;P 500은 2.0% 올랐고 "
    "Technology가 20.0%로 1위였다. 10년물은 12.0bp 내렸다. "
    "가중 점수는 0.33, 무포지션 비율 0.4다.</p>")


def test_clean_report_passes():
    assert check(GOOD, AGG, SC, "weekly") == []


def test_invented_number_is_caught():
    html = GOOD.replace("2.0%", "2.7%")
    v = check(html, AGG, SC, "weekly")
    assert any("2.7" in x for x in v)


def test_scorecard_number_must_match_the_file():
    html = GOOD.replace("0.33", "0.51")
    v = check(html, AGG, SC, "weekly")
    assert any("0.51" in x for x in v)


def test_unconfirmed_marker_is_banned():
    v = check(_html("<p>[확인필요] 수치</p>"), AGG, SC, "weekly")
    assert any("확인필요" in x for x in v)


def test_buyside_wording_is_banned():
    v = check(GOOD + "<p>buy-side 관점</p>", AGG, SC, "weekly")
    assert any("buy-side" in x for x in v)


def test_internal_filenames_must_not_leak():
    v = check(GOOD + "<p>weekly.json 참조</p>", AGG, SC, "weekly")
    assert any("weekly.json" in x for x in v)


def test_internal_ledger_key_must_not_leak():
    v = check(GOOD + "<p>_sessions 원장</p>", AGG, SC, "weekly")
    assert any("_sessions" in x for x in v)


def test_coverage_window_must_be_stated():
    v = check(_html("<p>S&amp;P 500은 2.0% 올랐다.</p>"), AGG, SC, "weekly")
    assert any("커버 기간" in x for x in v)


def test_comment_may_only_cite_numbers_from_the_two_recaps():
    sources = ["<p>S&amp;P 500은 2.0% 올랐다.</p>", "<p>코스피는 1.5% 내렸다.</p>"]
    ok = _html("<p>2026-08-17~2026-08-21 주. S&amp;P 500 2.0%와 코스피 1.5%가 갈렸다.</p>")
    assert check(ok, AGG, None, "weekly", kind="comment", sources=sources) == []
    bad = _html("<p>2026-08-17~2026-08-21 주. 나스닥은 9.9% 올랐다.</p>")
    v = check(bad, AGG, None, "weekly", kind="comment", sources=sources)
    assert any("9.9" in x for x in v)


def test_thin_sample_must_be_disclosed_when_rollup_is_insufficient():
    sc = {**SC, "rollup": {"last_4": {"insufficient": True, "periods": 1}}}
    v = check(GOOD, AGG, sc, "weekly")
    assert any("표본 부족" in x for x in v)
    ok = GOOD.replace("</p>", " 누적 표본 부족으로 당기만 싣는다.</p>")
    assert check(ok, AGG, sc, "weekly") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_period_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.period_gate'`

- [ ] **Step 3: Write minimal implementation**

`scripts/us/period_gate.py`:

```python
"""주간·월간 정리와 주간 코멘트의 발행 게이트.

핵심은 하나 — **발행본의 숫자는 집계 파일에 실재해야 한다.** 순위처럼 파생되는 값도
집계가 미리 계산해 담아 두므로, 에이전트가 즉석에서 산술한 수치는 통과하지 못한다.
"""

import re

from us.macro_gate import BANNED_LABELS
from us.post_check import banned_markers, body_text, data_tokens

INTERNAL_TERMS = ('weekly.json', 'monthly.json', 'scorecard.json', 'stance.jsonl',
                  'macro.jsonl', 'market_data.json', 'research_notes.md',
                  'macro_metrics.json', 'kr_flows.json', '_sessions',
                  'signed-z', 'allowed_grades', 'basket_excess_pct')

_NUM = re.compile(r'-?\d+(?:\.\d+)?')


def _numbers(obj, out=None):
    """중첩 구조 안의 모든 수치를 문자열 집합으로 — 표기 흔들림을 흡수한다."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _numbers(k, out)
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.add(_canon(obj))
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):
            out.add(_canon(m))
    return out


def _canon(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return f'{f:.10g}'


def _html_numbers(html):
    # data_tokens 는 {토큰: 등장횟수} 딕트다 — 여기서는 키(토큰)만 쓴다
    out = set()
    for tok in data_tokens(html):
        for m in _NUM.findall(tok.replace(',', '')):
            out.add(_canon(m))
    return out


def check(html, agg, scorecard, span, kind='report', sources=None):
    v = []
    text = body_text(html)

    for marker in banned_markers(html):
        v.append(f'발행본에 미확인 마커가 남았다: {marker} — 확인해 확정하거나 삭제할 것')

    low = text.lower()
    for word in BANNED_LABELS:
        if word in low:
            v.append(f'발행본에 buy-side 표기("{word}")가 남았다 — '
                     '전략·리포트·시황 정리로 부를 것')
            break

    for term in INTERNAL_TERMS:
        if term in text:
            v.append(f'내부 용어·파일명이 발행본에 노출됐다: {term}')

    # 커버 기간 — 시작·종료 거래일이 본문에 있어야 한다
    start, end = agg.get('start_date'), agg.get('end_date')
    if not (start and start in text) or not (end and end in text):
        v.append(f'커버 기간이 본문에 없다 — 시작({start})과 종료({end}) 거래일을 명시할 것')

    # 수치 대조
    allowed = _numbers(agg)
    if kind == 'comment':
        for s in (sources or []):
            allowed |= _html_numbers(s)
    else:
        allowed |= _numbers(scorecard or {})
    allowed |= _numbers({'y': [str(y) for y in range(2020, 2036)]})   # 연도는 통과

    for n in sorted(_html_numbers(html) - allowed):
        try:
            f = abs(float(n))
        except ValueError:
            continue
        if f <= 12 and f == int(f):
            continue            # 섹션 번호·순위·거래일 수 같은 작은 정수는 통과
        v.append(f'집계에 없는 수치가 본문에 있다: {n} — 창작 금지, 집계 파일 값만 인용할 것')

    ru = (scorecard or {}).get('rollup') or {}
    if any((ru.get(k) or {}).get('insufficient') for k in ru):
        if '표본 부족' not in text:
            v.append('누적 구간의 표본이 부족한데 본문이 그 사실을 밝히지 않았다 — '
                     '「누적 표본 부족」을 명시하고 당기만 실을 것')
    return v
```

`scripts/check_period.py`:

```python
#!/usr/bin/env python3
"""Publication gate for the weekly / monthly recaps and the weekly comment.

  python3 scripts/check_period.py --html weekly_2026-W34.html \
      --agg data/weekly/2026-W34.json --scorecard data/scorecard.json --span weekly

  python3 scripts/check_period.py --html comment_2026-08-22.html \
      --agg data/weekly/2026-W34.json --span weekly --kind comment \
      --source weekly_2026-W34.html --source kr_weekly_2026-W34.html

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to the
writer subagent verbatim and re-run.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.period_gate import check  # noqa: E402


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--agg', required=True)
    ap.add_argument('--scorecard', default=None)
    ap.add_argument('--span', choices=('weekly', 'monthly'), required=True)
    ap.add_argument('--kind', choices=('report', 'comment'), default='report')
    ap.add_argument('--source', action='append', default=[],
                    help='코멘트 검사용 — 그 주 정리 발행본 HTML (여러 번 지정)')
    args = ap.parse_args()

    try:
        html = read(args.html)
        agg = json.loads(read(args.agg))
    except OSError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        sys.exit(2)

    sc = None
    if args.scorecard and os.path.exists(args.scorecard):
        sc = json.loads(read(args.scorecard))
    sources = [read(p) for p in args.source if os.path.exists(p)]

    violations = check(html, agg, sc, args.span, kind=args.kind, sources=sources)
    if not violations:
        print('기간 리포트 게이트 통과')
        return
    print(f'기간 리포트 게이트 실패 — {len(violations)}건')
    for x in violations:
        print(f'  - {x}')
    sys.exit(1)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_period_gate.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: 전체 테스트가 여전히 통과하는지**

Run: `python3 -m pytest scripts -q`
Expected: 기존 테스트 전부 + 신규 통과

- [ ] **Step 6: Commit**

```bash
git add scripts/us/period_gate.py scripts/check_period.py scripts/us/tests/test_period_gate.py
git commit -m "기간 리포트 발행 게이트 — 집계에 없는 수치를 막는다"
```

---

### Task 10: 아카이브·sitemap 갱신

**Files:**
- Create: `scripts/update_archives.py`
- Create: `scripts/us/archives.py`
- Test: `scripts/us/tests/test_archives.py`
- Modify: `index.html`, `kr/index.html` (종류 필터)

**Interfaces:**
- Consumes: 없음
- Produces: `upsert_entry(entries: list[dict], entry: dict, key: str = 'key') -> list[dict]`, `sitemap_urls(base: str, listings: dict) -> list[str]`

- [ ] **Step 1: Write the failing test**

`scripts/us/tests/test_archives.py`:

```python
from us.archives import sitemap_urls, upsert_entry


def test_upsert_adds_a_new_entry_newest_first():
    e = upsert_entry([], {"key": "2026-W34", "title": "t", "headline": "h"})
    e = upsert_entry(e, {"key": "2026-W35", "title": "u", "headline": "i"})
    assert [x["key"] for x in e] == ["2026-W35", "2026-W34"]


def test_upsert_replaces_rather_than_duplicating():
    e = upsert_entry([], {"key": "2026-W34", "title": "old"})
    e = upsert_entry(e, {"key": "2026-W34", "title": "new"})
    assert len(e) == 1
    assert e[0]["title"] == "new"


def test_sitemap_lists_every_kind():
    urls = sitemap_urls("https://fdo2a.github.io", {
        "posts": ["2026-08-21"], "weekly": ["2026-W34"],
        "monthly": ["2026-08"], "comment": ["2026-08-22"],
        "kr/posts": ["2026-08-21"], "kr/weekly": ["2026-W34"], "kr/monthly": ["2026-08"]})
    assert "https://fdo2a.github.io/weekly/2026-W34.html" in urls
    assert "https://fdo2a.github.io/kr/monthly/2026-08.html" in urls
    assert "https://fdo2a.github.io/comment/2026-08-22.html" in urls


def test_sitemap_has_no_duplicates_and_is_sorted():
    urls = sitemap_urls("https://x", {"weekly": ["2026-W34", "2026-W34", "2026-W33"]})
    assert urls == sorted(set(urls))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_archives.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.archives'`

- [ ] **Step 3: Write minimal implementation**

`scripts/us/archives.py`:

```python
"""목록 JSON·sitemap 갱신 — 재실행이 중복을 만들지 않게 기간 키로 upsert 한다."""


def upsert_entry(entries, entry, key='key'):
    out = [e for e in (entries or []) if e.get(key) != entry.get(key)]
    out.append(entry)
    out.sort(key=lambda e: e.get(key) or '', reverse=True)
    return out


def sitemap_urls(base, listings):
    base = base.rstrip('/')
    urls = {f'{base}/'}
    for path, keys in (listings or {}).items():
        for k in keys:
            urls.add(f'{base}/{path}/{k}.html')
    return sorted(urls)
```

`scripts/update_archives.py`:

```python
#!/usr/bin/env python3
"""발행 후 목록 JSON 과 sitemap 을 갱신한다.

  python3 scripts/update_archives.py --root . \
      --kind weekly --key 2026-W34 \
      --title "미국 증시 주간 정리 — 2026년 8월 3주" --headline "..."

--kind 는 weekly / monthly / comment / kr-weekly / kr-monthly.
같은 키로 다시 돌리면 항목을 교체한다 (중복 생성 아님).
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.archives import sitemap_urls, upsert_entry  # noqa: E402

LISTINGS = {'weekly': ('weekly.json', 'weekly'),
            'monthly': ('monthly.json', 'monthly'),
            'comment': ('comment.json', 'comment'),
            'kr-weekly': ('kr/weekly.json', 'kr/weekly'),
            'kr-monthly': ('kr/monthly.json', 'kr/monthly')}
BASE = 'https://fdo2a.github.io'


def load(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--kind', choices=sorted(LISTINGS), required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--headline', default='')
    args = ap.parse_args()

    listing_rel, dir_rel = LISTINGS[args.kind]
    listing = os.path.join(args.root, listing_rel)
    entries = upsert_entry(load(listing, []),
                           {'key': args.key, 'title': args.title,
                            'headline': args.headline})
    os.makedirs(os.path.dirname(listing) or '.', exist_ok=True)
    json.dump(entries, open(listing, 'w'), ensure_ascii=False, indent=2)
    print(f'{listing_rel}: {len(entries)} entries')

    # sitemap — 디스크에 실재하는 파일만 싣는다
    listings = {}
    for path in ('posts', 'weekly', 'monthly', 'comment',
                 'kr/posts', 'kr/weekly', 'kr/monthly'):
        d = os.path.join(args.root, path)
        listings[path] = sorted(os.path.splitext(os.path.basename(p))[0]
                                for p in glob.glob(os.path.join(d, '*.html')))
    urls = sitemap_urls(BASE, listings)
    with open(os.path.join(args.root, 'sitemap.xml'), 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in urls:
            fh.write(f'  <url><loc>{u}</loc></url>\n')
        fh.write('</urlset>\n')
    print(f'sitemap.xml: {len(urls)} urls')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_archives.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 기존 sitemap 형식과 충돌하지 않는지 확인**

```bash
head -6 sitemap.xml
python3 scripts/update_archives.py --root . --kind weekly --key 2026-W00 \
    --title "probe" --headline "probe"
head -6 sitemap.xml && git diff --stat sitemap.xml
```

기존 sitemap에 `<lastmod>`·`<changefreq>` 같은 필드가 있으면 위 writer를 그 형식에 맞춘다. 확인 후 프로브 항목을 되돌린다:

```bash
git checkout sitemap.xml weekly.json 2>/dev/null || rm -f weekly.json
```

- [ ] **Step 6: index.html 에 종류 필터 추가**

`index.html`은 `posts.json`만 읽는다. 필터 칩 4개(일간·주간·월간·코멘트)를 붙이고 각 목록 JSON을 불러 합친 뒤 종류로 거른다. `kr/index.html`은 일간·주간·월간 3개.

기존 카드 마크업(`a.post` / `.post .date`)과 CSS 변수를 그대로 쓰고, 칩은 `.switch` 스타일을 재사용한다. 반응형 규격(390/1280px에서 가로 밀림 없음)을 지킨다.

- [ ] **Step 7: 반응형 검증**

```bash
python3 - <<'PY'
from playwright.sync_api import sync_playwright
import pathlib
url = pathlib.Path('index.html').resolve().as_uri()
with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (390, 1280):
        pg = b.new_page(viewport={'width': w, 'height': 900})
        pg.goto(url); pg.wait_for_timeout(300)
        sw = pg.evaluate('document.documentElement.scrollWidth')
        print(w, sw, 'OK' if sw == w else 'OVERFLOW')
    b.close()
PY
```

Expected: 두 폭 모두 `OK`

- [ ] **Step 8: Commit**

```bash
git add scripts/update_archives.py scripts/us/archives.py \
        scripts/us/tests/test_archives.py index.html kr/index.html
git commit -m "아카이브에 주간·월간·코멘트 종류를 세운다"
```

---

### Task 11: 작성 에이전트·오케스트레이터·트리거

**Files:**
- Create: `.claude/agents/period-report-writer.md`
- Create: `.claude/agents/weekly-comment-writer.md`
- Create: `.claude/WEEKLY_ORCHESTRATOR.md`
- Create: `.claude/MONTHLY_ORCHESTRATOR.md`
- Modify: `CLAUDE.md` (구성 요소에 기간 리포트 추가)

**Interfaces:**
- Consumes: Task 4·6의 집계 파일, Task 8의 `data/scorecard.json`, Task 9의 게이트 CLI, Task 10의 아카이브 CLI
- Produces: 루틴이 실행하는 파이프라인 문서

- [ ] **Step 1: `period-report-writer.md` 작성**

`market`(us|kr)와 `span`(weekly|monthly) 두 파라미터로 4종을 처리한다. 담아야 할 것:

- 입력 계약 — `data/weekly/<key>.json` 또는 `data/monthly/<key>.json`, `data/scorecard.json`, `data/history/*.jsonl` (KR은 `kr/data/...`, 스코어카드 없음)
- 출력 계약 — `weekly_<key>.html` / `monthly_<key>.html` (KR은 `kr_` 접두)
- **섹션 구조** — 스펙 §리포트 구조를 그대로 옮긴다. US 주간 5절, KR 주간 7절, 월간은 +3절(섹터 로테이션·레짐 궤적·스탠스 등급 궤적)
- **금기** — 수치를 새로 계산하지 않는다. 집계 파일에 있는 값만 인용한다. 웹 재리서치 금지(그 기간의 촉매는 `daily[]`가 이미 확정했다)
- **복기 서술 규율** — 틀린 것부터 쓴다. 맞은 것 나열 금지. 틀렸을 때 «트리거는 옳았는데 시장이 따라오지 않았나» 와 «트리거 설계가 틀렸나»를 구분한다
- **표본 부족** — `scorecard.rollup`의 `insufficient`가 참이면 「누적 표본 부족」을 명시하고 당기만 싣는다
- 디자인·반응형 규격은 `.claude/agents/brief-report-writer.md`를 참조하라고 지시 (중복 기술하지 않는다)

- [ ] **Step 2: `weekly-comment-writer.md` 작성**

- 입력 — 그 주 US·KR 주간 정리 **발행본 HTML 두 편**
- 출력 — `comment_<YYYY-MM-DD>.html` (발행일 기준)
- **표 없음.** 두 시장을 관통하는 주제 1~2개. 1,200~2,000자
- **근거 수치는 두 발행본에서 인용만.** 새로 계산하지 않는다 — 게이트가 부분집합으로 검사한다

- [ ] **Step 3: `WEEKLY_ORCHESTRATOR.md` 작성**

```
STEP 0  레포 클론, 최신 report_date 확인 → week_key 산출
STEP 1  data/weekly/<key>.json, kr/data/weekly/<key>.json 존재·complete 확인
        없거나 incomplete 면 PushNotification 후 중단 (완성본만 발행)
STEP 2  scorecard 계산 → data/scorecard.json, data/history/scorecard.jsonl append
STEP 3  period-report-writer (market=us, span=weekly) → 게이트 → /weekly/<key>.html 발행
STEP 4  period-report-writer (market=kr, span=weekly) → 게이트 → /kr/weekly/<key>.html 발행
STEP 5  weekly-comment-writer (입력: STEP 3·4 발행본) → 게이트(kind=comment) → /comment/<date>.html
STEP 6  update_archives.py 3회 → commit → push
STEP 7  PushNotification
```

각 STEP에 게이트 CLI 호출을 실제 명령으로 적는다. 게이트 실패 시 위반 목록을 writer에게 **그대로** 돌려주고 재작성시킨다(기존 관례).

- [ ] **Step 4: `MONTHLY_ORCHESTRATOR.md` 작성**

```
STEP 0  최신 report_date 의 달이 M+1 인지 확인.
        data/monthly/<M>.json 이 있고 posts 에 /monthly/<M>.html 이 없을 때만 진행.
        아니면 "월 롤오버 아님 — 종료" 를 남기고 즉시 끝낸다 (토큰 낭비 금지)
STEP 1~6  주간과 동일, span=monthly, 코멘트 없음, 누적 구간은 3개월·12개월
```

- [ ] **Step 5: 스코어카드 산출 스크립트 확인**

오케스트레이터 STEP 2가 부를 CLI가 필요하다. `scripts/us/scorecard.py`에 `__main__` 블록을 붙이거나 `scripts/build_scorecard.py`를 만든다:

```python
#!/usr/bin/env python3
"""python3 scripts/build_scorecard.py --agg data/weekly/2026-W34.json --datadir data"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from us.history import append_jsonl, read_jsonl  # noqa: E402
from us.scorecard import regime_check, rollup, score, trigger_hygiene  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--agg', required=True)
ap.add_argument('--datadir', default='data')
ap.add_argument('--spans', default='4,12')
a = ap.parse_args()

agg = json.load(open(a.agg, encoding='utf-8'))
h = os.path.join(a.datadir, 'history')
stance = read_jsonl(os.path.join(h, 'stance.jsonl'))
macro = read_jsonl(os.path.join(h, 'macro.jsonl'))
mm_path = os.path.join(a.datadir, 'macro_metrics.json')
mm = json.load(open(mm_path, encoding='utf-8')) if os.path.exists(mm_path) else {}

sc = score(stance, agg)
sc['regime'] = regime_check(macro, mm, agg['start_date'], agg['end_date'])
sc['triggers'] = trigger_hygiene(stance, agg['end_date'])
hist_path = os.path.join(h, 'scorecard.jsonl')
prior = read_jsonl(hist_path)
spans = tuple(int(x) for x in a.spans.split(','))
sc['rollup'] = rollup(prior + [{'key': agg['key'], 'weighted': sc['weighted'],
                                'judged': sc['judged']}], spans=spans)
json.dump(sc, open(os.path.join(a.datadir, 'scorecard.json'), 'w'),
          ensure_ascii=False, indent=2, default=str)
append_jsonl(hist_path, {'report_date': agg['end_date'], 'key': agg['key'],
                         'weighted': sc['weighted'], 'judged': sc['judged'],
                         'neutral_share': sc['neutral_share']})
print(f"scorecard {agg['key']}: weighted={sc['weighted']} judged={sc['judged']}")
```

**주의:** 월간은 `--spans 3,12`로 부른다 (스펙: 주간 4·12, 월간 3개월·12개월). 월간 스코어카드는 주간 행을 롤업하므로 `scorecard.jsonl`에 **월간 행을 새로 쌓지 않는다** — 월간 실행 시 `append_jsonl` 호출을 건너뛰도록 `--no-append` 플래그를 붙인다.

```bash
python3 scripts/build_scorecard.py --agg data/weekly/$(python3 -c "
import json,sys; sys.path.insert(0,'scripts')
from us.period import week_key; print(week_key(json.load(open('data/market_data.json'))['report_date']))").json
cat data/scorecard.json | head -30
```

- [ ] **Step 6: CLAUDE.md 갱신**

「구성 요소」 아래에 기간 리포트 항목을 추가한다 — 발행물 5종, 트리거 2개, 기간 키 파일 구조, 스코어카드 규율, 게이트 CLI. 기존 항목들의 밀도와 톤에 맞춘다.

- [ ] **Step 7: Commit & push**

```bash
git add .claude CLAUDE.md scripts/build_scorecard.py
git commit -m "주간·월간 파이프라인 — 에이전트 정의와 오케스트레이터"
git pull --rebase && git push
```

- [ ] **Step 8: 트리거 2개 등록**

`RemoteTrigger` 도구로 등록한다. 부트스트랩은 짧게, 파이프라인은 레포 파일을 읽게 한다(기존 규칙 — 도구 입력 ~7KB 제한, 한글은 `\uXXXX`로 팽창).

| 트리거 | cron (UTC) | 부트스트랩 |
|---|---|---|
| `weekly` | `0 0 * * 6` | 레포 클론 후 `.claude/WEEKLY_ORCHESTRATOR.md` 실행 |
| `monthly` | `30 0 1,2,28,29,30,31 * *` | 레포 클론 후 `.claude/MONTHLY_ORCHESTRATOR.md` 실행 |

등록 후 `CronList`(또는 RemoteTrigger 조회)로 두 트리거가 보이는지 확인하고, 트리거 ID를 CLAUDE.md에 적는다.

- [ ] **Step 9: 첫 회차 드라이런**

주간 트리거를 수동 실행해 3편이 나오는지 본다. **첫 회차는 누적 4주·12주가 비어 있으므로** 게이트가 「누적 표본 부족」 명시를 요구한다 — 그게 정상 동작이다.

---

## 자체 검토

**스펙 커버리지**

| 스펙 항목 | 태스크 |
|---|---|
| 발행물 매트릭스 5종·경로 | 10, 11 |
| 기간 경계·기간 키 파일 | 4, 6 |
| 집계 스키마 (US/KR) | 4, 6 |
| `basket_excess_pct` | 4 |
| KR 수급 확정치만 | 6 |
| 승계 로그 + 백필 | 1, 2, 3 |
| 스코어카드 부호·임계·중립·가중 | 8 |
| 레짐 채점·트리거 위생 | 8 |
| 누적 4주·12주 / 3개월·12개월 | 8, 11 |
| 리포트 구조 4종 + 코멘트 | 11 |
| 실행 구조 트리거 2개 | 11 |
| 발행 게이트 8항목 | 9 |
| 아카이브·SEO | 10 |
| 마이그레이션·표본 부족 표기 | 2, 9, 11 |

**미해결로 남긴 것 하나** — Task 8의 `score()`는 기간 중 등급이 바뀐 구간에도 **기간 전체 실현치**를 공통 적용한다(코드 주석에 명시). 구간별 실현치를 정확히 재려면 일별 종가 계열이 스코어카드까지 흘러야 하는데, 그건 집계 스키마를 키우는 별도 변경이다. 등급 변경은 하루 1단계·3영업일 잠금 규율 때문에 주간 시계에서 드물어 당장은 영향이 작다. 월간에서 문제가 드러나면 그때 `daily_closes`를 집계에 실어 정확히 쪼갠다.

**타입 일관성** — `week_key`/`month_key`는 Task 4에서 정의해 5·7·11에서 재사용, `read_jsonl`/`append_jsonl`은 1에서 정의해 2·3·8·11에서 재사용, `data_tokens`/`body_text`/`banned_markers`는 기존 `us.post_check`에서 가져온다. `finalize`가 쓰는 `_sessions` 키는 6에서 정의하고 9의 `INTERNAL_TERMS`가 막는다.
