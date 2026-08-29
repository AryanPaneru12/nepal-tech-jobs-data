import socket

import pytest

from nepal_jobs.http import UnsafeUrlError, validate_public_url


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://user:secret@example.com", "ftp://example.com/file"],
)
def test_rejects_unsupported_or_credential_urls(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)


def test_rejects_private_destinations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(UnsafeUrlError, match="non-public"):
        validate_public_url("http://example.test")
