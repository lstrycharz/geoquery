"""web_fetch — SSRF-hardened page fetcher with readability extraction.

Used by `agent.py` to populate `SerpResult.extracted_content` on the top-3
SERP results before they reach `analyze_serp`. The skill's prompt already
expects this field to be either content or None, so this is purely additive.

Security (per global security rules):
- scheme whitelist: http/https only
- DNS-resolution SSRF check — resolves the hostname and rejects any private,
  loopback, link-local, reserved, or multicast IP
- redirect follow disabled — each redirect target is re-validated through
  the same SSRF check
- streaming response with a 5MB size cap (no full-body download then truncate)
- 10s timeout end-to-end
- 1 final redirect hop max

Returns extracted body content (readability) on success; None on any failure
(timeout, SSRF reject, non-2xx, empty extraction). Never raises — callers
treat None as "we tried, nothing usable came back."
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx
from readability import Document

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024  # 5 MB
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 1


def _is_safe_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname or ""
    if not hostname:
        return False
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    return all(_is_safe_ip(r[4][0]) for r in results)


def _fetch_with_size_cap(client: httpx.Client, url: str) -> bytes | None:
    """Stream the body up to MAX_BYTES; bail at the cap. Returns None on
    non-2xx or any network error."""
    try:
        with client.stream("GET", url) as response:
            if response.status_code // 100 != 2:
                logger.info("web_fetch: non-2xx status %s for %s", response.status_code, url)
                return None
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes(chunk_size=65536):
                chunks.append(chunk)
                received += len(chunk)
                if received >= MAX_BYTES:
                    break
            return b"".join(chunks)
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.info("web_fetch: %s while fetching %s", type(e).__name__, url)
        return None


def fetch_page(url: str) -> str | None:
    """Fetch one page and return readability-extracted body text, or None.

    SSRF-hardened. Never raises. Suitable for use against user-supplied URLs
    (including URLs that came back from a SERP).
    """
    if not _is_safe_url(url):
        logger.info("web_fetch: rejected unsafe URL %s", url)
        return None

    redirects_followed = 0
    current_url = url
    with httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        headers={"User-Agent": "geoquery-agent/0.1 (+https://github.com/)"},
    ) as client:
        while True:
            # Re-validate on each hop (the initial check covered the first URL).
            if redirects_followed > 0 and not _is_safe_url(current_url):
                logger.info("web_fetch: rejected unsafe redirect to %s", current_url)
                return None
            try:
                head = client.request("GET", current_url, headers={"Range": "bytes=0-0"})
            except (httpx.HTTPError, httpx.TimeoutException):
                return None
            if head.status_code in (301, 302, 303, 307, 308):
                if redirects_followed >= MAX_REDIRECTS:
                    return None
                next_url = head.headers.get("location")
                if not next_url:
                    return None
                # httpx resolves relative redirects via response.next_request
                current_url = str(head.next_request.url) if head.next_request else next_url
                redirects_followed += 1
                continue
            break

        body = _fetch_with_size_cap(client, current_url)
        if body is None:
            return None

    try:
        # readability expects str input; decode permissively (HTML is utf-8 in
        # practice but charset-detection is the readability library's job).
        body_text = body.decode("utf-8", errors="replace")
        doc = Document(body_text)
        summary_html = doc.summary(html_partial=True)
    except Exception as e:  # readability can blow up on malformed HTML
        logger.info("web_fetch: readability failed on %s: %s", url, e)
        return None

    text = _strip_tags(summary_html)
    return text or None


def _strip_tags(html: str) -> str:
    """Very simple tag stripper. We don't need full text-rendering fidelity;
    just enough that the downstream LLM can read the page's substance."""
    from lxml import etree
    from lxml import html as lxml_html

    try:
        root = lxml_html.fromstring(html)
    except (etree.ParserError, ValueError):
        return ""
    return " ".join(root.text_content().split())
