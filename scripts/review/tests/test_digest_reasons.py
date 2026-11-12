"""매일 검증 알림 3a(2026-11-12) — 맥이 이미 아는 정보로만 「왜」를 붙이고, 넘치면 줄 중간에서 자르지 않는다.

A 길이 예산 · B 실패 종류+이유 · C·D 전송기 줄 · E 발행 알림 꼬리 · F 발행 전 기록 · G 접수 결과.
spec: docs/superpowers/specs/2026-11-08-daily-verify-digest.md
"""
import json
import os
import re
import subprocess
import sys
from datetime import date

import pytest

from review import digest as D
from review.tests.test_digest import (  # noqa: F401 — cli_env 는 fixture
    COUNTS, SID, FakeGit, FakeWorker, _attempt, _ev, _many, _pending, _publish_state, _texts, _tried, _unc,
    at, cli_env, post)

NOW = at(2026, 11, 9)
SUF = '(이름은 맥 로그에서 확인)'
LABELS = sorted(D.LABEL.values())


def name(i):
    return f'{LABELS[i % len(LABELS)]} {i % 12 + 1}/{i % 28 + 1:02d}'


def gone_note(n):
    return f'공개판에서 사라진 글 {n}건: ' + ', '.join(name(i) for i in range(n))


def kr_note(week=45):
    return D.kr_index_gap_notes({f'2026-W{week}': {'missing': ['indices.KOSPI.2026-11-05']}})[0]


def ok_note(text):
    return any(p.fullmatch(text) for p in D.NOTE_PATTERNS)


def _render_old(posts, prev_lines, now, notes=(), extra_tail=(), limit=D.LIMIT):
    """3a 전의 render 그대로(2026-11-12 얼림) — 불변식 ⓒ 의 기준. (글, 문장표, fixed, 첫 블록 길이)."""
    posts = sorted(posts, key=lambda p: (D.post_day(p['path']) or date.min, p['path']))
    hidden = 0
    head = [D._header(now)]
    for n in D.safe_notes(notes):
        line, k = D.scrub(f'⚠ {n}')
        head.append(line)
        hidden += k
    open_ = sorted((p for p in posts if not D.resolved(p)),
                   key=lambda p: -(D.post_day(p['path']) or date.min).toordinal())
    tail = []
    if open_:
        names = [D._day_label(p['path']) for p in open_]
        more = f' 외 {len(names) - 10}건' if len(names) > 10 else ''
        tail.append(f'아직 안 끝난 글 {len(open_)}건: ' + ', '.join(names[:10]) + more)
    unread = sum(1 for p in posts if p['state'] == '읽지 않음')
    if unread:
        tail.append(f'읽지 않고 범위에 넣은 글 {unread}편(90일 안, 게이트 도입 전 글, 검토 대상 아님)')
    for x in extra_tail:
        line, k = D.scrub(str(x))
        tail.append(line)
        hidden += k
    closing = [D._totals([p for p in posts if D.in_window(p['path'], now.date())]), D.CAVEAT]
    changed = []
    for p in posts:
        old = prev_lines.get(p['path'])
        old = old if isinstance(old, dict) else {}
        body = bool(old) and old.get('sha') != p.get('sha')
        if body or old.get('text') != D.block(p):
            changed.append((p, D.block(p, changed_body=body)))
    today = now.date()
    changed.sort(key=lambda x: (not D.in_window(x[0]['path'], today),
                                -(D.post_day(x[0]['path']) or date.min).toordinal(), x[0]['path']))
    lines = {k: v for k, v in prev_lines.items() if isinstance(v, dict)}
    fixed = len('\n\n'.join(head + ['새로 나온 글이나 바뀐 상태가 없어요.'] + tail + closing)) + 120
    first = None
    if not changed:
        body = ['새로 나온 글이나 바뀐 상태가 없어요.']
    else:
        body = [f'새로 나온 글·바뀐 상태 {len(changed)}건']
        fixed = len('\n\n'.join(head + body + tail + closing)) + 120
        first = len(D.scrub(changed[0][1])[0])
        used = 0
        for i, (p, text) in enumerate(changed):
            text, k = D.scrub(text)
            if fixed + used + len(text) + 2 > limit:
                body.append(f'…외 {len(changed) - i}건은 다음 알림에 이어서 보낼게요.')
                break
            body.append(text)
            used += len(text) + 2
            hidden += k
            if not k:
                lines[p['path']] = {'sha': p.get('sha'), 'text': D.block(p)}
    if hidden:
        tail.append(f'{hidden}줄 생략 — 맥에서 확인')
    text = '\n\n'.join(['\n'.join(head)] + body + tail + closing)
    return text, lines, fixed, first


@pytest.fixture
def blk(monkeypatch):
    """글 블록 길이를 마음대로 — post 에 `blk` 를 넣으면 그 글자가 블록이다."""
    real = D.block
    monkeypatch.setattr(D, 'block', lambda p, changed_body=False: p['blk'] if 'blk' in p else real(p, changed_body))

    def make(n, path='posts/2026-11-06.html'):
        return dict(post(path), blk='■' + '가' * (n - 1))
    return make


def whole_lines(text, originals):
    """전송본의 모든 줄이 온전하다 — 줄 중간에서 끊긴 흔적이 없다."""
    assert not text.endswith('…')
    for x in originals:
        assert x in text.split('\n\n') or x in text.split('\n'), x


# ── A. 길이 예산 ──────────────────────────────────────────────────────────────

MUST_TAIL = ['어제 요약 접수 실패(제출 시도 2번: 거절 2)', '전송기: 밀린 알림 2건 · 영구 실패 1건']


@pytest.mark.parametrize('n', [270, 280, 284, 285, 286, 290, 300, 330, 400])
def test_name_notes_shrink_at_name_boundaries_and_must_lines_stay(n):
    a = post()
    trimmed = []
    text, lines = D.render([a], {}, NOW, notes=[gone_note(n)], extra_tail=[D.Must(x) for x in MUST_TAIL],
                           trimmed=trimmed)
    assert len(text) <= D.LIMIT
    whole_lines(text, MUST_TAIL + [D.CAVEAT])
    assert '최근 7일: 글 1편' in text
    note = [x[2:] for x in text.split('\n') if x.startswith('⚠ ')]
    assert len(note) == 1 and ok_note(note[0])                  # ⑤ 줄인 문장도 고정 문구 목록 안
    if SUF in note[0]:
        m = re.fullmatch(rf'공개판에서 사라진 글 {n}건(?:: (.*?) 외 (\d+)건)?' + re.escape(SUF), note[0])
        kept = m.group(1).split(', ') if m.group(1) else []
        assert kept == [name(i) for i in range(len(kept))]      # ③ 이름 경계에서, 앞에서부터 남긴다
        assert len(kept) + int(m.group(2) or n) == n
        assert trimmed == [gone_note(n)]                        # 줄이기 전 전체 문장
    else:
        assert note[0] == gone_note(n) and trimmed == []
    if a['path'] in lines:                                      # ④ lines 불변식
        assert D.block(a) in text
    else:
        assert D.block(a) not in text


def test_counted_lengths_equal_assembled_lengths():
    # 예산은 조립하지 않고 센 길이로 걷는다 — 센 값이 실제 문장 길이와 같아야 「넘지 않는다」가 참이다
    names = gone_note(37).split(': ')[1]
    for note in (gone_note(1), gone_note(2), gone_note(37), gone_note(37).split(': ')[0] + SUF,
                 f'{D.KEEP_DAYS}일이 지나 추적을 멈춘 글 37건(안 끝났거나 못 보낸 글): {names}',
                 f'{D.KEEP_DAYS}일보다 오래된 날짜의 글이 새로 올라왔어요(검사 안 함) 37건: {names}'):
        assert D.safe_notes([note]) == [note]
        n = D._NameNote(note)
        for keep in range(len(n.names), -1, -1):
            n.keep = keep
            assert len(n) == len(n.text()) and D.safe_notes([n.text()]) == [n.text()]
    for limit in (3900, 2000, 1200, 700, 400):
        head = [{'text': '머리', 'cls': 'must', 'k': 0}, {'note': D._NameNote(gone_note(150)), 'cls': 'names',
                                                         'orig': 'x', 'k': 0},
                {'text': '⚠ ' + kr_note(), 'cls': 'kr', 'orig': 'k', 'k': 0}]
        tail = [{'text': '꼭', 'cls': 'must', 'k': 0}, {'text': '가' * 300, 'cls': 'soft', 'orig': 's', 'k': 0}]
        b = D._Budget(head, '본문 줄', tail, ['합계', '맺음'])
        b.fit(limit)
        h, t, _ = b.lines()
        assert b.measure() == len('\n\n'.join(h + ['본문 줄'] + t + ['합계', '맺음'])) + 120
        assert b.measure() <= limit or not any(x['on'] for x in head + tail if x['cls'] != 'must')


def test_small_inputs_are_not_trimmed_and_big_ones_are():
    assert SUF not in D.render([post()], {}, NOW, notes=[gone_note(200)])[0]
    assert SUF in D.render([post()], {}, NOW, notes=[gone_note(400)])[0]


