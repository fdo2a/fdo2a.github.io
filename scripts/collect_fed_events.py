#!/usr/bin/env python3
"""오늘 연준에서 무슨 자리가 열렸는지 찾아 **원문을 통째로 받아 커밋한다.**

  python scripts/collect_fed_events.py --datadir data

Actions 수집 잡에서 돌고 `data/fed/` 를 남긴다. `fetch_releases.py` 와 같은 갈래이고
같은 이유로 여기 있다 — 루틴 환경은 금융·정부 호스트를 막고, 매일 WAF 와 싸우는
자리를 파이프라인 한복판에 두지 않는다.

**파싱하지 않고 텍스트 덤프만 한다.** 읽고 해석하는 일은 작성 담당 몫이고, 이 스크립트가
책임지는 것은 「의장이 실제로 한 말이 레포 안에 글자 그대로 들어와 있는 것」 하나다.
그게 있어야 발행 게이트가 인용문을 대조할 수 있다.

비-코어다. 어떤 실패도 시장 데이터 수집을 세우지 않고, 못 받은 문서는 못 받았다고
적힌다 — 그 이벤트는 인용 없이 서술되거나 아예 실리지 않는다(삭제 > 창작).

산출:
  data/fed/events.json   오늘 다룰 이벤트와 각 원문의 수집 결과
  data/fed/<key>.txt     원문 전문 (게이트가 인용을 대조하는 대상)
  data/fed/seen.json     이미 본 문서 — 같은 이벤트를 이틀 연속 싣지 않기 위한 것
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import fed_events as fe  # noqa: E402
from us.release_text import to_text  # noqa: E402

IMPERSONATE = ('safari', 'chrome131', 'chrome119', 'safari_ios', 'firefox')
TIMEOUT = 30
# 기자회견 전문은 회의 3주쯤 뒤에 올라온다. 지난 FOMC 몇 회분을 매일 다시 두드려
# 처음 열리는 날 그날의 이벤트로 띄운다 — 그날이 의장의 말을 글자 그대로 읽을 수
# 있게 되는 첫날이기 때문이다.
PRESCONF_LOOKBACK = 6


def load(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return default


def fetch(url):
    """-> (response, note). 실패는 None 과 이유."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return None, 'curl_cffi 미설치'
    last = None
    for imp in IMPERSONATE:
        try:
            r = creq.get(url, impersonate=imp, timeout=TIMEOUT,
                         headers={'Referer': '/'.join(url.split('/')[:3]) + '/'})
        except Exception as e:
            last = f'{imp}: {type(e).__name__}'
            continue
        if r.status_code == 200 and len(r.content or b'') > 3000:
            return r, f'impersonate={imp}'
        # 연준의 404 페이지는 8만 바이트짜리 정상 페이지다 — 크기로는 못 가른다.
        last = f'{imp}: HTTP {r.status_code}, {len(r.content or b"")}B'
    return None, last or 'unknown'


def body(resp, url):
    if url.lower().endswith('.pdf') or 'pdf' in (resp.headers.get('content-type') or ''):
        try:
            import io

            from pypdf import PdfReader
            pages = PdfReader(io.BytesIO(resp.content)).pages
            return to_text('<p>' + '</p><p>'.join(p.extract_text() or '' for p in pages) + '</p>')
        except Exception as e:
            # **실패를 문자열로 돌려주지 않는다.** 예전에는 「[PDF 추출 실패: …]」를
            # 본문으로 돌려줬고, 호출부의 `ok=bool(text)` 가 그것을 성공으로 읽어
            # 그 실패 문구가 인용 대조의 원문이 됐다(2026-09-02 codex 검토).
            print(f'  PDF 추출 실패 {url}: {e}', file=sys.stderr)
            return None
    return fe.flatten(resp.text)


def feed_items(name):
    resp, note = fetch(fe.FEEDS[name])
    if resp is None:
        print(f'  피드 {name}: 실패 ({note})', file=sys.stderr)
        return []
    return fe.parse_feed(resp.text)


