"""glossary — 전부 아니면 전무, 뜻이 하나인 것만."""
import re

import pytest

from scripts.ja import extract as X
from scripts.ja import glossary as G
from scripts.ja import news as N
from scripts.ja import state as S
from scripts.ja.tests.corpus import ROOT, read


@pytest.mark.parametrize("ko,ja", [
    ("현재 위치", "現在位置"),
    ("⟦a⟧US Market Brief⟦/a⟧ · 2026년 11월 12일(목) 마감 기준", "⟦a⟧US Market Brief⟦/a⟧ · 2026年11月12日(木) 取引終了時点"),
    ("⟦a⟧미국 시장⟦/a⟧⟦b⟧›⟦/b⟧⟦c⟧일간⟦/c⟧", "⟦a⟧米国市場⟦/a⟧⟦b⟧›⟦/b⟧⟦c⟧日次⟦/c⟧"),
    ("⟦a⟧原題⟦/a⟧⟦b⟧ロイター · 11월 12일⟦/b⟧", "⟦a⟧原題⟦/a⟧⟦b⟧ロイター · 11月12日⟦/b⟧"),
    ("11월 12일", "11月12日"),
    ("CPI YoY(9월)", "CPI YoY(9月)"),
    ("실업률(10월)", "失業率(10月)"),
    ("미시간대 소비자심리(9월 확정)", "ミシガン大学消費者信頼感指数(9月確報)"),
    ("9영업일째", "9営業日目"),
    ("12영업일", "12営業日"),
    ("2026-11-05 (10월 31일 주간)", "2026-11-05 (10月31日の週)"),
    ("2026-09 기준월", "2026-09基準月"),
    ("2026년 3분기", "2026年第3四半期"),
    ("변동성:", "ボラティリティ:"),
    ("  종가  ", "  終値  "),
    ("(금요일)", "(金曜日)"),
])
def test_fixed(ko, ja):
    assert G.fixed(ko) == ja


@pytest.mark.parametrize("ko", [
    "엔비디아가 4.34% 내렸다.",          # 문장은 모델
    "미국 증시 모닝브리프 — 2026년 11월 12일 (목요일)",   # 일부만 풀리면 None
    "강세",                               # 애매 — 넣지 않았다
    "우호",
    "5개 중 2개",
    "S&P 500",                             # 한글이 없으면 fixed 의 일이 아니다
])
def test_not_fixed(ko):
    assert G.fixed(ko) is None


def test_dict_has_no_sentences():
    for ko in G.DICT:
        assert not re.search(r"(다|요)\.?$", ko), ko
        assert len(ko) <= 30


def test_dict_values_have_no_hangul_and_keep_digits():
    for ko, ja in G.DICT.items():
        assert not G.HANGUL.search(ja), ko
        assert re.findall(r"\d+", ko) == re.findall(r"\d+", ja), ko


def test_latin_map_and_names_shape():
    assert all(isinstance(v, tuple) and v for v in G.LATIN_MAP.values())
    assert G.LATIN_MAP["Fed"][0] == "FRB"
    assert all(not G.HANGUL.search(v) for v in G.NAMES.values())


def test_candidates_cli_runs():
    rows = G.candidates(ROOT, recent=3, min_docs=3)
    assert rows and all(n >= 3 for n, _ in rows)
    assert any(seg == "현재 위치" for _, seg in rows)


def test_localized_japan_daily_news_heads_never_reach_the_model():
    """localize → split → plan: 일본어 원문 항목 안의 단위는 todo 가 하나도 없다."""
    path = "japan/daily/2026-11-12.html"
    html, rep = N.localize(read(path), N.lookup(ROOT, path))
    doc = X.split(html)
    plan = S.plan(doc, None)
    todo_uids = {u.uid for u in plan.todo}
    in_items = [u for u in doc.units if _inside_news_item(html, u.start)]
    assert in_items and not [u.ko for u in in_items if u.uid in todo_uids]
    # 원제는 고정 번역 뒤에도 그대로 남는다
    out = X.join(doc, plan.texts())
    recs = N.lookup(ROOT, path)
    for nid in rep.localized:
        import html as H
        assert H.escape(H.unescape(recs[nid]["title"]), quote=False) in out


