from __future__ import annotations

from nepal_jobs.models import SourceDefinition
from nepal_jobs.settings import Settings

from .ats import AshbyCollector, GreenhouseCollector, LeverCollector
from .base import Collector
from .discovery import (
    BraveSearchCollector,
    GooglePlacesIdCollector,
    HtmlDirectoryCollector,
    ManualCsvCollector,
)
from .remote_feeds import HimalayasCollector, RemoteOkCollector, RemotiveCollector

COLLECTORS: dict[str, type[Collector]] = {
    "ashby": AshbyCollector,
    "greenhouse": GreenhouseCollector,
    "himalayas": HimalayasCollector,
    "html_directory": HtmlDirectoryCollector,
    "lever": LeverCollector,
    "manual_csv": ManualCsvCollector,
    "remoteok": RemoteOkCollector,
    "remotive": RemotiveCollector,
}


def create_collector(source: SourceDefinition, settings: Settings) -> Collector:
    if source.connector == "brave_search":
        return BraveSearchCollector(settings.brave_api_key)
    if source.connector == "google_places_id":
        return GooglePlacesIdCollector(settings.google_places_api_key)
    try:
        return COLLECTORS[source.connector]()
    except KeyError as exc:
        raise ValueError(
            f"unknown connector {source.connector!r} for source {source.id!r}"
        ) from exc
