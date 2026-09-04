import pytest

from review.queue import (is_watched, mark, pending, section_of, seed,
                          union_pending, watched)

TREE = {
    'posts/2026-08-21.html': 'aaa',
    'posts/2026-08-22.html': 'bbb',
    'kr/posts/2026-08-21.html': 'ccc',
    'thesis/skhynix.html': 'ddd',
    'scripts/thesis/content.py': 'mmm',
    'about.html': 'jjj',
    'posts.json': 'eee',
    'index.html': 'fff',
    'kr/index.html': 'kkk',
    'kr/data/kr_flows.json': 'ggg',
    'kr/data/kr_sector.html': 'lll',
    'data/sector_performance.html': 'hhh',
    'scripts/kr/tests/fixtures/top_value.html': 'iii',
}


def test_published_prose_is_watched():
    assert watched(TREE) == sorted([
        'about.html', 'posts/2026-08-21.html', 'posts/2026-08-22.html',
        'kr/posts/2026-08-21.html', 'scripts/thesis/content.py',
    ])


def test_a_pipeline_nobody_told_the_gate_about_is_still_watched():
    """The gate fails safe. /weekly/, /monthly/ and /comment/ are coming; a page must
    not escape review just because this module has not heard of its directory yet."""
    for path in ('weekly/2026-08-29.html', 'kr/weekly/2026-08-29.html',
                 'comment/2026-08-29.html', 'monthly/2026-08.html',
                 'kr/monthly/2026-08.html', 'newthing/whatever.html'):
        assert is_watched(path), path


def test_machine_rendered_thesis_pages_are_not_watched():
    """thesis 페이지는 사람이 타이핑하지 않는다. 산문은 content.py에서, 수치는 매일
    갱신되는 watch.json에서 렌더된다. 페이지를 감시하면 숫자가 바뀐 날마다 큐에 오르고,
    정작 읽어야 할 사람 글은 그 소음에 묻힌다."""
    for path in ('thesis/samsung.html', 'thesis/skhynix.html', 'thesis/micron.html',
                 'thesis/narrative.html'):
        assert not is_watched(path), path


def test_the_prose_those_pages_are_built_from_is_watched_instead():
    """읽어야 할 것은 결과물이 아니라 사람이 쓴 원고다."""
    for path in ('scripts/thesis/content.py', 'scripts/thesis/narrative.py'):
        assert is_watched(path), path
    assert section_of('scripts/thesis/content.py') == 'thesis 원고'


def test_other_python_under_scripts_stays_out():
    for path in ('scripts/thesis/triggers.py', 'scripts/us/macro.py',
                 'scripts/review_gate.py'):
        assert not is_watched(path), path


def test_machine_written_fragments_and_fixtures_are_not_watched():
    for path in ('data/sector_performance.html', 'kr/data/kr_sector.html',
                 'scripts/kr/tests/fixtures/top_value.html',
                 'thesis/data/anything.html'):
        assert not is_watched(path), path


def test_navigation_pages_are_not_watched():
    for path in ('index.html', 'kr/index.html', 'thesis/index.html', '404.html'):
        assert not is_watched(path), path


def test_non_html_is_never_watched():
    for path in ('posts.json', 'sitemap.xml', 'data/market_data.json', 'style.css'):
        assert not is_watched(path), path


def test_section_labels_come_from_the_path():
    assert section_of('posts/2026-08-22.html') == 'us'
    assert section_of('kr/posts/2026-08-21.html') == 'kr'
    assert section_of('weekly/2026-08-29.html') == 'weekly'
    assert section_of('kr/monthly/2026-08.html') == 'kr/monthly'
    assert section_of('about.html') == '사이트'


def test_everything_is_pending_against_an_empty_ledger():
    out = pending({}, TREE)
    assert sorted(p.path for p in out) == watched(TREE)
    assert all(p.reason == '신규' for p in out)


def test_a_reviewed_file_at_the_same_sha_is_quiet():
    assert pending(seed(TREE, at='2026-08-24T00:00:00+09:00'), TREE) == []


