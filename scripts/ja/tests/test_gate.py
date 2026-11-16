"""gate — 단위 검사와 문서 검사. 정상·오역 사례를 표로."""
import pytest

from scripts.ja import gate as GT
from scripts.common.analytics import MARKER


def codes(ko, ja, soft=None):
    return sorted({p.code for p in GT.check_unit(ko, ja) if soft is None or p.soft is soft})


OK = [
    ("엔비디아가 4.34% 내렸다.", "エヌビディアは4.34%下落した。"),
    ("시가총액 1조 2,000억 달러", "時価総額1兆2000億ドル"),              # 조·억 그대로, 쉼표는 지운다
    ("11월 12일 종가", "11月12日の終値"),
    ("-0.51%p 차이", "-0.51%ptの差"),
    ("1.1~2.5% 범위", "1.1～2.5%の範囲"),                                # 전각 물결
    ("9일째 하락", "9日目の下落"),
    ("하루 만에 되돌렸다", "一日で戻した"),                               # 한글 수사 → 한자 수사
    ("１２일", "12日"),                                                  # 전각 숫자는 NFKC 로 같다
    ("S&P 500은 0.35% 내렸다", "S&P 500は0.35%下落"),
    ("연준(Fed)이 MoM 0.3% 올렸다", "FRBは前月比0.3%上昇させた"),     # LATIN_MAP
    ("⟦a⟧엔비디아⟦/a⟧가 ⟦b⟧4%⟦/b⟧ 내렸다", "⟦a⟧エヌビディア⟦/a⟧は⟦b⟧4%⟦/b⟧下落"),
    ("⟦a⟧브로드컴⟦/a⟧과 ⟦b⟧AMD⟦/b⟧", "⟦b⟧AMD⟦/b⟧と⟦a⟧ブロードコム⟦/a⟧"),       # 형제 순서는 바뀌어도 된다
    ("윗줄⟦a/⟧아랫줄", "上の行⟦a/⟧下の行"),
]


@pytest.mark.parametrize("ko,ja", OK)
def test_ok(ko, ja):
    assert codes(ko, ja, soft=False) == []


BAD = [
    ("시가총액 1조 2,000억 달러", "時価総額1.2兆ドル", "number"),                # 조·억 환산
    ("11월 12일 종가", "11月13日の終値", "number"),
    ("4.34% 내렸다", "4.3%下落", "number"),
    ("하루 만에 되돌렸다", "1日で戻した", "number"),                              # 한글 수사를 아라비아 숫자로
    ("9일째 하락", "九日目の下落", "number"),                                      # 원문 숫자를 한자로
    ("엔비디아가 4.34% 내렸다.", "엔비디아は4.34%下落した。", "hangul"),
    ("⟦a⟧엔비디아⟦/a⟧가 내렸다", "エヌビディアは下落", "placeholder"),
    ("⟦a⟧엔비디아 ⟦b⟧CEO⟦/b⟧⟦/a⟧", "⟦a⟧エヌビディア⟦/a⟧⟦b⟧CEO⟦/b⟧", "placeholder"),   # 중첩이 바뀜
    ("⟦a⟧엔비디아⟦/a⟧", "⟦/a⟧エヌビディア⟦a⟧", "placeholder"),                    # 짝이 뒤집힘
    ("윗줄⟦a/⟧아랫줄", "上の行⟦a/⟧⟦a/⟧下の行", "placeholder"),
    ("VIX가 1.21p 올랐다", "ボラティリティ指数は1.21p上昇", "latin"),
    ("FOMC 의사록", "議事録", "latin"),
    ("엔비디아가 4.34% 내렸다.", "", "empty"),
    ("엔비디아가 4.34% 내렸다.", None, "empty"),
    ("엔비디아 이사회가 젠슨 황 CEO의 사임을 수리했다고 밝혔다", "CEO", "length"),
    ("엔비디아 이사회가 젠슨 황 CEO의 사임을 즉시 수리하고 콜레트 크레스 CFO를 임시 CEO로 세웠다.",
     "英伟达董事会立即接受黄仁勋CEO辞职并任命CFO为临时CEO。", "kana"),          # 중국어
]


@pytest.mark.parametrize("ko,ja,code", BAD)
def test_bad(ko, ja, code):
    assert code in codes(ko, ja, soft=False), GT.check_unit(ko, ja)