@pytest.mark.parametrize('n', [99_999, 100_000])
def test_trimmed_name_count_is_printed_as_is(n):
    text, _ = D.render([], {}, NOW, notes=[gone_note(n)])
    note = [x[2:] for x in text.split('\n') if x.startswith('⚠ ')][0]
    assert ok_note(note) and f'사라진 글 {n}건' in note and len(text) <= D.LIMIT
    m = re.search(r' 외 (\d+)건', note)
    assert m and int(m.group(1)) + note.split(': ')[1].split(' 외 ')[0].count(',') + 1 == n


def _shape(text, tails, kr, names_total):
    note = [x[2:] for x in text.split('\n') if x.startswith('⚠ 공개판')]
    if not note:
        kept = None
    elif SUF not in note[0]:
        kept = names_total
    else:
        kept = note[0].split(': ')[1].split(' 외 ')[0].count(',') + 1 if ': ' in note[0] else 0
    present = [t in text.split('\n\n') for t in tails]
    m = re.search(r'길어서 줄인 안내 (\d+)줄 — 맥 로그에서 확인', text)
    return kept, present, ('⚠ ' + kr) in text.split('\n'), int(m.group(1)) if m else 0


def test_trim_order_names_then_tail_then_kr_then_name_notes():
    tails = ['꼬리 하나 ' + '가' * 40, D.Soft('꼬리 둘 ' + '나' * 90), '짧음', D.Soft('꼬리 넷 ' + '라' * 60)]
    kr, total = kr_note(), 30
    seen = set()
    for limit in range(1600, 300, -1):
        trimmed = []
        text, _ = D.render([], {}, NOW, notes=[gone_note(total), kr], extra_tail=tails, limit=limit, trimmed=trimmed)
        kept, present, has_kr, n = _shape(text, tails, kr, total)
        dropped = present.count(False) + (not has_kr) + (kept is None)
        assert n == dropped                                     # 「길어서 줄인 안내 n줄」 = 뺀 줄 수(표시 유무 가리지 않음)
        assert present == sorted(present, reverse=True)         # ② 뒤에서부터
        if not all(present):
            assert kept in (0, None)                            # ① 이름을 다 던 뒤에만 꼬리를 뺀다
        if not has_kr:
            assert not any(present)                             # ③ 꼬리를 다 뺀 뒤에만 KR 안내
        if kept is None:
            assert not has_kr                                   # ④ 맨 마지막에 이름 0개 안내
        assert not text.endswith('…') and '최근 7일' in text and D.CAVEAT in text
        assert len(trimmed) == dropped + (kept is not None and kept < total)
        if dropped or (kept is not None and kept < total):
            assert len(text) <= max(limit, len(D.render([], {}, NOW, limit=limit)[0]) + 60)
        seen.add((kept is None, has_kr, tuple(present)))
    assert (True, False, (False,) * 4) in seen and (False, True, (True,) * 4) in seen
    assert (False, True, (True, True, True, False)) in seen and (False, False, (False,) * 4) in seen


def test_unmarked_tail_lines_long_or_short_are_soft():
    tails = ['가' * 3000, '짧']
    trimmed = []
    text, _ = D.render([], {}, NOW, extra_tail=tails, limit=900, trimmed=trimmed)
    assert '가' * 3000 not in text and '\n\n짧\n\n' not in text
    assert '길어서 줄인 안내 2줄 — 맥 로그에서 확인' in text and sorted(trimmed) == sorted(tails)


def _worst_health():
    h = {'config_error': {'kind': 'forbidden', 'since': '2026-11-12T00:00:00Z'}, 'backlog': 10 ** 9,
         'failed': 10 ** 9, 'last_outbox_ok': '2001-01-01T00:00:00Z'}
    return D.health_lines(h, at(2026, 11, 12, 9, 20))[0]


def test_marked_health_line_survives_a_tight_budget():
    line = _worst_health()
    assert '9999건 넘음' in line and 'Worker 분류: 봇이 대화에서 차단·강퇴됨' in line
    for limit in (1400, 900, 500):
        text, _ = D.render([post()], {}, NOW, notes=[gone_note(300)], extra_tail=[D.Must(line), '가' * 500],
                           limit=limit)
        assert line in text.split('\n\n')
        assert ('가' * 500 in text) == (limit == 1400)            # 이름만 덜어도 들어가면 꼬리는 그대로 둔다


def _worst_must(monkeypatch=None):
    """꼭 싣는 줄의 최대 조합 — 상한이 걸린 값으로."""
    carry = [{'date': '2026-11-11', 'kind': 'unknown', 'lookup': 'nohash',
              'tries': {k: 10 ** 9 for k in ('rejected', 'server', 'noresp', 'conflict', 'other')}}] * 9
    st = {'carry': carry, 'last_error': '전송 오류',
          'last_error_why': {'kind': '전송 오류', 'why': 'failed_permanent'}}
    tail = [D.Must(x) for x in D.carry_lines(st, date(2026, 11, 12))]
    tail += [D.Must('발행 알림: 최신 상태를 받지 못해 받아 둔 사본으로 읽었어요(원격 확인 실패)'),
             D.Must(D.tail_unread('원격 확인 실패', '받아 둔 사본에서 파일을 못 읽음')), D.Must(_worst_health()),
             D.Must(D.health_lines(None, NOW, why='auth')[0]), '줄일 수 있는 줄 /Users/x', '가' * 5000]
    notes = [D.NOTE_FIRST, D.NOTE_STALE, D.NOTE_CORRUPT, D.AUTH_NOTE, f'지난 알림 실패 — {D.error_text(st)}',
             '모르는 안내', gone_note(500), kr_note()]
    posts = [post(f'japan/daily/2026-10-{d:02d}.html', state='대기', findings=None) for d in range(10, 29)]
    posts += [post(f'posts/2026-09-{d:02d}.html', state='읽지 않음') for d in range(1, 29)]
    return posts, notes, tail


def test_worst_case_of_must_lines_fits_text_and_request():
    posts, notes, tail = _worst_must()
    now = at(2026, 11, 12, 9, 20)
    text, _ = D.render(posts, {}, now, notes=notes, extra_tail=tail)
    assert len(text) <= D.LIMIT
    for x in tail[:-2]:
        assert x in text.split('\n\n')
    assert '지난 요약 접수 결과 외 3건 — 맥 로그에서 확인' in text and '아직 안 끝난 글 19건' in text
    # 줄일 수 있는 줄과 글 블록을 다 뺀 꼴 = 꼭 싣는 줄의 최대 조합. 실제로는 함께 안 나오는 줄까지 넣어도 한도의 2/3 안이다
    bare, lines = D.render(posts, {}, now, notes=notes, extra_tail=tail, limit=1)
    assert len(bare) < 2400 and lines == {} and len(bare.encode('utf-8')) < 8000
    for x in tail[:-2]:
        assert x in bare.split('\n\n')
    for n in notes[:5]:
        assert '⚠ ' + n in bare.split('\n')
    assert '길어서 줄인 안내 4줄 — 맥 로그에서 확인' in bare and '…외 47건은 다음 알림에 이어서 보낼게요.' in bare
    assert '생략 — 맥에서 확인' not in bare                       # 보조 검사에 걸린 줄도 빠졌으면 세지 않는다
    p = D.compose(posts, {}, now, notes, tail, {}, {}, {})
    assert len(D.request_body(p).encode('utf-8')) <= D.MAX_BODY and len(p['text']) <= D.LIMIT


def test_must_lines_over_the_hard_limit_raise_instead_of_cutting():
    huge = D.Must('가' * 4000)
    with pytest.raises(D.SizeError):
        D.render([post()], {}, NOW, extra_tail=[huge])
    with pytest.raises(D.SizeError):
        D.compose([post()], {}, NOW, [], [huge], {}, {}, {})


def _scan(blk, soft, lo, hi, must=None, limit=D.LIMIT):
    """블록 길이를 1자씩 바꿔 (블록 실림, 줄일 수 있는 줄 실림 목록, 표시 줄, 로그) 를 모은다."""
    out = {}
    for n in range(lo, hi):
        p = blk(n)
        trimmed = []
        text, lines = D.render([p], {}, NOW, extra_tail=(must or []) + soft, limit=limit, trimmed=trimmed)
        parts = text.split('\n\n')
        got = (p['blk'] in parts, [s in parts for s in soft], '길어서 줄인 안내' in text, list(trimmed))
        assert (p['path'] in lines) == got[0]                   # lines 불변식
        assert len(text) <= limit
        for m in must or []:
            assert m in parts
        if not all(got[1]):
            assert got[0] and got[2]                            # ⓐ 한 걸음이라도 줄였으면 첫 블록이 실려 있다
        if not got[0]:
            assert all(got[1]) and not got[2] and not got[3]    # ⓑ 블록이 없으면 안내는 그대로
            assert '…외 1건은 다음 알림에 이어서 보낼게요.' in parts
        out[n] = got
    return out


def test_round13_short_soft_tail_is_never_traded_for_the_block(blk):
    # 15자 꼬리를 빼면 「길어서 줄인 안내」 줄이 더 길다 — 빼도 블록이 안 들어가니 빼지 않는다
    must = [D.Must('꼭' * 150)]
    got = _scan(blk, ['가' * 15], 3200, 3700, must)
    assert all(g[1] == [True] and not g[2] for g in got.values())
    assert got[3200][0] and not got[3699][0]