def test_an_edited_file_comes_back_into_the_queue():
    ledger = seed(TREE, at='2026-08-24T00:00:00+09:00')
    edited = dict(TREE, **{'posts/2026-08-22.html': 'bbb-edited'})
    assert [(p.path, p.reason, p.sha) for p in pending(ledger, edited)] == [
        ('posts/2026-08-22.html', '수정됨', 'bbb-edited')]


def test_a_newly_published_post_comes_into_the_queue():
    ledger = seed(TREE, at='2026-08-24T00:00:00+09:00')
    grown = dict(TREE, **{'posts/2026-08-25.html': 'new'})
    assert [(p.path, p.reason) for p in pending(ledger, grown)] == [
        ('posts/2026-08-25.html', '신규')]


def test_newest_first_across_pipelines_not_by_path_spelling():
    """A path-string sort puts posts/2026-08-21 above kr/posts/2026-08-25 because 'p'
    beats 'k'. The queue is about recency, so the date in the filename decides."""
    tree = {'posts/2026-08-21.html': 'a', 'kr/posts/2026-08-25.html': 'b',
            'monthly/2026-08.html': 'c', 'about.html': 'd'}
    assert [p.path for p in pending({}, tree)] == [
        'about.html',                 # undated — a page that just changed
        'monthly/2026-08.html',       # month end sorts after any day in that month
        'kr/posts/2026-08-25.html',
        'posts/2026-08-21.html',
    ]


def test_a_deleted_file_still_in_the_ledger_does_not_crash_or_report():
    ledger = seed(TREE, at='2026-08-24T00:00:00+09:00')
    shrunk = {k: v for k, v in TREE.items() if k != 'posts/2026-08-21.html'}
    assert pending(ledger, shrunk) == []


def test_a_damaged_ledger_entry_means_unreviewed_not_a_crash():
    """A corrupt record must fail toward review. Crashing inside a session-start hook
    would silence the gate entirely, which is the one outcome we cannot have."""
    for broken in (None, 'nonsense', {}, {'at': 'x'}, []):
        ledger = {'reviewed': {'posts/2026-08-22.html': broken}}
        assert [p.path for p in pending(ledger, {'posts/2026-08-22.html': 'bbb'})] == [
            'posts/2026-08-22.html']


def test_a_ledger_missing_its_reviewed_map_means_everything_is_unreviewed():
    for ledger in ({}, {'reviewed': None}, {'reviewed': 'junk'}):
        assert len(pending(ledger, TREE)) == len(watched(TREE))


def test_seed_marks_entries_as_baseline_so_history_stays_honest():
    ledger = seed(TREE, at='2026-08-24T00:00:00+09:00')
    assert ledger['reviewed']['posts/2026-08-22.html'] == {
        'sha': 'bbb', 'at': '2026-08-24T00:00:00+09:00', 'findings': 0,
        'baseline': True}


def test_marking_records_the_sha_reviewed_and_clears_baseline():
    ledger = seed(TREE, at='2026-08-24T00:00:00+09:00')
    after = mark(ledger, 'posts/2026-08-22.html', 'bbb',
                 at='2026-08-24T14:03:00+09:00', findings=3)
    assert after['reviewed']['posts/2026-08-22.html'] == {
        'sha': 'bbb', 'at': '2026-08-24T14:03:00+09:00', 'findings': 3}


def test_marking_does_not_mutate_the_ledger_it_was_given():
    ledger = seed(TREE, at='2026-08-24T00:00:00+09:00')
    mark(ledger, 'posts/2026-08-22.html', 'zzz', at='2026-08-24T14:03:00+09:00')
    assert ledger['reviewed']['posts/2026-08-22.html']['sha'] == 'bbb'


def test_marking_an_unwatched_path_is_refused():
    with pytest.raises(ValueError, match='감시 대상'):
        mark({}, 'posts.json', 'eee', at='2026-08-24T14:03:00+09:00')


