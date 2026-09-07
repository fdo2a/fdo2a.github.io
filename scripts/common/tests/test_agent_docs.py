"""지침 문서 구조 게이트 (2026-09-05).

「앞으로 새로운걸 추가하더라도 지금 설정한 형태로 되도록 해」(사용자 지시)를
프롬프트가 아니라 검사로 강제한다. 이 레포의 다른 규율과 같은 방식이다 —
「매일 돌되 보통은 아무것도 하지 마」도 프롬프트로는 안 지켜져서 게이트로 옮겼다.

지키려는 형태:

    report/CLAUDE.md            얇은 라우터 (레포 밖 — CI 에는 없다)
    site/AGENTS.md              공통 규칙의 자리. codex 가 어디서든 읽는 유일한 곳
    site/CLAUDE.md              → AGENTS.md 심볼릭 링크
    site/scripts/<p>/CLAUDE.md  파이프라인 잎사귀. 그 코드를 건드리면 자동 로드
    site/scripts/<p>/AGENTS.md  → CLAUDE.md 심볼릭 링크
    docs/superpowers/specs/     설계 근거·사고 이력

**왜 크기를 재나**: codex 는 지침 체인(`site/AGENTS.md` + 잎사귀 하나)이
32,768 B 를 넘으면 **꼬리부터 표시 없이 잘라낸다**(2026-09-05 `codex debug
prompt-input` 실측 — us 에서 9,009 B 가 조용히 버려지고 있었다). 잘린 자리가
「지켜야 할 규칙」이면 그 규칙은 없는 것과 같다.

**왜 한도가 아니라 예산으로 재나**: 한도에서 우는 검사는 늦다. 2026-09-06 이전이
그 상태였다 — 여유가 공통 132 B · us 체인 137 B 라, 규칙 한 줄을 더하는 사람이
무관한 spec 추출 리팩터를 그 작업 한가운데서 떠안거나, 테스트를 건너뛴 커밋이
잎사귀 꼬리를 조용히 지웠다. 그래서 한도보다 **예비량만큼 앞에서** 실패시킨다.
예비량은 **쓰라고 있는 자리가 아니다** — codex 가 아직 체인 전체를 읽고 있는
동안 빨간불이 뜨게 하는 폭이다. 실제로 쓸 수 있는 자리는 `예산 − 현재 크기`다.

이 검사가 실패하면 잎사귀를 줄이는 것이 아니라 **설계 이력을 spec 으로 옮기고
「고칠 때」 포인터를 남긴다.** 잎사귀에는 지금 작업할 때 필요한 계약만 둔다.
무엇이 계약인가 — **지우면 허용·금지·순서·소유권·오류 처리·검증 조건이
달라지는 문장**이 계약이고, 「왜 그 규칙이 생겼는가」의 날짜·수치·사건이 이력이다.
목적지 spec 에 같은 문장이 이미 있는지 먼저 보라(2026-09-06 실측: 옮기려던 넷 중
셋이 이미 있었다).
"""

import os
import re

import pytest

# codex 의 project doc 합산 기본 한도. `~/.codex/config.toml` 의
# `project_doc_max_bytes` 로 올릴 수 있지만(65536 까지 확인됨) 그것은 로컬
# 설정이라 다른 환경에 따라오지 않는다. 기본값에 맞춰 둔다.
CHAIN_LIMIT = 32_768

# 공통 문서의 **독자 상한**. 체인 검사만 있으면 여기가 부풀어도 「가장 큰 잎사귀가
# 아직 들어간다」는 이유로 통과한다. 공통이 커지면 **모든 체인의 여유가 같이 깎이지만
# 한도를 넘는 시점은 체인마다 다르다** — 지금은 us 가 먼저 넘는다(2026-09-06 여유:
# us 2.1 KB, kr 11.7 KB, thesis 15.9 KB, china 18.1 KB). 그래서 따로 잰다.
SHARED_LIMIT = 13_000

