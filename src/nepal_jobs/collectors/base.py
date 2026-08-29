from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from nepal_jobs.http import SafeHttpClient
from nepal_jobs.models import CollectionBatch, FetchedDocument, SourceDefinition


class Collector(ABC):
    @abstractmethod
    def collect(self, client: SafeHttpClient, source: SourceDefinition) -> CollectionBatch:
        raise NotImplementedError

    def discover(self, client: SafeHttpClient, source: SourceDefinition) -> CollectionBatch:
        return self.collect(client, source)

    @staticmethod
    def json(document: FetchedDocument) -> Any:
        return json.loads(document.content.decode("utf-8-sig"))


def required_parameter(source: SourceDefinition, key: str) -> Any:
    if key not in source.parameters:
        raise ValueError(f"source {source.id!r} requires parameter {key!r}")
    return source.parameters[key]
