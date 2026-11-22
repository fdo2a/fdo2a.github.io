#!/usr/bin/env python3
"""수집이 끝난 자료 폴더의 파일마다 해시·크기·수집 상태를 `<datadir>/_collect_status.json` 에 적는다(2026-11-17).

    python3 scripts/stamp_collect.py --datadir data        # US 수집 잡, 커밋 직전
    python3 scripts/stamp_collect.py --datadir kr/data     # KR 수집 잡, versions.py commit 직전

명세 「공통 계약 A」의 마지막 고리다. 수집기는 자기가 쓴 JSON 객체에 `collect` 칸을 넣고, 목록형 파일
(`kr_top_value.json`·`kr_index_etf.json`)은 `common.collect_status.record_sidecar()` 로 이 파일에 적는다.
여기서는 **이 수집 잡이 쓰는 파일**(아래 등록표)마다

    files["<datadir 기준 상대경로>"] = {"present": bool, "sha256": "...", "bytes": N,
                                       "collect_in": "file"|"sidecar"|"producer:<rel>"|"none",
                                       <collect 칸과 같은 모양: status·as_of·…·empty>}

을 만든다. 해시는 「수집 뒤 바뀜」을 가리는 근거다 — 그래서 루틴이 정당하게 고치는 상태 파일
(`macro.json`·`kr_stance.json`·`kr_stance_next.json`)과 매일 쌓이는 원장(`history/`·`weekly/`)은 등록하지 않는다.

* `collect_in: file` — JSON 안의 `collect` 칸을 그대로 옮긴다(두 곳이 다르면 해시가 이미 다르다).
* `sidecar` — 수집기가 이 파일에 직접 적은 상태(목록형). 지난 실행의 기록은 그 파일이 이번에 다시 쓰이지
  않았으면 그대로 그 바이트를 설명한다.
* `producer:<rel>` — 비 JSON 산출물(표 HTML·차트·원문 txt)은 그것을 만든 JSON 의 칸을 옮긴다.
* `none` — 칸이 없다(옛 형식이거나 수집기가 칸을 쓰기 전에 죽었다). 검사 쪽이 「상태 없음」으로 본다.

`--begin`(잡 시작, 수집 앞)이 이번 실행의 시작 시각을 적는다. 끝의 stamp 는 파일마다 `run` 을 적는다 — written(이번
실행이 썼다) / skipped(단계가 건너뛰었다) / kept(동결) / failed(단계는 돌았는데 파일이 다시 쓰이지 않았다 — 같은 날 앞선
실행의 정상 파일이 남아 있어도 `status: failed`, 그 바이트의 해시·상태는 `stale_copy` 로) / unknown / untracked.
단계 결과는 환경 변수 `COLLECT_STEPS`(`${{ toJSON(steps) }}`)로 받는다(1a 구현 검토 2회차 F3).

판정하지 않는다 — 기록만 한다. exit 0(쓰기 실패만 1).
"""
import argparse
import datetime as _dt
import glob
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import collect_status as C  # noqa: E402

COLLECT_KEYS = ('status', 'as_of', 'collected_at', 'source', 'response', 'required_ok', 'missing', 'empty',
                'checked', 'expected', 'detail', 'missing_ref')