# ── 예비량 ──
# **정책값이지 실측 최적값이 아니다.** 「가장 큰 항목 하나가 들어갈 폭」이라고 적고
# 싶었으나 그 근거는 서지 않는다 — 레포에서 가장 큰 항목은 `scripts/kr/CLAUDE.md:8`
# 의 2,329 B 이고, 항목에 「고칠 때」 포인터까지 포함하면 더 커진다(2026-09-06 codex
# 검토 지적 1). 여기 값이 재는 것은 **한 번의 보통 편집을 흡수하는 폭** 뿐이다.
#
# 값을 고른 방식: 이력을 spec 으로 옮겨 확보한 자리를 「예비량」과 「실제로 쓸 자리」로
# 나눈 결과다. 예비량을 키우면 빨간불이 더 일찍 뜨지만 쓸 자리가 줄어든다 — 2,048 로
# 잡으면 us 체인이 예산을 216 B 넘겨 당장 빨간불이고, 예전과 똑같이 다음 한 줄이
# 리팩터를 부른다(2026-09-06 codex 검토 지적 2).
#
# 512 는 「공통은 체인의 절반 폭만 예약한다」는 배분일 뿐 따로 잰 근거가 없다.
# 공통이 커지면 네 체인의 여유가 한꺼번에 깎이므로 더 좁게 잡았다.
#
# **현재 여유를 여기 적지 않는다.** 2026-09-07 에 두 번 낡았다 — 적어 두면 문서가
# 한 줄 자랄 때마다 주석이 거짓이 된다. 실패 메시지가 그때그때 잰 값을 찍고,
# 지금 값이 궁금하면 `pytest scripts/common/tests/test_agent_docs.py` 를 돌린다.
CHAIN_MARGIN = 1_024
SHARED_MARGIN = 512
CHAIN_BUDGET = CHAIN_LIMIT - CHAIN_MARGIN     # 31,744
SHARED_BUDGET = SHARED_LIMIT - SHARED_MARGIN  # 12,488

_HERE = os.path.abspath(__file__)  # site/scripts/common/tests/test_agent_docs.py
REPO = os.path.dirname(  # site/
    os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
)

LEAVES = ("us", "kr", "thesis", "china")

# 「고칠 때 이 spec 을 읽어라」 — 한국어·영어 어느 쪽이든 **조건부 지시**여야 한다.
# 맨 포인터는 읽히지 않는다(AGENTS.md 「Adding something new」 1항).
CONDITIONAL_POINTERS = ("고칠 때", "When changing this")

# 폐기된 경로를 「쓰지 말 것」이라고 적는 정상적인 주의문까지 실재 검사에 걸리면
# 이력을 남길 수 없다. 취소선으로 감싼 것만 예외로 둔다 — 넓은 예외("역사"라고
# 적기만 하면 통과)는 활성 경로까지 빠져나가게 한다.
_STRUCK = re.compile(r"~~[^~]*~~")


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _size(*parts):
    """**바이트로 잰다.** 텍스트 모드로 읽어 encode 하면 CRLF 가 LF 로 정규화돼
    원본보다 작게 세어진다 — 예산은 파일이 차지하는 바이트다."""
    with open(os.path.join(REPO, *parts), "rb") as fh:
        return len(fh.read())


# ── 참조 추출 (순수 함수 — 합성 입력으로 직접 시험한다) ──────────────────────

_SPEC_RE = re.compile(r"docs/superpowers/specs/([^\s`)\]]+\.md)")
# 백틱 안의 경로, 마크다운 링크, 명령 인자가 붙은 경로를 모두 잡는다.
# 예전 정규식은 백틱 안에 **경로만** 있을 때만 잡아서 `scripts/x.py --flag` 와
# `[제목](scripts/x.py)` 를 통째로 놓쳤다(2026-09-06 codex 검토).
_SCRIPT_RE = re.compile(r"(?<![\w./-])(scripts/[\w./-]*\.py)")


def spec_refs(text):
    """문서가 지목하는 spec 파일 경로들. 취소선 안은 폐기 이력으로 보고 뺀다."""
    live = _STRUCK.sub("", text)
    return sorted({"docs/superpowers/specs/" + m for m in _SPEC_RE.findall(live)})


def script_refs(text):
    """문서가 지목하는 스크립트 경로들. 취소선 안은 폐기 이력으로 보고 뺀다."""
    return sorted(set(_SCRIPT_RE.findall(_STRUCK.sub("", text))))


