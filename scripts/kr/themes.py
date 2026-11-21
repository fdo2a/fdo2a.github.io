"""테마 등락률 랭킹. 테마 페이지 파싱은 소스 폐지(2026-09-17)로 2026-11-21 지웠다."""


def rank_themes(themes: list, top: int = 15) -> list:
    uniq = {t["name"]: t for t in themes}
    return sorted(uniq.values(), key=lambda x: -x["change_pct"])[:top]
