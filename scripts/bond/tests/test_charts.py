"""커브 차트 — 축·범례가 한글이라 폰트 후보가 러너를 덮어야 한다.

2026-09-01 Actions 로그가 「Glyph 49688 missing from font(s) DejaVu Sans」를
쏟아냈다. 후보 목록이 macOS 폰트뿐이라 우분투 러너에서 전부 미스했고,
그림은 커밋되기 직전까지 두부(□)로 그려지고 있었다. 경고는 실패가 아니라서
게이트가 못 잡는다 — 그래서 여기서 잡는다.
"""

import warnings

import pytest

from bond import charts

CURVES = {'us': {'tenors': {'2Y': {'level': 3.6}, '10Y': {'level': 4.2},
                            '30Y': {'level': 4.8}}},
          'de': {'tenors': {'2Y': {'level': 2.0}, '10Y': {'level': 2.7}}}}


def test_font_candidates_cover_both_environments():
    # macOS 로컬과 우분투 러너가 같은 코드로 그린다. 한쪽만 적으면 다른 쪽이 두부다.
    assert 'Apple SD Gothic Neo' in charts.FONT_CANDIDATES
    assert 'Noto Sans CJK KR' in charts.FONT_CANDIDATES


def test_font_picks_noto_on_runner(monkeypatch):
    """fonts-noto-cjk 만 깔린 우분투에서 실제로 그 폰트가 뽑히는가."""
    def only_noto(name, fallback_to_default=False):
        if name.startswith('Noto Sans'):
            return '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
        raise ValueError(name)

    monkeypatch.setattr(charts.font_manager, 'findfont', only_noto)
    assert charts._font() == 'Noto Sans CJK KR'


def test_font_returns_none_when_nothing_installed(monkeypatch):
    """한글 폰트가 하나도 없으면 None — draw() 가 rcParams 를 건드리지 않는다."""
    def nothing(name, fallback_to_default=False):
        raise ValueError(name)

    monkeypatch.setattr(charts.font_manager, 'findfont', nothing)
    assert charts._font() is None


def test_render_emits_no_missing_glyph_warning(tmp_path):
    """실제로 그려 보고 글리프 누락 경고가 없는지 본다 — 후보 목록만 보면
    이름은 맞는데 렌더가 깨지는 경우를 놓친다."""
    if charts._font() is None:
        pytest.skip('이 환경에 한글 폰트가 없다 (러너에는 fonts-noto-cjk 가 깔린다)')

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        charts.draw(CURVES, str(tmp_path / 'curve.png'), '2026-09-01')

    missing = [str(w.message) for w in caught if 'missing from font' in str(w.message)]
    assert not missing, missing
