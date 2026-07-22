"""일봉 캔들 차트 렌더 — 코스피·코스닥·대장주. base64 PNG data URI 반환.

색상은 문서 일관성을 위해 상승=녹색(#00a763)·하락=적색(#e5342b) (섹터 막대와 동일).
"""
import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# CJK 폰트 (macOS: Apple SD Gothic Neo/AppleGothic, Actions: Noto Sans CJK KR)
for _cand in ("Apple SD Gothic Neo", "AppleGothic", "Noto Sans CJK KR", "Noto Sans KR"):
    if any(_cand in f.name for f in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _cand
        break
matplotlib.rcParams["axes.unicode_minus"] = False

UP, DOWN = "#00a763", "#e5342b"


def _draw_candles(ax, df, title):
    closes = df["Close"].tolist()
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        color = UP if c >= o else DOWN
        ax.plot([i, i], [l, h], color=color, linewidth=0.6, zorder=1)
        body = abs(c - o) or (h - l) * 0.01 or 0.01
        ax.add_patch(plt.Rectangle((i - 0.3, min(o, c)), 0.6, body, color=color, zorder=2))
    last, first = closes[-1], closes[0]
    chg = (last / first - 1) * 100 if first else 0
    ax.set_title(f"{title}   {last:,.0f}", fontsize=11, fontweight="bold", loc="left")
    ax.text(0.99, 1.02, f"3개월 {chg:+.1f}%", transform=ax.transAxes, ha="right",
            fontsize=9, color=(UP if chg >= 0 else DOWN))
    ax.margins(x=0.01)
    ax.grid(axis="y", color="#EEF1F4", linewidth=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#E5E8EB")
    ax.tick_params(labelsize=8, colors="#8B95A1", length=0)
    ax.set_xticks([])


def render_daily_charts(specs, period="3mo"):
    """specs: [(label, ticker), ...]. yfinance 일봉으로 2x2 캔들, base64 data URI 반환."""
    import yfinance as yf
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.4), dpi=140)
    fig.patch.set_facecolor("white")
    for ax, (label, ticker) in zip(axes.flat, specs):
        df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        if len(df):
            _draw_candles(ax, df, label)
        else:
            ax.set_title(f"{label} (데이터 없음)", fontsize=11)
            ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(pad=1.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
