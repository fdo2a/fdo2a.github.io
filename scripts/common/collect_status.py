"""수집 상태 칸(`collect`) — 수집기가 「무엇을 받았고 무엇을 못 받았는지」를 자료 파일 안에 적는다(2026-11-17).

모든 수집기가 이 도우미로 같은 모양을 만든다(명세 「공통 계약 A」):

    "collect": {"status": "ok"|"failed"|"partial", "as_of": "YYYY-MM-DD", "collected_at": "<ISO, KST>",
                "source": "<원천>", "response": "ok"|"<오류 요약 ≤200자>", "required_ok": bool,
                "missing": [...], "empty": "has_data"|"confirmed_none"|"unknown"}

**「수집 성공」과 「대상 없음 확인」은 따로다.** `confirmed_none` 은 조회가 끝까지 성공했고 결과가 0건일
때만 쓴다 — `build()` 가 강제한다: status 가 ok 가 아니면 `empty` 는 `unknown`, failed 면 `required_ok` 는
False. 예외·조기 반환·초기값 경로에서는 수집기가 `failed` 를 적는다.

최상위가 목록인 파일(`kr_top_value.json`·`kr_index_etf.json`)과 JSON 이 아닌 파일에는 칸을 넣을 수 없다 —
`record_sidecar()` 로 `<datadir>/_collect_status.json` 의 `files[<상대경로>]` 에 같은 모양으로 적고,
수집 끝의 `scripts/stamp_collect.py` 가 등록 파일 전부의 `sha256`·`bytes` 를 같은 곳에 더한다.

`response` 에는 비밀값·URL 쿼리를 넣지 않는다(`clean()` — `us/fred.py` 의 `scrub()` 관례).
기존 칸(`report_date`·`ok`·`error`·`status`·`complete`·`missing`·`pending`·`generated`)은 그대로 두고 덧붙인다.
"""
import datetime as _dt
import json
import os
import re

KST = _dt.timezone(_dt.timedelta(hours=9))
STATUS_FILE = '_collect_status.json'
FORMAT = 'collect-status/1'
STATUSES = ('ok', 'failed', 'partial')
EMPTY = ('has_data', 'confirmed_none', 'unknown')
RESPONSE_MAX = 200

_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_QUERY = re.compile(r'\?[^\s\'"<>]*')
_KEYVAL = re.compile(r'(?i)\b(api[_-]?key|apikey|servicekey|key|token|secret|password|auth)=[^&\s\'"]+')
_PATH_KEY = re.compile(r'(/api/[A-Za-z]+/)[^/\s]+')          # ECOS — 키가 URL 경로에 든다(kr/econ.py)
_LONG_TOKEN = re.compile(r'\b[A-Za-z0-9_\-]{32,}\b')        # 경로·본문에 맨몸으로 실린 키 모양
_SECRET_ENV = ('FRED_API_KEY', 'ECOS_API_KEY', 'TYPESAFE_API_KEY', 'NAVER_CLIENT_SECRET',
               'NAVER_CLIENT_ID', 'ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'GH_TOKEN')


def now_iso(now=None):
    return (now or _dt.datetime.now(KST)).astimezone(KST).isoformat(timespec='seconds')


def clean(text, limit=RESPONSE_MAX):
    """오류 문자열 → 한 줄 요약. URL 쿼리·키 모양·환경변수의 비밀값을 지운다."""
    s = ' '.join(str(text if text is not None else '').split())
    for name in _SECRET_ENV:
        v = os.environ.get(name)
        if v and len(v) >= 4:
            s = s.replace(v, '***')
    s = _KEYVAL.sub(lambda m: f'{m.group(1)}=***', s)
    s = _QUERY.sub('?…', s)
    s = _PATH_KEY.sub(r'\1***', s)
    s = _LONG_TOKEN.sub('***', s)
    return s[:limit] if s else 'error'


def build(status, as_of, source, *, response=None, missing=(), empty=None, required_ok=None,
          collected_at=None, **extra):
    """-> collect 객체. 규칙(바꾸지 않는다):

    * status ∈ ok·failed·partial. failed → required_ok False·empty unknown. partial → empty 가
      confirmed_none 이면 unknown 으로 내린다(일부만 읽고 「없음」이라 할 수 없다).
    * required_ok 기본값 = status == ok. 명시해도 failed 는 False.
    * empty 기본값 = unknown(추정하지 않는다).
    * as_of 는 YYYY-MM-DD 이거나 None(모름).
    """
    if status not in STATUSES:
        raise ValueError(f'collect.status {status!r}')
    empty = empty or 'unknown'
    if empty not in EMPTY:
        raise ValueError(f'collect.empty {empty!r}')
    if status != 'ok' and empty == 'confirmed_none':
        empty = 'unknown'
    if status == 'failed':
        empty, required_ok = 'unknown', False
    if required_ok is None:
        required_ok = status == 'ok'
    as_of = str(as_of) if as_of else None
    if as_of is not None and not _DATE.match(as_of):
        raise ValueError(f'collect.as_of {as_of!r}')
    missing = [str(m) for m in (missing or ())]
    if response is None:
        response = 'ok' if status == 'ok' else (
            'missing: ' + ', '.join(missing) if missing else status)
    out = {'status': status, 'as_of': as_of, 'collected_at': collected_at or now_iso(),
           'source': source, 'response': 'ok' if response == 'ok' else clean(response),
           'required_ok': bool(required_ok), 'missing': missing, 'empty': empty}
    for k, v in extra.items():
        if v is not None:
            out[k] = clean(v, 400) if k == 'detail' else v
    return out


def failed(as_of, source, error, **extra):
    """예외·조기 반환 경로의 칸."""
    return build('failed', as_of, source, response=clean(error) or 'failed', **extra)


def by_counts(as_of, source, missing, total, *, empty_when_ok='has_data', **kw):
    """항목 total 개 중 missing 만 못 받았을 때: 0개 못 받음 ok, 전부 못 받음 failed, 나머지 partial."""
    missing = list(missing)
    if total and len(missing) >= total:
        st = 'failed'
    elif missing:
        st = 'partial'
    else:
        st = 'ok'
    return build(st, as_of, source, missing=missing,
                 empty=empty_when_ok if st == 'ok' else ('has_data' if st == 'partial' else None), **kw)


# ── _collect_status.json ─────────────────────────────────────────────────

def status_path(datadir):
    return os.path.join(datadir, STATUS_FILE)


def load_status(datadir):
    try:
        with open(status_path(datadir), encoding='utf-8') as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get('files'), dict):
            return d
    except (OSError, ValueError):
        pass
    return {'format': FORMAT, 'files': {}}


def write_status(datadir, book):
    book['format'] = FORMAT
    book['files'] = dict(sorted((book.get('files') or {}).items()))
    path = status_path(datadir)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def record_sidecar(datadir, rel, collect):
    """칸을 넣을 수 없는 파일(목록형·비 JSON)의 상태를 `_collect_status.json` 에. 해시는 stamp 가 더한다."""
    book = load_status(datadir)
    entry = {k: v for k, v in (book['files'].get(rel) or {}).items() if k in ('sha256', 'bytes')}
    entry.update(collect)
    entry['collect_in'] = 'sidecar'
    book['files'][rel] = entry
    write_status(datadir, book)
    return entry
