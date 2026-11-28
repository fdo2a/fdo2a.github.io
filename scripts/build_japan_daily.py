#!/usr/bin/env python3
"""일본 일간 — 작성자 입력 진단과 조립 (2026-10-27).

    python3 scripts/build_japan_daily.py diag --session 2026-10-26
        → 절 순서(이벤트일이면 매크로가 둘째), complete, 기준일이 다른 값들, 뉴스 후보 수, 직전 일간 경로
    python3 scripts/build_japan_daily.py assemble --session 2026-10-26 \
        --body jpd.body.html --meta jpd.meta.json --out japan/daily/2026-10-26.html

스냅샷은 발행 전이면 `japan/data/daily/candidate/<s>.json`, 발행 뒤면 `japan/data/daily/<s>.json`.
`complete` 가 거짓이거나 `jgb_recollect` 가 false 가 아니면(이른 후보·옛 형식) 진단이 1 로 끝난다 — 오케스트레이터는 발행하지 않는다.
미발행 후보가 2판(`schema: 2`)이 아니어도 1 이다(v2 전환 — 다시 수집). 2판은 본문에 `<!--G:…-->` 자리가 필수이고
조립이 구조(자리표시자는 절의 바로 아래 자식, 숨김·style 금지)를 본다 — `japan/daily_render.validate_v2`.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from japan import daily_b as B  # noqa: E402
from japan import daily_render as R  # noqa: E402
from us.news_expand import expand  # noqa: E402


def snapshot_path(root, session):
    pub = Path(root) / 'japan' / 'data' / 'daily' / f'{session}.json'
    return pub if pub.exists() else Path(root) / 'japan' / 'data' / 'daily' / 'candidate' / f'{session}.json'


def news_path(root, session):
    return Path(root) / 'japan' / 'data' / 'news' / 'daily' / f'{session}.json'


def telegram_path(root, session):
    """발행된 세션이면 발행 단계가 고정한 사본(없으면 없는 것), 아니면 수집기 파일.
    발행 뒤에 수집기 파일이 바뀌어도 발행본의 근거는 달라지지 않는다."""
    base = Path(root) / 'japan' / 'data' / 'telegram'
    if (Path(root) / 'japan' / 'data' / 'daily' / f'{session}.json').exists():
        return base / 'published' / f'{session}.json'
    return base / f'{session}.json'


def telegram_problem(data, session):
    """쓸 수 없는 이유, 쓸 수 있으면 None. `usable: true` 가 유일한 스위치다."""
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        return '형식이 다르다'
    for it in data['items']:
        if (not isinstance(it, dict) or not isinstance(it.get('id'), str) or not it['id']
                or not isinstance(it.get('summary_ko'), (str, type(None)))):
            return '형식이 다르다(항목이 id·요약 글자를 가진 객체가 아니다)'
    if data.get('report_date') != session:
        return f'report_date {data.get("report_date")} ≠ {session}'
    if data.get('usable') is not True:
        return 'usable 이 아니다(' + ' · '.join(data.get('unusable_why') or ['사유 미기록']) + ')'
    return None


def load_telegram(root, session):
    """-> (쓸 수 있는 파일 내용 | None, 없는 것으로 본 이유 | None). 파일이 아예 없으면 (None, None)."""
    p = telegram_path(root, session)
    if not p.exists():
        return None, None
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, f'{p} 를 읽지 못했다'
    why = telegram_problem(data, session)
    return (None, f'{p}: {why}') if why else (data, None)


from common.jsonfile import load_json_path as _load  # noqa: E402 — 공용 JSON 읽기(2026-11-22)

# ── 일본은행 절(2026-11-27) ─────────────────────────────────────────────────────────
# 이 칸을 켠 첫 세션 — `japan/data/boj/schedule.json` 의 start 와 같아야 한다(시험이 묶는다). 그 앞 세션(옛 글 재검사·
# 일정 파일이 없던 커밋)은 「해당 없음」.
BOJ_START = '2026-11-28'


class BojInputError(Exception):
    """일본은행 칸 입력을 판정할 수 없다 — 조용히 「이벤트 없음」으로 읽지 않는다."""


def boj_state(root, session):
    """-> {'due', 'diff', 'outlook_diff', 'missing', 'schedule'}. `--root` 아래의 고정 입력만 읽는다.

    발행본 장부는 입력을 고정할 때 만든 `japan/data/boj/covered.json`(같은 커밋의 발행본에서 뽑은 KEY) — 없으면 멈춘다.
    """
    from common import cb_events as CE
    base = Path(root) / 'japan' / 'data' / 'boj'
    empty = {'due': [], 'diff': None, 'outlook_diff': None, 'missing': [], 'schedule': None}
    sp = base / 'schedule.json'
    if not sp.exists():
        if session < BOJ_START:
            return empty
        raise BojInputError(f'{sp} 이 없다 — 일본은행 일정 파일 없이 판정하지 않는다')
    schedule = _load(sp)
    if session < str(schedule.get('start') or BOJ_START):
        return dict(empty, schedule=schedule)
    cp = base / 'covered.json'
    if not cp.exists():
        raise BojInputError(f'{cp} 이 없다 — 발행본 장부가 고정되지 않았다(jp_daily_gates.py --pin 이 만든다)')
    cov = _load(cp)
    if cov.get('session') != session or not isinstance(cov.get('keys'), list):
        raise BojInputError(f'{cp} 가 세션 {session} 의 장부가 아니다({cov.get("session")})')
    ep = base / 'events.json'
    book = _load(ep) if ep.exists() else None
    events = (book or {}).get('events')
    try:
        due = CE.due_events(events, schedule, set(cov['keys']), session)
        missing = CE.missing_scheduled(schedule, events, session)
    except CE.ScheduleError as e:
        raise BojInputError(str(e))
    for e in due:
        if not CE.has_text(e):
            continue
        tp = base / f'{e["key"]}.txt'
        if not tp.exists():
            raise BojInputError(f'원문을 받았다고 한 이벤트 {e["key"]} 의 원문 파일 {tp} 이 없다')
        text = tp.read_text(encoding='utf-8')
        e['sources'] = [dict(x, text=text) if x.get('ok') else x for x in e.get('sources') or []]
    keys = {e['key'] for e in due}
    pick = lambda d: d if d and d.get('key') in keys else None  # noqa: E731
    return {'due': due, 'diff': pick((book or {}).get('diff')), 'outlook_diff': pick((book or {}).get('outlook_diff')),
            'missing': missing, 'schedule': schedule}


def boj_lines(state, root):
    """진단 출력 줄 — 작성자에게 넘긴다."""
    out = []
    base = Path(root) / 'japan' / 'data' / 'boj'
    if not state['due']:
        out.append('일본은행: 실을 이벤트 없음 — 「일본은행」 절을 쓰지 않는다')
    else:
        out.append(f'일본은행: 실을 이벤트 {len(state["due"])}건 — 전략 코멘트 바로 뒤에 '
                   '<section class="card" data-section="boj"> 절을 연다')
        for e in state['due']:
            where = ('원문 없음 — 인용·수치·아이디어 금지, 결정 사실만 기사 귀속으로' if not e.get('sources')
                     or not any(x.get('ok') for x in e['sources']) else f'원문 {base / (e["key"] + ".txt")}')
            out.append(f'  - {e["key"]} · {e["kind_ko"]} · 공개 {e["date"]} · {where}')
        for name, d in (('공표문 금리·표결 문장', state['diff']), ('전망 기본 견해 문장', state['outlook_diff'])):
            if d:
                out.append(f'  변경점({name}, 직전 {d.get("previous")}): 바뀐 {len(d["changed"])} · 추가 '
                           f'{len(d.get("added") or [])} · 삭제 {len(d.get("removed") or [])} — {base / "events.json"}')
    for m in state['missing']:
        out.append(f'  ! 예정된 {m["kind_ko"]}({m["date"]}) 원문을 못 받았다 — 절을 요구하지 않는다(알림)')
    return out


def cmd_diag(args):
    d = _load(snapshot_path(args.root, args.session))
    try:
        boj = boj_state(args.root, args.session)
    except BojInputError as e:
        print(f'  ! 일본은행: {e}')
        return 1
    want = R.order(d['calendar'].get('event_day'), boj=bool(boj['due']))
    news = _load(news_path(args.root, args.session)) if news_path(args.root, args.session).exists() else {}
    print(f'{args.session} complete={d["complete"]} 직전 세션={d["prev_session"]}')
    print('절 순서: ' + ' → '.join(want))
    if d['calendar'].get('event_day'):
        print('이벤트일: ' + ', '.join(e['name_ko'] for e in d['calendar']['event_day']))
    jgb = [f'{t} {r["period"]}' for t, r in (d.get('jgb') or {}).items() if isinstance(r, dict) and r]
    src = '네이버 당일' if R.jgb_source(d) == 'naver' else 'MOF 직전 세션'
    print(f'기준일 — JGB({src}) {", ".join(jgb) or "없음"} · 콜 {(d.get("call_rate") or {}).get("period")} · 엔 16:30 JST')
    print(f'뉴스 후보 {len(news.get("items") or [])}건 · 움직인 종목 묶음 {len(d["movers"]["groups"])}개')
    tg, why = load_telegram(args.root, args.session)
    if tg is None:
        print(f'견해·의견: 없음({why or "파일 없음"})')
    else:
        n = sum(1 for it in tg['items'] if it.get('news_use') is True)
        cut = (tg.get('stats') or {}).get('valve_dropped') or 0
        print(f'견해·의견 후보 {n}건' + (f' — {telegram_path(args.root, args.session)}' if n else '')
              + (f' (안전 한도로 {cut}건은 수집에서 빠졌다)' if cut else ''))
    bad = {k: v for k, v in d.get('fetch_status', {}).items() if v != 'ok'}
    for k, v in bad.items():
        print(f'  ! {k}: {v}')
    for line in boj_lines(boj, args.root):
        print(line)
    prev = Path(args.root) / 'japan' / 'daily' / f'{d["prev_session"]}.html'
    print(f'직전 일간: {prev if prev.exists() else "없음(첫 회)"}')
    # 이른(16:30 예약) 후보나 필드가 없는 옛 형식 후보는 네이버 당일 JGB 를 놓쳤을 수 있다 — 다시 수집할 때까지
    # 발행하지 않는다(codex 구현 검토 #2·#3). 재수집도 실패하면 재시도 회차가 이어받는다.
    published = (Path(args.root) / 'japan' / 'data' / 'daily' / f'{args.session}.json').exists()
    if d.get('schema') == 2:
        b = (d.get('facts') or {}).get('blocks') or {}
        curve = b.get('curve') or {}
        print(f'생성 문장 — TOPIX {b.get("topix")} · 업종 {b.get("sectors")} · '
              f'스프레드 2~10년 {curve.get("s2s10")} / 10~30년 {curve.get("s10s30")} '
              '(본문에는 <!--G:topix-->·<!--G:sectors-->·<!--G:curve--> 자리만 둔다)')
        if B.has_b(d):
            print(B.status_line(d) + ' — 주식 절 바로 아래에 <!--G:usual--> 자리를 하나 더 둔다(평소 대비 문장). '
                  '%·bp 수는 data-ref 로 묶거나 종목·닛케이의 그날 등락률 그대로만 쓴다 — 기간 변화·배수·어림수는 '
                  '표와 생성 문장이 말한다')
            for line in (d.get('facts') or {}).get('b_diag') or []:
                print(f'  ! {line}')
        miss = ((d.get('calendar') or {}).get('coverage') or {}).get('today_missing') or []
        if miss:
            print(f'일정표 미확인 계열: {"·".join(miss)} — 「오늘 발표가 없다」를 쓰지 않는다(캡션이 말한다)')
    # 2판이 아닌 미발행 후보는 v2 조립·게이트에 맞지 않는다 — 다시 수집한다(설계 §6 전환)
    if not published and d.get('schema') != 2:
        print('  ! schema: 2판 스냅샷이 아니다 — 다시 수집해야 한다')
        return 1
    if not published and d.get('jgb_recollect', True) is not False:
        print('  ! jgb_recollect: 네이버 JGB 마감 확정 전 후보 — 다시 수집해야 한다')
        return 1
    return 0 if d['complete'] else 1


def _run_dir_of(out):
    """조립본이 일본 일간 실행 폴더(입력 고정 기록이 있는 곳) 안이면 그 폴더."""
    d = Path(out).resolve().parent
    return d if (d / 'inputs.json').exists() else None


def cmd_assemble(args):
    # 새 판을 조립하는 순간 앞 판의 통과 기록과 조립본은 이 실행의 발행 자격을 잃는다(codex 구현 1회차 #1)
    run_dir = _run_dir_of(args.out)
    if run_dir is not None:
        from jp_daily_gates import invalidate
        invalidate(str(run_dir), '새 판 조립 시작')
        Path(args.out).unlink(missing_ok=True)
    body = Path(args.body).read_text(encoding='utf-8')
    meta = _load(args.meta)
    d = _load(snapshot_path(args.root, args.session))
    try:
        boj = bool(boj_state(args.root, args.session)['due'])
        errs = []
    except BojInputError as e:
        boj, errs = False, [f'일본은행: {e}']
    errs += R.validate_body(body, R.order(d['calendar'].get('event_day'), boj=boj), schema=d.get('schema'),
                            b=B.has_b(d))
    for k in ('title', 'summary'):
        if not str(meta.get(k, '')).strip():
            errs.append(f'meta.json 에 {k} 가 없다')
    if not errs:
        np = news_path(args.root, args.session)
        body, errs = expand(body, _load(np) if np.exists() else {'items': []})
    if errs:
        for e in errs:
            print(f'  - {e}')
        if run_dir is not None:
            invalidate(str(run_dir), '조립 실패', errs)
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(R.assemble(body, meta, d), encoding='utf-8')
    print(f'{args.out} 조립 완료')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    dg = sub.add_parser('diag')
    a = sub.add_parser('assemble')
    for p in (dg, a):
        p.add_argument('--session', required=True)
        p.add_argument('--root', default='.')
    for k in ('--body', '--meta', '--out'):
        a.add_argument(k, required=True)
    args = ap.parse_args(argv)
    return {'diag': cmd_diag, 'assemble': cmd_assemble}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
