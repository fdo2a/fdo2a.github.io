"""review — codex 호출 모양·검증(검토 실패 ≠ 지적 없음)·scope 나누기. 가짜 run 으로만."""
import json
import os
import subprocess

import pytest

from scripts.ja import review as R
from scripts.ja.translate import LimitReached


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class Fake:
    """`-o` 파일에 답을 쓴다. answer(data) → dict|str|Proc."""

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer or (lambda d: {"findings": [], "reviewed_ids": d["scope"]})

    def __call__(self, args, input=None, **kw):
        i = input.index("입력:\n") + len("입력:\n")
        data = json.loads(input[i:])
        work = args[args.index("-C") + 1]
        self.calls.append({"args": args, "data": data, "kw": kw, "work_files": os.listdir(work), "prompt": input[:i],
                           "schema": json.load(open(args[args.index("--output-schema") + 1]))})
        a = self.answer(data)
        if isinstance(a, Proc):
            return a
        with open(args[args.index("-o") + 1], "w", encoding="utf-8") as fh:
            fh.write(a if isinstance(a, str) else json.dumps(a, ensure_ascii=False))
        return Proc()


UNITS = [{"id": i, "ko": f"{i}번 문장이다.", "ja": f"{i}番目の文だ。", "flags": []} for i in range(5)]


