"""검토 게이트.

`scripts` 를 모듈 검색 경로에 한 번만 올린다. 하위 모듈이 저마다 `sys.path` 를 건드리면
경로가 절대·상대 두 벌로 쌓여 뒤의 import 를 가린다.
"""

import os
import sys

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
