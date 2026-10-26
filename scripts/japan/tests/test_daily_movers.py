"""일본 일간 움직인 종목 — 지수 기여 개념 없이 등락률만 (codex 설계 검토 #12)."""
import json

from common import movers as CM
from japan import daily_movers as DM

ROWS = [
    {'code': '7203', 'name': '도요타', 'change_pct': 0.4, 'close': 3117.0},
    {'code': '8035', 'name': '도쿄일렉트론', 'change_pct': -3.1, 'close': 9200.0},
    {'code': '6857', 'name': '어드밴테스트', 'change_pct': -6.2, 'close': 15000.0},
    {'code': '8306', 'name': '미쓰비시UFJ', 'change_pct': 2.5, 'close': 2100.0},
    {'code': '6758', 'name': '소니그룹', 'change_pct': 1.8, 'close': 4100.0},
    {'code': '9984', 'name': '소프트뱅크그룹', 'change_pct': None, 'close': None},
]


def test_universe_shape():
    codes = [u[0] for u in DM.UNIVERSE]
    assert len(codes) == len(set(codes)) and 30 <= len(codes) <= 50
    for code, name, sector in DM.UNIVERSE:
        assert code.isdigit() and name and sector in DM.SECTOR17.values()


def test_groups_without_market_cap():
    got = DM.build('2026-10-26', ROWS)
    assert got['groups'] and got['report_date'] == '2026-10-26'
    names = [m['name'] for g in got['groups'] for m in g['members']]
    assert '미쓰비시UFJ' in names and '어드밴테스트' in names and '도쿄일렉트론' in names
    assert '도요타' not in names


def test_same_sector_direction_grouped():
    got = DM.build('2026-10-26', ROWS)
    semis = [g for g in got['groups'] if g['industry'] == DM.SECTOR17['1625'] and g['direction'] == 'down']
    assert len(semis) == 1 and [m['name'] for m in semis[0]['members']] == ['어드밴테스트', '도쿄일렉트론']


def test_no_contribution_label():
    text = json.dumps(DM.build('2026-10-26', ROWS), ensure_ascii=False)
    assert '기여' not in text


def test_check_compatible():
    built = DM.build('2026-10-26', ROWS)
    paras = ''.join(f'<p data-mover="{g["id"]}">{g["members"][0]["name"]} '
                    f'{g["members"][0]["change_pct"]}% — 확인된 재료 없음</p>' for g in built['groups'])
    assert CM.check(paras, built, '2026-10-26') == []
    assert CM.check('<p>없음</p>', built, '2026-10-26')
