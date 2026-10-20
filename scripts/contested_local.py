#!/usr/bin/env python3
"""쟁점 분석 로컬 러너 — Mac 의 launchd 가 15분마다 부른다(`runner_launch.py contested run`).

2026-10-21 사용자: 「최대한 claude 주간한도를 사용하도록」 → 「로컬로 하자」. 판단은 Mac 에 로그인된
Claude Code(`claude -p`, 구독)가 하고, 이 러너는 수집·대조·조립·발행을 맡는다. 클라우드 루틴은
결과 JSON 을 읽어 섹션을 찍기만 한다.

한 tick 이 하는 일(대부분의 tick 은 할 일이 없어 몇 초 만에 끝난다):
1. origin/main 을 임시 폴더에 새로 clone 한다 — 사람 폴더는 읽지도 움직이지도 않는다.
2. 시장마다(US 뉴스·산업 브리프, KR 마감 브리프 — `contested.MARKET_CFG`) 시장 파일이 완성된 최근
   기준일과 자리표시가 남은 최근 발행본 날짜를 모은다.
3. 그 날짜 결과(`data/contested/<시장>/<D>.json`)가 확정 전이면 수집 → (US 만 고르기) → 추출·검증 →
   조립. **분석은 tick 당 시장을 통틀어 하나** — 직전 tick 에 분석한 시장은 뒤로 돈다(한도 교대).
4. 발행본이 이미 자리표시(`PENDING`)를 갖고 있으면 섹션을 채우고 게이트를 돈다(못 넘으면 명시적
   생략 기록). 확정된 결과가 섹션이 아니면 자리표시를 지운다. KR 은 발행 커밋의 kr/data 로 KR 데이터
   게이트를 앞판·뒷판 둘 다 돌려 새 실패만 막고, 섹션 밖 본문이 그대로인지 본다(KR 설계 검토 K14).
5. 결과(와 고친 발행본)를 커밋·푸시한다. 그 사이 발행본이 바뀌었으면 버린다.

KR 검색 키(NAVER API HUB)는 환경 변수가 없으면 키체인(`fdo2a-naver-client-id`·`-secret`)에서 읽는다.
키가 없거나 인증·정지·한도 오류면 수집기가 그날 언론사 RSS 로 바꾸고 사유를 진단에 남긴다.

    python3 scripts/contested_local.py run [--date D] [--dry-run]
"""

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import contested as C  # noqa: E402

KST = timezone(timedelta(hours=9))
LOCK = os.path.expanduser('~/Library/Caches/fdo2a-contested.lock')
MAX_AGE_DAYS = 3


def _git(cwd, *args, check=True, timeout=120):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}')
    return p.stdout.strip()


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save(path, payload):
    payload['content_hash'] = C.content_hash(payload)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def page_state(html):
    """발행본의 쟁점 자리 — 'none'(글 없음)·'pending'·'section'·'omitted'·'absent'."""
    if html is None:
        return 'none'
    if C.PENDING in html:
        return 'pending'
    if 'data-contested=' in html:
        return 'section'
    if C.OMIT_RE.search(html):
        return 'omitted'
    return 'absent'


def plan(prev, page, date, market='us'):
    """이번 tick 에 할 일 — 'analyze'·'fill'·'clear'·'skip'."""
    done = C.settled(prev, market, date)
    if page in ('section', 'omitted', 'absent'):
        # 발행 증거가 묶였거나, 쟁점 자리 없이 나간 글(이 기능 전 발행본·확정 none 으로 지운 자리)
        return 'skip'
    if not done:
        return 'analyze'
    if page == 'pending':
        return 'fill' if prev['status'] == 'ok' else 'clear'
    return 'skip'


