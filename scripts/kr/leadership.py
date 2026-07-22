"""섹터·테마의 '주도' 여부를 상승률과 유동성(거래대금) 교차로 판정.

상승률만 높고 거래대금이 뒷받침되지 않으면 주도가 아니라 저유동성 급등으로 본다.
"""
from statistics import median


def flag_leadership(items: list, ret_key: str = "ret", value_key: str = "value",
                    strong_note: str = "유동성 동반 주도",
                    weak_note: str = "저유동성 급등·개별이슈") -> list:
    """상승률(ret_key)과 확인지표(value_key: 거래대금 또는 breadth 등)를 교차해
    주도 여부를 판정. 확인지표가 중앙값 이상이어야 '주도'로 인정한다.
    strong_note/weak_note로 지표 성격(유동성/breadth)에 맞는 문구를 지정."""
    if not items:
        return []
    med = median([it.get(value_key, 0) for it in items])
    out = []
    for it in items:
        ret = it.get(ret_key, 0.0)
        val = it.get(value_key, 0)
        backed = val >= med
        leading = ret > 0 and backed
        if ret > 0 and not backed:
            note = weak_note
        elif leading:
            note = strong_note
        else:
            note = ""
        out.append({**it, "liquidity_backed": backed, "leading": leading, "note": note})
    return out
