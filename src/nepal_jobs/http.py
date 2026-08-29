from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import Lock
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .models import FetchedDocument, SourceDefinition
from .progress import ProgressCallback


class UnsafeUrlError(ValueError):
    pass


class ResponseTooLargeError(RuntimeError):
    pass


def validate_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UnsafeUrlError(f"unsupported URL: {url}")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in URLs are forbidden")
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"host cannot be resolved: {parts.hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise UnsafeUrlError(f"non-public destination rejected: {ip}")


@dataclass(slots=True)
class CacheValidators:
    etag: str | None = None
    last_modified: str | None = None


class SafeHttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 30,
        max_response_bytes: int = 10_000_000,
        retries: int = 3,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.retries = retries
        self.progress = progress
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        )
        self._host_last_request: dict[str, float] = {}
        self._lock = Lock()
        self._robots: dict[str, RobotFileParser] = {}
        self._request_count = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SafeHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(
        self,
        url: str,
        source: SourceDefinition,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        validators: CacheValidators | None = None,
    ) -> FetchedDocument:
        self._request_count += 1
        request_number = self._request_count
        started = time.monotonic()
        self._emit(
            "fetch_started",
            {
                "source": source.id,
                "request": request_number,
                "method": method,
                "url": _display_url(url),
            },
        )
        validate_public_url(url)
        if source.obey_robots and source.access_mode in {"html", "feed"}:
            self._assert_robots(url)
        request_headers = dict(headers or {})
        if validators and validators.etag:
            request_headers["If-None-Match"] = validators.etag
        if validators and validators.last_modified:
            request_headers["If-Modified-Since"] = validators.last_modified

        current_url = url
        for redirect_count in range(6):
            self._rate_limit(current_url, source.requests_per_minute)
            response = self._request_with_retries(
                method, current_url, headers=request_headers, json=json_body
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_count == 5 or "location" not in response.headers:
                    raise RuntimeError(f"redirect limit exceeded for {url}")
                current_url = urljoin(current_url, response.headers["location"])
                validate_public_url(current_url)
                if response.status_code == 303:
                    method, json_body = "GET", None
                continue
            response.raise_for_status()
            content = self._read_limited(response)
            self._emit(
                "fetch_completed",
                {
                    "source": source.id,
                    "request": request_number,
                    "status": response.status_code,
                    "bytes": len(content),
                    "elapsed_seconds": time.monotonic() - started,
                },
            )
            return FetchedDocument(
                source_id=source.id,
                url=current_url,
                fetched_at=datetime.now(UTC),
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                content=content,
            )
        raise RuntimeError(f"failed to fetch {url}")

    def _request_with_retries(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code not in {429, 500, 502, 503, 504}:
                    return response
                retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                delay = min(retry_after if retry_after is not None else 2**attempt, 30)
                self._emit(
                    "fetch_retry",
                    {
                        "attempt": attempt + 1,
                        "status": response.status_code,
                        "wait_seconds": delay,
                        "url": _display_url(url),
                    },
                )
                time.sleep(delay)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                delay = min(2**attempt, 10)
                self._emit(
                    "fetch_retry",
                    {
                        "attempt": attempt + 1,
                        "error": type(exc).__name__,
                        "wait_seconds": delay,
                        "url": _display_url(url),
                    },
                )
                time.sleep(delay)
        if last_error:
            raise last_error
        return response

    def _read_limited(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared and int(declared) > self.max_response_bytes:
            raise ResponseTooLargeError(
                f"declared response exceeds {self.max_response_bytes} bytes"
            )
        content = response.content
        if len(content) > self.max_response_bytes:
            raise ResponseTooLargeError(f"response exceeds {self.max_response_bytes} bytes")
        return content

    def _rate_limit(self, url: str, requests_per_minute: int) -> None:
        host = urlsplit(url).hostname or ""
        interval = 60 / requests_per_minute
        with self._lock:
            now = time.monotonic()
            wait = interval - (now - self._host_last_request.get(host, 0))
            if wait > 0:
                if wait >= 0.5:
                    self._emit(
                        "rate_limit_wait",
                        {"host": host, "wait_seconds": wait},
                    )
                time.sleep(wait)
            self._host_last_request[host] = time.monotonic()

    def _assert_robots(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            robots_url = f"{origin}/robots.txt"
            self._emit("robots_check", {"url": robots_url})
            validate_public_url(robots_url)
            parser = RobotFileParser(robots_url)
            try:
                response = self._client.get(robots_url)
                if response.status_code < 400:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])
            except httpx.HTTPError:
                raise RuntimeError(f"robots.txt could not be checked for {origin}") from None
            self._robots[origin] = parser
        if not parser.can_fetch(self.user_agent, url):
            raise PermissionError(f"robots.txt disallows {url}")

    def _emit(self, event: str, fields: dict[str, object]) -> None:
        if self.progress:
            self.progress(event, fields)


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            return max((target - datetime.now(UTC)).total_seconds(), 0)
        except (TypeError, ValueError):
            return None


def _display_url(url: str) -> str:
    return url if len(url) <= 180 else f"{url[:177]}..."
