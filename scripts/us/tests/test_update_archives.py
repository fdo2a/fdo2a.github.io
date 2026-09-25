"""update_archives.py — 목록 JSON 갱신과 sitemap 병합 (daily·news 는 2026-09-26)."""
import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(__file__), '..', '..', 'update_archives.py')
OTHER = 'https://fdo2a.github.io/weekly/2026-W38.html'


def run(root, *args):
    subprocess.run([sys.executable, SCRIPT, '--root', str(root), *args], check=True,
                   capture_output=True)


def seed(root):
    (root / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{OTHER}</loc><lastmod>2026-09-20</lastmod></url>\n</urlset>\n', encoding='utf-8')
    (root / 'posts.json').write_text(json.dumps(
        [{'date': '2026-09-24', 'title': 'old', 'headline': 'h'}], ensure_ascii=False), encoding='utf-8')


def test_daily_keeps_the_date_field_and_replaces_the_same_day(tmp_path):
    seed(tmp_path)
    run(tmp_path, '--kind', 'daily', '--key', '2026-09-24', '--title', 'new', '--headline', 'h2')
    run(tmp_path, '--kind', 'daily', '--key', '2026-09-25', '--title', 't', '--headline', 'h3')
    rows = json.loads((tmp_path / 'posts.json').read_text(encoding='utf-8'))
    assert [(r['date'], r['title']) for r in rows] == [('2026-09-25', 't'), ('2026-09-24', 'new')]
    assert all('key' not in r for r in rows)          # index.html 은 date 로 읽는다


def test_daily_and_news_merge_the_sitemap_instead_of_regenerating_it(tmp_path):
    seed(tmp_path)
    run(tmp_path, '--kind', 'daily', '--key', '2026-09-25', '--title', 't')
    run(tmp_path, '--kind', 'news', '--key', '2026-09-25', '--title', 'n')
    sitemap = (tmp_path / 'sitemap.xml').read_text(encoding='utf-8')
    for loc in (OTHER, 'https://fdo2a.github.io/posts/2026-09-25.html',
                'https://fdo2a.github.io/news/2026-09-25.html'):
        assert sitemap.count(f'<loc>{loc}</loc>') == 1, loc
    news = json.loads((tmp_path / 'news.json').read_text(encoding='utf-8'))
    assert news == [{'key': '2026-09-25', 'title': 'n', 'headline': ''}]