def budget_verdict(size, budget, limit):
    """`ok` / `over_budget` / `over_limit` 중 하나. **순수 함수라 경계값을 직접
    먹여 본다** — 부등호 하나가 뒤집히면 예산 검사가 한 바이트 늦게 운다.

    `over_budget` 과 `over_limit` 을 가르는 이유: 예산은 이 레포의 정책이고
    한도는 codex 기본값이다. 둘을 같은 문구로 말하면, 아직 아무것도 잘리지
    않았는데 「지금 잘리고 있다」고 겁을 주게 된다(2026-09-06 codex 검토 지적 10).
    한도 자체도 `project_doc_max_bytes` 로 올릴 수 있으므로 「잘린다」가 아니라
    「기본 설정에서는 잘린다」가 정확하다."""
    if size > limit:
        return "over_limit"
    if size > budget:
        return "over_budget"
    return "ok"


def budget_message(what, size, budget, limit, detail="", limit_label=None,
                   cliff=True):
    """실패 문구. 남은 자리와 넘긴 양을 **둘 다** 말한다 — 예산을 넘겼을 때
    「한도까지 아직 N B 남았다」를 알아야 계약을 지우지 않고 옮길 수 있다.

    `cliff` 는 그 한도를 넘기면 **실제로 잘리는가**다. 체인 한도는 codex 기본값이라
    참이지만 공통 문서의 `SHARED_LIMIT` 은 이 레포의 정책일 뿐이다 — 공통이 13,000 B
    를 1 B 넘겨도 체인은 아직 32,768 B 아래일 수 있다. 같은 문구로 말하면 아무것도
    안 잘리는데 잘린다고 겁을 준다(2026-09-07 codex 검토 지적 3)."""
    verdict = budget_verdict(size, budget, limit)
    label = limit_label or ("codex 기본 한도" if cliff else "상한")
    head = f"{what}가 {size:,} B"
    if verdict == "over_limit":
        tail = (
            "**기본 설정에서는 넘긴 만큼이 꼬리부터 표시 없이 버려진다** — "
            "지금 잘려 나가는 자리가 무엇인지 확인할 것."
            if cliff else
            "아직 체인 한도에 걸린 것은 아니지만, 여기가 커지면 모든 체인의 여유가 "
            "같이 깎인다."
        )
        return (
            f"{head} 로 {label} {limit:,} B 를 {size - limit:,} B 넘겼다"
            f"{detail}.\n{tail}\n"
            f"잎사귀를 억지로 줄이지 말고 설계 이력을 docs/superpowers/specs/ 로 "
            f"옮긴 뒤 「고칠 때」 포인터를 남긴다."
        )
    return (
        f"{head} 로 예산 {budget:,} B 를 {size - budget:,} B 넘겼다{detail}.\n"
        f"아직 {label} {limit:,} B 까지 {limit - size:,} B 남아 있다 — **codex 가 체인을 "
        f"다 읽고 있는 지금 옮기라고 우는 것이다.** 이 자리는 쓰라고 있는 예비량이 "
        f"아니다.\n계약(허용·금지·순서·소유권·오류 처리·검증 조건)은 그대로 두고 "
        f"이력(날짜·수치·사건)만 spec 으로 옮긴 뒤 「고칠 때」 포인터를 남길 것. "
        f"목적지에 같은 문장이 이미 있는지 먼저 본다."
    )


def chain_docs(*leaf_parts):
    """codex 가 실제로 이어 붙이는 문서들 — 레포 루트에서 잎사귀 디렉터리까지
    **경로 위의 모든 `AGENTS.md`**. 고정 목록(공통 + 잎사귀 하나)만 더하면
    중간에 `scripts/AGENTS.md` 를 하나 놓는 것만으로 예산 검사를 빠져나간다."""
    out, here = [], []
    for part in ("",) + tuple(leaf_parts):
        if part:
            here.append(part)
        doc = os.path.join(*here, "AGENTS.md") if here else "AGENTS.md"
        if os.path.exists(os.path.join(REPO, doc)):
            out.append(doc)
    return out


def _leaf(name):
    return os.path.join("scripts", name, "CLAUDE.md")


