#!/usr/bin/env python3
"""moomoo 보조 입력 수집 — **로컬 전용**. GitHub Actions 에서 돌지 않는다.

OpenD 는 로그인된 macOS GUI 세션을 요구하고, CI 러너는 매 실행마다 새 기기라
기기잠금 인증이 반복된다. 증권계좌 자격증명을 CI 시크릿에 넣지 않는다.

  python3 scripts/collect_moomoo_forward.py --datadir data
  python3 scripts/collect_moomoo_forward.py --datadir data --offline   # 공식 일정만
  python3 scripts/collect_moomoo_forward.py --datadir data --dry-run

**정본을 건드리지 않는다.** `market_data.json` 의 가격·금리는 이 스크립트의
소관이 아니다. 여기서 만드는 것은 「앞을 보는」 보조 재료뿐이다.

책임 분리: 연결·인증·타임아웃·호출제한·페이지 넘김은 여기, 응답 검사와
정규화는 `scripts/us/moomoo_forward.py`, 공식 FOMC 파싱은
`scripts/us/fomc_official.py`. SDK 가 없는 환경에서도 그 두 모듈은 import 된다.

When changing this: read `docs/superpowers/specs/2026-09-22-moomoo-forward-design.md`
before touching this file, `scripts/us/moomoo_forward.py`, or `fomc_official.py`.
"""

import argparse
import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.request
import uuid
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import fomc_official as FO  # noqa: E402
from us import moomoo_forward as M  # noqa: E402

KST = ZoneInfo('Asia/Seoul')
HOST = os.environ.get('MOOMOO_OPEND_HOST', '127.0.0.1')
PORT = int(os.environ.get('MOOMOO_OPEND_PORT', '11111'))

# 호출제한은 엔드포인트마다 다르다(실측에서 경제 캘린더가 30초당 60회에 걸렸다).
# 확정된 표가 없으므로 보수적으로 띄운다 — 여기서 아끼는 1초가 하루치 입력을
# 통째로 날릴 이유가 없다.
CALL_GAP_SEC = 1.2

PROVIDER = 'moomoo'
FEDWATCH_PROVIDER = 'moomoo/CME FedWatch'

# 보조 항목이 다루는 종목. 메모리·AI 인프라 섹션이 이미 쓰는 목록과 같다 —
# 한 종목이 두 자리에서 다르게 불리면 독자가 같은 회사를 둘로 읽는다.
WATCH = ('US.MU', 'US.WDC', 'US.STX', 'US.NVDA',
         'US.MRVL', 'US.COHR', 'US.LITE', 'US.GEV', 'US.VRT')


def now_kst():
    return dt.datetime.now(tz=KST)


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_official_fomc(timeout=30):
    req = urllib.request.Request(FO.URL, headers={'User-Agent': 'fdo2a-report/1.0'})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        return r.read().decode('utf-8', 'replace')


class Quote:
    """OpenD 연결 한 개. 실패는 예외가 아니라 사유로 돌려준다."""

    def __init__(self, offline=False):
        self.ctx = None
        self.error = 'offline' if offline else None
        self.offline = offline

    def __enter__(self):
        if self.offline:
            return self
        try:
            from moomoo import OpenQuoteContext
        except Exception as exc:                      # SDK 미설치
            self.error = f'sdk-missing: {exc}'
            return self
        try:
            self.ctx = OpenQuoteContext(host=HOST, port=PORT)
        except Exception as exc:                      # OpenD 미기동·인증 실패
            self.error = f'opend-unreachable: {exc}'
        return self

    def __exit__(self, *exc):
        if self.ctx is not None:
            try:
                self.ctx.close()
            except Exception:
                pass
        return False

    def call(self, name, *args, **kwargs):
        """(rows, error). 성공하면 error 는 None.

        `ret` 이 0 이 아니면 **그 사유를 그대로 들고 온다** — 권한 부족과
        일시적 호출제한은 다른 상태이고, 스키마 오류를 「오늘 이벤트 없음」으로
        바꾸지 않는다.
        """
        if self.ctx is None:
            return [], self.error or 'no-context'
        fn = getattr(self.ctx, name, None)
        if fn is None:
            return [], f'sdk-no-method: {name}'
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            return [], f'call-failed: {exc}'
        finally:
            time.sleep(CALL_GAP_SEC)
        if not isinstance(result, tuple) or len(result) < 2:
            return [], f'unexpected-shape: len={_safe_len(result)}'
        ret, payload = result[0], result[1]
        if ret != 0:
            return [], f'ret={ret}: {payload}'
        try:
            return _records(payload), None
        except Exception as exc:
            return [], f'schema: {exc}'


    def call_paged(self, name, *args, **kwargs):
        """(rows, error, has_more). 페이지가 남았는지까지 알려준다.

        한 페이지만 받고 `ok` 로 적으면, 조회 범위 안에 있으나 받지 못한 지표가
        「그날 발표가 없었다」와 구별되지 않는다.
        """
        if self.ctx is None:
            return [], self.error or 'no-context', False
        fn = getattr(self.ctx, name, None)
        if fn is None:
            return [], f'sdk-no-method: {name}', False
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            return [], f'call-failed: {exc}', False
        finally:
            time.sleep(CALL_GAP_SEC)
        if not isinstance(result, tuple) or len(result) < 2:
            return [], f'unexpected-shape: len={_safe_len(result)}', False
        if result[0] != 0:
            return [], f'ret={result[0]}: {result[1]}', False
        more = False
        if len(result) > 3:
            more = bool(result[3])
        elif len(result) > 2:
            more = bool(result[2] and str(result[2]) not in ('-1', 'None', ''))
        try:
            return _records(result[1]), None, more
        except Exception as exc:
            return [], f'schema: {exc}', more


