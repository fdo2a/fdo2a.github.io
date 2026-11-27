"""한국은행·일본은행 이벤트 칸의 의무 판정 — 「오늘 칸을 열어야 하는가」 (2026-11-27).

두 시장의 진단(diag)과 게이트가 **같은 함수**를 부른다. 판정에 쓰는 것은 셋뿐이다.

  · 수집기가 커밋한 `events.json` 의 행(원문을 받았는가 — `sources` 의 `ok:true`)
  · 손으로 채워 커밋한 일정 파일 `schedule.json`(결정일·각 문서의 공개 예정일, 기능을 켠 날 `start`)
  · 발행본 장부 `covered` — 발행일보다 앞선 날짜의 발행본에 찍힌 `data-cb-event="KEY"`

「다뤘는가」의 장부가 수집기가 아니라 발행본인 이유: 수집은 됐는데 그날 루틴이 한도로 빠지면(11/20 일본 일간)
수집기 기록만으로는 다음 발행일에 이벤트를 조용히 잃는다. 결정일의 의무가 수집기가 아니라 일정 파일에서
나오는 이유: 수집 step 이 시간 초과로 죽은 날은 실패 기록 자체가 없다(codex 설계 검토 4회차).
설계: docs/superpowers/specs/2026-11-27-central-bank-events.md
"""
import datetime as _dt
import glob
import os
import re
import subprocess

WINDOW_DAYS = 10

KINDS = {
    # kind: (라벨, 결정일 의무인가 — 원문을 못 받아도 칸을 요구한다)
    'bok_decision': ('통화정책방향 결정문', True),
    'bok_presser': ('총재 기자간담회', False),
    'bok_minutes': ('금통위 의사록', False),
    'boj_statement': ('금융정책 결정 공표문', True),
    'boj_outlook': ('경제·물가 정세의 전망(기본 견해)', False),
    'boj_presser': ('총재 정례 기자회견', False),
    'boj_opinions': ('결정회의 주요 의견', False),
    'boj_minutes': ('결정회의 의사요지', False),
}
# 위원 이름을 밝히지 않는 문서 — 인용 캡션에 「총재」를 화자로 쓰면 막는다
ANONYMOUS = frozenset(('bok_minutes', 'boj_opinions', 'boj_minutes'))
# 일정 파일의 회의 칸 이름 → kind
DOC_FIELDS = {
    'bok': (('decision', 'bok_decision'), ('presser', 'bok_presser'), ('minutes', 'bok_minutes')),
    'boj': (('statement', 'boj_statement'), ('outlook', 'boj_outlook'), ('presser', 'boj_presser'),
            ('opinions', 'boj_opinions'), ('minutes', 'boj_minutes')),
}

_MARK = re.compile(r'\bdata-cb-event\s*=\s*"([A-Za-z0-9_-]+)"', re.I)
_COMMENT = re.compile(r'<!--.*?--!?>', re.S)
_POST = re.compile(r'^(\d{4}-\d{2}-\d{2})\.html$')


class ScheduleError(Exception):
    """일정 파일을 읽을 수 없다 — 조용히 「이벤트 없음」으로 읽지 않는다."""


def event_key(kind, meeting_date):
    """파일 이름이자 발행본의 `data-cb-event` 키. 회의(마지막 날) 기준 — 의사록도 회의일 키, 공개일은 `date`."""
    return '%s-%s' % (kind.replace('_', '-'), str(meeting_date).replace('-', ''))


def label(kind):
    return KINDS.get(kind, (kind, False))[0]


def _day(value):
    try:
        return _dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def schedule_docs(schedule):
    """일정 파일 → [{key, kind, date, meeting_date}] (공개 예정일이 적힌 문서만). 꼴이 다르면 ScheduleError."""
    if not isinstance(schedule, dict) or schedule.get('bank') not in DOC_FIELDS \
            or not isinstance(schedule.get('meetings'), list) or _day(schedule.get('start')) is None:
        raise ScheduleError('일정 파일에 bank·start·meetings 가 없다')
    out = []
    for m in schedule['meetings']:
        meeting = m.get('meeting') if isinstance(m, dict) else None
        if _day(meeting) is None:
            raise ScheduleError(f'일정 파일의 회의 날짜를 읽을 수 없다: {m!r}')
        for field, kind in DOC_FIELDS[schedule['bank']]:
            d = m.get(field)
            if d is None:
                continue
            if _day(d) is None:
                raise ScheduleError(f'일정 파일 {meeting} 의 {field} 날짜를 읽을 수 없다: {d!r}')
            out.append({'key': event_key(kind, meeting), 'kind': kind, 'date': d, 'meeting_date': meeting})
    return out


def _in_window(date, d, start):
    day = _day(date)
    return day is not None and day <= d and (d - day).days <= WINDOW_DAYS and day >= start


