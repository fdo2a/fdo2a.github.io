#!/usr/bin/env python3
"""발행 전 codex 검토 — 루틴이 부르는 진입점(절차: `.claude/PREPUB_REVIEW.md`).

  prepub_review.py submit --section us|kr --date D --html H --notes research_notes.md --out DIR [--deadline-min 25]
      묶음 → review-drafts push → 비공개 워크플로 기동. `prepub: submitted rid=…` (exit 0) 또는
      `prepub: fallback submit_failed …` (exit 10). 마감 시각(절대)을 DIR/status.json 에 적는다.
  prepub_review.py wait --dir DIR [--minutes 9]
      결과를 최대 N 분 기다린다(루틴의 Bash 한 번은 10분까지라 나눠 부른다).
      `prepub: reviewed` (exit 0, DIR/review.md) · `prepub: waiting` (exit 11, 다시 부른다) ·
      `prepub: fallback <state>` (exit 10 — 마감·한도·실패·불일치).
  prepub_review.py split --review DIR/review.md --html H --section us|kr --date D --out DIR
      → DIR/facts.md(정확성 몫), DIR/candidates.json(문체 후보, STYLE_CLOSE 형식), DIR/split.json
  prepub_review.py merge-verdicts --pairs pairs.json --first v1.json --second v2.json --out verdicts.json
      판단 문장 낱말까지 바뀐 묶음(`judgment: true`)은 두 번의 의미 검사가 **둘 다 same** 일 때만 same.
      나머지 묶음은 첫 검사를 따른다. 두 답의 proposed_sha256 이 pairs 와 다르면 exit 2.
  prepub_review.py facts-done --dir DIR --html H [--applied N] [--rejected N]
      정확성 지적을 전부 판정했고, 받아들인 수정을 반영해 게이트를 다시 통과했다는 표시(검토가 온 판에만).
  prepub_review.py seal --dir DIR --html H --why style|note
      판정을 마친 판에 guard 를 지난 문체 편집·에디터 노트만 더했다는 표시.
  prepub_review.py record --dir DIR --html posts/D.html --section us|kr --date D [--style-applied N] …
      → reviews/prepublish/<section>/<date>.json (발행 커밋에 함께 넣는다). **facts-done 이 없거나 올릴 파일이 판정을 마친
      판(또는 봉인한 판)과 다르면 exit 10** — 쓰지 않는다.
  prepub_review.py hold --dir DIR --section us|kr --date D [--state …] [--html H] [--push]
      글을 세운다 — 닫힌 칸만 든 보류 기록을 쓰고, 잠금을 어떻게 놓을지 마지막 줄로 알린다:
      `lock=release`(검토가 아예 돌지 않았다 — 재시도가 처음부터 다시 써도 잃는 것이 없다) ·
      `lock=hold:<부호>`(판정을 시작했다 — 사람이 `run_lock.sh unhold` 하기 전에는 다시 쓰지 않는다).

**막기(2026-11-22 사용자 「발행 전에 제대로 검사하고 다 끝난 다음에 올려야지」)**: exit 10(fallback)은 이제 「발행하지
않는다」다. 그날 글은 세우고, 원래 판으로 되돌려 발행하지 않는다. 절차: `.claude/PREPUB_REVIEW.md` §5.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prepub import bundle as bundle_mod  # noqa: E402
from prepub import submit as submit_mod  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLBACK = 10
WAITING = 11


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _write(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(_dumps(obj))


def _now():
    import time
    return time.time()


def cmd_submit(a):
    os.makedirs(a.out, exist_ok=True)
    status = {'section': a.section, 'date': a.date, 'state': 'fallback'}
    import shutil
    try:
        # 무엇보다 먼저 — 제출한 판. 사람의 복구(세울 때 비공개 재료)가 이 판을 읽는다. 공개 기록의 인용은 올릴 판과 대조한다
        shutil.copyfile(a.html, os.path.join(a.out, 'original.html'))
        notes = a.notes if a.notes and os.path.isfile(a.notes) else None
        status['notes'] = bool(notes)
        man = bundle_mod.build(ROOT, a.section, a.date, a.html, os.path.join(a.out, 'bundle'),
                               notes_path=notes)
        status['request_id'] = rid = man['request_id']
        status['source_html_sha256'] = man['source_html_sha256']
        status['draft_sha'] = sha = submit_mod.push_bundle(ROOT, os.path.join(a.out, 'bundle'), rid)
        submit_mod.dispatch(rid, sha)
    except (bundle_mod.BundleError, submit_mod.SubmitError, OSError) as exc:
        status.update(state='submit_failed', reason=str(exc)[:300])
        _write(os.path.join(a.out, 'status.json'), status)
        print(f'prepub: fallback submit_failed {str(exc)[:160]}')
        return FALLBACK
    status.update(state='submitted', deadline=_now() + a.deadline_min * 60)
    _write(os.path.join(a.out, 'status.json'), status)
    print(f'prepub: submitted rid={rid}')
    return 0


def cmd_wait(a):
    path = os.path.join(a.dir, 'status.json')
    try:
        with open(path, encoding='utf-8') as fh:
            status = json.load(fh)
    except (OSError, ValueError):
        print('prepub: fallback no_status')
        return FALLBACK
    if status.get('state') != 'submitted':
        print(f"prepub: {'reviewed' if status.get('state') == 'reviewed' else 'fallback ' + str(status.get('state'))}")
        return 0 if status.get('state') == 'reviewed' else FALLBACK
    left = float(status.get('deadline', 0)) - _now()
    budget = min(left, a.minutes * 60)
    state, res = (submit_mod.wait(status['request_id'], status['draft_sha'], budget)
                  if budget > 0 else ('timeout', None))
    if res is not None:
        _write(os.path.join(a.dir, 'result.json'), res)
        status['auth_saved'] = res.get('auth_saved')
    if state == 'timeout' and left > budget:
        _write(path, status)
        print('prepub: waiting')
        return WAITING
    if state != 'reviewed':
        status.update(state=state, reason=str((res or {}).get('error', ''))[:300])
        _write(path, status)
        print(f"prepub: fallback {state} {status['reason'][:160]}".rstrip())
        return FALLBACK
    with open(os.path.join(a.dir, 'review.md'), 'w', encoding='utf-8') as fh:
        fh.write(res.get('review') or '')
    status['state'] = 'reviewed'
    _write(path, status)
    print(f"prepub: reviewed rid={status['request_id']}")
    return 0


def cmd_split(a):
    import hashlib
    from close import locks
    from prepub import split as split_mod
    with open(a.review, encoding='utf-8') as fh:
        review = fh.read()
    with open(a.html, 'rb') as fh:
        raw = fh.read()
    html = raw.decode('utf-8')
    if not a.after_fixes:
        # 검토 결과는 제출한 판에 대한 것이다 — 그 사이 글이 바뀌었으면 적용하지 않는다(codex 구현 #6)
        try:
            with open(os.path.join(a.out, 'status.json'), encoding='utf-8') as fh:
                want = json.load(fh).get('source_html_sha256')
        except (OSError, ValueError):
            want = None
        if want != hashlib.sha256(raw).hexdigest():
            print('prepub: fallback stale_html — 제출한 판과 지금 판이 다르다')
            return FALLBACK
    ledger = locks.Ledger.load(ROOT, a.section, a.date)
    got = split_mod.split(review, html, ledger)
    os.makedirs(a.out, exist_ok=True)
    lines = [got['facts'].rstrip(), '']
    if got['accuracy']:
        lines.append('=== 확신도 지적(근거와 대조해 정확성 오류로 판정) ===')
        lines += [f"- [{f['kind']}] 「{f['quote']}」 — {f['note']}" for f in got['accuracy']]
    with open(os.path.join(a.out, 'facts.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    _write(os.path.join(a.out, 'candidates.json'), got['candidates'])
    summary = {k: got[k] for k in ('accuracy', 'unplaced', 'excluded', 'dropped')}
    summary['candidates'] = len(got['candidates']['items'])
    summary['style_findings'] = got['style']
    # 명료성 분류(2026-11-18) — split 시점에 정해지는 값만. 고쳐졌는지는 여기서 적지 않는다(발행 뒤 발행본과 견준다)
    summary['clarity'] = got['clarity']
    summary['clarity_meta'] = got['meta']
    _write(os.path.join(a.out, 'split.json'), summary)
    recorded = sum(1 for f in got['clarity'] if f['route'] == 'record_only')
    print(f"prepub: accuracy {len(got['accuracy'])} · style candidates {summary['candidates']} · "
          f"excluded {len(got['excluded'])} · unplaced {len(got['unplaced'])} · "
          f"dropped {len(got['dropped'])} · recorded {recorded} (번역투·용어만 고친다 — 기록만 하는 지적은 발행을 막지 않는다)")
    return 0


def merge_verdicts(pairs, first, second):
    sha = pairs.get('proposed_sha256')
    if not sha or first.get('proposed_sha256') != sha or second.get('proposed_sha256') != sha:
        raise ValueError('의미 검사 답이 다른 판에 대한 것이다')
    v1, v2 = first.get('verdicts') or {}, second.get('verdicts') or {}
    out = {}
    for b in pairs.get('bundles', []):
        bid = b['id']
        a = (v1.get(bid) or {}).get('verdict', 'unsure')
        if not b.get('judgment'):
            out[bid] = v1.get(bid) or {'verdict': 'unsure', 'why': '첫 검사에 답 없음'}
            continue
        c = (v2.get(bid) or {}).get('verdict', 'unsure')
        if a == c == 'same':
            out[bid] = {'verdict': 'same', 'why': '판단 문장 — 두 검사 모두 same'}
        elif 'changed' in (a, c):
            out[bid] = {'verdict': 'changed', 'why': f'판단 문장 — {a}/{c}'}
        else:
            out[bid] = {'verdict': 'unsure', 'why': f'판단 문장 — {a}/{c}'}
    return {'proposed_sha256': sha, 'verdicts': out}


def cmd_merge(a):
    try:
        docs = [json.load(open(p, encoding='utf-8')) for p in (a.pairs, a.first, a.second)]
        merged = merge_verdicts(*docs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'prepub: merge failed {exc}')
        return 2
    _write(a.out, merged)
    j = sum(1 for b in docs[0].get('bundles', []) if b.get('judgment'))
    same = sum(1 for v in merged['verdicts'].values() if v['verdict'] == 'same')
    print(f'prepub: merged {len(merged["verdicts"])} bundles (judgment {j}) · same {same}')
    return 0


_BLOB = __import__('re').compile(r'[A-Za-z0-9+/_=-]{40,}')
PUBLIC_REASON = {
    'reviewed': '', 'submit_failed': '초안을 올리거나 검토를 띄우지 못했다', 'timeout': '마감까지 검토가 오지 않았다',
    'limit': 'codex 사용 한도', 'failed': '검토 실행 실패', 'mismatch': '다른 초안의 결과',
    'stale_html': '기다리는 사이 초안이 바뀌었다', 'not_reviewed': 'codex 가 검토하지 못했다',
    'suspicious_output': '검토 답을 버렸다(인코딩 덩어리)', 'sandbox_failed': '검토 샌드박스 실패',
    'manifest_mismatch': '묶음 해시 불일치', 'auth_missing': '로그인 비밀값 없음', 'bad_input': '입력 형식 오류',
    'recovery_needed': '받아들인 수정을 반영하지 못해 세움', 'style_abort': '문체 마감이 중단을 요구해 세움',
    'facts_unmarked': '정확성 판정 완료 표시가 없어 세움', 'mark_failed': '판정 중 표시를 달지 못해 판정하지 않음',
    'no_status': '검토 상태 파일 없음', 'fallback': '검토 상태를 알 수 없음',
}


def _public_findings(findings, post_text=''):
    """공개 기록에 남길 문체 지적 — **분류와, 발행본에 실제로 있는 인용만**(codex 구현 재검토 3차 #1).

    codex 의 자유 텍스트(방향·설명)는 공개 레포로 내보내지 않는다 — 인코딩 필터로는 모든 유출을 못 막는다.
    인용은 글에 그대로 있는 문장 조각일 때만 남긴다(글에 없는 글자는 실리지 않는다). 방향은 비공개 결과에만 있다.
    """
    norm = ' '.join((post_text or '').split())
    out = []
    for f in findings or ():
        quote = ' '.join(str(f.get('quote') or '').split())[:40]
        out.append({'kind': f.get('kind'), 'quote': quote if quote and quote in norm else ''})
    return out


_PLACED = frozenset({'candidate', 'not_located', 'protected'})


def _public_clarity(findings, final_html=''):
    """공개 기록에 남길 명료성 지적 — **닫힌 값과, 올릴 판(발행본)에 실제로 있는 인용만.**

    제출한 초안이 아니라 올릴 판과 대조한다 — 고치면서 지운 글자(중간판)가 공개 기록에 남지 않게(codex 구현 2회차 #2).

    검토자가 쓴 글(이유·고칠 방향)은 싣지 않는다 — 비공개 결과에만 있다. 분류는 네 이름, 알 수 없는 것은 가·나·다,
    길은 분류로 정해진 값(파일에 적힌 값을 믿지 않는다), 자리 결과는 세 값뿐이다. 그 밖의 글자는 빈 값이 된다.
    인용은 독자가 보는 글자(`prepub.public.visible`)로 대조한다 — 주간 묶음이 발행본과 견줄 때도 같은 읽기다.
    이 기록은 발행 직전 유출 검사의 대상이라, 칸 이름에 그 검사의 고정 문자열을 쓰지 않는다(`close/leak.py`).
    """
    from prepub import split as split_mod      # 길은 그 표 하나에서만 정한다
    from prepub.public import norm, visible
    route = {k: split_mod.ROUTES[k] for k in split_mod.CLARITY_KINDS}
    text = visible(final_html)
    out = []
    for f in findings or ():
        if not isinstance(f, dict) or f.get('kind') not in route:
            continue
        quote = norm(str(f.get('quote') or ''))[:40]
        tell, where = f.get('cannot_tell'), f.get('placed')
        out.append({'kind': f['kind'], 'quote': quote if quote and quote in text else '',
                    'cannot_tell': tell if tell in ('가', '나', '다') else '',
                    'route': route[f['kind']],
                    'placed': where if where in _PLACED else ''})
    return out


def _public_meta(meta):
    meta = meta if isinstance(meta, dict) else {}

    def count(key):
        v = meta.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10000 else 0
    return {'marker': meta.get('marker') is True, 'lines_skipped': count('lines_skipped'),
            'over_cap': count('over_cap')}


def _tag_stripped(html):
    """올릴 판의 본문 글자(태그 뺌) — 문체 지적의 인용이 그 글에 있는지 대조한다."""
    import re
    return re.sub(r'<[^>]+>', ' ', html or '')


def _status(folder):
    try:
        with open(os.path.join(folder, 'status.json'), encoding='utf-8') as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def cmd_facts_done(a):
    import hashlib
    status = _status(a.dir)
    # 다시 찍기(facts_done → facts_done)는 판정 뒤 작성자가 글을 다시 고친 경우다 — 루틴이 받아들인 지적을 그 판에서
    # 다시 대조한 뒤에만 부른다. 앞서 봉인한 판(문체·노트)은 모두 무효가 된다(codex 구현 1회차 #2).
    if not status or status.get('state') not in ('reviewed', 'facts_done'):
        print(f"prepub: fallback facts_unmarked — 검토가 온 판이 아니다({(status or {}).get('state')})")
        return FALLBACK
    with open(a.html, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    status.update(state='facts_done', facts_sha256=sha, facts_applied=a.applied, facts_rejected=a.rejected,
                  sealed=[])
    _write(os.path.join(a.dir, 'status.json'), status)
    print(f'prepub: facts_done applied={a.applied} rejected={a.rejected}')
    return 0


def cmd_seal(a):
    """판정을 마친 판에 **기계적·guard 를 지난 변경**만 덧붙였다는 표시 — 문체 마감(STYLE_CLOSE guard·의미 검사)과
    에디터 노트(apply_note). 작성자가 다시 쓴 판은 여기가 아니라 facts-done 을 다시 찍는다."""
    import hashlib
    status = _status(a.dir)
    if not status or status.get('state') != 'facts_done':
        print(f"prepub: fallback facts_unmarked — 봉인할 판정 완료 판이 없다({(status or {}).get('state')})")
        return FALLBACK
    with open(a.html, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    sealed = [x for x in status.get('sealed') or [] if isinstance(x, dict)]
    sealed.append({'sha256': sha, 'why': a.why})
    status['sealed'] = sealed
    _write(os.path.join(a.dir, 'status.json'), status)
    print(f'prepub: sealed {a.why} {sha[:12]}')
    return 0


def _allowed(status):
    shas = {status.get('facts_sha256')}
    shas |= {x.get('sha256') for x in status.get('sealed') or [] if isinstance(x, dict)}
    return {x for x in shas if isinstance(x, str) and len(x) == 64}


# 검토가 아예 돌지 않았다 — 받아들인 것이 없으니 재시도가 처음부터 다시 써도 잃는 것이 없다(잠금을 푼다).
# `stale_html` 은 판정 전에 나고, `mark_failed` 는 판정 중 표시를 못 달아 판정하지 않은 경우다(설계 §10.2).
NOT_RUN = frozenset({'submit_failed', 'timeout', 'limit', 'failed', 'mismatch', 'not_reviewed', 'suspicious_output',
                     'sandbox_failed', 'manifest_mismatch', 'auth_missing', 'bad_input', 'no_status', 'fallback',
                     'stale_html', 'mark_failed'})
# 판정을 시작했다 — 사람만 푼다(run_lock.sh hold 의 부호와 같은 목록)
HOLD_CODES = ('recovery_needed', 'style_abort', 'facts_unmarked')
# 「검토 미실행」의 세 갈래(설계 auto_resume v1.5 §6.1). 다시 해도 똑같이 실패하는 부호가 슬롯마다 처음부터
# 다시 쓰기(수집·Opus 작성·제출)를 태우지 않게, 같은 날짜 기록에서 센다.
HUMAN_CODES = frozenset({'auth_missing'})          # 사람 손 — 첫 번째에 바로 세운다
WAIT_CODES = frozenset({'limit'})                  # 기다림 — 세지 않고, 세우지 않는다(풀리면 바로 다시)
COUNTED_CODES = NOT_RUN - HUMAN_CODES - WAIT_CODES
SAME_TWICE, MAX_COUNTED = 2, 3                     # 같은 부호 연달아 2번 / 세는 실패 3번이면 세운다


# 세움 기록의 칸 — 쓰는 쪽(_hold_rec)과 읽는 쪽(_carried)이 같은 상수를 본다.
HOLD_ORDER_M = ('section', 'date', 'request_id', 'state', 'reason', 'hold', 'recorded_at')   # 11/22 M 의 세움 기록
HOLD_ORDER = HOLD_ORDER_M + ('attempt', 'last_counted')            # 11/22 선행 묶음 ② 의 세움 기록
# 11/22 즉시 알림(설계 instant_telegram v1.4 §4.2) — 닫힌 칸 `next` 하나를 더한 셋째 꼴. _hold_rec 는 이것만 쓴다.
# 감시(publish_watch)가 이 칸만 보고 「자동 재시도」/「사람 확인」을 알린다 — 세는 규칙을 다시 계산하지 않는다.
HOLD_ORDER_N = HOLD_ORDER + ('next',)
HOLD_KEYS_M, HOLD_KEYS, HOLD_KEYS_N = frozenset(HOLD_ORDER_M), frozenset(HOLD_ORDER), frozenset(HOLD_ORDER_N)
NEXT_VALUES = ('retry', 'person')                  # retry = lock=release, person = lock=hold:…
RID_RE = __import__('re').compile(r'[a-z]{2}-[0-9-]{10}-[0-9a-f]{12}')
STAMP_RE = __import__('re').compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')


def _carried(raw, section, date):
    """앞 기록(origin/main 의 같은 파일 **바이트**, 없으면 None) → (attempt, last_counted). 셀 수 없으면 None.

    **cmd_hold 가 쓰는 세움 기록의 꼴 그대로만** 받는다(codex 구현 2회차 — 칸을 하나씩 검사하다 두 번 뚫렸다). 그 밖의 모든 것,
    해석 중의 어떤 예외든 「셀 수 없다」다 — cmd_hold 가 늘 `lock=` 줄까지 가게 여기서 삼킨다.
    """
    if raw is None:
        return 0, None                               # 파일 없음 — 그날 첫 실패
    def pairs(items):                                # 같은 칸이 두 번 나오는 글자는 이 코드가 쓰지 않는다
        out = dict(items)
        if len(out) != len(items):
            raise ValueError('duplicate key')
        return out
    try:
        text = raw.decode('utf-8')                   # 바이트 그대로 — 다듬거나(.strip) 바꿔 읽지 않는다
        rec = json.loads(text, object_pairs_hook=pairs)
        if text != _dumps(rec):                      # _write 가 쓰는 글자와 한 바이트도 다르지 않아야 한다
            return None
        if tuple(rec) not in (HOLD_ORDER_M, HOLD_ORDER, HOLD_ORDER_N):     # 다시 직렬화는 읽은 순서를 따른다 — 순서는 따로 본다(5회차 ⑤)
            return None
        return _carried_exact(rec, section, date)
    except Exception:
        return None


def _carried_exact(rec, section, date):
    if type(rec) is not dict or rec.get('section') != section or rec.get('date') != date:
        return None
    keys, state = frozenset(rec), rec.get('state')
    if not isinstance(state, str):
        return None
    # 발행 기록(`hold` 칸 없음)은 받지 않는다 — 이미 발행한 날짜에 또 세우는 일은 정상 흐름에 없고, 그 꼴(칸 20여 개의
    # 값)을 하나씩 따지는 검사는 회차마다 뚫렸다(codex 구현 3회차 ⑤). 셀 수 없음 = 세는 실패는 사람 손.
    if keys not in (HOLD_KEYS_M, HOLD_KEYS, HOLD_KEYS_N):
        return None
    if keys == HOLD_KEYS_N and not (isinstance(rec['next'], str) and rec['next'] in NEXT_VALUES):
        return None                                  # 셋째 꼴의 값 검사 — 횟수에는 들지 않는다
    if rec['hold'] is not True or (state not in NOT_RUN and state not in HOLD_CODES) \
            or rec.get('reason') != PUBLIC_REASON.get(state, ''):
        return None
    rid, at = rec.get('request_id'), rec.get('recorded_at')
    if not (rid is None or isinstance(rid, str) and RID_RE.fullmatch(rid)) \
            or not (isinstance(at, str) and STAMP_RE.fullmatch(at)):
        return None
    __import__('datetime').datetime.strptime(at, '%Y-%m-%dT%H:%M:%SZ')     # 실제 날짜·시각이 아니면 ValueError → 셀 수 없다
    if keys == HOLD_KEYS_M:                          # M 의 세움 기록(횟수 칸 없음) — 세는 부호였으면 1번
        return (1, state) if state in COUNTED_CODES else (0, None)
    n, last = rec['attempt'], rec['last_counted']
    if type(n) is not int or not 0 <= n <= 99:       # null = 앞 런이 셀 수 없었다 — 이어서도 셀 수 없다
        return None
    if n == 0:                                       # 센 것이 없으면 마지막 부호도 없고, 세는 부호의 기록일 수 없다
        return (0, None) if last is None and state not in COUNTED_CODES else None
    if not isinstance(last, str) or last not in COUNTED_CODES:
        return None
    if state in COUNTED_CODES and last != state:     # 세는 부호의 기록은 자기 부호가 마지막이다
        return None
    return n, last


def _hold_rec(section, date, rid, state, carried, push=False):
    """세움 기록과 「세는 규칙으로 세울까」 — carried 는 _carried 의 값(None = 셀 수 없다).

    `next` 는 여기서 **한 번** 정한다(cmd_hold 의 lock= 이 이 값에서 나온다): 판정 뒤 부호 → person, 검토 미실행 부호는
    `--push` 이고 (세는 규칙이 세움이거나 사람 손 부호)일 때만 person, 아니면 retry(`--push` 없는 hold 는 늘 retry).
    """
    counted = state in COUNTED_CODES
    if carried is None:
        attempt, last, stop = None, None, counted    # 모르면 0 으로 적지 않는다. 세는 실패는 막는 쪽
    elif counted:
        attempt, last = carried[0] + 1, state
        stop = state == carried[1] or attempt >= MAX_COUNTED
    else:
        (attempt, last), stop = carried, False       # 한도·사람 손·판정 뒤 부호는 횟수를 그대로 옮긴다
    rec = {'section': section, 'date': date,
           'request_id': rid if isinstance(rid, str) and RID_RE.fullmatch(rid) else None,
           'state': state, 'reason': PUBLIC_REASON.get(state, ''), 'hold': True,
           'recorded_at': __import__('datetime').datetime.now(
               __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'attempt': attempt, 'last_counted': last}
    person = state not in NOT_RUN or bool(push and (stop or state in HUMAN_CODES))
    rec['next'] = 'person' if person else 'retry'
    return rec, stop


def _iso_date(text):
    import datetime
    import re
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', text):      # fullmatch — 줄바꿈이 붙은 값도 거른다
        raise argparse.ArgumentTypeError('YYYY-MM-DD')
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError('YYYY-MM-DD')
    return text


def cmd_hold(a):
    status = _status(a.dir) or {'state': 'no_status'}
    state = a.state or str(status.get('state'))
    if state not in NOT_RUN and state not in HOLD_CODES:
        state = 'recovery_needed'          # 모르는 값·검토가 온 뒤의 실패는 막는 쪽
    # 센다 — --push 로 부를 때만(그래야 다음 런이 이 횟수를 본다). push 없이는 M 의 동작 그대로(원격을 읽지 않는다).
    # 앞 기록은 **기록을 올리는 바로 그 받기**에서 읽는다(push_record 가 받을 때마다 build 를 부른다) — 따로 받으면
    # 「읽기만 실패하고 올리기는 성공」해 실제 횟수를 덮는 틈이 생긴다(codex 구현 2회차 ④).
    folder = os.path.join(ROOT, 'reviews', 'prepublish', a.section)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{a.date}.json')
    made = {}

    def build(raw, readable=True):
        carried = _carried(raw, a.section, a.date) if readable else None
        made['rec'], made['stop'] = _hold_rec(a.section, a.date, status.get('request_id'), state, carried, a.push)
        _write(path, made['rec'])
        # 한도(limit)는 읽지 못한 기록을 덮어쓰지 않는다 — 횟수를 지우지 않게. 올리지 않고 release 한다.
        return not (carried is None and state in WAIT_CODES)

    def keep_materials():
        # 판정을 시작한 글 — 사람이 이어 고칠 재료를 비공개 레포에만 둔다(세션이 끝나면 임시 폴더는 사라진다).
        # 검토 답(codex 문장)과 고치던 판이 들어 있다 — 공개 레포에는 개수와 부호뿐이다. 실패해도 세우는 것은 그대로.
        files = {}
        for name in ('status.json', 'original.html', 'review.md', 'facts.md', 'split.json', 'candidates.json',
                     'verdicts.md'):
            if os.path.isfile(os.path.join(a.dir, name)):
                files[name] = os.path.join(a.dir, name)
        if a.html and os.path.isfile(a.html):
            files['current.html'] = a.html
        rid = status.get('request_id')
        rid_dir = rid if isinstance(rid, str) and RID_RE.fullmatch(rid) else 'no-request'
        try:
            submit_mod.upload({f'holds/{a.section}/{a.date}/{rid_dir}/{k}': v for k, v in files.items()},
                              submit_mod.HOLDS_BRANCH, f'hold {a.section} {a.date} {state}')
            return 'private'
        except Exception:                            # 응답 꼴 오류 등 무엇이든 — lock= 줄에 닿아야 세움이 선다
            return 'failed'
    saved = 'none'
    if not a.push:
        build(None)
    elif state not in NOT_RUN:                       # 로컬 기록 → 재료 → 공개 기록(M 의 순서). 횟수는 받은 뒤 다시 쓴다
        _write(path, _hold_rec(a.section, a.date, status.get('request_id'), state, None, a.push)[0])
    if state not in NOT_RUN:
        saved = keep_materials()                     # 판정 뒤 부호는 세움이 이미 정해졌다 — M 의 순서(재료 먼저) 그대로
    pushed = 'skipped'
    if a.push:
        try:
            if push_record(ROOT, os.path.relpath(path, ROOT), f'Hold {a.date} brief (prepub {state})', build=build):
                pushed = 'ok'
        except Exception as exc:
            # 받기·올리기의 어떤 실패든(git 시간 초과·실행 실패 포함) 여기서 멈추면 재료 저장과 lock= 줄에 닿지 못한다
            pushed = 'failed'
            print(f'prepub: hold record push failed — {str(exc)[:160]}')
            if 'rec' not in made:                    # 받지도 못했다 — 로컬 기록은 「모름」
                made['rec'], made['stop'] = _hold_rec(a.section, a.date, status.get('request_id'), state, None, a.push)
                try:
                    _write(path, made['rec'])
                except OSError:
                    pass
            if state in COUNTED_CODES:
                made['stop'] = True                  # 다음 런이 이 횟수를 못 본다 — 셀 수 없으면 막는 쪽
    attempt = made['rec']['attempt']
    if state in NOT_RUN:
        # lock= 은 기록의 next 에서 나온다(감시가 같은 값을 읽는다). 덮는 것은 하나뿐 — 기록 push 가 실패한 세는 실패는
        # 세움이다(다음 런이 횟수를 못 본다). 그 기록은 main 에 없으니 감시가 읽을 일이 없다.
        stop = made['rec']['next'] == 'person' or (pushed == 'failed' and state in COUNTED_CODES)
        lock = 'hold:recovery_needed' if stop else 'release'
        if stop:
            saved = keep_materials()
    else:
        lock = f'hold:{state}'
    print(f"prepub: held {os.path.relpath(path, ROOT)} state={state} attempt={attempt} "
          f"materials={saved} pushed={pushed} lock={lock}")
    return 0


class RecordPushError(Exception):
    pass


def push_record(root, rel, message, tries=3, run=None, build=None):
    """보류 기록 **한 파일만** 바뀐 커밋을 origin/main 위에 지어 main 에 민다(codex 구현 1회차 #1).

    루틴의 인덱스·로컬 커밋은 쓰지 않는다 — 문체 마감 B 가 `git add -A` 한 뒤이거나 STEP 3 의 발행 커밋을 이미 만든 뒤에
    세워도, 올라가는 것은 origin/main 의 나무 + 이 파일뿐이다. 거절되면 다시 받아 그 위에 다시 짓는다.

    build 를 주면 받을 때마다 `build(그 받기의 같은 파일 글자 또는 None)` 을 불러 파일을 다시 쓰게 한다 — 읽은 판과
    올리는 바탕이 늘 같은 커밋이다. build 가 거짓을 돌려주면 올리지 않고 None 을 돌려준다.
    """
    import subprocess
    import tempfile
    import time
    run = run or subprocess.run

    def git(*args, env=None):
        out = run(['git', '-C', root, *args], capture_output=True, encoding='utf-8', errors='replace', env=env,
                  timeout=60)
        if out.returncode:
            raise RecordPushError(f"git {args[0]}: {(out.stderr or '').strip()[-200:]}")
        return (out.stdout or '').strip()
    sent = None
    for attempt in range(tries):
        git('fetch', '-q', 'origin', 'main')
        base = git('rev-parse', 'FETCH_HEAD')
        if sent and base == sent:
            return sent                              # 앞 push 가 반영됐는데 실패로 돌아왔다 — 다시 세지 않는다
        if build is not None:
            entry = git('ls-tree', base, '--', rel).split()      # '<mode> <type> <sha> <path>' 또는 빈 줄
            if not entry:
                go = build(None)
            elif entry[1] != 'blob':
                go = build(None, readable=False)
            else:
                # 바이트 그대로 읽는다 — git() 처럼 다듬으면(.strip) 앞뒤에 붙은 글자가 사라져 모르는 기록이 읽힌다
                got = run(['git', '-C', root, 'cat-file', 'blob', entry[2]], capture_output=True, timeout=60)
                # 읽기만 실패하면 「셀 수 없음」으로 짓는다 — 판정 뒤 부호의 공개 기록은 M 처럼 그대로 올라간다(5회차 ⑥).
                # 세는 실패는 셀 수 없으니 세움, 한도는 build 가 올리지 않는다.
                go = build(got.stdout) if got.returncode == 0 else build(None, readable=False)
            if not go:
                return None
        blob = git('hash-object', '-w', os.path.join(root, rel))
        fd, index = tempfile.mkstemp(prefix='prepub-hold-index-')
        os.close(fd)
        os.unlink(index)
        env = dict(os.environ, GIT_INDEX_FILE=index)
        try:
            git('read-tree', base, env=env)
            git('update-index', '--add', '--cacheinfo', f'100644,{blob},{rel}', env=env)
            tree = git('write-tree', env=env)
        finally:
            if os.path.exists(index):
                os.unlink(index)
        changed = git('diff-tree', '--no-commit-id', '--name-only', '-r', base, tree).split()
        if changed not in ([rel], []):
            raise RecordPushError(f'기록 밖 파일이 섞였다: {changed[:5]}')
        commit = git('commit-tree', tree, '-p', base, '-m', message)
        out = run(['git', '-C', root, 'push', '-q', 'origin', f'{commit}:refs/heads/main'],
                  capture_output=True, encoding='utf-8', errors='replace', timeout=60)
        if out.returncode == 0:
            return commit
        sent = commit
        if attempt == tries - 1:
            raise RecordPushError(f"push: {(out.stderr or '').strip()[-200:]}")
        time.sleep(2 * (attempt + 1))
    raise RecordPushError('push')


def cmd_record(a):
    import hashlib
    status = _status(a.dir)
    if not status or status.get('state') != 'facts_done':
        # 막기 — 정확성 판정을 끝냈다는 표시가 없는 판은 발행 기록을 만들지 않는다. 루틴은 §5 로 세운다.
        print(f"prepub: fallback facts_unmarked — facts-done 표시 없음({(status or {}).get('state')})")
        return FALLBACK
    # 올릴 파일이 판정을 마친 판(또는 그 판에 봉인한 변경)과 바이트까지 같아야 한다 — 판정 뒤에 다시 쓴 판이
    # 옛 표시로 나가지 않게(codex 구현 1회차 #2)
    try:
        with open(a.html, 'rb') as fh:
            final_bytes = fh.read()
        final = hashlib.sha256(final_bytes).hexdigest()
    except OSError:
        final_bytes, final = b'', None
    if final not in _allowed(status):
        print('prepub: fallback facts_unmarked — 올릴 판이 판정을 마친 판과 다르다(다시 쓴 판은 facts-done 을 다시 찍는다)')
        return FALLBACK
    try:
        with open(os.path.join(a.dir, 'split.json'), encoding='utf-8') as fh:
            split = json.load(fh)
    except (OSError, ValueError):
        split = {}
    # 공개 기록의 인용은 **해시를 잰 바로 그 바이트**(올릴 판)에 남아 있는 것만 — 제출 초안에만 있던 글자는 빈 값이 된다
    final_html = final_bytes.decode('utf-8', errors='replace')
    state = 'reviewed'
    # 공개 기록의 이유는 우리가 만든 상태 이름뿐이다 — codex·러너 출력은 옮기지 않는다(codex 구현 재검토 #1)
    rec = {'section': a.section, 'date': a.date, 'request_id': status.get('request_id'),
           'draft_sha': status.get('draft_sha'), 'state': state,
           'reason': PUBLIC_REASON.get(state, ''), 'auth_saved': status.get('auth_saved'),
           'accuracy_findings': len(split.get('accuracy', [])),
           'style_candidates': split.get('candidates', 0),
           'style_excluded': len(split.get('excluded', [])),
           'style_unplaced': len(split.get('unplaced', [])),
           'style_dropped': len(split.get('dropped', [])),
           'facts_applied': int(status.get('facts_applied') or 0), 'facts_rejected': int(status.get('facts_rejected') or 0),
           'style_applied': a.style_applied, 'style_rejected': a.style_rejected,
           'skeleton_rejected': a.skeleton_rejected, 'checker_rejected': a.checker_rejected,
           # 주간 묶음(`scripts/review/style_digest.py`)이 읽는다 — 반복되는 꼴을 예문으로 되먹인다
           'style_findings': _public_findings(split.get('style_findings', []), _tag_stripped(final_html)),
           'recorded_at': __import__('datetime').datetime.now(
               __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'facts_done': True, 'final_sha256': final}
    if isinstance(split, dict) and 'clarity' in split:
        # 덧붙이는 칸이다 — 만들다 무슨 일이 나도 지금 형식의 기록으로 내린다. 발행을 막거나 되돌리는 값이 아니다.
        try:
            extra = {'clarity': _public_clarity(split.get('clarity'), final_html),
                     'clarity_meta': _public_meta(split.get('clarity_meta'))}
            json.dumps(extra)
        except Exception:
            extra = {}
        rec.update(extra)
    folder = os.path.join(ROOT, 'reviews', 'prepublish', a.section)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{a.date}.json')
    _write(path, rec)
    print(f"prepub: recorded {os.path.relpath(path, ROOT)} state={rec['state']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='prepub_review.py')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('submit')
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--notes', default=None, help='작성자가 읽은 research_notes.md')
    p.add_argument('--out', required=True)
    p.add_argument('--deadline-min', type=int, default=25)
    p = sub.add_parser('wait')
    p.add_argument('--dir', required=True)
    p.add_argument('--minutes', type=float, default=9)
    p = sub.add_parser('split')
    p.add_argument('--review', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--after-fixes', action='store_true',
                   help='정확성 수정 뒤의 최종 판으로 다시 나눌 때 — 제출 판 해시 대조를 건너뛴다')
    p = sub.add_parser('merge-verdicts')
    p.add_argument('--pairs', required=True)
    p.add_argument('--first', required=True)
    p.add_argument('--second', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('record')
    p.add_argument('--dir', required=True)
    p.add_argument('--html', required=True, help='실제로 올릴 파일(posts/[DATE].html) — 판정을 마친 판과 같아야 한다')
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    for k in ('style-applied', 'style-rejected', 'skeleton-rejected', 'checker-rejected'):
        p.add_argument(f'--{k}', type=int, default=0)
    p = sub.add_parser('facts-done')
    p.add_argument('--dir', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--applied', type=int, default=0)
    p.add_argument('--rejected', type=int, default=0)
    p = sub.add_parser('hold')
    p.add_argument('--dir', required=True)
    p.add_argument('--section', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True, type=_iso_date)   # 공개 기록의 경로·칸·커밋 제목에 실린다
    p.add_argument('--state', default=None, choices=('recovery_needed', 'style_abort', 'stale_html', 'mark_failed'))
    p.add_argument('--html', default=None, help='지금 고치던 판 — 판정을 시작한 글이면 비공개 레포에 함께 둔다')
    p.add_argument('--push', action='store_true', help='보류 기록 한 파일만 든 커밋을 origin/main 위에 지어 민다')
    p = sub.add_parser('seal')
    p.add_argument('--dir', required=True)
    p.add_argument('--html', required=True)
    p.add_argument('--why', required=True, choices=('style', 'note'))
    a = ap.parse_args(argv)
    return {'submit': cmd_submit, 'wait': cmd_wait, 'split': cmd_split,
            'merge-verdicts': cmd_merge, 'record': cmd_record, 'facts-done': cmd_facts_done,
            'hold': cmd_hold, 'seal': cmd_seal}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
