"""일봉 캔들 차트 렌더 — 코스피·코스닥·대장주. base64 PNG data URI 반환.

캔들 위에 이평선(20/60/120)·볼린저밴드(20±2σ)·일목 구름대(선행 26봉 시프트)를 오버레이한다.
지표는 2년치 히스토리로 계산한 뒤 마지막 표시 구간(기본 3개월)만 그린다 — MA120·일목
선행스팬2(52봉)+시프트(26봉)에 충분한 과거가 필요하기 때문. 색상은 문서 일관성을 위해
상승=녹색(#00a763)·하락=적색(#e5342b) (섹터 막대와 동일).
"""
import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd

# CJK 폰트 (macOS: Apple SD Gothic Neo/AppleGothic, Actions: Noto Sans CJK KR)
for _cand in ("Apple SD Gothic Neo", "AppleGothic", "Noto Sans CJK KR", "Noto Sans KR"):
    if any(_cand in f.name for f in fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _cand
        break
matplotlib.rcParams["axes.unicode_minus"] = False

UP, DOWN = "#00a763", "#e5342b"
MA_COLORS = {"ma20": "#F59E0B", "ma60": "#0064FF", "ma120": "#8B5CF6"}
DISPLAY_BARS = 63  # 약 3개월(거래일)


def _indicator_series(df: pd.DataFrame) -> pd.DataFrame:
    """전체 히스토리로 이평·볼린저·일목 선행스팬 시계열 계산(표시 전 슬라이스용)."""
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    out = pd.DataFrame(index=df.index)
    out["ma20"] = close.rolling(20).mean()
    out["ma60"] = close.rolling(60).mean()
    out["ma120"] = close.rolling(120).mean()
    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    out["bb_up"] = mid + 2 * std
    out["bb_lo"] = mid - 2 * std
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    out["span_a"] = ((tenkan + kijun) / 2).shift(26)
    out["span_b"] = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    return out


def _draw_candles(ax, df, ind, title):
    xs = list(range(len(df)))
    closes = df["Close"].tolist()

    # 일목 구름대 (span_a>=span_b → 양운/녹색, 아니면 음운/적색)
    sa, sb = ind["span_a"].tolist(), ind["span_b"].tolist()
    ax.fill_between(xs, sa, sb, where=[a >= b for a, b in zip(sa, sb)],
                    color=UP, alpha=0.10, linewidth=0, zorder=0, interpolate=True)
    ax.fill_between(xs, sa, sb, where=[a < b for a, b in zip(sa, sb)],
                    color=DOWN, alpha=0.09, linewidth=0, zorder=0, interpolate=True)

    # 볼린저밴드
    ax.plot(xs, ind["bb_up"].tolist(), color="#B0B8C1", linewidth=0.7, linestyle=(0, (4, 3)), zorder=1)
    ax.plot(xs, ind["bb_lo"].tolist(), color="#B0B8C1", linewidth=0.7, linestyle=(0, (4, 3)), zorder=1)

    # 캔들
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        color = UP if c >= o else DOWN
        ax.plot([i, i], [l, h], color=color, linewidth=0.6, zorder=3)
        body = abs(c - o) or (h - l) * 0.01 or 0.01
        ax.add_patch(plt.Rectangle((i - 0.3, min(o, c)), 0.6, body, color=color, zorder=4))

    # 이동평균선
    for key, col in MA_COLORS.items():
        ax.plot(xs, ind[key].tolist(), color=col, linewidth=1.0, zorder=5,
                label=key.upper().replace("MA", "MA"))

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
    ax.legend(loc="upper left", fontsize=6.2, frameon=False, ncol=3,
              handlelength=1.1, columnspacing=0.9, labelcolor="#6B7684")


def render_daily_charts(specs, period="2y", display_bars=DISPLAY_BARS):
    """specs: [(label, ticker), ...]. 2년치 일봉으로 지표 계산 후 마지막 구간만 2x2 캔들+오버레이.

    base64 data URI 반환.
    """
    import yfinance as yf
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.4), dpi=140)
    fig.patch.set_facecolor("white")
    for ax, (label, ticker) in zip(axes.flat, specs):
        df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        if len(df):
            ind = _indicator_series(df)
            df_d = df.tail(display_bars).reset_index(drop=True)
            ind_d = ind.tail(display_bars).reset_index(drop=True)
            _draw_candles(ax, df_d, ind_d, label)
        else:
            ax.set_title(f"{label} (데이터 없음)", fontsize=11)
            ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(pad=1.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
