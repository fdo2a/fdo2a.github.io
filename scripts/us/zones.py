"""US 일간 숫자 구역 — 발행본 최상위 섹션(h2 제목)별 block|warn|exempt (2026-11-27, 숫자는 코드가 채운다 1차).

섹션 id(`read-N`)는 순번이라 구역을 가르지 못한다. 제목은 작성 지시문이 정한 고정 이름이라(`post_parts.LAYERS` 와 같은
목록) 앞부분 일치로 찾는다(「연준 이벤트 — …」). 설정: config/number_fill.json.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, 'config', 'number_fill.json')
MODES = ('block', 'warn', 'exempt')


class ConfigError(Exception):
    pass


def load(path=CONFIG):
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError) as e:
        raise ConfigError(f'config/number_fill.json 을 읽지 못했다: {e}')
    zones = d.get('zones')
    if d.get('default') not in MODES or not isinstance(zones, list) or \
            any(not isinstance(z, dict) or z.get('mode') not in MODES or not isinstance(z.get('title'), str)
                for z in zones):
        raise ConfigError('config/number_fill.json 꼴이 약속과 다르다')
    return d


def zone_of(cfg, title):
    """섹션 제목 → (구역 이름, 모드). 목록에 없으면 (제목, default)."""
    title = (title or '').strip()
    for z in sorted(cfg['zones'], key=lambda z: -len(z['title'])):
        if title.startswith(z['title']):
            return z.get('zone') or z['title'], z['mode']
    return title or '(제목 없음)', cfg['default']
