import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

# ── 1a 「자료 누락 차단」의 켠 뒤 판정을 시험하는 모듈 ─────────────────────────────────────────────
# `verification.inputs.EFFECTIVE` 가 None 인 동안 실제 판정은 1a 전과 같다. 아래 모듈은 켠 뒤의 판정(자료 없음 = 미완료,
# 2판 기록, 산출 범위 규칙, 재검사 경계)을 시험하므로 시험 전용 환경 변수로 스위치를 켠다 — 검사기가 하위 프로세스로
# 돌아 monkeypatch 가 닿지 않는다. 경계 날짜 `ENFORCE_FROM` 은 1a 시험들이 쓰던 2026-11-17 그대로다.
# 여기 없는 모듈은 전부 꺼진 채(= 운영과 같은 상태) 돈다.
ENFORCE_FROM = '2026-11-17'
ENFORCED_MODULES = frozenset((
    'test_checker_exit2', 'test_impl_review_r1', 'test_impl_review_r2', 'test_impl_review_r3',
    'test_input_mutations', 'test_inputs', 'test_inputs_policy', 'test_run_binding',
    'test_impl_review_r1_review', 'test_impl_review_r2_review',
    'test_impl_review_r4', 'test_impl_review_r5', 'test_macro_coverage',
))


@pytest.fixture(autouse=True)
def _input_health_switch(request, monkeypatch):
    name = request.module.__name__.rsplit('.', 1)[-1]
    if name in ENFORCED_MODULES or name.endswith('_1a'):
        monkeypatch.setenv('PREPUB_INPUTS_TEST_STRICT_FROM', ENFORCE_FROM)
        # 켠 뒤의 기록은 2판이다 — 알림 시험의 작은 레포도 2판 기록을 쓴다. 격리 사본용 날짜 사본도 같은 날로
        import review.corrector, review.style_pass, review.tests.prepub_fixture  # noqa: E401,F401
        for mod_name, mod in list(sys.modules.items()):      # `review.x` 와 `scripts.review.x` 두 이름으로 실릴 수 있다
            if mod_name.endswith('review.tests.prepub_fixture'):
                monkeypatch.setattr(mod, 'FORMAT', 'prepub-record/2')
            elif mod_name.endswith(('review.corrector', 'review.style_pass')):
                monkeypatch.setattr(mod, 'STRICT_FROM', ENFORCE_FROM)
    else:
        monkeypatch.delenv('PREPUB_INPUTS_TEST_STRICT_FROM', raising=False)