def test_s_and_p_spacing_is_a_number_issue_only_when_digits_change():
    # 공백만 붙인 것은 숫자 다중집합이 같다 — 차단하지 않는다(표기 차이는 검토가 본다)
    assert codes("S&P 500은 0.35% 내렸다", "S&P500は0.35%下落", soft=False) == []


def test_order_is_soft():
    ps = GT.check_unit("10년물 5.1%, 2년물 4.7%", "2年債4.7%、10年債5.1%")
    assert [(p.code, p.soft) for p in ps] == [("order", True)]


def test_kana_not_required_when_source_is_mostly_latin_or_numbers():
    # 494쌍 실측의 오차단 5건 유형: 출처 줄·일정 줄
    assert codes("출처: GuruFocus(TradingView 경유), Blockonomi, CNBC",
                 "出所:GuruFocus(TradingView経由)、Blockonomi、CNBC") == []
    assert codes("11월 19일 08:30 ET(11월 19일 22:30 KST) 신규 실업수당 청구.",
                 "11月19日 08:30 ET(11月19日 22:30 KST) 新規失業保険申請。") == []


def test_short_text_skips_length_and_kana():
    assert codes("종가", "終値") == []
    assert codes("엔비디아", "NVIDIA") == []     # 40자 미만이면 가나 검사 없음


# ── 문서 ──────────────────────────────────────────────────────────────────

def doc(body, lang="ja", marker=True):
    m = MARKER if marker else ""
    return f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>{m}</head><body>{body}</body></html>'


def test_check_doc_ok_with_language_button():
    btn = GT.lang_button("https://fdo2a.github.io/posts/2026-11-12.html")
    assert "한국어" in btn
    assert GT.check_doc(doc(btn + "<p>本文</p>"), doc("<p>본문</p>", "ko")) == []


@pytest.mark.parametrize("html,code", [
    (doc("<p>本文 한글</p>"), "hangul"),
    (doc("<style>/* 주석 */</style>"), "hangul"),
    (doc('<a href="x">한국어</a>'), "hangul"),            # 허용은 그 버튼 꼴만
    (doc("<p>⟦a⟧本文</p>"), "placeholder"),
    (doc("<p>本文</p>", lang="ko"), "lang"),
    (doc("<p>本文</p>", marker=False), "marker"),
    (doc("<p>本文</p>" + MARKER), "marker"),
])
def test_check_doc_problems(html, code):
    assert code in {p.code for p in GT.check_doc(html, doc("<p>본문</p>", "ko"))}


def test_marker_not_required_when_source_had_none():
    assert GT.check_doc(doc("<p>本文</p>", marker=False), doc("<p>본문</p>", "ko", marker=False)) == []


# ── 부호(soft) ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ko,ja", [
    ("-0.51%p 차이", "-0.51%ptの差"),
    ("-0.51%p 차이", "▲0.51%ptの差"),                       # 일본식 마이너스
    ("-0.51%p 차이", "マイナス0.51%ptの差"),
    ("-0.51%p 차이", "マイナス 0.51%ptの差"),                # 낱말 부호는 공백을 건너뛴다
    ("어드밴테스트(+2.08%)", "アドバンテスト(+2.08%)"),
    ("−1.5% 하락", "-1.5%下落"),                              # 원문 U+2212
    ("2026-11-13 기준", "2026-11-13基準"),                     # 날짜의 하이픈은 부호가 아니다
    ("1.2-1.5% 범위", "1.2-1.5%の範囲"),
    ("1.2-1.5% 범위", "1.2～1.5%の範囲"),                      # 범위 하이픈 → 물결
    ("전일 대비 -0.3%", "前日比-0.3%"),                        # 한자 뒤의 기호도 부호다
])
def test_sign_same(ko, ja):
    assert "sign" not in codes(ko, ja), GT.check_unit(ko, ja)


@pytest.mark.parametrize("ko,ja", [
    ("-0.51%p 차이", "0.51%ptの差"),                         # 부호를 잃음
    ("0.51%p 차이", "▲0.51%ptの差"),                         # 부호를 더함
    ("어드밴테스트(+2.08%)", "アドバンテスト(2.08%高)"),       # 말로 옮김 — 검토가 방향을 본다
    ("A -1.0%, B +1.0%", "A +1.0%、B -1.0%"),                 # 숫자별로 엇갈림
])
def test_sign_differs_is_soft(ko, ja):
    ps = [p for p in GT.check_unit(ko, ja) if p.code == "sign"]
    assert ps and all(p.soft for p in ps), GT.check_unit(ko, ja)
    assert codes(ko, ja, soft=False) == []


