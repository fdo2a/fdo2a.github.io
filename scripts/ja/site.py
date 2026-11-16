"""일본어 목록 페이지 — 한글 `index.html`·`japan/index.html` 에서 코드로 만든다.

    python3 -m scripts.ja.site           # ja/index.html, ja/japan/index.html 을 쓴다

순서: 한글 원본 → `prune`(일본어판에 없는 메뉴를 뺀다) → `extract.split` → 단위마다 `STRINGS`
→ `assemble.build`(lang·canonical·og·hreflang·상대 주소) → `finish`(언어 버튼·script 문자열).

한글판과 다른 점:
1. 메뉴바(`nav.menubar`)에서 `kr/`·`thesis/` 로 가는 `<a>` 와 「日本語」 링크(`a.lang`)를 뺀다 — `kr`·`thesis` 는
   정확히 한 개, 「日本語」는 0·1개여야 한다(원본 구조가 바뀌면 예외). 「日本語」가 없어도 되는 것은 첫 일본어 글이
   공개되기 전에 코드를 먼저 올리는 순서 때문이다. 뺀 뒤 문서 어디에도 `kr/`·`thesis/` 링크가 남으면 예외.
   서브탭(일간·주간·뉴스·산업)과 카드는 전부 일본어판이 있는 섹션이라 그대로 둔다. 바닥글의 소개·
   개인정보처리방침은 한글 페이지로 간다(`assemble.OUT_OF_JA_FILES`) — 글자에 「韓国語」를 붙인다.
2. 머리 언어 버튼: assemble 이 `<body>` 뒤에 다는 막대 대신, 한글판 「日本語」 자리(메뉴바 끝)에
   `gate.lang_button` 하나를 단다. 그 자리의 CSS(`.menubar a.lang`, 0·1개)는 `a.ja-lang` 으로 옮긴다.
3. 인라인 `<script>` 의 한글 문자열은 `SCRIPT_STRINGS`(통째 문자열, 긴 것부터)로 바꾸고, 한글이 든 `//`
   주석은 지운다. 그 뒤에 script 에 한글이 남으면 예외.
4. `STRINGS` 에 없는 한글 단위가 원본에 생기면 예외 — 한글 목록 페이지가 바뀌었는데 일본어판이
   조용히 낡는 일을 막는다. 고칠 때는 표에 한 줄을 더하고 다시 돌린다.
5. 로고만 Pretendard 로 되돌린다(`LIST_CSS`) — 머리 줄 높이가 한글판과 같게.

결과물(`ja/index.html`, `ja/japan/index.html`)은 레포에 파일로 둔다 — 한글 목록 페이지를 고치면
이 명령을 다시 돌려 함께 커밋한다(`test_site.py` 가 어긋남을 잡는다).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import assemble as A
from . import extract as X
from . import gate

SITE = "https://fdo2a.github.io/"

# 한글 원본 → (일본어판 경로 접미, 한글판 주소, 쓸 파일)
PAGES = {
    "index.html": ("", SITE, "ja/index.html"),
    "japan/index.html": ("japan/", SITE + "japan/", "ja/japan/index.html"),
}

_SEP = "\n    "

# 단위(한글) → 일본어. 자리표시(⟦a⟧…)는 원문과 같은 짝으로 둔다. 일본 증권사·경제 매체의 관용 표기.
STRINGS = {
    # ── 두 페이지 공통 ──
    f"⟦a⟧미국 시장⟦/a⟧{_SEP}⟦b⟧일본 시장⟦/b⟧": f"⟦a⟧米国市場⟦/a⟧{_SEP}⟦b⟧日本市場⟦/b⟧",
    "발행 주기": "発行頻度",
    "일간": "日次",
    "주간": "週次",
    "전체 보고서": "レポート一覧",
    "불러오는 중…": "読み込み中…",
    # ── index.html (미국 시장) ──
    "미국 증시 모닝브리프 아카이브 — 매일 아침(화–토) 지수·섹터, 국채 금리커브, FX, 원자재, 메모리/DRAM, "
    "AI 인프라, 경제지표를 애널리스트 관점으로 정리합니다.":
        "米国株式モーニングブリーフのアーカイブ — 毎朝（火〜土）、株価指数・セクター、米国債利回り曲線、為替、"
        "商品、メモリ/DRAM、AIインフラ、経済指標をアナリストの視点でまとめます。",
    "US Market Brief — 미국 증시 모닝브리프": "US Market Brief — 米国株式モーニングブリーフ",
    "매일 아침 전 거래일 미국 시장을 애널리스트 전략 관점으로 정리한 모닝브리프 아카이브":
        "前営業日の米国市場をアナリストの戦略視点でまとめたモーニングブリーフのアーカイブ",
    "미국 증시 모닝브리프 아카이브": "米国株式モーニングブリーフのアーカイブ",
    "미국 증시 마감 시황·모닝브리프 아카이브 | US Market Brief":
        "米国株式市況・モーニングブリーフ一覧 | US Market Brief",
    f"⟦a⟧US Market Brief⟦/a⟧{_SEP}⟦b⟧증시 전략 모닝브리프 아카이브⟦/b⟧":
        f"⟦a⟧US Market Brief⟦/a⟧{_SEP}⟦b⟧戦略モーニングブリーフ⟦/b⟧",
    "미국 증시가 열린 다음 날 아침(화–토 09:00 KST), 전 거래일의 시장을 정리한 모닝브리프가 자동으로 올라옵니다."
    f"{_SEP}⟦a⟧지수·섹터 · 채권 · FX · 원자재 · 매크로 · 경제지표 vs 컨센서스 — 뉴스와 메모리/DRAM · AI 인프라 · "
    "MLCC 는 「뉴스·산업」 탭⟦/a⟧":
        "米国市場の営業日の翌朝（火〜土 9:00 JST）、前営業日の市場をまとめたモーニングブリーフを掲載します。"
        "日本語版は韓国語版の翻訳のため、掲載が遅れることがあります。"
        f"{_SEP}⟦a⟧株価指数・セクター · 債券 · 為替 · 商品 · マクロ · 経済指標と市場予想 — ニュースとメモリ/DRAM · "
        "AIインフラ · MLCC は「ニュース・産業」タブ⟦/a⟧",
    "뉴스·산업": "ニュース・産業",
    "보고서 목록": "レポート一覧",
    "데이터: Yahoo Finance, FRED. 뉴스 코멘터리는 공개 보도 기반이며 주요 수치는 발행 전 교차 확인을 거칩니다.⟦a/⟧"
    f"{_SEP}본 자료는 정보 제공 목적으로 작성된 것으로, 특정 종목의 매수·매도 권유가 아닙니다.⟦b/⟧"
    f"{_SEP}⟦c⟧소개⟦/c⟧ · ⟦d⟧개인정보처리방침⟦/d⟧":
        "データ：Yahoo Finance、FRED。ニュースのコメントは公開報道に基づき、主要な数値は発行前にクロスチェックしています。⟦a/⟧"
        f"{_SEP}本資料は情報提供を目的として作成したものであり、特定銘柄の売買を推奨するものではありません。⟦b/⟧"
        f"{_SEP}⟦c⟧サイト紹介（韓国語）⟦/c⟧ · ⟦d⟧プライバシーポリシー（韓国語）⟦/d⟧",
    # ── japan/index.html (일본 시장) ──
    "일본 시장 리포트 — 도쿄 거래일 저녁의 마감브리프(주식·JGB·엔화·매크로·일본 경제 뉴스)와, "
    "BOJ·JGB·엔화·자금흐름으로 금리 정상화의 지속 가능성을 점검하는 주간 리포트.":
        "日本市場レポート — 東京市場の営業日夕方の大引けブリーフ（株式・JGB・円・マクロ・日本経済ニュース）と、"
        "BOJ・JGB・円・資金フローから金利正常化の持続性を点検する週次レポート。",
    "Japan Market — 일본 시장 일간·주간": "Japan Market — 日本市場 日次・週次",
    "도쿄 거래일 저녁의 일본 시장 마감브리프와 금리 정상화를 점검하는 주간 리포트":
        "東京市場の営業日夕方の日本市場大引けブリーフと、金利正常化を点検する週次レポート",
    "일본 시장 일간 마감브리프와 주간 리포트": "日本市場の日次大引けブリーフと週次レポート",
    "일본 시장 — 일간 마감·주간 점검 | Japan Market": "日本市場 — 日次マーケット・週次点検 | Japan Market",
    f"⟦a⟧Japan Market⟦/a⟧{_SEP}⟦b⟧일본 시장 일간·주간 리포트 아카이브⟦/b⟧":
        f"⟦a⟧Japan Market⟦/a⟧{_SEP}⟦b⟧日次・週次レポート⟦/b⟧",
    "도쿄 거래일 저녁에는 그날의 주식·JGB·엔화·매크로·일본 경제 뉴스를 마감브리프로, 매주 한 번은 일본이 금리 "
    "정상화를 계속할 수 있는지를 BOJ → JGB → 엔화·자금흐름 → 일본 기업의 순서로 점검합니다."
    f"{_SEP}⟦a⟧일간: 닛케이 225 · TOPIX-17 업종 · JGB · 콜금리 · 엔(16:30 JST) · 일본은행 지표 · 경제 뉴스 "
    " |  주간: 미·일 금리차 · 해외채권 매매 · 엔 투기 포지션⟦/a⟧":
        "東京市場の営業日の夕方にはその日の株式・JGB・円・マクロ・日本経済ニュースを大引けブリーフとして、"
        "週に一度は日本が金利正常化を続けられるかを BOJ → JGB → 円・資金フロー → 日本企業 の順に点検します。"
        "日本語版は韓国語版の翻訳のため、掲載が遅れることがあります。"
        f"{_SEP}⟦a⟧日次：日経平均 225 · TOPIX-17業種 · JGB · コールレート · 円（16:30 JST）· 日本銀行の指標 · 経済ニュース "
        " |  週次：日米金利差 · 対外債券売買 · 円の投機ポジション⟦/a⟧",
    "데이터: 일본경제신문사(닛케이 225 종가), 일본 재무성(JGB 금리·대외 증권투자), 일본은행 시계열 API, CFTC, FRED, "
    "Yahoo Finance, Yahoo!ファイナンス. 헤지 후 금리는 근사입니다.⟦a/⟧"
    f"{_SEP}⟦b⟧This service uses the API provided by the \"Bank of Japan Time-Series Data Search.\" "
    "The Bank of Japan does not guarantee the content of the service.⟦/b⟧⟦c/⟧"
    f"{_SEP}본 자료는 정보 제공 목적으로 작성된 것으로, 특정 종목의 매수·매도 권유가 아닙니다.⟦d/⟧"
    f"{_SEP}⟦e⟧소개⟦/e⟧ · ⟦f⟧개인정보처리방침⟦/f⟧":
        "データ：日本経済新聞社（日経平均株価の終値）、財務省（JGB金利・対外証券投資）、日本銀行 時系列統計データ API、"
        "CFTC、FRED、Yahoo Finance、Yahoo!ファイナンス。ヘッジ後利回りは近似値です。⟦a/⟧"
        f"{_SEP}⟦b⟧This service uses the API provided by the \"Bank of Japan Time-Series Data Search.\" "
        "The Bank of Japan does not guarantee the content of the service.⟦/b⟧⟦c/⟧"
        f"{_SEP}本資料は情報提供を目的として作成したものであり、特定銘柄の売買を推奨するものではありません。⟦d/⟧"
        f"{_SEP}⟦e⟧サイト紹介（韓国語）⟦/e⟧ · ⟦f⟧プライバシーポリシー（韓国語）⟦/f⟧",
}

# 인라인 script 의 한글 문자열 → 일본어. 통째 문자열만(따옴표·백틱 포함), 긴 것부터 바꾼다.
SCRIPT_STRINGS = {
    "['일','월','화','수','목','금','토']": "['日','月','火','水','木','金','土']",
    "'아직 올라온 보고서가 없습니다.'": "'まだレポートがありません。'",
    "'아직 발행된 주간 정리가 없습니다.'": "'まだ週次レポートがありません。'",
    "'아직 발행된 뉴스·산업 브리프가 없습니다.'": "'まだニュース・産業ブリーフがありません。'",
    "'아직 발행된 일간 마감브리프가 없습니다.'": "'まだ日次大引けブリーフがありません。'",
    "'아직 발행된 주간 리포트가 없습니다.'": "'まだ週次レポートがありません。'",
    "'<div class=\"empty\">불러오는 중…</div>'": "'<div class=\"empty\">読み込み中…</div>'",
    "'<div class=\"empty\">목록을 불러오지 못했습니다.<button type=\"button\" class=\"retry\">다시 시도</button></div>'":
        "'<div class=\"empty\">一覧を読み込めませんでした。<button type=\"button\" class=\"retry\">再試行</button></div>'",
    "'<div class=\"empty\">목록을 불러오지 못했습니다.</div>'": "'<div class=\"empty\">一覧を読み込めませんでした。</div>'",
    "`${y}년 ${+m}월`": "`${y}年${+m}月`",
    "`${y}년`": "`${y}年`",
    "${g.items.length}편": "${g.items.length}件",
}

_NAV = re.compile(r'<nav class="menubar">.*?</nav>', re.S)
_DROP = {   # 이름 → (꼴, 허용 개수)
    "kr": (re.compile(r'\n[ \t]*<a href="(?:\.\./)?kr/"[^>]*>[^<]*</a>'), (1,)),
    "thesis": (re.compile(r'\n[ \t]*<a href="(?:\.\./)?thesis/"[^>]*>[^<]*</a>'), (1,)),
    "lang": (re.compile(r'\n[ \t]*<a class="lang" href="[^"]*" hreflang="ja" lang="ja">日本語</a>'), (0, 1)),
}
_OUT_LINK = re.compile(r'href="(?:\.\./)*(?:kr|thesis)/')
_LANG_CSS = ".menubar a.lang {"
_SCRIPT = re.compile(r"(<script>)(.*?)(</script>)", re.S)
# 한글 `//` 주석 — 줄 전체(앞 줄바꿈까지)와, `;{}),` 뒤 꼬리 주석만. 문자열 안의 `//`(주소)는 건드리지 않는다.
_HANGUL_COMMENT = (re.compile(r"\n[ \t]*//[^\n'\"`]*[가-힣][^\n]*"),
                   re.compile(r"(?<=[;{}),])[ \t]+//[^\n'\"`]*[가-힣][^\n]*"))


# 로고(라틴 글자)는 한글판처럼 Pretendard 로 — ja-typography 가 본문 글꼴을 히라기노로 바꾸면 390px 에서
# 「US Market Brief」가 두 줄로 접힌다(2026-11-14 실측: 169px → 213px).
LIST_CSS = ('<style id="ja-list">html[lang="ja"] header.site .brand { font-family: '
            "'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, sans-serif; white-space: nowrap; }"
            '</style>\n')


class SiteError(ValueError):
    pass


def prune(src: str) -> str:
    """메뉴바에서 KR·thesis(정확히 한 개)·「日本語」(0·1개) 링크를 뺀다."""
    navs = _NAV.findall(src)
    if len(navs) != 1:
        raise SiteError(f"메뉴바 {len(navs)}개(1개여야 한다)")
    nav = navs[0]
    for name, (pat, allowed) in _DROP.items():
        n = len(pat.findall(nav))
        if n not in allowed:
            raise SiteError(f"메뉴바의 {name} 링크 {n}개({'·'.join(map(str, allowed))}개여야 한다)")
        nav = pat.sub("", nav)
    if "日本語" in src.replace(navs[0], nav, 1):
        raise SiteError("메뉴바 밖에 「日本語」가 남았다(메뉴바의 lang 링크 꼴이 바뀌었다)")
    out = src.replace(navs[0], nav, 1)
    left = _OUT_LINK.findall(out)
    if left:
        raise SiteError(f"일본어판에 없는 섹션으로 가는 링크가 남았다: {left}")
    return out


def texts_for(doc) -> dict:
    missing = [u.ko for u in doc.units if u.ko not in STRINGS]
    if missing:
        raise SiteError("대응표(STRINGS)에 없는 한글 단위 — 표에 더한다: " + " / ".join(repr(m) for m in missing))
    return {u.uid: STRINGS[u.ko] for u in doc.units}


def _script(body: str) -> str:
    for ko in sorted(SCRIPT_STRINGS, key=len, reverse=True):
        body = body.replace(ko, SCRIPT_STRINGS[ko])
    for pat in _HANGUL_COMMENT:
        body = pat.sub("", body)
    left = X.HANGUL.findall(body)
    if left:
        i = X.HANGUL.search(body).start()
        raise SiteError(f"script 에 한글 {len(left)}자가 남았다(SCRIPT_STRINGS 에 더한다): {body[max(0, i - 40):i + 20]!r}")
    return body


def finish(out: str, ko_url: str) -> str:
    """언어 버튼을 메뉴바 끝으로 옮기고, 인라인 script 의 한글을 바꾼다."""
    button = gate.lang_button(ko_url)
    bar = f'\n<div class="ja-lang-bar">{button}</div>'
    if out.count(bar) != 1:
        raise SiteError("assemble 의 언어 막대를 찾지 못했다")
    out = out.replace(bar, "", 1)
    navs = _NAV.findall(out)
    nav = navs[0]
    out = out.replace(nav, nav[:-len("</nav>")].rstrip() + f"\n    {button}\n  </nav>", 1)
    if out.count(_LANG_CSS) > 1:
        raise SiteError(f"언어 버튼 CSS({_LANG_CSS})가 {out.count(_LANG_CSS)}개다")
    out = out.replace(_LANG_CSS, ".menubar a.ja-lang {", 1)
    head = out.lower().find("</head>")
    out = out[:head] + LIST_CSS + out[head:]
    return _SCRIPT.sub(lambda m: m.group(1) + _script(m.group(2)) + m.group(3), out)


def build_page(src: str, rel: str) -> str:
    path, ko_url, _ = PAGES[rel]
    pruned = prune(src)
    doc = X.split(pruned)
    out = A.build(pruned, path, texts_for(doc), ko_url=ko_url)
    out = finish(out, ko_url)
    problems = gate.check_doc(out, src)
    if problems:
        raise SiteError(f"{rel}: " + "; ".join(f"{p.code} {p.detail}" for p in problems))
    return out


def build(root) -> dict:
    """{ja 경로: html}."""
    root = Path(root)
    return {dest: build_page((root / rel).read_text(encoding="utf-8"), rel)
            for rel, (_p, _k, dest) in PAGES.items()}


def write(root) -> list:
    root = Path(root)
    changed = []
    for rel, text in build(root).items():
        p = root / rel
        if p.exists() and p.read_text(encoding="utf-8") == text:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        changed.append(rel)
    return changed


def main():
    root = Path(__file__).resolve().parents[2]
    for rel in write(root):
        print(f"{rel} 갱신")


if __name__ == "__main__":
    main()
