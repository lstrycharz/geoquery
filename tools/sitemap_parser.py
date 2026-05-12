"""sitemap_parser — fetch and parse an XML sitemap into URL entries.

Used by `draft_content_brief` to ground `internal_linking_suggestions` in real
URLs from the user's actual site, rather than LLM-imagined placeholders.

SSRF-hardened (same posture as `tools/web_fetch`). Sitemap indexes are
followed one level deep. The URL count is capped (default 500) to keep the
brief's prompt context manageable; in practice, the drafter selects 3-5 of
these for the brief.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from lxml import etree

from tools.web_fetch import _is_safe_url  # reuse SSRF logic

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15.0
_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_LIMIT = 500


@dataclass(frozen=True)
class SitemapEntry:
    url: str
    title_hint: str  # human-readable slug derived from the URL path


def parse_sitemap(url: str, *, limit: int = _DEFAULT_LIMIT) -> list[SitemapEntry]:
    """Returns up to `limit` SitemapEntry items. Empty list on any failure."""
    if not _is_safe_url(url):
        logger.info("sitemap_parser: rejected unsafe URL %s", url)
        return []

    body = _fetch(url)
    if body is None:
        return []

    entries: list[SitemapEntry] = []
    for loc, is_index in _iter_locs(body):
        if is_index:
            # Recurse one level. Don't recurse further (sitemap indexes of
            # sitemap indexes are rare and we cap defensively).
            entries.extend(parse_sitemap(loc, limit=limit - len(entries)))
        else:
            entries.append(SitemapEntry(url=loc, title_hint=_title_hint(loc)))
        if len(entries) >= limit:
            break
    return entries[:limit]


def _fetch(url: str) -> bytes | None:
    try:
        with (
            httpx.Client(
                follow_redirects=False,
                timeout=httpx.Timeout(_TIMEOUT_SECONDS),
                headers={"User-Agent": "geoquery-agent/0.1"},
            ) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code // 100 != 2:
                return None
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes(chunk_size=65536):
                chunks.append(chunk)
                received += len(chunk)
                if received >= _MAX_BYTES:
                    break
            return b"".join(chunks)
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.info("sitemap_parser: %s for %s", type(e).__name__, url)
        return None


_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _iter_locs(body: bytes):
    """Yields (loc_text, is_index_entry). Handles both <urlset> and <sitemapindex>."""
    try:
        root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False))
    except etree.XMLSyntaxError as e:
        logger.info("sitemap_parser: XML syntax error: %s", e)
        return
    tag = etree.QName(root.tag).localname
    if tag == "sitemapindex":
        for elem in root.findall("sm:sitemap/sm:loc", _NS):
            if elem.text:
                yield (elem.text.strip(), True)
    elif tag == "urlset":
        for elem in root.findall("sm:url/sm:loc", _NS):
            if elem.text:
                yield (elem.text.strip(), False)
    # Other root tags: silently yield nothing.


def _title_hint(url: str) -> str:
    """Derive a human-readable title hint from the URL path. The drafter uses
    this as a starting anchor; it's expected to refine."""
    from urllib.parse import urlparse

    path = urlparse(url).path.strip("/")
    if not path:
        return "Home"
    last_segment = path.split("/")[-1] or path.split("/")[-2]
    return last_segment.replace("-", " ").replace("_", " ").strip().title() or "Page"
