from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

from nepal_jobs.models import (
    CollectionBatch,
    CompanyCandidate,
    DiscoveryLead,
    NepalRelationship,
)

from .base import Collector, required_parameter


class BraveSearchCollector(Collector):
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        if not self.api_key:
            raise RuntimeError("BRAVE_SEARCH_API_KEY is required")
        documents, leads = [], []
        for query in required_parameter(source, "queries"):
            url = f"{str(source.base_url)}?q={quote_plus(query)}&country=NP&count=20"
            document = client.fetch(
                url,
                source,
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            )
            documents.append(document)
            payload = json.loads(document.content)
            for row in payload.get("web", {}).get("results", []):
                leads.append(
                    DiscoveryLead(
                        source_id=source.id,
                        source_url=url,
                        external_id=row.get("url"),
                        title=row.get("title"),
                        candidate_url=row.get("url"),
                        query=query,
                        payload={"description": row.get("description")},
                    )
                )
        return CollectionBatch(leads=leads, documents=documents, full_snapshot=False)


class GooglePlacesIdCollector(Collector):
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        if not self.api_key:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is required")
        documents, leads = [], []
        for query in required_parameter(source, "queries"):
            document = client.fetch(
                str(source.base_url),
                source,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "places.id,nextPageToken",
                },
                json_body={"textQuery": query, "regionCode": "NP"},
            )
            documents.append(document)
            payload = json.loads(document.content)
            for row in payload.get("places", []):
                place_id = row.get("id")
                if place_id:
                    leads.append(
                        DiscoveryLead(
                            source_id=source.id,
                            source_url=str(source.base_url),
                            external_id=place_id,
                            query=query,
                            # Only the durable Place ID and our own query are persisted.
                            payload={"google_place_id": place_id},
                        )
                    )
        return CollectionBatch(leads=leads, documents=documents, full_snapshot=False)


class ManualCsvCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        path = Path(required_parameter(source, "path"))
        if not path.exists():
            raise FileNotFoundError(f"manual import file not found: {path}")
        companies: list[CompanyCandidate] = []
        for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))):
            if not row.get("name"):
                continue
            companies.append(
                CompanyCandidate(
                    source_id=source.id,
                    source_url=row.get("source_url") or str(source.base_url or path.resolve()),
                    external_id=row.get("registration_id") or None,
                    name=row["name"],
                    legal_name=row.get("legal_name") or None,
                    website=row.get("website") or None,
                    careers_url=row.get("careers_url") or None,
                    sectors=[
                        item.strip()
                        for item in (row.get("sectors") or "technology").split("|")
                        if item.strip()
                    ],
                    country=row.get("country") or "Nepal",
                    locality=row.get("locality") or None,
                    address=row.get("address") or None,
                    nepal_relationship=NepalRelationship(row.get("nepal_relationship") or "based"),
                    email=row.get("email") or None,
                    phone=row.get("phone") or None,
                    profile=row.get("profile") or None,
                    confidence=float(row.get("confidence") or 0.9),
                )
            )
        return CollectionBatch(companies=companies, full_snapshot=True)


class HtmlDirectoryCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        url = str(source.base_url)
        document = client.fetch(url, source)
        tree = HTMLParser(document.content)
        p = source.parameters
        companies: list[CompanyCandidate] = []
        for node in tree.css(required_parameter(source, "item_selector")):
            name_node = node.css_first(required_parameter(source, "name_selector"))
            if not name_node:
                continue
            link_node = node.css_first(p.get("website_selector", "a"))
            profile_node = (
                node.css_first(p["profile_selector"]) if p.get("profile_selector") else None
            )
            location_node = (
                node.css_first(p["location_selector"]) if p.get("location_selector") else None
            )
            companies.append(
                CompanyCandidate(
                    source_id=source.id,
                    source_url=url,
                    name=name_node.text(strip=True),
                    website=link_node.attributes.get("href") if link_node else None,
                    profile=profile_node.text(separator=" ", strip=True) if profile_node else None,
                    locality=location_node.text(strip=True) if location_node else None,
                    country="Nepal",
                    nepal_relationship=NepalRelationship.BASED,
                    sectors=p.get("sectors", ["technology"]),
                    confidence=float(p.get("confidence", 0.85)),
                )
            )
        return CollectionBatch(companies=companies, documents=[document], full_snapshot=True)