def test_marking_from_an_empty_ledger_works():
    after = mark({}, 'posts/2026-08-22.html', 'bbb', at='2026-08-24T14:03:00+09:00')
    assert after['reviewed']['posts/2026-08-22.html']['sha'] == 'bbb'


def test_a_stale_checkout_cannot_hide_what_was_published():
    """The hole worth the most: origin advances to R, the laptop still holds the
    reviewed L, and overlaying the working tree would erase R from view. Both versions
    have to be asked about."""
    ledger = seed({'posts/2026-08-22.html': 'L'}, at='2026-08-24T00:00:00+09:00')
    origin = {'posts/2026-08-22.html': 'R'}     # 루틴이 새로 올린 판
    work = {'posts/2026-08-22.html': 'L'}       # 아직 pull 안 한 로컬
    merged = union_pending(pending(ledger, origin), pending(ledger, work))
    assert [(p.path, p.sha) for p in merged] == [('posts/2026-08-22.html', 'R')]


def test_union_keeps_the_newest_first_order_across_groups():
    ledger = {}
    a = pending(ledger, {'posts/2026-08-21.html': 'x'})
    b = pending(ledger, {'posts/2026-08-21.html': 'x', 'posts/2026-08-25.html': 'z'})
    merged = union_pending(a, b)
    assert [p.path for p in merged] == ['posts/2026-08-25.html', 'posts/2026-08-21.html']


def test_two_unreviewed_versions_of_one_page_both_survive_the_union():
    """Ledger holds L, origin published R, the laptop holds a hand-edited W. Both R and
    W are unread; collapsing them by path would drop one, and the dropped one may be the
    version that was actually live."""
    ledger = seed({'posts/2026-08-22.html': 'L'}, at='2026-08-24T00:00:00+09:00')
    merged = union_pending(pending(ledger, {'posts/2026-08-22.html': 'R'}),
                           pending(ledger, {'posts/2026-08-22.html': 'W'}))
    assert sorted(p.sha for p in merged) == ['R', 'W']


def test_the_same_version_seen_twice_is_still_one_row():
    ledger = {}
    tree = {'posts/2026-08-22.html': 'same'}
    merged = union_pending(pending(ledger, tree), pending(ledger, tree))
    assert [(p.path, p.sha) for p in merged] == [('posts/2026-08-22.html', 'same')]


def test_union_of_nothing_is_nothing():
    assert union_pending([], []) == []


# ── 방향성 동등 판정으로 조판 변경을 걸러낸다 ────────────────────────────────

from review.queue import accept, accepted_shas, baselines, classify  # noqa: E402

LEDGER2 = {'reviewed': {
    'posts/2026-08-21.html': {'sha': 'old', 'at': 't', 'findings': 0},
}}
ONE = {'posts/2026-08-21.html': 'new'}


def verdicts(mapping):
    """(old_sha, new_sha) -> True/False/None."""
    return lambda path, old, new: mapping.get((old, new))


def test_a_typography_only_change_leaves_the_queue():
    got = classify(LEDGER2, ONE, verdicts({('old', 'new'): True}))
    assert got.todo == [] and got.unavailable == []
    assert [p.path for p in got.typography] == ['posts/2026-08-21.html']
    assert got.pending == []


def test_a_prose_change_stays_in_the_queue():
    got = classify(LEDGER2, ONE, verdicts({('old', 'new'): False}))
    assert [p.reason for p in got.todo] == ['수정됨']
    assert got.typography == []


def test_an_undecidable_change_counts_as_unreviewed():
    """None은 「같다」가 아니라 「모른다」다."""
    got = classify(LEDGER2, ONE, verdicts({}))
    assert got.todo == [] and got.typography == []
    assert [p.reason for p in got.unavailable] == ['판정 불가']
    assert len(got.pending) == 1


def test_without_a_verdict_source_the_old_sha_only_judgment_stands():
    """기존 27 tests가 이 계약 위에 있다."""
    assert [p.reason for p in classify(LEDGER2, ONE).todo] == ['수정됨']


