"""chart — 수익률 곡선 일본어판. 한글판 그림이 바뀌지 않는지, 입력을 같은 값으로 되살리는지, 글자가 깨지지 않는지."""
import json
import subprocess
import warnings

import pytest

from scripts.ja import chart as C
from scripts.ja.tests.corpus import ROOT

matplotlib = pytest.importorskip("matplotlib")
render_curve = C._render_curve()          # chart 가 scripts/ 를 sys.path 에 넣고 수집기를 불러온다
import collect_market_data as cmd  # noqa: E402


# `git show fc624579:scripts/collect_market_data.py` 의 render_curve, 이름만 바꿔 그대로(2026-11-14).
# labels·fonts 인자를 더하기 전의 한글판 — 기본 호출이 이것과 같은 바이트를 내야 한다.
def original_render_curve(yields, path):
    """Toss-style curve chart. Palette #0064FF/#D97706 is CVD-validated; dashes are the
    secondary encoding — do not change colors."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ['Noto Sans CJK KR', 'NanumGothic', 'Pretendard', 'Apple SD Gothic Neo']:
        if any(f.lower() in x.name.lower() for x in font_manager.fontManager.ttflist):
            plt.rcParams['font.family'] = f
            break
    plt.rcParams['axes.unicode_minus'] = False
    INK, INK2, MUTED, GRID = '#191F28', '#4E5968', '#8B95A1', '#F2F4F6'
    BLUE, AMBER = '#0064FF', '#D97706'
    labels = ['2Y', '5Y', '10Y', '30Y']
    today = [yields[t]['level'] for t in labels]
    week_ago = [yields[t]['week_ago'] for t in labels]
    t_date, w_date = yields['10Y']['date'], yields['10Y']['week_ago_date']
    # 2Y comes from FRED (T-1) while 5Y/10Y/30Y are same-day Yahoo spot, so a point on this
    # curve can be as of a different date than its neighbours. Star it rather than hide it.
    odd = [t for t in labels if yields[t].get('date') != t_date]
    x = range(4)
    fig, ax = plt.subplots(figsize=(7.4, 3.4), dpi=200)
    fig.patch.set_facecolor('white'); ax.set_facecolor('white')
    ax.plot(x, week_ago, '--', color=AMBER, linewidth=2, marker='o', markersize=7,
            markerfacecolor='white', markeredgecolor=AMBER, markeredgewidth=2, zorder=2)
    ax.plot(x, today, '-', color=BLUE, linewidth=2.4, marker='o', markersize=8,
            markerfacecolor=BLUE, markeredgecolor='white', markeredgewidth=2, zorder=3)
    for i, (t, w) in enumerate(zip(today, week_ago)):
        ax.annotate(f'{t:.2f}%', (i, t), textcoords='offset points', xytext=(0, 11),
                    ha='center', fontsize=10.5, fontweight='bold', color=INK)
        d = (t - w) * 100
        ax.annotate(f"{'+' if d > 0 else ''}{d:.0f}bp", (i, min(t, w)), textcoords='offset points',
                    xytext=(0, -20), ha='center', fontsize=9, color=MUTED)
    ax.annotate(f'오늘 ({t_date})', (3, today[3]), textcoords='offset points',
                xytext=(14, 4), fontsize=9.5, color=INK2, fontweight='bold')
    ax.annotate(f'1주 전 ({w_date})', (3, week_ago[3]), textcoords='offset points',
                xytext=(14, -12), fontsize=9.5, color=MUTED)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f'{t}*' if t in odd else t for t in labels], fontsize=11, color=INK2)
    if odd:
        note = ' · '.join(f"{t} {yields[t].get('source', '?')} {yields[t]['date']}" for t in odd)
        ax.text(0, -0.19, f'* {note} 기준 (그 외 Yahoo 스팟 {t_date})', transform=ax.transAxes,
                fontsize=8.5, color=MUTED)
    ax.tick_params(axis='y', labelsize=9.5, colors=MUTED, length=0)
    ax.tick_params(axis='x', length=0, pad=8)
    lo, hi = min(today + week_ago), max(today + week_ago)
    ax.set_ylim(lo - 0.22, hi + 0.22); ax.set_xlim(-0.35, 3.55)
    ax.yaxis.set_major_formatter(lambda v, _: f'{v:.1f}%')
    ax.grid(axis='y', color=GRID, linewidth=1); ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    plt.subplots_adjust(left=0.07, right=0.82, top=0.93, bottom=0.12)
    plt.savefig(path, facecolor='white', bbox_inches='tight')
    plt.close(fig)


def Y(today_date="2026-11-13", two_date=None, source="Naver"):
    rows = {"2Y": (4.874, 4.477), "5Y": (4.981, 4.608), "10Y": (5.153, 4.837), "30Y": (5.481, 5.251)}
    out = {}
    for t, (lv, wa) in rows.items():
        out[t] = {"level": lv, "date": today_date, "bp": 1.0, "week_ago": wa,
                  "week_ago_date": "2026-11-05", "source": source}
    if two_date:
        out["2Y"].update(date=two_date, source="FRED")
    return out


@pytest.mark.parametrize("yields", [Y(), Y(two_date="2026-11-12")], ids=["same-day", "starred-2Y"])
def test_default_call_is_byte_identical_to_the_original(tmp_path, yields):
    a, b, c = tmp_path / "orig.png", tmp_path / "new.png", tmp_path / "explicit.png"
    original_render_curve(json.loads(json.dumps(yields)), str(a))
    render_curve(json.loads(json.dumps(yields)), str(b))
    render_curve(json.loads(json.dumps(yields)), str(c), labels=dict(cmd.CURVE_LABELS_KO),
                 fonts=cmd.CURVE_FONTS_KO)
    assert a.read_bytes() == b.read_bytes() == c.read_bytes()


def test_japanese_labels_change_the_picture(tmp_path):
    a, b = tmp_path / "ko.png", tmp_path / "ja.png"
    render_curve(Y(two_date="2026-11-12"), str(a))
    render_curve(Y(two_date="2026-11-12"), str(b), labels=C.JA_LABELS, fonts=C.JA_FONTS)
    assert a.read_bytes() != b.read_bytes()


def test_no_korean_left_in_what_the_japanese_chart_draws():
    assert set(C.JA_LABELS) == set(cmd.CURVE_LABELS_KO)
    text = C.drawn_text(Y(two_date="2026-11-12"))
    assert "当日 (2026-11-13)" in text and "1週間前 (2026-11-05)" in text and "その他は" in text
    assert not any("가" <= ch <= "힣" for ch in text)


def _font():
    family, path = C.pick_font()
    if family is None:
        pytest.skip("일본어 글꼴(Hiragino 등)이 없다")
    return family, path


def test_hiragino_has_every_glyph_and_hangul_is_caught():
    _family, path = _font()
    assert C.missing_glyphs(C.drawn_text(Y(two_date="2026-11-12")), path) == []
    assert C.missing_glyphs("当日 한", path) == ["한"]


# ── 입력 되살리기: 임시 레포에 수집기 실행을 흉내 낸다 ──────────────────────────
def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def run(repo, report_date, yields, png=None, msg=None):
    """수집기 한 번 — json 은 늘 쓰고, PNG 는 주면 쓴다(같은 바이트면 git 에는 안 남는다)."""
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "market_data.json").write_text(
        json.dumps({"report_date": report_date, "generated": msg or report_date, "yields": yields}), encoding="utf-8")
    if png is not None:
        (repo / "data" / "yield_curve.png").write_bytes(png)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"data: market data for {report_date} {msg or ''}")


def publish(repo, date, png):
    (repo / "assets").mkdir(exist_ok=True)
    (repo / "assets" / f"yield_curve_{date}.png").write_bytes(png)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "site"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    return r


def test_restores_the_run_that_drew_the_published_picture(repo):
    run(repo, "2026-11-12", Y("2026-11-12"), b"P-early", "early")
    late = Y("2026-11-12")
    late["10Y"]["level"] = 5.2
    run(repo, "2026-11-12", late, b"P-late", "late")
    publish(repo, "2026-11-12", b"P-early")
    got, why = C.restore(repo, "2026-11-12")
    assert why is None and got["10Y"]["level"] == 5.153


def test_a_holiday_run_with_an_unchanged_picture_still_restores(repo):
    """11-11 실측 꼴: 값이 같아 PNG 가 같은 바이트 — git 에는 json 만 바뀐 커밋이 남는다."""
    run(repo, "2026-11-10", Y("2026-11-10"), b"P1")
    run(repo, "2026-11-11", Y("2026-11-10"), b"P1")
    publish(repo, "2026-11-11", b"P1")
    got, why = C.restore(repo, "2026-11-11")
    assert why is None and got["2Y"]["date"] == "2026-11-10"


def test_a_skipped_chart_run_is_not_used(repo):
    """1주 전 값이 빠져 수집기가 그림을 건너뛴 실행 — 트리의 PNG 는 앞 실행의 것이다."""
    run(repo, "2026-11-12", Y("2026-11-12"), b"P1")
    broken = Y("2026-11-13")
    broken["5Y"]["week_ago"] = None
    run(repo, "2026-11-13", broken)
    publish(repo, "2026-11-13", b"P1")
    got, why = C.restore(repo, "2026-11-13")
    assert got is None and "빠진 값" in why


def test_unknown_picture_or_conflicting_runs_give_none(repo):
    run(repo, "2026-11-12", Y("2026-11-12"), b"P1", "a")
    publish(repo, "2026-11-12", b"drawn-by-the-routine")
    got, why = C.restore(repo, "2026-11-12")
    assert got is None and "수집 커밋이 없다" in why
    other = Y("2026-11-12")
    other["30Y"]["level"] = 5.5
    run(repo, "2026-11-12", other, b"P1", "b")            # 다른 값인데 같은 그림 — 어느 쪽인지 모른다
    publish(repo, "2026-11-12", b"P1")
    got, why = C.restore(repo, "2026-11-12")
    assert got is None and "갈린다" in why
    assert C.restore(repo, "2026-11-30") == (None, "한글판 그림 assets/yield_curve_2026-11-30.png 이 없다")


def test_render_writes_the_japanese_png(repo, tmp_path):
    _font()
    run(repo, "2026-11-12", Y("2026-11-12", two_date="2026-11-10"), b"P1")
    publish(repo, "2026-11-12", b"P1")
    out = tmp_path / "out"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path, why = C.render_why(repo, "2026-11-12", dest_root=out)
    assert why is None and path == out / "ja/assets/yield_curve_2026-11-12.png"
    assert path.read_bytes().startswith(b"\x89PNG")
    assert not [w for w in caught if "missing from" in str(w.message)]
    assert C.render(repo, "2026-11-30", dest_root=out) is None


def test_render_refuses_a_label_the_font_cannot_draw(repo, tmp_path, monkeypatch):
    _font()
    run(repo, "2026-11-12", Y("2026-11-12"), b"P1")
    publish(repo, "2026-11-12", b"P1")
    monkeypatch.setattr(C, "JA_LABELS", {**C.JA_LABELS, "today": "오늘 ({date})"})
    path, why = C.render_why(repo, "2026-11-12", dest_root=tmp_path)
    assert path is None and "없는 글자" in why
    assert not (tmp_path / "ja/assets").exists() or not list((tmp_path / "ja/assets").iterdir())


def test_render_without_matplotlib(repo, monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    assert C.render_why(repo, "2026-11-12") == (None, "matplotlib 이 없다")


def test_blob_sha_matches_git():
    raw = (ROOT / "assets" / "yield_curve_2026-11-13.png").read_bytes()
    want = subprocess.run(["git", "hash-object", "--stdin"], input=raw, capture_output=True, check=True).stdout
    assert C.blob_sha(raw) == want.decode().strip()


def _shallow():
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],
                         capture_output=True, text=True)
    return out.stdout.strip() != "false"


def test_real_history_smoke():
    """이 레포: 2026-11-13 은 되살아나고, 루틴이 직접 그린 2026-07-10 은 안 된다(2026-11-14 실측 85/87)."""
    if _shallow():
        pytest.skip("얕은 클론 — 이력이 없다")
    got, why = C.restore(ROOT, "2026-11-13")
    assert why is None and set(got) == set(C.TENORS)
    assert C.restore(ROOT, "2026-07-10")[0] is None

