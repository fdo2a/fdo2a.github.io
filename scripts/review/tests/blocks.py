"""테스트가 쓰는 실제 조판 블록 두 종 — 등록된 것만 조판으로 인정되므로 지어내면 안 된다."""

from review.known_blocks import _PREV_V5 as PREV  # noqa: E402,F401
from us.readability import CSS as _CSS  # noqa: E402

CUR = _CSS.strip('\n')