def test_boundary_soft_tail_goes_only_when_the_block_then_fits(blk):
    must = [D.Must('꼭' * 150)]
    soft = ['가' * 200, '나' * 200]
    got = _scan(blk, soft, 3000, 3700, must)
    kinds = [(g[0], tuple(g[1])) for _, g in sorted(got.items())]
    order = [k for i, k in enumerate(kinds) if i == 0 or kinds[i - 1] != k]
    # 다 실림 → 뒤 하나만 뺌(필요 이상 빼지 않는다) → 둘 다 뺌 → 블록을 미루고 안내는 그대로
    assert order == [(True, (True, True)), (True, (True, False)), (True, (False, False)), (False, (True, True))]
    for g in got.values():                                      # 로그에는 뺀 줄의 원문만
        assert sorted(g[3]) == sorted(s for s, on in zip(soft, g[1]) if not on)


def test_condition_a_block_too_long_leaves_soft_lines_alone(blk):
    p = blk(5000)
    trimmed = []
    soft = '안' * 100
    text, lines = D.render([p], {}, NOW, extra_tail=[D.Must('꼭' * 300), soft], trimmed=trimmed)
    assert soft in text.split('\n\n') and '길어서 줄인 안내' not in text and trimmed == []
    assert '…외 1건은 다음 알림에 이어서 보낼게요.' in text and p['path'] not in lines


def test_condition_c_fixed_overflow_trims_only_as_far_as_needed(blk):
    p = blk(5000)
    text, lines = D.render([p], {}, NOW, notes=[gone_note(400)])
    note = [x for x in text.split('\n') if x.startswith('⚠ ')][0]
    kept = note.split(': ')[1].split(' 외 ')[0].count(',') + 1
    assert kept > 100 and p['path'] not in lines and len(text) <= D.LIMIT
    assert len(text) > D.LIMIT - 120 - 60                       # 고정 부분이 겨우 들어갈 만큼만 줄였다


def _grid_inputs(blk):
    for must in (0, 150, 300):
        for soft in (0, 15, 100, 400):
            for n in (50, 400, 2000, 3000, 3300, 3400, 3500, 3600, 3700, 5000):
                tail = ([D.Must('꼭' * must)] if must else []) + (['가' * soft] if soft else [])
                yield [blk(n)], [], tail
    for names in (0, 3, 100, 250, 280, 290, 400):
        notes = [gone_note(names)] if names else []
        yield [post()], notes, []
        yield _many(1), notes + [D.NOTE_STALE], ['꼬리 줄']
        yield [], notes, ['꼬리 줄']
    yield _many(), [], []


def test_grid_untouched_inputs_match_the_old_render_exactly(blk):
    same = diff = 0
    for limit in (D.LIMIT, 1400):
        for posts, notes, tail in _grid_inputs(blk):
            old_text, old_lines, fixed, first = _render_old(posts, {}, NOW, notes, tail, limit)
            hit = fixed > limit or (first is not None and fixed + first + 2 > limit)
            trimmed = []
            try:
                text, lines = D.render(posts, {}, NOW, notes, tail, limit=limit, trimmed=trimmed)
            except D.SizeError:
                assert hit
                continue
            if not hit:                                         # ⓒ 어느 조건에도 안 걸리면 글자 하나 다르지 않다
                assert (text, lines) == (old_text, old_lines) and trimmed == []
                same += 1
            else:
                diff += 1
            assert not text.endswith('…')
            assert (text, lines) == D.render(posts, {}, NOW, notes, tail, limit=limit)   # 선택 인자 없이도 같다
    assert same > 50 and diff > 20


def test_grid_ab_when_condition_a_trims_first(blk):
    """(가)가 먼저 줄인 뒤의 ⓐⓑ — codex 구현 검토 1회 #2.

    기준 = 같은 안내·꼬리에 절대 안 들어가는 블록(9,000자)을 주고 (가)만 적용한 결과(= 「(가) 뒤 상태」). ⓑ 블록이 없으면 전송본이 기준과 글자 하나 다르지 않다.
    ⓐ 기준보다 더 줄였으면(로그가 더 길면) 블록이 실려 있다. 경계(블록이 빠지기 시작하는 길이) ±2자도 본다.
    """
    def run(n, notes, tail, limit):
        trimmed = []
        p = blk(n)
        text, lines = D.render([p], {}, NOW, notes=notes, extra_tail=tail, limit=limit, trimmed=trimmed)
        assert len(text) <= limit and not text.endswith('…')
        assert (p['path'] in lines) == (p['blk'] in text.split('\n\n'))
        return text, p['blk'] in text.split('\n\n'), trimmed

    orig_fit = D._Budget.fit
    checked = boundary = a_trimmed = 0
    for limit in (D.LIMIT, 1400):
        for names in (0, 120, 250, 290, 400):
            for soft in ([], ['가' * 15], ['가' * 100, '나' * 300]):
                for must in ([], [D.Must('꼭' * 150)]):
                    notes = [gone_note(names)] if names else []
                    # 기준은 같은 코드의 (나)를 거치지 않게 만든다 — fit 을 (가)만으로(first 없이) 부른다
                    with pytest.MonkeyPatch.context() as mp:
                        mp.setattr(D._Budget, 'fit', lambda self, lim, first=None: orig_fit(self, lim))
                        ref_text, ref_in, ref_trim = run(9000, notes, must + soft, limit)
                    assert not ref_in
                    a_trimmed += bool(ref_trim)
                    ns = sorted(set(range(1, limit, 97)))
                    seen = {}
                    for n in ns:
                        seen[n] = run(n, notes, must + soft, limit)
                    cut = next((n for n in ns if not seen[n][1]), None)
                    if cut is not None:
                        for n in range(max(1, cut - 97), min(limit, cut + 3)):   # 경계 ±2자까지 1자씩
                            seen[n] = run(n, notes, must + soft, limit)
                        boundary += 1
                    for n, (text, inside, trim) in seen.items():
                        if not inside:      # ⓑ — 그 대우가 ⓐ(기준보다 더 줄였으면 블록이 실려 있다)
                            assert text == ref_text and trim == ref_trim, (limit, names, len(soft), n)
                        checked += 1
    assert checked > 2000 and boundary > 40 and a_trimmed > 10   # (가)가 먼저 줄인 입력이 실제로 들어 있다


def test_low_limit_keeps_every_must_line_and_defers_posts():
    posts, notes, tail = _worst_must()
    posts = posts + [post()]
    text, lines = D.render(posts, {}, at(2026, 11, 12, 9, 20), notes=notes[:6], extra_tail=tail[:-2], limit=1400)
    assert len(text) > 1400 and len(text) <= D.LIMIT
    for x in tail[:-2]:
        assert x in text.split('\n\n')
    for n in notes[:5]:
        assert '⚠ ' + n in text.split('\n')
    assert '건은 다음 알림에 이어서 보낼게요.' in text and lines == {}


def test_compose_without_the_optional_argument_is_the_same():
    args = (_many(), {}, NOW, [gone_note(400)], ['가' * 500], {}, {}, {})
    trimmed = []
    assert D.compose(*args) == D.compose(*args, trimmed=trimmed)
    assert trimmed == [gone_note(400)] or sorted(trimmed) == sorted([gone_note(400), '가' * 500])


def test_carry_lines_cap_at_six_and_log_the_rest():
    st = {'carry': [{'date': f'2026-11-{d:02d}', 'kind': 'failed'} for d in range(1, 10)]}
    trimmed = []
    got = D.carry_lines(st, date(2026, 11, 10), trimmed)
    assert got == [f'11/{d:02d} 요약 접수 실패' for d in range(4, 9)] + ['어제 요약 접수 실패',
                                                                 '지난 요약 접수 결과 외 3건 — 맥 로그에서 확인']
    assert trimmed == [f'11/{d:02d} 요약 접수 실패' for d in range(1, 4)]
    assert D.carry_lines(st, date(2026, 11, 10)) == got
    st['carry'] = st['carry'][:6]
    assert len(D.carry_lines(st, date(2026, 11, 10))) == 6


# ── A 6. 꼭 싣는 줄의 정수 ────────────────────────────────────────────────────────

def test_shown():
    assert D.shown(0, 9) == '0' and D.shown(9, 9, '건') == '9건' and D.shown(10, 9, '건') == '9건 넘음'
    for bad in (-1, True, 1.0, '3', None, [1]):
        assert D.shown(bad, 9) is None


def test_health_integers_are_capped():
    ok = {'last_outbox_ok': '2026-11-10T00:05:00.000Z', 'backlog': 0, 'failed': 0}
    now = at(2026, 11, 10, 9, 20)
    for bad in (10 ** 300, -1, True, '12', 1.5, None, [], {}):
        line = D.health_lines(dict(ok, backlog=bad, failed=bad), now)[0]
        assert len(line) < 80, line
        assert ('9999건 넘음' in line) == (bad == 10 ** 300)
        assert ('수를 못 읽었어요' in line) == (bad != 10 ** 300)
    assert D.health_lines(dict(ok, backlog=9999), now) == ['전송기: 밀린 알림 9999건']
    assert D.health_lines(dict(ok, last_outbox_ok='1900-01-01T00:00:00Z'), now) == \
        ['전송기: GitHub 계산 기록 마지막 정상 9999시간 넘음']


