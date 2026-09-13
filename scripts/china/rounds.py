"""예정 회차가 비었는지 본다 — 루틴이 조용히 죽은 것을 잡는 유일한 신호.

클라우드 루틴이 init 에서 죽으면(사용량 한도 등) **레포에 흔적이 0이다.** 2026-09-10 회차가
그렇게 죽었고 사흘 동안 아무도 몰랐다 — 수집 워크플로는 매일 커밋을 남기고 있어서 겉보기에는
멀쩡했다. 그 조합(수집 커밋은 있는데 포스트만 없다)이 이 실패의 지문이다.

**「최신 글이 며칠 전인가」로는 못 잡는다.** 그때 `china/posts/` 는 비어 있었다 — 기준점이
없는 상태가 정확히 그 상황이었다. 그래서 이력에서 거꾸로 세지 않고 **달력에서 회차를 먼저
계산한 뒤** 원장이 그 회차를 설명하는지 본다.

파일이 아니라 `curriculum_state.json` 의 `last_published` 를 본다. 원장이 발행의 주인이고
(`state.py` 머리말), 하루 늦은 수동 발행도 회차를 메운 것으로 읽어야 오경보가 안 난다.

**이건 게이트가 아니라 알림이다.** 매 세션 뜨는 한 줄이므로 오경보가 나면 사람이 곧 무시하게
된다 — 그래서 「정상적으로 멈춘 상태」(실라버스 소진)를 실패와 다르게 말하고, 판정이 애매하면
조용한 쪽을 고른다.
"""

import json
import os
import subprocess
from datetime import date, datetime, time, timedelta, timezone

from china import state as ST

KST = timezone(timedelta(hours=9))

# `0 2 * * 1,4` — 월·목 11:00 KST (2026-09-13 변경).
PUBLISH_WEEKDAYS = (0, 3)

# 회차 날짜를 이 시각 전에는 세지 않는다. 루틴은 11:00 에 깨어나 수집을 기다렸다가 쓰므로
# 한 시간 넘게 걸린다 — 도는 중에 「비었다」고 하면 매 회차 아침이 전부 오경보가 된다.
GRACE = time(14, 0)

# 이 주기의 첫 **예정** 회차. 그 전 날짜는 다른 주기(주간·3일)의 것이라 여기서 따지지
# 않는다. A01 은 09-13(일)에 손으로 냈다 — 예정 회차가 아니라 주기를 다시 세운 자리다.
FIRST_ROUND = date(2026, 9, 14)

LEDGER = 'china/data/curriculum_state.json'
SYLLABUS = 'china/data/syllabus.json'


def last_due_round(now):
    """`now`(KST) 기준으로 **이미 지나간** 가장 최근 회차. 없으면 None."""
    day = now.date()
    # `now` 는 KST 라 `.time()` 이 곧 벽시계다.
    if day.weekday() not in PUBLISH_WEEKDAYS or now.time() < GRACE:
        day -= timedelta(days=1)
        while day.weekday() not in PUBLISH_WEEKDAYS:
            day -= timedelta(days=1)
    return day if day >= FIRST_ROUND else None


def overdue(state, now=None):
    """비어 있는 회차 — `(회차, 마지막 발행)`. 밀린 게 없으면 None.

    `last_published` 가 날짜 꼴이 아니면 **비교하지 않고 밀린 것으로 본다.** 문자열 비교라
    `"9999-99-99"` 같은 값이 들어오면 영원히 「발행됨」으로 읽힌다(codex 지적 5).

    ponytail: 「가장 최근 회차」 하나만 본다. 09-14 를 놓치고 09-17 이 정상 발행되면 그
    사이에 세션을 안 연 사람에게 09-14 실패는 안 보인다. 진행 중인 장애를 잡는 게 목적이고
    스스로 나은 과거는 원장·plan.md 가 기록한다 — 빠진 회차 목록까지 필요해지면
    `completed[].date` 로 최근 N 회차를 훑는다.
    """
    now = now or datetime.now(KST)
    due = last_due_round(now)
    if due is None:
        return None
    last = state.get('last_published')
    if last is not None and not ST.valid_period(last):
        return due, None
    if last and last >= due.isoformat():
        return None
    return due, last


