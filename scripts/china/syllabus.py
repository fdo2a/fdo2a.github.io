"""실라버스 — 무엇을 어떤 순서로 배우는가.

이 파이프라인이 브리프와 다른 점은 «진도»가 있다는 것이다. 그날 시장이 무엇을 물었든
다음에 배울 것은 이미 정해져 있고, 선수 강의를 건너뛸 수 없다. 지방재정(A02)을 모르고
LGFV(A03)를 쓰면 글이 아니라 용어 나열이 된다.

로드 시점에 그래프를 통째로 검증한다 — 미지 prereq·자기참조·순환·중복 ID·중복 order·
fixed 가 draft 에 기대는 것·prereq 가 뒤 순서에 있는 것. 발행 도중에 발견하면 이미 늦다.

**draft 는 발행 대상이 아니다.** 승격은 사람이 커밋으로 한다. eligible fixed 가 없으면
`next_lesson()` 이 None 을 돌려주고 발행이 fail-closed 로 멈춘다 — 실라버스가 소진됐다는
사실을 조용히 넘기지 않기 위해서다.

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

from dataclasses import dataclass

STATUSES = ('fixed', 'draft')
TRACKS = ('structure', 'industry')


class SyllabusError(ValueError):
    """실라버스 자체가 깨졌다 — 발행이 아니라 레포가 잘못된 것이다."""


@dataclass
class Syllabus:
    lessons: list          # order 오름차순
    by_id: dict

    def get(self, lid):
        return self.by_id[lid]

    def next_lesson(self, completed):
        """다음에 발행할 강의 id. 없으면 None(실라버스 소진 또는 draft 만 남음)."""
        done = set(completed)
        for lesson in self.lessons:
            if lesson['id'] in done:
                continue
            if lesson['status'] != 'fixed':
                continue
            if not set(lesson['prereq']) <= done:
                continue
            return lesson['id']
        return None

    def eligible(self, completed):
        """지금 발행 가능한 fixed 강의 전부 — 진단·리포팅용."""
        done = set(completed)
        return [l['id'] for l in self.lessons
                if l['id'] not in done and l['status'] == 'fixed'
                and set(l['prereq']) <= done]


_REQUIRED_FIELDS = ('id', 'track', 'title', 'prereq', 'order', 'required_data',
                    'core_question', 'status')


def load(book):
    """dict(또는 파싱된 syllabus.json)를 검증해 Syllabus 로. 깨졌으면 SyllabusError."""
    lessons = book.get('lessons')
    if not isinstance(lessons, list) or not lessons:
        raise SyllabusError('lessons 가 비었다')

    by_id = {}
    orders = {}
    for lesson in lessons:
        missing = [f for f in _REQUIRED_FIELDS if f not in lesson]
        if missing:
            raise SyllabusError(f'{lesson.get("id", "?")}: 필드 누락 {missing}')
        lid = lesson['id']
        if lid in by_id:
            raise SyllabusError(f'강의 id 중복: {lid}')
        if lesson['status'] not in STATUSES:
            raise SyllabusError(f'{lid}: 알 수 없는 status {lesson["status"]!r}')
        if lesson['track'] not in TRACKS:
            raise SyllabusError(f'{lid}: 알 수 없는 track {lesson["track"]!r}')
        order = lesson['order']
        if not isinstance(order, int):
            raise SyllabusError(f'{lid}: order 가 정수가 아니다')
        if order in orders:
            raise SyllabusError(f'order 중복: {order} ({orders[order]}, {lid})')
        orders[order] = lid
        by_id[lid] = lesson

    for lid, lesson in by_id.items():
        for p in lesson['prereq']:
            if p == lid:
                raise SyllabusError(f'{lid}: prereq 가 자기 자신을 가리킨다')
            if p not in by_id:
                raise SyllabusError(f'{lid}: 알 수 없는 prereq {p}')

    # 순환을 order 검사보다 먼저 본다 — 순환은 반드시 order 도 어기므로, 뒤에 두면
    # 진짜 순환에 「order 가 뒤에 있다」는 엉뚱한 사인이 붙는다.
    _reject_cycles(by_id)

    for lid, lesson in by_id.items():
        for p in lesson['prereq']:
            # fixed 가 draft 에 기대면 그 강의는 영영 발행되지 않는다 — 조용히 막히는
            # 대신 로드 시점에 터뜨린다.
            if lesson['status'] == 'fixed' and by_id[p]['status'] != 'fixed':
                raise SyllabusError(f'{lid}(fixed) 가 draft 강의 {p} 에 기댄다')
            if by_id[p]['order'] >= lesson['order']:
                raise SyllabusError(
                    f'{lid}: prereq {p} 의 order 가 뒤에 있다 — 순서가 모순이다')

    return Syllabus(lessons=sorted(by_id.values(), key=lambda l: l['order']), by_id=by_id)


def _reject_cycles(by_id):
    """order 검사만으로도 대부분 걸리지만, 명시적으로 한 번 더 본다."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {lid: WHITE for lid in by_id}

    def visit(lid, path):
        color[lid] = GREY
        for p in by_id[lid]['prereq']:
            if color[p] == GREY:
                raise SyllabusError(f'prereq 순환: {" -> ".join(path + [lid, p])}')
            if color[p] == WHITE:
                visit(p, path + [lid])
        color[lid] = BLACK

    for lid in by_id:
        if color[lid] == WHITE:
            visit(lid, [])
