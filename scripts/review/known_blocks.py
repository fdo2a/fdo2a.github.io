"""발행본에 실제로 실려 있는 조판 블록들.

**등록되지 않은 블록은 조판으로 인정하지 않는다.** 검토 게이트가 「마커부터 `</style>`까지」를
무조건 들어내던 시절에는, 마커 뒤에 `html, body { display:none !important; }` 한 줄을 넣어도
지문이 움직이지 않았다(2026-09-04 codex 검토가 실제 발행본으로 재현). 지우는 규칙은 무엇이
지워지는지를 보지 않기 때문이다. 그래서 «무엇이 지워져도 되는가»를 여기 적어 둔다.

현재 판은 `us.readability.CSS` 에서 자동으로 가져온다 — 조판 도구가 지금 낼 수 있는 것은
정의상 조판이다. **과거 판만 손으로 적는다.** 발행본 75편의 블록은 2종뿐이고(2026-09-04 실측)
그중 하나가 아래다 — 현재 판에서 `.box-label, .p-label { break-after… }` 한 줄이 빠진 직전 판.

새 블록을 만나면 `refresh` 가 해시를 찍고 멈춘다. 등록은 `mark` 와 같은 «사람의 명시적
행위»다 — 자동으로 늘어나면 이 파일은 아무것도 막지 못한다.
"""

from us.readability import CSS as _CURRENT  # noqa: E402

# 2026-08-26 ~ 08-28 발행분 58편이 들고 있는 판.
_PREV_V5 = '/* readability-v5 */\n.card p, .doc p, .panel p, p { line-height: 1.78; margin: 0 0 15px; max-width: 42em; }\n.card p:last-child, .doc p:last-child, .panel p:last-child, p:last-child { margin-bottom: 0; }\n.card { padding: 20px 22px; }\nh1 { max-width: 34em; }\nh2 { line-height: 1.45; margin-bottom: 14px; }\nh3, h4 { line-height: 1.45; }\n.caption, .sub, .footer-note, .note, .lead, li { max-width: 42em; }\ntable { font-variant-numeric: tabular-nums; }\nsection { scroll-margin-top: 20px; }\n.reading-map { display: flex; align-items: center; gap: 8px; overflow-x: auto;\n  margin: -2px 0 20px; padding: 10px 2px 4px; scrollbar-width: none; }\n.reading-map::-webkit-scrollbar { display: none; }\n.reading-map-label { flex: 0 0 auto; color: #8B95A1; font-size: 12px; font-weight: 700; }\n.reading-map a { flex: 0 0 auto; color: #4E5968; background: #fff; border: 1px solid #E5E8EB;\n  border-radius: 9999px; padding: 6px 11px; font-size: 12.5px; font-weight: 700;\n  line-height: 1.2; text-decoration: none; }\n.reading-map a:first-of-type { color: #0064FF; border-color: #B9D5FF; background: #F5F9FF; }\n.reading-map a:focus-visible { outline: 2px solid #0064FF; outline-offset: 2px; }\n@media (max-width: 560px) {\n  .card p, .doc p, .panel p, p { line-height: 1.72; margin-bottom: 13px; }\n  .card { padding: 16px 16px; }\n  .reading-map { margin-bottom: 16px; }\n}\n.box-label { display: block; width: fit-content; margin-bottom: 6px; }\n.p-label { display: block; margin-bottom: 2px; }\n\n@media (min-width: 1024px) {\n  .card p, .doc p, .panel p, p,\n  .caption, .sub, .footer-note, .note, .lead, li { max-width: none; }\n  .card p:not([class]), .doc p:not([class]), .panel p:not([class]), p:not([class]),\n  .doc li { font-size: 17px; line-height: 1.8; }\n  h1 { font-size: 25px; max-width: 30em; }\n  h2 { font-size: 20px; }\n  h3 { font-size: 17px; }\n}\n'


def known():
    """조판으로 인정하는 블록들. 앞뒤 빈 줄은 무시하고 비교한다."""
    return {block.strip('\n') for block in (_CURRENT, _PREV_V5)}


def is_known(block):
    return block is not None and block.strip('\n') in known()
