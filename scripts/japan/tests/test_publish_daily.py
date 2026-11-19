"""일본 일간 발행 — 검증 기록이 있는 실행 폴더 → 발행 스냅샷, 이력, 목록, sitemap (설계 §13.7·§13.15, 실행 격리 20판 §6).
git 없이 실행 폴더만 꾸며 발행기 자체를 본다. git·게이트까지 잇는 시험은 test_jpd_publish_run.py."""
import hashlib
import json
import os

import pytest

import build_japan_daily as B
import publish_japan_daily as PUB
from japan.tests.test_daily_render import SNAP, S

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')
PAGE = ('<!DOCTYPE html>\n<html><head>\n<title>일본 증시 마감</title>\n'
        '<meta name="description" content="헤드라인">\n</head><body></body></html>\n')
TG = {'report_date': S, 'market': 'jp', 'usable': True, 'items': [{'id': 'c/1', 'summary_ko': '요약'}]}


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _root(tmp_path, snap=None, tg=TG):
    snap = dict(SNAP, schema=2, stocks=[{'code': '7203', 'value': 3117.0, 'chg_pct': 0.4}]) if snap is None else snap
    (tmp_path / 'japan').mkdir()
    (tmp_path / 'japan' / 'posts.json').write_text('[{"key": "2026-W42"}]', encoding='utf-8')
    (tmp_path / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '<url><loc>https://fdo2a.github.io/kr/posts/2026-10-26.html</loc><lastmod>2026-10-26</lastmod></url>\n'
        '<url><loc>https://fdo2a.github.io/japan/posts/2026-W42.html</loc><lastmod>2026-10-19</lastmod></url>\n'
        '</urlset>\n', encoding='utf-8')
    d = tmp_path / '_workspace' / 'jpd' / f'jpd-{S}-1-1'
    files = {f'japan/data/daily/candidate/{S}.json': json.dumps(snap, ensure_ascii=False).encode()}
    if tg is not None:
        files[f'japan/data/telegram/{S}.json'] = json.dumps(tg, ensure_ascii=False).encode()
    for rel, b in files.items():
        p = d / 'root' / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    (d / f'jpd_{S}.html').write_text(PAGE, encoding='utf-8')
    tgb = files.get(f'japan/data/telegram/{S}.json')
    (d / 'gates.json').write_text(json.dumps({
        'run_id': d.name, 'session': S, 'html_sha256': _sha(PAGE.encode()),
        'snapshot_sha256': _sha(files[f'japan/data/daily/candidate/{S}.json']), 'news_sha256': None,
        'telegram_sha256': _sha(tgb) if tgb and tg.get('usable') else None, 'title': '일본 증시 마감',
        'summary': '헤드라인', 'gates': [], 'verdict': 'pass', 'finished_at': 'x'}), encoding='utf-8')
    return tmp_path, d


def _publish(root, d):
    return PUB.main(['--root', str(root), '--run-dir', str(d), '--run-id', d.name])


def test_publish_promotes_candidate(tmp_path):
    root, d = _root(tmp_path)
    assert _publish(root, d) == 0
    pub = json.loads((root / 'japan' / 'data' / 'daily' / f'{S}.json').read_text(encoding='utf-8'))
    assert pub['session'] == S and pub['published']


def test_publish_appends_history_without_etf_codes_for_schema_2(tmp_path):
    root, d = _root(tmp_path)
    _publish(root, d)
    rows = [json.loads(l) for l in (root / 'japan' / 'data' / 'history' / 'jp_daily.jsonl').read_text().splitlines()]
    assert rows == [{'session': S, 'nikkei': 62189.65, 'prices': {'7203': 3117.0}}]


def test_old_schema_history_row_is_unchanged():
    snap = dict(SNAP, stocks=[{'code': '7203', 'value': 3117.0, 'chg_pct': 0.4}])
    assert PUB.history_row(snap) == {'session': S, 'nikkei': 62189.65,
                                     'prices': {'1306': 418.4, '1631': 37300.0, '7203': 3117.0}}


def test_publish_keeps_weekly_listing_and_sitemap(tmp_path):
    root, d = _root(tmp_path)
    _publish(root, d)
    assert json.loads((root / 'japan' / 'posts.json').read_text()) == [{'key': '2026-W42'}]
    daily = json.loads((root / 'japan' / 'daily.json').read_text(encoding='utf-8'))
    assert daily == [{'date': S, 'title': '일본 증시 마감', 'headline': '헤드라인'}]
    sm = (root / 'sitemap.xml').read_text()
    for url in ('kr/posts/2026-10-26.html', 'japan/posts/2026-W42.html', f'japan/daily/{S}.html'):
        assert url in sm


def test_publish_refuses_second_time(tmp_path):
    root, d = _root(tmp_path)
    assert _publish(root, d) == 0
    assert _publish(root, d) == 2


def test_publish_refuses_incomplete(tmp_path):
    root, d = _root(tmp_path, snap=dict(SNAP, schema=2, complete=False))
    assert _publish(root, d) == 2
    assert not (root / 'japan' / 'data' / 'daily' / f'{S}.json').exists()


def test_published_post_reads_the_pin_not_the_collector_file(tmp_path):
    root, d = _root(tmp_path)
    assert _publish(root, d) == 0
    pin = root / 'japan' / 'data' / 'telegram' / 'published' / f'{S}.json'
    assert pin.read_bytes() == (d / 'root' / 'japan' / 'data' / 'telegram' / f'{S}.json').read_bytes()
    (root / 'japan' / 'data' / 'telegram').mkdir(exist_ok=True)
    (root / 'japan' / 'data' / 'telegram' / f'{S}.json').write_text(json.dumps(dict(TG, items=[])), encoding='utf-8')
    assert B.telegram_path(root, S) == pin and B.load_telegram(root, S)[0]['items'][0]['id'] == 'c/1'


def test_no_record_is_exit_4(tmp_path):
    root, d = _root(tmp_path)
    (d / 'gates.json').unlink()
    assert _publish(root, d) == 4 and not (root / 'japan' / 'daily.json').exists()


def test_index_lists_daily_first_then_weekly():
    with open(os.path.join(ROOT, 'japan', 'index.html'), encoding='utf-8') as fh:
        html = fh.read()
    assert "daily:   { file: 'daily.json'" in html and "weekly:  { file: 'posts.json'" in html
    assert 'data-span="daily"' in html and 'data-span="weekly"' in html
    assert "? 'daily' : 'weekly'" in html and '매주 일요일' not in html.split('<div class="intro">')[1][:200]