def test_totals_cap_only_when_printing():
    a = post(number={'kind': 'ok', 'violations': 0, 'warnings': 0, 'counts': COUNTS})
    assert D._totals([a]) == ('최근 7일: 글 1편 · 숫자 위반 0·경고 0(US 일간 자동 검사 범위 안) · '
                              'codex 지적 2건(사실 오류로 확인된 수 아님) · 숫자 판정 불가 0 · 검토 미완료 0')
    b = post(number={'kind': 'ok', 'violations': 1.5, 'warnings': 10 ** 9, 'counts': COUNTS})
    assert '숫자 위반 ?·경고 99999 넘음(' in D._totals([b])
    c = post(number={'kind': 'ok', 'violations': '3', 'warnings': 0, 'counts': COUNTS})
    with pytest.raises(TypeError):
        D._totals([c])                                          # 집계는 안 바꿨다 — _tick 이 요약 만들기 오류로 받는다


# ── A 7. 줄인 원문은 맥 로그에 ──────────────────────────────────────────────────────

def _long_build(V, monkeypatch, note):
    def build(state, now, args, notes):
        notes.append(note)
        return [post()], {}, {'posts/2026-11-06.html': 's1'}
    monkeypatch.setattr(V, 'build', build)


def test_cli_trimmed_originals_go_to_stderr_with_the_id(cli_env, monkeypatch, capsys):
    V, st, w = cli_env
    note = gone_note(400)
    _long_build(V, monkeypatch, note)
    monkeypatch.setattr(D, 'publish_tail', lambda root, now, fetch=True: ['나' * 4000])
    D.save_state(st, {'carry': [{'date': f'2026-11-{d:02d}', 'kind': 'failed'} for d in range(1, 9)]})
    assert V.main([]) == 0
    err = capsys.readouterr().err.split('\n')
    i = err.index(f'줄인 안내 원문 — {SID}')
    assert [x for x in err[i + 1:] if x] == ['11/01 요약 접수 실패', '11/02 요약 접수 실패', note, '나' * 4000]
    text = _texts(w)[0]
    assert SUF in text and '지난 요약 접수 결과 외 2건 — 맥 로그에서 확인' in text and '나' * 4000 not in text
    s = D.load_state(st)                                        # 기록 파일에 새 칸은 없다
    assert set(s) <= {'carry', 'last_attempt', 'last_error', 'last_submitted', 'last_submitted_day',
                      'submitted', 'unconfirmed'}
    assert set(s['unconfirmed'][0]) == {'id', 'date', 'v', 'base', 'accepted_at', 'hash'}


def test_cli_nothing_trimmed_prints_nothing(cli_env, capsys):
    V, st, w = cli_env
    assert V.main([]) == 0
    assert '줄인 안내 원문' not in capsys.readouterr().err


def test_cli_broken_stderr_does_not_stop_the_digest(cli_env, monkeypatch):
    V, st, w = cli_env
    _long_build(V, monkeypatch, gone_note(400))

    class Broken:
        def write(self, s):
            raise OSError(5, 'Input/output error')

        def flush(self):
            raise OSError(5, 'Input/output error')
    monkeypatch.setattr(sys, 'stderr', Broken())
    assert V.main([]) == 0 and len(w.posts) == 1 and SUF in _texts(w)[0]


def test_log_survives_lone_surrogates(capsys):
    import verify_digest as V
    V._log_trimmed('2026-11-09:morning-digest:v1', ['앞 \udc80 뒤'])
    assert '앞 \\udc80 뒤' in capsys.readouterr().err


def test_cli_dry_run_with_trimming_touches_no_file(cli_env, monkeypatch, capsys):
    V, st, w = cli_env
    _long_build(V, monkeypatch, gone_note(400))
    assert V.main(['--dry-run']) == 0
    out = capsys.readouterr()
    assert out.out.startswith('[검증 알림]') and SUF in out.out and '줄인 안내 원문 — ' in out.err
    assert not w.calls and not os.path.exists(st) and not os.path.exists(st + '.lock')
    assert not os.path.exists(os.path.dirname(st))


def test_text_still_returns_two_values(cli_env):
    V, st, w = cli_env
    import argparse
    args = argparse.Namespace(no_fetch=True, no_replay=True, force=False, dry_run=True)
    got = V._text({}, NOW, args, [], [])
    assert len(got) == 2 and got[0]['id'] == SID and got[1] == 1


# ── B. 실패 종류 + 이유 ──────────────────────────────────────────────────────────

def test_set_and_clear_error():
    st = {}
    D.set_error(st, '접수 오류', 'rejected')
    assert st == {'last_error': '접수 오류', 'last_error_why': {'kind': '접수 오류', 'why': 'rejected'}}
    assert D.error_reason(st) == 'Worker 가 제출을 거절했어요'
    D.set_error(st, '기타 오류')
    assert st == {'last_error': '기타 오류'} and D.error_reason(st) is None
    D.set_error(st, '충돌', 'conflict')
    D.clear_error(st)
    assert st == {'last_error': None}


def test_every_reason_sentence_is_a_fixed_note():
    assert len(D.ERROR_WHY) == 19
    for (kind, why), sentence in D.ERROR_WHY.items():
        assert kind in D.ERRORS
        st = {}
        D.set_error(st, kind, why)
        note = f'지난 알림 실패 — {D.error_text(st)}'
        assert note == f'지난 알림 실패 — {kind} — {sentence}'
        assert D.safe_notes([note]) == [note] and D.scrub(note) == (note, 0)
    for kind in D.ERRORS:
        assert D.safe_notes([f'지난 알림 실패 — {kind}']) == [f'지난 알림 실패 — {kind}']
    for other in ('지난 알림 실패 — 접수 오류 — 맥이 지어낸 문장', '지난 알림 실패 — 가나다라', '지난 알림 실패 — 접수 오류 '):
        assert D.safe_notes([other]) == ['기타 안내 1건 — 맥에서 확인']


@pytest.mark.parametrize('why', ['x', ['a'], 3, None, {'kind': '접수 오류'}, {'kind': '접수 오류', 'why': ['rejected']},
                                 {'kind': ['접수 오류'], 'why': 'rejected'}, {'kind': '접수 오류', 'why': {'a': 1}},
                                 {'kind': '접수 오류', 'why': 3}, {'kind': '접수 오류', 'why': 'nope'},
                                 {'kind': '충돌', 'why': 'conflict'}, {'kind': '연결 오류', 'why': 'rejected'}])
def test_damaged_or_stale_reason_shows_the_kind_only(tmp_path, why):
    st = {'last_error': '접수 오류', 'last_error_why': why, 'last_sent': NOW.isoformat()}
    assert D.error_reason(st) is None and D.error_text(st) == '접수 오류'
    p = str(tmp_path / 's.json')
    D.save_state(p, st)
    assert D.digest_note(p, NOW) == '[검증 알림] 마지막 시도 실패 — 접수 오류'


def test_hook_and_head_show_the_reason(tmp_path, cli_env):
    p = str(tmp_path / 's.json')
    st = {'last_sent': NOW.isoformat()}
    D.set_error(st, '전송 보류', 'held')
    D.save_state(p, st)
    assert D.digest_note(p, NOW) == ('[검증 알림] 마지막 시도 실패 — 전송 보류 — Worker 가 접수만 하고 보내지 않았어요'
                                     '(보류 — Worker 는 하루 두 판까지만 보내요)')
    D.save_state(p, {'last_sent': NOW.isoformat(), 'last_error': '텔레그램 /Users/x',
                     'last_error_why': {'kind': '기타 오류', 'why': 'x'}})
    assert D.digest_note(p, NOW) == '[검증 알림] 마지막 시도 실패 — 기타 오류'


def test_attempt_records_kind_and_reason_together():
    w = FakeWorker()
    for step, kind, why in (((400, ''), '접수 오류', 'rejected'), ((500, ''), '연결 오류', 'server'),
                            ((200, '<html>'), '연결 오류', 'server'), ('drop', '연결 오류', 'noresp')):
        st = {'pending': _pending(), 'last_error': '충돌', 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}
        w.script = [step]
        _attempt(st, at(2026, 11, 9, 10), w)
        assert (st['last_error'], st['last_error_why']) == (kind, {'kind': kind, 'why': why})
    w.events[SID] = {'body': 'other', 'state': 'accepted'}
    st = {'pending': _pending()}
    assert _attempt(st, at(2026, 11, 9, 10), w) == 'conflict'
    assert st['last_error_why'] == {'kind': '충돌', 'why': 'conflict'}
    w = FakeWorker()
    st = {'pending': _pending(), 'last_error': '충돌', 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}
    assert _attempt(st, at(2026, 11, 9, 10), w) == 'accepted'
    assert st['last_error'] is None and 'last_error_why' not in st          # mark_accepted 가 지운다
    st = {'pending': _pending(), 'last_error': '충돌', 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}
    w.script = [(401, '')]
    _attempt(st, at(2026, 11, 9, 10), w)
    assert st['last_error'] == '제출 키 오류' and 'last_error_why' not in st and D.error_reason(st) is None