# 이 잡이 쓰는 파일. {D} = 그날 report_date. 값 = 비 JSON 파일의 생산자(JSON) — None 이면 JSON 자체.
REGISTRY = {
    'us': {
        'market_data.json': None, 'econ_indicators.json': None, 'intraday.json': None,
        'macro_eval.json': None, 'macro_metrics.json': None, 'movers.json': None,
        'fund_board.json': None, 'calendar.json': None, 'auctions.json': None,
        'fed/events.json': None, 'liquidity/liquidity.json': None, 'releases/index.json': None,
        'telegram/{D}.json': None,
        # 작성 재료·참고(검사기가 직접 안 읽거나 짝 JSON 으로 대조) — 해시만 남긴다.
        'news/{D}.json': None, 'scorecard.json': None, 'fund_factors.json': None,
        'fomc_dates.json': None, 'fed/seen.json': None, 'fed/statements.json': None,
        'liquidity/state.json': None,
        'sector_performance.html': 'market_data.json', 'yield_curve.png': 'market_data.json',
        'fund_board.html': 'fund_board.json', 'auction_table.html': 'auctions.json',
        'liquidity/table.html': 'liquidity/liquidity.json',
        'liquidity/qra/*.txt': 'liquidity/liquidity.json',
        'releases/*.txt': 'releases/index.json',
        'fed/*.txt': 'fed/events.json',
    },
    'kr': {
        'kr_market_data.json': None, 'kr_session.json': None, 'kr_movers.json': None,
        'kr_fund_view.json': None, 'kr_stance_eval.json': None, 'kr_flows.json': None,
        'kr_intraday.json': None, 'kr_econ.json': None, 'telegram/{D}.json': None,
        'kr_top_value.json': None, 'kr_index_etf.json': None,
        'news/{D}.json': None, 'kr_program.json': None, 'kr_technical.json': None,
        'kr_stock_moves.json': None, 'kr_industry.json': None, 'kr_theme.json': None,
        'kr_flows_intraday.json': None, 'kr_charts_manifest.json': None,
        'kr_sector.html': 'kr_market_data.json', 'kr_fund_view.html': 'kr_fund_view.json',
    },
}
MARKET_FILE = {'us': 'market_data.json', 'kr': 'kr_market_data.json'}

# ── 이번 실행이 그 파일을 실제로 다시 썼는가(2026-11-17, 1a 구현 검토 2회차 F3) ──────────────────────────
# 같은 날 앞선 실행의 정상 파일이 남아 있으면, 이번 실행이 그 파일을 쓰지 못해도(예외를 삼켰거나 단계가 죽었거나)
# 옛 파일의 `collect` 가 「성공」이라 장부에 성공으로 다시 찍혔다. 그래서 잡 시작에 `--begin` 이 시각을 적고,
# 여기서 파일의 `collect.collected_at`(칸이 없는 참고 파일은 mtime)이 그 뒤인지 본다.
# 등록표 패턴 → 그 파일을 쓰는 워크플로 단계 id(`steps.<id>` — 워크플로의 id 와 같아야 한다, 시험이 묶는다).
STEP_OF = {
    'us': {'market_data.json': 'collect', 'econ_indicators.json': 'collect', 'intraday.json': 'collect',
           'movers.json': 'collect', 'fund_board.json': 'collect', 'macro_metrics.json': 'collect',
           'scorecard.json': 'collect', 'macro_eval.json': 'macro_eval', 'releases/index.json': 'releases',
           'fed/events.json': 'fed', 'calendar.json': 'calendar', 'auctions.json': 'auctions',
           'liquidity/liquidity.json': 'liquidity', 'telegram/{D}.json': 'telegram',
           'news/{D}.json': 'news'},       # US 뉴스 글의 gate 자료(2026-11-22) — fetch_news.py 가 collect 칸을 쓴다
    'kr': {'kr_market_data.json': 'collect', 'kr_session.json': 'collect', 'kr_movers.json': 'collect',
           'kr_fund_view.json': 'collect', 'kr_stance_eval.json': 'collect', 'kr_flows.json': 'collect',
           'kr_intraday.json': 'collect', 'kr_econ.json': 'collect', 'kr_top_value.json': 'collect',
           'kr_index_etf.json': 'collect', 'telegram/{D}.json': 'telegram'},
}
# 단계가 성공하고도 일부러 다시 쓰지 않는 파일 — 요약이 있는 날의 텔레그램 파일은 동결된다(fetch_telegram.frozen).
# 뉴스도 요약이 끝난 날은 동결된다(fetch_news.frozen — 단 collect 가 ok 가 아닌 판은 동결하지 않는다).
MAY_KEEP = ('telegram/{D}.json', 'news/{D}.json')
# `collect` 칸이 없는 참고 파일 — 파일 수정 시각으로 본다(Actions 의 checkout 은 잡 시작 전이다).
MTIME_ONLY = ('scorecard.json',)
RUN_OK = ('written', 'skipped', 'kept')
RUN_STATES = RUN_OK + ('failed', 'unknown', 'untracked')
STEPS_ENV = 'COLLECT_STEPS'           # 워크플로가 `${{ toJSON(steps) }}` 를 넣는다
# 이번 실행의 ID — 워크플로가 `${{ github.run_id }}-${{ github.run_attempt }}` 를 두 단계(--begin·stamp)에 같이 넣는다.
# 시작 기록은 **그것을 연 실행**의 stamp 만 쓴다(3회차 G4: 앞 실행이 열어 두고 죽은 기록을 다음 실행이 제 것으로 읽었다).
RUN_ID_ENV = 'COLLECT_RUN_ID'


