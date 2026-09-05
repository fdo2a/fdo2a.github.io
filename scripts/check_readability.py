#!/usr/bin/env python3
"""산문 가독성 게이트 — 문장이 길어지고 수치가 뭉치는 것을 발행 전에 잡는다.

2026-08-24 실측(최근 US·KR 10편, 문장 1,249개): 중앙값 88자, P90 147자,
문장당 수치 중앙값 3개·P90 8개. 한 문장에 수치 여덟 개가 들어가면 문장이
아니라 표다. 임계는 그 분포의 상위 10%를 겨냥해 잡았다.

    python3 scripts/check_readability.py posts/2026-08-21.html
    python3 scripts/check_readability.py --strict posts/2026-08-21.html
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.us import readability as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

LEN_WARN, LEN_FAIL = 120, 160
# 작성 계약은 문장당 수치 넷까지다. 다섯째부터 경고, 일곱째부터 실패다.
FIG_WARN, FIG_FAIL = 4, 6
ECHO_LIMIT = 3
H1_WARN, H1_FAIL = 80, 110


def clip(s, n=90):
    return s if len(s) <= n else s[:n] + "…"


def audit(path, no_inline_images=False):
    html = Path(path).read_text(encoding="utf-8")
    m = R.measure(html)
    fails, warns = [], []

    h1 = R.first_heading(html)
    if h1:
        if len(h1) > H1_FAIL:
            fails.append("헤드라인 %d자 · 110자 초과" % len(h1))
        elif len(h1) > H1_WARN:
            warns.append("헤드라인 %d자 · 80자 안으로 줄일 것" % len(h1))
        h1_figures = len(R.figures(h1))
        if h1_figures > FIG_WARN:
            warns.append("헤드라인 수치 %d개 · 넷 이하로 줄일 것" % h1_figures)

    for s, n in R.long_sentences(html, LEN_WARN):
        (fails if n > LEN_FAIL else warns).append("%d자 문장 · %s" % (n, clip(s)))
    for s, n in R.dense_sentences(html, FIG_WARN):
        (fails if n > FIG_FAIL else warns).append("수치 %d개 문장 · %s" % (n, clip(s)))
    for tok in sorted(set(R.overprecise(html))):
        fails.append("산문 과잉 정밀 %s — 반올림할 것" % tok)
    for tok in sorted(set(R.loosely_precise(html))):
        warns.append("산문 소수점 %s — 호가가 아니면 반올림" % tok)
    for tok, n in R.echoed_figures(html, ECHO_LIMIT):
        warns.append("같은 수치 %s가 산문에서 %d회 되풀이" % (tok, n))

    for sid, why in R.section_div_breaks(html):
        # 2026-09-03 발행본: §3이 div를 연 채 끝나고 §8에 짝 없는 </div>가 있어,
        # 남은 하나가 본문 컨테이너를 §8 끝에서 닫았다. §9부터 1120px 제한과
        # 좌우 여백을 잃어 「매크로 논리부터 폭이 넓어진다」로 보였다.
        fails.append("%s 섹션 경계를 넘는 div — %s" % (sid or "이름 없는", why))

    # 파이프라인별로 켠다. KR 은 수집기가 날짜별 차트 파일을 쓰기 전까지 임베드가
    # 유일한 아카이브 수단이라, 공통 게이트에서 무조건 켜면 발행이 막힌다.
    if no_inline_images:
        for mime, size, alt in R.inline_data_uris(html):
            fails.append(
                "base64 인라인 이미지 %s %,d자%s — 파일로 빼고 경로로 참조할 것"
                .replace("%,d", "%d") % (mime, size, " (%s)" % alt if alt else ""))

    if not R.has_override(html):
        fails.append("조판 오버라이드 미적용 — apply_readability.py를 돌릴 것")
    return m, fails, warns


def main(argv):
    strict = "--strict" in argv
    no_inline = "--no-inline-images" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print("사용법: check_readability.py [--strict] [--no-inline-images] <파일…>")
        return 2
    bad = 0
    for p in paths:
        m, fails, warns = audit(p, no_inline_images=no_inline)
        print("== %s" % p)
        # 문장이 없으면 `measure()` 는 개수만 돌려준다. 그것을 모르고 분포 키를
        # 인덱싱하던 판은 산문 없는 문서에서 KeyError 로 죽었고, 죽은 자리가
        # 요약 출력이라 **아래의 FAIL 이 한 줄도 찍히지 않았다** — 종료 코드만
        # 1 이라 「검사가 걸렀다」와 구별되지 않는다(2026-09-06).
        if m["sentences"]:
            print(
                "   문장 %d · 중앙 %d자 · P90 %d자 · 120자 초과 %d문장 · "
                "수치 중앙 %d개/P90 %d개 · 문단 P90 %d자"
                % (
                    m["sentences"], m["median_len"], m["p90_len"], m["over_120"],
                    m["median_figures"], m["p90_figures"], m["p90_para_len"],
                )
            )
        else:
            print("   산문 문단 없음 — 구조 검사만 돈다")
        for f in fails:
            print("   FAIL %s" % f)
        for w in warns:
            print("   warn %s" % w)
        if fails or warns:
            print(
                "   repair 헤드라인 압축 → 긴 문장 분리 → 정확값은 표로 이동 → "
                "산문 반올림 → 반복 수치 제거 후 재검사"
            )
        if fails or (strict and warns):
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