def _security_boom(args, **kw):
    raise subprocess.TimeoutExpired(args, 20)


@pytest.mark.parametrize('worker,why', [(FakeWorker(url=''), 'cfg_url'), (FakeWorker(url='http://x'), 'cfg_url'),
                                        (FakeWorker(key=''), 'cfg_key'), (FakeWorker(key='짧'), 'cfg_key'),
                                        (_security_boom, 'cfg_read')])
def test_config_error_carries_a_code(worker, why):
    st = {'pending': _pending()}
    with pytest.raises(D.ConfigError) as e:
        _attempt(st, NOW, worker)
    assert e.value.why == why and D.config_why(e.value) == why
    assert st['last_error_why'] == {'kind': '제출 키 없음', 'why': why}


def test_config_error_without_a_known_code_is_cfg():
    assert D.config_why(D.ConfigError('x')) == 'cfg' and D.config_why(D.ConfigError('x', why=['a'])) == 'cfg'

    def post_(body, sid):
        raise D.ConfigError('옛 꼴')
    st = {'pending': _pending()}
    with pytest.raises(D.ConfigError):
        D.attempt(st, NOW, lambda s: None, post_)
    assert D.error_reason(st) == '키체인의 제출 키나 Worker 주소를 확인해 주세요'


def test_confirm_records_reasons():
    now = at(2026, 11, 10, 9)
    u = _unc('2026-11-09')
    for state, kind, why in (('failed_permanent', '전송 오류', 'failed_permanent'), ('held', '전송 보류', 'held')):
        st = {'unconfirmed': [dict(u)]}
        D.confirm(st, {u['id']: _ev(u, state)}, now)
        assert st['last_error_why'] == {'kind': kind, 'why': why}
    nohash_ev = _ev(u)
    nohash_ev.pop('hash')
    legacy = dict(u)
    legacy.pop('hash')
    for mine, ev, why, sentence in (
            (legacy, _ev(u), 'nohash_mac', '맥의 접수 기록에 본문 대조 값이 없어 대조하지 못했어요'),
            (dict(u), nohash_ev, 'nohash_worker', 'Worker 응답에서 본문 대조 값을 확인하지 못했어요'),
            (dict(u), dict(nohash_ev, hash='zz'), 'nohash_worker', 'Worker 응답에서 본문 대조 값을 확인하지 못했어요'),
            (legacy, nohash_ev, 'nohash', '본문 대조 값을 확인하지 못했어요')):
        st = {'unconfirmed': [dict(mine)], 'lines': {}}
        assert D.confirm(st, {u['id']: ev}, now)
        assert st['last_error_why'] == {'kind': '확인 불가', 'why': why} and st['lines'] == {}
        assert st['carry'] == [{'date': '2026-11-09', 'kind': 'unverified', 'why': why}]
        assert D.carry_lines(st, now.date()) == [f'어제 요약 전송 확인 불가 — {sentence}']
        assert D.error_reason(st) == sentence
    # 목록에 없다 — 14일이 지났거나 접수 날짜를 못 읽었다. 「14일이 지나」라고 단정하지 않는다
    for item in (dict(u), dict(u, date='날짜 아님')):
        st = {'unconfirmed': [item]}
        assert D.confirm(st, {}, at(2026, 11, 30, 9))
        assert st['last_error_why'] == {'kind': '확인 불가', 'why': 'absent'}
        assert '14일이 지나' not in D.error_reason(st) and '최근 14일' in D.error_reason(st)
    st = {'unconfirmed': [dict(u)], 'last_error': '확인 불가', 'last_error_why': {'kind': '확인 불가', 'why': 'absent'}}
    D.confirm(st, {u['id']: _ev(u)}, now)                       # 성공 확인이 지운다
    assert st['last_error'] is None and 'last_error_why' not in st