def gates(clone, rel, json_path, date, market='us'):
    """발행 게이트(쟁점 섹션을 채운 뒤) — (통과 여부, 출력 끝)."""
    py = sys.executable
    chain = [[py, 'scripts/apply_readability.py', rel]]
    if market == 'us':
        chain.append([py, 'scripts/apply_colors.py', rel])     # KR 루틴은 색을 입히지 않는다
    cmds = chain + [[py, 'scripts/check_contested.py', '--html', rel, '--json', json_path,
                     '--market', market, '--date', date],
                    [py, 'scripts/check_readability.py', '--strict', '--no-inline-images', rel],
                    [py, 'scripts/check_style.py', rel]]
    if market == 'kr':
        # 레이아웃(390·1280 폭) — 자기 자신과 대조해 수치 대조는 끄고 브라우저 검사만 돈다
        cmds.append([py, 'scripts/verify_post.py', rel, '--before', rel])
    for c in cmds:
        p = subprocess.run(c, cwd=clone, capture_output=True, text=True, timeout=300)
        if p.returncode:
            return False, f'{c[1]}: {(p.stdout + p.stderr).strip()[-400:]}'
    return True, ''


KR_DATA_GATES = ('check_session.py', 'check_weight.py', 'check_news.py', 'check_movers.py', 'check_fund.py')


def _evidence_dir(clone, rel, temp):
    """그 글을 처음 넣은 커밋의 kr/data → 임시 폴더. 다음 날 데이터로 어제 글을 검사하지 않는다."""
    first = _git(clone, 'log', '--diff-filter=A', '--format=%H', '-1', '--', rel, check=False)
    if not first:
        return None
    d = os.path.join(temp, f'evidence-{first[:10]}')
    if not os.path.isdir(d):
        os.makedirs(d)
        tar = subprocess.run(['git', 'archive', '--format=tar', first, 'kr/data'], cwd=clone,
                             capture_output=True, timeout=120)
        if tar.returncode:
            return None
        subprocess.run(['tar', '-x', '-C', d], input=tar.stdout, capture_output=True, check=True)
    return os.path.join(d, 'kr', 'data')


def kr_data_gates(clone, rel, before_html, date, temp):
    """KR 데이터 게이트를 앞판·뒷판에 같은 근거로 → 새로 생긴 실패 목록(빈 목록 = 통과).

    발행 뒤 데이터가 바뀌어 원래도 실패하는 게이트(10/20 의 check_news 처럼)는 섹션 탓이 아니다 —
    앞판과 출력이 같으면 넘긴다."""
    data = _evidence_dir(clone, rel, temp)
    if not data:
        return ['발행 커밋의 kr/data 를 못 꺼냈다']
    bdir = os.path.join(temp, 'before', os.path.dirname(rel))
    os.makedirs(bdir, exist_ok=True)
    bpath = os.path.join(bdir, os.path.basename(rel))
    with open(bpath, 'w', encoding='utf-8') as fh:
        fh.write(before_html)
    apath = os.path.join(clone, rel)
    bad = []
    for g in KR_DATA_GATES:
        extra = ['--date', date] if g == 'check_news.py' else []
        outs = []
        for path in (bpath, apath):
            p = subprocess.run([sys.executable, f'scripts/{g}', '--html', path, '--datadir', data,
                                '--market', 'kr', *extra], cwd=clone, capture_output=True, text=True,
                               timeout=300)
            outs.append((p.returncode, (p.stdout + p.stderr).replace(path, '<post>')))
        (rb, ob), (ra, oa) = outs
        if ra and (not rb or ob != oa):
            bad.append(f'{g}: {oa.strip()[-300:]}')
    return bad


def outside_section(html):
    """쟁점 자리를 하나의 표지로 바꾼 나머지 — 섹션 밖이 그대로인지 본다."""
    return C.strip_slot(html)


def fill(clone, date, payload, market='us', temp=None):
    """발행본의 자리표시를 채운다(또는 지운다) → 바뀐 파일 목록과 메모."""
    sys.path.insert(0, os.path.join(clone, 'scripts'))
    import render_contested as R
    cfg = C.MARKET_CFG[market]
    rel = cfg['page'].format(d=date)
    path = os.path.join(clone, rel)
    with open(path, encoding='utf-8') as fh:
        before = fh.read()
    jpath = os.path.join(clone, cfg['result'].format(d=date))
    after = R.apply(before, payload)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(after)
    if payload.get('status') != 'ok':
        return [rel], 'cleared'

    def check():
        ok, why = gates(clone, rel, jpath, date, market)
        if not ok or market != 'kr':
            return ok, why
        with open(path, encoding='utf-8') as fh:
            now = fh.read()
        if outside_section(now) != outside_section(before):
            return False, '섹션 밖 본문이 바뀌었다'
        bad = kr_data_gates(clone, rel, before, date, temp or tempfile.gettempdir())
        return (False, '; '.join(bad)[:400]) if bad else (True, '')
    ok, why = check()
    if ok:
        return [rel], 'filled'
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(R.apply(before, payload, omit='gate_failed'))
    ok2, why2 = check()
    if not ok2:
        raise RuntimeError(f'생략 뒤에도 게이트 실패 — {why2}')
    return [rel], f'omitted({why[:120]})'