def current_run_id(explicit=None):
    """이번 실행의 ID — 인자 > `COLLECT_RUN_ID` > `GITHUB_RUN_ID-GITHUB_RUN_ATTEMPT`. 모르면 None(추정하지 않는다)."""
    if explicit:
        return str(explicit)
    if os.environ.get(RUN_ID_ENV):
        return os.environ[RUN_ID_ENV]
    if os.environ.get('GITHUB_RUN_ID'):
        return f"{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return None


def _parse(ts):
    try:
        t = _dt.datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else None


def _steps():
    """워크플로 단계 결과 `{id: {outcome, outputs}}` — 없거나 못 읽으면 None(모른다)."""
    raw = os.environ.get(STEPS_ENV)
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def begin(datadir, now=None, run_id=None):
    """잡 시작(checkout 뒤·수집 앞) — 이번 실행의 시작 시각과 실행 ID 를 장부에 적는다. 파일 항목은 건드리지 않는다.
    실행 ID 를 모르면(로컬) 하나 만들어 적는다 — 끝의 stamp 에 `--run-id`(또는 `COLLECT_RUN_ID`)로 넘겨야 같은 실행이다."""
    rid = current_run_id(run_id)
    generated = rid is None
    if generated:
        import uuid
        rid = 'local-' + uuid.uuid4().hex[:12]
    book = C.load_status(datadir)
    book['run'] = {'started_at': C.now_iso(now), 'open': True, 'failures': {}, 'run_id': rid, 'generated': generated}
    C.write_status(datadir, book)
    return book['run']


def _own_run(run, run_id):
    """장부의 시작 기록이 **이번 실행**의 것인가 — 열려 있고, 시각을 읽을 수 있고, 실행 ID 가 같다."""
    return (isinstance(run, dict) and run.get('open') is True and _parse(run.get('started_at')) is not None
            and bool(run_id) and run.get('run_id') == run_id)


def run_state(market, pat, rel, path, collected_at, run, steps, run_id=None):
    """-> (상태, 사유). written 이번 실행이 썼다 / skipped 단계가 건너뛰었다(옛 판이 그대로 유효 — US 둘째 슬롯) /
    kept 일부러 다시 쓰지 않았다(동결) / failed 단계는 돌았는데 파일이 다시 쓰이지 않았다 / unknown 판정할 수 없다
    (시작 기록·단계 결과가 없다 — 성공으로 추정하지 않는다) / untracked 이 판정의 대상이 아니다."""
    step = STEP_OF[market].get(pat)
    if step is None:
        return 'untracked', None
    if not _own_run(run, run_id):
        return 'unknown', '이번 실행의 시작 기록(--begin, 같은 실행 ID)이 없다'
    started = _parse(run.get('started_at'))
    if pat in MTIME_ONLY:
        written = int(os.path.getmtime(path)) >= int(started.timestamp())
    else:
        t = _parse(collected_at)
        written = t is not None and t >= started
    if written:
        return 'written', None
    info = steps.get(step) if isinstance(steps, dict) else None
    info = info if isinstance(info, dict) else {}
    outcome = info.get('outcome')
    outputs = info.get('outputs') if isinstance(info.get('outputs'), dict) else {}
    if outcome == 'skipped' or outputs.get('skipped') == 'true':
        return 'skipped', None
    # 수익률만 고치는 재실행(us-collect-wait, 2026-11-19): collect 단계는 market_data.json 만 다시 쓴다 — 나머지는
    # 첫 실행의 판이 그대로 유효하다(고치기 자격이 그 판들이 같은 실행의 것임을 확인한다). market_data.json 자체는 예외가 아니다.
    if step == 'collect' and outputs.get('patched') == 'true' and pat != 'market_data.json':
        return 'skipped', None
    if pat in MAY_KEEP:
        if outcome == 'success':
            return 'kept', None
        if outcome is None:
            return 'unknown', f'단계 {step} 의 결과를 모른다'
    noted = (run.get('failures') or {}).get(rel) if isinstance(run.get('failures'), dict) else None
    return 'failed', noted or f'단계 {step} 결과 {outcome or "모름"}, 파일은 다시 쓰이지 않았다'


