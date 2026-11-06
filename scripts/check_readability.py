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

# 문장 길이는 2026-09-14 사용자 지시로 **발행을 막지 않는다** — 「문장 길이도 굳이 꼭
# 제약을 둘 필요는 없어」. 길이는 원인이 아니다: 긴 문장이 관계 하나면 읽히고, 짧은
# 문장이 관계 셋이면 안 읽힌다. 그래서 재서 보여 주기만 하고(`infos`) 막지 않는다.
#
# 지우지 않고 남겨 둔 이유는 회귀가 눈에 보여야 해서다. 게이트 도입 전 일간 28편은
# 2,591문장 중앙값 90자·P90 145자·최장 273자에 160자 초과가 129문장이었고, 도입 뒤
# 14편은 2,896문장 중앙값 54자·P90 93자에 160자 초과 0문장이었다. 그 129문장 가운데
# 58%는 수치가 넷 이하라 **수치 밀도 검사로는 잡히지 않는다** — 길이 검사를 없애면
# 그만큼이 아무 데도 안 걸린다(codex 설계 검토 2026-09-14).
LEN_INFO = 120
# 기사체로 가면서 넷 → 여섯으로 풀었다. 2026-11-06 부터는 여섯을 넘어도 막지 않는다 —
# 경제지표를 견주는 문장은 수치가 많을 수 있다. 읽기 어려우면 표로 옮기라는 참고다.
FIG_WARN, FIG_FAIL = 6, 8
H1_WARN, H1_FAIL = 80, 110
# 문체 참고(notes)는 **발행을 막지 않는다** — `--strict` 도 세지 않는다(2026-11-06 사용자 결정
# 「경고 문구가 아니라 발행 차단 조건을 바꿔야 한다」). 모든 발행 경로가 `--strict` 로 돌아
# 경고가 곧 반려였고, 반려를 피하려 자연스러운 문장을 고쳐 쓰는 것이 AI 문체를 만들었다.
# 막는 것은 조판이 깨지는 구조 문제뿐이다. 같은 수치 반복 검사는 이날 뺐다(핵심 수치는
# 논거라 되풀이될 수 있다).
# 헤드라인은 본문과 따로 센다. 2026-09-14 에 본문 임계를 넷 → 여섯으로 풀 때 이 검사가
# 같은 상수를 쓰고 있어서 제목 규칙까지 조용히 함께 풀렸다 — 계약은 그대로 「수치 넷
# 이내」다(`brief-report-writer.md` 구조 1번).
H1_FIG_WARN = 4


# 걸린 실행마다 한 번 찍는다. 작성자가 기준을 알려고 이 파일과 readability.py 를
# 읽지 않게 하려는 것이다(2026-09-22 KR 작성 에이전트가 수백 줄을 읽었다).
# 상수를 바꾸면 이 문장도 같이 바뀐다 — 값은 전부 위 상수에서 온다.
LEGEND = (
    "   기준 — 세는 대상: 본문 <p> 가운데 20자 넘는 문단의 문장. 표·차트, 그리고 caption·sub·"
    "muted·footer-note·source(s)·note·disclaimer·fed-trans 클래스 문단은 세지 않는다.\n"
    "        수치: 숫자 토큰(%%·bp·원·억원·조원·달러·엔·건·배 단위 포함). 연도·날짜·시각, "
    "「20일선·10년물·30분봉」 같은 기간 표기, 한 자리 수는 빼고 센다.\n"
    "        note(문체 참고): 문장당 수치 %d개 초과, 산문의 과잉 정밀(원 단위 소수·백만 이상 값의 소수)·"
    "천 단위+소수, 헤드라인 %d자 초과·수치 %d개 초과.\n"
    "        note 는 발행을 막지 않는다(--strict 도 세지 않는다) — 다시 읽어 보고, 자연스러우면 그대로 둔다.\n"
    "        FAIL 은 조판이 깨지는 구조 문제뿐이다: 섹션 경계를 넘는 div, 인라인 이미지(--no-inline-images), 조판 미적용."
    % (FIG_WARN, H1_WARN, H1_FIG_WARN))


def clip(s, n=90):
    return s if len(s) <= n else s[:n] + "…"


def audit(path, no_inline_images=False):
    html = Path(path).read_text(encoding="utf-8")
    m = R.measure(html)
    fails, warns, notes, infos = [], [], [], []

    # 헤드라인은 «전부» 본다. 첫 개만 보면 짧은 미끼 h1 을 앞에 두는 것으로
    # 길이·수치 검사를 통째로 피할 수 있다(발행본 78편은 전부 h1 이 하나다).
    for h1 in R.headings(html):
        if len(h1) > H1_WARN:
            notes.append("헤드라인 %d자 (%d자 넘음)" % (len(h1), H1_WARN))
        h1_figures = len(R.figures(h1))
        if h1_figures > H1_FIG_WARN:
            notes.append("헤드라인 수치 %d개 (%d개 넘음)" % (h1_figures, H1_FIG_WARN))

    for s, n in R.long_sentences(html, LEN_INFO):
        infos.append("%d자 문장 · %s" % (n, clip(s)))
    for s, n in R.dense_sentences(html, FIG_WARN):
        notes.append("수치 %d개 문장 (%d개 넘음 — 읽기 어려우면 표로) · %s" % (n, FIG_WARN, clip(s)))
    for tok in sorted(set(R.overprecise(html))):
        notes.append("산문 과잉 정밀 %s — 판정 경계 값이 아니면 반올림을 생각해 본다" % tok)
    for tok in sorted(set(R.loosely_precise(html))):
        notes.append("산문 소수점 %s — 호가가 아니면 반올림을 생각해 본다" % tok)

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
    return m, fails, warns, notes, infos


def main(argv):
    strict = "--strict" in argv
    no_inline = "--no-inline-images" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print("사용법: check_readability.py [--strict] [--no-inline-images] <파일…>")
        return 2
    bad = 0
    for p in paths:
        m, fails, warns, notes, infos = audit(p, no_inline_images=no_inline)
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
        for x in notes:
            print("   note %s" % x)
        # info 는 **종료 코드에 들어가지 않는다.** 여기를 warns 로 두면 모든 발행
        # 경로가 `--strict` 로 도는 탓에 경고 한 줄이 곧 발행 중단이 되고, 길이
        # 제약을 푼다는 변경이 아무것도 바꾸지 못한다(codex 검토 2026-09-14 치명).
        for x in infos[:5]:
            print("   info %s" % x)
        if len(infos) > 5:
            print("   info 길이 표시 %d건 중 5건만 출력 — 막지 않는다" % len(infos))
        if fails:
            print("   repair 섹션 div 짝 맞춤 → 인라인 이미지는 파일로 → apply_readability.py 재실행 후 재검사")
        if fails or warns or notes:
            print(LEGEND)
        if fails or (strict and warns):
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
