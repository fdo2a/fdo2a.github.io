from us.archives import merge_sitemap, upsert_entry


def test_upsert_adds_a_new_entry_newest_first():
    e = upsert_entry([], {"key": "2026-W34", "title": "t"})
    e = upsert_entry(e, {"key": "2026-W35", "title": "u"})
    assert [x["key"] for x in e] == ["2026-W35", "2026-W34"]


def test_upsert_replaces_rather_than_duplicating():
    e = upsert_entry([], {"key": "2026-W34", "title": "old"})
    e = upsert_entry(e, {"key": "2026-W34", "title": "new"})
    assert len(e) == 1 and e[0]["title"] == "new"


EXISTING = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://fdo2a.github.io/</loc><lastmod>2026-08-21</lastmod><changefreq>daily</changefreq></url>
  <url><loc>https://fdo2a.github.io/thesis/micron.html</loc><lastmod>2026-08-24</lastmod><changefreq>weekly</changefreq></url>
  <url><loc>https://fdo2a.github.io/posts/2026-08-21.html</loc><lastmod>2026-08-21</lastmod></url>
</urlset>"""


def test_merge_keeps_urls_it_was_not_told_about():
    out = merge_sitemap(EXISTING, ["https://fdo2a.github.io/weekly/2026-08-21.html"], "2026-08-22")
    assert "thesis/micron.html" in out
    assert "posts/2026-08-21.html" in out
    assert "https://fdo2a.github.io/" in out


def test_merge_preserves_existing_metadata_on_untouched_urls():
    out = merge_sitemap(EXISTING, ["https://fdo2a.github.io/weekly/2026-08-21.html"], "2026-08-22")
    assert "<loc>https://fdo2a.github.io/thesis/micron.html</loc><lastmod>2026-08-24</lastmod><changefreq>weekly</changefreq>" in out


def test_merge_adds_the_new_url_with_lastmod():
    out = merge_sitemap(EXISTING, ["https://fdo2a.github.io/weekly/2026-08-21.html"], "2026-08-22")
    assert "<loc>https://fdo2a.github.io/weekly/2026-08-21.html</loc><lastmod>2026-08-22</lastmod>" in out


def test_merge_updates_lastmod_of_a_url_it_owns_without_duplicating():
    out = merge_sitemap(EXISTING, ["https://fdo2a.github.io/posts/2026-08-21.html"], "2026-08-25")
    assert out.count("posts/2026-08-21.html") == 1
    assert "<loc>https://fdo2a.github.io/posts/2026-08-21.html</loc><lastmod>2026-08-25</lastmod>" in out


def test_merge_output_is_wellformed_xml():
    import xml.etree.ElementTree as ET
    out = merge_sitemap(EXISTING, ["https://fdo2a.github.io/weekly/2026-08-21.html"], "2026-08-22")
    root = ET.fromstring(out)
    assert root.tag.endswith("urlset")
    assert len(root) == 4


def test_merge_into_an_empty_or_missing_sitemap():
    out = merge_sitemap("", ["https://fdo2a.github.io/weekly/2026-08-21.html"], "2026-08-22")
    import xml.etree.ElementTree as ET
    assert len(ET.fromstring(out)) == 1
