"""한국은행·일본은행 수집기 공용 — 받기·PDF 글·산출 파일 쓰기 (2026-11-27).

`collect_bok_events.py`·`collect_boj_events.py` 가 쓴다. 산출 모양은 미국 `data/fed/` 와 같다:
  events.json   그날 실행이 본 이벤트와 각 원문의 수집 결과(원문 글은 담지 않는다)
  <key>.txt     원문 전문 — 게이트가 인용을 대조하는 대상
  seen.json     KEY → 처음 받은 날(기록용 — 칸을 열 의무는 발행본 장부와 일정 파일이 정한다)
  statements.json  결정문·공표문 KEY 목록(직전 결정문을 찾는 데 쓴다)

비-코어다. 어떤 실패도 시장 데이터 수집을 세우지 않고, 못 받은 문서는 못 받았다고 적힌다.
"""
import io
import json
import os
import sys

from common import cb_events as CE
from common import collect_status as C

IMPERSONATE = ('chrome131', 'safari', 'chrome119', 'firefox')
TIMEOUT = 30


def fetch(url, min_bytes=500):
    """-> (응답 바이트 | None, 메모). curl_cffi 가 없으면 urllib 로 한 번."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        creq = None
    last = None
    if creq is not None:
        for imp in IMPERSONATE:
            try:
                r = creq.get(url, impersonate=imp, timeout=TIMEOUT, allow_redirects=True)
            except Exception as e:  # noqa: BLE001
                last = f'{imp}: {type(e).__name__}'
                continue
            if r.status_code == 200 and len(r.content or b'') >= min_bytes:
                return r.content, f'impersonate={imp}'
            last = f'{imp}: HTTP {r.status_code}, {len(r.content or b"")}B'
        return None, last or 'unknown'
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
        if len(body) >= min_bytes:
            return body, 'urllib'
        return None, f'urllib: {len(body)}B'
    except Exception as e:  # noqa: BLE001
        return None, f'urllib: {type(e).__name__}'


def text_of(content, encoding='utf-8'):
    return (content or b'').decode(encoding, errors='replace')


def pdf_text(content):
    """PDF 바이트 → 글(쪽 사이 줄바꿈). 실패하면 None — 실패 문구를 본문으로 돌려주지 않는다."""
    if not content or not content.startswith(b'%PDF'):
        return None
    try:
        from pypdf import PdfReader
        pages = PdfReader(io.BytesIO(content)).pages
        text = '\n'.join(p.extract_text() or '' for p in pages).strip()
    except Exception as e:  # noqa: BLE001
        print(f'  PDF 추출 실패: {type(e).__name__}: {e}', file=sys.stderr)
        return None
    return text or None


def load(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def source(role, label, url, text, note):
    return {'role': role, 'label': label, 'url': url, 'ok': bool(text), 'note': note, 'chars': len(text or ''),
            'text': text}


def event_row(kind, meeting_date, date, title, url, sources, seen, report_date, tier=1):
    key = CE.event_key(kind, meeting_date)
    got = any(s['ok'] for s in sources)
    if got and key not in seen:
        seen[key] = report_date
    return {'key': key, 'kind': kind, 'kind_ko': CE.label(kind), 'tier': tier, 'date': date,
            'meeting_date': meeting_date, 'title': title, 'url': url, 'first_seen': seen.get(key),
            'sources': sources}


def corpus_text(row):
    return '\n\n'.join(f'# {s["label"]}\n# 원문: {s["url"]}\n\n{s["text"]}' for s in row['sources'] if s['ok'])


def write_all(outdir, report_date, rows, extra_texts, seen, statements, diff, failed, source_name, outlook_diff=None):
    """산출 파일을 쓴다. `rows` 의 원문은 `<key>.txt` 로, events.json 에는 원문을 뺀 행만."""
    os.makedirs(outdir, exist_ok=True)
    for row in rows:
        if any(s['ok'] for s in row['sources']):
            with open(os.path.join(outdir, f'{row["key"]}.txt'), 'w', encoding='utf-8') as fh:
                fh.write(corpus_text(row))
    for key, text in (extra_texts or {}).items():
        with open(os.path.join(outdir, f'{key}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(text)
    events = [dict(r, sources=[{k: v for k, v in s.items() if k != 'text'} for s in r['sources']]) for r in rows]
    has = any(any(s['ok'] for s in r['sources']) for r in rows)
    if failed and not has and not rows:
        collect = C.failed(report_date, source_name, '; '.join(failed)[:180], missing=list(failed))
    else:
        collect = C.build('partial' if failed else 'ok', report_date, source_name, missing=list(failed),
                          empty='has_data' if has else 'confirmed_none')
    book = {'report_date': report_date, 'events': events, 'diff': diff, 'collect': collect}
    if outlook_diff is not None:
        book['outlook_diff'] = outlook_diff
    with open(os.path.join(outdir, 'events.json'), 'w', encoding='utf-8') as fh:
        json.dump(book, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    with open(os.path.join(outdir, 'seen.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(seen.items())), fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    with open(os.path.join(outdir, 'statements.json'), 'w', encoding='utf-8') as fh:
        json.dump(sorted(set(statements)), fh, indent=2)
        fh.write('\n')
    return book


def report(book):
    for e in book['events']:
        got = sum(1 for s in e['sources'] if s['ok'])
        print(f'  {e["key"]}: {e["kind_ko"]} · {e["date"]} · 원문 {got}/{len(e["sources"])}건 · '
              f'{sum(s["chars"] for s in e["sources"]):,}자')
    if not book['events']:
        print('  창 안에 새 문서 없음')
    if book.get('diff'):
        print(f'  결정문 변경점: 바뀐 곳 {len(book["diff"]["changed"])} (직전 {book["diff"].get("previous")})')
    print(f'  수집 상태: {book["collect"]["status"]}' + (f' — 못 받은 것 {", ".join(book["collect"]["missing"])}'
                                                   if book['collect'].get('missing') else ''))