# ── 형태 ────────────────────────────────────────────────────────────────


def test_shared_doc_exists():
    """공통 규칙은 site/AGENTS.md 에 있다 — 레포 루트 위는 codex 가 안 읽는다."""
    assert os.path.isfile(os.path.join(REPO, "AGENTS.md"))


@pytest.mark.parametrize("name", LEAVES)
def test_leaf_doc_exists(name):
    assert os.path.isfile(os.path.join(REPO, _leaf(name)))


def test_site_claude_is_symlink_to_agents():
    """site/ 만 방향이 반대다 — codex 가 AGENTS.md 를 읽으므로 그쪽이 실체."""
    link = os.path.join(REPO, "CLAUDE.md")
    assert os.path.islink(link), "site/CLAUDE.md 는 심볼릭 링크여야 한다 (사본 금지)"
    assert os.readlink(link) == "AGENTS.md"


@pytest.mark.parametrize("name", LEAVES)
def test_leaf_agents_is_symlink_to_claude(name):
    """사본을 만들면 조용히 갈라진다 — 2026-09-05 감사에서 `sed s/claude/Codex/`
    사본이 존재하지 않는 경로 10곳을 가리키고 있었다."""
    link = os.path.join(REPO, "scripts", name, "AGENTS.md")
    assert os.path.islink(link), f"scripts/{name}/AGENTS.md 는 심볼릭 링크여야 한다"
    assert os.readlink(link) == "CLAUDE.md"


# ── 예산 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", LEAVES)
def test_chain_fits_codex_budget(name):
    docs = chain_docs("scripts", name)
    sizes = {d: _size(d) for d in docs}
    total = sum(sizes.values())
    detail = " (" + ", ".join(f"{d} {n:,}" for d, n in sizes.items()) + ")"
    assert budget_verdict(total, CHAIN_BUDGET, CHAIN_LIMIT) == "ok", budget_message(
        f"scripts/{name} 지침 체인", total, CHAIN_BUDGET, CHAIN_LIMIT, detail
    )


def test_shared_doc_has_its_own_ceiling():
    """**체인 검사만으로는 못 잡는다.** 공통 문서가 부풀어도 「가장 큰 잎사귀가
    아직 들어간다」는 이유로 통과하고, 잎사귀 하나가 커지는 순간 네 파이프라인이
    동시에 잘린다(2026-09-06 codex 검토: 문서는 10 KB 라고 적고 실제는 12.7 KB
    였는데 테스트는 통과했다)."""
    shared = _size("AGENTS.md")
    assert budget_verdict(shared, SHARED_BUDGET, SHARED_LIMIT) == "ok", budget_message(
        "공통 문서", shared, SHARED_BUDGET, SHARED_LIMIT,
        " — 여기 쓸 내용인지부터 의심할 것, 한 파이프라인 것이면 잎사귀로 보낸다",
        limit_label="이 레포의 독자 상한", cliff=False,
    )


# 「4.」로 시작하고 **콤마 끊은 바이트 수치**를 가진 줄. 「B 가 들어간 4항」으로
# 잡으면 「Rules」 절의 4항(`**Banned term ...**`)도 걸린다 — 지금은 예산 항목이
# 파일에서 먼저 나와 우연히 맞을 뿐이고, 절 순서가 바뀌면 조용히 엉뚱한 줄을 잰다.
_BUDGET_RULE = re.compile(r"^\s*4\..*\d{1,3},\d{3}\s*B")
_BUDGET_SECTION = "## Adding something new"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

# 바이트 수치. **경계를 본다** — `112,488 B` 안의 `12,488` 로 통과하면 안 된다
# (2026-09-07 codex 검토 지적 2, 재현 입력을 받았다).
_FIGURE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+)(?![\d,])\s*B")


def budget_rule_text(text):
    """AGENTS.md 「Adding something new」 **절 안의** 예산 항목 한 줄.

    문서 어디에나 숫자가 있으면 통과시키면 안 된다. 주석을 먼저 걷고 절로 범위를
    좁히는 이유 — 머리말 주석에 폐기한 옛 수치를 남겨 두는 것만으로 통과했다
    (2026-09-07 codex 검토 지적 1, 재현 입력을 받았다)."""
    body = _HTML_COMMENT.sub("", text)
    if _BUDGET_SECTION not in body:
        return ""
    section = body.split(_BUDGET_SECTION, 1)[1].split("\n## ", 1)[0]
    for line in section.split("\n"):
        if _BUDGET_RULE.match(line):
            return line
    return ""


