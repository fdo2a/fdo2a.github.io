"""무인 정정기의 숫자 출처 재검사(2026-11-28 「숫자는 코드가 채운다」 구역별 켜기 준비, KR 설계 §11.3 을 US 에도)."""
from pathlib import Path

from scripts.review import corrector
from scripts.review.queue import Pending


def _item(path, section='us'):
    return Pending(path, section, '0' * 40, 'new')


def test_gate_only_for_us_posts_on_or_after_the_switch(monkeypatch):
    from common import numsrc
    monkeypatch.setattr(numsrc, 'FILL_EFFECTIVE', '2026-12-01')
    args = ('/c/posts/x.html', Path('/e/data'), Path('/c'))
    assert corrector._number_sources_gate(_item('posts/2026-11-30.html'), *args) is None      # 스위치 전 — 지금과 같다
    assert corrector._number_sources_gate(_item('kr/posts/2026-12-02.html', 'kr'), *args) is None
    assert corrector._number_sources_gate(_item('news/2026-12-02.html', 'news'), *args) is None
    name, argv = corrector._number_sources_gate(_item('posts/2026-12-01.html'), *args)
    assert name == 'check_number_sources.py'
    assert argv == ['--market', 'us', '--date', '2026-12-01', '--html', '/c/posts/x.html', '--datadir', '/e/data',
                    '--repo', '/c', '--correction']
    assert name in corrector.VIOLATION_DIFF
    # 원본의 기존 위반은 줄 단위로 기록·비교한다 — 이름이 허용 목록에 없으면 원본 검사에서 바로 멈춘다(codex 구현 1회차 #4)
    assert name in corrector._ALL_GATES


def test_default_switch_off_adds_no_gate():
    assert corrector._number_sources_gate(_item('posts/2026-11-27.html'), 'p', Path('d'), Path('c')) is None


def test_violation_key_drops_sentence_and_summary_lines():
    """같은 문장의 다른 숫자를 고쳐도 남은 위반은 같은 열쇠다(codex 설계 2회차 #4). 집계·이력 줄은 비교하지 않는다."""
    before = ('number sources: 숫자 10개 = 자료로 확인 3\n  확인 불가(표식 없음): 7,263 — S&P 500은 시가\n  막는 판: 위반 1\n'
              '위반: 표식 없음 [세계 지수·업종] 145.39달러 — 엔비디아는 시가 151.94달러에서 145.39달러까지\n')
    after = ('number sources: 숫자 10개 = 자료로 확인 4\n  수정 이력: 확인 불가 — 첫 판이 없다\n  막는 판: 위반 1\n'
             '위반: 표식 없음 [세계 지수·업종] 145.39달러 — 엔비디아는 시가 151.95달러에서 145.39달러까지\n')
    k = corrector._violation_lines(before, 'check_number_sources.py')
    assert k == ['표식 없음 [세계 지수·업종] 145.39달러']
    assert k == corrector._violation_lines(after, 'check_number_sources.py')
    # 다른 게이트는 지금 그대로
    assert corrector._violation_lines('경고(문장): x\n[채권] 2Y — 데이터 4.477\n') == ['[채권] 2Y — 데이터 4.477']
