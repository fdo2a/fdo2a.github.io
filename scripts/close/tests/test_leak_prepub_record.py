"""staged-scan — 발행 전 검토 기록의 `final_sha256` 도 공개될 글의 해시다 (2026-11-26).

2026-11-24 US 루틴: 문체 편집 0 인 날, 발행 전 검토 기록(`reviews/prepublish/us/<date>.json`, 11/23 부터
`final_sha256` 을 담는다)의 글 해시가 감사 기록의 `source_sha256` 과 같아 staged-scan 이 FOUND 를 냈고,
게이트·codex 검토를 다 마친 글이 style_abort 로 세워졌다. 11/17 수정은 검증 기록만 허용했다.

허용은 검증 기록과 같은 기준이다: 그 날짜 기록의 `final_sha256` 한 자리가 **staged 된 글의 실제 바이트**
(또는 에디터 노트를 걷어낸 바이트)의 해시일 때만. 그 밖의 자리·값은 그대로 잡는다.
"""

import json

from close import leak
from close.tests.test_leak_public_hash import (BODY, DATE, EDITED, POST, RECORD, audit, record, repo,  # noqa: F401
                                               sha, stage)

PREPUB = 'reviews/prepublish/us/%s.json' % DATE


def prepub_record(final, extra=None):
    """실제 기록의 뼈대(2026-11-24 판)."""
    doc = {'section': 'us', 'date': DATE, 'request_id': 'us-%s-b0a3fb98db03' % DATE,
           'draft_sha': '6977444c29afb72edef3995c5324bcfa3bd66269', 'state': 'reviewed', 'reason': '',
           'style_candidates': 1, 'style_applied': 0, 'style_findings': [],
           'recorded_at': '2026-11-24T22:25:07Z', 'facts_done': True, 'final_sha256': final}
    doc.update(extra or {})
    return json.dumps(doc, ensure_ascii=False, indent=1) + '\n'


def test_zero_edit_day_with_prepub_record_is_clean(repo):
    """11/24 그대로 — 편집 0, 검증 기록과 발행 전 검토 기록이 함께 staged."""
    h = sha(BODY)
    stage(repo, BODY, record(h, h), {PREPUB: prepub_record(h)})
    assert leak.staged_hits(str(repo), audit(h, h)) == []


def test_private_draft_hash_in_final_slot_is_found(repo):
    """final_sha256 자리라도 staged 글의 바이트와 다른 해시(고치기 전 초안)면 유출이다."""
    h = sha(EDITED)
    stage(repo, EDITED, record(h, h), {PREPUB: prepub_record(sha(BODY))})
    assert leak.staged_hits(str(repo), audit(sha(BODY), h, proposed=h)) == [PREPUB]


def test_same_hash_in_other_prepub_field_is_found(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h), {PREPUB: prepub_record(h, {'reason': h})})
    assert leak.staged_hits(str(repo), audit(h, h)) == [PREPUB]


def test_verification_allowance_does_not_leak_into_prepub_path(repo):
    """두 기록의 허용은 서로 경로별이다 — 다른 날짜의 발행 전 검토 기록은 허용받지 못한다."""
    h = sha(BODY)
    other = 'reviews/prepublish/us/2026-11-15.json'
    stage(repo, BODY, record(h, h), {other: prepub_record(h)})
    assert leak.staged_hits(str(repo), audit(h, h)) == [other]
    assert RECORD not in leak.staged_hits(str(repo), audit(h, h))