class Interrupted(BaseException):
    """launchd·런처가 보낸 SIGTERM — 일반 예외 처리에 삼켜지지 않게(3차 P2)."""


STATE = os.path.expanduser('~/Library/Caches/fdo2a-contested-state.json')
ANALYZE_MAX_HOURS = 36        # 기준일 발행 뒤 이만큼 지나면 분석하지 않고 자리표시를 지운다


def _attempts_local(date, bump=False, at_least=0, market='us'):
    """날짜별 시도 횟수를 로컬에도 적는다 — 푸시가 계속 실패해도 3회 상한이 걸린다(3차 P2).
    열쇠는 `시장:날짜`. US 는 옛 열쇠(날짜만)도 읽는다."""
    try:
        with open(STATE, encoding='utf-8') as fh:
            st = json.load(fh)
        st = st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        st = {}
    key = f'{market}:{date}'
    n = st.get(key) if isinstance(st.get(key), int) else 0
    if market == 'us' and isinstance(st.get(date), int):
        n = max(n, st[date])
    if bump and os.environ.get('CONTESTED_DRY'):
        return n + 1                       # 시험 운행은 실제 시도 횟수를 쓰지 않는다
    if bump:
        n = max(n, at_least)                # 원격에 적힌 횟수보다 작아지지 않게(4차 P2)
        st[key] = n + 1
        st = {k: v for k, v in st.items() if isinstance(v, int)}
        tmp = STATE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(dict(sorted(st.items(), key=lambda kv: kv[0].split(':')[-1])[-60:]), fh)
        os.replace(tmp, STATE)
        return n + 1
    return n


def _normalize(prev):
    if not isinstance(prev, dict):
        return None
    if C.validate(prev) == ['구조가 깨졌다']:
        n = prev.get('attempts')
        return {'attempts': n if isinstance(n, int) and not isinstance(n, bool) else 0}
    if not isinstance(prev.get('attempts'), int) or isinstance(prev.get('attempts'), bool):
        prev = dict(prev, attempts=0)
    return prev


def push(clone, files, msg, page_shas):
    _git(clone, 'add', *files)
    if not _git(clone, 'status', '--porcelain', '--untracked-files=no', check=False):
        return 'nothing'
    base = _git(clone, 'rev-parse', 'HEAD')
    _git(clone, 'commit', '-q', '-m', msg)
    if subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], cwd=clone).returncode == 0:
        return 'pushed'
    _git(clone, 'fetch', '-q', 'origin', 'main')
    for f, sha in page_shas.items():
        if _git(clone, 'rev-parse', f'origin/main:{f}', check=False) != sha:
            return f'abandoned: {f} 가 그 사이 바뀌었다'
    # 그 사이 게이트·러너 코드가 바뀌었으면 옛 코드로 검사한 결과를 밀지 않는다 — 다음 tick 에 새 코드로
    moved = _git(clone, 'diff', '--name-only', base, 'origin/main', '--', 'scripts', '.claude', check=False)
    if moved:
        return 'abandoned: 코드가 그 사이 바뀌었다'
    if subprocess.run(['git', 'rebase', '-q', 'origin/main'], cwd=clone).returncode:
        subprocess.run(['git', 'rebase', '--abort'], cwd=clone)
        return 'abandoned: rebase 충돌'
    if subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], cwd=clone).returncode:
        return 'abandoned: push 거절'
    return 'pushed'


