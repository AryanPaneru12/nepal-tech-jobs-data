from __future__ import annotations

from pathlib import Path

import yaml

from .models import SourceDefinition


class SourceCatalog:
    def __init__(self, source_dir: Path):
        self.source_dir = source_dir

    def load(self) -> dict[str, SourceDefinition]:
        sources: dict[str, SourceDefinition] = {}
        if not self.source_dir.exists():
            return sources
        for path in sorted(self.source_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            source = SourceDefinition.model_validate(payload)
            if source.id in sources:
                raise ValueError(f"duplicate source id {source.id!r} in {path}")
            sources[source.id] = source
        return sources

    def get(self, source_id: str) -> SourceDefinition:
        sources = self.load()
        try:
            return sources[source_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown source {source_id!r}; available: {', '.join(sources)}"
            ) from exc

    def check(self) -> list[str]:
        errors: list[str] = []
        try:
            sources = self.load()
        except Exception as exc:
            return [str(exc)]
        if not sources:
            errors.append("no source definitions found")
        for source in sources.values():
            if source.enabled and source.access_mode == "blocked":
                errors.append(f"{source.id}: blocked source cannot be enabled")
            if (
                source.enabled
                and not source.base_url
                and source.access_mode not in {"manual", "search"}
            ):
                errors.append(f"{source.id}: enabled source requires base_url")
            if source.redistribution.value == "unknown" and source.enabled:
                errors.append(f"{source.id}: redistribution must be reviewed before enabling")
        return errors