def test_sign_not_checked_when_numbers_differ():
    assert codes("-0.51% 하락", "0.5%下落") == ["number"]


# ── 1회차 codex 구현 검토 — 통화·라틴 경계·방향·인코딩된 한글 ─────────────

@pytest.mark.parametrize("ko,ja,code", [
    ("10억원", "10億円", "currency"),                           # A1 재현: 원 → 엔
    ("1,000만 달러", "1000万ウォン", "currency"),
    ("$100 선", "100円の水準", "currency"),
    ("7.1위안", "7.1ドル", "currency"),
    ("150엔", "150", "currency"),                               # 단위를 빠뜨림
    ("USD 강세", "USDT高", "latin"),                            # A1 재현: USD 가 USDT 안에 있어도 없다
])
def test_currency_and_latin_boundary_bad(ko, ja, code):
    assert code in codes(ko, ja, soft=False), GT.check_unit(ko, ja)


@pytest.mark.parametrize("ko,ja", [
    ("10억원", "10億ウォン"),
    ("10억 원", "10億ウォン"),
    ("1조 2,000억 달러", "1兆2000億ドル"),
    ("$100 선", "100ドルの水準"),
    ("$100 선", "$100の水準"),
    ("¥150", "150円"),
    ("150엔", "150円台"),
    ("7.1위안", "7.1人民元"),
    ("1,400원/달러", "1,400ウォン/ドル"),
    ("100엔당 원", "100円当たりウォン"),
    ("달러 강세가 이어졌다", "ドル高が続いた"),                  # 숫자에 붙지 않은 통화는 세지 않는다
    ("엔비디아가 4.34% 내렸다.", "エヌビディアは4.34%下落した。"),
    ("USD 강세", "USD高"),
    ("USD/JPY 150", "USD/JPY 150"),
])
def test_currency_and_latin_boundary_ok(ko, ja):
    assert codes(ko, ja, soft=False) == [], GT.check_unit(ko, ja)


def test_direction_is_a_flag_not_a_block():
    # A1 재현: 3.2% 상승 → 3.2%下落 은 숫자·부호가 같아 hard 로는 못 잡는다 — 검토자에게 표시
    assert codes("3.2% 상승", "3.2%下落", soft=False) == []
    assert GT.direction("3.2% 상승", "3.2%下落") is not None
    assert GT.direction("3.2% 상승", "3.2%上昇") is None
    assert GT.direction("0.5% 내렸다", "0.5%下げた") is None
    assert GT.direction("국면 설명", "局面の説明") is None


@pytest.mark.parametrize("html,code", [
    (doc("<p>&#54620;&#44544;</p>"), "hangul"),                 # A8 재현: 엔티티로 쓴 한글
    (doc("<p>&#xD55C;</p>"), "hangul"),
    (doc('<script type="application/ld+json">{"headline": "\\ud55c\\uae00"}</script>'), "hangul"),
    (doc('<script type="application/ld+json">{"headline": </script>'), "jsonld"),
])
def test_check_doc_decodes_entities_and_jsonld(html, code):
    assert code in {p.code for p in GT.check_doc(html, doc("<p>본문</p>", "ko"))}, GT.check_doc(html, "")


def test_check_doc_jsonld_ok():
    ld = '<script type="application/ld+json">{"headline": "\\u65e5\\u672c", "inLanguage": "ja"}</script>'
    assert GT.check_doc(doc(ld + "<p>&amp;本文</p>"), doc("<p>본문</p>", "ko")) == []


@pytest.mark.parametrize("ko,ja", [
    ("유로는 0.2% 오른 101.995, 유로/달러는 0.1%", "ユーロは0.2%上昇の101.995、ユーロ/ドルは0.1%"),
    ("1.1140, 달러지수는 0.3% 내렸다", "1.1140、ドル指数は0.3%下落"),
    ("157 엔/달러", "157 円/ドル"),
])
def test_number_before_a_currency_pair_or_index_is_not_an_amount(ko, ja):
    # 151편 실측에서 「숫자, 통화쌍」 이 금액으로 잡혔다 — 일본어가 단위를 안 붙이면 영영 막힌다
    assert GT.currencies(ko) == [] and "currency" not in codes(ko, ja, soft=False)


def test_currency_counts_per_currency():
    assert "currency" in codes("100달러와 200달러", "100ドルと200円", soft=False)
    assert "currency" in codes("100달러, 150엔", "100円, 150ドル", soft=False)       # 숫자별로도 본다