def budget_figures(line):
    """줄에 적힌 바이트 수치를 **나온 순서대로**. 순서를 보는 이유: 값이 다 있어도
    공통과 체인이 뒤바뀐 문장(「shared ≤ 31,744 B, chain ≤ 12,488 B」)은 거짓이다."""
    return [int(m.replace(",", "")) for m in _FIGURE.findall(line)]


def test_the_budget_is_written_in_the_doc_itself():
    """문서가 적은 숫자와 검사하는 숫자가 갈리면 문서가 거짓말을 한다.
    **예산과 한도를 둘 다** 적어야 한다 — 예산만 적으면 왜 그 값인지 알 수 없고,
    한도만 적으면 벼랑까지 써도 되는 줄 안다."""
    rule = budget_rule_text(_read("AGENTS.md"))
    assert rule, "AGENTS.md 「Adding something new」에 바이트 예산 항목(4.)이 없다."
    figures = budget_figures(rule)
    assert figures[:2] == [SHARED_BUDGET, CHAIN_BUDGET], (
        f"AGENTS.md 예산 항목이 공통 {SHARED_BUDGET:,} B → 체인 {CHAIN_BUDGET:,} B "
        f"순서로 적고 있지 않다 (읽은 수치: {figures}):\n  {rule}"
    )
    assert CHAIN_LIMIT in figures, (
        f"AGENTS.md 예산 항목이 codex 한도 {CHAIN_LIMIT:,} B 를 적고 있지 않다 — "
        f"예산만 적으면 왜 그 값인지 알 수 없다:\n  {rule}"
    )


def test_shared_doc_leaves_room_for_leaves():
    """공통 문서가 커지면 모든 잎사귀가 동시에 잘린다. 가장 큰 잎사귀가
    들어갈 자리는 남겨 둔다."""
    shared = _size("AGENTS.md")
    biggest = max(_size(_leaf(n)) for n in LEAVES)
    assert shared + biggest <= CHAIN_LIMIT, (
        f"공통 문서 {shared:,} B 가 가장 큰 잎사귀 {biggest:,} B 를 밀어낸다."
    )


def test_every_instruction_doc_is_declared():
    """등록하지 않은 지침 파일은 검사에서 통째로 빠진다 — 새 파이프라인을 만들고
    LEAVES 에 안 넣으면 예산도 참조도 아무도 안 본다. 중간 디렉터리에 지침을
    하나 놓는 것만으로도 체인이 조용히 길어진다."""
    found = set()
    for root, _dirs, files in os.walk(os.path.join(REPO, "scripts")):
        if "CLAUDE.md" in files or "AGENTS.md" in files:
            found.add(os.path.relpath(root, os.path.join(REPO, "scripts")))
    assert found == set(LEAVES), (
        f"지침 파일이 있는 디렉터리 {sorted(found)} 가 등록 목록 {sorted(LEAVES)} 와 "
        f"다르다. 새 파이프라인이면 LEAVES 에 넣고, 중간 디렉터리 지침이면 "
        f"체인이 길어지므로 없앨 것."
    )


# ── 참조 무결성 ──────────────────────────────────────────────────────────


def _docs():
    yield "AGENTS.md", _read("AGENTS.md")
    for name in LEAVES:
        yield _leaf(name), _read(_leaf(name))


def test_referenced_specs_exist():
    """「고칠 때 이 spec 을 읽어라」가 없는 파일을 가리키면 이력이 유실된 것이다."""
    missing = []
    for where, text in _docs():
        for path in spec_refs(text):
            if not os.path.isfile(os.path.join(REPO, path)):
                missing.append(f"{where} → {path}")
    assert not missing, "존재하지 않는 spec 을 가리킨다:\n  " + "\n  ".join(missing)


