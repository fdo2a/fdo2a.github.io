"""국채 커브 차트 — 미국·독일·일본을 한 축에 겹친다.

세 나라를 따로 그리면 「미국이 높다」는 사실이 안 보인다. 겹쳐 그려야 캐리와
환헤지 이야기가 그림 하나로 붙는다.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                        # noqa: E402
from matplotlib import font_manager                    # noqa: E402

YEARS = {'3M': 0.25, '6M': 0.5, '1Y': 1, '2Y': 2, '3Y': 3, '5Y': 5, '7Y': 7,
         '10Y': 10, '20Y': 20, '30Y': 30, '40Y': 40}

SERIES = [('us', '미국', '#0064FF'), ('de', '독일', '#00A85A'),
          ('jp', '일본', '#FF8A3D'), ('gb', '영국', '#8B5CF6'),
          ('kr', '한국', '#F04452')]


# 축·범례가 한글이다. macOS 로컬과 우분투 러너가 같은 코드로 그리므로 양쪽을 다 적는다
# — 러너에는 fonts-noto-cjk 가 깔린다(2026-09-01: 이 이름이 빠져 있어 두부로 렌더됐다).
FONT_CANDIDATES = ('Pretendard', 'Apple SD Gothic Neo', 'AppleGothic',
                   'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic')


def _font():
    for name in FONT_CANDIDATES:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            return name
        except Exception:                              # noqa: BLE001
            continue
    return None


def draw(curves, out_path, report_date=''):
    fam = _font()
    if fam:
        plt.rcParams['font.family'] = fam
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
    drawn = 0
    for key, label, color in SERIES:
        node = (curves or {}).get(key) or {}
        pts = []
        for tenor, row in (node.get('tenors') or {}).items():
            y = YEARS.get(tenor)
            if y and row.get('level') is not None:
                pts.append((y, row['level'], tenor))
        if len(pts) < 2:
            continue
        pts.sort()
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker='o', ms=4,
                lw=2, color=color, label=label)
        ax.annotate(f'{pts[-1][1]:.2f}', (pts[-1][0], pts[-1][1]),
                    textcoords='offset points', xytext=(6, 0), fontsize=9,
                    color=color, fontweight='bold', va='center')
        drawn += 1

    ax.set_xscale('log')
    ax.set_xticks([0.25, 1, 2, 5, 10, 30])
    ax.set_xticklabels(['3M', '1Y', '2Y', '5Y', '10Y', '30Y'])
    ax.set_ylabel('수익률 (%)', fontsize=10)
    ax.grid(alpha=0.25, lw=0.7)
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, fontsize=10, loc='lower right', ncols=drawn or 1)
    ax.set_title(f'국채 수익률 곡선 — {report_date}', fontsize=12, fontweight='bold',
                 loc='left', color='#191F28')
    fig.tight_layout()
    fig.savefig(out_path, facecolor='white')
    plt.close(fig)
    return out_path