def test_settle_auth_and_migrate_keep_kind_and_reason_in_step():
    now = at(2026, 11, 10, 9, 20)
    st = {'pending': _tried('conflict'), 'last_error': '충돌', 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent', 'hash': D.text_hash('다른')}, True) == 'conflict'
    assert st['last_error'] is None and 'last_error_why' not in st
    st = {'last_error': '충돌', 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}
    D.auth_failed(st, now)
    assert st['last_error'] == '제출 키 오류' and 'last_error_why' not in st
    st = D.migrate({'last_error': 'OSError: /Users/x', 'last_error_why': {'kind': 'x', 'why': 'y'}})
    assert st == {'last_error': '기타 오류'}
    assert D.migrate({'last_error': None, 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}) == {'last_error': None}
    assert D.migrate({'last_error_why': 'x'}) == {}
    keep = {'last_error': '충돌', 'last_error_why': {'kind': '충돌', 'why': 'conflict'}}
    assert D.migrate(dict(keep)) == keep


def test_no_direct_assignment_to_last_error_outside_the_two_functions():
    import inspect
    import verify_digest as V
    own = inspect.getsource(D.set_error) + inspect.getsource(D.clear_error)
    # 대입·키워드 인자 꼴, 그리고 dict 글자 꼴(state.update({'last_error': …}) 같은 우회 — codex 구현 검토 1회 #1)
    rx = re.compile(r'''\[['"]last_error(?:_why)?['"]\]\s*=(?!=)|\blast_error(?:_why)?\s*=(?!=)'''
                    r'''|['"]last_error(?:_why)?['"]\s*:''')
    for bypass in ("state.update({'last_error': '충돌'})", 'state.update(last_error="충돌")',
                   "st['last_error_why'] = x", 'dict(state, **{"last_error_why": 1})'):
        assert rx.search(bypass), bypass
    assert not rx.search("state.get('last_error') == '충돌'")
    assert len(rx.findall(own)) >= 2
    for mod in (D, V):
        src = inspect.getsource(mod).replace(inspect.getsource(D.set_error), '').replace(
            inspect.getsource(D.clear_error), '')
        assert rx.findall(src) == [], mod.__name__
        assert not re.search(r'''setdefault\(['"]last_error|pop\(['"]last_error['"]''', src)


def test_cli_fail_paths_record_reasons(cli_env, monkeypatch, capsys):
    V, st, w = cli_env
    w.key = ''
    assert V.main([]) == 1
    assert D.load_state(st)['last_error_why'] == {'kind': '제출 키 없음', 'why': 'cfg_key'}
    w.key = FakeWorker().key
    monkeypatch.setattr(V, 'build', lambda *a: (_ for _ in ()).throw(KeyError('/Users/x')))
    assert V.main([]) == 1
    s = D.load_state(st)
    assert s['last_error_why'] == {'kind': '요약 만들기 오류', 'why': 'exception'} and '/Users/' not in json.dumps(s)
    assert '맥 로그' in D.digest_note(st, w.clock['now'])
    monkeypatch.setattr(V, 'build', lambda state, now, args, notes: ([post()], {}, {}))
    monkeypatch.setattr(D, 'publish_tail', lambda root, now, fetch=True: [D.Must('가' * 4000)])
    assert V.main([]) == 1
    assert D.load_state(st)['last_error_why'] == {'kind': '크기 초과', 'why': 'size'}


def test_cli_totals_type_error_becomes_exception_reason(cli_env, monkeypatch):
    V, st, w = cli_env
    bad = post(number={'kind': 'ok', 'violations': '3', 'warnings': 0, 'counts': COUNTS})
    monkeypatch.setattr(V, 'build', lambda state, now, args, notes: ([bad], {}, {}))
    assert V.main([]) == 1
    assert D.load_state(st)['last_error_why'] == {'kind': '요약 만들기 오류', 'why': 'exception'}


def test_cli_version_limit_reason(cli_env):
    V, st, w = cli_env
    D.save_state(st, {'submitted': {'date': '2026-11-09', 'v': 9}, 'last_submitted_day': '2026-11-09'})
    assert V.main(['--force']) == 1
    assert D.load_state(st)['last_error_why'] == {'kind': '요약 만들기 오류', 'why': 'max_versions'}


def test_cli_next_digest_head_carries_the_reason(cli_env):
    V, st, w = cli_env
    w.script = ['drop']
    assert V.main([]) == 1
    assert '응답을 받지 못했어요' in D.digest_note(st, w.clock['now'])
    w.clock['now'] = at(2026, 11, 9, 10, 20)
    assert V.main([]) == 0 and D.load_state(st)['last_error'] is None
    s = D.load_state(st)
    D.set_error(s, '전송 오류', 'failed_permanent')
    s['unconfirmed'] = []
    D.save_state(st, s)
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    assert ('⚠ 지난 알림 실패 — 전송 오류 — Worker 가 이 요약을 영구 실패로 처리했어요 — 이유는 Worker 가 보내는 경보에서 '
            '확인해 주세요') in _texts(w)[-1].split('\n')


def test_cli_lock_set_and_lock_open(cli_env, monkeypatch):
    V, st, w = cli_env
    import fcntl
    D.save_state(st, {'last_sent': NOW.isoformat()})

    def bad(fd, op):
        raise OSError(5, 'Input/output error')
    monkeypatch.setattr(fcntl, 'flock', bad)
    assert V.main([]) == 1
    assert D.load_state(st)['last_error_why'] == {'kind': '잠금 오류', 'why': 'lock_set'}
    monkeypatch.undo()


def test_cli_lock_file_cannot_be_opened(tmp_path, monkeypatch, capsys):
    import verify_digest as V
    st = str(tmp_path / 'st' / 'state.json')
    monkeypatch.setenv(D.STATE_ENV, st)
    monkeypatch.setattr(D, 'now_kst', lambda: at(2026, 11, 9, 9, 20))
    D.save_state(st, {'last_sent': NOW.isoformat()})
    os.mkdir(st + '.lock')                                       # 잠금 파일 자리에 폴더 — open 이 실패한다
    assert V.main([]) == 1
    assert D.load_state(st)['last_error_why'] == {'kind': '잠금 오류', 'why': 'lock_open'}
    assert D.digest_note(st, at(2026, 11, 9, 9, 20)).endswith('잠금 오류 — 잠금 파일을 열지 못했어요')


def test_cli_state_folder_cannot_be_made(tmp_path, monkeypatch, capsys):
    import verify_digest as V
    (tmp_path / 'st').write_text('폴더 자리에 파일')
    monkeypatch.setenv(D.STATE_ENV, str(tmp_path / 'st' / 'state.json'))
    monkeypatch.setattr(D, 'now_kst', lambda: at(2026, 11, 9, 9, 20))
    assert V.main([]) == 1                                       # 저장도 못 한다 — stderr 에만 남는다
    assert '잠금' in capsys.readouterr().err


# ── C·D. 전송기 줄 ────────────────────────────────────────────────────────────────

BASE = '전송기: 상태를 못 읽었어요 — 전송 여부를 몰라요'


def test_health_none_says_why():
    want = {'auth': 'Worker 가 제출 키를 받지 않았어요(401)', 'noresp': '응답을 받지 못했어요',
            'json': '응답이 JSON 이 아니었어요', 'format': '응답 형식이 약속과 달랐어요',
            'event': '사건 목록에 약속과 다른 항목이 있었어요', 'health': '응답에 전송기 상태가 없거나 형식이 달랐어요'}
    for why, sentence in want.items():
        assert D.health_lines(None, NOW, why=why) == [f'{BASE}({sentence})']
    assert D.health_lines(None, NOW, why='http', status=503) == [f'{BASE}(HTTP 503 응답을 받았어요)']
    for bad in (None, 99, 600, True, '503', 5.0, [503]):
        assert D.health_lines(None, NOW, why='http', status=bad) == [f'{BASE}(응답 형식이 약속과 달랐어요)']
    for why in (None, 'x', ['auth'], 3, {'a': 1}):
        assert D.health_lines(None, NOW, why=why) == [BASE]
    assert D.health_lines('문자열', NOW, why='health') == [f'{BASE}(응답에 전송기 상태가 없거나 형식이 달랐어요)']


def test_fetch_status_errors_carry_codes():
    w = FakeWorker()

    def code_of(**kw):
        with pytest.raises(D.TransportError) as e:
            D.fetch_status(run=w)
        return type(e.value), e.value.why, e.value.status
    w.status_down = True
    assert code_of() == (D.TransportError, 'noresp', None)
    w.status_down, w.status_code = False, 503
    assert code_of() == (D.TransportError, 'http', 503)
    w.status_code = 401
    assert code_of() == (D.AuthError, 'auth', 401)
    w.status_code = None
    real = w._out
    for text, why in (('<html>', 'json'), ('{"format": "x"}', 'format'),
                      ('{"format": "digest-status/1", "events": [3]}', 'event')):
        w._out = lambda args, code, _t, text=text: real(args, 200, text)
        assert code_of() == (D.TransportError, why, None)


def test_cli_health_reasons_reach_the_digest(cli_env):
    V, st, w = cli_env
    w.status_code = 503
    assert V.main([]) == 0
    assert f'{BASE}(HTTP 503 응답을 받았어요)' in _texts(w)[0].split('\n\n')


def test_cli_missing_health_object_still_confirms_events(cli_env):
    V, st, w = cli_env
    assert V.main([]) == 0
    w.send(SID, '2026-11-09T00:21:07.000Z')
    w.health = None
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    s = D.load_state(st)
    assert s['last_sent'] == '2026-11-09T00:21:07.000Z' and 'posts/2026-11-06.html' in s['lines']   # 사건 확인은 그대로
    assert f'{BASE}(응답에 전송기 상태가 없거나 형식이 달랐어요)' in _texts(w)[-1].split('\n\n')
    w.health = '객체 아님'
    assert V.main(['--force']) == 0
    assert f'{BASE}(응답에 전송기 상태가 없거나 형식이 달랐어요)' in _texts(w)[-1].split('\n\n')


def test_cli_status_401_says_auth(cli_env):
    V, st, w = cli_env
    real = D.post_digest
    w.status_code = 401
    assert V.main([]) == 0
    assert f'{BASE}(Worker 가 제출 키를 받지 않았어요(401))' in _texts(w)[0].split('\n\n')


def test_config_error_line_four_shapes():
    now = at(2026, 11, 12, 9, 20)
    ok = {'last_outbox_ok': '2026-11-12T00:05:00.000Z', 'backlog': 0, 'failed': 0}

    def line(ce):
        return D.health_lines(dict(ok, config_error=ce), now)
    head = '전송기: 설정 오류 — 텔레그램으로 못 보내는 중'
    assert line({'code': 401, 'kind': 'token', 'since': '2026-11-12T00:00:00Z'}) == \
        [f'{head}(Worker 분류: 봇 토큰, 11/12 09:00 부터 · Cloudflare 설정 확인)']
    assert line({'kind': 'chat', 'since': '2026-11-11T15:30:00.000Z'}) == \
        [f'{head}(Worker 분류: 대화 번호, 11/12 00:30 부터 · Cloudflare 설정 확인)']
    assert line({'kind': 'forbidden', 'since': None}) == \
        [f'{head}(Worker 분류: 봇이 대화에서 차단·강퇴됨 · Cloudflare 설정 확인)']
    for kind in ('token /Users/x', ['token'], {'a': 1}, 3, None):
        assert line({'kind': kind, 'since': '2026-11-12T00:00:00Z'}) == \
            [f'{head}(11/12 09:00 부터 · Cloudflare 설정 확인)']
    for since in ('9999-12-31T23:59:59-12:00', '0001-01-01T00:00:00+14:00', 3, None, 'x', ['2026'], '2026-11-12T00:00:00'):
        assert line({'kind': 'token', 'since': since}) == [f'{head}(Worker 분류: 봇 토큰 · Cloudflare 설정 확인)'], since
        assert line({'kind': 'nope', 'since': since}) == [f'전송기: {D.CONFIG_ERROR}']
    for ce in (True, 'x', [1], 3, {}):
        assert line(ce) == [f'전송기: {D.CONFIG_ERROR}']
    assert line(None) == []


def test_outbox_time_overflow_is_unreadable_not_a_crash(tmp_path):
    now = at(2026, 11, 12, 9, 20)
    for t in ('9999-12-31T23:59:59-12:00', '0001-01-01T00:00:00+14:00'):
        got = D.health_lines({'last_outbox_ok': t, 'backlog': 0, 'failed': 0}, now)
        # 파이썬의 시각 빼기는 이 값들에서 넘치지 않는다 — 먼 미래는 지금처럼 조용하고, 먼 과거는 상한 문구다
        assert got == ([] if t.startswith('9999') else ['전송기: GitHub 계산 기록 마지막 정상 9999시간 넘음'])
        p = str(tmp_path / 's.json')
        D.save_state(p, {'last_sent': t})
        assert isinstance(D.digest_note(p, now), str)
        u = {'id': SID, 'date': '2026-11-09', 'v': 1, 'base': {}, 'accepted_at': t}
        D.save_state(p, {'last_sent': now.isoformat(), 'unconfirmed': [u]})
        assert isinstance(D.digest_note(p, now), str)


def test_health_lines_never_raise():
    junk = [None, 'x', ['a'], {'a': 1}, 10 ** 400, -5, 1.5, True, '2026-11-12T00:00:00Z', '9999-12-31T23:59:59-12:00']
    now = at(2026, 11, 12, 9, 20)
    for key in ('config_error', 'backlog', 'failed', 'last_outbox_ok'):
        for v in junk:
            h = {'last_outbox_ok': '2026-11-12T00:05:00.000Z', 'backlog': 0, 'failed': 0, key: v}
            got = D.health_lines(h, now)
            assert len(got) <= 1 and all(len(x) < 300 for x in got)
            for inner in junk:
                D.health_lines(dict(h, config_error={'kind': v, 'since': inner, 'code': inner}), now)
    for h in junk:
        for why in junk:
            assert len(D.health_lines(h if isinstance(h, dict) else h, now, why=why, status=why)) <= 1


# ── E. 발행 알림 꼬리 ───────────────────────────────────────────────────────────────

class Git:
    """명령마다 반환 코드나 예외를 정한다."""

    def __init__(self, blob=None, **codes):
        self.show, self.codes, self.calls = blob, codes, []

    def __call__(self, args, **kw):
        cmd = args[3].replace('-', '_')
        self.calls.append(args[3])
        code = self.codes.get(cmd, 0)
        if isinstance(code, BaseException):
            raise code
        out = b''
        if cmd == 'show':
            code, out = (code, self.show) if self.show is not None and not code else (code or 128, b'')
        return subprocess.CompletedProcess(args, code, out, b'')


TIMEOUT = subprocess.TimeoutExpired(['git'], 60)
OSERR = OSError(2, 'No such file or directory: git')
COPY = '발행 알림: 최신 상태를 받지 못해 받아 둔 사본으로 읽었어요'
NOW10 = at(2026, 11, 10, 9)


def tail(git, fetch=True):
    got = D.publish_tail('/repo', NOW10, fetch=fetch, run=git)
    assert all(isinstance(x, (D.Must, D.Soft)) for x in got)
    return got


def test_tail_missing_branch_ends_there_even_with_an_old_copy():
    g = Git(_publish_state(), ls_remote=2)
    got = tail(g)
    assert got == [D.TAIL_MISSING] and isinstance(got[0], D.Must) and g.calls == ['ls-remote']


def test_tail_remote_failures_fall_back_to_the_copy(monkeypatch):
    from review import publish_watch as W
    monkeypatch.setattr(W, 'summary_lines_from', lambda st, now, stale=None: ['아직 안 올라온 세션: KR 일간 11/09'])
    for codes, why in (({'ls_remote': 1}, '원격 확인 실패'), ({'ls_remote': 128}, '원격 확인 실패'),
                       ({'ls_remote': TIMEOUT}, '원격 확인 실패'), ({'ls_remote': OSERR}, '원격 확인 실패'),
                       ({'fetch': 1}, 'git fetch 실패'), ({'fetch': TIMEOUT}, 'git fetch 실패')):
        got = tail(Git(_publish_state(), **codes))
        assert got == [f'{COPY}({why})', '아직 안 올라온 세션: KR 일간 11/09'], codes
        assert isinstance(got[0], D.Must) and isinstance(got[1], D.Soft)
        got = tail(Git(None, rev_parse=1, **codes))                     # 사본도 없다
        assert got == [D.tail_unread(why, '받아 둔 사본 없음')] and isinstance(got[0], D.Must)
        assert got[0] == f'발행 알림: 상태를 못 읽었어요({why} · 받아 둔 사본 없음) — 미발행·전송 여부를 몰라요'
        got = tail(Git(None, **codes))                                  # 사본은 있는데 파일을 못 읽는다
        assert got == [D.tail_unread(why, '받아 둔 사본에서 파일을 못 읽음')]
    got = tail(Git(_publish_state()))
    assert got == ['아직 안 올라온 세션: KR 일간 11/09'] and isinstance(got[0], D.Soft)


def test_tail_local_failures():
    assert tail(Git(_publish_state(), rev_parse=TIMEOUT)) == [D.tail_unread('받아 둔 사본을 확인하지 못함')]
    assert tail(Git(_publish_state(), rev_parse=1)) == [D.TAIL_MISSING]
    assert tail(Git(_publish_state(), show=TIMEOUT)) == [D.tail_unread('받아 둔 사본에서 파일을 못 읽음')]
    assert tail(Git(None)) == [D.tail_unread('받아 둔 사본에서 파일을 못 읽음')]
    for broken in (b'{broken', b'{"format": "other"}', b'{"format": "verify-publish/1"}'):
        assert tail(Git(broken)) == [D.tail_unread('상태 파일 내용 검증 실패')]
    assert tail(Git(_publish_state(), ls_remote=TIMEOUT, rev_parse=TIMEOUT)) == \
        [D.tail_unread('원격 확인 실패', '받아 둔 사본을 확인하지 못함')]
    assert D.tail_unread() == D.TAIL_UNREAD


def test_tail_calculation_errors(monkeypatch):
    from review import publish_watch as W
    import review

    def boom(*a, **kw):
        raise KeyError('/Users/x')
    monkeypatch.setattr(W, 'summary_lines_from', boom)
    assert tail(Git(_publish_state())) == [D.tail_unread('요약 꼬리 계산 오류')]
    monkeypatch.setattr(W, 'loads_state', boom)
    assert tail(Git(_publish_state())) == [D.tail_unread('요약 꼬리 계산 오류')]
    assert tail(Git(_publish_state(), fetch=1)) == [D.tail_unread('git fetch 실패', '요약 꼬리 계산 오류')]
    blob = _publish_state()
    monkeypatch.setitem(sys.modules, 'review.publish_watch', None)
    monkeypatch.delattr(review, 'publish_watch', raising=False)
    assert tail(Git(blob)) == [D.tail_unread('요약 꼬리 계산 오류')]


def test_tail_no_fetch(monkeypatch):
    from review import publish_watch as W
    monkeypatch.setattr(W, 'summary_lines_from', lambda st, now, stale=None: ['x'])
    g = Git(_publish_state(), ls_remote=1, fetch=1)
    assert tail(g, fetch=False) == ['x'] and g.calls == ['rev-parse', 'show']      # 원격을 안 보니 사본 안내도 없다
    got = tail(Git(None, rev_parse=1), fetch=False)
    assert got == ['발행 알림: 받아 둔 사본이 없어요(원격 확인 안 함)'] and isinstance(got[0], D.Must)
    assert '아직 없어요' not in got[0]


def test_tail_must_lines_survive_a_tight_digest(monkeypatch):
    from review import publish_watch as W
    soft = '아직 안 올라온 세션: ' + ', '.join(['KR 일간 11/09'] * 40)
    monkeypatch.setattr(W, 'summary_lines_from', lambda st, now, stale=None: [soft])
    for git, must in ((Git(None), D.tail_unread('받아 둔 사본에서 파일을 못 읽음')),
                      (Git(_publish_state(), ls_remote=2), D.TAIL_MISSING),
                      (Git(_publish_state(), fetch=1), f'{COPY}(git fetch 실패)')):
        got = tail(git)
        text, _ = D.render([post()], {}, NOW, notes=[gone_note(400)], extra_tail=got + ['표시 없는 줄 ' + '가' * 300],
                           limit=700)
        parts = text.split('\n\n')
        assert must in parts and soft not in parts and not any('표시 없는 줄' in x for x in parts)


# ── F. [발행 전 기록] 읽지 못했어요 — 이유 ──────────────────────────────────────────────

PRE = ' · [발행 전 기록] 읽지 못했어요'


def _pp(**kw):
    p = {'path': 'posts/2026-11-09.html', 'sha': 's', 'state': '완료', 'findings': 0, 'number': None, 'auto': True,
         'draft': False}
    p.update(kw)
    return p


def test_prepub_error_codes_become_fixed_lines():
    for code, want in (('module', f'{PRE}(기록을 읽는 모듈을 불러오지 못했어요)'),
                       ('read', f'{PRE}(git 이나 기록 파일을 읽지 못했어요)'),
                       ('render', f'{PRE}(기록을 문장으로 옮기지 못했어요)'),
                       ('other', PRE), ('모르는 코드', PRE), ('OSError: /Users/x', PRE), (['read'], PRE), (3, PRE),
                       ({'a': 1}, PRE), (True, PRE)):
        lines = D.block(_pp(prepub={'error': code})).split('\n')
        assert lines[1] == want and '[발행 뒤 재검사] 숫자' in lines[2] and '/Users/' not in '\n'.join(lines), code


def test_prepub_lines_survive_import_failure_and_render_failure(monkeypatch):
    from review import prepub_view as PV
    import review
    monkeypatch.setattr(PV, 'digest_lines', lambda pv: (_ for _ in ()).throw(KeyError('x')))
    assert D.block(_pp(prepub={'kind': 'x'})).split('\n')[1] == f'{PRE}(기록을 문장으로 옮기지 못했어요)'
    monkeypatch.setitem(sys.modules, 'review.prepub_view', None)
    monkeypatch.delattr(review, 'prepub_view', raising=False)
    lines = D.block(_pp(prepub={'kind': 'x'})).split('\n')
    assert lines[1] == f'{PRE}(기록을 읽는 모듈을 불러오지 못했어요)' and '숫자' in lines[2]
    assert D.block(_pp(prepub={'error': 'read'})).split('\n')[1] == f'{PRE}(git 이나 기록 파일을 읽지 못했어요)'
    text, lines = D.render([_pp(prepub={'kind': 'x'})], {}, at(2026, 11, 10))      # 요약이 완성된다
    assert f'{PRE}(기록을 읽는 모듈을 불러오지 못했어요)' in text and '최근 7일' in text


def _build(monkeypatch, tmp_path):
    import argparse
    import review_gate as G
    import verify_digest as V
    path = 'posts/2026-11-09.html'
    monkeypatch.setattr(G, 'repo_root', lambda: str(tmp_path))
    monkeypatch.setattr(V, '_published_view', lambda G, root, fetch: ({path: 's1'}, {}, {}, False, set()))
    monkeypatch.setattr(D, 'kr_weekly_aggs', lambda root: {})
    args = argparse.Namespace(no_fetch=True, no_replay=True)
    return lambda: V.build({}, at(2026, 11, 10), args, [])[0][0]


def test_build_stores_a_code_not_the_exception_text(monkeypatch, tmp_path, capsys):
    from review import prepub_view as PV
    import review
    build = _build(monkeypatch, tmp_path)

    def git_error(*a):
        raise PV.GitError('fatal: /Users/x bad object')
    monkeypatch.setattr(PV, 'view', git_error)
    assert build()['prepub'] == {'error': 'read'}
    assert '/Users/x bad object' in capsys.readouterr().err       # 자세한 문장은 맥 로그에만
    monkeypatch.setattr(PV, 'view', lambda *a: (_ for _ in ()).throw(KeyError('/Users/x')))
    assert build()['prepub'] == {'error': 'other'}
    monkeypatch.setitem(sys.modules, 'review.prepub_view', None)
    monkeypatch.delattr(review, 'prepub_view', raising=False)
    p = build()
    assert p['prepub'] == {'error': 'module'}
    assert f'{PRE}(기록을 읽는 모듈을 불러오지 못했어요)' in D.block(p) and '숫자' in D.block(p)


# ── G. 지난 요약 접수 결과 ────────────────────────────────────────────────────────────

def _none(sid):
    return None


def _down(sid):
    raise D.TransportError('응답 없음')


def test_settle_survives_damaged_try_results():
    now = at(2026, 11, 10, 9, 20)
    for bad in (['rejected'], {'a': 1}, 3, None):
        p = _tried('rejected')
        p['tries'] += [{'at': 'x', 'result': bad}, 'dict 아님', {'at': 'x'}]
        st = {'pending': p}
        kept = []
        assert D.settle(st, now, _none, True, lambda p, o: kept.append((p['id'], o))) == 'unknown'
        assert kept == [(SID, 'unknown')] and 'pending' not in st
        assert st['carry'] == [{'date': '2026-11-09', 'kind': 'unknown', 'lookup': 'absent',
                                'tries': {'rejected': 1, 'other': 3}}]
        assert D.carry_lines(st, now.date()) == \
            ['어제 요약 접수 여부 확인 불가(제출 시도 4번: 기타 3 · 거절 1 · Worker 상태 목록에 그 사건이 없었어요)']


def test_settle_verdicts_are_unchanged():
    now = at(2026, 11, 10, 9, 20)
    st = {'pending': _tried('rejected', 'rejected')}
    assert D.settle(st, now, _down, True) == 'failed'
    st = {'pending': _tried('rejected', 'conflict')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent'}, True) == 'conflict'
    st = {'pending': _tried('noresp')}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent', 'hash': D.text_hash('다른')}, True) == 'conflict'
    assert D.carry_lines(st, now.date()) == ['어제 요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요']
    st = {'pending': _tried('noresp', 'weird')}                  # 모르는 문자열 결과는 지금처럼 그대로 본다
    assert D.settle(st, now, _none, True) == 'unknown' and st['carry'][0]['tries'] == {'noresp': 1, 'other': 1}


def test_carry_sentences_say_what_was_tried_and_what_the_lookup_saw():
    now = at(2026, 11, 10, 9, 20)
    day = now.date()
    st = {'pending': _tried('rejected', 'rejected')}
    D.settle(st, now, _none, True)
    assert D.carry_lines(st, day) == ['어제 요약 접수 실패(제출 시도 2번: 거절 2)']
    st = {'pending': _tried()}
    assert D.settle(st, now, _down, True) == 'failed'            # 판정은 그대로, 문구는 「거절」을 암시하지 않는다
    assert st['carry'][0]['tries'] == {}
    assert D.carry_lines(st, day) == ['어제 요약 접수 실패(제출을 한 번도 내보내지 못했어요)']
    for lookup, word in ((_none, 'Worker 상태 목록에 그 사건이 없었어요'), (_down, '마지막 확인 때 Worker 상태를 읽지 못했어요'),
                         (lambda sid: {'id': sid, 'state': 'sent'}, 'Worker 응답에서 본문 대조 값을 확인하지 못했어요'),
                         (lambda sid: {'id': sid, 'state': 'sent', 'hash': 'zz'},
                          'Worker 응답에서 본문 대조 값을 확인하지 못했어요')):
        st = {'pending': _tried('noresp', 'server', 'noresp')}
        assert D.settle(st, now, lookup, True) == 'unknown'
        assert D.carry_lines(st, day) == \
            [f'어제 요약 접수 여부 확인 불가(제출 시도 3번: 응답 못 받음 2 · 약속에 없는 응답 1 · {word})']
    st = {'pending': _tried('conflict')}
    D.settle(st, now, _none, True)
    assert D.carry_lines(st, day) == ['어제 요약 접수 여부 확인 불가(제출 시도 1번: 409 1 · Worker 상태 목록에 그 사건이 없었어요)']
    st = {'pending': _tried()}
    assert D.settle(st, now, lambda sid: {'id': sid, 'state': 'sent'}, True) == 'unknown'
    assert D.carry_lines(st, day) == \
        ['어제 요약 접수 여부 확인 불가(제출을 한 번도 내보내지 못했어요 · Worker 응답에서 본문 대조 값을 확인하지 못했어요)']


def test_carry_lines_read_old_and_damaged_entries_without_raising():
    day = date(2026, 11, 10)

    def one(**kw):
        return D.carry_lines({'carry': [dict({'date': '2026-11-09'}, **kw)]}, day)
    assert one(kind='failed') == ['어제 요약 접수 실패']                                   # tries 칸 없는 옛 기록
    assert one(kind='unknown') == ['어제 요약 접수 여부 확인 불가']
    assert one(kind='unverified') == ['어제 요약 전송 확인 불가 — 본문 대조 값을 확인하지 못했어요']
    for why in (['nohash'], 3, {'a': 1}, 'nope', 'absent'):
        assert one(kind='unverified', why=why) == ['어제 요약 전송 확인 불가 — 본문 대조 값을 확인하지 못했어요']
    for tries in ('x', ['rejected'], 3, None):
        assert one(kind='failed', tries=tries) == ['어제 요약 접수 실패']
        assert one(kind='unknown', tries=tries, lookup='absent') == \
            ['어제 요약 접수 여부 확인 불가(Worker 상태 목록에 그 사건이 없었어요)']
    for lookup in (['absent'], 3, {'a': 1}, 'nope'):
        assert one(kind='unknown', tries={'noresp': 1}, lookup=lookup) == \
            ['어제 요약 접수 여부 확인 불가(제출 시도 1번: 응답 못 받음 1)']
    junk = {'rejected': True, 'server': 1.0, 'noresp': -1, 'conflict': '2', 'other': None, 'x': 5, 3: 1}
    assert one(kind='failed', tries=junk) == ['어제 요약 접수 실패']                        # 쓸 수 있는 항이 없다
    assert one(kind='failed', tries=dict(junk, rejected=2)) == ['어제 요약 접수 실패(제출 시도 2번: 거절 2)']
    assert one(kind='failed', tries={'rejected': 0}) == ['어제 요약 접수 실패(제출을 한 번도 내보내지 못했어요)']
    assert one(kind='failed', tries={}) == ['어제 요약 접수 실패(제출을 한 번도 내보내지 못했어요)']
    # 빠진 항이 하나라도 있으면 유효한 합 0 은 「시도 0번」이 아니다 — 횟수 문구를 통째로 뺀다(codex 구현 2회)
    for bad in ({'rejected': 0, 'other': '3'}, {'rejected': 0, 'x': 5}, {'noresp': 0, 'server': True},
                {'rejected': 0, 'conflict': -1}, {'rejected': 0, 3: 1}):
        assert one(kind='failed', tries=bad) == ['어제 요약 접수 실패']
        assert one(kind='unknown', tries=bad, lookup='absent') == \
            ['어제 요약 접수 여부 확인 불가(Worker 상태 목록에 그 사건이 없었어요)']
    big = one(kind='unknown', tries={'rejected': 10 ** 300, 'noresp': 1000, 'server': 999}, lookup='unread')
    assert big == ['어제 요약 접수 여부 확인 불가(제출 시도 999번 넘음: 거절 999 넘음 · 응답 못 받음 999 넘음 · '
                   '약속에 없는 응답 999 · 마지막 확인 때 Worker 상태를 읽지 못했어요)']
    assert one(kind='conflict', tries={'rejected': 1}, why='nohash') == ['어제 요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요']
    assert D.carry_lines({'carry': ['x', 3, {'kind': 'failed', 'date': 5}, {'kind': ['a']}]}, day) == []


def test_cli_expired_pending_reaches_archive_and_carry(cli_env):
    V, st, w = cli_env
    w.script = ['drop']
    assert V.main([]) == 1
    s = D.load_state(st)
    s['pending']['tries'].append({'at': 'x', 'result': ['손상']})
    D.save_state(st, s)
    w.status_down = True
    w.clock['now'] = at(2026, 11, 10, 9, 20)
    assert V.main([]) == 0
    text = _texts(w)[-1]
    assert ('어제 요약 접수 여부 확인 불가(제출 시도 2번: 응답 못 받음 1 · 기타 1 · 마지막 확인 때 Worker 상태를 읽지 못했어요)'
            in text.split('\n\n'))
    with open(D.archive_path(st), encoding='utf-8') as fh:
        assert json.loads(fh.readline())['outcome'] == 'unknown'
