"""섹터 멀티기간 수익률(대표 ETF, yfinance) + 바 차트 스니펫.

ETF 매핑은 초기 세트. 유효성은 검증 스텝에서 확인하고, 무효 티커는
교체하거나 Naver 업종/테마 히스토리 폴백으로 대체(§10 열린 항목).
"""
import pandas as pd

# 다양한 섹터/테마 — 반도체·조선·방산 포함 (spec 사용자 지시)
SECTOR_ETFS = {
    "반도체": "091160.KS",       # KODEX 반도체
    "2차전지": "305720.KS",      # KODEX 2차전지산업
    "자동차": "091180.KS",       # KODEX 자동차
    "은행": "091170.KS",         # KODEX 은행
    "증권": "102970.KS",         # KODEX 증권
    "철강소재": "117680.KS",     # KODEX 철강
    "건설": "117700.KS",         # KODEX 건설
    "헬스케어": "266420.KS",     # KODEX 헬스케어
    "소프트웨어": "157490.KS",   # TIGER 소프트웨어
    "조선": "466920.KS",         # SOL 조선TOP3플러스
    "방산": "449450.KS",         # PLUS K방산
    "로봇": "445290.KS",         # KODEX K-로봇액티브
}

_HORIZONS = {"1D": 1, "1W": 5, "1M": 21, "6M": 126, "1Y": 252}


def multi_horizon_returns(prices: pd.Series):
    prices = prices.dropna()
    last = prices.iloc[-1] if len(prices) else None
    out = {}
    for label, back in _HORIZONS.items():
        if last is not None and len(prices) > back:
            prev = prices.iloc[-1 - back]
            out[label] = (last / prev - 1) * 100 if prev else None
        else:
            out[label] = None
    return out


def render_sector_html(sectors: list) -> str:
    """sectors: [{"name","ret":{horizon:pct},"leading":bool,"note":str}].
    미국판 sector_performance.html와 동일한 self-contained 막대 규격."""
    horizons = ["1D", "1W", "1M", "6M", "1Y"]
    blocks = []
    for h in horizons:
        rows = sorted(sectors, key=lambda s: -(s["ret"].get(h) if s["ret"].get(h) is not None else -999))
        bars = []
        for s in rows:
            v = s["ret"].get(h)
            if v is None:
                continue
            color = "#e5342b" if v < 0 else "#00a763"
            width = min(abs(v) * 4, 100)
            caution = "" if s.get("leading", True) or v <= 0 else ' title="좁은 상승·개별종목 주도"'
            bars.append(
                f'<div class="spf-block"><span class="spf-name">{s["name"]}</span>'
                f'<span class="spf-bar"{caution}><i style="width:{width:.0f}%;background:{color}"></i></span>'
                f'<span class="spf-val" style="color:{color}">{v:+.2f}%</span></div>')
        blocks.append(f'<div class="spf-col"><h4>{h}</h4>{"".join(bars)}</div>')
    css = ("<style>.spf-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}"
           ".spf-block{display:flex;align-items:center;gap:6px;margin:3px 0;font-size:12px}"
           ".spf-name{flex:0 0 72px}.spf-bar{flex:1;background:#f2f4f6;border-radius:4px;height:10px}"
           ".spf-bar i{display:block;height:10px;border-radius:4px}.spf-val{flex:0 0 52px;text-align:right}"
           ".spf-col h4{margin:0 0 6px;font-size:13px}"
           "@media(max-width:560px){.spf-grid{grid-template-columns:1fr}}</style>")
    return f'{css}<div class="spf-grid">{"".join(blocks)}</div>'