def test_an_unchanged_page_is_never_judged():
    """SHA가 같으면 blob을 읽으러 가지 않는다 — 정상 상태에서 git 호출 0."""
    def explode(path, old, new):
        raise AssertionError('불려서는 안 된다')
    assert classify(LEDGER2, {'posts/2026-08-21.html': 'old'}, explode).pending == []


def test_an_accepted_version_is_the_fast_path_next_time():
    once = accept(LEDGER2, 'posts/2026-08-21.html', 'new', at='u')

    def explode(path, old, new):
        raise AssertionError('불려서는 안 된다')
    assert classify(once, ONE, explode).pending == []


def test_accepting_does_not_touch_the_reviewed_version():
    entry = accept(LEDGER2, 'posts/2026-08-21.html', 'new',
                   at='u')['reviewed']['posts/2026-08-21.html']
    assert entry['sha'] == 'old' and entry['at'] == 't' and entry['findings'] == 0
    assert accepted_shas(entry) == ['new']
    assert entry['accepted'][0]['reason'] == 'typography'


def test_accepted_versions_accumulate_so_two_views_do_not_fight():
    """origin 판과 작업 폴더 판이 둘 다 동등하면 둘 다 담는다."""
    book = accept(accept(LEDGER2, 'posts/2026-08-21.html', 'r', at='u'),
                  'posts/2026-08-21.html', 'w', at='u')
    assert accepted_shas(book['reviewed']['posts/2026-08-21.html']) == ['r', 'w']


def test_accepting_the_same_version_twice_changes_nothing():
    once = accept(LEDGER2, 'posts/2026-08-21.html', 'new', at='u')
    assert accept(once, 'posts/2026-08-21.html', 'new', at='v') is once
    assert accept(LEDGER2, 'posts/2026-08-21.html', 'old', at='v') is LEDGER2


def test_accepted_versions_do_not_grow_without_bound():
    book = LEDGER2
    for n in range(20):
        book = accept(book, 'posts/2026-08-21.html', f's{n}', at='u')
    kept = accepted_shas(book['reviewed']['posts/2026-08-21.html'])
    assert len(kept) == 8 and kept[-1] == 's19'


def test_reviewing_again_forgets_the_accepted_versions():
    """새로 읽었으면 옛 판과의 동등 기록은 의미가 없다."""
    once = accept(LEDGER2, 'posts/2026-08-21.html', 'new', at='u')
    again = mark(once, 'posts/2026-08-21.html', 'new', at='v', findings=1)
    assert accepted_shas(again['reviewed']['posts/2026-08-21.html']) == []


def test_an_accepted_version_can_serve_as_the_baseline():
    """최초 검토 blob이 사라져도 최근 승인분이 남아 있으면 판정이 된다."""
    once = accept(LEDGER2, 'posts/2026-08-21.html', 'mid', at='u')
    entry = once['reviewed']['posts/2026-08-21.html']
    assert baselines(entry) == ['mid', 'old']
    got = classify(once, ONE, verdicts({('mid', 'new'): True}))
    assert [p.path for p in got.typography] == ['posts/2026-08-21.html']


def test_accepting_does_not_mutate_the_ledger_it_was_given():
    accept(LEDGER2, 'posts/2026-08-21.html', 'new', at='u')
    assert 'accepted' not in LEDGER2['reviewed']['posts/2026-08-21.html']


def test_accepting_an_unknown_path_is_refused():
    with pytest.raises(ValueError):
        accept(LEDGER2, 'posts/2026-09-01.html', 'new', at='u')


def test_a_new_page_is_never_typography():
    """원장에 없는 글은 판정이 무엇이든 신규다 — refresh가 집어갈 수 없어야 한다."""
    got = classify({'reviewed': {}}, ONE, verdicts({('old', 'new'): True}))
    assert [p.reason for p in got.todo] == ['신규'] and got.typography == []
