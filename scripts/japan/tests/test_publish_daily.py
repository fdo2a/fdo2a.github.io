"""일본 일간 발행 — 수집 후보 → 발행 스냅샷, 이력, 목록, sitemap (설계 §13.7·§13.15)."""
import json
import os

import pytest

import publish_japan_daily as PUB
from japan.tests.test_daily_render import SNAP, S

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')


def _root(tmp_path):
    snap = dict(SNAP, stocks=[{'code': '7203', 'value': 3117.0, 'chg_pct': 0.4}])
    d = tmp_path / 'japan' / 'data' / 'daily' / 'candidate'
    d.mkdir(parents=True)
    (d / f'{S}.json').write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'japan' / 'posts.json').write_text('[{"key": "2026-W42"}]', encoding='utf-8')
    (tmp_path / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '<url><loc>https://fdo2a.github.io/kr/posts/2026-10-26.html</loc><lastmod>2026-10-26</lastmod></url>\n'
        '<url><loc>https://fdo2a.github.io/japan/posts/2026-W42.html</loc><lastmod>2026-10-19</lastmod></url>\n'
        '</urlset>\n', encoding='utf-8')
    return tmp_path


def test_publish_promotes_candidate(tmp_path):
    root = _root(tmp_path)
    PUB.publish(str(root), S, 't', 'h')
    pub = json.loads((root / 'japan' / 'data' / 'daily' / f'{S}.json').read_text(encoding='utf-8'))
    assert pub['session'] == S and pub['published']


def test_publish_appends_history(tmp_path):
    root = _root(tmp_path)
    PUB.publish(str(root), S, 't', 'h')
    rows = [json.loads(l) for l in (root / 'japan' / 'data' / 'history' / 'jp_daily.jsonl').read_text().splitlines()]
    assert rows == [{'session': S, 'nikkei': 62189.65,
                     'prices': {'1306': 418.4, '1631': 37300.0, '7203': 3117.0}}]


def test_publish_keeps_weekly_listing_and_sitemap(tmp_path):
    root = _root(tmp_path)
    PUB.publish(str(root), S, '일본 증시 마감', '헤드라인')
    assert json.loads((root / 'japan' / 'posts.json').read_text()) == [{'key': '2026-W42'}]
    daily = json.loads((root / 'japan' / 'daily.json').read_text(encoding='utf-8'))
    assert daily == [{'date': S, 'title': '일본 증시 마감', 'headline': '헤드라인'}]
    sm = (root / 'sitemap.xml').read_text()
    for url in ('kr/posts/2026-10-26.html', 'japan/posts/2026-W42.html', f'japan/daily/{S}.html'):
        assert url in sm


def test_publish_refuses_second_time(tmp_path):
    root = _root(tmp_path)
    PUB.publish(str(root), S, 't', 'h')
    with pytest.raises(PUB.AlreadyPublished):
        PUB.publish(str(root), S, 't', 'h')


def test_publish_refuses_incomplete(tmp_path):
    root = _root(tmp_path)
    p = root / 'japan' / 'data' / 'daily' / 'candidate' / f'{S}.json'
    snap = json.loads(p.read_text(encoding='utf-8'))
    snap['complete'] = False
    p.write_text(json.dumps(snap), encoding='utf-8')
    with pytest.raises(ValueError):
        PUB.publish(str(root), S, 't', 'h')


def test_index_lists_daily_first_then_weekly():
    with open(os.path.join(ROOT, 'japan', 'index.html'), encoding='utf-8') as fh:
        html = fh.read()
    assert "daily:   { file: 'daily.json'" in html and "weekly:  { file: 'posts.json'" in html
    assert 'data-span="daily"' in html and 'data-span="weekly"' in html
    assert "? 'daily' : 'weekly'" in html and '매주 일요일' not in html.split('<div class="intro">')[1][:200]
