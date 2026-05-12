"""tools/sitemap_parser — urlset, sitemapindex, SSRF rejection, malformed XML."""

from __future__ import annotations

from tools import sitemap_parser, web_fetch
from tools.sitemap_parser import _title_hint, parse_sitemap

_URLSET = b"""<?xml version='1.0' encoding='UTF-8'?>
<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
  <url><loc>https://example.com/blog/post-one</loc></url>
  <url><loc>https://example.com/guides/setup</loc></url>
  <url><loc>https://example.com/</loc></url>
</urlset>"""

_INDEX = b"""<?xml version='1.0' encoding='UTF-8'?>
<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
  <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
</sitemapindex>"""


def _fake_resolve_public(monkeypatch):
    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda host, _port: [(None, None, None, None, ("8.8.8.8", 0))],
    )


def _stub_fetch(monkeypatch, payload_by_url: dict[str, bytes]):
    def _fake(url: str) -> bytes | None:
        return payload_by_url.get(url)

    monkeypatch.setattr(sitemap_parser, "_fetch", _fake)


def test_parses_urlset(monkeypatch):
    _fake_resolve_public(monkeypatch)
    _stub_fetch(monkeypatch, {"https://example.com/sitemap.xml": _URLSET})

    entries = parse_sitemap("https://example.com/sitemap.xml")
    assert [e.url for e in entries] == [
        "https://example.com/blog/post-one",
        "https://example.com/guides/setup",
        "https://example.com/",
    ]
    assert entries[0].title_hint == "Post One"
    assert entries[1].title_hint == "Setup"
    assert entries[2].title_hint == "Home"


def test_recurses_one_level_into_index(monkeypatch):
    _fake_resolve_public(monkeypatch)
    _stub_fetch(
        monkeypatch,
        {
            "https://example.com/sitemap.xml": _INDEX,
            "https://example.com/sitemap-blog.xml": _URLSET,
        },
    )
    entries = parse_sitemap("https://example.com/sitemap.xml")
    assert len(entries) == 3


def test_respects_limit(monkeypatch):
    _fake_resolve_public(monkeypatch)
    _stub_fetch(monkeypatch, {"https://example.com/sitemap.xml": _URLSET})
    entries = parse_sitemap("https://example.com/sitemap.xml", limit=2)
    assert len(entries) == 2


def test_rejects_unsafe_url(monkeypatch):
    # default DNS resolves localhost -> 127.0.0.1, so this should reject.
    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda host, _port: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    assert parse_sitemap("http://localhost/sitemap.xml") == []


def test_returns_empty_on_malformed_xml(monkeypatch):
    _fake_resolve_public(monkeypatch)
    _stub_fetch(monkeypatch, {"https://example.com/sitemap.xml": b"<<<not xml"})
    assert parse_sitemap("https://example.com/sitemap.xml") == []


def test_title_hint_from_complex_path():
    assert _title_hint("https://example.com/category/sub-category/my-article-name/") == (
        "My Article Name"
    )