def discover(report_date):
    """오늘 다룰 후보 이벤트. 원문은 아직 안 받는다."""
    out = []

    for it in fe.in_window(feed_items('press_monetary'), report_date):
        kind = fe.press_kind(it['title'])
        if not kind:
            continue
        date8 = fe.slug_date(it['link']) or (it['published'] or '').replace('-', '')
        out.append({'kind': kind, 'date8': date8, 'item': it, 'speaker': None, 'role': None})

    for feed in ('speeches', 'testimony'):
        for it in fe.in_window(feed_items(feed), report_date):
            resp, note = fetch(it['link'])
            if resp is None:
                print(f'  연설 {it["title"][:40]}: 페이지 실패 ({note}) — 직함 확인 불가',
                      file=sys.stderr)
                continue
            page = fe.flatten(resp.text)
            hit = fe.speech_kind(it, page, feed=feed)
            if not hit:
                continue        # 의장이 아니면 이 섹션의 자리가 아니다
            kind, role, name = hit
            out.append({'kind': kind, 'date8': fe.slug_date(it['link']),
                        'item': it, 'speaker': name, 'role': role,
                        'prefetched': page})
    return out


def presconf_candidates(statements, seen):
    """전문이 이제야 올라온 지난 회의들.

    이미 본 것은 뺀다. 성명 당일에 전문까지 열린 회의(2026-06-17 실측)는 그날 성명
    이벤트가 전문을 이미 corpus 로 갖고 있으므로, 몇 주 뒤에 같은 문서로 이벤트를
    한 번 더 띄우면 같은 발언이 두 번 실린다.
    """
    return [d for d in statements[-PRESCONF_LOOKBACK:]
            if fe.event_key('presconf', d) not in seen]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--report-date', default=None)
    args = ap.parse_args()

    market = load(os.path.join(args.datadir, 'market_data.json'), {}) or {}
    report_date = args.report_date or market.get('report_date')
    if not report_date:
        print('report_date 를 알 수 없다 — 건너뜀', file=sys.stderr)
        return

    outdir = os.path.join(args.datadir, 'fed')
    os.makedirs(outdir, exist_ok=True)
    seen = load(os.path.join(outdir, 'seen.json'), {}) or {}
    statements = load(os.path.join(outdir, 'statements.json'), []) or []

    candidates = discover(report_date)
    for date8 in presconf_candidates(statements, seen):
        candidates.append({'kind': 'presconf', 'date8': date8,
                           'item': {'title': f'FOMC 기자회견 전문 ({date8})',
                                    'link': fe.presconf_url(date8), 'published': report_date},
                           'speaker': None, 'role': None})

    events, texts = [], {}
    for c in candidates:
        kind, date8, it = c['kind'], c['date8'], c['item']
        if not date8:
            continue
        key = fe.event_key(kind, date8)
        label, tier = fe.KINDS.get(kind, (kind, 2))
        first_seen = seen.get(key)
        sources = []
        for src in fe.sources_for(kind, date8, it['link']):
            text = c.get('prefetched') if src['role'] == 'primary' else None
            note = 'prefetched'
            if text is None:
                resp, note = fetch(src['url'])
                text = body(resp, src['url']) if resp is not None else None
            sources.append(dict(src, ok=bool(text), note=note,
                                chars=len(text or ''), text=text))
        got = [s for s in sources if s['ok']]
        if not got and first_seen is None and kind == 'presconf':
            continue            # 아직 안 올라온 전문은 이벤트가 아니다

        # **원문을 하나도 못 받았으면 「봤다」고 기록하지 않는다.** 예전에는 즉시
        # 기록했고, 그래서 수집이 실패한 첫날 이벤트가 소진돼 **정작 원문을 확보한
        # 다음 날에는 섹션이 열리지 않았다**(2026-09-02 codex 검토). 내일 다시
        # 시도하게 두고, 창이 닫힐 때까지 못 받으면 싣지 않는다 — 인용 없는 연준
        # 섹션을 내는 것보다 매크로 섹션이 정책 경로를 잇게 두는 편이 낫다.
        if first_seen is None:
            if not got:
                print(f'  {key}: 원문을 하나도 못 받았다 — 내일 다시 시도한다',
                      file=sys.stderr)
                events.append({
                    'key': key, 'kind': kind, 'kind_ko': label, 'tier': tier,
                    'date': f'{date8[:4]}-{date8[4:6]}-{date8[6:]}',
                    'title': it.get('title'), 'url': it.get('link'),
                    'speaker': c.get('speaker'), 'role': c.get('role'),
                    'first_seen': None, 'fresh': False,
                    'sources': [{k: v for k, v in s.items() if k != 'text'}
                                for s in sources],
                })
                continue
            first_seen = report_date
            seen[key] = report_date
        if kind == 'fomc_statement':
            if date8 not in statements:
                statements.append(date8)
                statements.sort()
            # 성명 당일에 전문까지 열렸으면 그 문서는 여기서 이미 다뤄졌다.
            if any(s['role'] == 'presconf' and s['ok'] for s in sources):
                seen.setdefault(fe.event_key('presconf', date8), first_seen)

        texts[key] = '\n\n'.join(
            f'# {s["label"]}\n# 원문: {s["url"]}\n\n{s["text"]}' for s in got)
        events.append({
            'key': key, 'kind': kind, 'kind_ko': label, 'tier': tier,
            'date': f'{date8[:4]}-{date8[4:6]}-{date8[6:]}' if date8 else None,
            'title': it.get('title'), 'url': it.get('link'),
            'speaker': c.get('speaker'), 'role': c.get('role'),
            'first_seen': first_seen,
            # 하루만 신선하다. 놓친 이벤트를 이틀 뒤에 오늘 일처럼 싣지 않는다 —
            # 그러느니 매크로 섹션의 정책 경로가 그 판단을 이어받는 편이 낫다.
            'fresh': first_seen == report_date,
            'sources': [{k: v for k, v in s.items() if k != 'text'} for s in sources],
        })

    diff = None
    fresh_stmt = next((e for e in events
                       if e['kind'] == 'fomc_statement' and e['fresh']), None)
    if fresh_stmt:
        prev8 = next((d for d in reversed(statements)
                      if d < fresh_stmt['key'].rsplit('-', 1)[1]), None)
        prev_path = os.path.join(outdir, fe.event_key('fomc_statement', prev8) + '.txt') \
            if prev8 else None
        if prev_path and os.path.exists(prev_path):
            with open(prev_path, encoding='utf-8') as fh:
                diff = fe.redline(fh.read(), texts.get(fresh_stmt['key'], ''))
            if diff is not None:
                diff['previous'] = f'{prev8[:4]}-{prev8[4:6]}-{prev8[6:]}'

    for key, text in texts.items():
        with open(os.path.join(outdir, f'{key}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(text)

    book = {'report_date': report_date, 'events': events, 'diff': diff}
    with open(os.path.join(outdir, 'events.json'), 'w', encoding='utf-8') as fh:
        json.dump(book, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(outdir, 'seen.json'), 'w', encoding='utf-8') as fh:
        json.dump(seen, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(outdir, 'statements.json'), 'w', encoding='utf-8') as fh:
        json.dump(statements, fh, indent=2)

    fresh = [e for e in events if e['fresh']]
    if not fresh:
        print('오늘 새로 나온 연준 이벤트 없음 — 섹션 없이 발행한다')
    for e in fresh:
        got = sum(1 for s in e['sources'] if s['ok'])
        print(f'  {e["key"]}: {e["kind_ko"]} · 원문 {got}/{len(e["sources"])}건 · '
              f'{sum(s["chars"] for s in e["sources"]):,}자')
    if diff:
        print(f'  성명 변경점: 고쳐 쓴 문장 {len(diff["changed"])} · '
              f'추가 {len(diff["added"])} · 삭제 {len(diff["removed"])} '
              f'(직전 {diff.get("previous")})')


if __name__ == '__main__':
    main()