class SchemaError(ValueError):
    """응답이 예상한 모양이 아니다. **정상 0건으로 바꾸지 않는다.**"""


def _records(payload):
    """DataFrame / (count, DataFrame) / list / dict → list[dict].

    모르는 모양은 `SchemaError` 다. 빈 리스트로 돌려주면 파싱 실패가 「그날
    발표가 없었다」와 구별되지 않는다(codex 구현 검토 P2-8).
    """
    if isinstance(payload, tuple) and len(payload) == 2:
        payload = payload[1]
    if payload is None:
        return []
    if isinstance(payload, list):
        bad = [r for r in payload if not isinstance(r, dict)]
        if bad:
            raise SchemaError(f'non-dict row: {type(bad[0]).__name__}')
        return payload
    if isinstance(payload, dict):
        for key in ('item_list', 'event_list', 'rows', 'stock_list', 'alert_list'):
            if key in payload:
                return _records(payload[key])
        return [payload]
    to_dict = getattr(payload, 'to_dict', None)
    if to_dict is not None:
        return to_dict(orient='records')
    raise SchemaError(f'unexpected payload: {type(payload).__name__}')


def _safe_len(value):
    try:
        return len(value)
    except TypeError:
        return 'n/a'


def _status_for(rows, error, query_range=None):
    if error:
        low = error.lower()
        if 'permission' in low:
            return 'unavailable'
        if 'frequency' in low or 'limit' in low:
            return 'partial'
        if 'schema' in low or 'unexpected-shape' in low:
            return 'invalid'
        if ('sdk-missing' in low or 'unreachable' in low
                or 'offline' in low or 'no-context' in low):
            return 'unavailable'
        return 'invalid'
    if rows:
        return 'ok'
    return 'empty' if query_range else 'unavailable'


