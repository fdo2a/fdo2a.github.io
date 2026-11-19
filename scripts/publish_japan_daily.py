#!/usr/bin/env python3
"""일본 일간 발행 단계 — **완료된 검증에만 묶인다**(2026-10-27, 실행 격리 2026-11-19 설계 20판 §6-5~§6-7-1).

    python3 scripts/publish_japan_daily.py --run-dir $D --run-id $RUN_ID
    python3 scripts/publish_japan_daily.py check-staged --run-dir $D      # git add 뒤, commit 전
    python3 scripts/publish_japan_daily.py verify-head --run-dir $D       # push 직전마다(첫 push·rebase 뒤)

발행(아무것도 쓰기 전에 전부 본다 — 어긋나면 exit 4, 아무것도 쓰지 않는다):
- `D/gates.json` 이 있고 `verdict == 'pass'`, 그 `run_id == --run-id == 폴더 이름`, 세션이 폴더 이름의 세션.
- `D/jpd_<S>.html`·`D/root` 의 후보·뉴스·견해 바이트 해시가 기록과 같다(`null` ↔ 파일 없음).
  견해는 `telegram_sha256` 이 있을 때만 그 바이트를 고정한다 — `null` 인 날은 고정 파일을 만들지 않는다.
- 조립본의 `<title>`·meta description 이 기록의 `title`·`summary` 와 같다. **제목·요약 인자는 없다** —
  `japan/daily.json` 항목은 이 값에서만 만든다.
- exit 2 = 발행할 수 없는 상태(이미 발행됨, 후보가 `schema: 2` 가 아님·`complete` 거짓·세션 불일치).

통과하면 확인한 그 바이트를 옮긴다: 글(`D` 의 조립본), 발행 스냅샷(`D/root` 후보 + `published`), 발행 기록
`japan/data/daily/runs/<S>.json`(= gates.json + `published_at`), 견해 고정 파일, 이력, 목록, sitemap.
쓰는 순서: ① `D/publish.json` — **쓰기 전에** 바꿀 경로와 그 바이트의 해시(`written`)·목록 항목·이력 행을 남긴다
② 경로마다 임시 파일(`D` 안) → `os.replace` 로 통째로 바꾼다 ③ `D/manifest.txt`(실제로 바뀐 경로) = 완료 표식.
어디서 죽어도 산출물 경로는 origin 판이거나 `written` 의 바이트라 다음 실행의 시작 가드가 되돌린다. ③ 이 없으면
`check-staged`·`verify-head` 는 4 다. 실행 폴더는 저장소와 같은 장치여야 한다(아니면 4, 아무것도 쓰지 않는다).
커밋은 하지 않는다.

`check-staged`: `git diff --cached --name-only` 가 manifest 와 정확히 같아야 0, 아니면 4.
`verify-head`: **HEAD 커밋에서** 꺼낸 글·발행 스냅샷·발행 기록·견해 고정 파일·이 세션 뉴스 파일·목록 항목·이력 행·
sitemap 을 기록과 견준다. 목록·이력·sitemap 은 **부모 커밋의 판에 이 세션 변경만 더한 바이트**와 같아야 한다
(다른 세션 항목을 지우거나 주석으로 감싼 판은 거부 — `expected_shared`, 시작 가드도 같은 함수로 되돌릴 판을 가린다). HEAD 가 `origin/main` 위 커밋 하나(`Add JP daily [<S>]`)이고 그 변경 경로가 manifest 와 같아야
한다. 하나라도 다르면 4 — push 하지 않는다.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.archives import merge_sitemap, upsert_entry  # noqa: E402

BASE = 'https://fdo2a.github.io'
DAILY = os.path.join('japan', 'data', 'daily')
HISTORY = 'japan/data/history/jp_daily.jsonl'
LISTING = 'japan/daily.json'
SITEMAP = 'sitemap.xml'


class AlreadyPublished(Exception):
    pass


class Mismatch(Exception):
    """검증 기록과 다르다 — exit 4."""


def paths(session):
    return {'post': f'japan/daily/{session}.html', 'snapshot': f'japan/data/daily/{session}.json',
            'runs': f'japan/data/daily/runs/{session}.json', 'pin': f'japan/data/telegram/published/{session}.json',
            'candidate': f'japan/data/daily/candidate/{session}.json', 'news': f'japan/data/news/daily/{session}.json',
            'telegram': f'japan/data/telegram/{session}.json'}


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def _read(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _json_bytes(obj, indent=1):
    return (json.dumps(obj, ensure_ascii=False, indent=indent) + '\n').encode('utf-8')


def history_row(snap):
    prices = {}
    if snap.get('schema') != 2:            # 옛 스냅샷만 ETF·업종 ETF 를 가졌다 — 2판은 지수 이력과 잇지 않는다
        etf = (snap.get('indices') or {}).get('topix_etf') or {}
        if etf.get('ok') and etf.get('value') is not None:
            prices['1306'] = etf['value']
        rows = (snap.get('sectors') or []) + (snap.get('stocks') or [])
    else:
        rows = snap.get('stocks') or []
    for row in rows:
        if row.get('value') is not None and row.get('ok', True):
            prices[row['code']] = row['value']
    return {'session': snap['session'], 'nikkei': snap['indices']['nikkei']['value'],
            'prices': dict(sorted(prices.items()))}


def _history_bytes(existing, row):
    rows = [json.loads(line) for line in (existing or b'').decode('utf-8').splitlines() if line.strip()]
    rows = [r for r in rows if r.get('session') != row['session']] + [row]
    rows.sort(key=lambda r: r['session'])
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode('utf-8')


def listing_entry(gates):
    return {'date': gates['session'], 'title': gates['title'], 'headline': gates['summary']}


_LASTMOD = re.compile(r'<url><loc>([^<]*)</loc><lastmod>(\d{4}-\d{2}-\d{2})</lastmod></url>')


def expected_shared(rel, base, session, entry, row, candidate=None):
    """공유 파일 `rel` 의 부모 판(`base` 바이트|None)에 이 세션의 변경만 적용한 바이트, 공유 파일이 아니면 None.
    sitemap 의 lastmod 는 `candidate` 에 적힌 이 세션 URL 의 날짜를 쓴다(발행일·rebase 복구일이 다를 수 있다).
    verify-head 와 시작 가드가 함께 쓴다 — 다른 세션의 항목·행·URL 을 지우거나 감싼 판은 이 값과 다르다."""
    if rel == LISTING:
        entries = json.loads(base.decode('utf-8')) if base else []
        return _json_bytes(upsert_entry(entries, entry, key='date'), indent=2)
    if rel == HISTORY:
        return _history_bytes(base, row)
    if rel == SITEMAP:
        url = f'{BASE}/japan/daily/{session}.html'
        dates = [m.group(2) for m in _LASTMOD.finditer((candidate or b'').decode('utf-8', 'replace'))
                 if m.group(1) == url]
        if len(dates) != 1:
            return None
        return merge_sitemap(base.decode('utf-8') if base else '', [url], dates[0]).encode('utf-8')
    return None


def load_record(run_dir, run_id=None):
    """-> (gates, session). 검증 기록의 꼴과 run_id 를 본다."""
    name = os.path.basename(os.path.normpath(run_dir))
    raw = _read(os.path.join(run_dir, 'gates.json'))
    if raw is None:
        raise Mismatch(f'{run_dir}/gates.json 이 없다 — 다섯 게이트를 다 통과한 검증이 없다')
    try:
        g = json.loads(raw.decode('utf-8'))
    except ValueError:
        raise Mismatch('gates.json 을 읽지 못했다')
    if g.get('verdict') != 'pass':
        raise Mismatch(f'gates.json verdict={g.get("verdict")!r}')
    if g.get('run_id') != name or (run_id is not None and run_id != name):
        raise Mismatch(f'run_id 불일치 — 기록 {g.get("run_id")}, 인자 {run_id}, 폴더 {name}')
    s = g.get('session') or ''
    if not name.startswith(f'jpd-{s}-'):
        raise Mismatch(f'기록의 세션 {s} 이 실행 폴더 {name} 과 다르다')
    return g, s


def verified_inputs(run_dir, g, s):
    """-> (글 바이트, 후보 바이트, 견해 고정 바이트|None). 해시가 하나라도 다르면 Mismatch."""
    from jp_daily_gates import html_path, title_summary
    p = paths(s)
    root = os.path.join(run_dir, 'root')
    html = _read(html_path(run_dir, s))
    cand = _read(os.path.join(root, p['candidate']))
    news = _read(os.path.join(root, p['news']))
    tg = _read(os.path.join(root, p['telegram']))
    bad = []
    if html is None or sha256(html) != g.get('html_sha256'):
        bad.append('조립본')
    if cand is None or sha256(cand) != g.get('snapshot_sha256'):
        bad.append('수집 후보 사본')
    if (sha256(news) if news is not None else None) != g.get('news_sha256'):
        bad.append('뉴스 사본')
    want_tg = g.get('telegram_sha256')
    if want_tg is not None and (tg is None or sha256(tg) != want_tg):
        bad.append('견해 사본')
    if not bad and title_summary(html.decode('utf-8')) != (g.get('title'), g.get('summary')):
        bad.append('제목·요약(조립본의 <title>·description 과 기록이 다르다)')
    if bad:
        raise Mismatch('검증 뒤 바뀌었다: ' + ', '.join(bad))
    return html, cand, (tg if want_tg is not None else None)


def _same_device(a, b):
    return os.stat(a).st_dev == os.stat(b).st_dev


def _put(run_dir, dst, data):
    """`dst` 를 `data` 로 통째로 바꾼다. 임시 파일은 git 이 무시하는 실행 폴더에만 만든다 — 산출물 폴더에 남으면
    다음 시작 가드가 「발행 산출물 밖 미추적 파일」 로 거부한다."""
    tmp = os.path.join(run_dir, '.put.tmp')
    with open(tmp, 'wb') as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dst)


def publish_run(root, run_dir, run_id):
    """-> 바뀐 경로 목록. 쓰기 전에 전부 확인한다."""
    g, s = load_record(run_dir, run_id)
    html, cand_b, pin_b = verified_inputs(run_dir, g, s)
    p = paths(s)
    if os.path.exists(os.path.join(root, p['snapshot'])) or os.path.exists(os.path.join(root, p['post'])):
        raise AlreadyPublished(f'{s} 은 이미 발행됐다(또는 글 파일이 남아 있다) — 고칠 때는 review-gate 정정 경로를 쓴다')
    snap = json.loads(cand_b.decode('utf-8'))
    if snap.get('schema') != 2:
        raise ValueError(f'{s} 수집 후보가 2판(schema 2)이 아니다 — 다시 수집한다')
    if not snap.get('complete') or snap.get('session') != s:
        raise ValueError(f'{s} 수집 후보가 발행할 수 없는 상태다(complete={snap.get("complete")})')
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    snap['published'] = now
    snap_b = _json_bytes(snap)
    runs_b = _json_bytes(dict(g, published_at=now))
    listing_b = _read(os.path.join(root, LISTING))
    entries = json.loads(listing_b.decode('utf-8')) if listing_b else []
    sm = _read(os.path.join(root, SITEMAP))
    out = {p['post']: html, p['snapshot']: snap_b, p['runs']: runs_b,
           HISTORY: _history_bytes(_read(os.path.join(root, HISTORY)), history_row(snap)),
           LISTING: _json_bytes(upsert_entry(entries, listing_entry(g), key='date'), indent=2),
           SITEMAP: merge_sitemap(sm.decode('utf-8') if sm else '', [f'{BASE}/japan/daily/{s}.html'],
                                  datetime.date.today().isoformat()).encode('utf-8')}
    if pin_b is not None:
        out[p['pin']] = pin_b
    changed = [rel for rel, b in out.items() if _read(os.path.join(root, rel)) != b]
    if not _same_device(root, run_dir):
        raise Mismatch(f'실행 폴더 {run_dir} 가 저장소와 다른 장치에 있다 — 산출물을 한 번에 바꿔 넣을 수 없다')
    # ① 쓰기 전에 「무엇을 쓸지」를 남긴다(codex 구현 2회차). 여기서부터 어디서 죽어도 산출물 경로는
    #    origin 판이거나 이 기록의 바이트다 — 다음 실행의 시작 가드가 그것만 보고 되돌린다.
    #    앞 시도의 완료 표식은 먼저 지운다.
    try:
        os.remove(os.path.join(run_dir, 'manifest.txt'))
    except FileNotFoundError:
        pass
    _put(run_dir, os.path.join(run_dir, 'publish.json'),
         _json_bytes({'run_id': g['run_id'], 'session': s, 'html_sha256': sha256(html),
                      'published_snapshot_sha256': sha256(snap_b), 'runs_sha256': sha256(runs_b),
                      'telegram_pin_sha256': sha256(pin_b) if pin_b is not None else None,
                      'news_sha256': g.get('news_sha256'), 'manifest': changed,
                      'written': {rel: sha256(out[rel]) for rel in changed},
                      'entry': listing_entry(g), 'history_row': history_row(snap)}))
    # ② 경로마다 통째로 바꿔 넣는다 — 반쯤 쓰인 파일이 남지 않는다.
    for rel in changed:
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
        _put(run_dir, dst, out[rel])
    # ③ 완료 표식. 이것이 없으면 check-staged·verify-head 가 4 로 끝난다.
    _put(run_dir, os.path.join(run_dir, 'manifest.txt'), ''.join(rel + '\n' for rel in changed).encode('utf-8'))
    return changed


# ── git 쪽 확인 ──────────────────────────────────────────────────────────

def _git(root, *args):
    return subprocess.run(['git', '-C', root, *args], capture_output=True)


def _names(raw):
    return sorted(x for x in raw.decode('utf-8', 'surrogateescape').split('\0') if x)


def _manifest(run_dir):
    with open(os.path.join(run_dir, 'manifest.txt'), encoding='utf-8') as fh:
        return sorted(line.strip() for line in fh if line.strip())


def check_staged(root, run_dir):
    man = _manifest(run_dir)
    r = _git(root, 'diff', '--cached', '--name-only', '-z', '--no-renames')
    if r.returncode:
        raise Mismatch('스테이징 목록을 읽지 못했다')
    staged = _names(r.stdout)
    if staged != man:
        raise Mismatch('스테이징이 manifest 와 다르다 — 더 올라감: ' + (', '.join(sorted(set(staged) - set(man))) or '없음')
                       + ' / 빠짐: ' + (', '.join(sorted(set(man) - set(staged))) or '없음'))


def _blob_at(root, rev, rel):
    if _git(root, 'cat-file', '-e', f'{rev}:{rel}').returncode:
        return None
    r = _git(root, 'show', f'{rev}:{rel}')
    if r.returncode:
        raise Mismatch(f'{rev}:{rel} 을 읽지 못했다')
    return r.stdout


def _head_blob(root, rel):
    return _blob_at(root, 'HEAD', rel)


def verify_head(root, run_dir, remote='origin'):
    g, s = load_record(run_dir)
    with open(os.path.join(run_dir, 'publish.json'), encoding='utf-8') as fh:
        pub = json.load(fh)
    if pub.get('run_id') != g['run_id'] or pub.get('session') != s:
        raise Mismatch('publish.json 이 이 실행의 것이 아니다')
    p, bad = paths(s), []
    subject = _git(root, 'log', '-1', '--format=%s', 'HEAD').stdout.decode('utf-8').strip()
    if subject != f'Add JP daily [{s}]':
        bad.append(f'HEAD 제목 「{subject}」')
    ahead = _git(root, 'rev-list', f'refs/remotes/{remote}/main..HEAD').stdout.decode().split()
    head = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    if ahead != [head]:
        bad.append(f'origin/main 위 로컬 커밋이 {len(ahead)}개다(발행 커밋 하나여야 한다)')
    files = _names(_git(root, 'diff-tree', '--no-commit-id', '-r', '--name-only', '-z', '--no-renames', 'HEAD').stdout)
    if files != _manifest(run_dir):
        bad.append('커밋 경로가 manifest 와 다르다: ' + ', '.join(sorted(set(files) ^ set(_manifest(run_dir)))))
    want = {p['post']: pub.get('html_sha256'), p['snapshot']: pub.get('published_snapshot_sha256'),
            p['runs']: pub.get('runs_sha256'), p['pin']: pub.get('telegram_pin_sha256'),
            p['news']: g.get('news_sha256')}
    blobs = {}
    for rel, h in want.items():
        b = blobs[rel] = _head_blob(root, rel)
        got = sha256(b) if b is not None else None
        if got != h:
            bad.append(f'{rel}: HEAD {got[:12] if got else "없음"} ≠ 기록 {h[:12] if h else "없음"}')
    if pub.get('html_sha256') != g.get('html_sha256'):
        bad.append('publish.json 의 글 해시가 gates.json 과 다르다')
    # 공유 파일: 부모 판에 이 세션 변경만 적용한 바이트와 같아야 한다(codex 구현 1회차 #2 — 다른 세션 항목 삭제·주석 감싸기)
    snap_b = blobs[p['snapshot']]
    row = history_row(json.loads(snap_b.decode('utf-8'))) if snap_b is not None else None
    for rel in (LISTING, HISTORY, SITEMAP):
        got = _head_blob(root, rel)
        try:
            want_b = (expected_shared(rel, _blob_at(root, 'HEAD^', rel), s, listing_entry(g), row, got)
                      if row is not None else None)
        except (ValueError, KeyError, AttributeError) as e:
            want_b = None
            bad.append(f'{rel}: 부모 판을 읽지 못했다({e})')
        if want_b is None or got != want_b:
            bad.append(f'{rel}: 부모 판에 이 세션 변경만 더한 것과 다르다')
    if bad:
        raise Mismatch('HEAD 가 검증 기록과 다르다 — ' + ' / '.join(bad))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('check-staged', 'verify-head'):
        cmd = argv.pop(0)
        ap = argparse.ArgumentParser(prog=f'publish_japan_daily.py {cmd}')
        ap.add_argument('--root', default='.')
        ap.add_argument('--run-dir', required=True)
        args = ap.parse_args(argv)
        try:
            (check_staged if cmd == 'check-staged' else verify_head)(os.path.abspath(args.root), args.run_dir)
        except (Mismatch, OSError, ValueError, KeyError) as e:
            print(f'{cmd}: {e}', file=sys.stderr)
            return 4
        print(f'{cmd}: 검증 기록과 같다')
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--run-id', required=True)
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        changed = publish_run(root, args.run_dir, args.run_id)
    except Mismatch as e:
        print(f'발행 거부 — {e}', file=sys.stderr)
        return 4
    except (AlreadyPublished, ValueError) as e:
        print(e, file=sys.stderr)
        return 2
    print(f'japan/daily — 발행 파일 {len(changed)}개 갱신, manifest {os.path.join(args.run_dir, "manifest.txt")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