def _market_for(clone, date, temp, market='us'):
    """그 기준일의 완성된 시장 파일을 히스토리에서 찾아 임시 폴더에 둔다 → (datadir, commit).
    KR 은 보조 파일(금리·수급·세션)까지 **같은 커밋**에서 꺼낸다."""
    cfg = C.MARKET_CFG[market]
    main = cfg['market_file']
    for oid in _git(clone, 'log', '--format=%H', '-n', '40', '--', main).split():
        raw = _git(clone, 'show', f'{oid}:{main}', check=False)
        try:
            md = json.loads(raw)
        except ValueError:
            continue
        if md.get('report_date') == date and md.get('complete'):
            d = os.path.join(temp, f'data-{market}-{date}')
            os.makedirs(d, exist_ok=True)
            for f in (main, *cfg['extra_files']):
                body = raw if f == main else _git(clone, 'show', f'{oid}:{f}', check=False)
                if body:
                    with open(os.path.join(d, os.path.basename(f)), 'w', encoding='utf-8') as fh:
                        fh.write(body)
            return d, oid
    return None, None


def _dates(clone, md, market='us'):
    """볼 날짜 — 현재 기준일 + 자리표시가 남은 최근 발행본(시장 기준일이 넘어가도 놓치지 않게, 3차 P1)."""
    out = []
    if md.get('report_date'):
        out.append(md['report_date'])
    today = datetime.now(KST).date()
    pdir = os.path.join(clone, C.MARKET_CFG[market]['pages_dir'])
    for name in sorted(os.listdir(pdir) if os.path.isdir(pdir) else []):
        m = re.fullmatch(r'(\d{4}-\d{2}-\d{2})\.html', name)
        if not m or m.group(1) in out:
            continue
        if (today - datetime.fromisoformat(m.group(1)).date()).days > MAX_AGE_DAYS:
            continue
        with open(os.path.join(pdir, name), encoding='utf-8') as fh:
            if C.PENDING in fh.read():
                out.append(m.group(1))
    return sorted(out)


def naver_keys():
    """KR 검색 키 — 환경 변수가 없으면 키체인에서 이 프로세스 환경에만 넣는다. 값은 출력하지 않는다."""
    for env, svc in (('NAVER_CLIENT_ID', 'fdo2a-naver-client-id'),
                     ('NAVER_CLIENT_SECRET', 'fdo2a-naver-client-secret')):
        if os.environ.get(env):
            continue
        p = subprocess.run(['security', 'find-generic-password', '-s', svc, '-w'], capture_output=True,
                           text=True)
        if p.returncode == 0 and p.stdout.strip():
            os.environ[env] = p.stdout.strip()
    return bool(os.environ.get('NAVER_CLIENT_ID') and os.environ.get('NAVER_CLIENT_SECRET'))


def handle(clone, temp, date, md_current, notes, market='us'):
    """한 날짜 → (바뀐 파일, 발행본 sha, 메모) 또는 None(할 일 없음)."""
    cfg = C.MARKET_CFG[market]
    rel_json = cfg['result'].format(d=date)
    jpath = os.path.join(clone, rel_json)
    prev = _normalize(_load(jpath))
    page_rel = cfg['page'].format(d=date)
    page_path = os.path.join(clone, page_rel)
    html = open(page_path, encoding='utf-8').read() if os.path.exists(page_path) else None
    shas = {page_rel: _git(clone, 'rev-parse', f'HEAD:{page_rel}', check=False)} if html else {}
    todo = plan(prev, page_state(html), date, market)
    if todo == 'skip':
        return None
    files = []
    if todo == 'analyze':
        age_h = (datetime.now(KST) - datetime.fromisoformat(date).replace(tzinfo=KST)).total_seconds() / 3600
        attempts = max((prev or {}).get('attempts', 0), _attempts_local(date, market=market))
        stale = age_h > ANALYZE_MAX_HOURS + 24
        if market == 'kr' and not stale:
            from collect_contested_kr import cutoff_of
            if datetime.now(KST) < cutoff_of(date):
                # 편집 기준 시각(D 20:00 KST) 전에는 분석하지 않는다 — 시도 횟수도 쓰지 않는다(구현 검토 #2).
                # 그날 18:00 루틴은 자리표시로 나가고 20시 뒤 tick 이 채운다.
                notes.append(f'{market} {date} 기준 시각 전')
                return None
        if stale or attempts >= C.MAX_ATTEMPTS:
            reason = 'stale' if stale else 'attempts_exhausted'
            result = _final_error(date, prev, reason, market)
        else:
            result = analyze_date(clone, temp, date, md_current, prev, market)
        _save(jpath, result)
        files.append(rel_json)
        with open(os.path.expanduser(f'~/Library/Caches/fdo2a-contested-last-{market}.json'), 'w') as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
        note = f'{result["status"]}({result.get("reason") or "-"})'
        if html is not None and page_state(html) == 'pending' and C.settled(result, market, date):
            f, n = fill(clone, date, result, market, temp)
            files += f
            note += f' · 발행본 {n}'
    else:
        result = prev
        f, n = fill(clone, date, result, market, temp)
        files += f
        note = f'{result["status"]} · 발행본 {n}'
    topic = ((result or {}).get('event') or {}).get('topic_ko') or ''
    notes.append(f'{market} {date} {note}' + (f' · {topic}' if topic else ''))
    return files, (shas if any(f == page_rel for f in files) else {})


