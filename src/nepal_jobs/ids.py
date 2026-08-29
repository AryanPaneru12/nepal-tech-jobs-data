from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NAMESPACE = uuid.UUID("55a45f42-cbd5-4f91-a2e3-665fd125ba16")
TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "ref",
    "referrer",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.encode("idna").decode("ascii").lower()
    port = parts.port
    netloc = (
        host
        if port is None
        or (parts.scheme == "http" and port == 80)
        or (parts.scheme == "https" and port == 443)
        else f"{host}:{port}"
    )
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_PARAMETERS and not key.casefold().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def stable_id(kind: str, *parts: object) -> str:
    material = "|".join(normalize_text(str(part)) for part in parts if part is not None)
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{material}"))


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def domain_from_url(value: str | None) -> str | None:
    normalized = canonical_url(value)
    if not normalized:
        return None
    host = urlsplit(normalized).hostname
    return host.removeprefix("www.") if host else None