def has_text(event):
    return any(isinstance(s, dict) and s.get('ok') for s in (event or {}).get('sources') or [])


def due_events(events, schedule, covered, report_date):
    """오늘 칸이 실어야 하는 이벤트 행(날짜순). 일정표 의무 행은 `from_schedule: True`, 원문 없음(인용 금지).

    행이 due 인 조건: 공개일이 발행일 D 이하·D 로부터 10일 창 안·일정 파일의 `start` 이상, KEY 가 `covered` 에
    없음, 그리고 원문을 하나라도 받았거나(`ok:true`) 결정일 의무 문서(일정표에 있고 그 KEY 의 받은 행이 없다).
    """
    d = _day(report_date)
    if d is None:
        raise ScheduleError(f'발행일을 읽을 수 없다: {report_date!r}')
    docs = schedule_docs(schedule)
    start = _day(schedule['start'])
    covered = set(covered or ())
    out, seen = [], set()
    rows = [e for e in events or [] if isinstance(e, dict) and e.get('key')]
    for e in rows:
        if e['key'] in covered or e['key'] in seen or not has_text(e):
            continue
        if _in_window(e.get('date'), d, start):
            out.append(dict(e, kind_ko=e.get('kind_ko') or label(e.get('kind'))))
            seen.add(e['key'])
    got = {e['key'] for e in rows if has_text(e)}
    for doc in docs:
        if not KINDS.get(doc['kind'], ('', False))[1]:
            continue
        if doc['key'] in covered or doc['key'] in seen or doc['key'] in got:
            continue
        if _in_window(doc['date'], d, start):
            out.append(dict(doc, kind_ko=label(doc['kind']), sources=[], from_schedule=True))
            seen.add(doc['key'])
    return sorted(out, key=lambda e: (e.get('date') or '', e['key']))


def missing_scheduled(schedule, events, report_date):
    """일정표상 D 까지(10일 창, `start` 이후) 나오기로 한 문서 가운데 받은(`ok:true`) 행이 없는 것."""
    d = _day(report_date)
    if d is None:
        raise ScheduleError(f'발행일을 읽을 수 없다: {report_date!r}')
    docs = schedule_docs(schedule)
    start = _day(schedule['start'])
    got = {e.get('key') for e in events or [] if isinstance(e, dict) and has_text(e)}
    return [dict(doc, kind_ko=label(doc['kind'])) for doc in docs
            if doc['key'] not in got and _in_window(doc['date'], d, start)]


def keys_in(html_text):
    return set(_MARK.findall(_COMMENT.sub(' ', html_text or '')))


def covered_from_posts(repo, post_dir, before_date, rev='HEAD'):
    """`rev` 에 커밋된 `post_dir/YYYY-MM-DD.html` 가운데 날짜 < before_date 인 글의 `data-cb-event` 키 집합.

    작업 트리가 아니라 커밋을 읽는다(US 유동성 칸 `ledger_from_posts` 와 같은 이유) — 커밋 안 된 오늘 글의
    표식이 스스로를 「이미 다룸」으로 만들지 않고, 커밋된 표식을 작업 트리에서 지워 중복 발행하지 못한다.
    git 저장소가 아니면(시험 임시 폴더) 파일을 읽는다. git 이 실패하면 예외 — 빈 집합으로 읽지 않는다.
    """
    before = str(before_date)
    try:
        inside = subprocess.run(['git', '-C', repo, 'rev-parse', '--is-inside-work-tree'],
                                capture_output=True, text=True, timeout=60).stdout.strip() == 'true'
    except (OSError, subprocess.SubprocessError):
        inside = False
    texts = []
    if inside:
        r = subprocess.run(['git', '-C', repo, 'grep', '-l', '-i', 'data-cb-event', rev, '--', f'{post_dir}/*.html'],
                           capture_output=True, text=True, timeout=60)
        if r.returncode not in (0, 1):
            raise RuntimeError(f'git grep 실패({r.returncode}): {r.stderr.strip()[:200]}')
        for line in r.stdout.splitlines():
            path = line.split(':', 1)[1] if line.startswith(f'{rev}:') else line
            m = _POST.match(os.path.basename(path))
            if not m or os.path.dirname(path) != post_dir.rstrip('/') or m.group(1) >= before:
                continue
            show = subprocess.run(['git', '-C', repo, 'show', f'{rev}:{path}'], capture_output=True, text=True,
                                  timeout=60)
            if show.returncode:
                raise RuntimeError(f'git show {rev}:{path} 실패: {show.stderr.strip()[:200]}')
            texts.append(show.stdout)
    else:
        for path in glob.glob(os.path.join(repo, post_dir, '*.html')):
            m = _POST.match(os.path.basename(path))
            if not m or m.group(1) >= before:
                continue
            with open(path, encoding='utf-8') as fh:
                texts.append(fh.read())
    out = set()
    for t in texts:
        out |= keys_in(t)
    return out