def test_referenced_scripts_exist():
    """지침이 가리키는 스크립트 경로가 실재하는지."""
    missing = []
    for where, text in _docs():
        for path in script_refs(text):
            if not os.path.isfile(os.path.join(REPO, path)):
                missing.append(f"{where} → {path}")
    assert not missing, "존재하지 않는 스크립트를 가리킨다:\n  " + "\n  ".join(missing)


@pytest.mark.parametrize("name", LEAVES)
def test_leaf_names_a_real_spec_file(name):
    """**디렉터리 이름만으로는 통과시키지 않는다.** 예전 검사는 본문에
    `docs/superpowers/specs/` 라는 문자열 하나만 있어도 통과했다 — 계약을 전부
    지우고 그 한 줄만 남겨도 세 검사가 다 녹색이었다(2026-09-06 codex 재현)."""
    refs = spec_refs(_read(_leaf(name)))
    assert refs, (
        f"scripts/{name}/CLAUDE.md 가 **실제 spec 파일**을 지목하지 않는다. "
        f"디렉터리 경로만 적는 것으로는 부족하다 — 파일명까지 적을 것."
    )


@pytest.mark.parametrize("name", LEAVES)
def test_leaf_pointer_is_a_conditional_instruction(name):
    """맨 포인터는 읽히지 않는다. 「X 를 건드리기 전에 이 spec 을 읽는다」처럼
    **조건이 붙은 지시**여야 실제로 읽는다(AGENTS.md 「Adding something new」 1항)."""
    text = _read(_leaf(name))
    assert any(k in text for k in CONDITIONAL_POINTERS), (
        f"scripts/{name}/CLAUDE.md 에 조건부 포인터가 없다 — "
        f"{' / '.join(CONDITIONAL_POINTERS)} 중 하나로 「언제 읽어야 하는지」를 적을 것."
    )


# ── 게이트 자신을 시험한다 (합성 입력) ────────────────────────────────────
#
# 「게이트가 읽는 문장 ≠ 지켜야 할 것」이 이 레포가 되풀이해 밟은 자리다.
# 검사가 무엇을 놓치는지는 실제 문서로는 드러나지 않으므로 직접 먹여 본다.

def test_the_spec_check_rejects_a_bare_directory_string():
    assert spec_refs("상세는 docs/superpowers/specs/ 를 볼 것") == []
    assert spec_refs("`docs/superpowers/specs/2026-08-24-thesis-watch-design.md`") == [
        "docs/superpowers/specs/2026-08-24-thesis-watch-design.md"]


def test_the_script_check_sees_commands_and_links_too():
    """백틱 안에 **경로만** 있을 때만 잡던 옛 정규식은 정상 표기 다수를 놓쳤다."""
    assert script_refs("`scripts/a.py --flag` 를 돌린다") == ["scripts/a.py"]
    assert script_refs("[제목](scripts/b.py) 참고") == ["scripts/b.py"]
    assert script_refs("`python3 scripts/c.py posts/x.html`") == ["scripts/c.py"]
    assert script_refs("로직 `scripts/us/d.py`.") == ["scripts/us/d.py"]


def test_deprecated_paths_are_excused_only_when_struck_through():
    """폐기 이력을 남길 수 있어야 하지만, 예외는 좁아야 한다 — 「역사」라고
    적기만 하면 통과하는 넓은 예외는 활성 경로까지 빠져나가게 한다."""
    assert script_refs("~~scripts/gone.py~~ 는 삭제됐다") == []
    assert script_refs("옛날 이야기지만 `scripts/gone.py` 는 삭제됐다") == ["scripts/gone.py"]


def test_the_budget_verdict_is_off_by_none():
    """부등호 경계. `>` 를 `>=` 로 잘못 쓰면 예산에 **딱 맞는** 문서가 초과 판정을
    받고, `>=` 를 `>` 로 쓰면 한 바이트 넘긴 문서가 통과한다."""
    b, l = 100, 120
    assert budget_verdict(b - 1, b, l) == "ok"
    assert budget_verdict(b, b, l) == "ok"          # 예산에 딱 맞으면 통과
    assert budget_verdict(b + 1, b, l) == "over_budget"
    assert budget_verdict(l, b, l) == "over_budget"  # 한도에 딱 맞아도 아직 안 잘린다
    assert budget_verdict(l + 1, b, l) == "over_limit"