def _failed_entry(entry, why, carried=None):
    """이번 수집 실패 — 남아 있는 옛 파일의 해시·상태는 `stale_copy` 로 따로 둔다(그 바이트가 「성공」이라 말해도
    이번 실행의 결과가 아니다). 최상위에 sha256 을 두지 않는다."""
    if entry.get('run') == 'failed' and isinstance(entry.get('stale_copy'), dict):
        return entry
    stale = {k: v for k, v in entry.items() if k not in ('present', 'run')}
    # 물려받은 실패는 앞선 실행이 적은 사유를 그대로 둔다(다시 감싸면 실행마다 길어져 잘린다)
    return {'present': True, 'collect_in': entry.get('collect_in'), 'status': 'failed', 'run': 'failed',
            'response': carried or C.clean(f'이번 수집 실행에서 다시 쓰이지 않았다 — {why}'), 'stale_copy': stale}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


from common.jsonfile import load_json_or_none as _json  # noqa: E402 — 공용 JSON 읽기(2026-11-22)


def infer_market(datadir):
    return 'kr' if os.path.exists(os.path.join(datadir, MARKET_FILE['kr'])) else 'us'


def expand(datadir, market, report_date):
    """등록표 → [(상대경로, 생산자)]. glob 은 지금 있는 파일로 펼친다(없으면 아무것도 안 남긴다)."""
    return [(rel, producer) for rel, producer, _pat in _expand(datadir, market, report_date)]


def _expand(datadir, market, report_date):
    """[(상대경로, 생산자, 등록표 패턴)]."""
    out = []
    for key, producer in REGISTRY[market].items():
        pat = key
        if '{D}' in pat:
            if not report_date:
                continue
            pat = pat.replace('{D}', report_date)
        if '*' in pat:
            for p in sorted(glob.glob(os.path.join(datadir, pat))):
                out.append((os.path.relpath(p, datadir).replace(os.sep, '/'), producer, key))
        else:
            out.append((pat, producer, key))
    return out


def _collect_fields(c):
    return {k: c[k] for k in COLLECT_KEYS if isinstance(c, dict) and k in c}


# ── 같은 값의 재수집은 바이트를 바꾸지 않는다(2026-11-20) ─────────────────────────────────────────
# `collect.collected_at` 과 장부의 실행 ID·시각은 실행마다 다르다. 그대로 두면 값이 같은 재수집도 모든 자료 파일을 바꾼다 —
# US 의 건너뛴 실행이 매번 커밋하고, KR 판 관리가 실행마다 사본을 쌓고, KR 발행 기록 뒤의 재수집이 verify 를 깨뜨린다
# (1a 전에는 값이 같으면 바이트도 같았다). 그래서 끝 기록이 ① 앞 판(git HEAD)과 **수집 시각만** 다른 파일을 앞 판
# 바이트로 되돌리고 ② 그 결과 장부에 실질적으로 달라진 것이 없으면 장부도 앞 판 그대로 둔다.
# 「이번 실행이 썼는가」(`run_state`)는 되돌리기 **전**의 수집 시각으로 판정한다 — 되돌려도 실패는 가려지지 않는다.
# 장부가 그대로면 실행 ID·시각은 그 자료를 마지막으로 바꾼 실행의 것이다(자료가 그 실행의 것과 바이트까지 같다).
# git 밖이거나 앞 판에 없는 파일은 건드리지 않는다.