def _base(date, attempts, market='us'):
    import contested_build as Bld
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return {'schema_version': C.SCHEMA_VERSION, 'market': market, 'span': 'daily', 'report_date': date,
            'status': 'error', 'reason': 'unknown', 'retryable': True, 'attempts': attempts,
            'collected_at': now, 'cutoff_at': now,
            'model': {k: Bld.MODELS[k] for k in (('pick', 'extract', 'verify') if market == 'us'
                                                 else ('extract', 'verify'))},
            'prompt_version': C.PROMPT_VERSION, 'market_snapshot': None, 'counts': {},
            'diagnostics': {'runner': 'local'}, 'event': {'topic_ko': '', 'query': '', 'trigger': []}}


def _final_error(date, prev, reason, market='us'):
    b = _base(date, max((prev or {}).get('attempts', 0), _attempts_local(date, market=market)), market)
    return dict(b, status='error', reason=reason, retryable=False)


def analyze_date(clone, temp, date, md_current, prev, market='us'):
    """수집·분석 한 번 → 결과 dict. 어떤 실패도 결과로 남긴다(3차 P2)."""
    import contested_build as Bld
    attempts = _attempts_local(date, bump=True, at_least=(prev or {}).get('attempts', 0),
                               market=market)                                  # 수집 전에 적는다
    base = _base(date, attempts, market)
    try:
        if market == 'us' and md_current.get('report_date') == date and md_current.get('complete'):
            datadir, oid = 'data', None
        else:
            # KR 은 늘 히스토리에서 같은 커밋의 네 파일을 꺼낸다 — 보조 파일만 하루 밀린 짝을 막는다
            datadir, oid = _market_for(clone, date, temp, market)
            if not datadir:
                return dict(base, status='error', reason='market_data_not_found', retryable=True)
        if market == 'kr':
            # 키가 없거나 네이버가 막히면 수집기가 그날 언론사 RSS 로 바꾼다(사용자 2026-10-21) — 건너뛰지 않는다
            naver_keys()
            from collect_contested_kr import collect as collect_kr
            bundle = collect_kr(date, datadir, commit=oid)
        else:
            from collect_contested import collect
            bundle = collect(date, datadir, rank=Bld.ranker(diag=base['diagnostics']))
            if oid and isinstance(bundle.get('market_snapshot'), dict):
                bundle['market_snapshot'] = dict(bundle['market_snapshot'], path='data/market_data.json',
                                                 commit=oid)
        base['counts'] = {'harvest': bundle.get('harvest'),
                          'candidates': len(bundle.get('candidates') or []),
                          'articles': [len(c['articles']) for c in bundle.get('candidates') or []]}
        base['diagnostics'].update(discovery=bundle.get('discovery'), hosts=bundle.get('hosts'),
                                   notes=bundle.get('notes'))
        if market == 'kr':
            base['diagnostics'].update(source=bundle.get('source'), source_switch=bundle.get('source_switch'))
        if market == 'us':
            base['diagnostics']['gdelt'] = bundle.get('gdelt')
        result = Bld.analyze(bundle, base)
    except Interrupted:
        raise
    except Exception as e:
        result = dict(base, status='error', reason=f'analyze_{type(e).__name__}'[:40], retryable=True)
    if result.get('status') != 'ok' and attempts >= C.MAX_ATTEMPTS:
        result['retryable'] = False                # 시도를 다 썼다 — 자리표시를 지운다
    return result


