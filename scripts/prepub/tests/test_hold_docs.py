"""막기(2026-11-22) — 루틴 지시문에 「검토가 실패해도 원래 판으로 발행」 길이 남지 않는다.

사용자: 「글을 먼저 내보내고 나중에 틀린 데를 찾아 고치면 안되고 발행 전에 제대로 검사하고 다 끝난 다음에 올려야지」.
루틴은 지시문을 따른다 — 옛 문장이 한 줄이라도 남으면 그 길로 발행한다(11/09 처럼 지시문 두 곳이 어긋난 전례).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PREPUB = (ROOT / '.claude' / 'PREPUB_REVIEW.md').read_text(encoding='utf-8')
ORCH = (ROOT / '.claude' / 'ORCHESTRATOR.md').read_text(encoding='utf-8')

GONE = ('검토·수정이 실패하면 발행을 막지 않는다', '원래 판으로 되돌려 발행', 'cp "$PREPUB_DIR/original.html"',
        '--state fix_failed', '--facts-applied', '실패·한도·25분 마감은 발행을 막지 않는다', '기록만 하고 다음 단계')


def test_the_publish_anyway_path_is_gone_from_both_documents():
    for doc, name in ((PREPUB, 'PREPUB_REVIEW'), (ORCH, 'ORCHESTRATOR')):
        left = [g for g in GONE if g in doc]
        assert not left, f'{name} 에 옛 발행 길이 남았다: {left}'


def test_every_fallback_exit_in_the_procedure_goes_to_the_hold_section():
    assert '## 5. 세우기' in PREPUB
    # 모든 「exit 10 이면」 이 §5 로 간다 — 다른 곳으로 가는 문장이 생기면 실패
    import re
    for m in re.finditer(r'exit 10[^\n]{0,80}', PREPUB):
        assert '§5' in m.group(0), m.group(0)


def test_the_hold_section_commits_only_the_record_and_names_both_lock_actions():
    sec = PREPUB.split('## 5. 세우기', 1)[1]
    assert '--push' in sec and '다른 파일은 add 하지 않는다' in sec and 'git add -A' not in sec
    assert 'run_lock.sh release' in sec and 'run_lock.sh hold' in sec
    assert 'STEP 2.6·3·3.5·4 를 하지 않는다' in sec


def test_judging_is_marked_before_the_findings_are_read_and_sealed_after():
    mark = PREPUB.index('renew "$(cat /tmp/us-lock-key)" judging')
    read = PREPUB.index('`$PREPUB_DIR/facts.md` 를 읽는다')
    assert mark < read
    assert 'prepub_review.py facts-done' in PREPUB


def test_the_orchestrator_stops_on_a_held_lock_and_clears_the_mark_after_the_brief():
    assert 'exit 6 이면 발행 전 검사가 이 세션을 세워 두었다' in ORCH
    assert 'run_lock.sh renew "$(cat /tmp/us-lock-key)" clear' in ORCH
    # 표시를 떼는 자리는 브리프 push 뒤, 뉴스 글(STEP 3.5) 앞
    assert ORCH.index('renew "$(cat /tmp/us-lock-key)" clear') < ORCH.index('## STEP 3.5')


def test_the_publish_record_is_taken_from_the_file_that_is_committed():
    assert 'prepub_review.py record --dir "$PREPUB_DIR" --html posts/[DATE].html' in PREPUB
    i = ORCH.index('prepub_review.py record --dir "$PREPUB_DIR" --html posts/[DATE].html')
    assert i < ORCH.index('run_gates.py record --market us')     # 최종 검증 기록 앞
    assert 'facts-done` 을 **다시 찍는다**' in PREPUB and 'facts-done` 을 다시 찍' in ORCH


def test_style_and_note_changes_are_sealed():
    assert '--why style' in PREPUB and '--why note' in ORCH


def test_a_news_resume_checks_the_brief_before_taking_over_a_dead_mark():
    assert 'brief-out' in ORCH and 'git cat-file -e "origin/main:posts/' in ORCH


def test_the_news_resume_check_reads_the_date_from_the_stored_key():
    """STEP 0 은 키를 /tmp/us-lock-key 에만 둔다 — 설정하지 않은 셸 변수로 날짜를 만들면 posts/.html 을 확인해
    뉴스 이어 쓰기가 늘 막힌다(codex 구현 2회차 #3)."""
    assert '${KEY' not in ORCH and '$KEY' not in ORCH      # 이 지시문 어디에도 설정하지 않은 KEY 가 없다
    assert 'git cat-file -e "origin/main:posts/$(cut -d- -f2- /tmp/us-lock-key).html"' in ORCH


def test_the_stored_key_gives_the_post_date(tmp_path):
    """지시문의 그 식을 실제 셸로 — `run_lock.sh key us` 의 출력 꼴(us-YYYY-MM-DD)에서 글 날짜가 나온다."""
    import subprocess
    key = tmp_path / 'us-lock-key'
    key.write_text('us-2026-11-20\n')
    out = subprocess.run(['bash', '-c', 'echo "posts/$(cut -d- -f2- "$0").html"', str(key)], capture_output=True, text=True)
    assert out.stdout.strip() == 'posts/2026-11-20.html'


def test_the_separate_style_close_seals_its_version_when_the_review_ran():
    """발행 전 검토의 문체 후보가 0 인 날 STEP 2.6(켜져 있으면)이 글을 고치면 그 판도 봉인해야 record 가 받는다
    (codex 구현 2회차 #4)."""
    step26 = ORCH.split('## STEP 2.6', 1)[1].split('## STEP 3', 1)[0]
    assert 'prepub_review.py seal --dir "$PREPUB_DIR" --html "$H" --why style' in step26
    assert 'STEP 2.7 이 돌았으면' in step26
    assert 'ORCHESTRATOR STEP 2.6 이 같은 봉인' in PREPUB