def _inside_news_item(html, pos):
    i = html.rfind('<div class="news-item"', 0, pos)
    return i >= 0 and html.find("</div>", i) > pos


def test_every_fixed_answer_in_the_corpus_passes_the_unit_gate():
    """고정 번역은 다시 번역할 길이 없다 — 검사에 걸리면 그 글은 영영 보류된다."""
    from scripts.ja import gate as GT
    from scripts.ja.tests.corpus import target_paths
    bad = []
    for path in target_paths():
        html, _ = N.localize(read(path), N.lookup(ROOT, path))
        for u in X.split(html).units:
            ja = G.fixed(u.ko)
            if ja is not None:
                bad += [(path, u.ko, ja, p.code) for p in GT.check_unit(u.ko, ja) if not p.soft]
    assert not bad[:5]


def _repo_titles():
    import json
    import unicodedata
    titles = []

    def walk(x):                      # items 밖(region_filter 등)의 title 도 원제다
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "title" and isinstance(v, str):
                    titles.append(unicodedata.normalize("NFKC", v))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for p in (ROOT / "japan/data/news").rglob("*.json"):
        try:
            walk(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            continue
    assert titles
    return "\n".join(titles)


def test_names_have_evidence():
    """NAMES 의 값은 레포의 일본어 원제에 그대로 있거나(손 목록), 일본은행 공식 명단(BOJ_BOARD)에서 나온 꼴이어야 한다."""
    blob = _repo_titles()
    assert [ja for ja in G.NAMES_TITLES.values() if ja not in blob] == []          # 손 목록은 원제만으로 선다
    assert [ja for ja in G.roster_terms().values() if not G.roster_evidence(ja, blob)] == []
    assert set(G.NAMES) == set(G.NAMES_TITLES) | set(G.roster_terms())


_BLOB = "中立金利へ早期利上げを＝高田日銀委員\n植田日銀総裁の会見\n氷見野日銀副総裁が講演\n高田日銀総裁\n山田日銀委員"


@pytest.mark.parametrize("ja,want", [
    ("高田創", True), ("田村直樹", True), ("植田和男", True),
    ("高田日銀委員", True), ("田村日銀委員", True), ("内田日銀副総裁", True),
    ("山田日銀委員", False),               # 명단에 없는 성 — 원제에 그 문자열이 있어도 명단 근거가 아니다
    ("高田創一", False),                   # 명단의 이름과 다르다
    ("高田日銀総裁", False),               # 직함이 그 사람 것이 아니다 — 원제에 그 문자열이 있어도
    ("高田", False), ("田村", False),      # 맨 성
    ("田村城太郎", False),
])
def test_roster_evidence(ja, want):
    assert G.roster_evidence(ja, _BLOB) is want


def test_role_suffix_needs_a_title_that_headlines_use():
    # 「성+직함」 꼴은 그 직함 꼴이 원제에서 한 번이라도 쓰였을 때만 근거다
    assert G.roster_evidence("田村日銀委員", "植田日銀総裁の会見") is False


def test_boj_board_snapshot_shape():
    from datetime import date
    from urllib.parse import urlsplit
    b = G.BOJ_BOARD
    assert urlsplit(b["source"]).scheme == "https" and urlsplit(b["source"]).hostname == "www.boj.or.jp"
    date.fromisoformat(b["as_of"])
    roles = [m.role for m in b["members"]]
    assert (roles.count("総裁"), roles.count("副総裁"), roles.count("審議委員")) == (1, 2, 6)
    assert set(roles) == set(G.ROLE_SUFFIX) == set(G.ROLE_KO)
    for m in b["members"]:
        assert m.family and m.given and m.ko_family and m.ko_given
        assert re.fullmatch(r"[A-Z]+ [A-Z][a-z]+", m.romaji)
    assert len({m.family + m.given for m in b["members"]}) == 9


# 로마자 → 한글(외래어 표기법 일본어 표기: 어두 k·t 는 ㄱ·ㄷ, 어중은 ㅋ·ㅌ, 장음은 적지 않는다). 명단의 표준 표기가
# 손으로 적은 것이 아니라 공식 로마자에서 나온 것임을 본다.
_KANA = {"a": "아", "i": "이", "u": "우", "e": "에", "o": "오",
         "ka": ("가", "카"), "ki": ("기", "키"), "ku": ("구", "쿠"), "ke": ("게", "케"), "ko": ("고", "코"),
         "ta": ("다", "타"), "chi": ("지", "치"), "tsu": "쓰", "te": ("데", "테"), "to": ("도", "토"),
         "sa": "사", "shi": "시", "su": "스", "se": "세", "so": "소",
         "na": "나", "ni": "니", "nu": "누", "ne": "네", "no": "노",
         "ha": "하", "hi": "히", "fu": "후", "he": "헤", "ho": "호",
         "ma": "마", "mi": "미", "mu": "무", "me": "메", "mo": "모",
         "ya": "야", "yu": "유", "yo": "요", "ra": "라", "ri": "리", "ru": "루", "re": "레", "ro": "로",
         "wa": "와", "ga": "가", "gi": "기", "gu": "구", "ge": "게", "go": "고",
         "za": "자", "ji": "지", "zu": "즈", "ze": "제", "zo": "조",
         "da": "다", "de": "데", "do": "도", "ba": "바", "bi": "비", "bu": "부", "be": "베", "bo": "보",
         "ryo": "료", "ju": "주", "sho": "쇼", "kyo": ("교", "쿄")}


_N_BEFORE_VOWEL = {"shinichi": 3}      # 眞一 = しん·いち — 헵번식은 ん 뒤 모음을 가르지 않는다(자리: ん 의 위치)


def _hangul(romaji):
    w, out, i = romaji.lower(), [], 0
    while i < len(w):
        if w[i] == "n" and (i + 1 == len(w) or w[i + 1] not in "aiueoy" or _N_BEFORE_VOWEL.get(w) == i):
            c = ord(out[-1]) + 4                      # 받침 ㄴ
            out[-1] = chr(c)
            i += 1
            continue
        for n in (3, 2, 1):
            v = _KANA.get(w[i:i + n])
            if v is not None:
                out.append(v if isinstance(v, str) else v[0 if not out else 1])
                i += n
                break
        else:
            raise AssertionError(f"모르는 음절: {romaji} @{i}")
    return "".join(out)


def test_standard_korean_spellings_come_from_the_official_romaji():
    for m in G.BOJ_BOARD["members"]:
        fam, given = m.romaji.split()
        assert (m.ko_family, m.ko_given) == (_hangul(fam), _hangul(given)), m.romaji


def test_aliases_carry_recorded_evidence():
    want = {(a, m.family) for m in G.BOJ_BOARD["members"] for a in m.ko_alias}
    assert set(G.BOJ_ALIAS_EVIDENCE) == want
    assert all(len(v) > 40 for v in G.BOJ_ALIAS_EVIDENCE.values())
    for m in G.BOJ_BOARD["members"]:
        assert m.ko_family not in m.ko_alias


def test_no_person_key_is_a_bare_surname():
    # 같은 성의 다른 사람(상선미쓰이 다무라 사장, 우치다 이사장, 사토 교수)이 실제로 나온다
    fam = {k for m in G.BOJ_BOARD["members"] for k in (m.ko_family,) + tuple(m.ko_alias)}
    assert not fam & set(G.NAMES)
    for ko in G.roster_terms():
        assert " " in ko
    bare = {m.family for m in G.BOJ_BOARD["members"]}
    assert not bare & set(G.NAMES.values())


@pytest.mark.parametrize("ko,ja", [
    ("다카다 하지메", "高田創"), ("다카타 하지메", "高田創"), ("다무라 나오키", "田村直樹"),
    ("다카다 일본은행 심의위원", "高田日銀委員"), ("다무라 일본은행 심의위원", "田村日銀委員"),
    ("우에다 가즈오", "植田和男"), ("우에다 일본은행 총재", "植田日銀総裁"),
    ("우치다 일본은행 부총재", "内田日銀副総裁"), ("고에다 준코", "小枝淳子"),
])
def test_roster_terms_reach_names(ko, ja):
    assert G.NAMES[ko] == ja


def test_misread_given_name_is_not_a_key():
    # 한글 요약이 淳子 를 「아쓰코」로 읽은 적이 있다(공식 읽기는 Junko) — 그 표기는 근거가 없으니 보류된다
    assert "고에다 아쓰코" not in G.NAMES


def test_roster_terms_do_not_contradict_headline_terms():
    r = G.roster_terms()
    assert {k: (r[k], v) for k, v in G.NAMES_TITLES.items() if k in r and r[k] != v} == {}


def test_names_note_scopes_roster_kanji_to_the_boj():
    n = G.NAMES_NOTE
    assert "日銀" in n and "unverified_names" in n and "別人" in n


# ── 명단 한자를 다른 사람에게 붙였는가(결정적 안전망) ────────────────────────────

_PAGE = ["일본은행 다카다 심의위원의 도쿠시마 강연에는 새 발언이 없었고, 시장은 다음 주 다무라 심의위원의 발언을 기다린다.",
         "일본은행 우에다 총재는 기자회견에서 말했다."]


def test_roster_strong_needs_the_boj_in_the_same_paragraph():
    assert G.roster_strong(_PAGE) == {"高田創", "田村直樹", "植田和男"}
    assert G.roster_strong(["다무라 심의위원의 발언", "우에다 총재는 말했다."]) == frozenset()
    assert G.roster_strong(["우에다 가즈오 일본은행 총재", "고에다 일은 위원", "BOJ 히미노 부총재"]) == {
        "植田和男", "小枝淳子", "氷見野良三"}
    # 문단 어딘가의 「위원」「총재」로는 안 된다 — 직함이 그 성에 붙어야 하고 그 사람의 직함이어야 한다
    assert G.roster_strong(["일본은행 발표 뒤 상선미쓰이의 다무라 조타로 사장은 정책위원 발언을 짚었다.",
                            "일본은행 우에다 부총재", "일본은행 히미노 총재", "일본은행 다무라 위원장"]) == frozenset()


_S = frozenset({"高田創", "田村直樹", "植田和男"})


@pytest.mark.parametrize("ko,ja,strong,want", [
    # 일본은행을 말한 문단에서 직함과 붙었다 — 통과
    (_PAGE[0], "日銀の高田審議委員の徳島講演に新味はなく、市場は来週の田村審議委員の発言を待つ。", frozenset(), []),
    ("일본은행 다카다 하지메 심의위원의 도쿠시마 강연", "日銀の高田創審議委員の徳島講演", frozenset(), []),
    ("⟦a⟧일본은행⟦/a⟧ 다무라 나오키 심의위원", "⟦a⟧日銀⟦/a⟧の田村直樹審議委員", frozenset(), []),
    # 직함만 붙었다 — 문장 머리이고, 그 글의 다른 문단이 그 사람을 일본은행과 묶었을 때만 통과
    ("단기금리는 1.232%다. 이날 다무라 위원은 반대했다.", "短期金利は1.232%だ。この日、田村委員は反対した。", _S, []),
    ("상선미쓰이 다무라 위원이 발언했다.", "商船三井の田村委員が発言した。", _S, ["다무라"]),          # 4회차 codex
    ("시장은 다음 주 다무라 심의위원의 발언을 기다린다.", "市場は来週の田村審議委員の発言を待つ。", _S, ["다무라"]),
    ("우에다 총재는 금리를 올렸다.", "植田総裁は利上げした。", _S, []),
    ("우에다 총재는 금리를 올렸다.", "植田総裁は利上げした。", frozenset(), ["우에다"]),
    ("다무라 위원은 반대했다.", "田村委員は反対した。", _S, []),
    # 별칭은 일본은행을 말한 문단에서만
    ("다카다 심의위원은 말했다.", "高田審議委員は述べた。", _S, ["다카다"]),
    ("다카타 심의위원은 말했다.", "高田審議委員は述べた。", _S, []),
    # 같은 성의 다른 사람 — 걸린다
    ("상선미쓰이의 다무라 조타로 사장은 9일 회견에서 말했다.", "商船三井の田村ジョウタロウ社長は9日の会見で述べた。", _S, ["다무라"]),
    ("일본은행 회의 뒤 상선미쓰이의 다무라 조타로 사장은 정책위원 발언을 짚었다.", "日銀会合後、商船三井の田村社長は…", _S, ["다무라"]),
    ("다무라 조타로 사장을 田村直樹 로 옮겼다.", "田村直樹社長は述べた。", _S, ["다무라"]),
    ("우치다 가즈히토 이사장은 유가를 짚었다.", "内田カズヒト理事長は原油価格に触れた。", _S, ["우치다"]),
    ("사토 모토히로 히토쓰바시대 교수의 인터뷰", "佐藤モトヒロ一橋大教授のインタビュー", _S, ["사토"]),
    # 한 문단에 두 사람 — 직함 없는 쪽이 있으면 걸린다
    ("일본은행 다무라 심의위원이 말한 날, 상선미쓰이의 다무라 사장도 회견했다.", "日銀の田村審議委員…商船三井の田村社長", _S, ["다무라"]),
    # 가나로 임시 표기했으면 한자를 붙인 것이 아니다
    ("상선미쓰이의 다무라 조타로 사장은 말했다.", "商船三井のタムラ・ジョウタロウ社長は述べた。", _S, []),
    # 한자가 있는데 한글에 그 사람이 없다
    ("위원 한 명이 강연했다.", "高田創審議委員が講演した。", _S, ["다카타"]),
    ("위원 한 명이 강연했다.", "田村日銀委員が講演した。", _S, ["다무라"]),
    # 성이 낱말 머리에 서면 뒤에 무엇이 붙든 사람으로 본다 — 조사 목록을 두지 않는다(3회차 codex)
    ("다무라밖에 없다", "田村しかいない", frozenset(), ["다무라"]),
    ("다무라야말로 적임이다", "田村こそ適任だ", _S, ["다무라"]),
    ("와리타 사토시 사장과 다카다공업은 말했다.", "割田サトシ社長と高田工業は述べた。", _S, ["다카다"]),   # 틀린 보류, 안전한 쪽
    ("와리타 사토시 사장은 말했다.", "割田サトシ社長は述べた。", _S, []),           # 일본어에 佐藤 가 없다
    # 한글에 그 성이 없는데 일본어에 명단 한자가 있다(5회차 codex)
    ("스즈키 사장", "佐藤社長", frozenset(), ["사토"]),
    ("마사토 사장은 말했다.", "佐藤社長は述べた。", _S, ["사토"]),
    # 2회차 codex: 조사가 붙은 두 번째 사람, 「위원장」, 자체 닫힘 자리표시
    ("일본은행 다무라 심의위원이 말했고 상선미쓰이의 다무라를 만났다", "日銀の田村委員が話し、商船三井の田村を訪ねた", frozenset(), ["다무라"]),
    ("다무라 위원은 반대했고 다무라로부터 들었다.", "田村委員は反対し、田村から聞いた。", _S, ["다무라"]),
    ("일본은행 다무라 위원장", "日銀の田村直樹委員長", frozenset(), ["다무라"]),
    ("일본은행 다무라 위원회", "日銀の田村委員会", frozenset(), ["다무라"]),
    ("상선미쓰이 대표⟦a/⟧가 말했다", "商船三井の田村⟦a/⟧直樹が述べた", frozenset(), ["다무라"]),
    ("일본은행 다무라⟦a/⟧ 심의위원이 말했다", "日銀の田村⟦a/⟧審議委員が述べた", frozenset(), []),
    ("일본은행 우에다 총재직", "日銀の植田総裁職", frozenset(), ["우에다"]),
    ("일본은행 다무라 심의위원을 만났다. 다무라 위원에게서 들었다.", "日銀の田村審議委員に会った。田村委員から聞いた。", frozenset(), []),
    # 6회차 codex: 정상 사람이 같은 문단에 있어도 맨 성·넘치는 횟수는 걸린다
    ("일본은행 사토 심의위원과 스즈키 사장이 만났다.", "日銀の佐藤審議委員と佐藤社長が会談した。", frozenset(), ["사토"]),
    ("일본은행 사토 심의위원과 스즈키 사장이 만났다.", "日銀の佐藤審議委員と佐藤委員が会談した。", frozenset(), ["사토"]),
    ("일본은행 사토 심의위원과 스즈키 사장이 만났다.", "日銀の佐藤審議委員とスズキ社長が会談した。", frozenset(), []),
    # 닫힌 꼴: 풀네임(+직함·氏), 성+그 사람의 직함, 성+氏
    ("일본은행 다무라 심의위원은 말했다.", "日銀の田村氏は述べた。", frozenset(), []),
    ("일본은행 다무라 심의위원은 말했다.", "日銀の田村直樹氏は述べた。", frozenset(), []),
    ("일본은행 다무라 심의위원은 말했다.", "日銀の田村は述べた。", frozenset(), ["다무라"]),
    ("일본은행 다무라 심의위원은 말했다.", "日銀の田村総裁は述べた。", frozenset(), ["다무라"]),      # 그 사람의 직함이 아니다
    ("일본은행 우에다 총재는 말했다.", "日銀の植田総裁選は近い。", frozenset(), ["우에다"]),
    # 한 글자 성 「増」
    ("크리스마스 수요가 늘었다.", "クリスマス需要が増加した。", _S, []),
    ("토마스 사장은 증산을 발표했다.", "トーマス社長は増産を発表した。", _S, []),
    ("결제액이 5% 늘었다.", "決済額が5%増え、増益となった。", _S, []),                          # 한글에 「마스」가 없다
    ("마스 사장이 발표했다", "増社長が発表した", frozenset(), ["마스"]),
    ("마스코 사장이 발표했다", "増社長が発表した", frozenset(), ["마스"]),                      # 4회차 codex
    ("마스터스 사장", "増社長", frozenset(), ["마스"]),                                         # 5회차 codex
    ("마스 에미 사장이 발표했다.", "増えみ社長が発表した。", frozenset(), ["마스"]),             # 6회차 codex
    ("마스 씨가 말했다", "増さんが述べた", frozenset(), ["마스"]),
    ("스즈키 심의위원", "増審議委員", frozenset(), ["마스"]),
    # 낱말 머리 「마스」가 있는 문단의 増 은 전부 센다 — 낱말 목록을 두지 않는다(틀린 보류, 드물다)
    ("마스터카드는 이익이 늘었다.", "マスターカードは増益だった。", _S, ["마스"]),
    ("마스터카드는 결제가 활발했다.", "マスターカードは決済が活発だった。", _S, []),
    ("일본은행 마스 가즈유키 심의위원", "日銀の増一行審議委員", frozenset(), []),
    ("마스 가즈유키 사장", "増一行社長", _S, ["마스"]),
])
def test_roster_misuse(ko, ja, strong, want):
    assert G.roster_misuse(ko, ja, strong) == want


def test_fixed_attr_closed_vocabulary():
    from scripts.fund import regime
    for st in regime.STATES + ("미판정",):
        assert G.fixed_attr("data-regime", st)
    assert G.fixed_attr("data-regime", "새 국면") is None
    assert G.fixed_attr("data-label", "강세") is None
    assert G.fixed("강세") is None                 # 본문의 「강세」는 여전히 모델 몫


# ── 1회차 codex 구현 검토 ─────────────────────────────────────────────────

def test_every_dictionary_and_attr_pair_passes_the_hard_gate():
    # A3 ③: 고정 번역도 기계 검사를 거친다 — 사전 자체가 막히면 그 사전을 쓰는 글이 전부 멈춘다
    from scripts.ja import gate as GT
    bad = []
    for ko, ja in list(G.DICT.items()) + [(k, v) for d in G.ATTR_VALUES.values() for k, v in d.items()]:
        bad += [(ko, ja, p.code) for p in GT.check_unit(ko, ja) if not p.soft]
        if G.fixed(ko) is not None:
            bad += [(ko, G.fixed(ko), p.code) for p in GT.check_unit(ko, G.fixed(ko)) if not p.soft]
    assert not bad


@pytest.mark.parametrize("ko,ja", [
    ("산업재", "資本財・サービス"),                                       # C1: GICS 「Industrials」
    ("2026년 10월 1일(목) 마감 기준", "2026年10月1日(木) 取引終了時点"),   # C7
    ("5거래일째", "5営業日目"),                                           # C2 은 안 받음 — 일본 시황 관용
])
def test_codex_r1_glossary_fixes(ko, ja):
    assert G.fixed(ko) == ja


def test_roster_checked_is_the_human_way_out():
    ko, ja = "와리타 사토시 사장과 다카다공업은 말했다.", "割田サトシ社長と高田工業は述べた。"
    assert G.roster_misuse(ko, ja, _S) == ["다카다"]
    assert G.roster_misuse(ko, ja, _S, checked=("高田",)) == []
    assert G.roster_misuse("상선미쓰이 다무라 위원", "商船三井の田村委員", _S, checked=("高田",)) == ["다무라"]
    fams = {m.family for m in G.BOJ_BOARD["members"]}
    for path, kanji in G.ROSTER_CHECKED.items():
        assert re.fullmatch(r"(?:posts|news|japan/daily)/\d{4}-\d{2}-\d{2}\.html", path) and set(kanji) <= fams


# codex 검토 2-6회차가 「잘못 통과한다」고 재현한 입력 전부 — 하나라도 `[]` 이면 그 구멍이 다시 열린 것이다.
CODEX_REPROS = [
    (2, "일본은행 다무라 심의위원이 말했고 상선미쓰이의 다무라를 만났다", "日銀の田村委員が話し、商船三井の田村を訪ねた", ()),
    (2, "일본은행 다무라 위원장", "日銀の田村直樹委員長", ()),
    (2, "상선미쓰이 대표⟦a/⟧가 말했다", "商船三井の田村⟦a/⟧直樹が述べた", ()),
    (3, "다무라밖에 없다", "田村しかいない", ()),
    (3, "다무라야말로 적임이다", "田村こそ適任だ", ()),
    (3, "마스 사장이 발표했다", "増社長が発表した", ()),
    (4, "마스코 사장이 발표했다", "増社長が発表した", ()),
    (4, "상선미쓰이 다무라 위원이 발언했다.", "商船三井の田村委員が発言した。", ("일본은행 다무라 심의위원이 발언했다.",)),
    (5, "마스터스 사장", "増社長", ()),
    (5, "스즈키 사장", "佐藤社長", ()),
    (6, "일본은행 사토 심의위원과 스즈키 사장이 만났다.", "日銀の佐藤審議委員と佐藤社長が会談した。", ()),
    (6, "마스 에미 사장이 발표했다.", "増えみ社長が発表した。", ()),
]


@pytest.mark.parametrize("rnd,ko,ja,other", CODEX_REPROS)
def test_every_codex_repro_is_held(rnd, ko, ja, other):
    assert G.roster_misuse(ko, ja, G.roster_strong(other)) != []