def collect(datadir, *, offline=False, session=None, run_id=None, verified_at=None):
    """여섯 묶음을 모은다. 한 항목의 실패가 나머지를 버리지 않는다."""
    fetched_at = now_kst().isoformat(timespec='seconds')
    run_id = run_id or uuid.uuid4().hex[:12]
    verified_at = verified_at or now_kst().date().isoformat()
    today = now_kst().date()
    out = {}
    notes = {}

    # --- 공식 FOMC 일정(정본) + moomoo 대조 --------------------------------
    official = None
    try:
        official = FO.book(fetch_official_fomc(), verified_at=verified_at)
        if not official['meetings']:
            official = None
            notes['fomc_official'] = 'parsed-empty'
    except Exception as exc:
        notes['fomc_official'] = f'fetch-failed: {exc}'

    with Quote(offline=offline) as q:

        fw_rows, fw_err = ([], 'offline') if offline else q.call('get_fed_watch_target_rate')
        dot_rows, dot_err = ([], 'offline') if offline else q.call('get_fed_watch_dot_plot')

        moomoo_dates = sorted({str(r.get('meeting_date')) for r in fw_rows
                               if r.get('meeting_date')})
        book = M.fomc_book(official=official, moomoo_dates=moomoo_dates,
                           checked_at=verified_at, report_date=session)
        out['fomc_dates'] = book

        fedwatch, fw_status = [], _status_for(fw_rows, fw_err)
        if fw_rows:
            try:
                fedwatch = M.normalize_fedwatch(
                    fw_rows, observed_at=fetched_at, provider=FEDWATCH_PROVIDER)
            except M.InvalidProbability as exc:
                fw_status, fw_err = 'invalid', str(exc)
        out['fedwatch'] = M.envelope(
            'fedwatch', rows=fedwatch, status=fw_status if fedwatch else
            ('invalid' if fw_status == 'ok' else fw_status),
            fetched_at=fetched_at, session=_iso(session),
            provider=FEDWATCH_PROVIDER, note=fw_err,
            missing=() if fedwatch else ('fedwatch',))

        out['dot_plot'] = M.envelope(
            'dot_plot', rows=dot_rows, status=_status_for(dot_rows, dot_err),
            fetched_at=fetched_at, session=_iso(session), provider=PROVIDER,
            note=dot_err, missing=() if dot_rows else ('dot_plot',))

        # --- 경제지표 컨센서스 ---------------------------------------------
        begin, end = today.isoformat(), (today + dt.timedelta(days=10)).isoformat()
        rng = {'begin': begin, 'end': end, 'market': 'US'}
        rows, err, more = ([], 'offline', False) if offline else q.call_paged(
            'get_economic_calendar', begin_date=begin, end_date=end,
            market_list=['US'], count=100)
        mapped = M.normalize_consensus(rows, observed_at=fetched_at) if rows else []
        status = _status_for(mapped, err, query_range=rng)
        if more and status in ('ok', 'empty'):
            # 다음 페이지가 남았으면 「범위 안에 발표가 없었다」가 아니다.
            # 첫 페이지가 전부 허용목록 밖이어도 마찬가지다(codex P2-9).
            status = 'partial'
        out['econ_consensus'] = M.envelope(
            'econ_consensus', rows=mapped, status=status,
            fetched_at=fetched_at, session=_iso(session), query_range=rng,
            provider=PROVIDER, note=err,
            missing=() if mapped else ('econ_consensus',))

        # --- 아래 넷은 수집만 한다. 본문 자동 사용은 계약이 정해질 때까지 보류.
        # 실적 캘린더는 **조회 구간 상한이 7일**이다(실측: ret=-1 "Date range
        # must not exceed 7 days"). 10일 창을 그대로 넘기면 매일 빈다.
        e_end = (today + dt.timedelta(days=6)).isoformat()   # 상한 7일은 양끝 포함
        e_rng = {'begin': begin, 'end': e_end, 'market': 'US'}
        out['earnings'] = _simple(q, 'earnings', 'get_earnings_calendar',
                                  fetched_at, session, offline,
                                  kwargs={'market': 'US', 'begin_date': begin,
                                          'end_date': e_end},
                                  query_range=e_rng)
        out['ratings'] = _simple(q, 'ratings', 'get_rating_change',
                                 fetched_at, session, offline,
                                 kwargs={'market': 'US', 'count': 20},
                                 query_range={'market': 'US', 'count': 20})
        out['session_rank'] = _simple(q, 'session_rank', 'get_us_after_hours_rank',
                                      fetched_at, session, offline,
                                      kwargs={'count': 20},
                                      query_range={'market': 'US', 'count': 20})

        si_rows, si_fail = [], {}
        if offline:
            si_fail = {c: 'offline' for c in WATCH}
        else:
            for code in WATCH:
                rows, err = q.call('get_short_interest', code, num=2)
                if err:
                    si_fail[code] = err
                    continue
                for r in rows:
                    r['code'] = code
                si_rows.extend(rows)
        si_err = '; '.join(f'{k}: {v}' for k, v in si_fail.items()) or None
        si_range = {'codes': list(WATCH), 'failed': sorted(si_fail)}
        if si_rows and si_fail:
            si_status = 'partial'      # 일부 종목만 실패한 것을 전량 실패로 적지 않는다
        else:
            si_status = _status_for(si_rows, si_err, query_range=si_range)
        out['short_interest'] = M.envelope(
            'short_interest', rows=si_rows, status=si_status,
            fetched_at=fetched_at, session=_iso(session),
            query_range=si_range, provider=PROVIDER,
            source_as_of=_max_field(si_rows, 'timestamp_str'),
            note=si_err,
            missing=sorted(si_fail) if si_fail else ())

    for value in out.values():
        if isinstance(value, dict):
            value['run_id'] = run_id

    manifest = {
        'run_id': run_id, 'fetched_at': fetched_at,
        'session': _iso(session), 'opend': f'{HOST}:{PORT}',
        'offline': bool(offline), 'notes': notes,
        'files': {k: out[k].get('status', 'n/a') if isinstance(out[k], dict) and
                  'status' in out[k] else 'book' for k in out},
    }
    return out, manifest


