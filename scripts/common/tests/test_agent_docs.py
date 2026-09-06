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

이 검사가 실패하면 잎사귀를 줄이는 것이 아니라 **설계 이력을 spec 으로 옮기고
「고칠 때」 포인터를 남긴다.** 잎사귀에는 지금 작업할 때 필요한 계약만 둔다.
"""

import os
import re

import pytest

# codex 의 project doc 합산 기본 한도. `~/.codex/config.toml` 의
# `project_doc_max_bytes` 로 올릴 수 있지만(65536 까지 확인됨) 그것은 로컬
# 설정이라 다른 환경에 따라오지 않는다. 기본값에 맞춰 둔다.
CHAIN_LIMIT = 32_768

# 공통 문서의 **독자 상한**. 체인 검사만 있으면 여기가 부풀어도 「가장 큰 잎사귀가
# 아직 들어간다」는 이유로 통과한다 — 그러다 잎사귀 하나가 커지는 순간 네 파이프라인이
# 동시에 잘린다. 그래서 따로 잰다. 값의 근거: 가장 큰 잎사귀(us ~19.4 KB)에 성장 여유를
# 두고도 체인이 남는 자리. `AGENTS.md` 머리말이 같은 숫자를 적고 있어야 한다.
SHARED_LIMIT = 13_000

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
    assert total <= CHAIN_LIMIT, (
        f"scripts/{name} 지침 체인이 {total:,} B 로 한도 {CHAIN_LIMIT:,} B 를 "
        f"{total - CHAIN_LIMIT:,} B 넘겼다 "
        f"({', '.join(f'{d} {n:,}' for d, n in sizes.items())}).\n"
        f"codex 는 넘긴 만큼을 꼬리부터 **표시 없이** 버린다.\n"
        f"잎사귀를 억지로 줄이지 말고 설계 이력·사고 경위를 "
        f"docs/superpowers/specs/ 로 옮긴 뒤 「고칠 때」 포인터를 남길 것."
    )


def test_shared_doc_has_its_own_ceiling():
    """**체인 검사만으로는 못 잡는다.** 공통 문서가 부풀어도 「가장 큰 잎사귀가
    아직 들어간다」는 이유로 통과하고, 잎사귀 하나가 커지는 순간 네 파이프라인이
    동시에 잘린다(2026-09-06 codex 검토: 문서는 10 KB 라고 적고 실제는 12.7 KB
    였는데 테스트는 통과했다)."""
    shared = _size("AGENTS.md")
    assert shared <= SHARED_LIMIT, (
        f"공통 문서가 {shared:,} B 로 독자 상한 {SHARED_LIMIT:,} B 를 넘겼다. "
        f"여기 쓸 내용인지부터 의심할 것 — 한 파이프라인 것이면 잎사귀로 보낸다."
    )


def test_the_shared_ceiling_is_written_in_the_doc_itself():
    """문서가 적은 숫자와 검사하는 숫자가 갈리면 문서가 거짓말을 한다."""
    text = _read("AGENTS.md")
    assert f"{SHARED_LIMIT:,}" in text or str(SHARED_LIMIT) in text, (
        f"AGENTS.md 머리말이 실제 상한 {SHARED_LIMIT:,} B 를 적고 있지 않다."
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