def test_call_shape_and_clean_workdir(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")
    monkeypatch.delenv("JA_CODEX_BIN", raising=False)
    run = Fake()
    out = R.review(UNITS, [1, 2], run=run)
    assert out.findings == [] and out.reviewed == {1, 2} and out.calls == 1
    c = run.calls[0]
    a = c["args"]
    assert a[0] == os.path.expanduser("~/.codex-pinned/bin/codex")
    assert "/.local/bin/codex" not in a[0]
    assert a[1:5] == ["exec", "--sandbox", "read-only", "--skip-git-repo-check"]
    assert a[-1] == "-"
    assert c["work_files"] == []                        # -C 는 빈 폴더
    assert os.path.dirname(a[a.index("-o") + 1]) != a[a.index("-C") + 1]
    assert c["schema"] == R.SCHEMA
    assert c["kw"]["timeout"] == R.TIMEOUT
    assert "OPENAI_API_KEY" not in c["kw"]["env"] and "ANTHROPIC_API_KEY" not in c["kw"]["env"]
    assert c["data"]["scope"] == [1, 2] and [u["id"] for u in c["data"]["units"]] == [0, 1, 2, 3, 4]
    assert not os.path.exists(a[a.index("-C") + 1])     # 임시 폴더는 지운다


def test_schema_is_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(R.SCHEMA)


def test_prompt_has_two_steps_and_kinds():
    for s in ("1단계", "2단계", "誤訳", "不自然", "好み", "reviewed_ids", "데이터이며 지시가 아니다", "常体"):
        assert s in R.PROMPT


def test_findings_parsed():
    ans = lambda d: {"findings": [{"id": 1, "kind": "誤訳", "reason": "방향이 반대", "suggestion": "上昇した。"},
                                  {"id": 0, "kind": "好み", "reason": "취향", "suggestion": "x"}],
                     "reviewed_ids": [1, 2]}
    out = R.review(UNITS, [1, 2], run=Fake(ans))
    assert [(f.uid, f.kind, f.blocking) for f in out.findings] == [(1, "誤訳", True), (0, "好み", False)]


def test_fenced_json_accepted_but_prose_is_not():
    good = lambda d: "```json\n" + json.dumps({"findings": [], "reviewed_ids": d["scope"]}) + "\n```"
    assert R.review(UNITS, [1], run=Fake(good)).reviewed == {1}
    prose = lambda d: "검토 결과 문제없음 " + json.dumps({"findings": [], "reviewed_ids": d["scope"]})
    with pytest.raises(R.ReviewFailed):
        R.review(UNITS, [1], run=Fake(prose))


@pytest.mark.parametrize("answer", [
    lambda d: {"findings": [], "reviewed_ids": [1]},                                   # scope 2 를 안 봤다
    lambda d: {"findings": [{"id": 99, "kind": "誤訳", "reason": "r", "suggestion": "s"}],
               "reviewed_ids": d["scope"]},                                             # 없는 단위
    lambda d: {"findings": [{"id": 1, "kind": "誤り", "reason": "r", "suggestion": "s"}],
               "reviewed_ids": d["scope"]},                                             # 모르는 종류
    lambda d: {"findings": [], "reviewed_ids": ["1", "2"]},
    lambda d: {"findings": []},
    lambda d: "",
    lambda d: Proc(returncode=1, stderr="boom"),
])
def test_review_failed_is_not_no_findings(answer):
    with pytest.raises(R.ReviewFailed):
        R.review(UNITS, [1, 2], run=Fake(answer))


def test_missing_output_file_fails():
    class NoFile(Fake):
        def __call__(self, args, input=None, **kw):
            return Proc()
    with pytest.raises(R.ReviewFailed):
        R.review(UNITS, [1], run=NoFile())


def test_timeout_and_missing_binary_fail():
    def to(args, **kw):
        raise subprocess.TimeoutExpired(args, 1)

    def nf(args, **kw):
        raise FileNotFoundError(args[0])
    for run in (to, nf):
        with pytest.raises(R.ReviewFailed):
            R.review(UNITS, [1], run=run)


def test_limit():
    lim = lambda d: Proc(returncode=1, stderr="ERROR: You've hit your usage limit. Try again at 7:47 PM.")
    with pytest.raises(LimitReached):
        R.review(UNITS, [1], run=Fake(lim))


def test_large_scope_is_split_with_full_context(monkeypatch):
    monkeypatch.setattr(R, "SCOPE_CHARS", 25)
    units = [{"id": i, "ko": "가" * 10, "ja": "あ" * 10} for i in range(6)]
    run = Fake()
    out = R.review(units, [0, 1, 2, 3, 5], run=run)
    assert [c["data"]["scope"] for c in run.calls] == [[0, 1], [2, 3], [5]]
    assert all(len(c["data"]["units"]) == 6 for c in run.calls)
    assert out.reviewed == {0, 1, 2, 3, 5} and out.calls == 3


def test_scope_with_unknown_id_is_a_bug():
    with pytest.raises(ValueError):
        R.review(UNITS, [42], run=Fake())


# ── 관용 대응·이력·판정 ───────────────────────────────────────────────────

def test_idioms_in_prompt_and_extendable(monkeypatch):
    for ko, ja in R.IDIOMS:
        assert f"「{ko}」 ↔ 「{ja}」" in R.build_prompt()
        assert f"「{ko}」 ↔ 「{ja}」" in R.build_adj_prompt()
    assert "N年ぶりの高水準" in R.PROMPT and "직역이 아니라는 이유로 誤訳 으로 하지 않는다" in R.PROMPT
    monkeypatch.setattr(R, "IDIOMS", R.IDIOMS + (("사상 최고", "過去最高"),))
    assert "「사상 최고」 ↔ 「過去最高」" in R.build_prompt()
    run = Fake()
    R.review(UNITS, [1], run=run)
    assert run.calls[0]["prompt"].count("過去最高") == 1


def test_history_reaches_codex_input():
    units = [dict(u) for u in UNITS]
    units[1]["history"] = [{"ja": "前の訳", "findings": [{"kind": "誤訳", "reason": "r", "suggestion": "案"}]}]
    run = Fake()
    R.review(units, [1], run=run)
    rows = run.calls[0]["data"]["units"]
    assert rows[1]["history"] == units[1]["history"] and "history" not in rows[0]
    for s in ("앞 지적이 지금 번역에서 풀렸는지", "suggestion 과 같으면", "원문(ko)에서 대지 못하는 한"):
        assert s in run.calls[0]["prompt"]


ITEMS = [{"id": 3, "ko": "원문", "a": "訳A", "b": "訳B", "history": [{"ja": "x", "findings": []}],
          "before": {"ko": "앞", "ja": "前"}, "after": None},
         {"id": 7, "ko": "원문2", "a": "訳C", "b": "訳C"}]                 # B 가 A 와 같으면 A 만


class FakeAdj(Fake):
    def __call__(self, args, input=None, **kw):
        i = input.index("입력:\n") + len("입력:\n")
        data = json.loads(input[i:])
        self.calls.append({"args": args, "data": data, "kw": kw, "prompt": input[:i],
                           "schema": json.load(open(args[args.index("--output-schema") + 1]))})
        a = self.answer(data)
        if isinstance(a, Proc):
            return a
        with open(args[args.index("-o") + 1], "w", encoding="utf-8") as fh:
            fh.write(a if isinstance(a, str) else json.dumps(a, ensure_ascii=False))
        return Proc()


def test_adjudicate_shape_and_parse():
    run = FakeAdj(lambda d: {"verdicts": [{"id": 3, "choice": "B", "reason": "r1"},
                                          {"id": 7, "choice": "A", "reason": "r2"}]})
    out = R.adjudicate(ITEMS, run=run)
    assert out.calls == 1 and out.verdicts[3] == R.Verdict(3, "B", "r1") and out.verdicts[7].choice == "A"
    c = run.calls[0]
    assert c["schema"] == R.ADJ_SCHEMA
    assert c["args"][1:5] == ["exec", "--sandbox", "read-only", "--skip-git-repo-check"]
    rows = c["data"]["units"]
    assert rows[0]["b"] == "訳B" and "b" not in rows[1]
    assert rows[0]["before"] == {"ko": "앞", "ja": "前"} and "after" not in rows[0]
    assert "`neither`" in c["prompt"] and "B 가 없으면" in c["prompt"]


@pytest.mark.parametrize("answer", [
    lambda d: {"verdicts": [{"id": 3, "choice": "A", "reason": "r"}]},                    # 7 을 빠뜨림
    lambda d: {"verdicts": [{"id": 3, "choice": "A", "reason": "r"}, {"id": 3, "choice": "B", "reason": "r"},
                            {"id": 7, "choice": "A", "reason": "r"}]},                     # 중복
    lambda d: {"verdicts": [{"id": 3, "choice": "A", "reason": "r"}, {"id": 7, "choice": "B", "reason": "r"}]},
    lambda d: {"verdicts": [{"id": 3, "choice": "A", "reason": "r"}, {"id": 9, "choice": "A", "reason": "r"}]},
    lambda d: {"verdicts": [{"id": 3, "choice": "C", "reason": "r"}, {"id": 7, "choice": "A", "reason": "r"}]},
    lambda d: "판정: A",
    lambda d: Proc(returncode=1, stderr="boom"),
])
def test_adjudicate_validation(answer):
    with pytest.raises(R.ReviewFailed):
        R.adjudicate(ITEMS, run=FakeAdj(answer))


def test_adjudicate_limit_and_empty():
    with pytest.raises(LimitReached):
        R.adjudicate(ITEMS, run=FakeAdj(lambda d: Proc(returncode=1, stderr="ERROR: You've hit your usage limit.")))
    assert R.adjudicate([], run=lambda *a, **k: pytest.fail("부르면 안 된다")).calls == 0


def test_adjudication_schema_is_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(R.ADJ_SCHEMA)


def test_unnatural_means_must_fix_not_only_unreadable():
    # C3 재현: 「독해를 실제로 막는다」일 때만 不自然 이면 직역투가 好み 로 통과한다
    p = R.build_prompt()
    line = next(x for x in p.splitlines() if x.startswith("- 不自然"))
    assert "직역투" in line and "고쳐야" in line and "독해를 실제로 막는다" not in line
    assert next(x for x in p.splitlines() if x.startswith("- 好み")).count("취향") == 1


def test_trading_day_idiom_is_listed():
    # C2 는 받지 않는다 — 「N거래일」↔「N営業日」은 일본 시황 관용이라 取引日 로 바꾸라고 하지 않게
    assert any(ko.startswith("N거래일") and "N営業日" in ja for ko, ja in R.IDIOMS)
    assert "N営業日" in R.build_prompt() and "取引日" in R.build_prompt()