def _head_bytes(datadir, rel):
    """git HEAD 에 있는 그 파일의 바이트 | None(git 밖·HEAD 에 없음·git 실패)."""
    import subprocess
    try:
        top = subprocess.run(['git', '-C', datadir, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
        if top.returncode != 0:
            return None
        path = os.path.relpath(os.path.realpath(os.path.join(datadir, rel)),
                               os.path.realpath(top.stdout.strip())).replace(os.sep, '/')
        if path.startswith('..'):
            return None
        got = subprocess.run(['git', '-C', datadir, 'show', f'HEAD:{path}'], capture_output=True)
    except OSError:
        return None
    return got.stdout if got.returncode == 0 else None


def _sans_time(obj):
    """수집 시각을 뺀 본문 — `collect` 의 나머지 칸(상태·결측·기준일…)은 내용이다."""
    c = obj.get('collect')
    return dict(obj, collect={k: v for k, v in c.items() if k != 'collected_at'}) if isinstance(c, dict) else obj


def _strict(obj):
    """JSON 값의 엄격한 비교용 표현 — 파이썬 `==` 는 `1 == True == 1.0`, `0.0 == -0.0` 이라 다른 자료를 같다고 본다
    (1a 1단계 codex 3회차 D4). 다시 직렬화하면 타입·숫자 표기·키 순서가 갈린다(키 순서도 바이트 차이다)."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=True)


def restore_unchanged(datadir, rel):
    """앞 판(HEAD)과 `collect.collected_at` 만 다른 JSON 객체 파일을 앞 판 바이트로 되돌린다.
    -> 되돌리기 전(이번 실행이 쓴) 수집 시각 | None(`collect` 칸이 없는 파일).

    **바이트로 비교한다**(2026-11-21, codex 구현 3·4회차 D4·E1): 파싱한 값끼리 비교하면 `1`↔`true`·`1e0`↔`1.0`·
    `-0`↔`0`·공백·이스케이프 차이가 합쳐져 새 바이트를 지울 수 있다. 새 바이트에서 이번 수집 시각 문자열(정확히 한 번)을
    앞 판의 수집 시각 문자열로 바꾼 것이 앞 판 바이트와 한 글자도 다르지 않을 때만 되돌린다. 시각 문자열이 한 번이 아니면
    (다른 칸이 같은 시각을 담는 등) 되돌리지 않는다 — 1a 전처럼 바뀐 파일로 남는 쪽이다."""
    path = os.path.join(datadir, rel)
    body = _json(path)
    if not (isinstance(body, dict) and isinstance(body.get('collect'), dict)):
        return None
    fresh = body['collect'].get('collected_at')
    raw = _head_bytes(datadir, rel)
    if raw is None or not isinstance(fresh, str):
        return fresh
    try:
        head = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return fresh
    old_at = head.get('collect', {}).get('collected_at') if isinstance(head, dict) \
        and isinstance(head.get('collect'), dict) else None
    if not isinstance(old_at, str) or old_at == fresh:
        return fresh
    with open(path, 'rb') as fh:
        mine = fh.read()
    f_tok, o_tok = json.dumps(fresh).encode('utf-8'), json.dumps(old_at).encode('utf-8')
    if mine.count(f_tok) == 1 and raw.count(o_tok) == 1 and mine.replace(f_tok, o_tok) == raw:
        tmp = path + '.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(raw)
        os.replace(tmp, path)
    return fresh


def _material(entry):
    """장부 항목에서 실행마다 달라지는 것(수집 시각, 정상 상태들 사이의 차이)을 뺀 것."""
    if not isinstance(entry, dict):
        return entry
    out = {k: v for k, v in entry.items() if k != 'collected_at'}
    if out.get('run') in RUN_OK:
        out['run'] = 'ok'
    return out


def _same_ledger(head, book):
    """앞 판 장부와 실질적으로 같은가 — 시장·세션·파일별 해시·상태가 같고, 앞 판이 제대로 닫힌 장부일 때만."""
    if not (isinstance(head, dict) and isinstance(head.get('files'), dict)):
        return False
    hr = head.get('run') if isinstance(head.get('run'), dict) else {}
    if hr.get('open') is not False or not hr.get('checked') or not head.get('run_id'):
        return False
    if not book['run'].get('checked'):
        return False                      # 이번 실행을 확인하지 못했다 — 그 사실을 장부에 남긴다
    # 칸이 없는 것과 null 은 다르다(codex 4회차 E2)
    if any((k in head, _strict(head.get(k))) != (k in book, _strict(book.get(k))) for k in ('format', 'market', 'report_date')):
        return False
    hf, bf = head['files'], book['files']
    return set(hf) == set(bf) and all(_strict(_material(hf[k])) == _strict(_material(bf[k])) for k in bf)


def stamp(datadir, market=None, now=None, steps=None, run_id=None):
    market = market or infer_market(datadir)
    md = _json(os.path.join(datadir, MARKET_FILE[market])) or {}
    report_date = md.get('report_date')
    prior = C.load_status(datadir)
    # 이번 실행이 쓴 수집 시각을 먼저 읽고(실행 상태 판정용), 수집 시각만 다른 파일을 앞 판 바이트로 되돌린다
    fresh = {rel: restore_unchanged(datadir, rel)
             for rel, producer, _pat in _expand(datadir, market, report_date) if producer is None
             and rel.endswith('.json') and os.path.isfile(os.path.join(datadir, rel))}
    old = prior.get('files') or {}
    run = prior.get('run') if isinstance(prior.get('run'), dict) else {}
    steps = _steps() if steps is None else steps
    run_id = current_run_id(run_id)
    files, states = {}, {}
    rows = _expand(datadir, market, report_date)
    # 생산자(JSON)부터 — 비 JSON 산출물은 생산자의 실행 상태를 따른다
    for rel, producer, pat in sorted(rows, key=lambda r: r[1] is not None):
        path = os.path.join(datadir, rel)
        if not os.path.isfile(path):
            files[rel] = {'present': False}
            continue
        entry = {'present': True, 'sha256': sha256(path), 'bytes': os.path.getsize(path)}
        if producer:
            pc = (_json(os.path.join(datadir, producer)) or {})
            pc = pc.get('collect') if isinstance(pc, dict) else None
            entry.update(_collect_fields(pc))
            entry['collect_in'] = f'producer:{producer}' if pc else 'none'
            state, why, carried = states.get(producer, ('untracked', None, None))
        else:
            if rel.endswith('.json'):
                body = _json(path)
                prev = old.get(rel) or {}
                prev = prev.get('stale_copy') if prev.get('run') == 'failed' and isinstance(
                    prev.get('stale_copy'), dict) else prev
                if isinstance(body, dict) and isinstance(body.get('collect'), dict):
                    entry.update(_collect_fields(body['collect']))
                    entry['collect_in'] = 'file'
                elif prev.get('collect_in') == 'sidecar':
                    entry.update(_collect_fields(prev))
                    entry['collect_in'] = 'sidecar'
                else:
                    entry['collect_in'] = 'none'
            else:
                entry['collect_in'] = 'none'
            state, why = run_state(market, pat, rel, path, fresh.get(rel) or entry.get('collected_at'),
                                   run, steps, run_id)
            carried = None
            if state in ('skipped', 'unknown') and (old.get(rel) or {}).get('run') == 'failed':
                # 앞선 실행의 실패는 건너뛴(또는 판정할 수 없는) 실행이 지우지 못한다 — 그 단계가 다시 돌아야 풀린다.
                # 단계가 성공하고 동결된 파일을 그대로 둔 것(kept)은 그 단계가 다시 돈 것이다 — 파일의 collect 가 다시 말한다
                # (동결 파일은 그날 다시 쓰이지 않으므로, 여기서 실패를 물려주면 재수집으로도 풀 길이 없다).
                state, carried = 'failed', (old[rel].get('response') or '앞선 실행의 수집 실패')
            states[rel] = (state, why, carried)
        entry['run'] = state
        files[rel] = _failed_entry(entry, why, carried) if state == 'failed' else entry
    checked = _own_run(run, run_id)
    book = {'format': C.FORMAT, 'market': market, 'report_date': report_date,
            'stamped_at': C.now_iso(now),
            'run_id': run_id,
            # 닫는다 — 다음 실행이 `--begin` 없이 이 기록을 자기 것으로 읽지 못하게(닫지 못하고 죽어도 실행 ID 가 다르다)
            'run': {'started_at': run.get('started_at') if checked else None, 'open': False, 'checked': checked,
                    'run_id': run_id, 'steps_known': isinstance(steps, dict)},
            'files': files}
    C.write_status(datadir, book)
    raw = _head_bytes(datadir, C.STATUS_FILE if hasattr(C, 'STATUS_FILE') else os.path.basename(C.status_path(datadir)))
    if raw is not None:
        try:
            head = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            head = None
        if _same_ledger(head, book):
            # 달라진 것이 없다 — 장부도 앞 판 그대로(실행 ID·시각은 이 자료를 마지막으로 바꾼 실행의 것)
            path = C.status_path(datadir)
            with open(path + '.tmp', 'wb') as fh:
                fh.write(raw)
            os.replace(path + '.tmp', path)
            return head
    return book


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', required=True)
    ap.add_argument('--market', choices=('us', 'kr'))
    ap.add_argument('--begin', action='store_true',
                    help='잡 시작(수집 앞)에 한 번 — 이번 실행의 시작 시각을 적는다. 끝의 stamp 가 그 뒤에 쓰인 파일만 '
                         '「이번 실행이 썼다」로 본다')
    ap.add_argument('--run-id', help='이번 실행의 ID(없으면 COLLECT_RUN_ID, 그다음 GITHUB_RUN_ID-ATTEMPT). --begin 과 '
                                     '끝의 stamp 가 같은 값을 받아야 한다')
    a = ap.parse_args(argv)
    if a.begin:
        try:
            run = begin(a.datadir, run_id=a.run_id)
        except OSError as e:
            print(f'stamp_collect --begin: 쓰기 실패 — {e}', file=sys.stderr)
            return 1
        print(f"{C.status_path(a.datadir)} — 실행 시작 {run['started_at']} · 실행 ID {run['run_id']}"
              + (' (만든 값 — 끝의 stamp 에 --run-id 로 넘긴다)' if run.get('generated') else ''))
        return 0
    try:
        book = stamp(a.datadir, a.market, run_id=a.run_id)
    except OSError as e:
        print(f'stamp_collect: 쓰기 실패 — {e}', file=sys.stderr)
        return 1
    files = book['files']
    absent = sorted(r for r, e in files.items() if not e.get('present'))
    bare = sorted(r for r, e in files.items() if e.get('present') and e.get('collect_in') == 'none')
    bad = sorted(r for r, e in files.items() if e.get('status') in ('failed', 'partial'))
    print(f"{C.status_path(a.datadir)} — {book['market']} {book['report_date']} · 파일 {len(files)}개"
          + (f" · 없음 {absent}" if absent else '')
          + (f" · 상태 칸 없음 {bare}" if bare else '')
          + (f" · 수집 실패·일부 {bad}" if bad else ''))
    for r in bad:
        print(f"::warning::수집 상태 {files[r]['status']}: {r} — {files[r].get('response')}")
    unknown = sorted(r for r, e in files.items() if e.get('run') == 'unknown')
    if unknown:
        print(f"::warning::이번 실행이 다시 썼는지 판정할 수 없는 파일 {len(unknown)}개 — {unknown[:6]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