_WD = '월화수목금토일'
_TRIGGER = 'trig_01FC8hN3FGpYpXCRwr9rfuxH'


def note(state, syllabus=None, now=None):
    """훅 한 줄. 밀린 게 없으면 빈 문자열."""
    got = overdue(state, now)
    if got is None:
        return ''
    due, last = got
    when = f'{due} ({_WD[due.weekday()]})'

    # 실라버스 소진은 **정상 정지**다(`syllabus.py` fail-closed). 이걸 장애로 말하면
    # 승격 전까지 매 세션 같은 거짓 경고가 뜨고, 그때부터 이 줄은 아무도 안 읽는다.
    if syllabus is not None:
        try:
            if syllabus.next_lesson(ST.completed_ids(state)) is None:
                return (f'[중국] 실라버스가 소진됐다 — {when} 회차부터 발행이 멈춰 있다. '
                        '장애가 아니다. draft 승격은 사람이 한다.')
        except Exception:  # noqa: BLE001 — 알림이 원장 모양 때문에 죽지 않는다
            pass

    if last is None and state.get('last_published') is not None:
        return (f'[중국] 원장의 last_published 가 날짜가 아니다: '
                f'{state["last_published"]!r} — {when} 회차를 판정할 수 없다.')
    return (f'[중국] {when} 회차가 비었다 — 마지막 발행 {last or "없음"}. '
            f'루틴이 조용히 죽었을 수 있다: RemoteTrigger list_runs {_TRIGGER}.')


def ledger(root):
    """원장 — `origin/main` 판과 작업 폴더 판 중 **뒤에 있는 쪽**.

    훅은 내 로컬 세션에서 돈다. 발행은 클라우드가 `origin/main` 에 한다 — 작업 폴더만 보면
    며칠 안 받아 온 것만으로 매 세션 오경보다(codex 지적 1). fetch 는 하지 않는다: 세션 시작
    훅에서 네트워크를 타면 느리고, 같은 훅 묶음의 `review_gate.py` 가 이미 fetch 한다.

    ponytail: 뒤에 있는 쪽을 고르므로 「원장만 쓰고 커밋 전에 중단」은 조용히 지나간다
    (codex 지적 6). 그 창을 막으려면 포스트 파일의 원격 존재까지 봐야 하는데, 매 세션 도는
    알림에 `git cat-file` 을 더 얹을 값은 아니다.
    """
    seen = []
    out = subprocess.run(['git', '-C', root, 'show', f'origin/main:{LEDGER}'],
                         capture_output=True, text=True)
    if out.returncode == 0:
        seen.append(json.loads(out.stdout))
    path = os.path.join(root, LEDGER)
    if os.path.exists(path):
        with open(path) as fh:
            seen.append(json.load(fh))
    if not seen:
        raise FileNotFoundError(LEDGER)
    return max(seen, key=lambda s: s.get('last_published') or '')


if __name__ == '__main__':  # `PYTHONPATH=scripts python3 -m china.rounds` 로 부른다
    import sys

    from china import syllabus as SY

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        state = ledger(root)
        try:
            with open(os.path.join(root, SYLLABUS)) as fh:
                syl = SY.load(json.load(fh))
        except Exception:  # noqa: BLE001 — 실라버스를 못 읽어도 회차 판정은 선다
            syl = None
        line = note(state, syl)
    except Exception as exc:  # noqa: BLE001 — 훅에서 조용히 죽는 것이 최악이다
        line = f'[중국] 회차 확인 실패 — {type(exc).__name__}: {exc}'
    if line:
        print(line)
    sys.exit(0)
