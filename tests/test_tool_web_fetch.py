"""tools/web_fetch — SSRF rejection + content extraction.

Network is mocked via monkeypatched DNS resolution and httpx.Client.
We don't hit the real internet from tests.
"""

from __future__ import annotations

import typing

import pytest

from tools import web_fetch
from tools.web_fetch import _is_safe_url, fetch_page

# --- SSRF rejection ----------------------------------------------------------


def _fake_resolve(monkeypatch, ip: str) -> None:
    monkeypatch.setattr(
        web_fetch.socket,
        "getaddrinfo",
        lambda host, _port: [(None, None, None, None, (ip, 0))],
    )


def test_rejects_non_http_schemes():
    assert not _is_safe_url("file:///etc/passwd")
    assert not _is_safe_url("ftp://example.com/")
    assert not _is_safe_url("javascript:alert(1)")


def test_rejects_loopback(monkeypatch):
    _fake_resolve(monkeypatch, "127.0.0.1")
    assert not _is_safe_url("http://localhost/")


def test_rejects_private_ip(monkeypatch):
    _fake_resolve(monkeypatch, "10.0.0.1")
    assert not _is_safe_url("http://internal.example.com/")


def test_rejects_link_local(monkeypatch):
    _fake_resolve(monkeypatch, "169.254.169.254")
    assert not _is_safe_url("http://metadata.google.internal/")


def test_rejects_unresolvable(monkeypatch):
    import socket

    def _raise(host, _port):
        raise socket.gaierror

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", _raise)
    assert not _is_safe_url("http://nothing-here.invalid/")


def test_accepts_public_ip(monkeypatch):
    _fake_resolve(monkeypatch, "8.8.8.8")
    assert _is_safe_url("https://example.com/")


# --- fetch_page integration --------------------------------------------------


def test_fetch_page_returns_none_for_unsafe_url(monkeypatch):
    _fake_resolve(monkeypatch, "127.0.0.1")
    assert fetch_page("http://localhost/") is None


@pytest.fixture
def public_dns(monkeypatch):
    _fake_resolve(monkeypatch, "8.8.8.8")


def test_fetch_page_returns_extracted_text_on_success(monkeypatch, public_dns):
    """Stub httpx.Client to return a tiny HTML body; verify readability returns
    the body text."""
    html = (
        b"<html><head><title>X</title></head>"
        b"<body><article><h1>Real Title</h1>"
        b"<p>This is the article body text used for testing.</p>"
        b"</article></body></html>"
    )

    class _FakeResponse:
        status_code: typing.ClassVar[int] = 200
        headers: typing.ClassVar[dict] = {}
        next_request: typing.ClassVar[None] = None

        def iter_bytes(self, chunk_size: int):
            yield html

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, url, headers=None):
            return _FakeResponse()

        def stream(self, method, url):
            return _FakeResponse()

    monkeypatch.setattr(web_fetch.httpx, "Client", _FakeClient)
    result = fetch_page("https://example.com/article")
    assert result is not None
    assert "article body text" in result.lower()


def test_fetch_page_returns_none_on_network_error(monkeypatch, public_dns):
    import httpx

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, method, url, headers=None):
            raise httpx.ConnectError("boom")

        def stream(self, method, url):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(web_fetch.httpx, "Client", _FakeClient)
    assert fetch_page("https://example.com/x") is None
