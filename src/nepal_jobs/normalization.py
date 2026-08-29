from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from dateutil import parser as date_parser
from selectolax.parser import HTMLParser

from .ids import canonical_url, domain_from_url, normalize_text
from .models import WorkplaceType


def clean_text(value: str | None, *, max_length: int | None = None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    if "<" in text and ">" in text:
        text = HTMLParser(text).text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:max_length] if max_length else text


def parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = date_parser.parse(str(value))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def infer_workplace(*values: str | None) -> WorkplaceType:
    text = normalize_text(" ".join(value or "" for value in values))
    if re.search(r"\bhybrid\b", text):
        return WorkplaceType.HYBRID
    if re.search(r"\bremote|work from (?:home|anywhere)|distributed\b", text):
        return WorkplaceType.REMOTE
    if re.search(r"\bon[ -]?site|in office\b", text):
        return WorkplaceType.ONSITE
    return WorkplaceType.UNKNOWN


def normalize_employment_type(value: str | None) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    mappings = {
        "full_time": ("full time", "full-time", "full_time", "permanent"),
        "part_time": ("part time", "part-time", "part_time"),
        "contract": ("contract", "contractor", "temporary"),
        "internship": ("intern", "internship", "trainee"),
        "freelance": ("freelance",),
    }
    for canonical, candidates in mappings.items():
        if any(candidate in text for candidate in candidates):
            return canonical
    return text[:50]


def normalize_company_website(value: str | None) -> tuple[str | None, str | None]:
    url = canonical_url(value)
    return url, domain_from_url(url)