ROTATE = os.path.expanduser('~/Library/Caches/fdo2a-contested-rotate.json')


def _order():
    """시장 순서 — 직전 tick 에 분석한 시장을 뒤로(한 시장이 한도를 몰아 쓰지 않게, K13)."""
    try:
        with open(ROTATE, encoding='utf-8') as fh:
            last = json.load(fh).get('last')
    except (OSError, ValueError, AttributeError):
        last = None
    return [m for m in C.MARKETS if m != last] + [m for m in C.MARKETS if m == last]


def _remember(market):
    if os.environ.get('CONTESTED_DRY'):
        return
    with open(ROTATE, 'w', encoding='utf-8') as fh:
        json.dump({'last': market}, fh)


def tick(root, date=None, dry=False, markets=None):
    if dry:
        os.environ['CONTESTED_DRY'] = '1'
    remote = _git(root, 'remote', 'get-url', 'origin')
    with tempfile.TemporaryDirectory(prefix='contested-') as temp:
        clone = os.path.join(temp, 'repo')
        _git(temp, 'clone', '-q', '--no-local', '--single-branch', '--branch', 'main', '--depth', '80',
             remote, clone, timeout=300)
        os.chdir(clone)                      # 스냅샷(git log)·게이트가 clone 기준으로 돈다
        files, shas, notes, looked = [], {}, [], []
        analyzed = None
        for market in [m for m in _order() if not markets or m in markets]:
            cfg = C.MARKET_CFG[market]
            md = _load(os.path.join(clone, cfg['market_file'])) or {}
            dates = [C.iso_date(date)] if date else _dates(clone, md, market)
            looked += [f'{market}:{d}' for d in dates]
            for d in dates:
                prev = _normalize(_load(os.path.join(clone, cfg['result'].format(d=d))))
                page = os.path.join(clone, cfg['page'].format(d=d))
                html = open(page, encoding='utf-8').read() if os.path.exists(page) else None
                if plan(prev, page_state(html), d, market) == 'analyze' and analyzed:
                    continue                   # 한 tick 에 분석은 한 건만 — 한도를 몰아 쓰지 않는다
                got = handle(clone, temp, d, md, notes, market)
                if got:
                    files += got[0]
                    shas.update(got[1])
                    if any(f.startswith('data/') for f in got[0]):
                        analyzed = market
        if analyzed:
            _remember(analyzed)
        if not files:
            return 'skip: 할 일 없음 ' + ' '.join(looked) + (f' · {" / ".join(notes)}' if notes else '')
        if dry:
            return 'dry-run: ' + ' / '.join(notes)
        mk = sorted({f.split('/')[2] for f in files if f.startswith('data/contested/')}) or ['page']
        msg = f'data: contested analysis {"+".join(mk)} — ' + ' / '.join(notes) + \
            '\n\n로컬 러너(claude -p, 구독)가 만든 쟁점 분석 결과.'
        return ' / '.join(notes) + ' · ' + push(clone, sorted(set(files)), msg, shas)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['run'])
    ap.add_argument('--date', type=C.iso_date)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--market', choices=C.MARKETS, action='append')
    a = ap.parse_args(argv)
    root = _git(os.getcwd(), 'rev-parse', '--show-toplevel')
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, 'w') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('[쟁점] 다른 tick 이 돌고 있다')
            return 0
        def _term(*_):
            raise Interrupted()
        signal.signal(signal.SIGTERM, _term)
        try:
            print(f'[쟁점 {datetime.now(KST):%m-%d %H:%M}] {tick(root, a.date, a.dry_run, a.market)}')
        except Interrupted:
            print('[쟁점] SIGTERM — 정리하고 끝낸다(시도 횟수는 이미 적었다)', file=sys.stderr)
            return 143
        except Exception as e:
            print(f'[쟁점] 실패 — {type(e).__name__}: {str(e)[:300]}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