def _simple(q, kind, method, fetched_at, session, offline, *, kwargs, query_range):
    rows, err = ([], 'offline') if offline else q.call(method, **kwargs)
    return M.envelope(kind, rows=rows,
                      status=_status_for(rows, err, query_range=query_range),
                      fetched_at=fetched_at, session=_iso(session),
                      query_range=query_range, provider=PROVIDER, note=err,
                      missing=() if rows else (kind,))


def _iso(day):
    return day.isoformat() if isinstance(day, dt.date) else day


def _max_field(rows, field):
    vals = [str(r.get(field)) for r in rows if r.get(field)]
    return max(vals) if vals else None


def write(datadir, out, manifest, *, dry_run=False):
    """원자적으로 쓴다. 회차가 섞이지 않도록 manifest 를 **마지막에** 놓는다."""
    moodir = os.path.join(datadir, 'moomoo')
    targets = [(os.path.join(datadir, 'fomc_dates.json'), out['fomc_dates'])]
    for key, value in out.items():
        if key == 'fomc_dates':
            continue
        targets.append((os.path.join(moodir, f'{key}.json'), value))

    if dry_run:
        for path, _ in targets:
            print(f'  would write {path}')
        return

    os.makedirs(moodir, exist_ok=True)
    for path, value in targets:
        _atomic(path, value)
    _atomic(os.path.join(moodir, 'manifest.json'), manifest)


def _atomic(path, value):
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')
    os.replace(tmp, path)


def _load_holidays(datadir):
    """`data/us_market_holidays.json` 의 `["YYYY-MM-DD", ...]`. 없으면 빈 목록.

    여기서 달력을 만들지 않는다 — 없는 휴장을 지어내는 것보다 건너뛰지 않는
    편이 낫고, 그 사실은 세션 대조에서 드러난다.
    """
    path = os.path.join(datadir, 'us_market_holidays.json')
    try:
        with open(path, encoding='utf-8') as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return ()
    except Exception as exc:
        print(f'WARN: {path} 를 읽지 못했다 ({exc}) — 휴장 건너뛰기 없이 진행', file=sys.stderr)
        return ()
    days = raw.get('holidays') if isinstance(raw, dict) else raw
    return tuple(d for d in (days or ()) if isinstance(d, str))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--offline', action='store_true',
                    help='OpenD 를 부르지 않는다 — 공식 FOMC 일정만 갱신')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--date', help='KST 실행일 override (YYYY-MM-DD)')
    ap.add_argument('--allow-backfill', action='store_true',
                    help='과거 세션으로 저장 — 현재 응답을 과거 보고서용으로 '
                         '포장하게 되므로 기본은 막는다')
    args = ap.parse_args()

    kst_day = (dt.date.fromisoformat(args.date) if args.date
               else now_kst().date())
    # 휴장을 건너뛰지 않으면 휴장 다음 실행이 정본 report_date 와 어긋나고,
    # 그러면 원천 대조가 통째로 생략된다(codex 구현 검토 P2-12).
    holidays = _load_holidays(args.datadir)
    session = M.target_session(kst_day, holidays=holidays)
    if session is None:
        print(f'{kst_day} (KST) 는 발행일이 아니다 — 대상 세션 없음. 종료.')
        return 0

    if session < now_kst().date() - dt.timedelta(days=1) and not args.allow_backfill:
        print(f'대상 세션 {session} 이 오늘 응답보다 과거다 — 소급 포장을 막는다. '
              f'정말 필요하면 --allow-backfill', file=sys.stderr)
        return 2

    out, manifest = collect(args.datadir, offline=args.offline, session=session)
    write(args.datadir, out, manifest, dry_run=args.dry_run)

    book = out['fomc_dates']
    print(f"run {manifest['run_id']} | 대상 세션 {session}")
    print(f"  FOMC: {len(book['meetings'])}회 "
          f"(대조 {book['cross_check']['agrees']}) missing={book['missing']}")
    for key in ('fedwatch', 'dot_plot', 'econ_consensus', 'earnings',
                'ratings', 'short_interest', 'session_rank'):
        env = out[key]
        print(f"  {key}: {env['status']} rows={len(env['rows'])}"
              + (f" note={env['note']}" if env.get('note') else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
