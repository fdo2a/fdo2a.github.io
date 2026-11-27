"""매일 검증 알림 — 한국은행·일본은행 예정 문서를 못 받은 줄(2026-11-27, 설계 8절 r5 #7).

일정표에 오늘까지 나오기로 한 문서인데 받은 원문이 없으면 한 줄. 문구는 고정 목록이라 「기타 안내」로 뭉개지지 않고
원문 그대로 남는다. 이유는 고정 목록에서만 — 수집기의 자유 문장은 새지 않는다.
"""
from datetime import date

from review import digest as D

BOK = {'bank': 'bok', 'start': '2026-11-28', 'meetings': [
    {'meeting': '2026-11-26', 'decision': '2026-11-26', 'presser': '2026-11-26', 'minutes': '2026-12-15'}]}
BOJ = {'bank': 'boj', 'start': '2026-11-28', 'meetings': [
    {'meeting': '2026-12-18', 'statement': '2026-12-18', 'presser': '2026-12-21'}]}


def test_missing_minutes_line_keeps_its_text_through_the_note_filter():
    book = {'report_date': '2026-12-15', 'events': [], 'collect': {'status': 'ok', 'missing': ['/fileSrc/secret']}}
    notes = D.cb_missing_notes({'한국은행': (BOK, book)}, date(2026, 12, 16))
    assert notes == ['한국은행 12/15 예정된 금통위 의사록 원문을 못 받았다 — 공개 목록에 아직 없음']
    assert D.safe_notes(notes) == notes
    assert [c for _n, c in D._classified_notes(notes)] == ['must']


def test_reason_comes_from_a_closed_list():
    stale = {'report_date': '2026-12-17', 'events': [], 'collect': {'status': 'ok'}}
    failed = {'report_date': '2026-12-21', 'events': [], 'collect': {'status': 'failed'}}
    assert D.cb_missing_notes({'일본은행': (BOJ, stale)}, date(2026, 12, 19)) == [
        '일본은행 12/18 예정된 금융정책 결정 공표문 원문을 못 받았다 — 수집 기록 없음']
    got = D.cb_missing_notes({'일본은행': (BOJ, failed)}, date(2026, 12, 22))
    assert got == ['일본은행 12/18 예정된 금융정책 결정 공표문 원문을 못 받았다 — 수집 실패',
                   '일본은행 12/21 예정된 총재 정례 기자회견 원문을 못 받았다 — 수집 실패']
    assert D.safe_notes(got) == got
    assert D.cb_missing_notes({'일본은행': (BOJ, None)}, date(2026, 12, 19))[0].endswith('수집 기록 없음')


def test_received_docs_and_days_before_start_are_quiet():
    got = {'report_date': '2026-12-15', 'events': [
        {'key': 'bok-minutes-20261126', 'date': '2026-12-15', 'sources': [{'ok': True}]}], 'collect': {'status': 'ok'}}
    assert D.cb_missing_notes({'한국은행': (BOK, got)}, date(2026, 12, 16)) == []
    assert D.cb_missing_notes({'한국은행': (BOK, None)}, date(2026, 11, 28)) == []
    # 공개 당일(수집 전)에는 알리지 않는다 — 기준은 어제까지
    assert D.cb_missing_notes({'한국은행': (BOK, None)}, date(2026, 12, 15)) == []


def test_unreadable_schedule_is_one_fixed_line():
    assert D.cb_missing_notes({'한국은행': (None, None)}, date(2026, 12, 15)) == [D.CB_UNREAD]
    assert D.safe_notes([D.CB_UNREAD]) == [D.CB_UNREAD]
    # 고정 문구에 맞지 않는 줄(자유 이유)은 여전히 「기타 안내」로 접힌다
    assert D.safe_notes(['한국은행 12/15 예정된 금통위 의사록 원문을 못 받았다 — HTTP 403 /fileSrc/x']) == [
        '기타 안내 1건 — 맥에서 확인']