def test_over_budget_and_over_limit_say_different_things():
    """같은 문구를 쓰면, 아직 아무것도 잘리지 않았는데 「잘리고 있다」고 겁을 준다."""
    over_budget = budget_message("체인", 110, 100, 120)
    over_limit = budget_message("체인", 130, 100, 120)
    assert "10 B 남아" in over_budget and "codex 기본 한도 120 B 까지" in over_budget
    assert "버려진다" not in over_budget, "예산 초과인데 잘린다고 말하고 있다"
    assert "버려진다" in over_limit and "기본 설정에서는" in over_limit
    assert "남아 있다" not in over_limit


def test_the_budget_rule_is_read_from_the_rule_not_the_whole_file():
    """폐기한 옛 수치가 문서 어딘가에 남아 있어도 통과하면 안 된다."""
    assert budget_rule_text("여기 어딘가 30,720 B 라고 적힌 옛 문장") == ""
    section = "## Adding something new\n3. 사본 금지\n4. **예산 12,488 B / 31,744 B**\n"
    assert budget_rule_text(section) == "4. **예산 12,488 B / 31,744 B**"


def test_the_budget_rule_is_not_confused_with_the_other_rule_four():
    """AGENTS.md 에는 4항이 둘이다 — 「Adding something new」의 예산과 「Rules」의
    금칙어. 「B 가 들어간 4항」으로 집으면 둘 다 걸리고, 절 순서가 바뀌는 날
    조용히 엉뚱한 줄을 잰다."""
    banned = '4. **Banned term "buy-side"**: never use buy-side anywhere in US or KR posts.'
    assert budget_rule_text("## Rules\n" + banned) == ""
    both = "## Adding something new\n4. **Budget: this file <= 12,488 B**\n## Rules\n" + banned
    assert budget_rule_text(both) == "4. **Budget: this file <= 12,488 B**"


def test_the_budget_rule_ignores_comments_and_other_sections():
    """머리말 주석에 폐기한 옛 수치를 남겨 두는 것만으로 통과했다
    (2026-09-07 codex 검토 지적 1 — 아래가 codex 가 준 재현 입력이다)."""
    bypass = (
        "<!--\n4. old 12,488 B / 31,744 B / 32,768 B\n-->\n"
        "## Adding something new\n4. No budget\n"
    )
    assert budget_rule_text(bypass) == ""
    assert budget_rule_text("## Rules\n4. **Banned term** 12,488 B") == ""
    good = "## Adding something new\n4. **Budget: 12,488 B / 31,744 B**\n## Rules\n"
    assert budget_rule_text(good) == "4. **Budget: 12,488 B / 31,744 B**"


def test_the_budget_figures_see_role_and_boundary():
    """숫자가 「들어 있는지」만 보면 뒤바뀐 값도 자릿수가 다른 값도 통과한다
    (2026-09-07 codex 검토 지적 2 — 둘 다 codex 가 재현해 보였다)."""
    assert budget_figures("shared <= 12,488 B, chain <= 31,744 B; limit 32,768 B") == [
        12_488, 31_744, 32_768]
    # 뒤바뀐 문장은 같은 수치를 갖고도 순서가 다르다
    assert budget_figures("shared <= 31,744 B, chain <= 12,488 B; limit 32,768 B") == [
        31_744, 12_488, 32_768]
    # 부분 문자열로 통과하던 자리 — `112,488` 은 `12,488` 이 아니다
    assert budget_figures("shared <= 112,488 B, chain <= 131,744 B") == [112_488, 131_744]


def test_a_policy_ceiling_does_not_claim_the_text_is_being_cut():
    """공통 문서가 제 상한을 1 B 넘겨도 체인은 아직 codex 한도 아래일 수 있다.
    거기에 「꼬리가 버려진다」를 붙이면 게이트가 거짓말을 한다."""
    policy = budget_message("공통 문서", 13_001, 12_488, 13_000,
                            limit_label="이 레포의 독자 상한", cliff=False)
    assert "버려진다" not in policy and "이 레포의 독자 상한" in policy
    assert "버려진다" in budget_message("체인", 33_000, 31_744, 32_768)

