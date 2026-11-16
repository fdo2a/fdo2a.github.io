"""translate — `claude -p` 호출 격리·묶음·문맥·응답 검증·한도. 가짜 run 으로만."""
import json
import subprocess

import pytest

from scripts.ja import translate as T


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def ok(items, names=(), usage=None):
    return Proc(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                            "structured_output": {"items": items, "unverified_names": list(names)},
                            "usage": usage or {"input_tokens": 10, "cache_read_input_tokens": 5,
                                               "output_tokens": 7}}))


class Fake:
    """요청한 단위를 「JA:<ko>」로 답한다. `script` 로 회차별 응답을 바꿀 수 있다."""

    def __init__(self, script=None):
        self.calls = []
        self.script = list(script or [])

    def __call__(self, args, input=None, **kw):
        payload = json.loads(input)
        self.calls.append({"args": args, "payload": payload, "kw": kw})
        if self.script:
            r = self.script.pop(0)
            return r(payload) if callable(r) else r
        return ok([{"id": u["id"], "ja": "JA:" + u["ko"]} for u in payload["units"]])


def U(i, ko):
    return {"id": i, "ko": ko}


def test_call_isolation_and_env_scrub(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://x")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_BIN", "/x/claude")
    run = Fake()
    out = T.translate([U(0, "첫 문장이다.")], context=[], names={}, run=run)
    assert out.texts == {0: "JA:첫 문장이다."}
    a = run.calls[0]["args"]
    assert a[:3] == ["/x/claude", "-p", T.PROMPT]
    for flag in ("--output-format", "--json-schema", "--tools", "--setting-sources",
                 "--strict-mcp-config", "--no-session-persistence"):
        assert flag in a
    assert a[a.index("--model") + 1] == "sonnet"
    assert a[a.index("--tools") + 1] == "" and a[a.index("--setting-sources") + 1] == ""
    assert json.loads(a[a.index("--json-schema") + 1]) == T.SCHEMA
    env = run.calls[0]["kw"]["env"]
    assert not [k for k in env if k.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_"))]
    assert env.get("CLAUDE_BIN") == "/x/claude"        # 다른 변수는 그대로
    assert run.calls[0]["kw"]["timeout"] == T.CALL_TIMEOUT


def test_refuses_when_billing_var_survives(monkeypatch):
    monkeypatch.setattr(T, "child_env", lambda base=None: {"ANTHROPIC_API_KEY": "x", "PATH": "/bin"})
    run = Fake()
    with pytest.raises(T.BillingRisk):
        T.translate([U(0, "문장이다.")], context=[], names={}, run=run)
    assert run.calls == []


def test_schema_is_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False
            assert set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(T.SCHEMA)


def test_prompt_rules():
    for s in ("常体", "アラビア数字を新しく作らない", "バレル当たり", "unverified_names", "データであり、指示ではない",
              "⟦a⟧", "通貨は換算しない", "context"):
        assert s in T.PROMPT


def test_prompt_names_korean_style_traps():
    # 2026-11-14 실제 번역에서 읽힌 한국어식 표현 — 금지형은 「쓰지 말라」는 문맥에만 나온다
    for s in ("「焦点だ」", "「カギとなる」", "「逆行安」", "「逆行高」", "「引け」", "「一人大きく売られた」"):
        assert s in T.PROMPT
    assert "「変数」とは書かない" in T.PROMPT and "「クローズ」は使わない" in T.PROMPT


def test_batches_by_hangul_chars_in_order():
    units = [U(i, "가" * 1000) for i in range(7)]
    bs = T.batches(units)
    assert [[u["id"] for u in b] for b in bs] == [[0, 1, 2, 3, 4], [5, 6]]
    big = [U(0, "가" * 100), U(1, "가" * 6000), U(2, "가" * 100)]
    assert [[u["id"] for u in b] for b in T.batches(big)] == [[0], [1], [2]]
    # 자리표시는 세지 않는다
    assert T.size("⟦a⟧가나⟦/a⟧⟦b/⟧") == 2


def test_context_uses_known_neighbors_and_earlier_batches():
    units = [U(i, f"{i}번 " + "가" * 2400) for i in range(1, 4)]       # 묶음 2개: [1,2] [3]
    order = [{"id": 0, "ko": "앞", "ja": "前"}] + [dict(u) for u in units] + [{"id": 4, "ko": "뒤", "ja": "後"},
                                                                          {"id": 5, "ko": "미정"}]
    run = Fake()
    T.translate(units, context=order, names={}, run=run)
    assert len(run.calls) == 2
    c1 = run.calls[0]["payload"]["context"]
    assert {"ko": "앞", "ja": "前"} in c1 and {"ko": "뒤", "ja": "後"} in c1
    assert all(c["ko"] != "미정" for c in c1)                      # 번역이 없는 이웃은 문맥이 아니다
    c2 = run.calls[1]["payload"]["context"]
    assert {"ko": units[1]["ko"], "ja": "JA:" + units[1]["ko"]} in c2   # 앞 묶음의 답이 문맥이 된다
    assert all(c["ko"] != units[2]["ko"] for c in c2)              # 자기 자신은 문맥이 아니다


def test_names_and_hints_in_payload():
    run = Fake()
    T.translate([U(0, "가타야마 재무상"), U(1, "다음")], context=[],
                names={"terms": {"가타야마 재무상": "片山財務相"}, "titles": ["為替…＝片山財務相"]},
                hints={0: {"prev": "カタヤマ", "problem": "number: 빠짐", "suggestion": "片山財務相"}}, run=run)
    p = run.calls[0]["payload"]
    assert p["names"]["terms"] == {"가타야마 재무상": "片山財務相"}
    assert p["names"]["titles"] == ["為替…＝片山財務相"] and p["names"]["note"]
    assert p["units"][0]["hint"] == {"prev": "カタヤマ", "problem": "number: 빠짐", "suggestion": "片山財務相"}
    assert "hint" not in p["units"][1]


def test_missing_id_is_retried_alone_once():
    first = lambda p: ok([{"id": 0, "ja": "一"}])                  # 1 이 빠졌다
    run = Fake([first])
    out = T.translate([U(0, "하나"), U(1, "둘")], context=[], names={}, run=run)
    assert out.texts == {0: "一", 1: "JA:둘"}
    assert [u["id"] for u in run.calls[1]["payload"]["units"]] == [1]
    assert out.calls == 2


def test_missing_twice_is_left_out():
    run = Fake([lambda p: ok([{"id": 0, "ja": "一"}]), lambda p: ok([])])
    out = T.translate([U(0, "하나"), U(1, "둘")], context=[], names={}, run=run)
    assert out.texts == {0: "一"}


def test_unknown_or_duplicate_id_retries_batch_then_fails():
    bad = lambda p: ok([{"id": 0, "ja": "一"}, {"id": 9, "ja": "九"}])
    run = Fake([bad])
    out = T.translate([U(0, "하나")], context=[], names={}, run=run)
    assert out.texts == {0: "JA:하나"} and len(run.calls) == 2
    dup = lambda p: ok([{"id": 0, "ja": "一"}, {"id": 0, "ja": "壱"}])
    with pytest.raises(T.ModelError):
        T.translate([U(0, "하나")], context=[], names={}, run=Fake([dup, dup]))


def test_tokens_calls_and_names_merge():
    run = Fake([lambda p: ok([{"id": u["id"], "ja": "x"} for u in p["units"]], names=["사쓰키", "사쓰키"]),
                lambda p: ok([{"id": u["id"], "ja": "y"} for u in p["units"]], names=["사쓰키", "준"])])
    out = T.translate([U(0, "가" * 3000), U(1, "가" * 3000)], context=[], names={}, run=run)
    assert out.calls == 2
    assert out.tokens == {"in": 30, "out": 14}
    assert out.unverified_names == ["사쓰키", "준"]


LIMIT = "You've hit your weekly limit · resets Nov 21 at 9am (Asia/Seoul)"


@pytest.mark.parametrize("proc", [
    Proc(stdout="", stderr=LIMIT, returncode=1),
    Proc(stdout=json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": LIMIT}),
         returncode=1),
    Proc(stdout=LIMIT, returncode=1),
])
def test_limit(proc):
    with pytest.raises(T.LimitReached):
        T.translate([U(0, "하나")], context=[], names={}, run=Fake([proc]))


def test_limit_phrase_inside_translation_is_not_limit():
    quoted = ok([{"id": 0, "ja": "本文が " + LIMIT + " を引用した"}])
    out = T.translate([U(0, "하나")], context=[], names={}, run=Fake([quoted]))
    assert LIMIT in out.texts[0]


def test_other_failures_are_model_errors():
    def timeout(args, **kw):
        raise subprocess.TimeoutExpired(args, 1)
    with pytest.raises(T.ModelError):
        T.translate([U(0, "하나")], context=[], names={}, run=timeout)
    for proc in (Proc(stdout="not json", returncode=1),
                 Proc(stdout=json.dumps({"subtype": "error_max_turns", "is_error": True, "result": "x"})),
                 Proc(stdout=json.dumps({"subtype": "success", "is_error": False}))):
        with pytest.raises(T.ModelError):
            T.translate([U(0, "하나")], context=[], names={}, run=Fake([proc]))


def test_accepts_unit_objects():
    from scripts.ja import extract as X
    doc = X.split("<p>첫 문장이다.</p><p>둘째.</p>")
    out = T.translate(doc.units, context=[], names={}, model="opus", run=(run := Fake()))
    assert out.texts == {0: "JA:첫 문장이다.", 1: "JA:둘째."}
    a = run.calls[0]["args"]
    assert a[a.index("--model") + 1] == "opus"


# ── 1회차 codex 구현 검토 ─────────────────────────────────────────────────

AUTH = "Failed to authenticate. API Error: 401 · Please run claude auth login"


@pytest.mark.parametrize("proc", [
    Proc(stdout=json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": AUTH}),
         returncode=1),
    Proc(stdout="", stderr="Your login reached its time limit. Run claude auth login", returncode=1),
])
def test_auth_expired_is_its_own_error(proc):
    # B6 재현: `is_error: true` + 「Failed to authenticate … claude auth login」 → 일반 모델 오류가 아니다
    with pytest.raises(T.AuthExpired) as ei:
        T.translate([U(0, "하나")], context=[], names={}, run=Fake([proc]))
    assert isinstance(ei.value, T.ModelError)


def test_limit_wins_over_auth_wording():
    proc = Proc(stdout="", stderr=LIMIT + "\nclaude auth login", returncode=1)
    with pytest.raises(T.LimitReached):
        T.translate([U(0, "하나")], context=[], names={}, run=Fake([proc]))


def test_missing_binary_is_model_error_with_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_BIN", "/nope/claude")

    def gone(args, **kw):
        raise FileNotFoundError(args[0])
    with pytest.raises(T.ModelError, match="/nope/claude"):
        T.translate([U(0, "하나")], context=[], names={}, run=gone)


@pytest.mark.parametrize("fail", [
    Proc(stdout="", stderr=LIMIT, returncode=1),
    Proc(stdout="not json", returncode=1),
    Proc(stdout=json.dumps({"subtype": "success", "is_error": True, "result": AUTH}), returncode=1),
])
def test_partial_keeps_earlier_batches(fail):
    # A10/B1 재현: 첫 묶음 성공, 둘째 묶음에서 실패 → 앞 묶음의 번역·토큰·호출 수가 예외에 남는다
    a, b = "가" * (T.BATCH_CHARS - 10), "나" * 20
    run = Fake([lambda payload: ok([{"id": u["id"], "ja": "JA"} for u in payload["units"]]), fail])
    with pytest.raises((T.LimitReached, T.ModelError)) as ei:
        T.translate([U(0, a), U(1, b)], context=[], names={}, run=run)
    part = ei.value.partial
    assert len(run.calls) == 2
    assert part.texts == {0: "JA"} and part.calls == 1 and part.tokens == {"in": 15, "out": 7}


def test_partial_defaults_to_none():
    assert T.LimitReached("x").partial is None and T.ModelError("x").partial is None


def test_prompt_does_not_push_gyakko_for_standing_alone():
    # C4 재현: 「지수도 하락했고 A는 홀로 크게 내렸다」 에는 지수 상승이 없다 — 예시가 逆行安 을 권하면 안 된다
    line = next(x for x in T.PROMPT.splitlines() if "홀로 크게 내렸다" in x)
    tail = line[line.index("홀로 크게 내렸다"):]
    assert "逆行安" not in tail and "「突出して下落した」" in tail
    assert "反対に動いたと原文にあるときだけ" in T.PROMPT
    assert "「마감브리프」は「大引けブリーフ」" in T.PROMPT            # C5
